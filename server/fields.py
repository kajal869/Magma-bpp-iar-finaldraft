"""Mandatory-field model for the review UI.

Each field maps a labelled input on screen to a place in the case JSON (dotted path). A field is
  ok       value read from the files and accepted by the extractor (status ok / derived)
  check    the extractor flagged it (conflict, failed check, abbreviated name ...); alternatives are offered, the user decides
  missing  empty. Fields that live in the policy system and not in the slip/quote (policy number, invoice number, ...)
           always start empty here; the demo sample (ACME only) can offer a value as a suggestion.
Required fields left empty can still be rendered, but only after the user acknowledges the blanks.
"""
import copy
import re
from typing import Any

GROUPS = ["Insured", "Policy period", "Intermediary", "Policy and invoice", "Premium", "Other"]

# key, label, group, path, kind, system_only, required, slip_key
F = [
    ("insured.name", "Insured name", "Insured", "insured.name", "text", False, True, "insured_name"),
    ("insured.gstin", "Insured GSTIN", "Insured", "insured.gstin", "text", False, True, "gst_no"),
    ("insured.address", "Insured address", "Insured", "insured.address_lines", "lines", False, True, "insured_address"),
    ("period.start", "Policy start date", "Policy period", "period.start", "date", False, True, "policy_start"),
    ("period.end", "Policy end date", "Policy period", "period.end", "date", False, True, "policy_end"),
    ("intermediary.name", "Broker / agent name", "Intermediary", "intermediary.name", "text", False, True, "intermediary_name"),
    ("intermediary.code", "Broker / agent code", "Intermediary", "intermediary.code", "text", False, True, "intermediary_code"),
    ("intermediary.mobile", "Broker mobile / phone", "Intermediary", "intermediary.mobile", "text", False, False, None),
    ("intermediary.email", "Broker email", "Intermediary", "intermediary.email", "text", False, False, None),
    ("system.policy_no", "Policy number", "Policy and invoice", "system.policy_no", "text", True, True, None),
    ("system.issue_date", "Issue date", "Policy and invoice", "system.issue_date", "date", True, True, None),
    ("system.servicing_office", "Policy servicing office", "Policy and invoice", "system.servicing_office.address_lines", "lines", True, True, None),
    ("system.magma_gstin", "Magma GSTIN", "Policy and invoice", "system.magma_gstin", "text", True, True, None),
    ("system.gst_invoice_no", "GST invoice number", "Policy and invoice", "system.gst_invoice_no", "text", True, True, None),
    ("system.gst_invoice_date", "GST invoice date", "Policy and invoice", "system.gst_invoice_date", "date", True, True, None),
    ("system.place_of_supply.state", "Place of supply (state)", "Policy and invoice", "system.place_of_supply.state", "text", True, True, None),
    ("system.place_of_supply.code", "Place of supply (code)", "Policy and invoice", "system.place_of_supply.code", "text", True, True, None),
    ("system.stamp_duty.order_no", "Stamp duty order no.", "Policy and invoice", "system.stamp_duty.order_no", "text", True, True, None),
    ("system.stamp_duty.order_date", "Stamp duty order date", "Policy and invoice", "system.stamp_duty.order_date", "date", True, True, None),
    ("system.sac_code", "SAC code", "Policy and invoice", "system.sac_code", "text", False, True, None),
    ("premium.basic", "Basic premium (INR)", "Premium", "premium.basic", "money", False, True, None),
    ("premium.net", "Net premium (INR)", "Premium", "premium.net", "money", False, True, None),
    ("premium.final", "Final premium incl. tax (INR)", "Premium", "premium.final", "money", False, True, "premium"),
    ("hypothecation", "Hypothecation (financier)", "Other", "hypothecation", "lines", False, True, None),
]
BY_KEY = {f[0]: f for f in F}
# UI key -> extractor envelope field
ENV = {"insured.name": "insured.name", "insured.gstin": "insured.gstin", "insured.address": "insured.address", "period.start": "period.start",
       "period.end": "period.end", "intermediary.name": "intermediary.name", "intermediary.code": "intermediary.code",
       "premium.net": "premium.net", "premium.final": "premium.final"}
TOOL = {"slip": "Closing slip", "quote": "Quote", "imd": "IMD master"}


