"""Add-on matching tests on synthetic data (fictional titles; no private library or dictionary needed)."""
import openpyxl

from extractor.clausebank import api
from extractor.clausebank.common import fullkey, norm
from extractor.clausebank.resolve import Index

TITLES = ["Removal of Debris Clause (Upto 1% of the Claim Amount)", "Removal of Debris (In excess of 1% of the Claim Amount)",
          "Start Up Expenses", "Agreed Bank Clause", "Fire Brigade Charges"]


def lib():
    return Index({"clauses": [{"title": t, "key": fullkey(t), "nkey": norm(t), "source": "master", "wording": ""} for t in TITLES]})


def quote(path, variants=None):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name in (variants or ["Plant"]):
        ws = wb.create_sheet(name)
        ws.append(["Add-on Covers", "Limit", "Magma Remarks"])
        for i, (n, lim, rem) in enumerate([
            ("Start Up Expenses", "5% of TSI", "Covered"),
            ("Agreed Bank Clause", "", "Not covered"),
            ("Fire Brigade Charges", "1 cr", "to be finalized"),
            ("Removal of Debris", "", "Covered"),
            ("Something Unheard Of", "", "Covered"),
        ], 1):
            ws.append([n, lim, rem])
    wb.save(path)


def run(path, variant=None):
    rows, _ = api.extract_rows(str(path), variant)
    return {r["name"]: r for r in api.match_rows(rows, idx=lib(), aliases={}, ids={})}


def test_keep_drop_pending_and_auto(tmp_path):
    q = tmp_path / "q.xlsx"
    quote(q)
    r = run(q)
    assert r["Start Up Expenses"]["decision"] == "keep" and r["Start Up Expenses"]["auto_eligible"]
    assert r["Agreed Bank Clause"]["decision"] == "drop" and not r["Agreed Bank Clause"]["auto_eligible"]
    assert r["Fire Brigade Charges"]["decision"] == "pending" and "pending_remark" in r["Fire Brigade Charges"]["needs_review"]


def test_near_identical_titles_never_auto(tmp_path):
    q = tmp_path / "q.xlsx"
    quote(q)
    d = run(q)["Removal of Debris"]
    assert not d["auto_eligible"] and "near_identical_title" in d["needs_review"] and d["near_identical"]


def test_unmatched_kept_row_is_flagged_not_invented(tmp_path):
    q = tmp_path / "q.xlsx"
    quote(q)
    u = run(q)["Something Unheard Of"]
    assert u["clause"] is None and u["wording_id"] is None and "no_library_clause" in u["needs_review"] and not u["auto_eligible"]


def test_every_kept_row_is_auto_or_flagged(tmp_path):
    q = tmp_path / "q.xlsx"
    quote(q)
    for r in run(q).values():
        if r["decision"] == "keep":
            assert r["auto_eligible"] or r["needs_review"], r["name"]


def test_variant_scoping(tmp_path):
    q = tmp_path / "q.xlsx"
    quote(q, ["Quote @A1", "Quote @A2"])
    rows, w = api.extract_rows(str(q), "@A2")
    assert {r["sheet"] for r in rows} == {"Quote @A2"} and not w
    rows, w = api.extract_rows(str(q), None)
    assert w and all(r["variant_unchosen"] for r in rows)
    assert all("variant_not_chosen" in r["needs_review"] for r in api.match_rows(rows, idx=lib(), aliases={}, ids={}) if r["decision"] != "drop")
