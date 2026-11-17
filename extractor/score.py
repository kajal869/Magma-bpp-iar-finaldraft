"""Score the pipeline against an answer-key case JSON.

  python -m extractor.score demo_laghu mann valmet shreeji

Per field:
  correct   shown (ok/derived) and equal to the key
  flagged   not shown as ok (conflict / check / not_found ...); `flag_has_truth` says whether the right value was on offer
  missing   the pipeline produced no entry
  SILENT_WRONG  shown as ok/derived but different from the key  (target: 0)

Inputs per case come from extractor/cases.local.json (private, git-ignored); see cases.example.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .envelope import FIELDS, SHOWN, same
from .pipeline import run

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
KEY_PATHS = {"insured.address": "insured.address_lines"}


def _get(d, path):
    for p in path.split("."):
        d = d.get(p) if isinstance(d, dict) else None
    return d


def load_cases() -> dict:
    cfg: dict = {}
    for name in ("cases.example.json", "cases.local.json"):
        p = HERE / name
        if p.exists():
            cfg.update(json.loads(p.read_text(encoding="utf-8")))
    return cfg


def _abs(p):
    if p is None:
        return None
    q = Path(p)
    return str(q if q.is_absolute() else ROOT / q)


def score_case(case: str, cfg: dict) -> dict:
    c = cfg.get(case)
    if not c:
        raise SystemExit(f"{case}: not in cases.example.json / cases.local.json")
    key = json.loads((ROOT / "app" / "cases" / f"{case}.json").read_text(encoding="utf-8"))
    res = run(_abs(c["slip"]), _abs(c["quote"]), _abs(c.get("imd")))
    got = {f.field: f for f in res["fields"]}
    rows, tally = [], {"correct": 0, "flagged": 0, "missing": 0, "SILENT_WRONG": 0}
    for name, (kind, _) in FIELDS.items():
        truth = _get(key, KEY_PATHS.get(name, name))
        f = got.get(name)
        if f is None:
            tally["missing"] += 1
            rows.append((name, "missing", None, truth, ""))
            continue
        if f.status in SHOWN:
            ok = same(kind, f.value, truth)
            verdict = "correct" if ok else "SILENT_WRONG"
        else:
            verdict = "flagged"
            offered = [f.value] + [a["value"] for a in f.alternatives]
            has = any(same(kind, v, truth) for v in offered)
            f.note = (f.note + " | " if f.note else "") + ("right value offered" if has else "right value NOT offered")
        tally[verdict] += 1
        rows.append((name, verdict, f.value, truth, f"{f.status}: {f.note}"))
    return {"case": case, "tally": tally, "rows": rows, "warnings": res["warnings"], "variant": res["variant"], "addons": len(res["addons"])}


def _short(v, n=44):
    s = " ".join(v) if isinstance(v, list) else str(v)
    return s if len(s) <= n else s[: n - 1] + "…"


def print_report(r: dict) -> None:
    t = r["tally"]
    print(f"\n== {r['case']}   correct {t['correct']}  flagged {t['flagged']}  missing {t['missing']}  SILENT_WRONG {t['SILENT_WRONG']}"
          + (f"   variant {r['variant']}" if r["variant"] else ""))
    for name, verdict, got, truth, note in r["rows"]:
        print(f"  {name:20} {verdict:13} got={_short(got):46} key={_short(truth):46} {note}")
    for w in r["warnings"]:
        print(f"  ! {w}")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cfg = load_cases()
    names = argv or sorted(n for n in cfg if (ROOT / "app" / "cases" / f"{n}.json").exists())
    bad = 0
    for n in names:
        try:
            r = score_case(n, cfg)
        except Exception as e:  # one broken case must not hide the others
            print(f"\n== {n}   ERROR {type(e).__name__}: {e}")
            bad += 1
            continue
        print_report(r)
        bad += r["tally"]["SILENT_WRONG"]
    print(f"\nTOTAL SILENT_WRONG = {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