def _get(d: dict, path: str) -> Any:
    cur: Any = d
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def _set(d: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    cur = d
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def _norm(s: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def to_text(kind: str, v: Any) -> str:
    if v is None:
        return ""
    if kind == "lines":
        return "\n".join(v) if isinstance(v, list) else str(v)
    if kind == "money":
        if isinstance(v, (int, float)):
            return str(int(v)) if float(v).is_integer() else f"{v:.2f}"
        return str(v)
    return str(v)


def from_text(kind: str, raw: str) -> Any:
    raw = (raw or "").strip()
    if kind == "lines":
        return [ln.strip() for ln in raw.replace("\r", "").split("\n") if ln.strip()]
    if kind == "money":
        if not raw:
            return None
        try:
            return float(raw.replace(",", ""))
        except ValueError:
            return None
    return raw


def _alt_text(kind: str, v: Any) -> str:
    return to_text(kind, v)


def effective_case(base: dict, values: dict[str, str] | None) -> dict:
    """base = the case generated by the extractor. Policy-system fields stay blank unless the user supplied a value."""
    d = copy.deepcopy(base)
    values = values or {}
    for key, label, group, path, kind, system_only, required, slip_key in F:
        if key in values:
            v = from_text(kind, values[key])
            _set(d, path, v)
            if key == "insured.address":
                d["insured"]["address_lines_ral"] = v
        elif system_only:
            _set(d, path, [] if kind == "lines" else (None if kind == "money" else ""))
    return d


def build_fields(case: dict, env: dict, suggest: dict | None = None, values: dict[str, str] | None = None) -> list[dict]:
    """case: generated case JSON. env: {extractor field name: Field}. suggest: optional sample case offering values for policy-system fields."""
    eff = effective_case(case, values)
    out = []
    for key, label, group, path, kind, system_only, required, _ in F:
        value = to_text(kind, _get(eff, path))
        suggestion = to_text(kind, _get(suggest, path)) if (suggest and system_only) else None
        ef = env.get(ENV.get(key, ""))
        status, source, note, alts = "ok", "Quote / closing slip", None, []
        if key in (values or {}):
            source = "Entered by you"
            status = "ok" if value.strip() else "missing"
        elif ef is not None:
            tool = TOOL.get((ef.source or {}).get("tool"), "Extractor")
            source = tool + (f" ({ef.source['sheet']}{'!' + ef.source['cell'] if ef.source.get('cell') else ''})" if ef.source.get("sheet") and ef.source.get("tool") == "quote" else "")
            if ef.status in ("ok", "derived"):
                note = ef.note or None
                if ef.status == "derived":
                    source += " - derived"
            elif ef.status in ("not_found", "not_stated"):
                status, source = "missing", "Not found in the files"
                note = ef.note or None
            else:
                status = "check"
                alts = [{"value": _alt_text(kind, a["value"]), "label": TOOL.get((a.get("source") or {}).get("tool"), "?")
                         + (f" ({a['source']['sheet']})" if (a.get("source") or {}).get("sheet") else "")} for a in ef.alternatives]
                note = ef.note or "The extractor could not settle this value"
        elif key in ("intermediary.mobile", "intermediary.email"):
            if value.strip():
                source, note = "IMD master (by broker code)", None
            else:
                status, source, note = "missing", "Not in the IMD master", "The broker's contact is taken from the IMD master; no record or no value for this broker."
        elif key == "premium.basic":
            terr, opted = env.get("premium.terrorism"), env.get("terrorism.opted")
            if terr is not None and terr.value not in (None, "") and terr.status in ("ok", "derived"):
                source = "Net premium less the terrorism premium"
            elif opted is not None and opted.value == "No":
                source = "Net premium (terrorism not opted on the slip)"
            elif opted is not None and opted.value == "Yes":
                status, source, note = "check", "Net premium (derived)", "Terrorism is opted on the slip but its premium was not found on the quote; basic = net, terrorism = 0"
            else:
                status, source, note = "check", "Net premium (derived)", "The slip does not say whether terrorism is opted; basic = net, terrorism = 0"
        elif key == "hypothecation":
            if not value.strip():
                status, source = "missing", "No financial interest on the quote"
            else:
                source = "Quote (financial interest)"
        elif key == "system.sac_code":
            source = "Product rule (template)"
        elif system_only or not value.strip():
            status, source = "missing", ("Not in the uploaded files" if system_only else "Not found")
            if key == "system.policy_no":
                exp = env.get("policy.expiring_no")
                note = (f"This is a renewal of {exp.value}. The new policy number is issued by the policy system and is not in the files." if exp and exp.value
                        else "The new policy number is issued by the policy system and is not in the files.")
        if status != "missing" and not value.strip():
            status, source = "missing", "Not found in the files"
        out.append({"key": key, "label": label, "group": group, "kind": kind, "value": value, "status": status, "source": source, "note": note,
                    "alternatives": alts, "suggestion": suggestion if (suggestion and status == "missing") else None, "required": required})
    return out


def blanks(fields: list[dict]) -> list[dict]:
    return [f for f in fields if f["required"] and f["status"] == "missing"]
