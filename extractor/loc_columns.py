"""Item-by-location tables laid out with the locations as COLUMNS and the sum-insured items as rows (the APA "Annexure" sheet, the Texmaco "RFQ" sheet).

  Annexure sheet:                              RFQ sheet:
        | Unit 1 | Unit 2                       Location |  Agarpara | Sodepur | ... |
        | Office | Workshop                     Sl.No Particulars               ... | Total
  Building |  75 M  | 130 M                     1.0  a) Building ...  | ...         | ...
  ...
  Total    | 177 M  | 690 M                          TOTAL SUM INSURED | ...

Read generically: find a total row, walk up over the item rows (a text label + numbers in the same columns), take the nearest row above with a text in
every data column as the location names, and the occupancy from an 'Occupancy' row or the row under the names. A location is returned only when its
items add up to its own total (a table that does not tie is not trusted).
"""
from __future__ import annotations

import re

from .legacy.grid import is_num, norm

TOTAL_LABEL = re.compile(r"^total( sum insured)?( \(.*\))?$|^total sum insured")
SKIP_LABEL = re.compile(r"^(sl\.? ?no\.?|particulars|location|occupancy|rate|premium|discount|flexa|eq|stfi|terrorism|gst|total premium|earth ?quake)", re.I)


def _label(cells: dict):
    """(col, text) of the leftmost text cell that is not a bare serial number."""
    for c in sorted(cells):
        v = cells[c]
        if isinstance(v, str) and v.strip() and not re.fullmatch(r"[\d.\s]+", v.strip()):
            return c, " ".join(v.split())
    return None, None


def _clean_desc(t: str) -> str:
    t = re.sub(r"^\s*(?:\d+(?:\.\d+)?[.)]?|[a-z]\))\s*", "", t.strip(), flags=re.I)
    return re.sub(r"\s+", " ", t).strip(" :-")


def _block(rows: dict, total_rn: int):
    """-> (item_rows[(rn, label, cells)], data_cols, header_rn) for the table whose total row is total_rn, or None."""
    tot = rows[total_rn]
    lc, lab = _label(tot)
    num_cols = sorted(c for c, v in tot.items() if is_num(v) and c != lc and (lc is None or c > lc))
    if not num_cols:
        return None
    items, rn, gap = [], total_rn - 1, 0
    while rn >= 1 and gap <= 3:
        cells = rows.get(rn)
        if not cells:
            gap += 1
            rn -= 1
            continue
        c, lab = _label(cells)
        nums = {k: v for k, v in cells.items() if is_num(v) and k in num_cols}
        if lab and nums and not SKIP_LABEL.match(norm(lab)):
            items.append((rn, lab, cells))
            gap = 0
        elif lab and not nums and items:
            break                                       # a text-only row above the items: the header
        elif not lab and nums:
            gap += 1                                    # a stray subtotal / total-column zero with no label
        else:
            gap += 1
        rn -= 1
    if len(items) < 2:
        return None
    items.reverse()
    return items, num_cols, items[0][0]


def _names(rows: dict, first_item_rn: int, data_cols: list[int]):
    """-> (names_rn, {col: name}, occupancy_row_or_None). Nearest row above the items with a text cell in (almost) every data column is the names row;
    when the row right above it also qualifies, that upper row holds the names and the lower one the occupancies."""
    need = max(1, len(data_cols) - 1)

    def texts(rn):
        cells = rows.get(rn) or {}
        return {c: " ".join(cells[c].split()) for c in data_cols if isinstance(cells.get(c), str) and len(cells[c].strip()) > 2 and not is_num(cells[c])}

    for rn in range(first_item_rn - 1, max(0, first_item_rn - 8), -1):
        hit = texts(rn)
        if len(hit) >= need and not all(norm(v) in ("total", "rs.in lacs") for v in hit.values()):
            up = texts(rn - 1)
            if len(up) >= need and _label(rows.get(rn - 1) or {})[0] in data_cols and _label(rows.get(rn) or {})[0] in data_cols:
                return rn - 1, up, rn
            return rn, hit, None
    return None, {}, None


def _occupancy(rows: dict, names_rn: int | None, first_item_rn: int, total_rn: int, data_cols: list[int]) -> dict:
    cand = []
    for rn in list(range(total_rn + 1, total_rn + 6)) + ([names_rn + 1] if names_rn else []):
        cells = rows.get(rn) or {}
        lab = norm(_label(cells)[1] or "")
        if lab.startswith("occupancy") or (rn == (names_rn or -9) + 1 and rn < first_item_rn and not lab):
            cand.append(rn)
    for rn in cand:
        cells = rows.get(rn) or {}
        occ = {c: " ".join(str(cells[c]).split()) for c in data_cols if isinstance(cells.get(c), str) and cells[c].strip()}
        if occ:
            return occ
    return {}


