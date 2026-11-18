"""Quote identity block: the insured's name and address as the quote states them, for cross-checking against the closing slip.

The slip stays the source of the printed values (slip beats quote for identity). This module only READS the quote's own statement so that a
quote written for a different insured, or with a different address, is noticed instead of silently ignored.
"""
from __future__ import annotations

import re

from ..envelope import Field
from ..legacy.grid import load, norm

NAME_LABELS = re.compile(r"^(name of (the )?(insured|client|customer)|insured'?s?\s*name|name)$")
ADDR_LABELS = re.compile(r"^(insured'?s?\s*)?(communication|correspondence|mailing|insured)?\s*address$|^insured'?s? communication address$")
NOISE = {"PRIVATE", "PVT", "LIMITED", "LTD", "THE", "LLP", "AND", "OF", "INDIA", "CO", "COMPANY", "M", "S", "MS", "INC", "CORP", "CORPORATION"}


def _tokens(s: str, drop_noise: bool = True) -> set[str]:
    s = re.sub(r"\([^)]*\)", " ", str(s or ""))                       # "(Including all subsidiary companies ...)"
    s = re.sub(r"\bM\s*/\s*S\.?", " ", s, flags=re.I)                   # "M/s."
    toks = re.sub(r"[^A-Z0-9 ]", " ", s.upper().replace("'", "")).split()
    return {t for t in toks if not (drop_noise and t in NOISE)}


def similarity(a: str, b: str, noise: bool = True) -> float:
    """Share of the smaller token set found in the larger (0..1). Order, punctuation, M/s, Pvt/Ltd and bracketed text are ignored."""
    x, y = _tokens(a, noise), _tokens(b, noise)
    if not x or not y:
        return 0.0
    return len(x & y) / min(len(x), len(y))


def read(path: str) -> dict:
    """-> {'name': (value, sheet, cell) | None, 'address': (...) | None}. First visible sheet holding the label wins."""
    out = {"name": None, "address": None}
    for sh in load(path):
        if not sh.visible:
            continue
        for rn, cells in sh.rows:
            if rn > 60:
                break
            for i, (cn, v) in enumerate(cells):
                if not isinstance(v, str) or len(v) > 40:
                    continue
                t = norm(v)
                key = "name" if NAME_LABELS.match(t) else ("address" if ADDR_LABELS.match(t) else None)
                if key and out[key] is None:
                    nxt = next(((c, x) for c, x in cells[i + 1:] if isinstance(x, str) and len(x) > 2), None)
                    if nxt:
                        out[key] = (nxt[1], sh.name, f"R{rn}C{nxt[0]}")
        if out["name"] and out["address"]:
            break
    return out


def cross_check(quote_path: str, slip_name, slip_address) -> tuple[list[Field], list[str], list[dict]]:
    """-> (fields to feed the resolver, warnings, cross-check rows).
    A field is emitted only when the quote disagrees (so agreeing cases keep their current statuses); the resolver then keeps the slip value, flags
    it `check` and shows the quote's value as the alternative."""
    fields, warnings, rows = [], [], []
    try:
        q = read(quote_path)
    except Exception as e:
        return [], [f"quote identity block could not be read: {type(e).__name__}: {e}"], []
    nm = q["name"]
    if nm and slip_name:
        sim = similarity(slip_name, nm[0])
        ok = sim >= 0.6
        rows.append({"field": "insured.name", "slip": slip_name, "quote": nm[0], "similarity": round(sim, 2), "agree": ok})
        if not ok:
            src = {"tool": "quote", "sheet": nm[1], "cell": nm[2], "method": "label"}
            fields.append(Field("insured.name", nm[0], "ok", src))
            warnings.append(f"The quote names a different insured ('{nm[0]}') from the closing slip ('{slip_name}'). Check that both files belong to the same case.")
    ad = q["address"]
    if ad and slip_address:
        a = " ".join(slip_address) if isinstance(slip_address, list) else slip_address
        sim = similarity(a, ad[0], noise=False)
        ok = sim >= 0.5
        rows.append({"field": "insured.address", "slip": a, "quote": ad[0], "similarity": round(sim, 2), "agree": ok})
        if not ok:
            warnings.append(f"Insured address differs between the closing slip and the quote (quote: '{ad[0][:90]}'); the closing slip address is used.")
    return fields, warnings, rows
