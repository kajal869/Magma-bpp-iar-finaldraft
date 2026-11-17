"""Run-time add-on matching: quote workbook -> add-on rows in the common row format (handover 4.2). No issued policy needed.

  rows  = extract_rows(path, variant="@A2")          # quote_rows.extract + remarks.classify, scoped to the live variant
  addons = match_rows(rows)                          # resolve to library clauses (exact -> alias -> remark -> fuzzy), flag for review

Rules kept from the clause bank: fuzzy matches are never auto-accepted; only human-approved aliases count; titles that share a
normalised key (near-identical) are never auto-accepted; a miss stays a miss.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import quote_rows
from .common import AUTO_ACCEPT, fullkey, norm
from .match import sim
from .resolve import Index, confidence, resolve_clause

NEAR_IDENTICAL = 0.9    # library titles this similar are never told apart automatically (the clause bank's 3 known wrong pairs)

DATA = Path(__file__).resolve().parent / "data"
ROOT = Path(__file__).resolve().parents[2]
WORDING = ROOT / "app" / "wording" / "clauses.json"          # 150 clauses with ids (private; not in this repo yet)
_VARIANT = re.compile(r"@\s*\w+")

_cache: dict = {}


def load_library(path: Path | None = None) -> Index:
    p = Path(path or DATA / "library.json")
    key = ("lib", str(p))
    if key not in _cache:
        _cache[key] = Index(json.loads(p.read_text(encoding="utf-8")))
    return _cache[key]


def load_aliases(path: Path | None = None) -> dict:
    """Approved aliases only: {normalised phrase: [clause titles]}."""
    p = Path(path or DATA / "dictionary.json")
    key = ("dict", str(p))
    if key not in _cache:
        out: dict = {}
        if p.exists():
            for a in json.loads(p.read_text(encoding="utf-8")).get("aliases", []):
                if a.get("status") == "approved":
                    lst = out.setdefault(a["phrase"], [])
                    if a["clause"] not in lst:
                        lst.append(a["clause"])
        _cache[key] = out
    return _cache[key]


def wording_ids(path: Path | None = None) -> dict:
    """{fullkey(title): wording id} from app/wording/clauses.json when present; otherwise empty (ids are never invented)."""
    p = Path(path or WORDING)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    items = data.get("clauses", data) if isinstance(data, dict) else data
    out = {}
    for it in items if isinstance(items, list) else []:
        t, i = it.get("title") or it.get("name"), it.get("id") or it.get("wording_id")
        if t and i:
            out[fullkey(t)] = i
    return out


def near_titles(idx: Index, clause: str) -> list[str]:
    """Other library titles that share the loose key, or are >= NEAR_IDENTICAL similar. Cached per clause."""
    key = ("near", id(idx), clause)
    if key not in _cache:
        loose = {c["title"] for c in idx.by_nkey.get(norm(clause), [])}
        sims = {t for t in idx.titles if sim(clause, t) >= NEAR_IDENTICAL}
        _cache[key] = sorted((loose | sims) - {clause})
    return _cache[key]


def variant_token(sheet: str):
    m = _VARIANT.search(sheet or "")
    return re.sub(r"\s+", "", m.group(0)) if m else None


def extract_rows(path: str, variant: str | None = None) -> tuple[list[dict], list[str]]:
    """Quote rows (all sheets). With a chosen variant, sheets of the other variants are dropped; with variants present but none
    chosen, every row is kept and tagged so it goes to review."""
    rows = quote_rows.extract("run", path)
    warnings = []
    tokens = {variant_token(r["sheet"]) for r in rows} - {None}
    for r in rows:
        r["variant_unchosen"] = False
    if tokens:
        if variant:
            rows = [r for r in rows if variant_token(r["sheet"]) in (None, variant)]
        else:
            warnings.append(f"quote has policy variants ({', '.join(sorted(tokens))}) and none was chosen; add-ons from all variants are listed")
            for r in rows:
                r["variant_unchosen"] = variant_token(r["sheet"]) is not None
    return rows, warnings


def match_rows(rows: list[dict], idx: Index | None = None, aliases: dict | None = None, ids: dict | None = None) -> list[dict]:
    idx = idx or load_library()
    aliases = load_aliases() if aliases is None else aliases
    ids = wording_ids() if ids is None else ids
    out = []
    for q in rows:
        review = []
        res = {"clause": None, "method": None, "score": 0.0, "ambiguous": [], "candidates": []}
        near = []
        if q["decision"] != "drop":
            res = resolve_clause(q["name"], idx, aliases, q.get("cited"))
        if res["clause"]:
            near = near_titles(idx, res["clause"])
        conf = confidence(res["method"], res["score"]) if res["clause"] else 0.0
        if q["decision"] == "pending":
            review.append("pending_remark" if q["row_type"] == "addon_row" else "no_remark_to_classify")
        if q["decision"] == "keep" and not res["clause"]:
            review.append("no_library_clause")
        if res["method"] == "fuzzy":
            review.append("fuzzy_match")
        if res["ambiguous"]:
            review.append("ambiguous_title")
        if near:
            review.append("near_identical_title")
        if q.get("conditional") and q["decision"] == "keep":
            review.append("conditional_cover")
        if q.get("variant_unchosen"):
            review.append("variant_not_chosen")
        auto = (q["decision"] == "keep" and bool(res["clause"]) and conf >= AUTO_ACCEPT and res["method"] in ("exact", "alias", "remark")
                and not res["ambiguous"] and not near and not q.get("variant_unchosen"))
        if q["decision"] == "keep" and not auto and not review:
            review.append("low_confidence")
        out.append({
            "sheet": q["sheet"], "row": q["row"], "serial": q.get("serial"), "name": q["name"], "limit": q.get("limit", ""), "remark": q.get("remark", ""),
            "decision": q["decision"], "decision_class": q["cls"], "row_type": q.get("row_type", "addon_row"), "section": q.get("section", 1), "cited": q.get("cited"), "hidden_sheet": bool(q.get("hidden")),
            "clause": res["clause"], "wording_id": ids.get(fullkey(res["clause"])) if res["clause"] else None,
            "method": res["method"], "confidence": conf, "candidates": res["candidates"], "near_identical": near,
            "auto_eligible": auto, "needs_review": review, "source_tool": "kajal",
        })
    return out
