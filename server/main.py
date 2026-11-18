"""Local server: two uploads in, front-pack PDF out. No database, nothing kept on disk.

Run (from the repo root):  python -m uvicorn --app-dir server main:app --port 8000
Uploads live in a per-request temp folder that is deleted when the request ends. Generated PDFs are held in memory
for 15 minutes (or until the browser asks to discard them).

Data path: both workbooks go through the extractor package (extractor/pipeline.py): closing slip fields, quote headline with
variant selection, add-on rows matched to the clause library, sections, terms and annexures. The result is a case JSON that
app/render.py renders. The user reviews fields, add-ons, sections and terms and may edit them before the PDF is built.
The ACME demo case, when it matches, only supplies suggestions for policy-system fields (policy number, invoice, ...).
"""
import copy
import json
import os
import re
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent          # bpp_plan
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import render  # noqa: E402  (app/render.py)
import fields as fields_mod  # noqa: E402  (server/fields.py)

from extractor import annexures as annex_mod  # noqa: E402
from extractor import build_case, pipeline  # noqa: E402
from extractor import sections as sec_mod  # noqa: E402
from extractor.clausebank import api as clause_api  # noqa: E402
from extractor.clausebank.common import fullkey  # noqa: E402,F401

CASES = ROOT / "app" / "cases"
TTL = 15 * 60
MAX_BYTES = 15 * 1024 * 1024
RENDER_LOCK = threading.Lock()
STORE: dict[str, dict] = {}
SESSIONS: dict[str, dict] = {}

app = FastAPI(title="Magma BPP front-pack demo")
from api_extract import layouts as layouts_router  # noqa: E402
from api_extract import router as extract_router  # noqa: E402
app.include_router(extract_router)
app.include_router(layouts_router)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------- helpers
def norm_name(s: str) -> str:
    s = re.sub(r"[^A-Z0-9 ]", "", (s or "").upper())
    s = re.sub(r"\b(PRIVATE|PVT|LIMITED|LTD|LLP|THE)\b", " ", s)
    return re.sub(r"\s+", "", s)


def quote_text(path: Path, name: str) -> str:
    """First ~40 rows of every sheet as one string, to cross-check that the quote belongs to the same insured."""
    out = []
    if name.lower().endswith(".xls"):
        import xlrd
        wb = xlrd.open_workbook(str(path))
        try:
            for sh in wb.sheets():
                for r in range(min(sh.nrows, 40)):
                    out += [str(v) for v in sh.row_values(r) if isinstance(v, str)]
        finally:
            wb.release_resources()
    else:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            for sh in wb.worksheets:
                for i, row in enumerate(sh.iter_rows(values_only=True)):
                    if i > 40:
                        break
                    out += [str(v) for v in row if isinstance(v, str)]
        finally:
            wb.close()
    return " ".join(out)


