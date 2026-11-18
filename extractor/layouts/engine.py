"""Order of attack for a quote's sections: matching profile -> (caller's built-in readers) -> generic discovery -> unsupported.

apply_profiles(sheets, net)  try stored profiles best-overlap first; a profile counts only if its read verifies (premiums tie to net)
discover(sheets, net)        run the generic recipes; save an auto profile when the read verifies
taught_overrides(sheets)     cells a person taught always win for their field, and are labelled as such
"""
from __future__ import annotations

from . import store
from .common import h, shape
from .fingerprint import fingerprint, overlap
from .recipes import TIE, find_table, read_matrix, read_scalars, read_summed, read_table, resolve_cell

MIN_OVERLAP = 0.5


def _verify(res: dict, net: float | None) -> tuple[bool, float | None]:
    """Section premiums must add up to the net premium (the sheet's own, else the resolved one)."""
    use = res.get("net") if res.get("net") is not None else net
    total = sum((d["premium"] or 0.0) for d in res["sections"].values())
    if use is None:
        return False, None
    return abs(total - use) <= max(TIE, abs(use) * 1e-6), use


def _run_recipe(sheets, rec: dict, net=None):
    """Apply one stored recipe: the sheet of the recorded shape first, then any visible sheet; the recipe's own spec must still match."""
    ordered = sorted((s for s in sheets if s.visible), key=lambda s: h(shape(s.name)) != rec.get("sheet"))
    for s in ordered:
        if rec["type"] == "labelled_table":
            t = find_table(s, rec["spec"])
            r = read_table(s, t) if t else None
        elif rec["type"] == "summed_table":
            r = read_summed(s, net)
        else:
            r = read_matrix(s)
        if r:
            return r, s
    return None


def _result(res, sheet, how: dict):
    ok, use = _verify(res, how.get("net"))
    res["verified"], res["net_used"] = ok, use
    res["sheet"] = sheet
    res["layout_info"] = how
    return res


def apply_profiles(sheets, net=None):
    fp = fingerprint(sheets)
    ranked = sorted(((overlap(set(p.get("fingerprint", [])), fp), p) for p in store.list_profiles()), key=lambda x: -x[0])
    for ov, p in ranked:
        if ov < MIN_OVERLAP:
            break
        for rec in p.get("recipes", []):
            if rec["type"] in ("labelled_table", "location_matrix", "summed_table"):
                got = _run_recipe(sheets, rec, net)
                if got:
                    res, sh = got
                    out = _result(res, sh, {"profile": p["id"], "source": p.get("source", "learned"), "overlap": round(ov, 2), "net": net})
                    if out["verified"]:
                        store.touch(p["id"], True)
                        return out
        store.touch(p["id"], False)
    return None


def discover(sheets, net=None, save=True):
    """Try every generic recipe on every visible sheet. Returns the first verified read, else the best unverified one (shown as check)."""
    best = None
    for s in sheets:
        if not s.visible:
            continue
        for kind in ("labelled_table", "summed_table", "location_matrix"):
            if kind == "labelled_table":
                t = find_table(s)
                r = read_table(s, t) if t else None
                rec = {"type": "labelled_table", "sheet": h(shape(s.name)), "spec": t["spec"]} if t else None
            elif kind == "summed_table":
                r = read_summed(s, net)
                rec = {"type": "summed_table", "sheet": h(shape(s.name))} if r else None
            else:
                r = read_matrix(s)
                rec = {"type": "location_matrix", "sheet": h(shape(s.name))} if r else None
            if not r:
                continue
            out = _result(r, s, {"profile": None, "source": "discovered", "overlap": None, "net": net})
            out["recipe"] = rec
            if out["verified"]:
                if save:
                    fp = sorted(fingerprint(sheets))
                    pid = "p_" + h("|".join(fp))
                    old = store.get(pid)               # never overwrite a profile a person taught: add the recipe next to the taught cells
                    prof = store.save({**old, "recipes": old["recipes"] + ([rec] if rec not in old["recipes"] else [])} if old and old.get("_dir") == "learned"
                                      else {"id": pid, "source": "auto", "fingerprint": fp, "recipes": [rec], "uses": 0})
                    out["layout_info"]["profile"] = prof["id"]
                    out["layout_info"]["saved"] = True
                return out
            best = best or out
    return best


def taught_overrides(sheets) -> dict:
    """{target: {value, ref, sheet, profile}} from cell recipes of every profile whose fingerprint matches this workbook."""
    fp = fingerprint(sheets)
    out: dict = {}
    for p in store.list_profiles():
        if overlap(set(p.get("fingerprint", [])), fp) < MIN_OVERLAP:
            continue
        for rec in p.get("recipes", []):
            if rec["type"] == "cell":
                got = resolve_cell(sheets, rec)
                if got:
                    out[rec["target"]] = {"value": got[0], "ref": got[1], "sheet": got[2], "profile": p["id"]}
    return out


def scalars(sheets) -> dict:
    return read_scalars(sheets)
