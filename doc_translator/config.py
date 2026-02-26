from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict
from typing import List


def load_local_config(config_path: str | None) -> Dict[str, Any]:
    if not config_path:
        return {}
    path = Path(config_path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_profiles(local_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = local_config.get("LLM_PROFILES")
    if not isinstance(raw, list):
        return []
    profiles: List[Dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            profiles.append(item)
    return profiles


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def write_lock(lock_file: Path, owner: str) -> None:
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": os.getpid(),
        "owner": owner,
        "created_at": int(time.time()),
    }
    lock_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_lock(lock_file: Path) -> Dict[str, Any]:
    if not lock_file.exists():
        return {}
    try:
        return json.loads(lock_file.read_text(encoding="utf-8"))
    except Exception:
        return {}
