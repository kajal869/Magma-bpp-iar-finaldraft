"""Quote parsers for two more layout families, plus a dispatcher.
  blocks : one sheet per location with SFSP / burglary item tables and an 'Add-on Covers | Magma Remarks' table, premiums on a summary sheet (Mann's)
  matrix : a summary table with one row per location and one column per cover/premium (Valmet)
  asset  : the original Daechang layout (bpp.quote)
Every parser returns the same shape as bpp.quote.parse so the rest of the pipeline does not care which was used."""
import re

from . import quote as q1
from .grid import is_num, load, norm

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE_RX = re.compile(r"(\d{1,2})\s*[-/. ]\s*([A-Za-z]{3}|\d{1,2})\s*[-/. ]\s*(\d{2,4})")


def find_dates(text):
    out = []
    for d, m, y in DATE_RX.findall(text or ""):
        mo = MONTHS.get(m.lower()[:3]) if not m.isdigit() else int(m)
        if not mo:
            continue
        y = int(y) + (2000 if len(y) == 2 else 0)
        out.append(f"{y:04d}-{mo:02d}-{int(d):02d}")
    return out


def _texts(cells):
    return [(c, v) for c, v in cells if isinstance(v, str)]


def _is_sr(v):
    return (is_num(v) and float(v).is_integer()) or (isinstance(v, str) and v.strip().isdigit())


def _item(cells):
    """[optional serial] description ... first number -> (description, number) or None."""
    txt = [(c, v) for c, v in cells if isinstance(v, str) and not v.strip().isdigit()]
    num = [(c, v) for c, v in cells if is_num(v) and not (c == cells[0][0] and _is_sr(v))]
    if not txt or not num:
        return None
    d = txt[0]
    after = [v for c, v in num if c > d[0]]
    return (d[1], after[0]) if after else None


def _period(q):
    d = find_dates(q.get("policy_period", ""))
    if len(d) >= 2:
        q["policy_start"], q["policy_end"] = d[0], d[1]


# ------------------------------------------------------------------ blocks (Mann's)
def parse_blocks(sheets):
    locs = [s for s in sheets if s.visible and any(isinstance(v, str) and re.match(r"^insured\s*name", norm(v)) for _, cells in s.rows[:15] for _, v in cells)]
    q = {"layout": "blocks", "source_sheet": locs[0].name, "locations": []}
    q1._header(locs[0], q)
    _period(q)
    fire_total = burg_total = 0.0
    fire_items, burg_items = [], []
    for sh in locs:
        hdr = {}
        q1._header(sh, hdr)
        loc = {"sheet": sh.name, "address": hdr.get("risk_location"), "occupancy": hdr.get("occupancy"),
               "fire_items": [], "fire_total": None, "burglary_items": [], "burglary_total": None, "addons": []}
        mode = None
        for _, cells in sh.rows:
            txt = _texts(cells)
            t0 = norm(txt[0][1]) if txt else ""
            if len(cells) == 1 and txt:
                if re.search(r"standard fire|fire (and|&) special", t0):
                    mode = "fire"
                elif re.search(r"^burglary", t0):
                    mode = "burglary"
                elif re.search(r"^(terms|claim details|magma gil)", t0):
                    mode = None
                continue
            if mode and txt and re.match(r"^total\s*(sum insured|\(rs)", t0):
                num = [v for _, v in cells if is_num(v)]
                if num:
                    loc[f"{'fire' if mode == 'fire' else 'burglary'}_total"] = num[-1]
                    mode = None
                continue
            if mode and txt and not re.search(r"sr no|risk description|description|cover required|renewal sum", t0):
                it = _item(cells)
                if it and not re.match(r"^(burglary|theft|rsmd|damage|waiver)", norm(it[0])):
                    loc[f"{'fire' if mode == 'fire' else 'burglary'}_items"].append({"description": it[0], "si": it[1]})
        loc["addons"] = _addons_block(sh)
        for k, v in (("fire_total", "fire"), ("burglary_total", "burglary")):
            pass
        fire_total += loc["fire_total"] or 0
        burg_total += loc["burglary_total"] or 0
        fire_items += loc["fire_items"]
        burg_items += loc["burglary_items"]
        q["locations"].append(loc)
    # premiums per section from the summary sheet (header names), else unknown
    fp = bp = None
    for sh in sheets:
        if not sh.visible:
            continue
        head = next(((rn, dict(c)) for rn, c in sh.rows if any(isinstance(v, str) and norm(v) == "fire premium" for _, v in c)), None)
        if not head:
            continue
        cols = {norm(v): c for c, v in head[1].items() if isinstance(v, str)}
        for rn, c in sh.rows:
            if rn <= head[0]:
                continue
            by = dict(c)
            if cols.get("fire premium") in by and cols.get("burglary premium") in by and not any(isinstance(v, str) for v in by.values()):
                fp, bp = by[cols["fire premium"]], by[cols["burglary premium"]]
        break
    q["sections"] = {1: {"heading": "Standard Fire & Special Perils", "items": fire_items, "total_si": fire_total, "rate": None, "premium": fp, "first_loss_pct": None, "notes": []},
                     3: {"heading": "Burglary", "items": burg_items, "total_si": burg_total, "rate": None, "premium": bp, "first_loss_pct": None, "notes": []}}
    net = (fp or 0) + (bp or 0)
    q["premium_summary"] = {"net_premium": net, "gst": net * 0.18, "total_premium": net * 1.18}
    q.update(q1._terms(locs[0])) if False else None
    q.update(_terms_broad(locs[0]))
    q["coverages"] = q["locations"][0]["addons"]
    return q


