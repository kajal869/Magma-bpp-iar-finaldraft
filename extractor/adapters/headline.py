"""Headline adapter: wraps the qg3 quote reader (extractor/headline/quote_grid.py, unmodified) and emits envelope fields.

Variant/scenario rule: when the quote has several policy variants (@A1/@A2/...), run each, and pick the one whose total
premium ties to the slip total premium (tolerance 1 rupee). No match or several matches -> conflict, user chooses.
"""
from __future__ import annotations

import os
import re
import tempfile

from ..envelope import Field
from ..headline import quote_grid as qg

TOL = 1.0
MAP = {"net_premium": "premium.net", "total_premium": "premium.final", "period_from": "period.start", "period_to": "period.end"}


def _xls_to_xlsx(path: str) -> str:
    """qg3 needs LibreOffice for .xls; convert values with xlrd instead (hidden sheets stay hidden)."""
    import openpyxl
    import xlrd
    wb = xlrd.open_workbook(path)
    out = openpyxl.Workbook()
    out.remove(out.active)
    try:
        for sh in wb.sheets():
            ws = out.create_sheet(sh.name[:31])
            for r in range(sh.nrows):
                for c in range(sh.ncols):
                    cell = sh.cell(r, c)
                    if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                        continue
                    v = cell.value
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        v = xlrd.xldate.xldate_as_datetime(v, wb.datemode)
                    ws.cell(row=r + 1, column=c + 1, value=v)
            if sh.visibility != 0:
                ws.sheet_state = "hidden"
    finally:
        wb.release_resources()
    d = tempfile.mkdtemp(prefix="bpp_xls_")
    p = os.path.join(d, os.path.splitext(os.path.basename(path))[0] + ".xlsx")
    out.save(p)
    return p


def _fields_from(rep: dict, extra_note: str = "", status_cap: str | None = None) -> list[Field]:
    out = []
    for qname, fname in MAP.items():
        e = rep["fields"].get(qname)
        if e is None:
            continue
        refs = [x for x in e.get("evidence", []) if x.get("ref")]
        ref = refs[0]["ref"] if refs else ""
        sheet, _, cell = ref.rpartition("!")
        src = {"tool": "quote", "sheet": sheet.strip("'"), "cell": cell, "method": "qg3"}
        status = e["status"]
        if status in ("hidden_only", "unverified"):
            status = "check"
        if status == "ok" and status_cap:
            status = status_cap
        note = "; ".join(x for x in (e.get("note", ""), extra_note) if x)
        alts = []
        if status == "conflict":
            seen = set()
            for ev in e.get("evidence", []):
                v = ev.get("value")
                if v is not None and (v, ev.get("ref")) not in seen:
                    seen.add((v, ev.get("ref")))
                    s, _, c = (ev.get("ref") or "").rpartition("!")
                    alts.append({"value": v, "source": {"tool": "quote", "sheet": s.strip("'"), "cell": c, "method": "qg3"}})
        out.append(Field(fname, e.get("value"), status, src, alts, note))
    return out


GST = 1.18
TIE_NET = 2.0     # net x 1.18 against a slip total that carries rounding


def _vals(e: dict) -> list[float]:
    """All numeric candidate values behind a qg3 field entry (the value itself, or the evidence of a conflict)."""
    out = [e["value"]] if isinstance(e.get("value"), (int, float)) else []
    out += [x["value"] for x in e.get("evidence", []) if isinstance(x.get("value"), (int, float))]
    return out


def _ties(rep: dict, slip_total: float) -> list[float]:
    """Net-premium candidates in this view whose total (stated, or net x 1.18) equals the slip total."""
    f = rep["fields"]
    if any(abs(t - slip_total) <= TOL for t in _vals(f.get("total_premium", {}))):
        nets = [n for n in _vals(f.get("net_premium", {})) if abs(n * GST - slip_total) <= TIE_NET] or _vals(f.get("net_premium", {}))
        return sorted(set(round(n, 2) for n in nets)) or [None]
    return sorted(set(round(n, 2) for n in _vals(f.get("net_premium", {})) if abs(n * GST - slip_total) <= TIE_NET))


