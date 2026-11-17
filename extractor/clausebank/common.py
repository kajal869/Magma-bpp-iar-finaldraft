"""Name normalisation and thresholds, vendored from Kajal's clausebank/common.py. The private-zip case locator was removed
(run time has no issued policy and no repo layout)."""
import datetime
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path


# threshold constants are stated here so the workbook can print them
FUZZY_THRESHOLD = 0.75      # method (d): minimum similarity to propose a pair
FUZZY_MARGIN = 0.05         # method (d): lead over the runner-up, else the pair goes to a human
AUTO_ACCEPT = 0.85          # holdout: confidence at or above which a lookup counts as auto-resolved

_STOP = {"clause", "clauses", "cover", "covers", "coverage", "the", "of", "and", "for", "in", "to", "a", "an", "as", "per",
         "any", "is", "or", "by", "on", "with"}
_ABBREV = {"oem": "original equipment manufacturer", "hrs": "hours", "hr": "hour", "p&m": "plant machinery",
           "tsi": "total sum insured", "sartup": "startup", "foregin": "foreign", "subrogration": "subrogation",
           "underinsurance": "under insurance", "ommission": "omission", "invalidation": "invalidation",
           "vitiation": "vitiation", "adjustors": "adjusters", "adjustor": "adjuster", "custom": "customs", "expenses": "cost", "expense": "cost", "costs": "cost"}


def today():
    return datetime.date.today().isoformat()


def norm(s):
    """Normalised key for a clause name. Drops brackets, punctuation, filler words; singularises crudely."""
    s = str(s or "").lower().replace("&", " and ").replace("’", "'")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\bstart[\s-]*up\b", "startup", s)
    s = re.sub(r"\bshut[\s-]*down\b", "shutdown", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    out = []
    for w in s.split():
        w = _ABBREV.get(w, w)
        for v in w.split():
            if v in _STOP:
                continue
            if len(v) > 3 and v.endswith("s") and not v.endswith("ss"):
                v = v[:-1]
            out.append(v)
    return " ".join(out)


def fullkey(s):
    """Identity key of a title: lower-case alphanumerics only, brackets and filler words KEPT (so 'Removal of Debris (In excess of 1%)'
    and 'Removal of Debris' stay different titles)."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(s or "").lower().replace("&", " and ").replace("\u2019", "'")).split())


def norm_loose(s):
    """Like norm() but keeps brackets' content (used only to tell apart near-identical titles)."""
    return norm(re.sub(r"[()]", " ", str(s or "")))


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=False), encoding="utf-8")


