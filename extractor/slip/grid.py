"""Workbook loading: one uniform cell grid for .xlsx and .xls."""
import datetime
import re
from dataclasses import dataclass, field

import openpyxl
import xlrd


@dataclass
class Sheet:
    name: str
    visible: bool
    rows: list = field(default_factory=list)  # [(row_no, [(col_no, value), ...])], non-empty cells only

    def cell(self, r, c):
        for rn, cells in self.rows:
            if rn == r:
                for cn, v in cells:
                    if cn == c:
                        return v
        return None


def clean(v):
    if isinstance(v, str):
        v = v.replace("\xa0", " ").strip()
        return v or None
    return v


def load(path):
    sheets = []
    if str(path).lower().endswith(".xls"):
        wb = xlrd.open_workbook(path)
        for sh in wb.sheets():
            rows = []
            for r in range(sh.nrows):
                cells = []
                for c in range(sh.ncols):
                    cell = sh.cell(r, c)
                    v = cell.value
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        v = xlrd.xldate.xldate_as_datetime(v, wb.datemode)
                    elif cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                        continue
                    v = clean(v)
                    if v is not None:
                        cells.append((c + 1, v))
                if cells:
                    rows.append((r + 1, cells))
            sheets.append(Sheet(sh.name, sh.visibility == 0, rows))
    else:
        wb = openpyxl.load_workbook(path, data_only=True)
        for ws in wb.worksheets:
            rows = []
            for row in ws.iter_rows():
                cells = [(c.column, clean(c.value)) for c in row if clean(c.value) is not None]
                if cells:
                    rows.append((row[0].row, cells))
            sheets.append(Sheet(ws.title, ws.sheet_state == "visible", rows))
    return sheets


def norm(s):
    """Lower-case, collapse whitespace; used for label matching."""
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def find_sheet(sheets, pattern):
    """First visible sheet whose name matches the pattern."""
    for s in sheets:
        if s.visible and re.search(pattern, s.name, re.I):
            return s
    return None
