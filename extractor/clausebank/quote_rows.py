"""Extract every add-on / coverage / clause row from a broker quote workbook (all sheets, hidden ones included).

Two row kinds:
  addon_row       a row in an 'Add-on Covers' / 'Add Ons' / 'Additional Clauses' table that has an insurer remark (or a serial)
  condition_line  a plain line under a 'Conditions / Warranties / Clauses' heading in quotes with no remark column (Laghu style);
                  decision is 'pending' because there is no remark to classify
Own reader on purpose: the existing cover_grid reads 'Cannot be covered' as include, stops tables after 2 blank rows,
does not dedupe and skips hidden sheets. Duplicates are NOT removed here (the back-tracker groups them)."""
import re
import warnings
from pathlib import Path

from .remarks import classify

warnings.filterwarnings("ignore")

TABLE_ANCHOR = re.compile(r"^\s*(?:add[\s\-]*ons?(?:\s+covers?)?|add[\s\-]*on\s+covers?|additional\s+clauses.*|add[\s\-]*on\s+covers?\s*(?:&|and)\s*clauses)\s*:?\s*$", re.I)
LIST_ANCHOR = re.compile(r"^\s*(?:conditions?\s*[,/]?\s*warranties.*|terms\s*/\s*conditions\s*/?\s*clauses?|conditions\s+applicable\s+to\s+all.*|special\s+conditions.*)\s*:?\s*$", re.I)
HEADER_NAME = re.compile(r"^\s*(?:covers?|coverages?|clauses?|particulars)\s*:?\s*$", re.I)
REMARK_HDR = re.compile(r"remark|insurer\s*terms?|status|magma|response|comment", re.I)
LIMIT_HDR = re.compile(r"limit|sum\s*insured|\bsi\b", re.I)
STOP_NAME = re.compile(r"^\s*(?:total|premium|net\s+premium|particulars|rate\b|gst|grand|section\b|burglary\s+for|all\s+risk|flop\b|sum\s+insured\b|location\b|discount|loading)", re.I)
NOT_A_CLAUSE = re.compile(r"quotation|validit|incurred\s+claims|deteriorat|revision|quote\s+date|^excess|^deductible|subject\s+to\s+no\b|capacity\s+quoted|"
                          r"insurance\s*:?$|^bharat\s+laghu|^money\s*/|^terrorism\s+excess|locations?\s+having\s+sum|transit\s+details|^maximum\s+per", re.I)


