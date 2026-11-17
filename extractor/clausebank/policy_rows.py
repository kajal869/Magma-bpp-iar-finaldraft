"""SCORING/TRAINING ONLY (needs an issued policy; production runs have none). Vendored unchanged except HERE.

Read an issued policy (PDF or Daechang DOCX) into
  rows      annexure add-on rows: annexure, risk location, serial, printed name, limit, page
  headings  clause-wording headings found after 'Whereas the Insured named in the Schedule', each with its wording text

Headings are bold stand-alone lines (PDF font name / DOCX run bold) plus any line equal to a library title. Wording is the text up to
the next heading. Results are cached under _cache/ (git-ignored) because pdfplumber is slow on 100+ page policies."""
import hashlib
import json
import re
import warnings
from pathlib import Path

from .common import load_json, norm, save_json

HERE = Path(__file__).resolve().parent   # vendored: cache lives next to this file (git-ignored _cache/)

warnings.filterwarnings("ignore")
CACHE = HERE / "_cache"
BOILER = re.compile(r"^(?:policy no|page \d+ of|magma general insurance limited|\|\s*e-mail|\d,\s*ambedkar|india\.\s*\||u66000|general insurance limited under|"
                    r"for detailed policy|registered office|irdai|chat with mira|trade logo|\| irdai)", re.I)
ASSETISH = re.compile(r"\b(?:building|buildings|contents|plant|machinery|stocks?|furniture|fixtures|fittings|raw materials?|finished goods|"
                      r"semi[- ]finished|work in progress|boundary wall|electronic equipment|computers?|office equipment|p&m|stock in process|"
                      r"stocks or stocks|total sum insured|including but not limited)\b", re.I)
SKIP_HEADING = re.compile(r"^(?:policy no|page \d+|sr\.?|description|schedule|annexure|section\b|part\b|note\b|notes\b|total\b|\d+$|signed|authori[sz]ed|"
                          r"for magma|date\b|place\b|insured\b|premium\b|name of|address|email|phone|toll)", re.I)


def _digest(path):
    p = Path(path)
    return hashlib.sha1(f"{p.name}|{p.stat().st_size}|{p.stat().st_mtime_ns}".encode()).hexdigest()[:16]


def _clean_heading(t):
    t = " ".join(t.split())
    t = re.sub(r"^\(?\d{1,2}[.)]\s+", "", t)           # '8. Sanction Limitation ...' -> title
    return t.strip(" :-–")


def _is_heading_text(t):
    t = _clean_heading(t)
    if not t or len(t) < 4 or len(t.split()) > 16 or BOILER.match(t) or SKIP_HEADING.match(t):
        return False
    if t.endswith((".", ",", ";")) and not re.search(r"(?:clause|cover)\.$", t, re.I):
        return False
    if t[0].islower() and t.lower() not in ("spontaneous combustion.",):
        return False
    return True


# ---------------------------------------------------------------------------------------------------- PDF
def _lines(page):
    """-> [(top, text, bold, size)] merged from words, header/footer boilerplate removed."""
    words = page.extract_words(extra_attrs=["fontname", "size"], keep_blank_chars=False, use_text_flow=False)
    rows = {}
    for w in words:
        rows.setdefault(round(w["top"] / 2.5), []).append(w)
    out = []
    for k in sorted(rows):
        ws = sorted(rows[k], key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in ws)
        if BOILER.match(text):
            continue
        bold = all(("bold" in w["fontname"].lower() or "black" in w["fontname"].lower()) for w in ws)
        out.append((ws[0]["top"], text, bold, round(ws[0]["size"], 1)))
    return out


