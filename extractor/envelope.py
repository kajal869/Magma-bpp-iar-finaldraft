"""Common field envelope (INTEGRATION_HANDOVER 4.1) and the field catalogue shared by adapters, resolver and scorer.

status: ok | derived | conflict | check_failed | not_found | not_stated | check
  "shown"   = ok, derived  (a value is presented as usable; a wrong shown value is a SILENT WRONG)
  "flagged" = everything else (the user must look)
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

SHOWN = {"ok", "derived"}

# field -> (kind, group)   kind: text | name | address | date | money | code
FIELDS = {
    "insured.name": ("name", "identity"),
    "insured.gstin": ("code", "identity"),
    "insured.address": ("address", "identity"),
    "period.start": ("date", "identity"),
    "period.end": ("date", "identity"),
    "intermediary.name": ("name", "identity"),
    "intermediary.code": ("code", "identity"),
    "product.name": ("text", "identity"),
    "premium.net": ("money", "money"),
    "premium.final": ("money", "money"),
    "premium.terrorism": ("money", "money"),
    "hypothecation": ("text", "identity"),
}


@dataclass
class Field:
    field: str
    value: object = None
    status: str = "not_found"
    source: dict = field(default_factory=dict)       # {tool, sheet, cell, method}
    alternatives: list = field(default_factory=list)  # [{value, source}]
    note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def norm_text(s) -> str:
    s = re.sub(r"[^A-Z0-9]", "", str(s or "").upper())
    return s


_STOP = r"\b(PRIVATE|PVT|LIMITED|LTD|THE)\b"


def norm_name(s) -> str:
    s = re.sub(r"[^A-Z0-9 ]", "", str(s or "").upper())
    return re.sub(r"\s+", "", re.sub(_STOP, " ", s))


def same(kind: str, a, b, tol: float = 1.0) -> bool:
    """Value equality per kind; used by the resolver and the scorer."""
    if a in (None, "") or b in (None, ""):
        return False
    if kind == "money":
        try:
            return abs(float(a) - float(b)) <= tol
        except (TypeError, ValueError):
            return False
    if kind == "date":
        return str(a)[:10] == str(b)[:10]
    if kind == "name":
        return norm_name(a) == norm_name(b)
    if kind == "address":
        x = norm_text(" ".join(a) if isinstance(a, list) else a)
        y = norm_text(" ".join(b) if isinstance(b, list) else b)
        return x == y
    return norm_text(a) == norm_text(b)
