"""Score sections, terms and annexures against an answer-key case; validate the generated case against the schema.

  python -m extractor.section_score mann valmet shreeji

Sections: per section SI and premium. correct = shown (ok/derived) and equal to the key (1 rupee); flagged = status check; SILENT_WRONG =
shown but different. Terms: key lines matched by similarity (>= 0.8) / key lines; extra lines the extractor added are listed.
Annexures: which sections have an annexure, and block types, versus the key.
"""
from __future__ import annotations

import json
import sys

from jsonschema import Draft202012Validator

from .build_case import assemble
from .clausebank.match import sim
from .pipeline import run
from .score import ROOT, _abs, load_cases

SCHEMA = json.loads((ROOT / "app" / "schema" / "policy.schema.json").read_text(encoding="utf-8"))
TOL = 1.0


def _eq(a, b):
    return a is None and b is None or (a is not None and b is not None and abs(float(a) - float(b)) <= TOL)


def lines_match(got: list[str], key: list[str]):
    left, hit = list(got), 0
    for k in key:
        best = max(((sim(k, g), i) for i, g in enumerate(left)), default=(0, -1))
        if best[0] >= 0.8:
            hit += 1
            left.pop(best[1])
    return hit, left


def score_case(case: str, cfg: dict) -> dict:
    c = cfg[case]
    key = json.loads((ROOT / "app" / "cases" / f"{case}.json").read_text(encoding="utf-8"))
    res = run(_abs(c["slip"]), _abs(c["quote"]), _abs(c.get("imd")))
    out, notes = assemble(res)
    tally = {"correct": 0, "flagged": 0, "SILENT_WRONG": 0}
    rows = []
    sec = res["sections"]["sections"] if res.get("sections") else {}
    for k in key["schedule"]["sections"]:
        n = k["no"]
        s = sec.get(n)
        if s is None:
            continue
        for what, kv, gv in (("SI", k["sum_insured"], s["sum_insured"]), ("premium", k["premium"], s["premium"])):
            if kv is None and gv is None:
                continue
            if s["status"] in ("ok", "derived"):
                verdict = "correct" if _eq(kv, gv) else "SILENT_WRONG"
            else:
                verdict = "flagged"
            tally[verdict] += 1
            rows.append((f"section {n} {what}", verdict, gv, kv, s["status"] + (": " + s["note"] if s["note"] else "")))
    t_rows, t_hit, t_tot, t_extra = [], 0, 0, 0
    for grp in ("section_conditions", "deductibles"):
        kmap = {g["key"]: g for g in key["terms"][grp]}
        gmap = {g["key"]: g for g in out["terms"][grp]}
        for kk, g in kmap.items():
            klines = list(g.get("lines", [])) + [l for sg in g.get("sub_groups", []) for l in sg["lines"]]
            glines = list(gmap.get(kk, {}).get("lines", [])) + [l for sg in gmap.get(kk, {}).get("sub_groups", []) for l in sg["lines"]]
            hit, extra = lines_match(glines, klines)
            t_hit += hit
            t_tot += len(klines)
            t_extra += len(extra)
            t_rows.append((f"{grp}:{kk}", f"{hit}/{len(klines)}", len(extra)))
        for kk in gmap.keys() - kmap.keys():
            t_extra += len(gmap[kk].get("lines", []))
            t_rows.append((f"{grp}:{kk}", "not in key", len(gmap[kk].get("lines", []))))
    hit, extra = lines_match(out["terms"]["all_sections_conditions"]["lines"], key["terms"]["all_sections_conditions"]["lines"])
    t_hit += hit
    t_tot += len(key["terms"]["all_sections_conditions"]["lines"])
    t_rows.append(("all_sections", f"{hit}/{len(key['terms']['all_sections_conditions']['lines'])}", len(extra)))
    a_key = {a["applies_to_section"]: [b["type"] for b in a["blocks"]] for a in key["annexures"] if a["no"] != 99}
    a_got = {a["applies_to_section"]: [b["type"] for b in a["blocks"]] for a in out["annexures"]}
    errs = [f"{'/'.join(map(str, e.absolute_path))}: {e.message[:90]}" for e in Draft202012Validator(SCHEMA).iter_errors(out)]
    return {"case": case, "layout": res["sections"]["layout"] if res.get("sections") else None, "tally": tally, "rows": rows, "terms": (t_hit, t_tot, t_extra, t_rows),
            "annex": (a_key, a_got), "schema_errors": errs, "notes": notes, "warnings": res["warnings"]}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cfg = load_cases()
    names = argv or [n for n in sorted(cfg) if n != "demo_laghu" and (ROOT / "app" / "cases" / f"{n}.json").exists()]
    bad = 0
    for n in names:
        try:
            r = score_case(n, cfg)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"\n== {n}   ERROR {type(e).__name__}: {e}")
            bad += 1
            continue
        t = r["tally"]
        print(f"\n== {n} ({r['layout']})   sections: correct {t['correct']}  flagged {t['flagged']}  SILENT_WRONG {t['SILENT_WRONG']}")
        for name, verdict, got, kv, note in r["rows"]:
            print(f"  {name:22} {verdict:13} got={got!s:>16} key={kv!s:>16}  {note[:90]}")
        h, tot, ex, trows = r["terms"]
        print(f"  terms: key lines found {h}/{tot}; extra lines {ex}")
        for name, frac, e in trows:
            print(f"     {name:24} {frac:>10}  extra {e}")
        ak, ag = r["annex"]
        print(f"  annexures key sections {sorted(ak)}  got {sorted(ag)}")
        for sct in sorted(set(ak) | set(ag)):
            print(f"     S{sct}: key {ak.get(sct)}  got {ag.get(sct)}")
        other = [e for e in r["schema_errors"] if not e.startswith("system/")]
        print(f"  schema errors: {len(r['schema_errors']) - len(other)} policy-system fields still blank (expected, entered by the user); {len(other)} other")
        for e in other[:8]:
            print("     ", e)
        for x in r["notes"]:
            print("  note:", x)
        bad += t["SILENT_WRONG"]
    print(f"\nTOTAL SECTION SILENT_WRONG = {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
