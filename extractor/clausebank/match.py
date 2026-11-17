"""Name matching shared by the back-tracker, the library and the hold-out test.
Similarity is deliberately simple and explainable: best of sequence ratio, token Jaccard and a discounted containment score."""
import difflib

from .common import norm


def sim(a, b):
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    r = difflib.SequenceMatcher(None, na, nb).ratio()
    j = len(ta & tb) / len(ta | tb)
    c = (len(ta & tb) / min(len(ta), len(tb))) * 0.9 if min(len(ta), len(tb)) >= 2 else 0.0
    return round(max(r, j, c), 3)


def top(name, pool, n=3):
    """pool: list of (label, text). -> [(score, label)] best first."""
    sc = sorted(((sim(name, t), lab) for lab, t in pool), key=lambda x: (-x[0], str(x[1])))
    return sc[:n]
