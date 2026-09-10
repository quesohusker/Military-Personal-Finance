"""
Local persistence for plans.

Two mechanisms, because "save my data" means different things depending on how
the app is running:

  * Named slots in a local folder (./saved_plans). Works when Streamlit runs on
    your own machine, survives restarts, and is the everyday path.
  * Download / upload of a JSON file. Works everywhere, including a hosted
    deployment where the filesystem is ephemeral and a saved slot would vanish
    on the next restart. This is the path that matters on Streamlit Cloud.

Nothing leaves the machine either way.
"""

from __future__ import annotations
from pathlib import Path
from datetime import datetime
import json
import re

from engine.profile import Household

SAVE_DIR = Path(__file__).resolve().parent.parent / "saved_plans"
SUFFIX = ".mpfplan.json"


def ensure_dir() -> Path:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    return SAVE_DIR


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 _.-]", "", name or "").strip()
    return (cleaned or "plan")[:80]


def slot_path(name: str) -> Path:
    return ensure_dir() / (safe_name(name) + SUFFIX)


def list_slots() -> list[dict]:
    ensure_dir()
    out = []
    for f in SAVE_DIR.glob("*" + SUFFIX):
        try:
            st = f.stat()
            out.append({"name": f.name[: -len(SUFFIX)], "path": str(f),
                        "modified": datetime.fromtimestamp(st.st_mtime),
                        "size": st.st_size})
        except OSError:
            continue
    return sorted(out, key=lambda d: d["modified"], reverse=True)


def save_slot(h: Household, name: str) -> Path:
    path = slot_path(name)
    payload = h.to_dict()
    payload["_saved_at"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_slot(name: str) -> Household:
    path = slot_path(name)
    if not path.exists():
        raise FileNotFoundError(f"No saved plan named '{name}'.")
    return Household.from_json(path.read_text(encoding="utf-8"))


def delete_slot(name: str) -> bool:
    path = slot_path(name)
    if path.exists():
        path.unlink()
        return True
    return False


def to_download_bytes(h: Household) -> bytes:
    payload = h.to_dict()
    payload["_saved_at"] = datetime.now().isoformat(timespec="seconds")
    return json.dumps(payload, indent=2).encode("utf-8")


def download_filename(h: Household) -> str:
    stamp = datetime.now().strftime("%Y%m%d")
    return f"{safe_name(h.profile_name)}_{stamp}{SUFFIX}"


def from_upload_bytes(data: bytes) -> Household:
    obj = json.loads(data.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("That file does not contain a plan.")
    return Household.from_dict(obj)
