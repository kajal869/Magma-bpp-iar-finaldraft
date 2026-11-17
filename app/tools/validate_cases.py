"""Validate case JSONs against policy.schema.json and check the arithmetic.

Run: python -P app/tools/validate_cases.py [case ...]
Exit code 1 if any schema error or hard arithmetic failure.
Soft notes (rounding of 1, known issued mismatches) are printed but do not fail.
"""
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

APP = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((APP / "schema" / "policy.schema.json").read_text(encoding="utf-8"))
CASES = sys.argv[1:] or ["mann", "valmet", "shreeji"]


def check(case):
    d = json.loads((APP / "cases" / f"{case}.json").read_text(encoding="utf-8"))
    hard, soft = [], []
    for e in sorted(Draft202012Validator(SCHEMA).iter_errors(d), key=lambda e: list(e.path)):
        hard.append("schema: " + "/".join(map(str, e.path)) + ": " + e.message[:160])

    # premium arithmetic
    p = d["premium"]
    if abs(p["basic"] + p["terrorism"] - p["net"]) > 0.5:
        hard.append(f"premium: basic+terrorism {p['basic'] + p['terrorism']} != net {p['net']}")
    tax = sum(t["amount"] for t in p["taxes"])
    for t in p["taxes"]:
        if abs(p["net"] * t["rate"] - t["amount"]) > 1:
            hard.append(f"premium: {t['type']} {t['amount']} != net x rate {p['net'] * t['rate']:.2f}")
    if abs(p["net"] + tax - p["final"]) > 1:
        hard.append(f"premium: net+tax {p['net'] + tax:.2f} != final {p['final']}")
    elif abs(p["net"] + tax - p["final"]) > 0.5:
        soft.append(f"premium: net+tax {p['net'] + tax:.2f} vs final {p['final']} (rounding)")

    # tax type vs place of supply
    types = {t["type"] for t in p["taxes"]}
    if types not in ({"IGST"}, {"CGST", "SGST"}):
        hard.append(f"taxes: unexpected combination {types}")

    # schedule premium column vs net premium
    rows = d["schedule"]["sections"]
    prem = 0
    for s in rows:
        prem += s["premium"] or 0
        for sub in s.get("sub_rows", []):
            prem += sub["premium"] or 0
    if abs(prem - p["net"]) > 1:
        hard.append(f"schedule: premium column {prem} != net premium {p['net']}")
    elif prem != p["net"]:
        soft.append(f"schedule: premium column {prem} vs net {p['net']} (rounding)")

    # annexure arithmetic
    for a in d["annexures"]:
        for b in a["blocks"]:
            t = b["type"]
            if t == "si_simple" and "total" in b:
                s = sum(r["si"] for r in b["rows"])
                if s != b["total"]:
                    hard.append(f"annexure {a['no']} si_simple: rows {s} != total {b['total']}")
            if t == "si_groups":
                for g in b["groups"]:
                    s = sum(r["si"] for r in g["rows"])
                    if s != g["total"]:
                        hard.append(f"annexure {a['no']} group: rows {s} != total {g['total']}")
                s = sum(g["total"] for g in b["groups"])
                if s != b["grand_total"]:
                    hard.append(f"annexure {a['no']} grand total {b['grand_total']} != {s}")
            if t == "matrix" and "total" in b:
                for c in b["columns"]:
                    k = c["key"]
                    s = sum((r["values"].get(k) or 0) for r in b["rows"])
                    tot = b["total"].get(k) or 0
                    if s != tot:
                        (soft if abs(s - tot) <= 10 else hard).append(
                            f"annexure {a['no']} matrix col {k}: rows {s} != total {tot}")
                for r in b["rows"]:
                    comp = [v for k, v in r["values"].items() if k != "total" and v]
                    if comp and r["values"].get("total") and sum(comp) != r["values"]["total"]:
                        hard.append(f"annexure {a['no']} matrix row {r['address'][:25]}: parts {sum(comp)} != {r['values']['total']}")

    # schedule SI vs annexure totals
    by_sec = {a["applies_to_section"]: a for a in d["annexures"] if a.get("applies_to_section") and a["no"] != 99}
    for s in rows:
        a = by_sec.get(s["no"])
        if a is None or s["sum_insured"] is None:
            continue
        tot = None
        for b in a["blocks"]:
            if b["type"] == "si_simple" and "total" in b and tot is None:
                tot = b["total"]
            if b["type"] == "si_groups" and tot is None:
                tot = b["grand_total"]
        if tot is not None and tot != s["sum_insured"]:
            hard.append(f"section {s['no']}: schedule SI {s['sum_insured']} != annexure total {tot}")
    return d, hard, soft


bad = 0
for c in CASES:
    d, hard, soft = check(c)
    n_add = sum(len(b["rows"]) for a in d["annexures"] for b in a["blocks"] if b["type"] == "addons")
    print(f"== {c}: {len(d['annexures'])} annexures, {n_add} add-on rows, "
          f"{len(d['provenance']['conflicts'])} conflicts, {len(d['provenance'].get('deviations_from_issued', []))} deviations")
    for m in hard:
        print("  FAIL", m)
    for m in soft:
        print("  note", m)
    bad += len(hard)
    if not hard:
        print("  OK")
sys.exit(1 if bad else 0)
