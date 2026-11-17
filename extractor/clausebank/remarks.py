"""Insurer-remark classifier: keep / drop / pending, negation-aware and word-boundary safe.

Order matters: negations are tested before affirmatives, so "cannot be covered", "not accepted", "not allowed",
"not included" are drops and never read as "covered". A remark that is both (e.g. "not covered under X, covered as Y")
is pending, not guessed. The raw remark is always kept by the caller."""
import re

_AFFIRM = (r"covered|cover|accepted|allowed|included|offered|available|agreed|possible|considered|provided|granted|"
           r"applicable|entertained|given|payable|admissible|extended")
_NEG = r"(?:not|cannot|can not|can't|cant|never|unable to|won't|shall not|will not|isn't|aren't|no)"
NEGATED = re.compile(rf"\b{_NEG}\s+(?:\w+\s+){{0,2}}?(?:be\s+)?(?:{_AFFIRM})\b", re.I)
NO_COVER = re.compile(r"\bno\s+cover\b|\bexcluded\b|\bexclusion\b|\bdecline[ds]?\b|\bnot\s+required\b|\bdeleted\b", re.I)
WORDING_REQ = re.compile(r"\b(?:pls|please|kindly)\s+(?:share|provide|send)\b|\bwordings?\s+(?:not\s+(?:provided|available|shared)|awaited|required|needed)\b"
                         r"|\bshare\s+(?:the\s+)?wordings?\b", re.I)
NA = re.compile(r"^\s*(?:n\.?\s?/?\s?a\.?|nil|none|-+|--)\s*$", re.I)
DUPLICATE = re.compile(r"\bduplicate(?:\s+entry)?\b|\bduplicated\b", re.I)
ALREADY = re.compile(r"\balready\s+(?:covered|included|considered|provided|part of)\b|\bcovered\s+(?:above|earlier)\b|\bin\s+place\b", re.I)
PENDING = re.compile(r"\bto\s+be\s+(?:finali[sz]ed|mutually\s+agreed|discussed|confirmed|decided|checked|advised)\b|\btbd\b|\bsubject\s+to\s+(?:claims?|surveyor|underwriter|approval|prorata|pro-rata|recommendation)\b"
                     r"|\bsubject\s+to\s+(?:the\s+)?(?:necessary|availability)\b|\bunder\s+(?:review|discussion)\b|\bmutually\s+agreed\b|\bprorata\b|\bpro-rata\b", re.I)
AFFIRMATIVE = re.compile(r"\bcover(?:ed)?\b|\bagreed\b|\baccepted\b|\bincluded\b|\bgranted\b|\bapplicable\b", re.I)
LIMIT_GRANT = re.compile(r"^\s*(?:up\s*to|upto|max(?:imum)?|limited\s+to)\b", re.I)
CONDITIONAL = re.compile(r"\bif\s+(?:included|declared|used|opted|applicable|loss|provided|inclu?ded)\b|\bexcept\b|\bexcluding\b|\bonly\b|\bsubject\s+to\b|\bprovided\b", re.I)

# pointer: "as per X", "covered as X", "under X"; X is cut at limit phrases
_CITE = [re.compile(r"\bas\s+per\s+(.+)$", re.I), re.compile(r"\bcovered\s+as\s+(.+)$", re.I), re.compile(r"\bunder\s+(.+?)\s+(?:clause|cover)\b", re.I)]
_CUT = re.compile(r"\s+(?:\d[\d.,]*\s*(?:cr|crs|crore|crores|lakh|lakhs|lac|lacs|k|%|per ?cent)\b|upto\b|up to\b|in aggregate\b|subject\b|if\b|provided\b|"
                  r"excluding\b|only\b|for upto\b|within\b|max\b|rs\.?\b|inr\b|whichever\b).*$", re.I)


def cited(remark):
    """The clause an insurer remark points at ("as per Claims Preparation Costs"), or None."""
    r = " ".join(str(remark or "").split())
    for rx in _CITE:
        m = rx.search(r)
        if m:
            x = _CUT.sub("", m.group(1)).strip(" .,;-:–")
            x = re.sub(r"^(?:the|a|an)\s+", "", x, flags=re.I)
            if len(x) >= 3 and not re.fullmatch(r"(?:the\s+)?(?:policy|schedule|quote|insured'?s? book|above|insured)", x, re.I) \
                    and not re.search(r"^(?:the\s+|magma\s+|gil\s+|standard\s+)*(?:policy|schedule)\b|\bwordings?$|\bpolicy\s+(?:terms|wordings?|conditions)", x, re.I):
                return x
    return None


def classify(remark):
    """-> dict(decision, cls, cited, conditional). decision in keep | drop | pending."""
    r = " ".join(str(remark if remark is not None else "").replace("\xa0", " ").split())
    out = {"decision": "pending", "cls": "other", "cited": None, "conditional": False}
    if not r:
        out["cls"] = "blank"
        return out
    out["cited"] = cited(r)
    if NA.match(r):
        out.update(decision="drop", cls="na")
        return out
    if DUPLICATE.search(r):
        out.update(decision="drop", cls="duplicate")
        return out
    neg = bool(NEGATED.search(r) or NO_COVER.search(r))
    pos_text = NEGATED.sub(" ", r)           # what is left when the negated phrases are removed
    pos = bool(AFFIRMATIVE.search(pos_text))
    if WORDING_REQ.search(r):
        out.update(decision="drop", cls="wording_requested")
        return out
    if ALREADY.search(r) and not neg:
        out.update(decision="drop", cls="already_covered")
        return out
    if neg and pos and re.search(r"\b(?:but|however|except|only|else|otherwise)\b|,\s*covered\b", r, re.I):
        out.update(decision="pending", cls="mixed")    # both negative and positive: a person decides
        return out
    if neg:
        out.update(decision="drop", cls="not_covered")
        return out
    if PENDING.search(r):
        out.update(decision="pending", cls="pending_terms")
        return out
    if pos:
        out.update(decision="keep", cls="covered", conditional=bool(CONDITIONAL.search(r)))
        if out["conditional"]:
            out["cls"] = "covered_conditional"
        return out
    if re.match(r"^\s*if\s+(?:included|declared|opted|applicable)\b", r, re.I):
        out.update(decision="keep", cls="covered_conditional", conditional=True)
        return out
    if LIMIT_GRANT.search(r):
        out.update(decision="keep", cls="limit_grant", conditional=True)
        return out
    return out
