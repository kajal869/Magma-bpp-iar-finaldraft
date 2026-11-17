"""Show what the extractor reads from any closing slip + quote pair (no answer key needed).

  python -m extractor.inspect_pair SLIP.xlsx QUOTE.xlsx [--imd IMD.xlsb] [--addons] [--json out.json]

Prints each field with its status and source, the sections with their tie-out, the terms, and an add-on summary (all rows with --addons).
--json writes the full generated case JSON (private data: keep it out of Git).
"""
from __future__ import annotations

import argparse
import json

from .build_case import assemble
from .pipeline import run


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slip")
    ap.add_argument("quote")
    ap.add_argument("--imd")
    ap.add_argument("--addons", action="store_true", help="list every add-on row")
    ap.add_argument("--json", help="write the generated case JSON here")
    a = ap.parse_args(argv)
    res = run(a.slip, a.quote, a.imd)
    print("FIELDS")
    for f in res["fields"]:
        src = f.source or {}
        where = f"{src.get('tool', '')}{':' + src['sheet'] if src.get('sheet') else ''}{'!' + src['cell'] if src.get('cell') else ''}"
        alts = f"  alternatives={[x['value'] for x in f.alternatives]}" if f.alternatives else ""
        print(f"  {f.field:20} {f.status:12} {str(f.value)[:48]:48} {where}{alts}")
        if f.note:
            print(f"  {'':20} {'':12} note: {f.note[:110]}")
    sec = res.get("sections")
    print(f"\nSECTIONS  layout={sec and sec['layout']}  tie={sec and sec.get('tie')}  variant={res['variant']}")
    for n, s in (sec["sections"].items() if sec else []):
        if s["sum_insured"] is not None or s["premium"] is not None:
            print(f"  {n:2} {s['status']:8} SI={s['sum_insured']}  premium={s['premium']}  {s['note'][:80]}")
    if sec:
        t = sec["terms"]
        print(f"  terms: conditions {{{', '.join(f'S{k}:{len(v)}' for k, v in sorted(t['conditions'].items()))}}}  deductibles {{{', '.join(f'S{k}:{len(v)}' for k, v in sorted(t['deductibles'].items()))}}}  all-sections lines {len(t['all'])}")
    rows = res["addons"]
    kept = [r for r in rows if r["decision"] == "keep"]
    print(f"\nADD-ONS  rows={len(rows)}  keep={len(kept)}  drop={sum(r['decision'] == 'drop' for r in rows)}  pending={sum(r['decision'] == 'pending' for r in rows)}  "
          f"auto={sum(r['auto_eligible'] for r in kept)}  needs review={sum(bool(r['needs_review']) for r in rows if r['decision'] != 'drop')}")
    if a.addons:
        for r in rows:
            print(f"  {r['decision']:8} {'AUTO' if r['auto_eligible'] else '    '} {r['name'][:40]:40} -> {str(r['clause'])[:40]:40} {r['method'] or '':7} {','.join(r['needs_review'])}")
    print("\nWARNINGS")
    for w in res["warnings"]:
        print("  !", w)
    if a.json:
        case, _ = assemble(res)
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(case, fh, indent=1, ensure_ascii=False, default=str)
        print(f"\ncase JSON written to {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
