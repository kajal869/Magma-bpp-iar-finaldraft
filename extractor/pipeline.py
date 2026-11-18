"""End to end: slip + quote -> resolved envelope fields (+ add-on rows, warnings)."""
from __future__ import annotations

from . import sections as sections_mod
from .adapters import addons, headline, quote_identity, slip as slip_adapter
from .resolver import resolve


def run(slip_path: str, quote_path: str, imd_path: str | None = None) -> dict:
    warnings: list[str] = []
    fields = []
    slip_total = None
    raw = {}
    try:
        sf, raw = slip_adapter.read(slip_path, imd_path)
        fields += sf
        slip_total = next((f.value for f in sf if f.field == "premium.final" and isinstance(f.value, (int, float))), None)
    except Exception as e:
        warnings.append(f"closing slip could not be read: {type(e).__name__}: {e}")
    try:
        hf, info = headline.read(quote_path, slip_total)
        fields += hf
        warnings += info["warnings"]
    except Exception as e:
        info = {}
        warnings.append(f"quote headline could not be read: {type(e).__name__}: {e}")
    cross = []
    try:   # the quote's own statement of insured name / address, compared with the slip (the slip value stays the printed one)
        slip_name = next((f.value for f in fields if f.field == "insured.name" and f.source.get("tool") == "slip"), None)
        qf, qw, cross = quote_identity.cross_check(quote_path, slip_name, raw.get("insured_address"))
        fields += qf
        warnings += qw
    except Exception as e:
        warnings.append(f"quote identity cross-check failed: {type(e).__name__}: {e}")
    rows, w = addons.read(quote_path, info.get("variant"))
    warnings += w
    resolved = resolve(fields)
    net = next((f.value for f in resolved if f.field == "premium.net" and isinstance(f.value, (int, float))), None)
    try:
        sec = sections_mod.read(quote_path, info.get("variant"), net, raw)
        warnings += sec["warnings"]
    except Exception as e:
        sec = None
        warnings.append(f"sections could not be read: {type(e).__name__}: {e}")
    resolved = _extras(_from_sections(resolved, sec, slip_total), sec)
    return {"fields": resolved, "addons": rows, "sections": sec, "slip": raw, "warnings": warnings, "variant": info.get("variant"), "cross_checks": cross}


def _extras(fields: list, sec: dict | None) -> list:
    """Single-source values read by label (terrorism premium, hypothecation) or taught by a person; they bypass the resolver."""
    from .envelope import Field
    if not sec:
        return fields
    out = list(fields)
    for name, sc in (sec.get("scalars") or {}).items():
        if name in ("premium.terrorism", "hypothecation") and not any(f.field == name for f in out):
            out.append(Field(name, sc["value"], "ok", {"tool": "quote", "sheet": sc["sheet"], "cell": sc["ref"], "method": "label"}))
    for target, t in (sec.get("taught") or {}).items():
        if target in ("premium.net", "premium.final", "premium.terrorism", "hypothecation", "business_activity"):
            out = [f for f in out if f.field != target]
            out.append(Field(target, t["value"], "derived", {"tool": "quote", "sheet": t["sheet"], "cell": t["ref"], "method": "taught"}, note="from a location you taught (profile " + t["profile"] + ")"))
    return out


def _from_sections(fields: list, sec: dict | None, slip_total: float | None) -> list:
    """When the headline reader could not settle a premium but a verified section table states it, use the table.
    Verified = the section premiums add up to the table's own net premium."""
    from .envelope import SHOWN, Field
    info = (sec or {}).get("layout_info") or {}
    if not sec or not info.get("verified") or sec.get("net") is None:
        return fields
    out = list(fields)
    get = lambda n: next((f for f in out if f.field == n), None)  # noqa: E731
    src = {"tool": "quote", "sheet": "", "cell": info.get("net_cell") or "", "method": "section table"}
    net = get("premium.net")
    if net is None or net.status not in SHOWN:
        out = [f for f in out if f.field != "premium.net"]
        out.append(Field("premium.net", sec["net"], "derived", src, note="net premium stated on the verified section table (section premiums add up to it)"))
    gross = sec.get("gross")
    fin = get("premium.final")
    if gross and abs(gross - sec["net"] * 1.18) <= 2 and fin is not None and fin.status not in SHOWN and slip_total is not None and abs(slip_total - sec["net"]) <= 1:
        out = [f for f in out if f.field != "premium.final"]
        out.append(Field("premium.final", gross, "derived", {**src, "method": "section table"},
                         note="the closing slip amount equals the quote's net premium (it excludes GST); total taken from the quote's premium incl. GST"))
    return out
