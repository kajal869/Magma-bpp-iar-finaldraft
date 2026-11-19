"""Annexures from the quote: one per opted section, built only from what the quote states.

  laghu    section 1: sum-insured items + inbuilt covers (EQ / STFI rows the quote prices); section 3: first-loss block; section 7: money components
  blocks   section 1/3: si_groups from the per-location item tables, add-on blocks from the matched add-on rows
  matrix   add-on blocks only; the matrix/kv annexures of the commercial matrix layout are NOT built (flagged in `unbuilt`)
Add-on values are the quote's own limit text, never a computed sum insured; rows that still need review are carried with their reasons
in `provenance`, not hidden.
"""
from __future__ import annotations

import re


def _hdr(case_hdr: dict) -> dict:
    return {"insured": case_hdr.get("insured") or "", "risk_location": case_hdr.get("risk_location") or "",
            "business_activity": case_hdr.get("business_activity"), "occupancy": case_hdr.get("occupancy")}


def _rows(items):
    return [{"sr": i + 1, "desc": it["description"], "si": float(it["si"])} for i, it in enumerate(items)]


ADDON_COLUMNS = ["Sr. no.", "Description", "Sum Insured / Limit (in INR)"]


def addon_value(r: dict):
    """What the third column of an add-on table prints: the cover's sum insured when the quote states one (a plain amount), otherwise the insurer's
    (Magma) remark, otherwise whatever limit text the row has. Never blank when the quote said something about the cover."""
    lim = str(r.get("limit") or "").strip()
    rem = str(r.get("remark") or "").strip()
    if re.fullmatch(r"\d[\d,]*(?:\.\d+)?", lim) and float(lim.replace(",", "")) >= 1000:
        return float(lim.replace(",", ""))
    return rem or lim or None


def addon_block(rows: list[dict], heading: str) -> dict:
    out = []
    for i, r in enumerate(rows, 1):
        out.append({"sr": i, "desc": r.get("clause") or r["name"], "value": addon_value(r), "wording_id": r.get("wording_id")})
    return {"type": "addons", "heading": heading, "columns": ADDON_COLUMNS, "rows": out}


def kept(rows: list[dict]) -> list[dict]:
    """Kept add-on rows, one per clause (a clause quoted twice on a sheet prints once)."""
    seen, out = set(), []
    for r in rows:
        if r["decision"] != "keep":
            continue
        k = (r["sheet"], r["clause"] or r["name"].lower())
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def section_addon_blocks(addons: list[dict], n: int) -> list[dict]:
    """One add-on block per location sheet, only for rows that belong to section n (rows without a section count as section 1)."""
    by_sheet: dict[str, list] = {}
    for r in kept([r for r in addons if int(r.get("section") or 1) == n]):
        by_sheet.setdefault(r["sheet"], []).append(r)
    word = "Add on Covers-For Risk location-" if n == 1 else "Add on Covers for Risk location-"
    return [addon_block(rows, f"{word}{i}" if len(by_sheet) > 1 else "Add on Covers") for i, rows in enumerate(by_sheet.values(), 1)]


