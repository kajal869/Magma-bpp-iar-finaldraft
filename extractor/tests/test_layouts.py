"""Layout profiles: generic recipes, auto-learning, taught cells. Synthetic workbooks only."""
import openpyxl
import pytest

from extractor import sections
from extractor.layouts import engine, store
from extractor.legacy.grid import load


@pytest.fixture(autouse=True)
def learned_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LEARNED", tmp_path / "learned")
    return tmp_path / "learned"


def section_table(path, fire=1000.0, terror=100.0, burg=50.0, net=None, shift=0):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Quote (SFSP)"
    for _ in range(shift):
        ws.append(["filler"])
    ws.append(["Quotation"])
    ws.append([None, "Section", "Description", "Sum Insured", "Rate", "Premium (In Rs.)"])
    ws.append([None, "Section – 1 Fire Insurance Cover", "As per Annexure", 5_000_000, None, fire, 999])
    ws.append([None, None, None, None, None, terror])
    ws.append([None, "Section – 3 Burglary and Housebreaking Cover", "As per Annexure", 2_000_000, 0.02, burg])
    ws.append([])
    ws.append([None, "Premium (Excl GST)", net if net is not None else fire + terror + burg])
    ws.append([None, "Premium (Terrorism)", terror])
    wb.save(path)


def test_labelled_table_discovered_verified_and_saved(tmp_path, learned_dir):
    q = tmp_path / "q.xlsx"
    section_table(q)
    r = sections.read(str(q))
    s = r["sections"]
    assert r["layout"] == "labelled_table" and r["layout_info"]["source"] == "discovered" and r["layout_info"]["saved"]
    assert (s[1]["sum_insured"], s[1]["premium"]) == (5_000_000, 1100.0)      # fire + the terrorism line under it
    assert (s[3]["sum_insured"], s[3]["premium"]) == (2_000_000, 50.0) and s[1]["status"] in ("ok", "derived")
    assert r["scalars"]["premium.terrorism"]["value"] == 100.0
    assert len(list(learned_dir.glob("*.json"))) == 1


def test_same_format_next_time_uses_the_saved_profile_even_if_rows_shift(tmp_path):
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    section_table(a)
    sections.read(str(a))
    section_table(b, fire=2000.0, terror=0.0, burg=70.0, shift=5)               # new numbers, everything 5 rows lower
    r = sections.read(str(b))
    assert r["layout_info"]["source"] == "auto" and r["layout_info"]["profile"] and r["layout_info"].get("overlap")
    assert r["sections"][1]["premium"] == 2000.0 and r["sections"][3]["premium"] == 70.0


def test_unverified_generic_read_is_check_and_not_saved(tmp_path, learned_dir):
    q = tmp_path / "q.xlsx"
    section_table(q, net=99999.0)                                              # premiums do not add up to the stated net
    r = sections.read(str(q))
    assert not r["layout_info"]["verified"] and all(r["sections"][n]["status"] == "check" for n in (1, 3))
    assert not list(learned_dir.glob("*.json"))


