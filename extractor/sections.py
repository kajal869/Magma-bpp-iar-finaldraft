"""Per-section sum insured / premium and the terms (conditions, deductibles) from a quote workbook.

Three layout families (detected from the quote, never from the insured's name):
  blocks  one sheet per location, SFSP / burglary item tables, premiums on a "Premium working" sheet   (pilot quote2.parse_blocks)
  matrix  a summary table with a row per location and a column per cover; terms on the RFQ sheet        (pilot quote2.parse_matrix)
  laghu   one "Quote" sheet: Roman-numeral sections (I Fire, II Burglary, IV Money ...) with SI / rate / premium (new reader below)

Output: a dict with 13 section rows, terms in the schema's text-group shape, location/item data for annexures, and warnings.
Every number carries a status: ok (read directly and the section premiums tie to the quote's net premium), check (read but the
tie-out fails or a column looks empty), not_found. Unknown stays None; nothing is invented.
"""
from __future__ import annotations

import re

from .legacy import quote2
from .legacy.grid import is_num, load, norm

TIE = 2.0   # rupees: premium columns are rounded on some quotes

SECTION_LABELS = {1: "Fire Insurance Cover", 2: "Fire Loss of Profit Cover", 3: "Burglary and Housebreaking Cover", 4: "Machinery Breakdown Cover",
                  5: "Electronic Equipment Cover", 6: "Boiler and Pressure Plant Cover", 7: "Money/Cash Cover - Money in Safe",
                  8: "Fidelity Cover – Aggregate Limit", 9: "All Risk Cover", 10: "Plate Glass Cover", 11: "Neon Sign/Glow Sign Cover",
                  12: "Baggage Cover", 13: "Public Liability Cover"}
TERM_TITLES = {1: "SECTION 1 – FIRE INSURANCE COVER", 2: "SECTION 2 – FIRE LOSS OF PROFIT COVER", 3: "SECTION 3 – BURGLARY AND HOUSEBREAKING COVER",
               4: "SECTION 4 – MACHINERY BREAKDOWN COVER", 5: "SECTION 5 – ELECTRONIC EQUIPMENT COVER", 6: "SECTION 6 – BOILER AND PRESSURE PLANT COVER",
               7: "SECTION 7 – MONEY INSURANCE COVER", 8: "SECTION 8 – FIDELITY COVER", 9: "SECTION 9 – ALL RISK COVER",
               10: "SECTION 10 – PLATE GLASS COVER", 11: "SECTION 11 – NEON SIGN/GLOW SIGN COVER", 12: "SECTION 12 – BAGGAGE COVER",
               13: "SECTION 13 – PUBLIC LIABILITY COVER"}
KEYWORDS = [(r"loss of profit|\bflop\b", 2), (r"fire", 1), (r"burglary|house ?breaking", 3), (r"machinery|breakdown", 4), (r"electronic", 5), (r"boiler", 6),
            (r"money|cash", 7), (r"fidelity", 8), (r"all risk", 9), (r"plate glass", 10), (r"neon|glow", 11), (r"baggage", 12), (r"public liability", 13)]


def section_no(text: str):
    t = norm(text)
    return next((n for rx, n in KEYWORDS if re.search(rx, t)), None)


def _empty_sections() -> dict:
    return {n: {"no": n, "label": SECTION_LABELS[n], "sum_insured": None, "premium": None, "status": "not_found", "note": "", "sub_rows": []} for n in range(1, 14)}


def _txt(v):
    return " ".join(str(v).replace("\xa0", " ").split()) if isinstance(v, str) else ""


# ------------------------------------------------------------------ laghu layout
ROMAN = re.compile(r"^(?:I|II|III|IV|V|VI|VII|VIII|IX|X)$")


def detect_laghu(sheets):
    for s in sheets:
        if not s.visible:
            continue
        hdr = any({"description", "sum insured", "premium"} <= {norm(v) for _, v in cells if isinstance(v, str)} for _, cells in s.rows)
        romans = sum(1 for _, cells in s.rows if cells and isinstance(cells[0][1], str) and ROMAN.match(cells[0][1].strip()))
        if hdr and romans >= 2:
            return s
    return None