def _addons_block(sh):
    out, on = [], False
    for _, cells in sh.rows:
        txt = _texts(cells)
        if any(norm(v) == "add-on covers" for _, v in txt):
            on = True
            continue
        if on and txt and re.match(r"^(claim details|burglary|terms)", norm(txt[0][1])):
            break
        if not on or len(txt) < 2:
            continue
        sr = next((v for _, v in cells if _is_sr(v)), None)
        name, status = txt[0][1], txt[-1][1]
        if norm(name) in ("free clauses",) and len(txt) > 2:
            name = txt[1][1]
        nums = [v for c, v in cells if is_num(v) and v > 1000]  # a sum insured printed in the limit column
        out.append({"sr": int(sr) if sr is not None else None, "name": name,
                    "limit": nums[0] if nums else (txt[1][1] if len(txt) > 2 else None), "status": status})
    return out


def _terms_broad(sh):
    """Like quote._terms but with the heading variants seen in the Mann's / Magma Terms sheets."""
    res = {"deductibles": {"fire": [], "burglary": []}, "conditions": {"fire": [], "burglary": [], "all": []},
           "quote_date": None, "validity": None, "claims_terms": []}
    on, state, sec = False, None, None
    for _, cells in sh.rows:
        c0, text = cells[0]
        if not isinstance(text, str):
            continue
        t = norm(text)
        if re.match(r"^terms and conditions", t):
            on = True
            continue
        if not on:
            continue
        t = re.sub(r"^[øø•➢\-\s]+", "", t)
        text = re.sub(r"^[Ø➢•\s]+", "", text)
        m = re.search(r"quote date\s*[:\-]?\s*(.+)", t)
        if m and find_dates(m.group(1)):
            res["quote_date"] = find_dates(m.group(1))[0]
            continue
        if re.match(r"^section\s*[–-]\s*1", t):
            sec, state = "fire", None
        elif re.match(r"^section\s*[–-]\s*3", t):
            sec, state = "burglary", None
        elif re.match(r"^(excess/)?deductible", t):
            state = ("deductibles", sec or "fire")
        elif re.match(r"^(conditions\s*/\s*warranties|coverages\s*/\s*clauses|terms/conditions)", t):
            state = ("conditions", sec or "fire")
        elif re.match(r"^conditions applicable to all", t):
            state = ("conditions", "all")
        elif t.startswith("excess") and sec == "burglary":
            res["deductibles"]["burglary"].append(text)
        elif re.match(r"^terms, conditions, and capacity", t):
            state = ("claims", None)
            res["claims_terms"].append(text)
        elif state and state[0] == "claims":
            res["claims_terms"].append(text)
        elif state:
            res[state[0]][state[1]].append(text)
    return res


