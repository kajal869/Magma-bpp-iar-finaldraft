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


def test_resolver_disagreement_is_conflict_never_picked():
    r = resolve([F("insured.gstin", "29AAAAA0000A1Z5", "slip"), F("insured.gstin", "27BBBBB1111B1Z5", "quote")])[0]
    assert r.status == "conflict" and r.value is None and len(r.alternatives) == 2


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