def parse_laghu(sh) -> dict:
    sections, items, subs, warns = _empty_sections(), [], [], []
    started, cur, after_total = False, None, False
    net = None
    money = {}
    for rn, cells in sh.rows:
        vals = [(c, v) for c, v in cells]
        texts = [_txt(v) for c, v in vals if isinstance(v, str)]
        nums = [v for c, v in vals if is_num(v)]
        first = texts[0] if texts else ""
        if not started:
            started = any({"description", "sum insured", "premium"} <= {norm(t) for t in texts} for _ in [0])
            continue
        low = norm(first)
        if re.match(r"^total sum insured of all sections|^total premium$|^total$", low) and nums and "gst" not in low:
            net = nums[-1]
            cur = None
            continue
        if low.startswith(("gst", "total premium with gst", "deductible", "conditions")):
            cur = None
            continue
        if ROMAN.match(first.strip()) and len(texts) >= 2:
            cur = section_no(texts[1])
            after_total = False
            lab = texts[1]
            if cur and cur != 1:
                row = sections[cur]
                if cur == 7:
                    money_row(money, lab + " " + " ".join(texts[2:]), nums)
                elif nums:
                    row["sum_insured"] = nums[0]
                    row["premium"] = nums[-1] if len(nums) >= 3 else None
                    row["desc"] = texts[2] if len(texts) > 2 else None
            continue
        if cur == 1:
            if re.match(r"^total sum insured", low) and nums:
                sections[1]["sum_insured"] = nums[-1]
                after_total = True
            elif not after_total and nums and texts:
                desc = texts[0] if len(texts) == 1 else texts[0] + " " + texts[1] if texts[1] and len(texts[1]) > 30 else texts[0]
                desc = texts[1] if len(texts) > 1 and len(texts[1]) > 30 else texts[0]
                items.append({"description": desc, "si": nums[0]})
            elif after_total and len(nums) >= 3:
                sections[1]["premium"] = (sections[1]["premium"] or 0) + nums[-1]
                sections[1].setdefault("perils", []).append({"name": texts[0] if texts else "", "si": nums[0], "premium": nums[-1]})
        elif cur == 7 and texts:
            money_row(money, " ".join(texts), nums)
        elif cur == 3 and texts and nums and sections[3]["sum_insured"] is None:
            sections[3]["sum_insured"], sections[3]["premium"] = nums[0], (nums[-1] if len(nums) >= 3 else None)
    sec7(sections, money)
    hdr = {}
    for _, cells in sh.rows[:14]:
        t = [_txt(v) for c, v in cells if isinstance(v, str) and _txt(v)]
        if len(t) >= 2:
            hdr[norm(t[0]) if not re.fullmatch(r"[\d.]+", t[0]) else norm(t[1])] = t[-1]
    return {"sections": sections, "net": net, "items": items, "warnings": warns, "layout": "laghu", "header": hdr}


def money_row(money: dict, label: str, nums: list):
    t = norm(label)
    si = nums[0] if nums else None
    pr = nums[-1] if len(nums) >= 3 else None
    if "annual" in t or "turnover" in t or "estimated" in t:
        money["annual"] = (si, pr)
    elif "safe" in t or "strong room" in t:
        money["safe"] = (si, pr)
    elif "till" in t or "counter" in t:
        money["till"] = (si, pr)
    elif "transit" in t:
        money["transit_single"] = (si, pr)
    elif nums:
        money["safe"] = (si, pr)           # a single undifferentiated money row


def sec7(sections: dict, money: dict):
    if not money:
        return
    row = sections[7]
    main = money.get("safe") or money.get("till")
    if main:
        row["sum_insured"], row["premium"] = main
    if money.get("till") and money.get("safe"):
        row["sub_rows"].append({"label": "Cash at/till Counter", "sum_insured": money["till"][0], "premium": money["till"][1]})
    if money.get("annual"):
        row["sub_rows"].append({"label": "Money in Transit –Estimated Annual Transit", "sum_insured": money["annual"][0], "premium": money["annual"][1]})
    row["money"] = {k: v[0] for k, v in money.items()}


