"""
Local persistence for plans.

Two independent mechanisms, because "save my data" means different things
depending on how the app is running:

  * Named slots in a local folder (./saved_plans). Works when you run Streamlit
    on your own machine. Survives restarts. This is the everyday path.
  * Download / upload of a JSON file. Works everywhere, including a hosted
    deployment where the filesystem is not yours. This is the portable path,
    and the one to use for backups or for sending a plan to someone else.

Nothing leaves the machine either way.
"""

from __future__ import annotations
from pathlib import Path
from datetime import datetime
import json
import re

from engine.roth_profile import Profile

SAVE_DIR = Path(__file__).resolve().parent.parent / "saved_plans"
SUFFIX = ".rothplan.json"


def ensure_dir() -> Path:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    return SAVE_DIR


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 _.-]", "", name).strip()
    return (cleaned or "plan")[:80]


def slot_path(name: str) -> Path:
    return ensure_dir() / (safe_name(name) + SUFFIX)


def list_slots() -> list[dict]:
    """Saved plans in the local folder, newest first."""
    ensure_dir()
    out = []
    for f in SAVE_DIR.glob("*" + SUFFIX):
        try:
            stat = f.stat()
            out.append({
                "name": f.name[: -len(SUFFIX)],
                "path": str(f),
                "modified": datetime.fromtimestamp(stat.st_mtime),
                "size": stat.st_size,
            })
        except OSError:
            continue
    return sorted(out, key=lambda d: d["modified"], reverse=True)


def save_slot(p: Profile, name: str) -> Path:
    path = slot_path(name)
    payload = p.to_dict()
    payload["_saved_at"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_slot(name: str) -> Profile:
    path = slot_path(name)
    if not path.exists():
        raise FileNotFoundError(f"No saved plan named '{name}'.")
    return Profile.from_json(path.read_text(encoding="utf-8"))


def delete_slot(name: str) -> bool:
    path = slot_path(name)
    if path.exists():
        path.unlink()
        return True
    return False


def to_download_bytes(p: Profile) -> bytes:
    payload = p.to_dict()
    payload["_saved_at"] = datetime.now().isoformat(timespec="seconds")
    return json.dumps(payload, indent=2).encode("utf-8")


def download_filename(p: Profile) -> str:
    stamp = datetime.now().strftime("%Y%m%d")
    return f"{safe_name(p.profile_name)}_{stamp}{SUFFIX}"


def from_upload_bytes(data: bytes) -> Profile:
    text = data.decode("utf-8")
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("That file does not contain a plan.")
    return Profile.from_dict(obj)