def _is_num(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    return bool(isinstance(v, str) and re.fullmatch(r"[\d,.\s%]+", v.strip()) and re.search(r"\d", v))


def _serial(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(int(v)) if float(v).is_integer() else None
    if isinstance(v, str) and re.fullmatch(r"\d{1,3}(?:\.0)?", v.strip()):
        return str(int(float(v)))
    return None


def sheets(path):
    """-> list of (name, hidden, {row: {col: value}}) with 1-based indexes."""
    path = Path(path)
    out = []
    if path.suffix.lower() == ".xls":
        try:
            import xlrd
        except ImportError:
            raise RuntimeError("reading .xls needs xlrd (pip install xlrd) or save the quote as .xlsx")
        wb = xlrd.open_workbook(str(path))
        for ws in wb.sheets():
            g = {}
            for r in range(ws.nrows):
                row = {c + 1: ws.cell_value(r, c) for c in range(ws.ncols) if ws.cell_value(r, c) not in ("", None)}
                if row:
                    g[r + 1] = row
            out.append((ws.name, ws.visibility != 0, g))
        return out
    import openpyxl
    wb = openpyxl.load_workbook(str(path), data_only=True)
    for ws in wb.worksheets:
        g = {}
        for row in ws.iter_rows():
            cells = {c.column: c.value for c in row if c.value is not None and str(c.value).strip() != ""}
            if cells:
                g[row[0].row] = cells
        out.append((ws.title, ws.sheet_state != "visible", g))
    return out


def _txt(v):
    return " ".join(str(v).replace("\n", " ").split()) if isinstance(v, str) else ""


def _table_block(g, r0, namecol):
    """Rows below a table anchor at (r0, namecol)."""
    hdr = g.get(r0, {})
    remark_col = next((c for c, v in hdr.items() if c != namecol and isinstance(v, str) and REMARK_HDR.search(v) and len(v) < 40), None)
    limit_col = next((c for c, v in hdr.items() if c not in (namecol, remark_col) and isinstance(v, str) and LIMIT_HDR.search(v) and len(v) < 40), None)
    rows, blanks, r = [], 0, r0 + 1
    last = max(g) if g else r0
    while r <= last:
        cells = g.get(r)
        name = _txt(cells.get(namecol)) if cells else ""
        if not cells or (not name and not any(isinstance(v, str) and v.strip() for c, v in cells.items() if c > namecol)):
            blanks += 1
            if blanks >= 3:
                break
            r += 1
            continue
        blanks = 0
        if name and (TABLE_ANCHOR.match(name) or LIST_ANCHOR.match(name)):
            break                                     # next block starts here; caller re-anchors
        if name and STOP_NAME.match(name) and not re.match(r"^\s*(?:total|section)\b.*(?:cover|clause)", name, re.I):
            break
        if not name:
            r += 1
            continue
        right = {c: v for c, v in cells.items() if c > namecol}
        if remark_col is not None:
            remark = _txt(cells.get(remark_col))
        else:                                         # rightmost text cell to the right of the name that is not a number
            cand = [(c, _txt(v)) for c, v in sorted(right.items()) if isinstance(v, str) and v.strip() and not _is_num(v)]
            remark = cand[-1][1] if cand else ""
            remark_col_row = cand[-1][0] if cand else None
        if remark_col is None and remark:
            limit_cells = [_txt(v) if isinstance(v, str) else str(int(v) if isinstance(v, float) and float(v).is_integer() else v)
                           for c, v in sorted(right.items()) if c < remark_col_row]
        else:
            limit_cells = []
        if limit_col is not None:
            v = cells.get(limit_col)
            limit = _txt(v) if isinstance(v, str) else ("" if v is None else str(int(v) if isinstance(v, float) and float(v).is_integer() else v))
        else:
            limit = "; ".join(x for x in limit_cells if x)
        serial = next((_serial(v) for c, v in sorted(cells.items()) if c < namecol and _serial(v)), None)
        if not remark and not serial:
            r += 1
            continue                                  # sub-heading
        rows.append({"row": r, "serial": serial, "name": name, "limit": limit, "remark": remark})
        r += 1
    return rows


def _list_block(g, r0, namecol):
    rows, r, last = [], r0 + 1, max(g)
    while r <= last:
        cells = g.get(r)
        if not cells:
            break
        name = _txt(cells.get(namecol))
        if not name or TABLE_ANCHOR.match(name) or LIST_ANCHOR.match(name) or re.match(r"^\s*section\b", name, re.I):
            break
        if not NOT_A_CLAUSE.search(name) and len(name) > 6:
            rows.append({"row": r, "serial": None, "name": name, "limit": "", "remark": ""})
        r += 1
    return rows


def extract(case, path):
    """-> list of quote-row dicts for one quote workbook."""
    out = []
    for sheet, hidden, g in sheets(path):
        has_table = False
        for r in sorted(g):
            for c, v in sorted(g[r].items()):
                name = _txt(v)
                is_hdr = bool(name) and HEADER_NAME.match(name) and any(
                    isinstance(v2, str) and REMARK_HDR.search(v2) and len(v2) < 40 for c2, v2 in g[r].items() if c2 != c)
                if name and len(name) < 70 and (TABLE_ANCHOR.match(name) or is_hdr):
                    # a table anchor must have rows with something to its right or a remark header, else it is a label
                    blk = _table_block(g, r, c)
                    if blk:
                        has_table = True
                        for b in blk:
                            out.append({**b, "case": case, "sheet": sheet, "hidden": hidden, "block": r, "row_type": "addon_row"})
        if not has_table:
            for r in sorted(g):
                for c, v in sorted(g[r].items()):
                    name = _txt(v)
                    if name and len(name) < 90 and LIST_ANCHOR.match(name):
                        for b in _list_block(g, r, c):
                            out.append({**b, "case": case, "sheet": sheet, "hidden": hidden, "block": r, "row_type": "condition_line"})
    seen, rows = set(), []
    for q in out:                                    # the same row can be reached by two anchors on one row
        k = (q["sheet"], q["row"])
        if k in seen:
            continue
        seen.add(k)
        if q["row_type"] == "condition_line":
            q.update(decision="pending", cls="no_remark", cited=None, conditional=False)
        else:
            c = classify(q["remark"])
            q.update(decision=c["decision"], cls=c["cls"], cited=c["cited"], conditional=c["conditional"])
            if re.fullmatch(r"\s*fire\s*", q["name"], re.I):
                q.update(decision="drop", cls="base_peril")
        q["key"] = f"{case}|{q['sheet']}|{q['row']}"
        rows.append(q)
    return rows