def _apply_net_tie(fields: list[Field], rep: dict, slip_total: float | None) -> list[Field]:
    """A premium left in conflict (several scenarios / sheets) is resolved only if exactly one candidate ties to the slip total.
    Tie 1: net x 1.18 equals the slip total (the slip states the premium incl. GST).
    Tie 2: net equals the slip total (some slips state the net premium under a 'including GST' heading); the total is then the one candidate equal to net x 1.18.
    Both are recorded in the note, and the value is `derived`, never `ok`."""
    if slip_total is None:
        return fields
    by = {f.field: f for f in fields}
    net = by.get("premium.net")
    if net is not None and net.status == "conflict":
        nets = _vals(rep["fields"].get("net_premium", {}))
        hit = sorted({round(n, 2) for n in nets if abs(n * GST - slip_total) <= TIE_NET})
        how = "the only scenario whose net x 1.18 ties to the slip total premium"
        if len(hit) != 1:
            hit = sorted({round(n, 2) for n in nets if abs(n - slip_total) <= TOL})
            how = "the only net premium equal to the slip amount (the slip amount appears to exclude GST)"
        if len(hit) == 1:
            net.value, net.status = hit[0], "derived"
            net.note = (net.note + "; " if net.note else "") + how
    fin = by.get("premium.final")
    if fin is not None and fin.status == "conflict":
        totals = _vals(rep["fields"].get("total_premium", {}))
        hit = sorted({round(t, 2) for t in totals if abs(t - slip_total) <= TOL})
        how = "the only total in the quote that ties to the slip total premium"
        if len(hit) != 1 and net is not None and net.status == "derived" and isinstance(net.value, (int, float)):
            hit = sorted({round(t, 2) for t in totals if abs(t - net.value * GST) <= TIE_NET})
            how = "the only total in the quote equal to the chosen net premium x 1.18"
        if len(hit) == 1:
            fin.value, fin.status = hit[0], "derived"
            fin.note = (fin.note + "; " if fin.note else "") + how
    return fields


def _confirm_total(fields: list[Field], slip_total: float | None) -> list[Field]:
    """Quotes often do not state a clean total. If the quote's net premium x 1.18 equals the slip total, the quote supports that total."""
    if slip_total is None:
        return fields
    net = next((f for f in fields if f.field == "premium.net" and isinstance(f.value, (int, float))), None)
    fin = [f for f in fields if f.field == "premium.final"]
    if net is None or any(f.status in ("ok", "derived") and isinstance(f.value, (int, float)) for f in fin):
        return fields
    if abs(net.value * GST - slip_total) <= TIE_NET:
        fields = [f for f in fields if f.field != "premium.final"]
        fields.append(Field("premium.final", slip_total, "derived", {**net.source, "method": "net x 1.18"}, note="the quote's net premium x 1.18 equals the slip total premium"))
    return fields


def read(path: str, slip_total: float | None = None) -> tuple[list[Field], dict]:
    """-> (fields, info). info has warnings, variants, chosen variant."""
    info = {"warnings": [], "variants": [], "variant": None}
    src_path = _xls_to_xlsx(path) if path.lower().endswith(".xls") else path
    rep = qg.extract(src_path)
    info["variants"] = rep.get("variants", [])
    info["warnings"] += rep.get("warnings", [])
    if not rep.get("per_variant"):
        return _confirm_total(_apply_net_tie(_fields_from(rep), rep, slip_total), slip_total), info
    # variants: sheets sharing an "@A2"-style token belong to one policy variant (e.g. "RFQ VALMET @A2" + "VALMET @A2")
    groups: dict[str, list[str]] = {}
    for v in rep["variants"]:
        m = re.search(r"@\s*\w+", v)
        groups.setdefault(re.sub(r"\s+", "", m.group(0)) if m else v, []).append(v)
    if slip_total is None:
        info["warnings"].append("variants found but no slip total to choose between them")
        return _variant_conflict(rep["per_variant"]), info
    base = [s["name"] for s in rep["sheets"] if s["name"] not in rep["variants"]]
    grid, labels = qg.Grid(src_path), qg.Labels()
    views = {g: qg._extract_view(grid.view(base + sheets), labels) for g, sheets in groups.items()}  # one view per policy variant
    ties = {g: _ties(r, slip_total) for g, r in views.items()}
    live = [g for g, t in ties.items() if t]
    if len(live) == 1:
        g = live[0]
        info["variant"] = g
        info["warnings"] = [w for w in info["warnings"] if not w.startswith(("Policy variants found", "NO LABELLED VALUES"))]  # resolved by the tie-out
        info["warnings"].append(f"variant {g} chosen: its premium ties to the slip total premium")
        fs = _fields_from(views[g], extra_note=f"variant {g} chosen by slip total", status_cap="derived")
        return _confirm_total(_apply_net_tie(fs, views[g], slip_total), slip_total), info
    info["warnings"].append("no variant ties to the slip total" if not live else f"several variants tie to the slip total: {live}")
    return _variant_conflict(rep["per_variant"]), info


def _variant_conflict(pv: dict, rep: dict | None = None) -> list[Field]:
    out = []
    for qname, fname in MAP.items():
        alts = [{"value": r["fields"][qname]["value"], "source": {"tool": "quote", "sheet": v, "cell": "", "method": "qg3"}}
                for v, r in pv.items() if r["fields"].get(qname, {}).get("value") is not None]
        out.append(Field(fname, None, "conflict" if alts else "not_found", {"tool": "quote", "sheet": "", "cell": "", "method": "qg3"}, alts,
                         "policy variants disagree; choose the live variant"))
    return out