def build(sec: dict, addons: list[dict], case_hdr: dict) -> tuple[list[dict], list[str]]:
    secs, unbuilt, out = sec["sections"], [], []
    opted = [n for n, s in secs.items() if s["sum_insured"] or s["premium"]]
    layout = sec["layout"]
    for n in opted:
        s = secs[n]
        blocks = []
        case_hdr_n = case_hdr
        if layout == "laghu":
            if n == 1:
                blocks.append({"type": "si_simple", "columns": ["Sr. no.", "Description", "Sum Insured (in INR)"], "rows": _rows(sec["items"]),
                               "total": float(s["sum_insured"]), "total_label": "Total Sum Insured"})
                inbuilt = []
                for p in sorted(s.get("perils", []), key=lambda p: 0 if re.search(r"\beq\b|earthquake", p["name"], re.I) else 1):
                    nm = p["name"].strip()
                    inbuilt += [{"desc": "Earthquake (Fire & Shock) Cover", "si": p["si"]}] if re.search(r"\beq\b|earthquake", nm, re.I) else \
                               [{"desc": "STFI", "si": p["si"]}] if re.search(r"stfi", nm, re.I) else []
                if inbuilt:
                    blocks.append({"type": "si_simple", "heading": "Inbuilt Cover", "columns": ["Sr. no.", "Description", "Sum Insured (in INR)"],
                                   "rows": [{"sr": i + 1, **r} for i, r in enumerate(inbuilt)]})
                blocks += section_addon_blocks(addons, 1)    # add-on rows the quote or the user supplied (laghu quotes normally have none)
            elif n == 3:
                desc = s.get("desc") or "All contents, first loss basis"
                blocks.append({"type": "si_simple", "columns": ["Sr. no.", "Description", "Sum Insured (in INR)"],
                               "rows": [{"sr": 1, "desc": desc, "si": float(s["sum_insured"])}], "total": float(s["sum_insured"]), "total_label": "Total Sum Insured"})
                if re.search(r"first loss", desc, re.I):
                    m = re.search(r"first loss basis\s*[-–@]*\s*(\d+)\s*%", desc, re.I)
                    blocks.append({"type": "note", "text": f"First Loss Basis @ {m.group(1)}%" if m else "First Loss Basis"})
                    blocks.append({"type": "note", "text": f"First Loss Sum Insured – INR. {int(s['sum_insured']):,}"})
            elif n == 7:
                m = s.get("money", {})
                comp = [("Money In Transit (Estimated Annual Transit)", m.get("annual")), ("Money In Transit (Single Carrying Limit)", m.get("transit_single")),
                        ("Cash in safe / strong room", m.get("safe")), ("Cash at/till Counter", m.get("till"))]
                blocks.append({"type": "kv_rows", "columns": ["Sum Insured Component", "Sum Insured (in INR)"], "rows": [[k, float(v)] for k, v in comp if v]})
            else:
                unbuilt.append(f"annexure for section {n}")
        else:
            blocks, over, notes = _other(sec, n, s, addons)
            unbuilt += notes
            case_hdr_n = {**case_hdr, **over}
        if blocks:
            no = n if layout in BY_SECTION else len(out) + 1        # single-location policies number the annexure like its section (A1 / A3), like the issued ones
            out.append({"no": no, "applies_to_section": n, "title": f"ANNEXURE {no} – APPLICABLE TO SECTION {n}", "header": _hdr(case_hdr_n if layout != "laghu" else case_hdr), "blocks": blocks})
    return out, unbuilt


BY_SECTION = ("asset", "labelled_table")


# ------------------------------------------------------------------ the non-laghu layouts (blocks / asset / matrix / location table / plain totals)
BUILDING = re.compile(r"building|civil work|plinth", re.I)
SI_COLS = ["Sr. no.", "Description", "Total Sum Insured (in INR)"]
MATRIX_COL = {2: "fire loss of profit", 5: "electronic equipment", 7: "cash in safe"}
PLAIN_DESC = {1: "Fire Insurance Cover", 2: "Fire Loss of Profit", 3: "Burglary and Housebreaking Cover", 4: "Machinery Breakdown Cover", 5: "Electronic Equipment",
              7: "Cash in Safe", 8: "Fidelity Cover - Aggregate Limit"}
_BUCKETS = (("building", r"building|civil|plinth|shed"), ("pm", r"plant|machinery"), ("stock", r"stock"), ("fff", r"furniture|fixture|fitting|content"), ("git", r"trust"))


def _tie(rows, total) -> bool:
    return bool(rows) and abs(sum(float(r["si"]) for r in rows) - float(total)) <= max(1.0, abs(float(total)) * 1e-6)


def _simple(rows, total, heading=None) -> dict:
    return {"type": "si_simple", **({"heading": heading} if heading else {}), "columns": SI_COLS, "rows": [{"sr": i + 1, **r} for i, r in enumerate(rows)],
            "total": float(total), "total_label": "Total Sum Insured"}


def _items(items) -> list[dict]:
    return [{"desc": i["description"], "si": float(i["si"])} for i in items if i.get("si")]


def _first_loss(terms: dict, total: float) -> list[dict]:
    """'First Loss Basis @ 25%' + its sum insured, only when a section-3 condition states the percentage."""
    for l in (terms.get("conditions") or {}).get(3, []):
        m = re.search(r"first\s+loss\s+(?:basis|limit)\s*[-–@:]*\s*(\d+(?:\.\d+)?)\s*%|\bFLB\s*[-–@:]*\s*(\d+(?:\.\d+)?)\s*%", l, re.I)
        if m:
            pct = float(m.group(1) or m.group(2))
            return [{"type": "note", "text": f"First Loss Basis @ {pct:g}%"}, {"type": "note", "text": f"First Loss Sum Insured – INR {int(total * pct / 100):,}"}]
    return []


