from __future__ import annotations

import hashlib
import re

from openpyxl.utils import get_column_letter

from ..legacy.grid import is_num, norm


def h(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def label_norm(v) -> str:
    """Normalised label text: lower case, digits -> '#', single spaces. Used for matching and (hashed) fingerprints."""
    t = re.sub(r"\s+", " ", str(v).replace("\xa0", " ")).strip().lower()
    return re.sub(r"\d+(?:[.,]\d+)*", "#", t)


def shape(name: str) -> str:
    """A sheet name reduced to its shape (digits removed, punctuation dropped): the stable part of 'RFQ Option II' / 'Plant 2'."""
    return re.sub(r"[^a-z]+", " ", name.lower()).strip()


def ref(col: int, row: int) -> str:
    return f"{get_column_letter(col)}{row}"


def col_from_ref(r: str) -> tuple[int, int]:
    from openpyxl.utils.cell import coordinate_from_string, column_index_from_string
    c, row = coordinate_from_string(r)
    return column_index_from_string(c), row


def cells(sheet):
    """sheet.rows -> {row: {col: value}}"""
    return {rn: dict(cs) for rn, cs in sheet.rows}


__all__ = ["h", "label_norm", "shape", "ref", "col_from_ref", "cells", "is_num", "norm"]
