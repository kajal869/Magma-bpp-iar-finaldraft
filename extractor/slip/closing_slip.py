"""Closing slip parser. The template is stable but row positions drift, so values are found by label."""
import datetime
import re

from .grid import find_sheet, is_num, load, norm

# key, label regex (matched against the normalised cell text)
LABELS = [
    ("office", r"^office name/code"),
    ("sales_manager", r"^sales manager"),
    ("channel", r"^channel"),
    ("business_type", r"^business type"),
    ("expiring_policy_no", r"^if renewal"),
    ("product_name", r"^gc policy/product name"),
    ("insured_name", r"^name of the insured"),
    ("insured_address", r"^insured'?s communication address"),
    ("gst_no", r"^gst no"),
    ("customer_id", r"^customer/client id"),
    ("policy_start", r"^policy start date"),
    ("policy_end", r"^policy end date"),
    ("intermediary", r"^intermediary name/code"),
    ("commission_pct", r"^intermediary commission"),
    ("terrorism_opted", r"^terrorism cover opted"),
    ("premium_100", r"^100% premium amount"),
    ("magma_role", r"^whether magma.*leader"),
    ("our_share", r"^our share$"),
    ("product_code", r"^product code"),
    ("uin", r"^uin number"),
    ("location_address", r"^location address"),
    ("occupancy", r"^occupancy$"),
    ("risk_code", r"^risk code"),
    ("hazard_grade", r"^hazard grade"),
]
_COMPILED = [(k, re.compile(p)) for k, p in LABELS]


def _label_key(v):
    if not isinstance(v, str):
        return None
    t = norm(v)
    for k, rx in _COMPILED:
        if rx.search(t):
            return k
    return None


def _iso(v):
    return v.strftime("%Y-%m-%d") if isinstance(v, (datetime.datetime, datetime.date)) else v


def split_intermediary(text):
    """'NE0 RISK /BRC0000684' -> (name, code). The code is the reliable part."""
    if not text:
        return None, None
    m = re.search(r"\b([A-Z]{3}\d{7})\b", text)
    code = m.group(1) if m else None
    name = re.sub(r"\s*[/-]*\s*\b[A-Z]{3}\d{7}\b.*$", "", text).strip(" /-") or None
    return name, code


def parse(path):
    sheets = load(path)
    cs = find_sheet(sheets, r"closing slip")
    out, seen = {}, set()
    for _, cells in cs.rows:
        for i, (_, v) in enumerate(cells):
            k = _label_key(v)
            if not k or k in seen:
                continue
            seen.add(k)
            nxt = cells[i + 1][1] if i + 1 < len(cells) else None
            if _label_key(nxt):  # next cell is another label, so this field is empty
                nxt = None
            out[k] = _iso(nxt)
    name, code = split_intermediary(out.get("intermediary"))
    out["intermediary_name_raw"], out["intermediary_code"] = name, code
    out["locations"] = _locations(sheets)
    out["co_insurers"] = _co_insurers(cs)
    return out


def _co_insurers(cs):
    """Rows between the 'Leader' header and the Branch Operations block: name + share."""
    res, on = [], False
    for _, cells in cs.rows:
        t = norm(cells[0][1]) if isinstance(cells[0][1], str) else ""
        if t.startswith("to be filled by branch operations"):
            break
        if t in ("leader", "followers"):
            on = True
            continue
        if on and isinstance(cells[0][1], str) and len(cells) > 1 and is_num(cells[1][1]):
            res.append({"name": cells[0][1], "share": cells[1][1]})
    return res


def _locations(sheets):
    ld = find_sheet(sheets, r"location details")
    if not ld:
        return []
    out, head = [], None
    for _, cells in ld.rows:
        vals = [v for _, v in cells]
        if head is None:
            if any(isinstance(v, str) and norm(v) == "location address" for v in vals):
                head = True
            continue
        if isinstance(vals[0], str) and norm(vals[0]).startswith("total sum insured"):
            break
        by_col = dict(cells)
        if is_num(by_col.get(8)) and by_col.get(8) > 0 or by_col.get(2):
            out.append({"label": by_col.get(1), "address": by_col.get(2), "state": by_col.get(3), "district": by_col.get(4),
                        "pin": by_col.get(5), "occupancy": by_col.get(6), "occupancy_code": by_col.get(7),
                        "pd_si": by_col.get(8), "bi_si": by_col.get(9)})
    return out
