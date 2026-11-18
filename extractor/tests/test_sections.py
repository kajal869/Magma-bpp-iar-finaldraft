"""Section / terms / annexure tests on a synthetic laghu quote (fictional data)."""
import openpyxl

from extractor import annexures, sections
from extractor.build_case import assemble


def laghu(path, net_premium=None):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Quote"
    rows = [
        ["MAGMA GENERAL INSURANCE LTD"], ["BUSINESS PROTECT POLICY (LAGHU UDYAM) QUOTATION"],
        [1.0, "Name of Insured", "ACME TEST LIMITED"], [4.0, "Risk Location ", "PLOT 1 TEST ROAD"], [5.0, "Type of occupation", "WORKSHOP"],
        ["Description", "Sum insured", "Premium rate", "Premium"],
        ["I", "Fire", "Description"], ["Building ", 6000000.0], ["Contents", "FFF and equipment", 2000000.0], ["Total Sum Insured", 8000000.0],
        ["STFI", 8000000.0, 0.22, 1760.0], ["EQ", 8000000.0, 0.05, 400.0],
        ["II", "Burglary and House Breaking", "All contents, First loss basis - 100%", 1000000.0, 0.1, 100.0],
        ["IV", "Money insurance", "Estimated Annual Turnover", 600000.0, 0.1, 60.0],
        ["Cash in Till / Counter", 300000.0, 0.15, 45.0], ["Cash in safe / strong room", 300000.0, 0.15, 45.0],
        ["TOTAL SUM INSURED OF ALL SECTIONS", net_premium or 2410.0],
        ["GST", 0.18, 425.7], ["Total premium with GST", 2790.7], [],
        ["Deductible/Excess"], ["Bharat Laghu Udyam Suraksha"], ["5% of claim amount subject to a min of INR 5,000"],
        ["Burglary & Housebreaking Insurance"], ["5% of claim amount"],
        ["Conditions, Warranties, Clauses and Exclusions"], ["Bharat Laghu Udyam Suraksha"], ["Earthquake (Fire & Shock) Cover"], ["No cover for Kutcha Construction"],
        ["Conditions Applicable to All Sections"], ["Subject to Sanctions, Limitation and Exclusion Clause"], ["Terms, conditions, and capacity quoted is subject to following"],
    ]
    for r in rows:
        ws.append(r)
    wb.save(path)


def test_laghu_sections_and_tie(tmp_path):
    q = tmp_path / "q.xlsx"
    laghu(q)
    r = sections.read(str(q))
    s = r["sections"]
    assert (s[1]["sum_insured"], s[1]["premium"]) == (8000000.0, 2160.0)
    assert (s[3]["sum_insured"], s[3]["premium"]) == (1000000.0, 100.0)
    assert s[7]["premium"] == 45.0 and len(s[7]["sub_rows"]) == 2
    assert r["layout"] == "laghu" and r["tie"] and all(s[n]["status"] == "ok" for n in (1, 3, 7))
    assert r["terms"]["all"] == ["Subject to Sanctions, Limitation and Exclusion Clause"]
    assert r["terms"]["deductibles"][1] and r["terms"]["conditions"][1]


def test_tie_failure_flags_every_section(tmp_path):
    q = tmp_path / "q.xlsx"
    laghu(q, net_premium=9999.0)
    r = sections.read(str(q))
    assert not r["tie"] and all(r["sections"][n]["status"] == "check" for n in (1, 3, 7))


def test_unopted_sections_stay_empty_not_invented(tmp_path):
    q = tmp_path / "q.xlsx"
    laghu(q)
    s = sections.read(str(q))["sections"]
    assert all(s[n]["sum_insured"] is None and s[n]["premium"] is None for n in (2, 4, 5, 6, 8, 9, 10, 11, 12, 13))


def test_annexures_laghu(tmp_path):
    q = tmp_path / "q.xlsx"
    laghu(q)
    sec = sections.read(str(q))
    ann, unbuilt = annexures.build(sec, [], {"insured": "ACME TEST LIMITED", "risk_location": "PLOT 1", "business_activity": "WORKSHOP", "occupancy": "x"})
    by = {a["applies_to_section"]: [b["type"] for b in a["blocks"]] for a in ann}
    assert by[1] == ["si_simple", "si_simple"] and by[3] == ["si_simple", "note", "note"] and by[7] == ["kv_rows"] and not unbuilt


def test_assemble_blank_system_fields_and_no_invented_values(tmp_path):
    from extractor.pipeline import run
    from extractor.score import load_cases, _abs
    c = load_cases()["demo_laghu"]
    case, notes = assemble(run(_abs(c["slip"]), _abs(c["quote"])))
    assert case["system"]["policy_no"] == "" and case["system"]["magma_gstin"] == ""
    assert len(case["schedule"]["sections"]) == 13
    assert any("house conventions" in n for n in notes)


def _sheet(rows):
    from extractor.legacy.grid import Sheet
    return Sheet("Q", True, [(i + 1, [(j + 1, v) for j, v in enumerate(r) if v is not None]) for i, r in enumerate(rows)])


def _out(net, **secs):
    out = {"sections": sections._empty_sections(), "net": net}
    for n, (si, pr) in secs.items():
        out["sections"][int(n[1:])].update(sum_insured=si, premium=pr, status="ok")
    return out


def test_unsplit_premium_is_flagged():
    """Net premium put on one section while the same sheet has Burglary / Fidelity rows with amounts: flagged, values untouched."""
    sh = _sheet([["Fire", 5000000, 90000], ["Burglary", 5000000, 7000], ["Fidelity", 1000000, 3000], ["Total Premium", None, 100000]])
    out = _out(100000.0, s1=(5000000, 100000.0))
    w = sections._missed_sections(out, [sh])
    assert w and "section 3" in w[0] and "section 8" in w[0]
    assert out["sections"][1]["status"] == "check" and out["sections"][1]["premium"] == 100000.0


def test_asset_lines_are_not_mistaken_for_sections():
    sh = _sheet([["Electrical Machinery", 25000000, 1282000], ["Plant & Machineries", 4000000, 2000000], ["Total Premium", None, 6660000]])
    assert sections._missed_sections(_out(6660000.0, s1=(13000000, 6660000.0)), [sh]) == []


def test_well_split_quote_is_not_flagged():
    sh = _sheet([["Burglary", 5000000, 7000], ["Total Premium", None, 100000]])
    out = _out(100000.0, s1=(5000000, 93000.0), s3=(5000000, 7000.0), s8=(1000000, 0.0))
    assert sections._missed_sections(out, [sh]) == []