def read(sheets) -> dict | None:
    """-> {'sheet', 'locations': [{'name', 'occupancy', 'items': [{'description','si'}], 'total'}], 'grand_total'} or None."""
    best = None
    for sh in sheets:
        if not sh.visible:
            continue
        rows = {rn: dict(cells) for rn, cells in sh.rows}
        for rn in sorted(rows):
            _, lab = _label(rows[rn])
            if not lab or not TOTAL_LABEL.match(norm(lab)):
                continue
            blk = _block(rows, rn)
            if not blk:
                continue
            items, data_cols, first = blk
            names_rn, names, occ_rn = _names(rows, first, data_cols)
            if not names:
                continue
            occ = {}
            if occ_rn:
                occ = {c: " ".join(str(rows[occ_rn][c]).split()) for c in data_cols if isinstance(rows[occ_rn].get(c), str)}
            occ = occ or _occupancy(rows, names_rn, first, rn, data_cols)
            locs = []
            total_col = None
            tvals = {c: float(rows[rn][c]) for c in data_cols if is_num(rows[rn].get(c))}
            for c in list(data_cols):                           # a column whose total is the sum of the others is the table's Total column
                others = sum(v for k, v in tvals.items() if k != c)
                if len(tvals) > 2 and c in tvals and others and abs(tvals[c] - others) <= max(1.0, tvals[c] * 1e-6):
                    total_col = c
                    names.pop(c, None)
            for c in data_cols:
                if c not in names:
                    continue
                its = [{"description": _clean_desc(l), "si": float(cells[c])} for _, l, cells in items if is_num(cells.get(c)) and float(cells[c]) > 0]
                tot = rows[rn].get(c)
                s = sum(i["si"] for i in its)
                if its and is_num(tot) and abs(s - float(tot)) <= max(1.0, abs(float(tot)) * 1e-6):
                    perils = {}
                    for rn2 in sorted(r2 for r2 in rows if r2 > rn):          # the last EQ / STFI / Terrorism row below the total is the premium row
                        l2 = norm(_label(rows[rn2])[1] or "")
                        if l2 in ("eq", "earthquake", "stfi", "terrorism") and is_num(rows[rn2].get(c)):
                            perils[l2] = float(rows[rn2][c])
                    locs.append({"name": names[c], "occupancy": occ.get(c, ""), "items": its, "total": float(tot), "perils": perils})
            if not locs:
                continue
            grand = rows[rn].get(total_col) if total_col else None
            cand = {"sheet": sh.name, "locations": locs, "grand_total": float(grand) if is_num(grand) else sum(l["total"] for l in locs)}
            if best is None or len(locs) > len(best["locations"]):
                best = cand
    return best


# ------------------------------------------------------------------ per-section, per-location blocks stacked down one sheet (the Pune "BPP Laghu" quote)
BLOCK_HEAD = re.compile(r"^(fire|burglary|money|fidelity|plate glass|neon sign|baggage|public liability)\b[^-–]*[-–]\s*(?:location\s*\d+\s*[-–]?\s*)?(.+)$", re.I)
BLOCK_SECTION = {"fire": 1, "burglary": 3, "money": 7, "fidelity": 8, "plate glass": 10, "neon sign": 11, "baggage": 12, "public liability": 13}
BLOCK_STOP = re.compile(r"^(total|fire total|first loss|balance sum|add on|stfi\b|eq\b|terrorism|rate\b|premium)", re.I)


def read_section_blocks(sheets) -> dict:
    """-> {section_no: [{'address', 'items': [{'description','si'}], 'total', 'first_loss_pct'|None, 'addons': [{'name','remark'}]}]}.
    A block is a heading row alone in its row ("Fire Section - <address>"), a 'Description | Sum Insured' header row, then item rows."""
    out: dict[int, list] = {}
    for sh in sheets:
        if not sh.visible:
            continue
        rows = {rn: dict(c) for rn, c in sh.rows}
        order = sorted(rows)
        for i, rn in enumerate(order):
            cells = rows[rn]
            if len(cells) != 1 or not isinstance(next(iter(cells.values())), str):
                continue
            m = BLOCK_HEAD.match(" ".join(next(iter(cells.values())).split()))
            nxt = rows.get(order[i + 1]) if i + 1 < len(order) else None
            if not m or not nxt or not any(isinstance(v, str) and re.search(r"sum insured", v, re.I) for v in nxt.values()):
                continue
            si_col = next(c for c, v in nxt.items() if isinstance(v, str) and re.search(r"sum insured", v, re.I))
            sec = BLOCK_SECTION[m.group(1).lower()]
            blk = {"address": " ".join(m.group(2).split()), "items": [], "total": None, "first_loss_pct": None, "addons": []}
            in_addons = False
            for rn2 in order[i + 2:]:
                c2 = rows[rn2]
                lab = _label(c2)[1]
                if lab is None:
                    break
                if len(c2) == 1 and BLOCK_HEAD.match(lab):
                    break
                if re.match(r"^add on", lab, re.I):
                    in_addons = True
                    continue
                if in_addons:
                    if re.match(r"^total", lab, re.I):
                        in_addons = False
                        continue
                    rem = next((str(v) for c, v in sorted(c2.items()) if isinstance(v, str) and v is not lab and c > 1), "")
                    blk["addons"].append({"name": lab, "remark": rem})
                    continue
                m2 = re.match(r"^first loss basis\s*[@:-]*\s*(\d+(?:\.\d+)?)\s*%", lab, re.I)
                if m2:
                    blk["first_loss_pct"] = float(m2.group(1))
                    continue
                v = c2.get(si_col)
                if re.match(r"^(fire total|total .*sum insured|total sum insured)", lab, re.I):
                    blk["total"] = float(v) if is_num(v) else None
                    continue
                if BLOCK_STOP.match(lab):
                    continue
                if is_num(v) and float(v) > 0:
                    blk["items"].append({"description": lab, "si": float(v)})
            if blk["items"]:
                if blk["total"] is None:
                    blk["total"] = sum(i["si"] for i in blk["items"])
                out.setdefault(sec, []).append(blk)
    return out
