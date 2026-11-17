"""Quote parser for the 'Asset' + 'Coverages' layout (Daechang). Pieces are label/heading driven, not cell-address driven,
so the same functions can be pointed at other quotes once their headings are covered by the patterns below."""
import re

from .grid import find_sheet, is_num, load, norm

HEADER_LABELS = [
    ("insured_name", r"^insured\s*name"),
    ("address", r"^(communication|insured)\s*address"),
    ("business_description", r"^nature of business"),
    ("occupancy", r"^risk occupancy|^occupancy"),
    ("risk_location", r"^risk location"),
    ("policy_period", r"^policy period|^period of insurance"),
    ("incumbent", r"^incumbent"),
    ("claims", r"^claims"),
]

# section heading regex -> policy section number
SECTION_HEADINGS = [
    (r"standard fire|fire and special perils|^fire insurance", 1),
    (r"burglary", 3),
]

DATE = r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})"


def _iso(d, m, y):
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def _first_text(cells, after=0):
    for c, v in cells:
        if c > after and isinstance(v, str):
            return c, v
    return None, None


def parse(path):
    sheets = load(path)
    main = next((s for s in sheets if s.visible and any(
        isinstance(v, str) and re.match(r"^insured\s*name", norm(v)) for _, cells in s.rows for _, v in cells)), None)
    q = {"source_sheet": main.name}
    _header(main, q)
    q["sections"] = _sections(main)
    q["premium_summary"] = _premium_summary(main)
    q.update(_terms(main))
    cov = next((s for s in sheets if s.visible and any(
        isinstance(v, str) and re.search(r"insurer terms", norm(v)) for _, cells in s.rows[:3] for _, v in cells)), None)
    q["coverages"] = _coverages(cov) if cov else []
    return q


def _header(sh, q):
    for _, cells in sh.rows[:15]:
        c0, label = cells[0]
        if not isinstance(label, str):
            continue
        for key, rx in HEADER_LABELS:
            if key not in q and re.search(rx, norm(label)):
                _, val = _first_text(cells, c0)
                if val:
                    q[key] = val
                break
    per = q.get("policy_period", "")
    dates = re.findall(DATE, per)
    if len(dates) >= 2:
        q["policy_start"], q["policy_end"] = _iso(*dates[0]), _iso(*dates[1])


def _sections(sh):
    out, cur = {}, None
    for _, cells in sh.rows:
        texts = [v for _, v in cells if isinstance(v, str)]
        if len(cells) == 1 and texts:  # a lone heading cell
            for rx, no in SECTION_HEADINGS:
                if re.search(rx, norm(texts[0])) and not norm(texts[0]).startswith("terms"):
                    cur = out.setdefault(no, {"heading": texts[0], "items": [], "total_si": None, "rate": None, "premium": None,
                                              "first_loss_pct": None, "notes": []})
                    break
            continue
        if cur is None:
            continue
        by = dict(cells)
        sr, desc = by.get(1), by.get(2)
        nums = [(c, v) for c, v in cells if is_num(v) and c > 2]
        if isinstance(desc, str) and norm(desc).startswith("total sum insured") and nums:
            vals = [v for _, v in nums]
            cur["total_si"] = vals[0]
            cur["rate"] = vals[1] if len(vals) > 1 else None
            cur["premium"] = vals[2] if len(vals) > 2 else None
            cur = cur if False else cur
            continue
        if isinstance(desc, str) and re.match(r"first loss basis", norm(desc)):
            m = re.search(r"(\d+(?:\.\d+)?)\s*%", desc)
            cur["first_loss_pct"] = float(m.group(1)) if m else None
            cur["notes"].append(desc)
            continue
        if sr is not None and isinstance(desc, str) and nums and (is_num(sr) or str(sr).isdigit()):
            cur["items"].append({"description": desc, "si": nums[0][1]})
    return out


def _premium_summary(sh):
    out = {}
    for _, cells in sh.rows:
        for _, v in cells:
            if not isinstance(v, str):
                continue
            t = norm(v)
            key = ("net_premium" if t == "net premium" else "gst" if t.startswith("gst") else
                   "total_premium" if t == "total premium" else None)
            if key and key not in out:
                nums = [x for _, x in cells if is_num(x)]
                if nums:
                    out[key] = nums[-1]
    return out


def _terms(sh):
    """Walk the single-column text lines under 'Terms and Conditions' with a small state machine."""
    res = {"deductibles": {"fire": [], "burglary": []}, "conditions": {"fire": [], "burglary": [], "all": []},
           "quote_date": None, "validity": None, "claims_terms": []}
    on, state = False, None
    for _, cells in sh.rows:
        c0, text = cells[0]
        if not isinstance(text, str) or c0 != 1:
            continue
        t = norm(text)
        if re.match(r"^terms and conditions", t):
            on = True
            continue
        if not on:
            continue
        m = re.search(r"quote date\s*-?\s*" + DATE, t)
        if m:
            res["quote_date"] = _iso(*m.groups())
            continue
        if re.match(r"^standard fire", t):
            state = None
        elif re.match(r"^excess/deductible", t):
            state = ("deductibles", "fire")
        elif re.match(r"^conditions / warranties", t):
            state = ("conditions", "fire")
        elif re.match(r"^section\s*[–-]\s*3", t):
            state = None
        elif t.startswith("excess for burglary"):
            res["deductibles"]["burglary"].append(text)
        elif re.match(r"^terms/conditions", t):
            state = ("conditions", "burglary")
        elif re.match(r"^conditions applicable to all", t):
            state = ("conditions", "all")
        elif re.match(r"^quotation vali", t):
            res["validity"], state = text, None
        elif re.match(r"^terms, conditions, and capacity", t):
            state = ("claims", None)
            res["claims_terms"].append(text)
        elif state and state[0] == "claims":
            res["claims_terms"].append(text)
        elif state:
            res[state[0]][state[1]].append(text)
    return res


def _coverages(sh):
    out = []
    for _, cells in sh.rows[1:]:
        by = dict(cells)
        sr = by.get(1)
        if sr is None or not (is_num(sr) or str(sr).isdigit()):
            continue
        out.append({"sr": int(float(sr)), "name": by.get(2), "limit": by.get(3), "status": by.get(max(by))})
    return out