LAGHU_GROUP = [(r"bharat laghu|laghu udyam suraksha|fire", 1), (r"burglary", 3), (r"money|cash", 7), (r"public liability", 13), (r"machinery", 4), (r"electronic", 5)]


def laghu_terms(sh) -> dict:
    """Deductible / Conditions blocks. Two heading orders occur: a mode heading first and cover headings under it (Laghu), or an explicit
    "Section - N ..." heading first with Excess / Conditions sub-headings under it (SFSP-style quotes)."""
    mode, sec, sub, explicit = None, None, None, False
    ded, cond, allc, subg = {}, {}, [], {}
    for _, cells in sh.rows:
        texts = [_txt(v) for c, v in cells if isinstance(v, str) and _txt(v)]
        if not texts or len(texts) > 2 and any(is_num(v) for _, v in cells):
            continue
        t = texts[-1] if len(texts) == 1 else " ".join(texts)
        low = norm(t)
        mnum = re.match(r"^section\s*[\u2013\u2014\-:.]*\s*(\d{1,2})\b", low)
        if mnum and len(t) < 80 and not any(is_num(v) for _, v in cells):
            sec, sub, explicit, mode = int(mnum.group(1)), None, True, None
            continue
        if re.match(r"^(?:excess\s*/\s*)?deductibles?\b|^excess\s*:?$", low):
            mode, sub = "ded", None
            sec = sec if explicit else None
            continue
        if re.match(r"^conditions\s*[,/]\s*warranties|^coverages\s*/\s*clauses", low):
            mode, sub = "cond", None
            sec = sec if explicit else None
            continue
        if re.match(r"^conditions applicable to all", low):
            mode, sec, sub, explicit = "all", None, None, False
            continue
        if re.match(r"^terms, conditions, and capacity|^quotation valid|^quote date|^our (terms|quote)", low):
            if mode == "all":
                mode = None
            continue
        if mode is None:
            continue
        if mode == "all":
            if re.match(r"^(terms, conditions|our terms|our quote|quotation|quote date)", low):
                mode = None
                continue
            allc.append(t)
            continue
        grp = next((n for rx, n in LAGHU_GROUP if re.search(rx, low) and len(t) < 60), None)
        if not explicit and grp and len(t.split()) <= 6:
            sec, sub = grp, None
            continue
        if sec is None:
            continue
        if mode == "ded":
            ded.setdefault(sec, []).append(t)
        elif t.endswith("-") and len(t) < 50:
            sub = t
            subg.setdefault(sec, {}).setdefault(sub, [])
        elif sub and sec == 7:
            subg[sec][sub].append(t)
        else:
            cond.setdefault(sec, []).append(t)
    return {"conditions": cond, "deductibles": ded, "all": allc, "sub_groups": subg}


# ------------------------------------------------------------------ dispatch
def _legacy(path, variant, out) -> bool:
    """The pilot readers (blocks / matrix / asset). True if they produced at least one section; never raises."""
    try:
        q = quote2.parse(path, variant)
    except Exception as e:
        out["warnings"].append(f"built-in reader could not read this layout ({type(e).__name__}: {e})")
        return False
    got = False
    for no, s in q["sections"].items():
        row = out["sections"][int(no)]
        row["sum_insured"], row["premium"] = s.get("total_si"), s.get("premium")
        row["items"] = s.get("items", [])
        if s.get("inferred"):
            row["note"] = s["inferred"]
        got = got or bool(row["sum_insured"] or row["premium"])
    if not got:
        return False
    out["layout"] = q["layout"]
    t = q.get("terms", {})
    out["terms"] = {"conditions": {int(k): v for k, v in (t.get("conditions") or {}).items()},
                    "deductibles": {int(k): v for k, v in (t.get("deductibles") or {}).items()},
                    "all": t.get("all") or [], "sub_groups": {}}
    out["locations"] = q.get("locations", [])
    out["header"] = {k: q.get(k) for k in ("insured_name", "address", "risk_location", "occupancy", "business_description", "policy_start", "policy_end")}
    out["layout_info"] = {"source": "builtin", "profile": None, "reader": q["layout"]}
    return True


