"""Backend test APIs: run the extractor and look at its results without the UI.

Upload a closing slip and a quote (multipart), or name a registered private case (extractor/cases.local.json) with ?case=<name>:

  POST /api/extract/all        everything below in one response
  POST /api/extract/fields     scalar fields with status, source and alternatives
  POST /api/extract/sections   13 sections, tie-out, conditions / deductibles
  POST /api/extract/addons     add-on rows (keep/drop/pending, clause, review reasons)
  POST /api/extract/case       the generated case JSON + schema errors
  POST /api/extract/render     the front-pack PDF (policy-system fields left blank)
  GET  /api/extract/registered names usable with ?case=

Nothing is stored. Uploads live in a temp folder for the request. Interactive docs: /docs.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from jsonschema import Draft202012Validator

from extractor import build_case, pipeline
from extractor.score import HERE, _abs, load_cases

router = APIRouter(prefix="/api/extract", tags=["extractor (backend testing)"])
ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "app" / "schema" / "policy.schema.json").read_text(encoding="utf-8"))
MAX_BYTES = 15 * 1024 * 1024


def _registered() -> dict:
    p = HERE / "cases.local.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _run(slip: UploadFile | None, quote: UploadFile | None, case: str | None):
    """-> pipeline result dict. Files win over ?case=."""
    if slip is not None and quote is not None:
        with tempfile.TemporaryDirectory(prefix="bpp_extract_", ignore_cleanup_errors=True) as tmp:
            paths = []
            for f, key in ((slip, "slip"), (quote, "quote")):
                if not (f.filename or "").lower().endswith((".xlsx", ".xlsm", ".xls")):
                    raise HTTPException(400, f"The {key} must be an Excel file (.xlsx or .xls).")
                data = f.file.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise HTTPException(413, "File too large (15 MB limit).")
                p = Path(tmp) / (key + Path(f.filename).suffix.lower())
                p.write_bytes(data)
                paths.append(str(p))
            return pipeline.run(paths[0], paths[1], None)
    if case:
        cfg = {**load_cases(), **_registered()}
        c = cfg.get(case)
        if not c:
            raise HTTPException(404, f"No registered case '{case}'. Known: {sorted(cfg)}")
        return pipeline.run(_abs(c["slip"]), _abs(c["quote"]), _abs(c.get("imd")))
    raise HTTPException(400, "Send both files (closing_slip, quote) or name a registered case with ?case=<name>.")


def _field(f) -> dict:
    return f.as_dict()


def _fields_part(res) -> dict:
    return {"fields": [_field(f) for f in res["fields"]], "variant": res["variant"],
            "counts": {"shown": sum(1 for f in res["fields"] if f.status in ("ok", "derived")), "flagged": sum(1 for f in res["fields"] if f.status not in ("ok", "derived"))}}


def _sections_part(res) -> dict:
    sec = res.get("sections")
    if not sec:
        return {"layout": None, "layoutInfo": None, "sections": [], "terms": None}
    t = sec["terms"]
    return {"layout": sec["layout"], "layoutInfo": sec.get("layout_info"), "tie": sec.get("tie"), "premiumSum": sec.get("premium_sum"), "net": sec.get("net"),
            "sections": [{"no": n, "label": s["label"], "sumInsured": s["sum_insured"], "premium": s["premium"], "status": s["status"], "note": s["note"], "subRows": s["sub_rows"]}
                         for n, s in sec["sections"].items() if s["sum_insured"] is not None or s["premium"] is not None],
            "terms": {"conditions": {f"S{k}": v for k, v in sorted(t["conditions"].items())}, "deductibles": {f"S{k}": v for k, v in sorted(t["deductibles"].items())},
                      "allSections": t["all"], "subGroups": {f"S{k}": v for k, v in t.get("sub_groups", {}).items()}}}


def _addons_part(res) -> dict:
    rows = res["addons"]
    by = lambda k: sum(1 for r in rows if r["decision"] == k)  # noqa: E731
    return {"counts": {"rows": len(rows), "keep": by("keep"), "drop": by("drop"), "pending": by("pending"),
                       "autoEligible": sum(1 for r in rows if r["auto_eligible"]),
                       "needsReview": sum(1 for r in rows if r["needs_review"] and r["decision"] != "drop")},
            "rows": rows}


def _case_part(res) -> dict:
    case, notes = build_case.assemble(res)
    errs = [f"{'/'.join(map(str, e.absolute_path))}: {e.message[:120]}" for e in Draft202012Validator(SCHEMA).iter_errors(case)]
    return {"case": case, "notes": notes, "schemaErrors": [e for e in errs if not e.startswith("system/")],
            "policySystemFieldsBlank": sum(1 for e in errs if e.startswith("system/"))}


@router.get("/registered")
def registered():
    return {"cases": sorted({**load_cases(), **_registered()})}


@router.post("/all")
def extract_all(closing_slip: UploadFile | None = File(None), quote: UploadFile | None = File(None), case: str | None = Query(None)):
    res = _run(closing_slip, quote, case)
    return {**_fields_part(res), "sections": _sections_part(res), "addons": _addons_part(res), "generated": _case_part(res), "warnings": res["warnings"]}


@router.post("/fields")
def extract_fields(closing_slip: UploadFile | None = File(None), quote: UploadFile | None = File(None), case: str | None = Query(None)):
    res = _run(closing_slip, quote, case)
    return {**_fields_part(res), "warnings": res["warnings"]}


@router.post("/sections")
def extract_sections(closing_slip: UploadFile | None = File(None), quote: UploadFile | None = File(None), case: str | None = Query(None)):
    res = _run(closing_slip, quote, case)
    return {**_sections_part(res), "warnings": res["warnings"]}


@router.post("/addons")
def extract_addons(closing_slip: UploadFile | None = File(None), quote: UploadFile | None = File(None), case: str | None = Query(None),
                   decision: str | None = Query(None, description="filter rows: keep | drop | pending")):
    res = _run(closing_slip, quote, case)
    part = _addons_part(res)
    if decision:
        part["rows"] = [r for r in part["rows"] if r["decision"] == decision]
    return {**part, "warnings": res["warnings"]}


@router.post("/case")
def extract_case(closing_slip: UploadFile | None = File(None), quote: UploadFile | None = File(None), case: str | None = Query(None)):
    res = _run(closing_slip, quote, case)
    return {**_case_part(res), "warnings": res["warnings"]}


@router.post("/render")
def extract_render(closing_slip: UploadFile | None = File(None), quote: UploadFile | None = File(None), case: str | None = Query(None)):
    import sys
    sys.path.insert(0, str(ROOT / "app"))
    import render
    res = _run(closing_slip, quote, case)
    d = build_case.assemble(res)[0]
    cid = d.get("case_id") or "case"
    with tempfile.TemporaryDirectory(prefix="bpp_extract_out_", ignore_cleanup_errors=True) as out:
        render.build_dict(cid, d, Path(out), True, validate=False)
        pdf = (Path(out) / f"{cid}_front.pdf").read_bytes()
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{cid}_front.pdf"', "Cache-Control": "no-store"})


# ---------------------------------------------------------------- layout profiles (learning where fields live)
layouts = APIRouter(prefix="/api/layouts", tags=["layout profiles (learning)"])


@layouts.get("")
def list_layouts():
    """Stored profiles: seed (committed, generic) and learned (private). No customer text: fingerprints are hashes."""
    from extractor.layouts import store
    return {"profiles": [{"id": p["id"], "source": p.get("source"), "dir": p["_dir"], "created": p.get("created"), "updated": p.get("updated"), "uses": p.get("uses", 0),
                          "lastOk": p.get("last_ok"), "recipes": [{k: v for k, v in r.items() if k != "sheet"} for r in p.get("recipes", [])],
                          "fingerprintSize": len(p.get("fingerprint", []))} for p in store.list_profiles()]}


@layouts.delete("/{pid}")
def delete_layout(pid: str):
    from extractor.layouts import store
    if not store.delete(pid):
        raise HTTPException(404, "No such learned profile (seed profiles are files in the repo).")
    return {"ok": True}


def _quote_sheets(quote: UploadFile):
    from extractor.legacy.grid import load
    with tempfile.TemporaryDirectory(prefix="bpp_layout_", ignore_cleanup_errors=True) as tmp:
        p = Path(tmp) / ("quote" + Path(quote.filename or "q.xlsx").suffix.lower())
        data = quote.file.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise HTTPException(413, "File too large (15 MB limit).")
        p.write_bytes(data)
        return str(p), load(str(p))


@layouts.post("/grid")
def grid(quote: UploadFile = File(...), sheet: str | None = Query(None), max_rows: int = Query(400)):
    """The quote as cells (sheet, ref, text/number) so a person or a UI can pick the cell that holds a field."""
    from extractor.layouts.common import ref
    _, sheets = _quote_sheets(quote)
    out = []
    for s in sheets:
        if sheet and s.name != sheet:
            continue
        rows = [{"row": rn, "cells": [{"ref": ref(c, rn), "value": (v if isinstance(v, (int, float)) else str(v)[:80])} for c, v in cs]} for rn, cs in s.rows[:max_rows]]
        out.append({"sheet": s.name, "hidden": not s.visible, "rows": rows})
    return {"sheets": out}


@layouts.post("/teach")
def teach(quote: UploadFile = File(...), mappings: str = Query(..., description='JSON list: [{"field":"premium.net","sheet":"Quote","cell":"C20","kind":"number"}]')):
    """Teach where fields live in this quote format. The location is stored by row label + column header, so the same format is read
    correctly next time even if rows shift. Returns what each mapping resolves to right now."""
    from extractor.layouts import store
    from extractor.layouts.common import h
    from extractor.layouts.engine import taught_overrides
    from extractor.layouts.fingerprint import fingerprint
    from extractor.layouts.recipes import teach_cell
    try:
        maps = json.loads(mappings)
        assert isinstance(maps, list) and maps
    except Exception:
        raise HTTPException(400, "mappings must be a JSON list of {field, sheet, cell, kind?}")
    _, sheets = _quote_sheets(quote)
    fp = sorted(fingerprint(sheets))
    pid = "p_" + h("|".join(fp))
    prof = next((p for p in store.list_profiles() if p["id"] == pid), None) or {"id": pid, "source": "taught", "fingerprint": fp, "recipes": [], "uses": 0}
    prof["source"] = "taught"
    for m in maps:
        try:
            rec = teach_cell(sheets, m["field"], m["sheet"], m["cell"], m.get("kind", "number"))
        except (KeyError, ValueError) as e:
            raise HTTPException(400, f"bad mapping {m}: {e}")
        prof["recipes"] = [r for r in prof["recipes"] if not (r["type"] == "cell" and r["target"] == rec["target"])] + [rec]
    saved = store.save({k: v for k, v in prof.items() if not k.startswith("_")})
    check = taught_overrides(sheets)
    return {"profile": saved["id"], "recipes": len([r for r in saved["recipes"] if r["type"] == "cell"]),
            "resolvesTo": {k: {"value": v["value"] if isinstance(v["value"], (int, float, str)) else str(v["value"]), "ref": v["ref"], "sheet": v["sheet"]} for k, v in check.items()}}
