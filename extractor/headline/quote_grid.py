"""
quote_grid.py v2 - layout-independent extraction of headline fields from broker quotes.

Scope: net premium, GST, total premium, total sum insured, quote number, quote date,
policy period. Closing-slip fields (insured, GST no., address, occupancy, UIN, co-insurance)
and add-ons/clauses are handled by the slip parser and clause matcher, not here.

Principles
  1. Read every cell once, with provenance (sheet, cell, hidden flags, formula).
  2. Use arithmetic to FIND totals, not only to check them.
  3. Labels point to a value (right of the label, or below it for headers-across layouts);
     structure (Total column, proven sums) picks the value when there are several.
  4. Never invent. "ok" only when the evidence is single and the arithmetic does not object.
     Everything else is labelled for review. A layout with no recognised labels says so loudly.

Usage
  python quote_grid.py quote.xlsx [more.xlsx ...]            JSON report per file
  python quote_grid.py --summary quote.xlsx ...               one-line-per-field table
  python quote_grid.py --sheet "@A1" quote.xlsx               choose the live policy variant
  python quote_grid.py learn "Basic Premium" net_premium      teach a new label (labels.json)
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, asdict, field as dc_field
from datetime import datetime, date

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

VERSION = "2.0"
TOL = 1.0
GST_RATE = 0.18
BLOCK_GAP = 3
ERRORS = {"#N/A", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#NULL!"}
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LABELS = os.path.join(HERE, "labels.json")

MONEY = {"net_premium", "total_premium", "total_sum_insured", "gst"}
FIELD_NAMES = ["net_premium", "gst", "total_premium", "total_sum_insured",
               "quote_number", "quote_date", "period_from", "period_to"]
REVIEW_STATUSES = {"conflict", "hidden_only", "not_found", "check_failed", "derived", "unverified"}


# --------------------------------------------------------------------------- values
def to_num(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return None if math.isnan(v) else float(v)
    if isinstance(v, str):
        s = v.strip()
        if s in ERRORS:
            return None
        s = re.sub(r"(?i)rs\.?|inr|₹|/-", "", s).replace(",", "").strip()
        if re.fullmatch(r"-?\d+(\.\d+)?", s):
            return float(s)
    return None


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _yr(y: str) -> int:
    y = int(y)
    return y + 2000 if y < 100 else y


def _mon(s: str):
    return _MONTHS.get(s[:3].lower())


_DATE_PATS = [
    (re.compile(r"\b(\d{4})[./-](\d{1,2})[./-](\d{1,2})\b"),
     lambda m: (int(m[1]), int(m[2]), int(m[3]))),
    (re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})\b"),
     lambda m: (_yr(m[3]), int(m[2]), int(m[1]))),
    # 23-Jan-26, 01/JAN/2026, 1st April 2026, 23 Jan. 2026
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s./-]*([A-Za-z]{3,9})\.?[\s.,/-]*(\d{4}|\d{2})\b"),
     lambda m: (_yr(m[3]), _mon(m[2]), int(m[1]))),
    # Jan 23, 2026
    (re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b"),
     lambda m: (int(m[3]), _mon(m[1]), int(m[2]))),
]


def to_dates(v) -> list[date]:
    if isinstance(v, datetime):
        return [v.date()]
    if isinstance(v, date):
        return [v]
    if not isinstance(v, str):
        return []
    found = []
    for pat, build in _DATE_PATS:
        for m in pat.finditer(v):
            try:
                y, mo, d = build(m)
                if mo is None or not 1990 <= y <= 2100:
                    continue
                found.append((m.start(), m.end(), date(y, mo, d)))
            except ValueError:
                pass
    found.sort()
    out, last_end = [], -1
    for s, e, d in found:
        if s >= last_end:
            out.append(d)
            last_end = e
    return out


def norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[()\[\]{}:;/\\_.,%@#*'\"|+=-]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# --------------------------------------------------------------------------- labels
BUILTIN = [
    ("net_premium", [r"\bnet premium\b", r"premium (excl|excluding|exclusive of|before|without|w o|wo) ?(of )?(gst|tax|taxes)",
                     r"\bbasic premium\b", r"premium before tax", r"\bnet amount\b"]),
    ("total_premium", [r"\b(total|final|gross) premium\b", r"premium (incl|including|inclusive of|with) ?(of )?(gst|tax|taxes)",
                       r"\btotal payable\b", r"\bamount payable\b", r"\bpremium payable\b", r"\bgrand total premium\b"]),
    ("total_sum_insured", [r"\btotal (sum insured|s i|si)\b", r"\btsi\b", r"grand total.*(sum insured|\bsi\b)",
                           r"\bsum insured total\b", r"\btotal sum assured\b"]),
    ("gst", [r"\b[ics]?gst\b", r"\bservice tax\b", r"\btax(es)?\b"]),
    ("quote_date", [r"\bquot\w* date\b", r"\bdate of quot\w*", r"\bquote dt\b"]),
    ("quote_number", [r"\bquot\w* (no|number|ref|reference|id)\b", r"\bref(erence)? (no|number)\b"]),
    ("period_from", [r"\b(period|policy) (from|start)\b", r"\bstart date\b", r"\binception\b", r"\bfrom date\b"]),
    ("period_to", [r"\b(period|policy) (to|end)\b", r"\b(end|expiry) date\b", r"\bto date\b"]),
    ("policy_period", [r"\bpolicy period\b", r"\bperiod of (insurance|cover)\b", r"\bperiod\b"]),
]


class Labels:
    def __init__(self, path: str = DEFAULT_LABELS):
        self.path = path
        self.learned: dict[str, str] = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.learned = {norm(k): v for k, v in json.load(f).items()}

    def field_for(self, text: str) -> str | None:
        t = norm(text)
        if not t:
            return None
        if t in self.learned:
            return self.learned[t]
        if re.search(r"\brate\b", t):          # "Rate of GST", "Premium rate": never an amount
            return None
        for name, pats in BUILTIN:
            if any(re.search(p, t) for p in pats):
                return name
        return None

    def learn(self, label: str, fieldname: str):
        if fieldname not in FIELD_NAMES + ["policy_period"]:
            raise SystemExit(f"unknown field '{fieldname}'. Use one of: {', '.join(FIELD_NAMES)}")
        raw = {}
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
        raw[label] = fieldname
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)
        print(f"learned: '{label}' -> {fieldname}  ({self.path})")


# --------------------------------------------------------------------------- grid
@dataclass
class Cell:
    sheet: str
    row: int
    col: int
    value: object
    formula: str | None
    sheet_hidden: bool
    row_hidden: bool
    col_hidden: bool

    @property
    def ref(self) -> str:
        return f"{self.sheet}!{get_column_letter(self.col)}{self.row}"

    @property
    def hidden(self) -> bool:
        return self.sheet_hidden or self.row_hidden or self.col_hidden

    @property
    def num(self) -> float | None:
        return to_num(self.value)

    @property
    def text(self) -> str:
        return self.value.strip() if isinstance(self.value, str) else ""


def ensure_xlsx(path: str) -> str:
    if not path.lower().endswith(".xls"):
        return path
    candidates = [shutil.which("soffice"), shutil.which("libreoffice"),
                  r"C:\Program Files\LibreOffice\program\soffice.exe"]
    soffice = next((c for c in candidates if c and os.path.exists(c)), None)
    if not soffice:
        raise RuntimeError(".xls is not supported directly. Open it in Excel and Save As .xlsx, "
                           "or install LibreOffice for automatic conversion.")
    out = tempfile.mkdtemp()
    subprocess.run([soffice, "--headless", "--convert-to", "xlsx", "--outdir", out, path],
                   check=True, capture_output=True, timeout=180)
    conv = os.path.join(out, os.path.splitext(os.path.basename(path))[0] + ".xlsx")
    if not os.path.exists(conv):
        raise RuntimeError("LibreOffice conversion of .xls failed")
    return conv


class Grid:
    def __init__(self, path: str):
        self.path = path
        real = ensure_xlsx(path)
        wb_v = load_workbook(real, data_only=True)
        wb_f = load_workbook(real, data_only=False)
        self.cells: dict[tuple[str, int, int], Cell] = {}
        self.sheets: list[str] = []
        self.hidden_sheets: set[str] = set()
        self.warnings: list[str] = []
        for ws in wb_v.worksheets:
            wf = wb_f[ws.title]
            hidden = ws.sheet_state != "visible"
            if hidden:
                self.hidden_sheets.add(ws.title)
            self.sheets.append(ws.title)
            hidden_cols = {k for k, d in ws.column_dimensions.items() if d.hidden}
            for row in ws.iter_rows():
                for c in row:
                    f = wf.cell(c.row, c.column).value
                    formula = f if isinstance(f, str) and f.startswith("=") else None
                    if c.value is None and formula is None:
                        continue
                    if c.value is None and formula:
                        self.warnings.append(f"{ws.title}!{c.coordinate} has a formula but no stored result: "
                                             "open the file in Excel, save, and rerun")
                    self.cells[(ws.title, c.row, c.column)] = Cell(
                        ws.title, c.row, c.column, c.value, formula, hidden,
                        bool(ws.row_dimensions[c.row].hidden),
                        get_column_letter(c.column) in hidden_cols)
            for rng in ws.merged_cells.ranges:
                top = self.cells.get((ws.title, rng.min_row, rng.min_col))
                if top and top.text:
                    for r in range(rng.min_row, rng.max_row + 1):
                        for col in range(rng.min_col, rng.max_col + 1):
                            self.cells.setdefault((ws.title, r, col), Cell(
                                ws.title, r, col, top.value, None, top.sheet_hidden,
                                top.row_hidden, top.col_hidden))
        self._by_row: dict[tuple[str, int], list[Cell]] = {}
        self._by_sheet: dict[str, list[Cell]] = {}
        for c in self.cells.values():
            self._by_row.setdefault((c.sheet, c.row), []).append(c)
            self._by_sheet.setdefault(c.sheet, []).append(c)
        for v in self._by_row.values():
            v.sort(key=lambda c: c.col)

    def view(self, sheets: list[str]) -> "Grid":
        g = copy.copy(self)
        g.sheets = [s for s in self.sheets if s in sheets]
        return g

    def row(self, sheet: str, r: int) -> list[Cell]:
        return self._by_row.get((sheet, r), [])

    def sheet_cells(self, sheet: str) -> list[Cell]:
        return self._by_sheet.get(sheet, [])

    def header_at(self, sheet: str, row: int, col: int, depth: int = 40) -> str:
        for r in range(row - 1, max(0, row - depth), -1):
            c = self.cells.get((sheet, r, col))
            if c and c.text and c.num is None and not to_dates(c.value):
                return c.text
        return ""

    def header_above(self, cell: Cell) -> str:
        return self.header_at(cell.sheet, cell.row, cell.col)

    def label_left(self, cell: Cell) -> str:
        return " ".join(c.text for c in self.row(cell.sheet, cell.row)
                        if c.col < cell.col and c.text and c.num is None)


# --------------------------------------------------------------------------- arithmetic totals
@dataclass
class SumRelation:
    total_ref: str
    total: float
    parts: list[str]
    direction: str
    labelled: bool
    via_formula: bool
    sheet: str = ""
    row: int = 0
    col: int = 0
    first: int = 0          # first row (column dir) or first col (row dir) of the parts


def _blocks(seq, key):
    blocks, cur, last = [], [], None
    for c in seq:
        k = key(c)
        if last is not None and k - last > BLOCK_GAP + 1:
            blocks.append(cur)
            cur = []
        cur.append(c)
        last = k
    if cur:
        blocks.append(cur)
    return blocks


def _relations(block, direction, grid):
    rels = []
    for i in range(2, len(block)):
        tgt = block[i].num
        if tgt is None or abs(tgt) < 1:
            continue
        s, best = 0.0, None
        for j in range(i - 1, -1, -1):
            s += block[j].num
            if i - j >= 2 and abs(s - tgt) <= TOL:
                best = j
        if best is None:
            continue
        c = block[i]
        lab = grid.label_left(c) if direction == "column" else grid.header_above(c)
        first = block[best].row if direction == "column" else block[best].col
        rels.append(SumRelation(c.ref, tgt, [x.ref for x in block[best:i]], direction,
                                bool(re.search(r"(?i)total", lab)),
                                bool(c.formula and re.search(r"(?i)sum\(|\+", c.formula)),
                                c.sheet, c.row, c.col, first))
    return rels


def find_sum_relations(grid: Grid) -> list[SumRelation]:
    rels = []
    for sh in grid.sheets:
        by_col, by_row = {}, {}
        for c in grid.sheet_cells(sh):
            if c.num is None:
                continue
            by_col.setdefault(c.col, []).append(c)
            by_row.setdefault(c.row, []).append(c)
        for cells in by_col.values():
            for b in _blocks(sorted(cells, key=lambda c: c.row), lambda c: c.row):
                rels += _relations(b, "column", grid)
        for cells in by_row.values():
            for b in _blocks(sorted(cells, key=lambda c: c.col), lambda c: c.col):
                rels += _relations(b, "row", grid)
    return rels


_SKIP_HDR = re.compile(r"rate|%|per mille|\bsr\b|\bs no\b|\bsl no\b|\bno\b|\bpin|code|year|days|months|\bage\b|\bqty\b")


def blank_total_conflicts(grid: Grid, rels: list[SumRelation]) -> list[dict]:
    """A total row is a row where arithmetic proves totals in 2+ columns (or 1 with a Total label).
    In that row, a column that is 0/blank while the rows above it hold amounts is flagged."""
    out = []
    rows: dict[tuple[str, int], list[SumRelation]] = {}
    for r in rels:
        if r.direction == "column":
            rows.setdefault((r.sheet, r.row), []).append(r)
    for (sh, row), rs in rows.items():
        if len(rs) < 2 and not any(r.labelled for r in rs):
            continue
        r0 = min(r.first for r in rs)
        rel_cols = {r.col for r in rs}
        cols = sorted({c.col for c in grid.sheet_cells(sh) if r0 <= c.row < row and c.num is not None})
        for col in cols:
            if col in rel_cols:
                continue
            hdr = grid.header_at(sh, r0, col)
            if not hdr or _SKIP_HDR.search(norm(hdr)):
                continue
            vals = [grid.cells[(sh, rr, col)].num for rr in range(r0, row)
                    if (sh, rr, col) in grid.cells and grid.cells[(sh, rr, col)].num is not None]
            if not vals or max(vals) < 1:
                continue
            cell = grid.cells.get((sh, row, col))
            stated = cell.num if cell else None
            if (stated or 0) == 0 and sum(vals) > 0:
                out.append({"total_ref": f"{sh}!{get_column_letter(col)}{row}", "stated": stated,
                            "sum_of_rows": sum(vals), "column_header": hdr})
    return out


# --------------------------------------------------------------------------- labelled candidates
@dataclass
class Candidate:
    field: str
    value: object
    ref: str | None
    method: str
    hidden: bool
    derived: bool = False
    note: str = ""


def _right_cells(grid, c, labels):
    out = []
    for x in grid.row(c.sheet, c.row):
        if x.col <= c.col:
            continue
        if x.text and x.num is None and not to_dates(x.value) and labels.field_for(x.text):
            if x.text != c.text:           # next label on the same row: stop (merged copies excepted)
                break
            continue
        out.append(x)
    return out


def _below_cells(grid, c, depth=60, allow_text=False):
    out, gap = [], 0
    for r in range(c.row + 1, c.row + depth):
        x = grid.cells.get((c.sheet, r, c.col))
        if x is None or x.value is None:
            gap += 1
            if gap > BLOCK_GAP:
                break
            continue
        if x.text and x.num is None and not to_dates(x.value):
            if x.text == c.text:            # merged label copy
                continue
            if not allow_text:
                break
        out.append(x)
        gap = 0
    return out


def _pick_money(grid, f, nums, totals, direction):
    if len(nums) == 1:
        c = nums[0]
        return [Candidate(f, c.num, c.ref, f"label+{direction}", c.hidden)]
    if direction == "right":
        tot = [c for c in nums if re.search(r"(?i)total", grid.header_above(c))]
        if len(tot) == 1:
            return [Candidate(f, tot[0].num, tot[0].ref, "label+total_column", tot[0].hidden)]
    else:
        tot = [c for c in nums if re.search(r"(?i)total", grid.label_left(c))]
        if len(tot) == 1:
            return [Candidate(f, tot[0].num, tot[0].ref, "label+total_row", tot[0].hidden)]
    tot = [c for c in nums if c.ref in totals]
    if tot:
        c = max(tot, key=lambda c: (c.num, c.row, c.col))
        return [Candidate(f, c.num, c.ref, f"label+proven_sum_{direction}", c.hidden)]
    return [Candidate(f, c.num, c.ref, "label+ambiguous", c.hidden,
                      note=f"header: {grid.header_above(c) or '-'}") for c in nums[:8]]


_GST_RATES = {5.0, 9.0, 12.0, 14.0, 18.0, 28.0}


def labelled_candidates(grid, totals, labels) -> list[Candidate]:
    out = []
    for sh in grid.sheets:
        seen = set()
        for c in sorted(grid.sheet_cells(sh), key=lambda c: (c.row, c.col)):
            if not c.text or c.num is not None or len(c.text) > 80:
                continue
            f = labels.field_for(c.text)
            if not f or (c.row, f) in seen:
                continue
            seen.add((c.row, f))
            inline = c.text.split(":", 1)[1] if ":" in c.text else ""
            right = _right_cells(grid, c, labels)

            if f in MONEY:
                def ok_num(x):
                    n = x.num
                    if n is None or abs(n) < 1:
                        return False
                    return not (f == "gst" and n in _GST_RATES)
                if to_num(inline) is not None:
                    out.append(Candidate(f, to_num(inline), c.ref, "label+inline", c.hidden))
                    continue
                nums = [x for x in right if ok_num(x)]
                direction = "right"
                if not nums:
                    nums = [x for x in _below_cells(grid, c) if ok_num(x)]
                    direction = "below"
                if nums:
                    cands = _pick_money(grid, f, nums, totals, direction)
                    if f == "gst" and re.search(r"to be added|extra|additional|as applicable", norm(c.text)):
                        for k in cands:
                            k.note = "label says GST is added later: value may not be the GST amount"
                    out += cands

            elif f in ("quote_date", "period_from", "period_to", "policy_period"):
                def is_value(x):
                    # a cell that is itself a label for another field ("Quote Date - 11/09/2025") is not a value here
                    g = labels.field_for(x.text) if x.text else None
                    return not (g and g != f and not (f == "policy_period" and g in ("period_from", "period_to")))
                pairs = [(d, c) for d in to_dates(inline or c.text)]     # v3: 'Quote Date - 11/09/2025' in one cell
                for x in right[:4]:
                    if is_value(x):
                        pairs += [(d, x) for d in to_dates(x.value)]
                if not pairs:
                    for x in _below_cells(grid, c)[:2]:
                        if is_value(x):
                            pairs += [(d, x) for d in to_dates(x.value)]
                if not pairs:
                    continue
                if f == "policy_period":
                    out.append(Candidate("period_from", pairs[0][0], pairs[0][1].ref, "label+date", pairs[0][1].hidden))
                    if len(pairs) > 1:
                        out.append(Candidate("period_to", pairs[1][0], pairs[1][1].ref, "label+date", pairs[1][1].hidden))
                else:
                    out.append(Candidate(f, pairs[0][0], pairs[0][1].ref, "label+date", pairs[0][1].hidden))

            elif f == "quote_number":
                opts = [(inline.strip(), c)] + [(str(x.value).strip(), x) for x in right[:3]]
                if not any(re.search(r"\d", v) for v, _ in opts):
                    opts += [(str(x.value).strip(), x) for x in _below_cells(grid, c, allow_text=True)[:1]]
                for v, x in opts:
                    if (re.search(r"\d", v) and len(v) >= 3 and not to_dates(v)
                            and labels.field_for(v) is None):
                        if isinstance(x.value, float) and x.value.is_integer():
                            v = str(int(x.value))
                        out.append(Candidate(f, v, x.ref, "label+text", x.hidden))
                        break
    return out


def arithmetic_candidates(grid, rels, have: set[str]) -> list[Candidate]:
    """Unlabelled column totals become *derived* candidates, chosen by their column header."""
    out = []
    for r in rels:
        if r.direction != "column":
            continue
        hdr = norm(grid.header_at(r.sheet, r.first, r.col))
        if not hdr:
            continue
        cell = grid.cells[(r.sheet, r.row, r.col)]
        if "total_sum_insured" not in have and re.search(r"sum insured|\bsi\b|\btsi\b|\bvalue\b", hdr) \
                and "premium" not in hdr:
            out.append(Candidate("total_sum_insured", r.total, r.total_ref, "arith_total+header",
                                 cell.hidden, derived=True, note=f"column: {hdr}"))
        elif "net_premium" not in have and "premium" in hdr and not re.search(
                r"gst|tax|incl|rate|total premium|gross|final", hdr):
            out.append(Candidate("net_premium", r.total, r.total_ref, "arith_total+header",
                                 cell.hidden, derived=True, note=f"column: {hdr}"))
    # keep only the bottom-most total per column
    best = {}
    for c in out:
        sh, rest = c.ref.rsplit("!", 1)
        col = re.match(r"[A-Z]+", rest)[0]
        key = (c.field, sh, col)
        if key not in best or int(rest[len(col):]) > int(best[key].ref.rsplit("!", 1)[1][len(col):]):
            best[key] = c
    return list(best.values())


# --------------------------------------------------------------------------- resolve
def _same(a, b):
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= TOL
    return a == b


def _distinct(pool):
    d = []
    for c in pool:
        if not any(_same(c.value, x.value) for x in d):
            d.append(c)
    return d


def resolve(cands: list[Candidate]) -> dict:
    res = {}
    for name in FIELD_NAMES:
        cs = [c for c in cands if c.field == name]
        vis = [c for c in cs if not c.hidden]
        hid = [c for c in cs if c.hidden]
        direct = [c for c in vis if not c.derived]
        derived = [c for c in vis if c.derived]
        pool = direct or derived or hid
        if not pool:
            res[name] = {"status": "not_found" if name in MONEY else "not_stated", "value": None}
            continue
        distinct = _distinct(pool)
        entry = {"evidence": [asdict(c) for c in pool]}

        if len(distinct) > 1 and name in MONEY and pool is direct:
            by_sheet = {}
            for c in distinct:
                by_sheet.setdefault(c.ref.rsplit("!", 1)[0], []).append(c)
            if len(by_sheet) >= 3 and all(len(v) == 1 for v in by_sheet.values()):
                vals = {s: v[0] for s, v in by_sheet.items()}
                total = sum(c.value for c in vals.values())
                winner = [c for c in vals.values() if abs(c.value - (total - c.value)) <= TOL]
                if winner:
                    distinct = winner
                    entry["note"] = "summary value equals the sum of the other sheets"
            elif len(by_sheet) >= 2 and all(len(v) == 1 for v in by_sheet.values()):
                entry["suggested_sum_across_sheets"] = sum(v[0].value for v in by_sheet.values())

        if len(distinct) == 1:
            entry["value"] = distinct[0].value
            entry["status"] = ("ok" if pool is direct else "derived" if pool is derived else "hidden_only")
            if any(c.note for c in pool) and entry["status"] == "ok":
                entry["note"] = "; ".join(sorted({c.note for c in pool if c.note}))
        else:
            entry["value"] = None
            entry["status"] = "conflict"
        if vis and hid:
            vv = [c.value for c in vis if isinstance(c.value, float)]
            dis = [asdict(h) for h in hid if isinstance(h.value, float) and all(abs(h.value - v) > TOL for v in vv)]
            if dis:
                entry["hidden_disagrees"] = dis
        res[name] = entry
    return res


def _set(res, name, value, status, note):
    res[name] = {"value": value, "status": status, "note": note,
                 "evidence": res.get(name, {}).get("evidence", [])}


def reconcile(res: dict) -> list[dict]:
    def val(k, statuses=("ok",)):
        e = res[k]
        return e["value"] if e["status"] in statuses else None

    net, gst, tot = val("net_premium"), val("gst"), val("total_premium")

    # v3: "Total premium" cell holds the net and the GST row holds net x 1.18 (Louis Dreyfus case)
    if net is None and gst is not None and tot is not None and res["net_premium"]["status"] == "not_found" \
            and (abs(gst - tot * 1.18) <= 2 or abs(gst - math.floor(tot) * 1.18) <= 2):
        n0, t0 = tot, gst
        _set(res, "net_premium", n0, "derived", "the 'total premium' cell equals GST-row / 1.18: it is the net premium")
        _set(res, "total_premium", t0, "derived", "taken from the GST row, which holds net x 1.18")
        _set(res, "gst", round(t0 - n0, 2), "derived", "total - net")
        net, tot, gst = None, None, None
    # v3: net cell equals the total cell (one cell matched both labels) and GST is known: net = total - GST
    elif res["net_premium"]["status"] in ("ok", "derived", "check_failed") and res["total_premium"]["status"] in ("ok", "derived", "check_failed") \
            and res["net_premium"]["value"] is not None and res["total_premium"]["value"] is not None \
            and abs(res["net_premium"]["value"] - res["total_premium"]["value"]) <= TOL \
            and res["gst"]["value"] is not None and res["gst"]["value"] < res["net_premium"]["value"] / 2:
        t0, g0 = res["total_premium"]["value"], res["gst"]["value"]
        if abs(g0 - GST_RATE * (t0 - g0)) <= 2:
            _set(res, "net_premium", round(t0 - g0, 2), "derived", "net and total were the same cell; net = total - GST")
            _set(res, "total_premium", t0, "derived", "total premium with GST")
            _set(res, "gst", g0, "derived", "GST row (confirmed: 18% of total - GST)")
            net, tot, gst = None, None, None

    # v3: pick the one (net, total) pair that satisfies total = net x 1.18 when the fields conflict
    def cand_vals(k):
        out = []
        for e in res[k].get("evidence", []):
            v = e.get("value")
            if isinstance(v, float) and not any(abs(v - o) <= TOL for o in out):
                out.append(v)
        return out
    if res["net_premium"]["status"] == "conflict" or res["total_premium"]["status"] == "conflict":
        pairs = []
        for n in cand_vals("net_premium"):
            for t in cand_vals("total_premium"):
                if abs(round(math.floor(n) * 1.18) - t) <= 1.5 or abs(n * 1.18 - t) <= 1.5:
                    pairs.append((n, t))
        if len(pairs) == 1:
            n, t = pairs[0]
            _set(res, "net_premium", n, "derived", "only net/total pair on the quote with total = net x 1.18")
            _set(res, "total_premium", t, "derived", "only net/total pair on the quote with total = net x 1.18")
            if res["gst"]["status"] == "conflict":
                g = [v for v in cand_vals("gst") if abs(v - 0.18 * n) <= 2]
                if len(g) == 1:
                    _set(res, "gst", g[0], "derived", "GST candidate that equals 18% of the chosen net")
                else:
                    res["gst"]["status"] = "derived"
                    res["gst"]["value"] = round(t - n, 2)
                    res["gst"]["note"] = "total - net"
            net, tot = None, None
        elif len(pairs) > 1:
            for k in ("net_premium", "total_premium"):
                res[k]["options"] = [{"net": n, "total": t} for n, t in pairs]
                res[k]["note"] = "several net/total pairs are consistent: choose the live sheet or option"

    # GST cell that actually holds the premium including GST (Louis Dreyfus case)
    if net is not None and gst is not None and (abs(gst - net * 1.18) <= 2 or abs(gst - math.floor(net) * 1.18) <= 2):
        res["gst"]["status"] = "check_failed"
        res["gst"]["note"] = "value equals net x 1.18: this is premium incl. GST, not the GST amount"
        if tot is None:
            _set(res, "total_premium", res["gst"]["value"], "derived", "taken from the GST row, which holds net x 1.18")
            tot = None
        gst = None

    # derive the missing one of net / gst / total from the other two
    if net is not None and gst is not None and res["total_premium"]["value"] is None:
        _set(res, "total_premium", round(net + gst, 2), "derived", "net + GST")
    if tot is not None and gst is not None and res["net_premium"]["value"] is None:
        if tot - gst > 0 and abs(gst - GST_RATE * (tot - gst)) <= 2:     # v3: never derive a negative / implausible net
            _set(res, "net_premium", round(tot - gst, 2), "derived", "total - GST")
        else:
            res["total_premium"]["status"] = res["gst"]["status"] = "check_failed"
            res["total_premium"]["note"] = res["gst"]["note"] = "total and GST do not fit net x 18%: not derived"
    if net is not None and tot is not None and res["gst"]["value"] is None:
        _set(res, "gst", round(tot - net, 2), "derived", "total - net")

    # v3: net known but GST / total not stated or contested on the quote: offer the policy arithmetic, never as "ok"
    n1 = val("net_premium", ("ok", "derived"))
    if n1 is not None:
        comp_tot, comp_gst = round(math.floor(n1) * (1 + GST_RATE)), round(math.floor(n1) * GST_RATE, 2)
        if res["gst"]["status"] == "not_found":
            _set(res, "gst", comp_gst, "derived", "not stated on the quote: 18% of net")
        elif res["gst"]["status"] == "conflict":
            res["gst"]["options"] = [{"gst": comp_gst}]
        if res["total_premium"]["status"] == "not_found":
            _set(res, "total_premium", comp_tot, "derived", "not stated on the quote: round(trunc(net) x 1.18)")
        elif res["total_premium"]["status"] == "conflict":
            res["total_premium"]["options"] = res["total_premium"].get("options", []) + [{"total": comp_tot}]

    usable = ("ok", "derived")
    net, gst, tot = val("net_premium", usable), val("gst", usable), val("total_premium", usable)
    checks = []

    def add(name, passed, fields, **kw):
        checks.append({"check": name, "pass": passed, **kw})
        if not passed:
            for f in fields:
                if res[f]["status"] in usable:
                    res[f]["status"] = "check_failed"

    if net is not None and tot is not None:
        exp = round(math.floor(net) * (1 + GST_RATE))
        add("total == round(trunc(net) x 1.18)", abs(exp - tot) <= TOL, ["total_premium", "net_premium"],
            expected=exp, found=tot)
    if net is not None and gst is not None and tot is not None:
        add("net + gst == total", abs(net + gst - tot) <= TOL, ["gst"], expected=tot, found=round(net + gst, 2))
    if net is not None and gst is not None:
        add("gst == 18% of net", abs(net * GST_RATE - gst) <= TOL + 1, ["gst"],
            expected=round(net * GST_RATE, 2), found=gst)
    # GST is only trusted when arithmetic confirms it
    if res["gst"]["status"] == "ok" and net is None:
        res["gst"]["status"] = "unverified"
        res["gst"]["note"] = (res["gst"].get("note", "") + "; no net premium to check against").strip("; ")
    a, b = val("period_from"), val("period_to")
    if a and b:
        add("period_to after period_from", b > a, ["period_from", "period_to"])
    return checks


# --------------------------------------------------------------------------- top level
_VARIANT = re.compile(r"(^@|@\w|\boption\b|\bopt\s*\d|\balt\b|variant|\bplan\s*\d|\bv\d+\b|quote\s*\d)", re.I)


def _extract_view(grid: Grid, labels: Labels) -> dict:
    rels = find_sum_relations(grid)
    totals = {r.total_ref for r in rels}
    cands = labelled_candidates(grid, totals, labels)
    labelled_found = bool(cands)
    have = {c.field for c in cands}
    cands += arithmetic_candidates(grid, rels, have)
    res = resolve(cands)
    checks = reconcile(res)
    blanks = blank_total_conflicts(grid, rels)
    warnings = []
    if not labelled_found:
        warnings.append("NO LABELLED VALUES FOUND: layout not recognised. 'not_stated' / 'not_found' here "
                        "does NOT mean the quote lacks the value. Check the file by hand and teach the labels.")
    review = [k for k, e in res.items() if e["status"] in REVIEW_STATUSES]
    review += [k for k, e in res.items() if "hidden_disagrees" in e and k not in review]
    if blanks:
        review.append("blank_total_conflicts")
    return {"fields": res, "checks": checks, "blank_total_conflicts": blanks,
            "totals_found": [asdict(r) for r in rels if r.labelled or r.via_formula][:50]
                            + [asdict(r) for r in rels if not (r.labelled or r.via_formula)][:50],
            "layout_recognised": labelled_found, "warnings": warnings, "needs_review": review}


def extract(path: str, sheet: str | None = None, labels: Labels | None = None, only: list[str] | None = None) -> dict:
    """only: restrict the read to these sheets (v3; lets a caller that knows the product pick the live tab)."""
    labels = labels or Labels()
    grid = Grid(path)
    if only:
        missing = [s for s in only if s not in grid.sheets]
        if missing:
            raise RuntimeError(f"sheet(s) not found: {missing}. Sheets: {', '.join(grid.sheets)}")
        grid = grid.view(only)
    visible = [s for s in grid.sheets if s not in grid.hidden_sheets]
    variants = [s for s in visible if _VARIANT.search(s)]
    if len(variants) < 2:
        variants = []
    base = [s for s in grid.sheets if s not in variants]
    report = {"file": path, "version": VERSION,
              "sheets": [{"name": s, "hidden": s in grid.hidden_sheets} for s in grid.sheets]}

    if variants and sheet is None:
        out = _extract_view(grid.view(base), labels)
        out["per_variant"] = {}
        for v in variants:
            r = _extract_view(grid.view(base + [v]), labels)
            out["per_variant"][v] = {"fields": {k: {"value": e["value"], "status": e["status"], "note": e.get("note", "")}
                                                for k, e in r["fields"].items()},
                                     "checks": r["checks"], "needs_review": r["needs_review"]}
        # v3: if exactly one variant yields a complete, arithmetic-consistent premium, use it (still flagged)
        full = [v for v, r in out["per_variant"].items()
                if all(r["fields"][k]["status"] in ("ok", "derived") and r["fields"][k]["value"] is not None
                       and not r["fields"][k].get("note", "").startswith("not stated on the quote")
                       for k in ("net_premium", "total_premium")) and all(c["pass"] for c in r["checks"])]
        if len(full) == 1:
            out2 = _extract_view(grid.view(base + full), labels)
            out2["per_variant"] = out["per_variant"]
            for k, e in out2["fields"].items():          # a guessed variant can never give a clean "ok"
                if e["status"] == "ok" and k in MONEY:
                    e["status"] = "derived"
                    e["note"] = (e.get("note", "") + "; variant auto-selected").strip("; ")
            out2["needs_review"].insert(0, "variant_auto_selected")
            out2["warnings"].insert(0, f"Policy variants found ({', '.join(variants)}). Only '{full[0]}' gives a complete "
                                       "premium, so it was used. Confirm it is the live variant.")
            out = out2
        else:
            out["needs_review"].insert(0, "choose_variant")
            out["warnings"].insert(0, f"Policy variants found ({', '.join(variants)}). Rerun with "
                                      f"--sheet \"<name>\" for the live one; per-variant values are under per_variant.")
    else:
        if sheet is not None and sheet not in grid.sheets:
            raise RuntimeError(f"sheet '{sheet}' not found. Sheets: {', '.join(grid.sheets)}")
        out = _extract_view(grid.view(base + ([sheet] if sheet else [])), labels)
    out["variants"] = variants
    out["warnings"] += grid.warnings
    report.update(out)
    return report


def summary_lines(rep: dict) -> list[str]:
    if "error" in rep:
        return [f"== {rep['file']}", f"  ERROR: {rep['error']}"]
    lines = [f"== {rep['file']}"]
    for w in rep["warnings"]:
        lines.append(f"  ! {w}")
    for k, e in rep["fields"].items():
        refs = ", ".join(sorted({x['ref'] for x in e.get('evidence', []) if x.get('ref')})[:3])
        lines.append(f"  {k:18} {e['status']:13} {str(e['value']):>20}  {refs}"
                     + (f"   [{e['note']}]" if e.get("note") else ""))
    for c in rep["checks"]:
        lines.append(f"  check {'PASS' if c['pass'] else 'FAIL'}  {c['check']}")
    for b in rep["blank_total_conflicts"]:
        lines.append(f"  blank total {b['total_ref']} ({b['column_header']}): stated {b['stated']}, rows sum to {b['sum_of_rows']}")
    for v, r in rep.get("per_variant", {}).items():
        vals = ", ".join(f"{k}={e['value']}" for k, e in r["fields"].items() if e["value"] is not None)
        lines.append(f"  variant {v}: {vals}")
    lines.append(f"  REVIEW: {', '.join(rep['needs_review']) or 'none'}")
    return lines


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "learn":
        if len(argv) < 3:
            raise SystemExit('usage: python quote_grid.py learn "<label as in the quote>" <field>')
        p = argparse.ArgumentParser()
        p.add_argument("--labels", default=DEFAULT_LABELS)
        ns, rest = p.parse_known_args(argv[1:])
        Labels(ns.labels).learn(rest[0], rest[1])
        return
    p = argparse.ArgumentParser(description="Extract headline fields from broker quotes")
    p.add_argument("files", nargs="+")
    p.add_argument("--sheet", help="live policy variant sheet, e.g. @A1")
    p.add_argument("--summary", action="store_true", help="print a short table instead of JSON")
    p.add_argument("--labels", default=DEFAULT_LABELS, help="learned labels file")
    ns = p.parse_args(argv)
    labels = Labels(ns.labels)
    reports = []
    for f in ns.files:
        try:
            reports.append(extract(f, ns.sheet, labels))
        except Exception as e:  # keep going on a batch
            reports.append({"file": f, "error": f"{type(e).__name__}: {e}"})
    if ns.summary:
        for r in reports:
            print("\n".join(summary_lines(r)))
    else:
        print(json.dumps(reports if len(reports) > 1 else reports[0], indent=2, default=str))


if __name__ == "__main__":
    main()
