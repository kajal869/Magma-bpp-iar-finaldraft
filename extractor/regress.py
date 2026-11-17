"""Regression harness: run the pipeline on every registered case and report, without needing a full answer key.

  python -m extractor.regress              compare with extractor/baseline.local.json (exit 1 on a regression)
  python -m extractor.regress --update     accept the current numbers as the new baseline
  python -m extractor.regress apa pune     only these cases

Per case (inputs and optional expectations live in the private extractor/cases.local.json):
  crash          the pipeline raised (it must never; adapters fail soft)
  money          premium.net / premium.final against `expect` (net_premium, total_premium) when given: correct / flagged / SILENT_WRONG
  sections       layout, whether the section premiums tie to the net premium, how many sections are ok / check
  addons         rows, keep/drop/pending, auto-eligible, and UNFLAGGED kept rows (invariant: 0)
Where a full answer-key case exists (app/cases/<case>.json) the field and section scorers run too.

Regression = a new crash, more SILENT_WRONG, any UNFLAGGED row, or fewer correct values than the baseline. The baseline holds counts only
(no values), but it is still kept private and git-ignored.
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from .envelope import SHOWN
from .pipeline import run
from .score import ROOT, HERE, _abs, load_cases

BASELINE = HERE / "baseline.local.json"
TOL = 1.5


def _match(v, expected) -> bool:
    return v is not None and any(e is not None and abs(float(v) - float(e)) <= TOL for e in expected)


def money_checks(fields: dict, expect: dict) -> dict:
    out = {"correct": 0, "flagged": 0, "SILENT_WRONG": 0, "missing": 0, "detail": {}}
    for fname, ekey in (("premium.net", "net_premium"), ("premium.final", "total_premium")):
        exp = [x for x in expect.get(ekey, []) if x is not None]
        if not exp:
            continue
        f = fields.get(fname)
        if f is None:
            v = "missing"
        elif f.status in SHOWN:
            v = "correct" if _match(f.value, exp) else "SILENT_WRONG"
        else:
            v = "flagged"
        out[v] += 1
        out["detail"][fname] = (v, f.value if f else None, exp[0])
    return out


def run_case(name: str, cfg: dict) -> dict:
    c = cfg[name]
    r: dict = {"case": name, "crash": None}
    try:
        res = run(_abs(c["slip"]), _abs(c["quote"]), _abs(c.get("imd")))
    except Exception as e:
        r["crash"] = f"{type(e).__name__}: {e}"
        r["trace"] = traceback.format_exc()
        return r
    f = {x.field: x for x in res["fields"]}
    r["fields"] = {k: x.status for k, x in f.items()}
    r["field_counts"] = {"ok": sum(1 for x in f.values() if x.status in SHOWN), "flagged": sum(1 for x in f.values() if x.status not in SHOWN)}
    r["money"] = money_checks(f, c.get("expect", {}))
    sec = res.get("sections")
    if sec and sec.get("layout"):
        sv = [s for s in sec["sections"].values() if s["status"] != "not_found"]
        r["sections"] = {"layout": sec["layout"], "tie": bool(sec.get("tie")), "ok": sum(1 for s in sv if s["status"] in SHOWN), "check": sum(1 for s in sv if s["status"] not in SHOWN)}
    else:
        r["sections"] = {"layout": None, "tie": False, "ok": 0, "check": 0}
    rows = res["addons"]
    kept = [a for a in rows if a["decision"] == "keep"]
    r["addons"] = {"rows": len(rows), "keep": len(kept), "drop": sum(1 for a in rows if a["decision"] == "drop"),
                   "pending": sum(1 for a in rows if a["decision"] == "pending"), "auto": sum(1 for a in kept if a["auto_eligible"]),
                   "unflagged": sum(1 for a in kept if not a["auto_eligible"] and not a["needs_review"])}
    r["variant"] = res["variant"]
    r["warnings"] = res["warnings"]
    if (ROOT / "app" / "cases" / f"{name}.json").exists():
        from . import score, section_score
        t = score.score_case(name, cfg)["tally"]
        s = section_score.score_case(name, cfg)["tally"]
        r["key"] = {"fields": t, "sections": s}
    return r


def summarise(r: dict) -> dict:
    """The counts that the baseline tracks."""
    if r["crash"]:
        return {"crash": True}
    m = r["money"]
    k = r.get("key")
    silent = m["SILENT_WRONG"] + (k["fields"]["SILENT_WRONG"] + k["sections"]["SILENT_WRONG"] if k else 0)
    correct = m["correct"] + (k["fields"]["correct"] + k["sections"]["correct"] if k else 0)
    return {"crash": False, "silent_wrong": silent, "correct": correct, "unflagged": r["addons"]["unflagged"], "rows": r["addons"]["rows"]}


def show(r: dict) -> None:
    if r["crash"]:
        print(f"\n== {r['case']}   CRASH {r['crash']}")
        print(r["trace"])
        return
    m, s, a = r["money"], r["sections"], r["addons"]
    print(f"\n== {r['case']}   fields ok {r['field_counts']['ok']} flagged {r['field_counts']['flagged']}"
          + (f"   variant {r['variant']}" if r["variant"] else ""))
    for k, (v, got, exp) in m["detail"].items():
        print(f"   money {k:14} {v:13} got={got}  expected={exp}")
    print(f"   sections layout={s['layout']} tie={s['tie']} ok={s['ok']} check={s['check']}")
    print(f"   add-ons rows={a['rows']} keep={a['keep']} drop={a['drop']} pending={a['pending']} auto={a['auto']} UNFLAGGED={a['unflagged']}")
    if r.get("key"):
        print(f"   answer key: fields {r['key']['fields']}  sections {r['key']['sections']}")
    for w in r["warnings"]:
        if "wording/clauses" not in w:
            print(f"   ! {w[:140]}")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    update = "--update" in argv
    names_arg = [a for a in argv if not a.startswith("--")]
    cfg = load_cases()
    names = names_arg or sorted(n for n in cfg if n != "demo_laghu") + ["demo_laghu"]
    results = [run_case(n, cfg) for n in names]
    for r in results:
        show(r)
    now = {r["case"]: summarise(r) for r in results}
    base = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    if update:
        base.update(now)
        BASELINE.write_text(json.dumps(base, indent=1, sort_keys=True))
        print(f"\nbaseline updated ({len(now)} cases) -> {BASELINE.name}")
        return 0
    bad = []
    for n, c in now.items():
        if c.get("crash"):
            bad.append(f"{n}: crashed")
            continue
        if c["unflagged"]:
            bad.append(f"{n}: {c['unflagged']} unflagged kept add-on rows")
        b = base.get(n)
        if b and not b.get("crash"):
            if c["silent_wrong"] > b["silent_wrong"]:
                bad.append(f"{n}: silent wrong {b['silent_wrong']} -> {c['silent_wrong']}")
            if c["correct"] < b["correct"]:
                bad.append(f"{n}: correct {b['correct']} -> {c['correct']}")
        elif not b:
            print(f"\nnote: {n} has no baseline yet (run with --update)")
    total_silent = sum(c.get("silent_wrong", 0) for c in now.values())
    print(f"\nTOTAL SILENT_WRONG = {total_silent}   regressions: {len(bad)}")
    for x in bad:
        print("  REGRESSION", x)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
