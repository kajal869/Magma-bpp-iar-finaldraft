"""Workbook fingerprint: a set of hashes of structural labels and sheet shapes.

No readable text is stored, so a fingerprint can sit in a profile (and in Git) without exposing customer wording. Two quotes of the
same format share most label hashes; values (names, amounts, addresses) vary and rarely recur."""
from __future__ import annotations

import re

from .common import h, label_norm, shape

MAX_TOKENS = 400


def fingerprint(sheets) -> set[str]:
    toks: set[str] = set()
    for s in sheets:
        toks.add("S:" + h(shape(s.name)))
        for _, cs in s.rows:
            for col, v in cs:
                if col > 12 or not isinstance(v, str):
                    continue
                t = label_norm(v)
                if 2 <= len(t) <= 60 and len(t.split()) <= 8 and not re.search(r"@|https?:", t):
                    toks.add("L:" + h(t))
        if len(toks) > MAX_TOKENS * 2:
            break
    return set(sorted(toks)[:MAX_TOKENS])


def overlap(profile_fp: set[str], fp: set[str]) -> float:
    """Share of the profile's tokens present in this workbook (containment), 0..1."""
    return len(profile_fp & fp) / len(profile_fp) if profile_fp else 0.0
