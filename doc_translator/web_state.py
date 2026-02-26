from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from typing import Dict


def make_initial_state(job_id: str, output_dir: Path, log_path: Path) -> Dict[str, Any]:
    now = time.time()
    return {
        "job_id": job_id,
        "status": "queued",
        "message": "任务已创建，等待执行",
        "created_at": now,
        "updated_at": now,
        "current_file": "",
        "file_done": 0,
        "file_total": 0,
        "file_percent": 0,
        "completed_files": 0,
        "total_files": 0,
        "overall_percent": 0,
        "output_dir": str(output_dir),
        "report_path": "",
        "error": "",
        "pid": 0,
        "log_path": str(log_path),
    }


def read_state(state_file: Path) -> Dict[str, Any]:
    if not state_file.exists():
        return {}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_state(state_file: Path, payload: Dict[str, Any]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = state_file.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_file.replace(state_file)


def patch_state(state_file: Path, **updates: Any) -> Dict[str, Any]:
    payload = read_state(state_file)
    payload.update(updates)
    payload["updated_at"] = time.time()
    write_state(state_file, payload)
    return payload
