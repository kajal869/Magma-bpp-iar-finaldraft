"""Run-time clause resolution, vendored from Kajal's clausebank (backtrack.resolve_clause/confidence, library.Index).
Unchanged logic; only the imports differ. Exact -> alias -> remark -> fuzzy; fuzzy is never auto-accepted and ambiguity is reported."""
from .common import AUTO_ACCEPT, FUZZY_MARGIN, FUZZY_THRESHOLD, fullkey, norm
from .match import sim

CONF = {"exact": 0.95, "alias": 0.90, "remark": 0.85, "split": 0.80}


def resolve_clause(name, idx, aliases, cited=None):
    """Quote/policy name (and optional remark pointer) -> dict(clause, method, score, ambiguous, candidates).
    aliases: {normalised phrase: [clause titles]} (only the statuses the caller wants to trust)."""
    out = {"clause": None, "method": None, "score": 0.0, "ambiguous": [], "candidates": []}
    def cited_clause():
        if not cited:
            return None
        for variant in (cited, cited + " Clause", cited + " Cover"):
            t2, _ = idx.exact(variant)
            if t2:
                return t2
            a2 = aliases.get(norm(variant), [])
            if len(a2) == 1:
                return a2[0]
        return None

    t, amb = idx.exact(name)
    if t:
        rc = cited_clause()
        if rc and rc != t:       # the name says one clause, the insurer's remark names another: a person decides
            return {**out, "clause": t, "method": "exact", "score": 1.0, "ambiguous": [t, rc]}
        return {**out, "clause": t, "method": "exact", "score": 1.0}
    if amb:
        out["ambiguous"] = amb
    a = aliases.get(norm(name), [])
    if len(a) == 1:
        rc = cited_clause()
        if rc and rc != a[0]:
            return {**out, "clause": a[0], "method": "alias", "score": 1.0, "ambiguous": [a[0], rc]}
        return {**out, "clause": a[0], "method": "alias", "score": 1.0}
    if len(a) > 1:
        out["ambiguous"] = sorted(set(out["ambiguous"]) | set(a))
    if cited:
        for variant in (cited, cited + " Clause", cited + " Cover"):
            t, amb = idx.exact(variant)
            if t:
                return {**out, "clause": t, "method": "remark", "score": 1.0}
            a = aliases.get(norm(variant), [])
            if len(a) == 1:
                return {**out, "clause": a[0], "method": "remark", "score": 1.0}
    cand = sorted(((max(sim(name, ti), sim(cited, ti) if cited else 0.0), ti) for ti in idx.titles), key=lambda x: (-x[0], x[1]))[:3]
    out["candidates"] = [(round(s, 2), ti) for s, ti in cand]
    if cand and cand[0][0] >= FUZZY_THRESHOLD and (len(cand) < 2 or cand[0][0] - cand[1][0] >= FUZZY_MARGIN or sim(cand[0][1], cand[1][1]) >= 0.98):
        return {**out, "clause": cand[0][1], "method": "fuzzy", "score": cand[0][0]}
    return out


def confidence(method, score=1.0):
    if method == "fuzzy":
        return round(min(score, AUTO_ACCEPT - 0.01), 3)      # fuzzy is never auto-accepted
    return CONF.get(method, 0.0)


class Index:
    """Lookup helpers over a library. Identity is the full-title key; matching uses the looser norm() key, which can be ambiguous
    (several titles share it): ambiguity is reported, never resolved by guessing."""

    def __init__(self, lib):
        self.lib = lib
        self.by_key = {}
        self.by_nkey = {}
        for c in lib["clauses"]:
            self.by_key.setdefault(c["key"], c)
            self.by_nkey.setdefault(c["nkey"], []).append(c)
        self.titles = [c["title"] for c in lib["clauses"]]
        self.pool = [(c["title"], c["title"]) for c in lib["clauses"]]

    def exact(self, name):
        """-> (title | None, ambiguous_titles). A full-title match wins; a loose match only if it is unique."""
        c = self.by_key.get(fullkey(name))
        if c:
            return c["title"], []
        m = self.by_nkey.get(norm(name), [])
        if len(m) == 1:
            return m[0]["title"], []
        return None, [x["title"] for x in m]