def match_case(slip: dict):
    n_up = norm_name(slip.get("insured_name") or "")
    best = (0, None)
    for f in sorted(CASES.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        cn = norm_name(d["insured"]["name"])
        score = 0
        if n_up and cn and (n_up == cn or (len(min(n_up, cn, key=len)) >= 6 and (n_up in cn or cn in n_up))):
            score += 2
        if slip.get("gst_no") and slip["gst_no"] == d["insured"]["gstin"]:
            score += 1
        if slip.get("policy_start") and str(slip["policy_start"])[:10] == d["period"]["start"]:
            score += 1
        if score > best[0]:
            best = (score, f.stem)
    return best[1] if best[0] >= 2 else None


def money(v):
    return f"{v:,.0f}"


def sweep():
    now = time.time()
    for store in (STORE, SESSIONS):
        for k in [k for k, v in store.items() if v["exp"] < now]:
            store.pop(k, None)


# ---------------------------------------------------------------- API
def _default_imd() -> str | None:
    """IMD master (.xlsb) for broker legal names and contacts: BPP_IMD_PATH, else a 'Non Motor IMD Contact details*.xlsb' in the project folder."""
    if os.environ.get("BPP_IMD_PATH"):
        return os.environ["BPP_IMD_PATH"]
    hits = sorted(p for p in Path(__file__).resolve().parents[1].glob("Non Motor IMD Contact details*.xlsb") if not p.name.startswith("~$"))
    return str(hits[0]) if hits else None


IMD_PATH = _default_imd()


class AddonEdit(BaseModel):
    id: int | None = None            # index of the extracted row; None = a row added by the user
    include: bool = True
    clause: str | None = None        # library clause title; None with printAsQuoted = print the quote's own wording
    name: str = ""
    limit: str | None = None
    printAsQuoted: bool = False


class SectionEdit(BaseModel):
    no: int
    sumInsured: float | None = None
    premium: float | None = None


class TermGroup(BaseModel):
    key: str
    title: str
    lines: list[str] = []


class TermsEdit(BaseModel):
    sectionConditions: list[TermGroup] = []
    deductibles: list[TermGroup] = []
    allLines: list[str] = []


class RenderRequest(BaseModel):
    sessionId: str
    values: dict[str, str] = {}
    allowBlanks: bool = False
    addons: list[AddonEdit] | None = None
    sections: list[SectionEdit] | None = None
    terms: TermsEdit | None = None


def _blank_payload(bl):
    return [{"key": f["key"], "label": f["label"], "group": f["group"]} for f in bl]


def _env(res) -> dict:
    return {f.field: f for f in res["fields"]}


def _summary(res) -> dict:
    e = _env(res)
    v = lambda k: (e[k].value if k in e and e[k].value is not None else None)  # noqa: E731
    return {"insured": v("insured.name"), "gstin": v("insured.gstin"), "address": str(v("insured.address") or "").replace("\n", " ").strip(),
            "periodStart": str(v("period.start") or "")[:10], "periodEnd": str(v("period.end") or "")[:10], "product": v("product.name"),
            "intermediary": v("intermediary.name"), "office": (res.get("slip") or {}).get("office")}


def _addon_payload(rows: list[dict]) -> list[dict]:
    """Add-on covers for the review table. Plain condition/warranty lines (no insurer remark, e.g. Laghu quotes) are not covers: they are
    already in the conditions block, so they are left out here instead of showing up as an alarming wall of 'dropped' rows."""
    out = []
    for i, r in enumerate(rows):
        if r.get("row_type") == "condition_line":
            continue
        if r["decision"] == "drop":
            status = "dropped"
        elif r["auto_eligible"]:
            status = "ok"
        elif r["decision"] == "keep" and not r["clause"]:
            status = "missing"
        else:
            status = "check"
        out.append({"id": i, "sheet": r["sheet"], "row": r["row"], "serial": r.get("serial"), "name": r["name"], "limit": r.get("limit") or "", "remark": r.get("remark") or "",
                    "decision": r["decision"], "decisionClass": r["decision_class"], "include": r["decision"] == "keep", "clause": r["clause"], "wordingId": r.get("wording_id"),
                    "method": r["method"], "confidence": r["confidence"], "status": status, "needsReview": r["needs_review"], "nearIdentical": r["near_identical"],
                    "candidates": [c[1] for c in (r.get("candidates") or []) if c[0] >= 0.5][:3], "printAsQuoted": False})
    return out


def _sections_payload(sec) -> list[dict]:
    if not sec:
        return []
    return [{"no": n, "label": s["label"], "sumInsured": s["sum_insured"], "premium": s["premium"], "status": s["status"], "note": s["note"],
             "opted": bool(s["sum_insured"] or s["premium"]), "subRows": s["sub_rows"]} for n, s in sec["sections"].items()]


def _terms_payload(case) -> dict:
    t = case["terms"]
    grp = lambda g: [{"key": x.get("key", ""), "title": x["title"], "lines": x.get("lines", [])} for x in g]  # noqa: E731
    return {"sectionConditions": grp(t["section_conditions"]), "deductibles": grp(t["deductibles"]), "allLines": t["all_sections_conditions"].get("lines", [])}


def _wording_ids() -> dict:
    try:
        return clause_api.wording_ids()
    except Exception:
        return {}


@app.get("/api/clauses")
def clauses():
    """Clause titles for the add-on dropdown (wording library when present, else the clause bank's library)."""
    try:
        idx = clause_api.load_library()
        return {"clauses": sorted(idx.titles)}
    except Exception:
        return {"clauses": []}


@app.post("/api/analyze")
def analyze(closing_slip: UploadFile = File(...), quote: UploadFile = File(...)):
    """Step 1: read both files; return fields, add-ons, sections and terms with a status each."""
    sweep()
    for f, label in ((closing_slip, "closing slip"), (quote, "quote")):
        if not (f.filename or "").lower().endswith((".xlsx", ".xlsm", ".xls")):
            raise HTTPException(400, f"The {label} must be an Excel file (.xlsx or .xls).")
    with tempfile.TemporaryDirectory(prefix="bpp_demo_", ignore_cleanup_errors=True) as tmp:
        tmp = Path(tmp)
        paths = {}
        for f, key in ((closing_slip, "slip"), (quote, "quote")):
            data = f.file.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise HTTPException(413, "File too large (15 MB limit).")
            p = tmp / (key + Path(f.filename).suffix.lower())
            p.write_bytes(data)
            paths[key] = p
        res = pipeline.run(str(paths["slip"]), str(paths["quote"]), IMD_PATH)
        summary = _summary(res)
        if not summary["insured"]:
            return JSONResponse(status_code=422, content={"error": "unsupported", "summary": summary,
                                "message": "Could not read the insured from the closing slip. Is it the Magma closing-slip workbook (sheet 'Closing Slip')?"})
        warnings = [w for w in res["warnings"] if not w.startswith("app/wording")]
        try:
            qtxt = norm_name(quote_text(paths["quote"], quote.filename))
            if norm_name(summary["insured"])[:8] not in qtxt:
                warnings.append("The quote does not seem to mention the same insured as the closing slip. Check that both files belong to the same case.")
        except Exception:
            warnings.append("The quote workbook could not be scanned for the insured's name.")
    case, notes = build_case.assemble(res)
    sample = match_case({"insured_name": summary["insured"], "gst_no": summary["gstin"], "policy_start": summary["periodStart"]})
    suggest = json.loads((CASES / f"{sample}.json").read_text(encoding="utf-8")) if sample else None
    sid = uuid.uuid4().hex
    SESSIONS[sid] = {"res": res, "case": case, "suggest": suggest, "exp": time.time() + TTL}
    fields = fields_mod.build_fields(case, _env(res), suggest)
    addons = _addon_payload(res["addons"])
    n_cond = sum(1 for r in res["addons"] if r.get("row_type") == "condition_line")
    if n_cond:
        notes.append(f"{n_cond} condition / warranty lines in the quote have no insurer remark, so they are treated as conditions (see Conditions below), not add-on covers.")
    return {"sessionId": sid, "summary": summary, "fields": fields, "groups": fields_mod.GROUPS, "warnings": warnings, "layout": (res.get("sections") or {}).get("layout"),
            "addons": addons, "sections": _sections_payload(res.get("sections")), "terms": _terms_payload(case),
            "notes": notes + ["Policy-system values (policy number, invoice number, Magma GSTIN, ...) are not in the two files, so they start empty."]
                     + (["The ACME demo sample is offering values for those policy-system fields."] if suggest else [])}


def _apply_edits(sess: dict, req: RenderRequest):
    """-> (case dict with the user's edits, extra blank entries). Does not touch the session."""
    res, base = sess["res"], sess["case"]
    case = fields_mod.effective_case(base, req.values)
    extra_blank = []
    sec = copy.deepcopy(res.get("sections"))
    if req.sections is not None and sec:
        for e in req.sections:
            row = sec["sections"].get(e.no)
            if row is not None:
                row["sum_insured"], row["premium"] = e.sumInsured, e.premium
        case["schedule"]["sections"] = [{**r, "sum_insured": sec["sections"][r["no"]]["sum_insured"], "premium": sec["sections"][r["no"]]["premium"]} for r in case["schedule"]["sections"]]
        case["options"]["wording_sections"] = [n for n, s in sec["sections"].items() if s["sum_insured"] or s["premium"]]
    if req.terms is not None:
        case["terms"] = {"section_conditions": [g.model_dump() for g in req.terms.sectionConditions if g.lines or g.title],
                         "deductibles": [g.model_dump() for g in req.terms.deductibles if g.lines or g.title],
                         "all_sections_conditions": {**case["terms"]["all_sections_conditions"], "lines": [x for x in req.terms.allLines if x.strip()]}}
    rows = res["addons"]
    if req.addons is not None:
        ids = _wording_ids()
        rows = []
        for e in req.addons:
            src = dict(res["addons"][e.id]) if e.id is not None and 0 <= e.id < len(res["addons"]) else {"sheet": "Added by you", "row": 0, "serial": None, "remark": ""}
            clause = None if e.printAsQuoted else (e.clause or None)
            src.update(decision="keep" if e.include else "drop", clause=clause, name=e.name or src.get("name", ""), limit=e.limit or "",
                       wording_id=ids.get(fullkey(clause)) if clause else None)
            rows.append(src)
            if e.include and not clause and not e.printAsQuoted:
                extra_blank.append({"key": f"addon:{e.id if e.id is not None else 'new'}", "label": f"Add-on cover: {e.name or src.get('name', '')}".strip(), "group": "Add-on covers"})
    if sec:
        case["annexures"], _ = build_case.annexures_for({"addons": rows, "slip": res.get("slip")}, sec, case)
    return case, extra_blank


@app.post("/api/render")
def render_draft(req: RenderRequest):
    """Step 2: apply the user's values and edits and render the front pack. Blanks need an explicit acknowledgement."""
    sweep()
    sess = SESSIONS.get(req.sessionId)
    if not sess:
        raise HTTPException(404, "This session has expired. Please upload the files again.")
    fields = fields_mod.build_fields(sess["case"], _env(sess["res"]), sess["suggest"], req.values)
    d, extra = _apply_edits(sess, req)
    bl = fields_mod.blanks(fields) + extra
    if bl and not req.allowBlanks:
        return JSONResponse(status_code=409, content={"error": "blanks", "blanks": _blank_payload(bl),
                            "message": "Some mandatory fields are empty. Confirm to download with these places left blank."})
    case = d.get("case_id") or "case"
    with RENDER_LOCK, tempfile.TemporaryDirectory(prefix="bpp_out_", ignore_cleanup_errors=True) as out:
        render.build_dict(case, d, Path(out), True, validate=False)
        pdf = (Path(out) / f"{case}_front.pdf").read_bytes()
    import fitz
    pages = len(fitz.open(stream=pdf, filetype="pdf"))
    token = uuid.uuid4().hex
    pol = (d["system"]["policy_no"] or "no-policy-no").replace("/", "-")
    fname = f"Front pack - {d['insured']['name'].title()} - {pol}.pdf"
    STORE[token] = {"pdf": pdf, "name": fname, "exp": time.time() + TTL}
    return {"token": token, "case": case, "fileName": fname, "pages": pages, "blanks": _blank_payload(bl),
            "draft": {"insured": d["insured"]["name"], "policyNo": d["system"]["policy_no"] or "-", "product": d["product"]["name"],
                      "period": f"{render.dmy(d['period']['start'])} to {render.dmy(d['period']['end'])}",
                      "netPremium": money(d["premium"]["net"] or 0), "finalPremium": money(d["premium"]["final"] or 0),
                      "tax": "+".join(t["type"] for t in d["premium"]["taxes"]),
                      "sections": [x["label"] for x in d["schedule"]["sections"] if x["sum_insured"]]},
            "notes": ["Front pack only: schedule, premium summary, GST block and annexures. The policy wording book is not included."]}


@app.get("/api/pdf/{token}")
def get_pdf(token: str, download: int = 0):
    sweep()
    item = STORE.get(token)
    if not item:
        raise HTTPException(404, "This draft has expired. Please generate it again.")
    disp = "attachment" if download else "inline"
    return Response(item["pdf"], media_type="application/pdf", headers={"Content-Disposition": f'{disp}; filename="{item["name"]}"', "Cache-Control": "no-store"})


@app.get("/api/page/{token}/{n}")
def get_page(token: str, n: int):
    """One page of the draft as a PNG, so the preview works in any browser without a PDF plugin."""
    import fitz
    item = STORE.get(token)
    if not item:
        raise HTTPException(404, "This draft has expired. Please generate it again.")
    doc = fitz.open(stream=item["pdf"], filetype="pdf")
    if not 1 <= n <= len(doc):
        raise HTTPException(404, "No such page.")
    png = doc[n - 1].get_pixmap(dpi=110, alpha=False).tobytes("png")
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.delete("/api/pdf/{token}")
def drop_pdf(token: str):
    STORE.pop(token, None)
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True, "extractor": True, "cases": sorted(p.stem for p in CASES.glob("*.json"))}


DIST = ROOT / "web" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="web")
