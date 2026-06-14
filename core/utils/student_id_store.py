import os
from typing import List, Set

DATA_DIR = os.path.abspath(os.path.join(os.getcwd(), "data"))
SID_FILE = os.path.join(DATA_DIR, "known_student_ids.txt")


def _ensure_paths():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except Exception:
        pass


def list_sids() -> List[str]:
    try:
        if os.path.isfile(SID_FILE):
            with open(SID_FILE, "r", encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip()]
    except Exception:
        return []
    return []


def add_sid(sid: str) -> bool:
    """Add a student id to store; returns True if added or already exists."""
    if not isinstance(sid, str):
        return False
    s = sid.strip()
    if not s or not s.isdigit():
        return False
    _ensure_paths()
    try:
        existing: Set[str] = set(list_sids())
        if s in existing:
            return True
        with open(SID_FILE, "a", encoding="utf-8") as f:
            f.write(s + "\n")
        return True
    except Exception:
        return False