def _covered_pairs(terms: dict, existing: set) -> list[dict]:
    """A burglary condition such as "Theft and RSMD Covered" states two covers at once; each becomes a row of the add-on table."""
    rows = []
    for l in (terms.get("conditions") or {}).get(3, []):
        m = re.fullmatch(r"\s*(theft|rsmd|burglary)\s*(?:,|and|&)\s*(rsmd|theft|burglary)\s+(covered.*)", l, re.I)
        if m:
            for nm in (m.group(1), m.group(2)):
                if nm.lower() not in existing:
                    rows.append({"name": nm.upper() if nm.lower() == "rsmd" else nm.title(), "clause": None, "limit": "", "remark": m.group(3).strip().capitalize(), "wording_id": None})
    return rows


def _norm_label(s: str) -> list[str]:
    s = re.sub(r"@\s*\d+(?:\.\d+)?\s*%", " ", str(s).lower().replace("\u2019", "'"))
    s = re.sub(r"'s\b", "", s)
    return [w for w in re.findall(r"[a-z]+", s) if w not in ("of", "the", "and")]


def _ded_pairs(lines: list[str]) -> list[tuple[list[str], str]]:
    """Deductible lines of the form 'Escalation – Policy Excess' -> (label words, text)."""
    out = []
    for l in lines:
        m = re.match(r"^\s*([^–—:]+?)\s*[–—:]\s*(.+)$", l) or re.match(r"^\s*([^-]+?)\s+-\s+(.+)$", l)
        if m and len(_norm_label(m.group(1))) >= 1:
            out.append((_norm_label(m.group(1)), m.group(2).strip()))
    return out


def _attach_deductibles(blocks: list[dict], terms: dict, n: int, total) -> None:
    """An add-on that the section's excess table also prices ('Escalation – Policy Excess', 'Third Party Liability – 1% of the TPL limits') gets its own
    Deductible column, so the sum insured / limit column never carries deductible text. '@ N%' covers state their limit as N% of the section sum insured."""
    pairs = _ded_pairs((terms.get("deductibles") or {}).get(n, []))
    if not pairs:
        return
    for b in blocks:
        if b.get("type") != "addons":
            continue
        hit = 0
        for r in b["rows"]:
            w = _norm_label(r["desc"])
            for lab, txt in pairs:
                if w and lab and (set(w) <= set(lab) or set(lab) <= set(w)):
                    r["deductible"] = txt
                    hit += 1
                    break
        if hit:
            for r in b["rows"]:
                m = re.search(r"@\s*(\d+(?:\.\d+)?)\s*%", r["desc"])
                if m and total and isinstance(r["value"], str) and r["value"].strip().lower() == "covered":
                    r["value"] = round(float(total) * float(m.group(1)) / 100)
                r.setdefault("deductible", None)
            b["columns"] = ADDON_COLUMNS + ["Deductible"]


def _addon_blocks(addons: list[dict], n: int, terms: dict, total=None) -> list[dict]:
    blocks = section_addon_blocks(addons, n)
    if n == 3:
        have = {str(r["desc"]).lower() for b in blocks for r in b["rows"]}
        extra = _covered_pairs(terms, have)
        for e in extra:      # "Theft and RSMD Covered" with no separate limit and no first-loss % in the quote: covered up to the section sum insured
            if total and not _first_loss(terms, total) and str(e["remark"]).strip().lower() == "covered":
                e["limit"] = str(int(total))
        if extra and blocks:
            blocks[0]["rows"] += [{"sr": len(blocks[0]["rows"]) + i + 1, "desc": e["name"], "value": float(e["limit"]) if e.get("limit") else e["remark"], "wording_id": None} for i, e in enumerate(extra)]
        elif extra:
            blocks.append(addon_block(extra, "Add on Covers"))
    _attach_deductibles(blocks, terms, n, total)
    return blocks


def _pick(locs: list, total: float):
    """Locations of an item-by-location table that make up a section's sum insured: all of them, or the one whose total equals it."""
    locs = [l for l in locs if l["total"]]
    if not locs:
        return None
    if abs(sum(l["total"] for l in locs) - total) <= max(1.0, total * 1e-6):
        return locs
    one = [l for l in locs if abs(l["total"] - total) <= max(1.0, total * 1e-6)]
    return one[:1] or None


