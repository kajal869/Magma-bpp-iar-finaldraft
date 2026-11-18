"""Render a case JSON to HTML (and PDF) with Jinja2 + Playwright (Chromium).

  python -P app/render.py mann [valmet shreeji] [--pdf] [--out app/out]

Phase 3: front pack only (RAL, schedule, terms, summary, GST block, annexures).
"""
import argparse, base64, json, re, sys
from pathlib import Path
import jinja2
from jsonschema import Draft202012Validator

APP = Path(__file__).resolve().parent
SCHEMA = json.loads((APP / "schema" / "policy.schema.json").read_text(encoding="utf-8"))


def money(v, dec=0):
    if v is None or isinstance(v, jinja2.Undefined):
        return ""
    return f"{v:,.{dec}f}"


def dash(v):
    return "-" if v is None or isinstance(v, jinja2.Undefined) or v == 0 else money(v)


def dash_blank(v):
    return "" if v is None or isinstance(v, jinja2.Undefined) or v == 0 else money(v)


def dmy(iso):
    if not iso or isinstance(iso, jinja2.Undefined) or iso.count("-") != 2:
        return ""
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y}"


def data_uri(path):
    """Image as a data URI; "" when the file is absent (e.g. signature images are not shipped with the portal repo)."""
    if not path.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


FOOT_TAIL = "Trade Logo displayed above belongs to Magma Ventures Private Limited and is used by Magma General Insurance Limited under license. | Chat with MIRA on our website or say “Hi” on WhatsApp No. 7208976789"
REG = "Registered Office: Equinox Business Park, Tower 3, Ambedkar Nagar, 2nd Floor, Unit Number 1b & 2b, LBS Marg Kurla West, Kurla, Mumbai, Mumbai- 400070, Maharashtra, India"
CIN = "CIN: U66000MH2009PLC460693"


# Page geometry per theme in PDF points (page coordinates measured on the reference PDFs).
# Chromium puts header/footer templates 15pt below/above where the CSS says, hence the -15 corrections in header_html/footer_html.
GEOM = {
    "mann":   dict(top=86, bottom=140, left=72, right=72, pno=(72, 37, 11), logo=(243, 54, 118), foot_text=(727, 9), foot_page=713, page_label=True),
    "valmet": dict(top=92, bottom=140, left=72, right=72, pno=(79, 30, 8), logo=(246, 49, 151), foot_text=(702, 8), foot_page=783, page_label=True),
    "laghu":  dict(top=72, bottom=95, left=64, right=47, pno=(64, 14, 11), logo=(245, 30, 119), foot_text=(760, 8), foot_page=None, page_label=False),
}


def page_css(g):
    css = "@page { size: A4; margin: %dpt %dpt %dpt %dpt; }" % (g["top"], g["right"], g["bottom"], g["left"])
    return css + " @page land { size: A4 landscape; margin: 86pt 50pt 120pt 50pt; } "


def footer_text(d):
    p, uin = d["presentation"], d["product"]["uin"]
    head = "Magma General Insurance Limited (erstwhile Magma HDI General Insurance Company Limited) | www.magmainsurance.com | E-mail: customercare@magmainsurance.com | Toll Free: 1800 266 3202 | " + REG
    st = p["footer_style"]
    if st == "mann":
        return f"{head}. | IRDAI Registered No. 149 | {p['footer_product_text']} | UIN: {uin}| {CIN} | {FOOT_TAIL}"
    if st == "valmet":
        return f"{head} | {CIN}| IRDAI Reg. No. 149 | {p['footer_product_text']} | Product UIN: {uin}| {FOOT_TAIL}"
    return f"{head}. | IRDAI Registered No. 149 | {p['footer_product_text']} | UIN: {uin} | {CIN}| {FOOT_TAIL}"


def header_html(d, logo):
    g = GEOM[d["presentation"]["theme"]]
    pre = d["presentation"]["header_policy_prefix"]
    x, y, sz = g["pno"]
    lx, ly, lw = g["logo"]
    return (f'<div style="width:100%;font-family:Calibri,Carlito,sans-serif;position:relative;height:{g["top"]}pt;">'
            f'<div style="position:absolute;left:{x}pt;top:{max(0, y - 15)}pt;font-size:{sz}pt;font-weight:700;white-space:nowrap;">{pre}{d["system"]["policy_no"]}</div>'
            f'<img src="{logo}" style="position:absolute;left:50%;margin-left:{round(lx + lw / 2 - 297.7 - lw / 2, 1)}pt;top:{max(0, ly - 15)}pt;width:{lw}pt;"></div>')