def test_location_matrix(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "RFQ Option II"
    ws.append(["Location", "A", "B", "C", "Total"])
    ws.append(["TOTAL SUM INSURED", 100, 200, 300, 600])
    ws.append(["Total Premium Before GST.", 10.0, 20.0, 30.0, 60.0])
    q = tmp_path / "q.xlsx"
    wb.save(q)
    r = sections.read(str(q))
    assert r["layout"] == "location_matrix" and (r["sections"][1]["sum_insured"], r["sections"][1]["premium"]) == (600, 60.0)


def test_unknown_layout_asks_to_be_taught_then_teaching_sticks(tmp_path):
    q = tmp_path / "q.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Odd"
    ws.append(["Fire cover value", 7_000_000])
    ws.append(["Net amount payable", 4321.0])
    wb.save(q)
    r = sections.read(str(q))
    assert r["layout_info"]["source"] == "unsupported" and r["layout_info"]["teach"]
    from extractor.layouts.common import h
    from extractor.layouts.fingerprint import fingerprint
    from extractor.layouts.recipes import teach_cell
    sh = load(str(q))
    fp = sorted(fingerprint(sh))
    store.save({"id": "p_t", "source": "taught", "fingerprint": fp, "uses": 0,
                "recipes": [teach_cell(sh, "section.1.si", "Odd", "B1"), teach_cell(sh, "premium.net", "Odd", "B2")]})
    r2 = sections.read(str(q))
    assert r2["sections"][1]["sum_insured"] == 7_000_000 and r2["sections"][1].get("taught")
    assert r2["layout_info"]["source"] == "taught" and not any("not recognised" in w for w in r2["warnings"])
    assert r2["taught"]["premium.net"]["value"] == 4321.0


def test_taught_location_survives_shifted_rows(tmp_path):
    from extractor.layouts.fingerprint import fingerprint
    from extractor.layouts.recipes import teach_cell
    q1, q2 = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    for q, shift, val in ((q1, 0, 111.0), (q2, 4, 222.0)):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Odd"
        for _ in range(shift):
            ws.append(["filler"])
        ws.append(["Net amount payable", val])
        wb.save(q)
    sh = load(str(q1))
    store.save({"id": "p_s", "source": "taught", "fingerprint": sorted(fingerprint(sh)), "uses": 0, "recipes": [teach_cell(sh, "premium.net", "Odd", "B1")]})
    got = engine.taught_overrides(load(str(q2)))
    assert got["premium.net"]["value"] == 222.0 and got["premium.net"]["ref"] == "B5"


def test_closing_slip_allocation_is_a_check_fallback(tmp_path):
    q = tmp_path / "q.xlsx"
    wb = openpyxl.Workbook()
    wb.active.append(["nothing recognisable"])
    wb.save(q)
    r = sections.read(str(q), slip={"pd_allocation": 590_875_967, "bi_allocation": 1})
    assert r["sections"][1]["sum_insured"] == 590_875_967 and r["sections"][1]["status"] == "check"
    assert r["sections"][2]["sum_insured"] is None                              # 1 is a share, not a sum insured


def headerless_table(path, fidelity=155000.0):
    """The premium column is headed 'Insurer' (no word 'Premium'); the covers are named by their rows; the fidelity sum insured is in its own block."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Stock"
    ws.append(["Description", None, "Sum Insured INR", "Insurer"])
    ws.append([None, "Standard Fire and Special Perils", 9_000_000, 1000.0])
    ws.append([None, "Burglary", 9_000_000, 70.0])
    ws.append([None, "Premium Total without terrorism", None, 1070.0])
    ws.append([None, "Fidelity", None, fidelity])
    ws.append([None, "Total Premium", None, 1070.0 + fidelity])
    ws.append([])
    ws.append(["Section 8 - Fidelity Cover"])
    ws.append([None, "Sum Insured", 1_000_000])
    wb.save(path)


def test_summed_table_found_by_structure_not_header_words(tmp_path, learned_dir):
    q = tmp_path / "h.xlsx"
    headerless_table(q)
    r = sections.read(str(q))
    s = r["sections"]
    assert r["layout"] == "summed_table" and r["layout_info"]["verified"]
    assert (s[1]["sum_insured"], s[1]["premium"]) == (9_000_000, 1000.0)
    assert (s[3]["sum_insured"], s[3]["premium"]) == (9_000_000, 70.0)
    assert (s[8]["sum_insured"], s[8]["premium"]) == (1_000_000, 155000.0)      # sum insured taken from the cover's own block
    assert s[1]["status"] == "ok"


def test_summed_table_needs_an_exact_tie(tmp_path, learned_dir):
    q = tmp_path / "h.xlsx"
    headerless_table(q)
    wb = openpyxl.load_workbook(q)
    wb.active["D6"] = 5000.0                                                   # the stated total no longer equals the rows
    wb.save(q)
    r = sections.read(str(q), net=None)
    assert r["layout"] != "summed_table"


def test_discovery_never_overwrites_a_taught_profile(tmp_path, learned_dir):
    q = tmp_path / "h.xlsx"
    headerless_table(q)
    fp = sorted(engine.fingerprint(load(str(q))))
    pid = "p_" + engine.h("|".join(fp))
    store.save({"id": pid, "source": "taught", "fingerprint": fp, "recipes": [{"type": "cell", "target": "premium.net", "sheet": "x", "ref": "D6", "kind": "number"}], "uses": 0})
    sections.read(str(q))
    types = [r["type"] for r in store.get(pid)["recipes"]]
    assert "cell" in types and "summed_table" in types


def test_excess_line_and_single_section_default_in_terms(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Section – 3- Burglary & House Breaking Cover"])
    ws.append(["Excess 5% of claim amount subject to min of INR 5,000/-"])
    ws.append(["Terms/Conditions /Clause"])
    ws.append(["Terrorism cover is excluded"])
    p = tmp_path / "t.xlsx"
    wb.save(p)
    t = sections.laghu_terms(load(str(p))[0])
    assert t["deductibles"][3] == ["Excess 5% of claim amount subject to min of INR 5,000/-"] and t["conditions"][3] == ["Terrorism cover is excluded"]
    wb2 = openpyxl.Workbook()
    w2 = wb2.active
    w2.append(["Deductible/Excess"])
    w2.append(["5% of claim"])
    w2.append(["Conditions / Warranties / Clauses"])
    w2.append(["Warranted no Kutcha construction"])
    p2 = tmp_path / "t2.xlsx"
    wb2.save(p2)
    assert sections.laghu_terms(load(str(p2))[0]) ["conditions"] == {}                 # no section known: nothing is guessed
    assert sections.laghu_terms(load(str(p2))[0], default_sec=1)["conditions"] == {1: ["Warranted no Kutcha construction"]}
