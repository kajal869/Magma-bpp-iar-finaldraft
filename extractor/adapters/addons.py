"""Add-on / clause adapter: Kajal's row reader + remark classifier + library matcher (extractor/clausebank).

Returns (rows, warnings). Rows follow the common add-on row format; `needs_review` is empty only for rows that are dropped or auto-eligible.
Floyd's heading reader (fallback for layouts without a recognisable table) is not wired: when no table is found the caller gets a
warning, never an empty list passed off as "no add-ons".
"""
from __future__ import annotations

from ..clausebank import api


def read(path: str, variant: str | None = None) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    try:
        rows, w = api.extract_rows(path, variant)
    except Exception as e:
        return [], [f"add-ons could not be read: {type(e).__name__}: {e}"]
    warnings += w
    if not rows:
        warnings.append("no add-on / clause table was recognised in the quote; check it by hand (this does not mean there are none)")
        return [], warnings
    try:
        out = api.match_rows(rows)
    except FileNotFoundError as e:
        return [], warnings + [f"clause library not found: {e}"]
    if not api.wording_ids():
        warnings.append("app/wording/clauses.json not found: clause titles are matched but wording ids are empty")
    return out, warnings