def _pdf(path):
    import pdfplumber
    rows, headings = [], []
    with pdfplumber.open(str(path)) as pdf:
        n = len(pdf.pages)
        texts_first = []
        wording = n
        for i, p in enumerate(pdf.pages):                      # locate the fixed wording start cheaply
            t = p.extract_text() or ""
            texts_first.append(t)
            if "Whereas the Insured named in the Schedule" in t:
                wording = i
                break
        annex, loc, in_addon, last_hdr = None, "", False, None
        for i in range(wording):
            page = pdf.pages[i]
            lines = _lines(page)
            tabs = sorted(page.find_tables(), key=lambda t: t.bbox[1])
            prev_bottom = 0
            def see(text):
                nonlocal annex, loc, in_addon
                if re.search(r"risk\s*location\s*annexure", text, re.I):
                    annex, in_addon = None, False             # location listing, not an add-on annexure
                m = re.search(r"ANNEXURE\s*(\d+)", text, re.I)
                if m:
                    annex, loc, in_addon = m.group(1), "", False
                m = re.search(r"risk\s*location\s*[-:]?\s*(\d+)", text, re.I)
                if m and re.search(r"add[\s-]*on", text, re.I):
                    loc = m.group(1)
                if re.search(r"add[\s-]*on", text, re.I) and len(text) < 60:
                    in_addon = True

            for t in tabs:
                head = [l for l in lines if prev_bottom <= l[0] < t.bbox[1]]
                prev_bottom = t.bbox[3]
                for _, text, *_ in head:
                    see(text)
                data = [[(c or "").replace("\n", " ").strip() for c in r] for r in t.extract()]
                if not data or annex is None:
                    continue
                hdr = " ".join(data[0]).lower()
                if "total sum" in hdr or "risk location" in hdr:
                    in_addon = False
                    continue
                numbered = [r for r in data if r and re.fullmatch(r"\d{1,3}", next((c for c in r if c), ""))]
                names = [[c for c in r if c][1] if len([c for c in r if c]) > 1 else "" for r in numbered]
                if names and all(ASSETISH.search(x) or re.search(r"risk location", x, re.I) for x in names if x):
                    in_addon = False
                    continue
                if re.search(r"add[\s-]*on", hdr):
                    in_addon = True
                kind = "addon" if in_addon else "annexure_other"
                if not in_addon and last_hdr and hdr[:40] == last_hdr[:40]:
                    kind = "addon"
                    in_addon = True
                last_hdr = hdr
                body = data if kind == "addon" else numbered
                for r in body:
                    cells = [c for c in r if c]
                    if len(cells) < 2 or len(cells[0]) < 3 and not cells[0].isdigit() or (len(cells) == 2 and cells[1].upper() in ("NA", "N/A")) or re.match(r"^(?:sr\b|s\.?\s?no|covers?\b|description|add[\s-]*on)", cells[0], re.I):
                        continue
                    ser = cells[0] if re.fullmatch(r"\d{1,3}", cells[0]) else ""
                    rest = cells[1:] if ser else cells
                    if not rest or (ser and len(rest) < 1):
                        continue
                    rows.append({"page": i + 1, "annexure": annex or "", "location": loc, "serial": ser, "name": rest[0],
                                 "limit": " ".join(rest[1:]), "table_kind": kind})
            for _, text, *_ in [l for l in lines if l[0] >= prev_bottom]:
                see(text)                                   # heading at the foot of a page applies to the next page's table
        # wording headings
        for i in range(wording, n):
            page = pdf.pages[i]
            cur = None
            for top, text, bold, size in _lines(page):
                if bold and _is_heading_text(text):
                    h = _clean_heading(text)
                    if cur is not None and cur["_open"] and cur["wording"] == "" and cur["page"] == i + 1:
                        cur["name"] += " " + h          # wrapped heading line
                        continue
                    cur = {"page": i + 1, "name": h, "wording": "", "via": "bold", "_open": True}
                    headings.append(cur)
                elif headings:
                    headings[-1]["wording"] += text + " "
                    if cur is not None:
                        cur["_open"] = cur is headings[-1]
    for h in headings:
        h.pop("_open", None)
        h["wording"] = " ".join(h["wording"].split())
    return rows, headings, {"pages": n, "wording_page": wording + 1}


# --------------------------------------------------------------------------------------------------- DOCX
def _docx(path):
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    d = docx.Document(str(path))
    rows, headings = [], []
    annex, in_wording, seen_tables = None, False, 0
    for el in d.element.body.iterchildren():
        if el.tag.endswith("}p"):
            p = Paragraph(el, d)
            t = " ".join(p.text.split())
            if not t:
                continue
            m = re.search(r"ANNEXURE\s*(\d+)", t, re.I)
            if m and not in_wording:
                annex = m.group(1)
            if "Whereas the Insured named in the Schedule" in t:
                in_wording = True
                continue
            if in_wording:
                bold = bool(p.runs) and all((r.bold or (p.style and p.style.font and p.style.font.bold)) for r in p.runs if r.text.strip())
                if bold and _is_heading_text(t):
                    headings.append({"page": None, "name": _clean_heading(t), "wording": "", "via": "bold"})
                elif headings:
                    headings[-1]["wording"] += t + " "
        elif el.tag.endswith("}tbl") and not in_wording:
            tb = Table(el, d)
            seen_tables += 1
            data = [[" ".join(c.text.split()) for c in r.cells] for r in tb.rows]
            if not data:
                continue
            hdr = " ".join(data[0]).lower()
            if "total sum" in hdr and "add" not in hdr:
                continue
            body = [r for r in data[1:] if r and re.fullmatch(r"\d{1,3}", r[0] or "")]
            names = [r[1] for r in body if len(r) > 1]
            if names and all(ASSETISH.search(x) for x in names if x):
                continue
            kind = "addon" if re.search(r"add[\s-]*on", hdr) else "annexure_other"
            for r in body:
                # python-docx repeats merged cells; de-duplicate adjacent equal cells
                cells = [c for k, c in enumerate(r) if c and (k == 0 or c != r[k - 1])]
                if len(cells) >= 2:
                    rows.append({"page": None, "annexure": annex or "", "location": "", "serial": cells[0], "name": cells[1],
                                 "limit": " ".join(cells[2:]), "table_kind": kind})
    for h in headings:
        h["wording"] = " ".join(h["wording"].split())
    return rows, headings, {"pages": None, "wording_page": None}


def read(case, path, kind):
    """-> {'rows': [...], 'headings': [...], 'meta': {...}} (cached)."""
    CACHE.mkdir(exist_ok=True)
    cf = CACHE / f"policy_{case}_{_digest(path)}.json"
    if cf.exists():
        return json.loads(cf.read_text(encoding="utf-8"))
    rows, headings, meta = (_pdf if kind == "pdf" else _docx)(path)
    for i, r in enumerate(rows):
        r["case"] = case
        r["key"] = f"{case}|P{i + 1}"
    for h in headings:
        h["case"] = case
    out = {"rows": rows, "headings": headings, "meta": meta}
    cf.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out
