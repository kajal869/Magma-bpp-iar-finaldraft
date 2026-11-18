"""Synthetic tests (fictional data only). Run: python -m pytest extractor/tests -q"""
import openpyxl
import pytest

from extractor import score
from extractor.adapters import headline
from extractor.envelope import Field, same
from extractor.resolver import resolve


def F(name, v, tool, status="ok"):
    return Field(name, v, status, {"tool": tool})


def test_resolver_agreement_is_ok():
    r = {f.field: f for f in resolve([F("premium.final", 100.0, "slip"), F("premium.final", 100.4, "quote", "derived")])}
    assert r["premium.final"].status == "ok" and r["premium.final"].value == 100.4   # quote wins for money


def test_identity_disagreement_prefers_the_slip_but_is_flagged():
    r = resolve([F("insured.gstin", "29AAAAA0000A1Z5", "slip"), F("insured.gstin", "27BBBBB1111B1Z5", "quote")])[0]
    assert r.value == "29AAAAA0000A1Z5" and r.status == "check" and len(r.alternatives) == 2 and "closing slip value is used" in r.note


def test_money_disagreement_is_still_a_conflict_never_picked():
    r = resolve([F("premium.net", 100.0, "slip"), F("premium.net", 5000.0, "quote")])[0]
    assert r.status == "conflict" and r.value is None


def test_resolver_never_upgrades_single_source():
    r = resolve([F("intermediary.name", "SHORT NAME", "slip", "check")])[0]
    assert r.status == "check"


def test_same_kinds():
    assert same("name", "ACME PVT LTD.", "ACME PRIVATE LIMITED")
    assert same("money", 100.4, 100.0) and not same("money", 102, 100)
    assert not same("code", None, None)


def _quote(path, variants):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for tag, net in variants.items():
        ws = wb.create_sheet(f"Quote @{tag}")
        for r, (a, b) in enumerate([("Net Premium", net), ("GST @ 18%", round(net * .18, 2)), ("Total Premium", round(net * 1.18, 2))], 1):
            ws.cell(r, 1, a)
            ws.cell(r, 2, b)
    wb.save(path)


def test_variant_chosen_by_slip_total(tmp_path):
    q = tmp_path / "q.xlsx"
    _quote(q, {"A1": 10000, "A2": 20000, "A3": 30000})
    fields, info = headline.read(str(q), slip_total=23600.0)
    assert info["variant"] == "@A2"
    assert {f.field: f.value for f in fields}["premium.net"] == 20000


def test_variant_no_tie_is_conflict(tmp_path):
    q = tmp_path / "q.xlsx"
    _quote(q, {"A1": 10000, "A2": 20000})
    fields, info = headline.read(str(q), slip_total=99999.0)
    net = next(f for f in fields if f.field == "premium.net")
    assert info["variant"] is None and net.status == "conflict" and net.value is None


def test_demo_case_has_no_silent_wrong():
    r = score.score_case("demo_laghu", score.load_cases())
    assert r["tally"]["SILENT_WRONG"] == 0 and r["tally"]["missing"] == 0


def test_slip_only_money_is_a_check_not_ok():
    r = resolve([F("premium.final", 420650.0, "slip")])[0]
    assert r.status == "check" and "quote did not confirm" in r.note


def test_quote_net_confirms_slip_total(tmp_path):
    q = tmp_path / "q.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Quote"
    ws.append(["Net Premium", 20000])
    wb.save(q)
    fields, _ = headline.read(str(q), slip_total=23600.0)
    r = {f.field: f for f in resolve(fields + [F("premium.final", 23600.0, "slip")])}
    assert r["premium.final"].status == "ok" and r["premium.final"].value == 23600.0


def test_quote_net_that_does_not_tie_does_not_confirm(tmp_path):
    q = tmp_path / "q.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Quote"
    ws.append(["Net Premium", 20000])
    wb.save(q)
    fields, _ = headline.read(str(q), slip_total=20000.0)           # slip amount equals the NET: it excludes GST
    r = {f.field: f for f in resolve(fields + [F("premium.final", 20000.0, "slip")])}
    assert r["premium.final"].status in ("check", "conflict") and r["premium.final"].status not in ("ok", "derived")