# ------------------------------------------------------------------ matrix (Valmet)
def parse_matrix(sheets, hint=None):
    summ = next(s for s in sheets if s.visible and (not hint or hint.lower() in s.name.lower()) and any(
        isinstance(v, str) and norm(v) == "fire premium" for _, c in s.rows for _, v in c))
    rfq = next((s for s in sheets if s.visible and s is not summ and (not hint or hint.lower() in s.name.lower())
                and any(isinstance(v, str) and re.match(r"^insured\s*name", norm(v)) for _, c in s.rows[:15] for _, v in c)), None)
    q = {"layout": "matrix", "source_sheet": summ.name, "rfq_sheet": rfq.name if rfq else None}
    if rfq:
        q1._header(rfq, q)
        m = re.search(r"from\s+(.+?)\s+to\s+(.+)", q.get("policy_period", ""), re.I)
        _period(q)
    hrow = next((rn, dict(c)) for rn, c in summ.rows if any(isinstance(v, str) and norm(v) == "fire premium" for _, v in c))
    cols = {norm(re.sub(r"\s+", " ", v)): c for c, v in hrow[1].items() if isinstance(v, str)}

    def col(*names):
        for n in names:
            for k, c in cols.items():
                if k == n or k.startswith(n):
                    return c
        return None

    rows = [(rn, dict(c)) for rn, c in summ.rows if rn > hrow[0]]
    total = next(r for rn, r in rows if not any(isinstance(v, str) for v in r.values()) and len(r) > 5)

    def tot(*names):
        """Total-row value; if that cell is blank/0 but the rows hold values, sum the rows (the quote's total row can miss a column)."""
        c = col(*names)
        if not c:
            return 0.0
        t = float(total.get(c, 0) or 0)
        return t if t else float(sum(r.get(c, 0) or 0 for _, r in rows if r is not total and is_num(r.get(c)) and not any(isinstance(v, str) and norm(v).startswith("total") for v in r.values())))

    fire_si, building, pm = tot("fire si", "tsi"), tot("building"), tot("plant & machinery")
    prem = {}
    for label_row in rows:
        for c, v in label_row[1].items():
            if isinstance(v, str) and norm(v) in ("total premium", "addon premium", "total premium incl addon"):
                nums = [x for x in label_row[1].values() if is_num(x)]
                prem[norm(v)] = nums[-1] if nums else None
    addon = prem.get("addon premium") or 0
    s = {}
    s[1] = {"total_si": fire_si, "premium": tot("fire premium") + tot("terrorism premium") + addon}
    s[2] = {"total_si": tot("fire loss of profit"), "premium": tot("flop premium") + tot("flop terrorism")}
    s[3] = {"total_si": fire_si - building, "premium": tot("burglary"), "inferred": "SI = fire SI - building"}
    s[4] = {"total_si": pm, "premium": tot("mbd")}
    s[5] = {"total_si": tot("electronic equipment"), "premium": tot("eei premium")}
    s[7] = {"total_si": tot("cash in safe"), "premium": tot("money")}
    q["sections"] = {k: {**v, "heading": "", "items": [], "rate": None, "first_loss_pct": None, "notes": []} for k, v in s.items() if v["total_si"] or v["premium"]}
    # one location per data row: address, occupancy and the SI columns that hold a value
    si_cols = [(c, v) for c, v in ((col(n), n) for n in ("building", "office equipment", "plant & machinery", "stocks", "furniture", "goods held in trust")) if c]
    head_names = {c: re.sub(r"\s+", " ", v) for c, v in hrow[1].items() if isinstance(v, str)}
    addr_c, occ_c = col("address"), col("occupancy")
    q["locations"] = []
    for rn, r in rows:
        if addr_c in r and isinstance(r[addr_c], str) and any(is_num(r.get(c)) for c, _ in si_cols):
            items = [{"description": head_names[c], "si": r[c]} for c, _ in si_cols if is_num(r.get(c)) and r[c]]
            q["locations"].append({"sheet": summ.name, "address": re.sub(r"\s+", " ", r[addr_c]), "occupancy": re.sub(r"\s+", " ", str(r.get(occ_c) or "")),
                                   "fire_items": items, "fire_total": r.get(col("fire si", "tsi")), "burglary_items": [], "burglary_total": None, "addons": []})
    net = prem.get("total premium incl addon")
    q["premium_summary"] = {"net_premium": net, "gst": (net or 0) * 0.18, "total_premium": (net or 0) * 1.18}
    # the policy's 'Terrorism' line bundles terrorism + FLOP terrorism + add-on premium; 'Basic' is the rest (seen on the Valmet policy)
    q["premium_parts"] = {"terrorism": tot("terrorism premium") + tot("flop terrorism") + addon}
    if rfq:
        q.update(_terms_broad(rfq))
        q["coverages"] = _covers_rfq(rfq)
    return q