def _fill_generic(out: dict, got: dict) -> None:
    """Copy a profile / discovered read into the common section structure."""
    out["layout"] = got["reader"]
    out["net"] = got.get("net_used")
    for n, d in got["sections"].items():
        row = out["sections"][n]
        row["sum_insured"], row["premium"] = d["si"], d["premium"]
        row["refs"] = d.get("refs", [])
        if d.get("extra_lines"):
            row["note"] = f"includes {d['extra_lines']} extra premium line(s) under the section (e.g. terrorism)"
        if got["reader"] == "location_matrix":
            row["note"] = "single-section quote: the whole premium is assigned to Section 1"
    out["gross"] = got.get("gross")
    out["layout_info"] = got["layout_info"] | {"reader": got["reader"], "verified": got["verified"], "net_cell": got.get("net_ref")}
    try:
        out["terms"] = laghu_terms(got["sheet"])            # the same heading-driven term reader, headings found by section name
    except Exception:
        pass
    if not got["verified"]:
        out["warnings"].append("sections were read by a generic recipe but the section premiums do not add up to the net premium; shown as check")


def read(path: str, variant: str | None = None, net: float | None = None, slip: dict | None = None) -> dict:
    """-> {layout, sections{1..13}, net, terms, locations, items, scalars, taught, layout_info, warnings}.
    `net` = the resolved net premium (tie-out when the sheet has none); `slip` = the parsed closing slip (second source for section 1/2 sum insured)."""
    from .layouts import engine
    out = {"layout": None, "sections": _empty_sections(), "net": None, "terms": {"conditions": {}, "deductibles": {}, "all": [], "sub_groups": {}},
           "locations": [], "items": [], "warnings": [], "scalars": {}, "taught": {}, "layout_info": {"source": "none", "profile": None}}
    sheets = load(path)
    lag = detect_laghu(sheets)
    if lag is not None:
        r = parse_laghu(lag)
        out.update(layout="laghu", net=r["net"], items=r["items"], sections=r["sections"], terms=laghu_terms(lag), header=r["header"],
                   layout_info={"source": "builtin", "profile": None, "reader": "laghu"})
    else:
        got = engine.apply_profiles(sheets, net)
        if got:
            _fill_generic(out, got)
        elif not _legacy(path, variant, out):
            got = engine.discover(sheets, net)
            if got:
                _fill_generic(out, got)
            else:
                out["layout_info"] = {"source": "unsupported", "profile": None, "teach": True}
                out["warnings"].append("layout not recognised: no built-in reader, stored profile or generic recipe fits this quote. "
                                       "Point at the cells once (POST /api/layouts/teach) and the same format will be read next time.")
    if out["net"] is None:
        out["net"] = net
    out["scalars"] = engine.scalars(sheets)
    _apply_taught(out, engine.taught_overrides(sheets))
    _from_slip(out, slip or {})
    _drop_unopted_terms(out)
    out["warnings"] += _status(out)
    return out


def _apply_taught(out: dict, taught: dict) -> None:
    """Cells a person pointed at win for their field and say so."""
    if taught and out["layout_info"].get("source") == "unsupported":
        pid = next(iter(taught.values()))["profile"]
        out["layout"], out["layout_info"] = "taught", {"source": "taught", "profile": pid, "reader": "taught cells"}
        out["warnings"] = [w for w in out["warnings"] if not w.startswith("layout not recognised")]
    for target, t in taught.items():
        m = re.fullmatch(r"section\.(\d+)\.(si|premium)", target)
        if m and is_num(t["value"]):
            row = out["sections"][int(m.group(1))]
            row["sum_insured" if m.group(2) == "si" else "premium"] = float(t["value"])
            row["note"] = (row["note"] + "; " if row["note"] else "") + f"taught location {t['sheet']}!{t['ref']}"
            row["taught"] = True
        else:
            out["taught"][target] = t


