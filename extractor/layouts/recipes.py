"""Generic readers (recipes). Each one either finds its structure in a sheet or returns None; none guesses.

labelled_table  header row naming a Sum Insured and a Premium column; rows keyed by "Section - N ..." or a cover name
location_matrix one SFSP-style sheet: a column per location and a TOTAL column; rows labelled Total Sum Insured / Premium before GST
scalars         labelled single values: hypothecation, business activity, terrorism premium
cell            a cell a person pointed at, addressed by row label + column header (robust to shifted rows), absolute ref as fallback
"""
from __future__ import annotations

import re

from .common import cells, col_from_ref, h, is_num, label_norm, ref, shape

TIE = 2.0
SECTION_RX = re.compile(r"section\s*[–—\-:.]*\s*(\d{1,2})\b", re.I)
NET_RX = re.compile(r"(?:total\s+)?net\s+premium|premium\s*\(\s*ex(?:cl)?[a-z.]*\s*gst\s*\)|(?:total\s+)?premium\s+before\s+gst|premium\s+excl", re.I)
STOP_KEY = re.compile(r"^(total|premium|gst|net|grand|sub\s*total)")


def section_of(text) -> int | None:
    """'Section - 3 Burglary ...' -> 3; otherwise the cover named by keywords ('Plate Glass Cover' -> 10)."""
    if not isinstance(text, str):
        return None
    m = SECTION_RX.search(text)
    if m and 1 <= int(m.group(1)) <= 13:
        return int(m.group(1))
    from ..sections import section_no           # lazy: sections imports this package
    return section_no(text)


# ------------------------------------------------------------------ labelled table
def find_table(sheet, spec: dict | None = None):
    cs = cells(sheet)
    for rn in sorted(cs):
        texts = {c: label_norm(v) for c, v in cs[rn].items() if isinstance(v, str)}
        if spec:
            si = [c for c, t in texts.items() if t == spec["si"]]
            pr = [c for c, t in texts.items() if t == spec["premium"]]
        else:
            si = [c for c, t in texts.items() if re.search(r"sum\s*insured", t)]
            pr = [c for c, t in texts.items() if "premium" in t and "rate" not in t]
        if not (si and pr):
            continue
        left = [c for c in texts if c < min(si)]
        if not left:
            continue
        key = min(left)
        if spec and texts[key] != spec["key"]:
            continue
        return {"row": rn, "key": key, "si": si[0], "premium": pr[0], "spec": {"key": texts[key], "si": texts[si[0]], "premium": texts[pr[0]]}}
    return None


def find_net(sheet):
    """The sheet's own net premium: the value right of a 'Net Premium' / 'Premium (Excl GST)' style label."""
    best = None
    for rn, cs in sheet.rows:
        for i, (c, v) in enumerate(cs):
            if isinstance(v, str) and NET_RX.search(label_norm(v)) and len(v) < 60:
                nums = [x for cc, x in cs if cc > c and is_num(x)]
                if nums:
                    best = (nums[0], ref(c, rn))
                    if re.search(r"net|excl", label_norm(v)):
                        return best
    return best


GROSS_RX = re.compile(r"premium\s*\(\s*incl[a-z.]*\s*gst\s*\)|gross\s+premium|total\s+premium\s+(?:payable|with\s+gst|incl)", re.I)


def find_gross(sheet):
    for rn, cs in sheet.rows:
        for c, v in cs:
            if isinstance(v, str) and len(v) < 60 and GROSS_RX.search(label_norm(v)):
                nums = [x for cc, x in cs if cc > c and is_num(x)]
                if nums:
                    return nums[0], ref(c, rn)
    return None


def read_table(sheet, t: dict) -> dict | None:
    cs = cells(sheet)
    secs: dict[int, dict] = {}
    last, prev = None, t["row"]
    for rn in (r for r in sorted(cs) if r > t["row"]):
        if rn - prev > 4 and secs:
            break
        prev = rn
        row = cs[rn]
        key = row.get(t["key"])
        keytxt = label_norm(key) if isinstance(key, str) else ""
        if keytxt and STOP_KEY.match(keytxt):
            break
        si, pr = row.get(t["si"]), row.get(t["premium"])
        n = section_of(key) if isinstance(key, str) else None
        if n:
            d = secs.setdefault(n, {"si": None, "premium": None, "refs": []})
            if is_num(si):
                d["si"] = (d["si"] or 0.0) + si
                d["refs"].append(ref(t["si"], rn))
            if is_num(pr):
                d["premium"] = (d["premium"] or 0.0) + pr
                d["refs"].append(ref(t["premium"], rn))
            last = n
        elif not keytxt and last and is_num(pr) and not is_num(si):
            secs[last]["premium"] = (secs[last]["premium"] or 0.0) + pr      # an extra premium line under a section (e.g. terrorism)
            secs[last]["refs"].append(ref(t["premium"], rn))
            secs[last].setdefault("extra_lines", 0)
            secs[last]["extra_lines"] = secs[last].get("extra_lines", 0) + 1
    if not secs:
        return None
    net, gross = find_net(sheet), find_gross(sheet)
    return {"reader": "labelled_table", "sections": secs, "net": net[0] if net else None, "net_ref": net[1] if net else None,
            "gross": gross[0] if gross else None, "gross_ref": gross[1] if gross else None, "table": t}


