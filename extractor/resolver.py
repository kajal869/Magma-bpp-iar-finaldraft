"""Resolver: merge envelope fields from several tools into one value + status per field.

Rules (handover 4.1 / E1):
  * identity fields: slip beats quote; money fields: quote beats slip (the slip total is the tie-out anchor).
  * two tools that agree -> ok (never downgraded); disagree -> conflict, both values kept, nothing auto-picked.
  * a field's own status is never upgraded by the resolver, except agreement of two independent tools.
"""
from __future__ import annotations

from .envelope import FIELDS, SHOWN, Field, same

PREFER = {"identity": "slip", "money": "quote"}


def resolve(fields: list[Field]) -> list[Field]:
    by: dict[str, list[Field]] = {}
    for f in fields:
        by.setdefault(f.field, []).append(f)
    out = []
    for name, cands in by.items():
        kind, group = FIELDS.get(name, ("text", "identity"))
        have = [c for c in cands if c.value not in (None, "") and c.status not in ("conflict", "not_found", "not_stated")]
        if not have:
            # nothing usable: keep the most informative flagged candidate (conflict carries alternatives)
            pick = next((c for c in cands if c.status == "conflict"), cands[0])
            out.append(pick)
            continue
        pref = PREFER[group]
        if group == "money" and all(c.source.get("tool") == "slip" for c in have):
            # only the slip states this amount: it is an anchor, not evidence. The slip's "100% premium" can be the net premium (seen on
            # a laghu slip), so it is shown as a check, with whatever the quote offered as alternatives.
            quote_alts = [a for c in cands if c.source.get("tool") == "quote" for a in c.alternatives]
            top = have[0]
            alts = [{"value": top.value, "source": top.source}] + quote_alts
            out.append(Field(name, top.value, "check", top.source, alts, "stated on the closing slip only; the quote did not confirm it (the slip amount may exclude GST)"))
            continue
        have.sort(key=lambda c: 0 if c.source.get("tool") == pref else 1)
        top, rest = have[0], have[1:]
        others = [r for r in rest if r.source.get("tool") != top.source.get("tool")]
        disagree = [r for r in others if not same(kind, top.value, r.value)]
        agree = [r for r in others if same(kind, top.value, r.value)]
        if disagree:
            alts = [{"value": top.value, "source": top.source}] + [{"value": r.value, "source": r.source} for r in disagree]
            out.append(Field(name, None, "conflict", top.source, alts, f"{top.source.get('tool')} and {disagree[0].source.get('tool')} disagree; confirm which is right"))
            continue
        res = Field(name, top.value, top.status, top.source, list(top.alternatives), top.note)
        if agree and top.status in SHOWN:
            res.status = "ok"
            res.note = (res.note + "; " if res.note else "") + f"confirmed by {', '.join(sorted({a.source.get('tool', '?') for a in agree}))}"
        out.append(res)
    return out
