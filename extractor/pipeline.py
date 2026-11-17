"""End to end: slip + quote -> resolved envelope fields (+ add-on rows, warnings)."""
from __future__ import annotations

from . import sections as sections_mod
from .adapters import addons, headline, slip as slip_adapter
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
    rows, w = addons.read(quote_path, info.get("variant"))
    warnings += w
    resolved = resolve(fields)
    net = next((f.value for f in resolved if f.field == "premium.net" and isinstance(f.value, (int, float))), None)
    try:
        sec = sections_mod.read(quote_path, info.get("variant"), net)
        warnings += sec["warnings"]
    except Exception as e:
        sec = None
        warnings.append(f"sections could not be read: {type(e).__name__}: {e}")
    return {"fields": resolved, "addons": rows, "sections": sec, "slip": raw, "warnings": warnings, "variant": info.get("variant")}
