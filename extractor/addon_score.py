"""Score add-on extraction against the issued policy's add-on clauses.

  python -m extractor.addon_score mann valmet shreeji

Truth = the clauses the issued policy actually prints in its annexures (policy_rows), resolved to library titles with the same
matcher. That is the clause bank's own "truth" and is optimistic until a person reviews it (the dictionary was partly built from these
cases). Reported per case:
  overlap       library clauses present in both the kept quote rows and the issued policy
  quote_only    kept in the quote, absent from the issued policy (Magma may have dropped them; a person decides)
  policy_only   in the issued policy, not found among the kept quote rows
  unflagged     kept rows that are neither auto-eligible nor carry a review reason  (invariant: must be 0)
  auto_not_in_policy  auto-eligible rows whose clause the policy does not carry (candidates for silent wrong; review each)
"""
from __future__ import annotations

import sys

from .clausebank import api, policy_rows
from .clausebank.resolve import resolve_clause
from .pipeline import run
from .score import _abs, load_cases


def policy_clauses(case: str, spec: dict, idx, aliases) -> tuple[set, list]:
    pol = policy_rows.read(case, _abs(spec["path"]), spec.get("kind", "pdf"))
    found, unresolved = set(), []
    for r in pol["rows"]:
        name = (r.get("name") or "").strip()
        if len(name) < 3:
            continue
        res = resolve_clause(name, idx, aliases, None)
        (found.add(res["clause"]) if res["clause"] else unresolved.append(name))
    return found, unresolved


def score(case: str, cfg: dict) -> dict:
    c = cfg[case]
    res = run(_abs(c["slip"]), _abs(c["quote"]), _abs(c.get("imd")))
    rows = res["addons"]
    idx, aliases = api.load_library(), api.load_aliases()
    truth, pol_unres = policy_clauses(case, c["policy"], idx, aliases)
    kept = [r for r in rows if r["decision"] == "keep"]
    kept_clauses = {r["clause"] for r in kept if r["clause"]}
    auto = [r for r in kept if r["auto_eligible"]]
    return {
        "case": case, "variant": res["variant"], "rows": len(rows),
        "decisions": {d: sum(1 for r in rows if r["decision"] == d) for d in ("keep", "drop", "pending")},
        "kept_unique_clauses": len(kept_clauses), "policy_clauses": len(truth),
        "overlap": sorted(kept_clauses & truth), "quote_only": sorted(kept_clauses - truth), "policy_only": sorted(truth - kept_clauses),
        "policy_unresolved": pol_unres,
        "unflagged": [r for r in kept if not r["auto_eligible"] and not r["needs_review"]],
        "kept_no_clause": sum(1 for r in kept if not r["clause"]),
        "auto": len(auto), "auto_not_in_policy": sorted({r["clause"] for r in auto} - truth),
        "review_reasons": {k: sum(1 for r in rows if k in r["needs_review"]) for k in sorted({x for r in rows for x in r["needs_review"]})},
        "warnings": [w for w in res["warnings"] if "add-on" in w or "variant" in w],
    }


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cfg = load_cases()
    names = argv or [n for n, v in sorted(cfg.items()) if "policy" in v]
    bad = 0
    for n in names:
        try:
            r = score(n, cfg)
        except Exception as e:
            print(f"\n== {n}   ERROR {type(e).__name__}: {e}")
            bad += 1
            continue
        print(f"\n== {n}   rows {r['rows']} {r['decisions']}" + (f"   variant {r['variant']}" if r["variant"] else ""))
        print(f"  kept clauses {r['kept_unique_clauses']}   policy clauses {r['policy_clauses']}   OVERLAP {len(r['overlap'])}   "
              f"quote_only {len(r['quote_only'])}   policy_only {len(r['policy_only'])}   policy rows with no library clause {len(r['policy_unresolved'])}")
        print(f"  auto-eligible rows {r['auto']}   kept rows without clause {r['kept_no_clause']}   review reasons {r['review_reasons']}")
        print(f"  UNFLAGGED kept rows (must be 0): {len(r['unflagged'])}   auto-eligible clauses not in policy: {len(r['auto_not_in_policy'])}")
        for t in r["auto_not_in_policy"][:15]:
            print(f"     auto not in policy: {t}")
        for t in r["policy_only"][:15]:
            print(f"     policy only: {t}")
        for w in r["warnings"]:
            print(f"  ! {w}")
        bad += len(r["unflagged"])
    print(f"\nTOTAL UNFLAGGED = {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
