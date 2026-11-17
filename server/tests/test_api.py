"""API tests for the demo portal (fictional data only).

Run from the repo root:   python -m pytest server/tests -q
Each render launches headless Chromium, so the suite takes about half a minute.
"""
import datetime
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "samples"))

import main  # noqa: E402
from make_samples import make_quote, make_slip  # noqa: E402

client = TestClient(main.app)


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    d = tmp_path_factory.mktemp("inputs")
    slip, quote = d / "slip.xlsx", d / "quote.xlsx"
    make_slip(slip)
    make_quote(quote)
    unknown = d / "unknown.xlsx"
    make_slip(unknown, name="NOT A KNOWN COMPANY LTD", gstin="27AAAAA0000A1Z5", start=datetime.datetime(2030, 1, 1))
    other_quote = d / "other_quote.xlsx"
    make_quote(other_quote, name="SOMETHING ELSE ENTIRELY LIMITED")
    return {"slip": slip, "quote": quote, "unknown": unknown, "other_quote": other_quote}


def analyze(slip, quote, slip_name="slip.xlsx", quote_name="quote.xlsx"):
    with open(slip, "rb") as a, open(quote, "rb") as b:
        return client.post("/api/analyze", files={"closing_slip": (slip_name, a), "quote": (quote_name, b)})


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200 and "demo_laghu" in r.json()["cases"]


def test_analyze_reports_captured_and_missing(files):
    r = analyze(files["slip"], files["quote"])
    assert r.status_code == 200
    d = r.json()
    assert {"fields", "addons", "sections", "terms", "groups", "warnings"} <= set(d)
    assert [x["no"] for x in d["sections"] if x["opted"]] == [1, 3, 7]
    by = {f["key"]: f for f in d["fields"]}
    assert by["insured.name"]["status"] == "ok" and by["insured.name"]["source"] == "Closing slip"
    assert by["period.start"]["status"] == "ok"
    assert by["premium.final"]["status"] == "ok"
    for k in ("system.policy_no", "system.gst_invoice_no", "system.magma_gstin", "system.stamp_duty.order_no"):
        assert by[k]["status"] == "missing" and by[k]["suggestion"], k
    assert not any("same insured" in w for w in d["warnings"])


def test_quote_for_other_insured_warns(files):
    d = analyze(files["slip"], files["other_quote"]).json()
    assert d["warnings"], "a quote that does not mention the insured must raise a warning"


def test_unknown_insured_is_analysed_without_sample_suggestions(files):
    r = analyze(files["unknown"], files["quote"])
    assert r.status_code == 200
    d = r.json()
    assert d["summary"]["insured"] == "NOT A KNOWN COMPANY LTD"
    assert not any(f["suggestion"] for f in d["fields"])


def test_workbook_without_closing_slip_is_refused(files):
    r = analyze(files["quote"], files["quote"])
    assert r.status_code == 422 and r.json()["error"] == "unsupported"


