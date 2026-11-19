"""Draft-generation fixes: terms headings / closing block / tables, asset register warranty, matrix terrorism premium, add-on values, annexures for every
layout, location tables. Synthetic workbooks only."""
import openpyxl

from extractor import annexures, loc_columns, sections
from extractor.legacy import quote2
from extractor.legacy.grid import load


def _sheet(tmp_path, rows, name="RFQ"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = name
    for r in rows:
        ws.append(r)
    p = tmp_path / "t.xlsx"
    wb.save(p)
    return load(str(p))[0]


TERMS = [
    [None, "Terms and Conditions"],
    [None, "Section – 1- Fire Insurance Cover"], [None, "Deductible"], [None, "Locations having Sum Insured upto INR 10 Crores- 5% of claim amount"],
    [None, "Coverages/ Clauses/ Warranties"], [None, "Earthquake Covered"],
    [None, "Section – 2 Fire Loss of Profit Cover"], [None, "Deductible"], [None, "FLOP- 7 days of Standard Gross Profit"],
    [None, "Conditiions / Warranties / Clauses"], [None, "Terrorism Damage"], [None, "Transmission and Distribution lines (if any) outside the insured premises are not covered."],
    [None, "Section – 4- Machinery Breakdown Cover"], [None, "Excess:"], [None, "Escalation", None, "Policy Excess"],
    [None, "Terms/Conditions /Clause"], [None, "Terrorism Cover is excluded"], [None, "** Description of Equipments to be provided as annexure before policy placement"],
    [None, "Section – 5- Electronic Equipment  Cover"], [None, "Excess:"], [None, "Policy Excess", None, "As per the table below"],
    [None, "Table of EEI excess"], [None, "Section", None, "Excess"], [None, "Section 1 - Equipments", None, "5% of claim"],
    [None, None, None, "second line"], [None, "Section 3 - Increased Cost of Working", None, "Minimum time excess of 7 days"],
    [None, "Section – 7 Money / Cash  Cover"], [None, "Excess-5% of claim amount subject to minimum of 5,000/-"],
    [None, "Ø  Communicable Disease Exclusion Clause."], [None, "Ø  Sanctions Limitations & Exclusion Clause."], [None, "Ø  Cyber Loss Limited Exclusion Clause ~ LMA5410 (amended)."],
    [None, "Terms, conditions, and capacity quoted is subject to incurred claims ratio"],
]


def test_terms_by_section_headings_closing_block_table_and_asset_flag(tmp_path):
    t = quote2.terms_by_section(_sheet(tmp_path, TERMS))
    assert t["conditions"][2] == ["Terrorism Damage", "Transmission and Distribution lines (if any) outside the insured premises are not covered."]
    assert t["deductibles"][2] == ["FLOP- 7 days of Standard Gross Profit"]             # the misspelt "Conditiions / Warranties" heading still switches the group
    assert t["all"] == ["Communicable Disease Exclusion Clause.", "Sanctions Limitations & Exclusion Clause.", "Cyber Loss Limited Exclusion Clause ~ LMA5410 (amended)."]
    assert t["deductibles"][4] == ["Escalation – Policy Excess"]                   # key / value rows keep their value
    assert t["tables"][5]["header"] == ["Section", "Excess"]
    assert t["tables"][5]["rows"][0] == {"name": "Section 1 - Equipments", "text": ["5% of claim", "second line"]}
    assert t["asset_register"] == [4]
    assert 7 not in t["conditions"] and t["deductibles"][7]


def test_finish_terms_asset_register_and_all_sections_block():
    out = {"layout": "matrix", "sections": {n: {"sum_insured": 1.0 if n in (1, 2, 4) else None, "premium": None} for n in range(1, 14)},
           "terms": {"conditions": {2: ["Transmission and Distribution lines (if any) outside the insured premises are not covered."], 4: ["Terrorism Cover is excluded"]},
                     "deductibles": {}, "all": ["Communicable Disease Exclusion Clause.", "Sanctions Limitations & Exclusion Clause.", "Cyber Loss Limited Exclusion Clause ~ LMA5410 (amended)."],
                     "asset_register": [4, 5], "tables": {5: {"header": ["Section", "Excess"], "rows": [{"name": "x", "text": ["y"]}]}}}}
    sections._finish_terms(out)
    t = out["terms"]
    assert t["conditions"][4][-1].startswith("Asset Register Warranty - It is hereby agreed") and 5 not in t["conditions"]      # only for an opted section
    assert [l[:9] for l in t["all"]] == ["Sanctions", "Cyber Los", "Communica", "Transmiss", "All other"]
    assert t["all"][-1] == sections.OTHER_TERMS_ALL and t["tables"] == {}                                                  # section 5 is not opted: its table is dropped


def test_finish_terms_moves_general_clauses_when_there_is_no_all_block():
    out = {"layout": "location_matrix", "sections": {n: {"sum_insured": 1.0 if n == 1 else None, "premium": None} for n in range(1, 14)},
           "terms": {"conditions": {1: ["Warranted no Kutcha construction", "Sanctions Limitation And Exclusion Clause", "Communicable Disease Exclusion Clause",
                                        "All other terms, conditions and coverage will be as per Magma GIL policy wordings"]}, "deductibles": {}, "all": []}}
    sections._finish_terms(out)
    assert out["terms"]["conditions"][1] == ["Warranted no Kutcha construction"]
    assert out["terms"]["all"] == ["Sanctions Limitation And Exclusion Clause", "Communicable Disease Exclusion Clause", sections.OTHER_TERMS_ALL]


def test_term_groups_carries_the_table():
    g = sections.term_groups({"conditions": {}, "deductibles": {5: ["Policy Excess – As per the table below"]}, "all": [],
                              "tables": {5: {"header": ["Section", "Excess"], "rows": [{"name": "Section 1", "text": ["5%"]}]}}})
    d = g["deductibles"][0]
    assert d["table_header"] == ["Section", "Excess"] and d["table"] == [{"name": "Section 1", "text": ["5%"]}]


def test_addon_value_is_the_sum_insured_else_the_magma_remark():
    f = annexures.addon_value
    assert f({"limit": "200000000", "remark": "Covered upto FLB%"}) == 200000000.0
    assert f({"limit": "5% of Total Sum Insured", "remark": "Covered upto 10K subject to GD/DD entry"}) == "Covered upto 10K subject to GD/DD entry"
    assert f({"limit": "", "remark": "Covered upto 5% of BMA"}) == "Covered upto 5% of BMA"
    assert f({"limit": "upto 5%", "remark": ""}) == "upto 5%" and f({"limit": "", "remark": ""}) is None


def test_addon_block_is_numbered_in_order_with_the_new_column_title():
    b = annexures.addon_block([{"name": "Theft", "clause": None, "limit": "100000", "remark": "Covered"}, {"name": "Waiver of FIR", "clause": None, "limit": "5%", "remark": "10K"}], "Add on Covers")
    assert b["columns"] == ["Sr. no.", "Description", "Sum Insured / Limit (in INR)"] and [(r["sr"], r["desc"], r["value"]) for r in b["rows"]] == [(1, "Theft", 100000.0), (2, "Waiver of FIR", "10K")]


def test_location_columns_reads_a_table_with_locations_as_columns(tmp_path):
    sh = _sheet(tmp_path, [[None, "Unit 1", "Unit 2"], [None, "Office", "Workshop"], ["Building", 10, 130], ["Contents", 20, 50], ["Stocks", 0, 500], ["Total", 30, 680]], "Annexure")
    r = loc_columns.read([sh])
    assert [(l["name"], l["occupancy"], l["total"]) for l in r["locations"]] == [("Unit 1", "Office", 30.0), ("Unit 2", "Workshop", 680.0)]
    assert [i["description"] for i in r["locations"][1]["items"]] == ["Building", "Contents", "Stocks"]


def test_location_columns_ignores_a_table_that_does_not_add_up(tmp_path):
    sh = _sheet(tmp_path, [[None, "Unit 1", "Unit 2"], ["Building", 10, 130], ["Contents", 20, 50], ["Total", 30, 999]], "x")
    assert [l["name"] for l in (loc_columns.read([sh]) or {"locations": []})["locations"]] == ["Unit 1"]


def test_section_blocks_reader(tmp_path):
    rows = [["Fire Section - Plot 1 Pune"], ["Description", None, None, "Sum Insured (INR)"], ["Building", None, None, 100], ["Stock", None, None, 50],
            ["Fire Total Sum Insured", None, None, 150], ["STFI", None, None, 150], [],
            ["Burglary Section - Location 1 - Plot 1 Pune"], ["Description", None, None, "Sum Insured (INR)"], ["Stock", None, None, 50],
            ["Total Burglary Sum Insured", None, None, 50], ["First Loss Basis @ 25%", None, None, 12.5], ["ADD ON Cover"], ["Theft Cover", None, None, None, "Covered"], ["Total Burglary Premium"]]
    r = loc_columns.read_section_blocks([_sheet(tmp_path, rows)])
    assert r[1][0]["total"] == 150 and [i["description"] for i in r[1][0]["items"]] == ["Building", "Stock"]
    assert r[3][0]["first_loss_pct"] == 25 and r[3][0]["addons"] == [{"name": "Theft Cover", "remark": "Covered"}] and r[3][0]["address"] == "Plot 1 Pune"


def _sec(layout, **kw):
    secs = {n: {"no": n, "label": f"S{n}", "sum_insured": None, "premium": None, "items": [], "status": "ok", "note": "", "sub_rows": []} for n in range(1, 14)}
    return {"layout": layout, "sections": secs, "locations": [], "items": [], "terms": {"conditions": {}, "deductibles": {}, "all": []}, **kw}


HDR = {"insured": "ACME", "risk_location": "X", "business_activity": "BA", "occupancy": "OC"}


def test_asset_layout_builds_the_item_table_first_loss_and_theft_rsmd_rows():
    sec = _sec("asset", locations=[{"address": "GAT 1", "occupancy": "Workshop", "fire_items": [], "burglary_items": []}],
               terms={"conditions": {3: ["First loss limit - 25%", "Theft and RSMD Covered"]}, "deductibles": {}, "all": []})
    sec["sections"][3].update(sum_insured=400.0, premium=1.0, items=[{"description": "Plant", "si": 300}, {"description": "Stock", "si": 100}])
    ann, notes = annexures.build(sec, [], HDR)
    a = ann[0]
    assert a["no"] == 3 and a["title"] == "ANNEXURE 3 – APPLICABLE TO SECTION 3" and a["header"]["risk_location"] == "GAT 1" and a["header"]["occupancy"] == "Workshop"
    assert [r["desc"] for r in a["blocks"][0]["rows"]] == ["Plant", "Stock"] and a["blocks"][0]["total"] == 400.0
    assert [b.get("text") for b in a["blocks"][1:3]] == ["First Loss Basis @ 25%", "First Loss Sum Insured – INR 100"]
    assert [(r["desc"], r["value"]) for r in a["blocks"][3]["rows"]] == [("Theft", "Covered"), ("RSMD", "Covered")]


def test_location_table_picks_the_location_that_makes_up_the_sum_insured_and_adds_priced_perils():
    lm = {"locations": [{"name": "Unit 1", "occupancy": "Office", "items": [{"description": "Building", "si": 30.0}], "total": 30.0, "perils": {}},
                        {"name": "Unit 2", "occupancy": "Workshop", "items": [{"description": "Building", "si": 80.0}, {"description": "Stock", "si": 100.0}], "total": 180.0,
                         "perils": {"eq": 5.0, "stfi": 6.0, "terrorism": 7.0}}]}
    sec = _sec("labelled_table", loc_matrix=lm)
    sec["sections"][1].update(sum_insured=180.0, premium=1.0)
    sec["sections"][3].update(sum_insured=100.0, premium=1.0)
    ann, notes = annexures.build(sec, [], HDR)
    a1, a3 = ann
    assert (a1["no"], a3["no"]) == (1, 3) and a1["header"]["risk_location"] == "Unit 2" and a1["header"]["occupancy"] == "Workshop"
    assert [r["desc"] for r in a1["blocks"][1]["rows"]] == ["Earthquake", "STFI", "Terrorism"] and a1["blocks"][1]["rows"][0]["value"] == 180.0
    assert [r["desc"] for r in a3["blocks"][0]["rows"]] == ["Stock"]                          # burglary = fire items without the building


def test_section_without_an_item_table_prints_its_total_alone_and_says_so():
    sec = _sec("labelled_table")
    sec["sections"][1].update(sum_insured=500.0, premium=1.0)
    ann, notes = annexures.build(sec, [], HDR)
    assert ann[0]["blocks"][0]["rows"][0]["si"] == 500.0 and any("no item breakdown" in n for n in notes)


def test_matrix_layout_builds_one_annexure_per_opted_section():
    locs = [{"address": "A", "occupancy": "Office", "fire_items": [{"description": "Building", "si": 10.0}, {"description": "Plant & Machinery", "si": 40.0}], "fire_total": 50.0,
             "cols": {"fire loss of profit": 0.0, "electronic equipment": 0.0, "cash in safe": 20.0, "plant & machinery": 40.0}},
            {"address": "B", "occupancy": "Works", "fire_items": [{"description": "Plant & Machinery", "si": 100.0}], "fire_total": 100.0,
             "cols": {"fire loss of profit": 70.0, "electronic equipment": 5.0, "plant & machinery": 100.0}}]
    sec = _sec("matrix", locations=locs)
    for n, si in ((1, 150.0), (2, 70.0), (3, 140.0), (4, 140.0), (5, 5.0), (7, 20.0)):
        sec["sections"][n].update(sum_insured=si, premium=1.0)
    ann, notes = annexures.build(sec, [], HDR)
    assert [a["applies_to_section"] for a in ann] == [1, 2, 3, 4, 5, 7] and [a["no"] for a in ann] == [1, 2, 3, 4, 5, 6]
    assert ann[1]["header"]["risk_location"] == "B" and ann[5]["header"]["risk_location"] == "A"       # single-location sections name their location
    assert ann[0]["blocks"][1]["type"] == "matrix" and ann[0]["blocks"][1]["total"]["total"] == 150.0
    assert ann[2]["blocks"][1]["total"]["total"] == 140.0                                          # burglary = fire items without the building