def footer_html(d):
    g = GEOM[d["presentation"]["theme"]]
    ty, fs = g["foot_text"]
    base = g["bottom"] - 827
    label = ""
    if g["page_label"]:
        label = (f'<div style="position:absolute;left:{g["left"]}pt;right:{g["right"]}pt;top:{g["foot_page"] + base}pt;text-align:right;'
                 f'font-family:Times New Roman,serif;font-size:10pt;">Page <b class="pageNumber"></b> of <b class="totalPages"></b></div>')
    return (f'<div style="width:100%;font-family:Calibri,Carlito,sans-serif;position:relative;height:{g["bottom"]}pt;">{label}'
            f'<div style="position:absolute;left:{g["left"]}pt;right:{g["right"]}pt;top:{ty + base}pt;font-size:{fs}pt;line-height:1.45;">{footer_text(d)}</div></div>')


def load_wording(d):
    """Blocks of the case's wording book in manifest order: policy book (preamble, sections, general exclusions/conditions)
    then the appended section wordings listed in options.endorsement_blocks."""
    book = d["options"]["wording_book"]
    base = APP / "wording" / "books" / book
    man = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    keep_end = set(d["options"].get("endorsement_blocks") or [])
    blocks = []
    for b in man["blocks"]:
        if b["block"].startswith("endorse_") and b["block"] not in keep_end:
            continue
        paras = json.loads((base / f"{b['block']}.json").read_text(encoding="utf-8"))["paragraphs"]
        x0 = min(p["x"] for p in paras) if paras else 0
        for p in paras:
            p["text"] = p["text"].replace("", "•")
            if p.get("type") == "table":
                p["rows"] = [[c.replace("", "•") for c in r] for r in p["rows"]]
                p["indent"], p["heading"], p["fs"] = 0, False, 11
                continue
            p["indent"] = max(0, min(p["x"] - x0, 120))
            p["heading"] = bool(p["bold"]) and len(p["text"]) < 110
            p["fs"] = 11
        blocks.append({"name": b["block"], "paragraphs": paras, "new_page": bool(b.get("new_page", True)) or not blocks})
    return blocks


def build(case, out_dir, pdf, full=False):
    d = json.loads((APP / "cases" / f"{case}.json").read_text(encoding="utf-8"))
    return build_dict(case, d, out_dir, pdf, full, validate=True)


def build_dict(case, d, out_dir, pdf, full=False, validate=True):
    """Render from an in-memory case dict. validate=False lets callers leave fields blank on purpose (demo UI)."""
    if validate:
        errs = list(Draft202012Validator(SCHEMA).iter_errors(d))
        if errs:
            sys.exit(f"{case}: schema errors: {errs[0].message}")
    assets = APP / "assets"
    logo_file = "logo_laghu.png" if d["presentation"]["theme"] == "laghu" else "logo_magma.png"
    sig_ral = "sig_laghu.png" if d["presentation"]["theme"] == "laghu" else "sig_ral.png"
    sig_gst = "sig_laghu.png" if d["presentation"]["theme"] == "laghu" else "sig_gst.png"
    img = {"logo": data_uri(assets / logo_file), "sig_ral": data_uri(assets / sig_ral), "sig_gst": data_uri(assets / sig_gst)}

    def period_text():
        p = d["period"]
        return d["presentation"]["period_template"].format(start_time=p.get("start_time", "00:01"), start=dmy(p["start"]), end=dmy(p["end"]))

    pref = tuple(d["presentation"].get("bold_line_prefixes") or [])

    def bold_line(t):
        return bool(pref) and t.startswith(pref)

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(APP / "templates"), autoescape=jinja2.select_autoescape(["j2", "html"], default=True))
    env.filters["money"] = money
    html = env.get_template("front_pack.html.j2").render(d=d, img=img, css=page_css(GEOM[d["presentation"]["theme"]]) + (APP / "templates" / "style.css").read_text(encoding="utf-8"),
                                                         money=money, dash=dash, dash_blank=dash_blank, dmy=dmy, period_text=period_text, bold_line=bold_line, wording=load_wording(d) if full else [])
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "full" if full else "front"
    hp = out_dir / f"{case}_{suffix}.html"
    hp.write_text(html, encoding="utf-8")
    print("html ->", hp)
    if pdf:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            g = GEOM[d["presentation"]["theme"]]
            b = pw.chromium.launch()
            pg = b.new_page()
            pg.goto(hp.resolve().as_uri())
            pp = out_dir / f"{case}_{suffix}.pdf"
            pg.pdf(path=str(pp), format="A4", print_background=True, prefer_css_page_size=True, display_header_footer=True,
                   header_template=header_html(d, img["logo"]), footer_template=footer_html(d),
                   margin={"top": f"{g['top'] / 72}in", "bottom": f"{g['bottom'] / 72}in", "left": f"{g['left'] / 72}in", "right": f"{g['right'] / 72}in"})
            b.close()
        print("pdf  ->", pp)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cases", nargs="+")
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--full", action="store_true", help="append the wording book")
    ap.add_argument("--out", default=str(APP / "out"))
    a = ap.parse_args()
    for c in a.cases:
        build(c, Path(a.out), a.pdf, a.full)