def _groups(locs, heading=None, drop_building=False):
    groups = []
    for l in locs:
        its = [i for i in l["items"] if not (drop_building and BUILDING.search(i["description"]))]
        groups.append({"label": "Risk Location", "address": l["name"], "rows": [{"sr": k + 1, "desc": i["description"], "si": float(i["si"])} for k, i in enumerate(its)],
                       "total": float(sum(i["si"] for i in its))})
    return {"type": "si_groups", **({"heading": heading} if heading else {}), "groups": groups, "grand_total": float(sum(g["total"] for g in groups))}


def _matrix(locs: list, n: int, total: float):
    """Matrix layout (one summary row per location): item columns for sections 1 and 3, a single column for the others. -> (block, [locs used]) or (None, [])."""
    rows, cols, used = [], [], []
    for l in locs:
        cells = {}
        if n in (1, 3):
            for it in l.get("fire_items") or []:
                if n == 3 and BUILDING.search(it["description"]):
                    continue
                key = next((k for k, rx in _BUCKETS if re.search(rx, it["description"], re.I)), it["description"])
                cells[key] = cells.get(key, 0) + float(it["si"])
                if key not in [c["key"] for c in cols]:
                    cols.append({"key": key, "label": it["description"]})
            tot = sum(cells.values())
        elif n == 4:
            tot = next((float(v) for k, v in (l.get("cols") or {}).items() if re.match(r"plant", k)), 0)
            cells["total"] = tot
        else:
            tot = next((float(v) for k, v in (l.get("cols") or {}).items() if k.startswith(MATRIX_COL.get(n, "\0"))), 0)
            cells["total"] = tot
        if tot:
            rows.append({"address": l.get("address") or "", "occupancy": l.get("occupancy") or "", "values": {**cells, "total": tot}})
            used.append(l)
    if not rows or abs(sum(r["values"]["total"] for r in rows) - total) > max(1.0, total * 1e-6):
        return None, []
    label = {1: "Fire SI", 3: "Burglary", 4: "MBD"}.get(n, "Sum Insured")
    columns = (cols if n in (1, 3) else []) + [{"key": "total", "label": label}]
    totals = {c["key"]: sum(r["values"].get(c["key"], 0) for r in rows) for c in columns}
    return {"type": "matrix", "heading": "Risk Location address as per annexure A", "columns": columns, "rows": rows, "total": totals}, used


