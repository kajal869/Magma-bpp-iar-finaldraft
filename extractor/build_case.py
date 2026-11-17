"""Resolved extraction -> case JSON (app/schema/policy.schema.json).

assemble() builds the whole case: scalar fields, 13 schedule sections, terms, annexures. Unknown values are None / "" / [] with the
status kept in provenance; policy-system values (policy number, invoice, Magma GSTIN, stamp duty, servicing office) stay blank for the
user. House conventions (theme, wording book, footer text, labels) are copied from a template case and listed in provenance, never guessed.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from . import annexures as annex_mod
from . import sections as sec_mod
from .envelope import Field

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "app" / "cases"
PATHS = {"insured.address": "insured.address_lines"}


def _set(d: dict, path: str, v) -> None:
    parts = path.split(".")
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = v


def to_partial_case(fields: list[Field]) -> dict:
    """Scalar fields only (kept for the field scorer and the UI)."""
    case: dict = {}
    status: dict = {}
    for f in fields:
        v = f.value
        if f.field == "insured.address" and isinstance(v, str):
            v = [ln.strip() for ln in v.replace("\r", "").split("\n") if ln.strip()]
        _set(case, PATHS.get(f.field, f.field), v)
        status[f.field] = f.status
    case["_status"] = status
    return case


def template_for(layout: str | None) -> tuple[dict | None, str]:
    """House conventions come from a committed or local template case; the caller is told which one was used."""
    name = "demo_laghu" if layout == "laghu" else "mann"
    p = CASES / f"{name}.json"
    if not p.exists():
        p = CASES / "demo_laghu.json"
        name = "demo_laghu"
    return json.loads(p.read_text(encoding="utf-8")), name


def signature_available(theme: str) -> bool:
    """The signatory images are private (not in the repo). Drafts print the signature only when the files are present."""
    names = ["sig_laghu.png"] if theme == "laghu" else ["sig_ral.png", "sig_gst.png"]
    return all((ROOT / "app" / "assets" / n).exists() for n in names)


def _lines(v) -> list[str]:
    if isinstance(v, list):
        return v
    return [ln.strip() for ln in str(v or "").replace("\r", "").split("\n") if ln.strip()]


def assemble(res: dict) -> tuple[dict, list[str]]:
    """res = pipeline.run(...). -> (case dict, notes)."""
    notes: list[str] = []
    f = {x.field: x for x in res["fields"]}
    val = lambda k, default="": (f[k].value if k in f and f[k].value is not None else default)  # noqa: E731
    sec = res.get("sections") or {"sections": sec_mod._empty_sections(), "layout": None, "terms": {"conditions": {}, "deductibles": {}, "all": []},
                                    "items": [], "locations": [], "header": {}}
    slip = res.get("slip") or {}
    tpl, tname = template_for(sec["layout"])
    case = copy.deepcopy(tpl)
    notes.append(f"house conventions (presentation, options, wording book, footer) copied from template case '{tname}'; confirm for this insured")

    # policy-system values: blank, entered by the user
    case["system"].update(policy_no="", issue_date="", magma_gstin="", gst_invoice_no="", gst_invoice_date="", previous_gst_invoice_no=None,
                          place_of_supply={"state": "", "code": ""}, stamp_duty={"order_no": "", "order_date": ""}, signed_at="", signed_on="",
                          servicing_office={"code": "", "address_lines": []})
    case["case_id"] = re.sub(r"[^a-z0-9]+", "_", str(val("insured.name", "case")).lower()).strip("_")[:40] or "case"
    hdr = sec.get("header") or {}
    occ = slip.get("occupancy")
    case["insured"] = {"name": val("insured.name"), "gstin": val("insured.gstin"), "address_lines": _lines(val("insured.address", "")),
                       "address_lines_ral": _lines(val("insured.address", "")),
                       "business_activity": hdr.get("type of occupation") or hdr.get("business_description") or "", "occupancy": occ or hdr.get("occupancy") or ""}
    case["period"] = {"start": val("period.start"), "end": val("period.end"), "start_time": case["period"].get("start_time", "00:01")}
    code = val("intermediary.code")
    case["intermediary"] = {"name": val("intermediary.name"), "code": code, "mobile": "", "email": "",
                            "kind": "imd" if str(code).startswith("BRC") and "commercial" in str(val("product.name")).lower() else "agent_broker"}
    case["product"] = {**case["product"], "name": val("product.name", case["product"]["name"]), "title_upper": str(val("product.name", case["product"]["name"])).upper(),
                       "uin": slip.get("uin") or case["product"]["uin"], "code": int(slip["product_code"]) if str(slip.get("product_code") or "").isdigit() else case["product"]["code"]}

    net, final = val("premium.net", None), val("premium.final", None)
    gst = round((final - net), 2) if net is not None and final is not None else 0.0
    terr = val("premium.terrorism", None)
    terr = float(terr) if isinstance(terr, (int, float)) else 0
    case["premium"] = {"basic": (net - terr) if net is not None else 0, "terrorism": terr, "net": net if net is not None else 0,
                       "taxes": [{"type": "IGST", "rate": 0.18, "amount": gst}], "final": final if final is not None else 0}
    notes.append("tax split (IGST vs CGST+SGST) is not decided by the files; placeholder IGST 18%" + ("" if "premium.terrorism" in f else "; the terrorism part of the premium was not found (0)"))
    share = slip.get("our_share")
    case["coinsurance"] = ([{"insurer": c["name"], "share_pct": c["share"] * 100 if c["share"] <= 1 else c["share"]} for c in (slip.get("co_insurers") or [])]
                           or ([{"insurer": "Magma General Insurance Limited", "share_pct": share * 100 if share and share <= 1 else (share or 100)}]))
    fin = hdr.get("financial interest")
    hy = f["hypothecation"].value if "hypothecation" in f and f["hypothecation"].value else None
    case["hypothecation"] = list(hy) if isinstance(hy, list) else ([hy] if hy else ([fin] if fin else []))
    ba = (sec.get("scalars") or {}).get("business_activity", {}).get("value")
    if ba and not case["insured"]["business_activity"]:
        case["insured"]["business_activity"] = str(ba)

    rows = []
    for n in range(1, 14):
        s = sec["sections"][n]
        r = {"no": n, "label": s["label"], "sum_insured": s["sum_insured"], "premium": s["premium"]}
        if s["sub_rows"]:
            r["sub_rows"] = s["sub_rows"]
        rows.append(r)
    case["schedule"] = {"sections": rows}
    case["terms"] = sec_mod.term_groups(sec["terms"])
    annex, unbuilt = annexures_for(res, sec, case)
    case["annexures"] = annex
    notes += [f"not built: {u}" for u in unbuilt]
    case["options"]["show_signature"] = signature_available(case["presentation"]["theme"])
    if not case["options"]["show_signature"]:
        notes.append("signature images (app/assets/sig_*.png) are not installed; the draft prints no signature")
    case["options"]["wording_sections"] = [n for n in range(1, 14) if sec["sections"][n]["sum_insured"] or sec["sections"][n]["premium"]]
    tool = {"slip": "slip", "quote": "quote", "imd": "master"}
    case["provenance"] = {
        "sources": {"note": "Generated by the extractor from the closing slip and quote; review before use.",
                    "section_status": "; ".join(f"S{n}:{s['status']}" for n, s in sec["sections"].items() if s["status"] != "not_found"),
                    "review_notes": " | ".join(notes)},
        "field_sources": {k: ("derived" if x.status == "derived" else tool.get(x.source.get("tool"), "rule")) for k, x in f.items() if x.value not in (None, "")},
        "conflicts": [{"field": k, "note": x.note or "sources disagree"} for k, x in f.items() if x.status == "conflict"],
        "deviations_from_issued": []}
    return case, notes


def annexures_for(res: dict, sec: dict, case: dict):
    hdr = {"insured": case["insured"]["name"], "risk_location": (sec.get("header") or {}).get("risk location") or (sec.get("header") or {}).get("risk_location")
           or (res.get("slip") or {}).get("location_address") or "", "business_activity": case["insured"]["business_activity"], "occupancy": case["insured"]["occupancy"]}
    if sec["layout"] in ("blocks", "matrix") and len(sec.get("locations") or []) > 1:
        hdr["risk_location"], hdr["occupancy"] = "As per annexure below", "As per annexure below"
    return annex_mod.build(sec, res.get("addons") or [], hdr)
