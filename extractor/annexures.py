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


def addon_block(rows: list[dict], heading: str) -> dict:
    out = []
    for r in rows:
        out.append({"sr": int(r["serial"]) if r.get("serial") and str(r["serial"]).isdigit() else None,
                    "desc": r["clause"] or r["name"], "value": r["limit"] or None, "wording_id": r.get("wording_id")})
    return {"type": "addons", "heading": heading, "columns": ["Sr no", "Description", "Limit"], "rows": out}


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
            locs = sec["locations"]
            if n in (1, 3) and layout == "blocks" and locs:
                key = "fire_items" if n == 1 else "burglary_items"
                groups = []
                for l in locs:
                    items = l.get(key) or []
                    if items:
                        groups.append({"label": "Risk Location", "address": l.get("address") or "", "rows": _rows(items), "total": float(sum(i["si"] for i in items))})
                if groups:
                    blocks.append({"type": "si_groups", "heading": "Add on cover", "groups": groups, "grand_total": float(sum(g["total"] for g in groups))})
            elif n in (1, 3):
                unbuilt.append(f"annexure {n}: sum-insured breakup for the {layout} layout")
            else:
                unbuilt.append(f"annexure for section {n} ({layout} layout)")
            if n in (1, 3) and addons:
                blocks += section_addon_blocks(addons, n)
        if blocks:
            out.append({"no": len(out) + 1, "applies_to_section": n, "title": f"ANNEXURE {len(out) + 1} – APPLICABLE TO SECTION {n}", "header": _hdr(case_hdr), "blocks": blocks})
    return out, unbuilt