def test_policy_period_must_be_twelve_months_or_it_is_a_check(tmp_path):
    import datetime
    import sys
    sys.path.insert(0, "samples")
    from extractor.adapters import slip as slip_adapter
    from samples.make_samples import make_slip
    for end, expect in ((datetime.datetime(2027, 3, 31), "ok"), (datetime.datetime(2026, 9, 30), "check")):
        p = tmp_path / f"s_{end.year}{end.month}.xlsx"
        make_slip(p, start=datetime.datetime(2026, 4, 1))
        import openpyxl
        wb = openpyxl.load_workbook(p)
        ws = wb["Closing Slip"]
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.lower().startswith("policy end date"):
                    ws.cell(row=c.row, column=c.column + 1, value=end)
        wb.save(p)
        f = {x.field: x for x in slip_adapter.read(str(p))[0]}
        assert f["period.start"].status == expect and f["period.end"].status == expect


def test_quote_identity_similarity_ignores_company_suffixes_and_brackets():
    from extractor.adapters.quote_identity import similarity
    assert similarity("APA ENGINEERING PRIVATE LIMITED", "M/s. APA Engineering Pvt Ltd") == 1.0
    assert similarity("LOUIS DREYFUS COMPANY INDIA PRIVATE LIMITED.", "Louis Dreyfus Company India Private Limited (Including all subsidiary companies)") == 1.0
    assert similarity("TOWELL ENGINEERING INTERNATIONAL LLP", "Kasliwal Automotive Pvt Ltd") == 0.0


def test_quote_naming_another_insured_is_flagged_not_overwritten(tmp_path):
    import openpyxl
    from extractor.adapters import quote_identity
    from extractor.resolver import resolve
    from extractor.envelope import Field
    p = tmp_path / "q.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Name of the Insured", None, "Kasliwal Automotive Pvt Ltd"])
    ws.append(["Insured's Communication Address", None, "Halka 17, Indore"])
    wb.save(p)
    fields, warns, rows = quote_identity.cross_check(str(p), "TOWELL ENGINEERING LLP", "Rourkela Odisha")
    assert [f.field for f in fields] == ["insured.name"] and any("different insured" in w for w in warns) and not rows[0]["agree"]
    slip = Field("insured.name", "TOWELL ENGINEERING LLP", "ok", {"tool": "slip"})
    got = {f.field: f for f in resolve([slip] + fields)}["insured.name"]
    assert got.value == "TOWELL ENGINEERING LLP" and got.status == "check" and got.alternatives[1]["value"] == "Kasliwal Automotive Pvt Ltd"
    ok_fields, ok_warns, _ = quote_identity.cross_check(str(p), "Kasliwal Automotive Private Limited", "Halka 17 Indore")
    assert ok_fields == [] and not any("different insured" in w for w in ok_warns)


def test_slip_amount_equal_to_net_selects_the_sheet_and_is_derived():
    from extractor.adapters import headline
    from extractor.envelope import Field
    rep = {"fields": {"net_premium": {"value": None, "evidence": [{"value": 420650.0}, {"value": 89346.55}]},
                      "total_premium": {"value": None, "evidence": [{"value": 496367.0}, {"value": 105428.93}]}}}
    fields = [Field("premium.net", None, "conflict"), Field("premium.final", None, "conflict")]
    out = {f.field: f for f in headline._apply_net_tie(fields, rep, 420650.0)}
    assert out["premium.net"].value == 420650.0 and out["premium.net"].status == "derived" and "exclude GST" in out["premium.net"].note
    assert out["premium.final"].value == 496367.0 and out["premium.final"].status == "derived"
    amb = {f.field: f for f in headline._apply_net_tie([Field("premium.net", None, "conflict")], {"fields": {"net_premium": {"evidence": [{"value": 100.0}, {"value": 100.5}]}}}, 100.0)}
    assert amb["premium.net"].status == "conflict"            # two candidates within tolerance of the slip amount: nothing is picked
