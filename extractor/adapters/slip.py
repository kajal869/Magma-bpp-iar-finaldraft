"""Closing-slip adapter: wraps the pilot label-anchored parser (extractor/slip) and emits envelope fields."""
from __future__ import annotations

from ..envelope import Field
from ..slip import closing_slip


def _src(method="label"):
    return {"tool": "slip", "sheet": "Closing Slip", "cell": None, "method": method}


def _opt(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def read(path: str, imd_path: str | None = None) -> tuple[list[Field], dict]:
    """-> (fields, raw parse). Raises on an unreadable workbook; the caller turns that into a warning."""
    raw = closing_slip.parse(path)
    out: list[Field] = []

    def put(name, value, status="ok", note="", method="label"):
        value = _opt(value) if isinstance(value, str) or value is None else value
        if value is None:
            out.append(Field(name, None, "not_found", _src(method), note=note or "label or value not found on the closing slip"))
        else:
            out.append(Field(name, value, status, _src(method), note=note))

    put("insured.name", raw.get("insured_name"))
    put("insured.gstin", raw.get("gst_no"))
    put("insured.address", raw.get("insured_address"))
    put("period.start", raw.get("policy_start"))
    put("period.end", raw.get("policy_end"))
    pn = _opt(raw.get("product_name"))
    if pn and "laghu" in pn.lower() and pn.lower().endswith("(commercial)"):
        # the slip prints "(Laghu Udyam) (Commercial)"; the product is Laghu Udyam, not the commercial BPP
        out.append(Field("product.name", pn[: pn.lower().rindex("(commercial)")].strip(), "derived", _src("rule"), note=f"slip prints '{pn}'"))
    else:
        put("product.name", pn)

    # intermediary: the code is reliable, the printed name is often abbreviated ("NE0 RISK"). Only an IMD master match makes it ok.
    code, raw_name = raw.get("intermediary_code"), raw.get("intermediary_name_raw")
    put("intermediary.code", code)
    rec = None
    if imd_path and (code or raw_name):
        try:
            from ..slip import imd
            hit = imd.lookup(imd_path, code=code, name=raw_name)
            if hit["status"] == "exact_code":
                rec = hit["record"]
        except Exception:
            rec = None
    if rec:
        out.append(Field("intermediary.name", rec["name"], "derived", {"tool": "imd", "sheet": "IMD master", "cell": None, "method": "code"},
                         note=f"name taken from the IMD master by code {code}; slip prints '{raw_name}'"))
    elif raw_name:
        out.append(Field("intermediary.name", raw_name, "check", _src("label"),
                         note="slip prints a short/abbreviated name; confirm the legal name from the IMD master"))
    else:
        put("intermediary.name", None)

    prem = raw.get("premium_100")
    try:
        prem = float(prem) if prem is not None else None
    except (TypeError, ValueError):
        prem = None
    put("premium.final", prem, note="slip total premium (100%), tie-out anchor")
    return out, raw