def _other(sec: dict, n: int, s: dict, addons: list[dict]):
    """Annexure blocks for one opted section on the non-laghu layouts. -> (blocks, header overrides, notes). Item tables are printed only when they
    add up to the section's sum insured; otherwise one line with the section total (never a made-up breakdown)."""
    layout, terms, locs = sec["layout"], sec.get("terms") or {}, sec.get("locations") or []
    total, blocks, over, notes = float(s["sum_insured"] or 0), [], {}, []
    key = "fire_items" if n == 1 else "burglary_items"
    built = False
    if total:
        if layout == "blocks" and n in (1, 3) and locs:
            groups = [{"label": "Risk Location", "address": l.get("address") or "", "rows": _rows(l[key]), "total": float(sum(i["si"] for i in l[key]))} for l in locs if l.get(key)]
            if groups and abs(sum(g["total"] for g in groups) - total) <= max(1.0, total * 1e-6):
                blocks.append({"type": "si_groups", "heading": "Add on cover", "groups": groups, "grand_total": float(sum(g["total"] for g in groups))})
                built = True
        elif layout == "asset" and n in (1, 3) and (s.get("items") or (locs and locs[0].get(key))):
            its = _items(s.get("items") or locs[0].get(key))
            if _tie(its, total):
                blocks.append(_simple(its, total))
                built = True
                if locs:
                    over = {"risk_location": locs[0].get("address") or "", "occupancy": locs[0].get("occupancy") or ""}
                if n == 3:
                    blocks += _first_loss(terms, total)
        elif layout == "matrix" and locs:
            mb, used = _matrix(locs, n, total)
            if mb:
                if len(used) == 1:
                    blocks.append(_simple([{"desc": PLAIN_DESC.get(n, s["label"]), "si": total}], total))
                    over = {"risk_location": used[0].get("address") or "", "occupancy": used[0].get("occupancy") or ""}
                    if n in (1, 3, 4):
                        blocks.append(mb)
                else:
                    blocks.append(_simple([{"desc": "Risk Location address as per annexure", "si": total}], total))
                    blocks.append(mb)
                    over = {"risk_location": "Risk Location address as per annexure A", "occupancy": "Risk Location address as per annexure A"}
                built = True
        elif (sec.get("section_blocks") or {}).get(n):
            sb = sec["section_blocks"][n]
            if n in (1, 3) and abs(sum(b["total"] for b in sb) - total) <= max(1.0, total * 1e-6):
                if len(sb) == 1:
                    blocks.append(_simple(_items(sb[0]["items"]), total))
                    over = {"risk_location": sb[0]["address"]}
                else:
                    blocks.append(_groups([{"name": b["address"], "items": b["items"], "total": b["total"]} for b in sb], "Add on cover"))
                    over = {"risk_location": "As per annexure below", "occupancy": "As per annexure below"}
                built = True
                if n == 3 and all(b.get("first_loss_pct") for b in sb):
                    pcts = {b["first_loss_pct"] for b in sb}
                    if len(pcts) == 1:
                        pct = pcts.pop()
                        blocks += [{"type": "note", "text": f"First Loss Basis @ {pct:g}%"}, {"type": "note", "text": f"First Loss Sum Insured – INR {int(sum(b['total'] * pct / 100 for b in sb)):,}"}]
                if n == 3:   # the add-on covers printed under the burglary blocks (Theft / RSMD)
                    seen = {}
                    for b in sb:
                        for a in b["addons"]:
                            seen.setdefault(re.sub(r"\s*cover$", "", a["name"], flags=re.I).strip().upper() if a["name"].upper().startswith("RSMD") else re.sub(r"\s*cover$", "", a["name"], flags=re.I).strip(), a["remark"] or "Covered")
                    if seen:
                        have = {str(r["desc"]).lower() for blk in _addon_blocks(addons, n, terms, total) for r in blk["rows"]}
                        rows = [{"sr": i + 1, "desc": k, "value": v, "wording_id": None} for i, (k, v) in enumerate(seen.items()) if k.lower() not in have]
                        if rows:
                            blocks.append({"type": "addons", "heading": "Add on Covers", "columns": ADDON_COLUMNS, "rows": rows})
            elif n not in (1, 3):
                blocks.append({"type": "kv_rows", "columns": ["Description", "Sum Insured (in INR)"], "rows": [[i["description"], float(i["si"])] for b in sb for i in b["items"]]})
                over = {"risk_location": sb[0]["address"]}
                built = True
        else:
            lm = (sec.get("loc_matrix") or {}).get("locations")
            use = _pick(lm or [], total) if n == 1 else None
            if n == 3 and lm:                                    # burglary: the fire items without the building
                trial = [{**l, "items": [i for i in l["items"] if not BUILDING.search(i["description"])]} for l in lm]
                trial = [{**l, "total": sum(i["si"] for i in l["items"])} for l in trial]
                use = _pick(trial, total)
            if use:
                if len(use) == 1:
                    blocks.append(_simple(_items(use[0]["items"]), total))
                    over = {"risk_location": use[0]["name"], "occupancy": use[0]["occupancy"]}
                    inb = [(d, k) for d, k in (("Earthquake", ("eq", "earthquake")), ("STFI", ("stfi",)), ("Terrorism", ("terrorism",))) if any(use[0].get("perils", {}).get(x, 0) > 0 for x in k)]
                    if n == 1 and inb:                              # perils the quote prices for this location are covered up to the section sum insured
                        blocks.append({"type": "addons", "heading": "Add on Covers", "columns": ADDON_COLUMNS,
                                       "rows": [{"sr": i + 1, "desc": d, "value": total, "wording_id": None} for i, (d, _) in enumerate(inb)]})
                    if n == 3:
                        blocks += _first_loss(terms, total)
                else:
                    blocks.append(_groups(use, "Add on cover") if n == 1 else {**_groups(use, "Add on cover")})
                    over = {"risk_location": "As per annexure below", "occupancy": "As per annexure below"}
                built = True
    if not built and total:
        blocks.append(_simple([{"desc": s.get("desc") or PLAIN_DESC.get(n, s["label"]), "si": total}], total))
        notes.append(f"annexure {n}: no item breakdown that ties to the sum insured was found in the quote; the section total is printed alone")
    flb = any(b.get("type") == "note" and str(b.get("text", "")).startswith("First Loss") for b in blocks)      # a stated first-loss % keeps Theft / RSMD at "Covered"
    blocks += _addon_blocks(addons, n, terms, None if flb else total)
    return blocks, over, notes
