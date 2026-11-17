"""Profile store: seed/ (committed, generic) and learned/ (private, git-ignored, written automatically and by teaching)."""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = HERE / "seed"
LEARNED = Path(os.environ.get("BPP_LAYOUT_DIR") or HERE / "learned")


def _all_dirs():
    return [("seed", SEED), ("learned", LEARNED)]


def list_profiles() -> list[dict]:
    out = []
    for src, d in _all_dirs():
        if not d.exists():
            continue
        for p in sorted(d.glob("*.json")):
            try:
                prof = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            prof["_dir"] = src
            out.append(prof)
    return out


def get(pid: str) -> dict | None:
    return next((p for p in list_profiles() if p["id"] == pid), None)


def save(profile: dict) -> dict:
    LEARNED.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now().isoformat(timespec="seconds")
    profile.setdefault("created", now)
    profile["updated"] = now
    prof = {k: v for k, v in profile.items() if not k.startswith("_")}
    (LEARNED / f"{prof['id']}.json").write_text(json.dumps(prof, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return prof


def delete(pid: str) -> bool:
    p = LEARNED / f"{pid}.json"
    if p.exists():
        p.unlink()
        return True
    return False


def touch(pid: str, ok: bool) -> None:
    prof = get(pid)
    if prof and prof.get("_dir") == "learned":
        prof["uses"] = prof.get("uses", 0) + 1
        prof["last_ok"] = ok
        save(prof)