def _covers_rfq(sh):
    out, on = [], False
    for _, cells in sh.rows:
        txt = _texts(cells)
        if txt and norm(txt[0][1]) == "covers":
            on = True
            continue
        if on and txt and re.match(r"^(flop for|section)", norm(txt[0][1])):
            break
        if on and len(txt) >= 2:
            out.append({"sr": None, "name": txt[0][1], "limit": None, "status": txt[-1][1]})
    return out


# ------------------------------------------------------------------ per-section terms
def terms_by_section(sh):
    """Conditions and excess lines per section number, from 'Section - N' headings in a Terms and Conditions block."""
    cond, ded, allc = {}, {}, []
    on, sec, state = False, None, None
    for _, cells in sh.rows:
        c0, text = cells[0]
        if not isinstance(text, str):
            continue
        raw = re.sub(r"^[Ø➢•\s]+", "", text).strip()
        t = norm(raw)
        if re.match(r"^terms and conditions", t):
            on = True
            continue
        if not on:
            continue
        if re.match(r"^terms, conditions, and capacity|^quotation vali|^quote date", t):
            break
        m = re.match(r"^section\s*[–-]\s*(\d+)", t)
        if m:
            sec, state = int(m.group(1)), None
            continue
        if re.match(r"^conditions applicable to all", t):
            sec, state = "all", "cond"
            continue
        if t.startswith("**") or t.startswith("table of") or re.match(r"^section\s+\d", t) or t == "section excess":
            continue
        if re.match(r"^(excess/)?deductible:?$|^excess:?$", t):
            state = "ded"
            continue
        if re.match(r"^(coverages\s*/\s*clauses|terms/conditions|terms and conditions/warranties|conditions\s*/\s*warranties|coverage:?$)", t):
            state = "cond"
            continue
        if t.startswith("excess") and len(t) > 12 and not t.startswith("excess:"):
            ded.setdefault(sec, []).append(raw)
            continue
        if sec is None:
            continue
        if sec == "all":
            allc.append(raw)
        elif state == "ded":
            ded.setdefault(sec, []).append(raw)
        else:
            cond.setdefault(sec, []).append(raw)
    return {"conditions": cond, "deductibles": ded, "all": allc}


def unify(q):
    """Give every layout the same extra shape: q['terms'] keyed by section number and q['locations'] with items."""
    if "terms" not in q:
        c, d = q.get("conditions", {}), q.get("deductibles", {})
        q["terms"] = {"conditions": {1: c.get("fire", []), 3: c.get("burglary", [])}, "deductibles": {1: d.get("fire", []), 3: d.get("burglary", [])},
                      "all": c.get("all", [])}
    if "locations" not in q:
        s1, s3 = q["sections"].get(1, {}), q["sections"].get(3, {})
        q["locations"] = [{"sheet": q.get("source_sheet"), "address": q.get("risk_location"), "occupancy": q.get("occupancy"),
                           "fire_items": s1.get("items", []), "fire_total": s1.get("total_si"), "burglary_items": s3.get("items", []),
                           "burglary_total": s3.get("total_si"), "addons": q.get("coverages", [])}]
    return q


# ------------------------------------------------------------------ dispatcher
def detect(sheets):
    vis = [s for s in sheets if s.visible]
    for s in vis:  # a matrix has fire AND terrorism/net premium columns in one header row
        for _, c in s.rows:
            heads = {norm(v) for _, v in c if isinstance(v, str)}
            if "fire premium" in heads and ({"terrorism premium", "net premium"} & heads):
                return "matrix"
    if any(isinstance(v, str) and norm(v) == "add-on covers" for s in vis for _, c in s.rows[:40] for _, v in c):
        return "blocks"
    return "asset"


def parse(path, hint=None):
    sheets = load(path)
    kind = detect(sheets)
    if kind == "matrix":
        q = parse_matrix(sheets, hint)
        rfq = next((s for s in sheets if s.name == q.get("rfq_sheet")), None)
        if rfq:
            q["terms"] = terms_by_section(rfq)
    elif kind == "blocks":
        q = parse_blocks(sheets)
    else:
        q = q1.parse(path)
        q["layout"] = "asset"
    return unify(q)