def _from_slip(out: dict, slip: dict) -> None:
    """The closing slip's RI allocation states the fire (and FLOP) sum insured: a second source, and a fallback when the quote is unreadable."""
    for sec, key, name in ((1, "pd_allocation", "Property Damage (Fire Section)"), (2, "bi_allocation", "Business Interruption (FLOP Section)")):
        v = slip.get(key)
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if v < 1000:                                   # a share (0..1) or blank, not a sum insured
            continue
        row = out["sections"][sec]
        if row["sum_insured"] in (None, 0):
            row["sum_insured"], row["status"] = v, "check"
            row["note"] = f"sum insured from the closing slip ({name}); the quote's section table could not be read"
            row["from_slip"] = True
        elif abs(row["sum_insured"] - v) > 1.5:
            row["slip_sum_insured"] = v
            row["note"] = (row["note"] + "; " if row["note"] else "") + f"closing slip says {v:,.0f} for this section"


def _drop_unopted_terms(out: dict) -> None:
    """Terms are printed only for sections that carry a sum insured or premium on the quote."""
    opted = {n for n, s in out["sections"].items() if s["sum_insured"] or s["premium"]}
    t = out["terms"]
    dropped = sorted((set(t["conditions"]) | set(t["deductibles"])) - opted)
    for k in ("conditions", "deductibles"):
        t[k] = {n: v for n, v in t[k].items() if n in opted}
    if dropped:
        out["warnings"].append(f"terms for section(s) {dropped} were found but those sections carry no sum insured; left out")


def _status(out: dict) -> list[str]:
    """ok only when the section premiums tie to the quote's net premium and no column looks empty; otherwise check."""
    warns, secs = [], out["sections"]
    have = [s for s in secs.values() if s["sum_insured"] is not None or s["premium"] is not None]
    total = 0.0
    for s in have:
        total += s["premium"] or 0
        total += sum((x["premium"] or 0) for x in s["sub_rows"] if s["no"] == 7 and x["label"].startswith("Money in Transit"))
        if s["no"] == 7 and any(x["label"].startswith("Cash at") for x in s["sub_rows"]):
            total += sum((x["premium"] or 0) for x in s["sub_rows"] if x["label"].startswith("Cash at"))
    empty_prem = [s["no"] for s in have if s["sum_insured"] and not s["premium"]]
    tied = out["net"] is not None and abs(total - out["net"]) <= TIE
    out["premium_sum"], out["tie"] = total, tied
    for s in have:
        if s.get("from_slip"):
            continue                                       # already `check`, with its own note
        if s.get("slip_sum_insured"):
            s["status"] = "check"
            continue
        if empty_prem and s["no"] not in empty_prem and s["premium"]:
            s["status"], s["note"] = "check", (s["note"] + "; " if s["note"] else "") + f"section(s) {empty_prem} have a sum insured but no premium; premium split may be misallocated"
        elif empty_prem and s["no"] in empty_prem:
            s["status"], s["note"] = "check", "sum insured present but premium column is empty"
        elif out["net"] is not None and not tied:
            s["status"], s["note"] = "check", f"section premiums total {total:,.2f} but the quote's net premium is {out['net']:,.2f}"
        elif out["net"] is None:
            s["status"], s["note"] = "check", "no net premium found on this sheet to tie the section premiums to"
        else:
            s["status"] = "ok" if not s["note"] else "derived"
    if have and not out["terms"]["all"]:
        warns.append("conditions applicable to all sections were not found on the quote; the front pack prints that block empty")
    if empty_prem:
        warns.append(f"section premium looks empty for section(s) {empty_prem}; check the split")
    return warns


# ------------------------------------------------------------------ to schema
def term_groups(terms: dict) -> dict:
    """-> {'section_conditions': [...], 'deductibles': [...], 'all_sections_conditions': {...}} in the schema's text-group shape."""
    def groups(by_sec, with_sub=False):
        out = []
        for n in sorted(by_sec):
            lines = [x for x in by_sec[n] if x]
            g = {"key": f"S{n}", "title": TERM_TITLES.get(n, f"SECTION {n}"), "lines": lines}
            sg = terms.get("sub_groups", {}).get(n) if with_sub else None
            if sg:
                g["sub_groups"] = [{"title": k, "lines": v} for k, v in sg.items()]
            out.append(g)
        return out
    return {"section_conditions": groups(terms["conditions"], True), "deductibles": groups(terms["deductibles"]),
            "all_sections_conditions": {"key": "ALL", "title": "CONDITIONS AND WARRANTIES APPLICABLE TO ALL SECTIONS", "lines": list(terms["all"])}}