def test_non_excel_rejected(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("hello")
    with open(p, "rb") as a, open(p, "rb") as b:
        r = client.post("/api/analyze", files={"closing_slip": ("x.txt", a), "quote": ("y.txt", b)})
    assert r.status_code == 400


def test_render_requires_blank_acknowledgement_then_renders(files):
    sid = analyze(files["slip"], files["quote"]).json()["sessionId"]
    blocked = client.post("/api/render", json={"sessionId": sid, "values": {}})
    assert blocked.status_code == 409 and blocked.json()["error"] == "blanks" and len(blocked.json()["blanks"]) >= 8

    ok = client.post("/api/render", json={"sessionId": sid, "values": {}, "allowBlanks": True})
    assert ok.status_code == 200
    j = ok.json()
    assert j["pages"] >= 5 and len(j["blanks"]) >= 8
    pdf = client.get(f"/api/pdf/{j['token']}")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    png = client.get(f"/api/page/{j['token']}/1")
    assert png.status_code == 200 and png.content.startswith(b"\x89PNG")
    assert client.get(f"/api/page/{j['token']}/999").status_code == 404
    assert client.delete(f"/api/pdf/{j['token']}").status_code == 200
    assert client.get(f"/api/pdf/{j['token']}").status_code == 404


def test_fully_filled_render_has_no_blanks_and_policy_number_in_pdf(files):
    import fitz
    a = analyze(files["slip"], files["quote"]).json()
    values = {f["key"]: f["suggestion"] for f in a["fields"] if f["suggestion"]}
    r = client.post("/api/render", json={"sessionId": a["sessionId"], "values": values})
    assert r.status_code == 200 and r.json()["blanks"] == []
    pdf = client.get(f"/api/pdf/{r.json()['token']}").content
    text = "".join(p.get_text() for p in fitz.open(stream=pdf, filetype="pdf"))
    assert "P0099900001/9999/900001" in text and "ACME PRECISION PRODUCTS" in text and "29,688.80" in text


def test_user_value_overrides_sample(files):
    import fitz
    a = analyze(files["slip"], files["quote"]).json()
    values = {f["key"]: f["suggestion"] for f in a["fields"] if f["suggestion"]}
    values["system.policy_no"] = "P0000000000/0000/000000"
    r = client.post("/api/render", json={"sessionId": a["sessionId"], "values": values})
    pdf = client.get(f"/api/pdf/{r.json()['token']}").content
    text = "".join(p.get_text() for p in fitz.open(stream=pdf, filetype="pdf"))
    assert "P0000000000/0000/000000" in text and "P0099900001/9999/900001" not in text


def test_expired_session():
    r = client.post("/api/render", json={"sessionId": "nope", "values": {}})
    assert r.status_code == 404


# ---------------------------------------------------------------- add-ons, sections, terms (synthetic clause library)
TITLES = ["Start Up Expenses", "Fire Brigade Charges", "Agreed Bank Clause"]


@pytest.fixture
def library(monkeypatch):
    from extractor.clausebank import api as cb
    from extractor.clausebank.common import fullkey, norm
    from extractor.clausebank.resolve import Index
    idx = Index({"clauses": [{"title": t, "key": fullkey(t), "nkey": norm(t), "source": "master", "wording": ""} for t in TITLES]})
    monkeypatch.setattr(cb, "load_library", lambda path=None: idx)
    monkeypatch.setattr(cb, "load_aliases", lambda path=None: {})
    monkeypatch.setattr(cb, "wording_ids", lambda path=None: {})
    return idx


@pytest.fixture
def addon_files(files, tmp_path):
    import openpyxl
    q = tmp_path / "q_addons.xlsx"
    wb = openpyxl.load_workbook(files["quote"])
    ws = wb.create_sheet("Add-ons")
    ws.append(["Add-on Covers", "Limit", "Magma Remarks"])
    ws.append(["Start Up Expenses", "5% of TSI", "Covered"])
    ws.append(["Fire Brigade Charges", "1 cr", "Covered"])
    ws.append(["Something Unheard Of", "", "Covered"])
    ws.append(["Agreed Bank Clause", "", "Not covered"])
    wb.save(q)
    return files["slip"], q


def test_addon_rows_are_returned_with_status(library, addon_files):
    r = analyze(*addon_files).json()
    by = {a["name"]: a for a in r["addons"]}
    assert by["Start Up Expenses"]["status"] == "ok" and by["Start Up Expenses"]["clause"] == "Start Up Expenses"
    assert by["Something Unheard Of"]["status"] == "missing" and by["Something Unheard Of"]["clause"] is None
    assert by["Agreed Bank Clause"]["status"] == "dropped" and by["Agreed Bank Clause"]["include"] is False


def test_unresolved_kept_addon_counts_as_blank_until_resolved(library, addon_files):
    a = analyze(*addon_files).json()
    values = {f["key"]: f["suggestion"] for f in a["fields"] if f["suggestion"]}
    edits = [{"id": x["id"], "include": x["include"], "clause": x["clause"], "name": x["name"], "limit": x["limit"], "printAsQuoted": False} for x in a["addons"]]
    r = client.post("/api/render", json={"sessionId": a["sessionId"], "values": values, "addons": edits})
    assert r.status_code == 409 and any(b["group"] == "Add-on covers" for b in r.json()["blanks"])
    for e in edits:
        if e["name"] == "Something Unheard Of":
            e["printAsQuoted"] = True
    r = client.post("/api/render", json={"sessionId": a["sessionId"], "values": values, "addons": edits})
    assert r.status_code == 200 and not any(b["group"] == "Add-on covers" for b in r.json()["blanks"])


def test_edits_reach_the_pdf(library, addon_files):
    import fitz
    a = analyze(*addon_files).json()
    values = {f["key"]: f["suggestion"] for f in a["fields"] if f["suggestion"]}
    edits = [{"id": x["id"], "include": x["name"] != "Fire Brigade Charges" and x["decision"] == "keep", "clause": x["clause"], "name": x["name"], "limit": x["limit"],
              "printAsQuoted": x["name"] == "Something Unheard Of"} for x in a["addons"]]
    edits.append({"id": None, "include": True, "name": "Added Cover Xyz", "printAsQuoted": True, "limit": "2 cr"})
    terms = a["terms"]
    terms["allLines"] = ["Edited all-sections line Qwerty"]
    secs = [{"no": s["no"], "sumInsured": s["sumInsured"], "premium": s["premium"]} for s in a["sections"]]
    r = client.post("/api/render", json={"sessionId": a["sessionId"], "values": values, "addons": edits, "terms": terms, "sections": secs})
    assert r.status_code == 200
    text = "".join(p.get_text() for p in fitz.open(stream=client.get(f"/api/pdf/{r.json()['token']}").content, filetype="pdf"))
    assert "Start Up Expenses" in text and "Added Cover Xyz" in text and "Fire Brigade Charges" not in text
    assert "Qwerty" in text


def test_section_edit_changes_the_schedule(library, files):
    import fitz
    a = analyze(files["slip"], files["quote"]).json()
    values = {f["key"]: f["suggestion"] for f in a["fields"] if f["suggestion"]}
    secs = [{"no": s["no"], "sumInsured": 123456789 if s["no"] == 1 else s["sumInsured"], "premium": s["premium"]} for s in a["sections"]]
    r = client.post("/api/render", json={"sessionId": a["sessionId"], "values": values, "sections": secs})
    text = "".join(p.get_text() for p in fitz.open(stream=client.get(f"/api/pdf/{r.json()['token']}").content, filetype="pdf"))
    assert "123,456,789" in text


def test_clause_list_endpoint(library):
    assert client.get("/api/clauses").json()["clauses"] == sorted(TITLES)


# ---------------------------------------------------------------- backend test APIs (/api/extract/*)
def _upload(path, slip, quote, **kw):
    with open(slip, "rb") as a, open(quote, "rb") as b:
        return client.post(path, files={"closing_slip": ("s.xlsx", a), "quote": ("q.xlsx", b)}, **kw)


def test_extract_fields_sections_case(files):
    f = _upload("/api/extract/fields", files["slip"], files["quote"]).json()
    by = {x["field"]: x for x in f["fields"]}
    assert by["insured.name"]["status"] == "ok" and by["premium.final"]["source"]["tool"] == "quote"
    s = _upload("/api/extract/sections", files["slip"], files["quote"]).json()
    assert s["layout"] == "laghu" and s["tie"] and [x["no"] for x in s["sections"]] == [1, 3, 7]
    c = _upload("/api/extract/case", files["slip"], files["quote"]).json()
    assert c["schemaErrors"] == [] and c["policySystemFieldsBlank"] >= 7 and len(c["case"]["schedule"]["sections"]) == 13


def test_extract_all_and_render(files):
    a = _upload("/api/extract/all", files["slip"], files["quote"]).json()
    assert {"fields", "sections", "addons", "generated", "warnings"} <= set(a)
    r = _upload("/api/extract/render", files["slip"], files["quote"])
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")


def test_extract_needs_files_or_case_and_rejects_bad_input(files, tmp_path):
    assert client.post("/api/extract/fields").status_code == 400
    assert client.post("/api/extract/fields?case=no_such_case").status_code == 404
    p = tmp_path / "x.txt"
    p.write_text("x")
    with open(p, "rb") as a, open(p, "rb") as b:
        assert client.post("/api/extract/fields", files={"closing_slip": ("x.txt", a), "quote": ("y.txt", b)}).status_code == 400
    assert "demo_laghu" in client.get("/api/extract/registered").json()["cases"]


def test_condition_lines_are_not_shown_as_dropped_addons(library, files, tmp_path):
    """Laghu-style quotes list plain conditions with no insurer remark. They are conditions, not add-on covers."""
    import openpyxl
    q = tmp_path / "q_cond.xlsx"
    wb = openpyxl.load_workbook(files["quote"])
    ws = wb["Quote"]
    for r in (["Conditions, Warranties, Clauses and Exclusions"], ["Earthquake (Fire & Shock) Cover"], ["No cover for Kutcha Construction"], ["Agreed Bank Clause"]):
        ws.append(r)
    wb.save(q)
    api = client.post("/api/extract/addons", files={"closing_slip": ("s.xlsx", open(files["slip"], "rb")), "quote": ("q.xlsx", open(q, "rb"))}).json()
    assert api["counts"]["pending"] >= 3 and all(r["row_type"] == "condition_line" for r in api["rows"])
    ui = analyze(files["slip"], q).json()
    assert ui["addons"] == [] and any("condition / warranty lines" in n for n in ui["notes"])


def test_policy_number_is_never_filled_from_the_expiring_number(files, tmp_path):
    import openpyxl
    p = tmp_path / "renewal_slip.xlsx"
    make_slip(p)
    wb = openpyxl.load_workbook(p)
    ws = wb["Closing Slip"]
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value, str) and c.value.startswith("If Renewal"):
                ws.cell(row=c.row, column=c.column + 1, value="P0000000000/9999/100001")
    wb.save(p)
    d = analyze(p, files["quote"]).json()
    f = {x["key"]: x for x in d["fields"]}["system.policy_no"]
    assert f["value"] == "" and f["status"] == "missing" and "P0000000000/9999/100001" in (f["note"] or "")