# ------------------------------------------------------------------ location matrix
def read_matrix(sheet) -> dict | None:
    cs = cells(sheet)
    si_row = prem_row = None
    for rn in sorted(cs):
        texts = [label_norm(v) for v in cs[rn].values() if isinstance(v, str)]
        nums = {c: v for c, v in cs[rn].items() if is_num(v)}
        if not texts or len(nums) < 2:
            continue
        t0 = texts[0]
        if si_row is None and re.match(r"total sum insured", t0):
            si_row = (rn, nums)
        elif prem_row is None and re.match(r"(?:total )?premium before gst|total net premium|net premium", t0):
            prem_row = (rn, nums)
    if not si_row or not prem_row:
        return None

    def total(nums):
        cols = sorted(nums)
        last = nums[cols[-1]]
        parts = [nums[c] for c in cols[:-1]]
        return (last, True) if parts and abs(sum(parts) - last) <= max(1.0, abs(last) * 1e-6) else (sum(nums.values()), False)

    si, si_col = total(si_row[1])
    pr, pr_col = total(prem_row[1])
    return {"reader": "location_matrix", "sections": {1: {"si": si, "premium": pr, "refs": [f"row {si_row[0]}", f"row {prem_row[0]}"], "total_column": si_col and pr_col}},
            "net": pr, "net_ref": f"row {prem_row[0]}", "locations": len(si_row[1]) - (1 if si_col else 0)}


# ------------------------------------------------------------------ scalars
SCALARS = [("hypothecation", re.compile(r"hypothecation|financial interest|financier|lender|loss payee"), "text"),
           ("business_activity", re.compile(r"business activity|type of occupation|nature of business"), "text"),
           ("premium.terrorism", re.compile(r"^premium\s*\(\s*terrorism\s*\)|^terrorism\s+premium|^terrorism\s*\(\s*premium\s*\)"), "number")]


def split_lines(text: str) -> list[str]:
    parts = re.split(r"\s*(?:\d+\s*[.)]\s+|;|\n)\s*", text)
    out = [p.strip(" ,.;") for p in parts if p and p.strip(" ,.;")]
    return out or [text.strip()]


def read_scalars(sheets) -> dict:
    out: dict = {}
    for s in sheets:
        if not s.visible:
            continue
        for rn, cs in s.rows:
            for i, (c, v) in enumerate(cs):
                if c > 6 or not isinstance(v, str) or len(v) > 70:
                    continue
                t = label_norm(v)
                for field, rx, kind in SCALARS:
                    if field in out or not rx.search(t):
                        continue
                    right = [(cc, x) for cc, x in cs if cc > c and x not in (None, "")]
                    if kind == "number":
                        right = [(cc, x) for cc, x in right if is_num(x)]
                    if not right:
                        continue
                    cc, x = right[0]
                    out[field] = {"value": split_lines(str(x)) if field == "hypothecation" else x, "ref": ref(cc, rn), "sheet": s.name}
    return out


# ------------------------------------------------------------------ taught cells
def teach_cell(sheets, target: str, sheet_name: str, cell_ref: str, kind: str = "number") -> dict:
    """Describe a cell the user pointed at by what is next to it: the row's label and the column's header."""
    col, row = col_from_ref(cell_ref)
    sh = next((s for s in sheets if s.name == sheet_name), None)
    if sh is None:
        raise ValueError(f"sheet '{sheet_name}' not found")
    cs = cells(sh)
    left = [(c, v) for c, v in sorted(cs.get(row, {}).items()) if c < col and isinstance(v, str)]
    row_label = label_norm(left[-1][1]) if left else None
    head = None
    for rr in range(row - 1, max(0, row - 30), -1):
        v = cs.get(rr, {}).get(col)
        if isinstance(v, str):
            head = label_norm(v)
            break
    return {"type": "cell", "target": target, "sheet": h(shape(sheet_name)), "sheet_name_shape": shape(sheet_name), "row_label": row_label, "col_header": head,
            "ref": cell_ref, "kind": kind}


def resolve_cell(sheets, rec: dict):
    """-> (value, ref, sheet_name) or None. Row label + column header first; the absolute cell is a fallback only if its label still matches."""
    cands = [s for s in sheets if h(shape(s.name)) == rec["sheet"]] or list(sheets)
    want_col, want_row = col_from_ref(rec["ref"])
    for sh in cands:
        cs = cells(sh)
        rows = []
        if rec.get("row_label"):
            rows = [rn for rn, r in cs.items() if any(isinstance(v, str) and label_norm(v) == rec["row_label"] for c, v in r.items() if c < want_col + 3)]
        for rn in rows:
            col = want_col
            if rec.get("col_header"):
                found = None
                for c in sorted(cs[rn]) + [want_col]:
                    for rr in range(rn - 1, max(0, rn - 30), -1):
                        v = cs.get(rr, {}).get(c)
                        if isinstance(v, str):
                            if label_norm(v) == rec["col_header"]:
                                found = c
                            break
                    if found:
                        break
                col = found or want_col
            val = cs[rn].get(col)
            if val is not None and (rec["kind"] != "number" or is_num(val)):
                return val, ref(col, rn), sh.name
        val = cs.get(want_row, {}).get(want_col)               # absolute fallback
        if val is not None and (rec["kind"] != "number" or is_num(val)):
            lbl = [label_norm(v) for c, v in cs.get(want_row, {}).items() if c < want_col and isinstance(v, str)]
            if not rec.get("row_label") or (lbl and lbl[-1] == rec["row_label"]):
                return val, rec["ref"], sh.name
    return None
