"""Intermediary (IMD) master lookup. Code match is exact; a name-only match is a proposal that needs confirmation."""
import re

from pyxlsb import open_workbook

_CACHE = {}


def _load(path):
    if path not in _CACHE:
        rows = []
        with open_workbook(path) as wb, wb.get_sheet(wb.sheets[0]) as sh:
            for r in sh.rows():
                v = [c.v for c in r] + [None] * 5
                if v[0] and str(v[0]) != "TXT_INTERMEDIARY_CD":
                    rows.append({"code": str(v[0]), "name": str(v[1] or ""), "email": v[2],
                                 "phone": _digits(v[3]), "mobile": _digits(v[4])})
        _CACHE[path] = rows
    return _CACHE[path]


def _digits(x):
    if x is None:
        return None
    s = str(int(x)) if isinstance(x, float) else str(x)
    return re.sub(r"\D", "", s) or None


_STOP = {"pvt", "private", "ltd", "limited", "llp", "india", "insurance", "broker", "brokers", "broking", "services",
         "and", "the", "of"}


def _tokens(name):
    return {t for t in re.sub(r"[^a-z0-9 ]", " ", name.lower()).split() if t not in _STOP}


def lookup(path, code=None, name=None):
    """-> {'status': exact_code|name_candidate|ambiguous|not_found, 'record': {...}|None, 'candidates': [...]}"""
    rows = _load(path)
    if code:
        for r in rows:
            if r["code"] == code:
                return {"status": "exact_code", "record": r, "candidates": []}
    if name:
        want = _tokens(name)
        brokers = [r for r in rows if r["code"].startswith("BRC")]  # a name containing 'broker' implies BRC; keep BRC only
        hits = [r for r in brokers if want and want <= _tokens(r["name"])]  # every distinctive word must be present
        if len(hits) == 1:
            return {"status": "name_candidate", "record": hits[0], "candidates": hits}
        if hits:
            return {"status": "ambiguous", "record": None, "candidates": hits[:5]}
    return {"status": "not_found", "record": None, "candidates": []}
