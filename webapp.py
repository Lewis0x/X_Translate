from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path
from typing import Any

from flask import Flask
from flask import jsonify
from flask import make_response
from flask import render_template
from flask import request
from flask import send_file
from werkzeug.utils import secure_filename

from doc_translator.config import is_pid_alive
from doc_translator.config import load_local_config
from doc_translator.glossary import Glossary
from doc_translator.translator import TranslationConfig
from doc_translator.translator import create_translator
from doc_translator.web_state import make_initial_state
from doc_translator.web_state import patch_state
from doc_translator.web_state import read_state
from doc_translator.web_state import write_state


app = Flask(__name__)
workspace_root = Path(__file__).resolve().parent
jobs_root = workspace_root / "web_runs"
jobs_root.mkdir(parents=True, exist_ok=True)

_jobs: dict[str, dict[str, Any]] = {}


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/office/addin")
def office_addin_page():
    return render_template("office_addin.html")


@app.get("/office/manifest.xml")
def office_addin_manifest():
    manifest_path = workspace_root / "office_addin" / "manifest.xml"
    if not manifest_path.exists():
        return jsonify({"error": "manifest 不存在"}), 404

    response = make_response(manifest_path.read_text(encoding="utf-8"))
    response.headers["Content-Type"] = "application/xml; charset=utf-8"
    return response


@app.post("/api/jobs")
def create_job():
    files = request.files.getlist("files")
    valid_files = [file for file in files if file and file.filename]
    if not valid_files:
        return jsonify({"error": "请至少选择一个文件"}), 400

    job_id = uuid.uuid4().hex[:12]
    job_dir = jobs_root / job_id
    input_dir = job_dir / "input"
    output_dir = job_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    for file in valid_files:
        safe_name = secure_filename(file.filename)
        if not safe_name:
            continue
        file.save(input_dir / safe_name)

    local_config = load_local_config(str(workspace_root / "local.config.json"))
    provider = request.form.get("provider", "openai")
    provider_lower = provider.strip().lower()

    if provider_lower == "openai":
        base_url_default = str(local_config.get("OPENAI_BASE_URL", "") or local_config.get("LLM_BASE_URL", ""))
        endpoint_default = str(local_config.get("OPENAI_ENDPOINT", "") or local_config.get("LLM_ENDPOINT", "/chat/completions"))
    else:
        base_url_default = str(local_config.get("LLM_BASE_URL", ""))
        endpoint_default = str(local_config.get("LLM_ENDPOINT", "/chat/completions"))

    config_payload: dict[str, Any] = {
        "source": request.form.get("source", "zh"),
        "target": request.form.get("target", "en"),
        "domain": request.form.get("domain", "general"),
        "provider": provider,
        "model": request.form.get("model", "") or str(local_config.get("LLM_MODEL", local_config.get("OPENAI_MODEL", ""))),
        "api_key": request.form.get("api_key", "") or str(local_config.get("OPEN_API_KEY", "")),
        "base_url": request.form.get("base_url", "") or base_url_default,
        "endpoint": request.form.get("endpoint", "/chat/completions") or endpoint_default,
        "batch_size": int(request.form.get("batch_size", "20")),
        "max_retries": int(request.form.get("max_retries", "3")),
        "rate_limit_rpm": int(request.form.get("rate_limit_rpm", "60")),
        "suffix": request.form.get("suffix", "") or request.form.get("target", "en"),
    }
    (job_dir / "job_config.json").write_text(
        json.dumps(config_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    state_file = job_dir / "job_state.json"
    state = make_initial_state(job_id=job_id, output_dir=output_dir, log_path=output_dir / "logs" / "translator.log")
    write_state(state_file, state)
    _jobs[job_id] = state

    cmd = [
        sys.executable,
        "-m",
        "doc_translator.web_worker",
        "--jobs-root",
        str(jobs_root),
        "--job-id",
        job_id,
    ]

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(workspace_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            creationflags=creationflags,
        )
        patch_state(
            state_file,
            message="任务已启动，等待worker执行",
            pid=int(proc.pid),
        )
    except Exception as exc:
        patch_state(
            state_file,
            status="failed",
            message="任务启动失败",
            error=str(exc),
        )
        return jsonify({"error": f"任务启动失败: {exc}"}), 500

    return jsonify({"job_id": job_id})


@app.post("/api/translate_text")
def translate_text():
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", ""))
    if not text.strip():
        return jsonify({"error": "text 不能为空"}), 400

    try:
        config = _build_translation_config(payload)
        translator = create_translator(config)
        translated_text = _translate_texts_with_optional_glossary([text], translator, payload)[0]
    except Exception as exc:
        return jsonify({"error": f"翻译失败: {exc}"}), 500

    return jsonify({"translated_text": translated_text})


@app.post("/api/translate_batch")
def translate_batch():
    payload = request.get_json(silent=True) or {}
    texts = payload.get("texts")
    if not isinstance(texts, list) or not texts:
        return jsonify({"error": "texts 不能为空数组"}), 400

    normalized_texts = [str(item) for item in texts]

    try:
        config = _build_translation_config(payload)
        translator = create_translator(config)
        translations = _translate_texts_with_optional_glossary(normalized_texts, translator, payload)
    except Exception as exc:
        return jsonify({"error": f"翻译失败: {exc}"}), 500

    return jsonify({"translations": translations})


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str):
    state = _read_job_state(job_id)
    if not state:
        return jsonify({"error": "任务不存在"}), 404
    _jobs[job_id] = state
    return jsonify(state)


@app.get("/api/jobs/<job_id>/logs")
def get_job_logs(job_id: str):
    state = _read_job_state(job_id)
    if not state:
        return jsonify({"error": "任务不存在"}), 404

    tail = int(request.args.get("tail", "120"))
    tail = max(10, min(1000, tail))
    log_file = Path(str(state.get("log_path") or (jobs_root / job_id / "output" / "logs" / "translator.log")))
    if not log_file.exists():
        return jsonify({"logs": [], "status": state.get("status", "queued")})

    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    return jsonify({"logs": lines[-tail:], "status": state.get("status", "queued")})


@app.get("/api/jobs/<job_id>/download")
def download_job(job_id: str):
    state = _read_job_state(job_id)
    if not state:
        return jsonify({"error": "任务不存在"}), 404
    if state.get("status") != "completed":
        return jsonify({"error": "任务尚未完成"}), 400

    output_dir = Path(str(state.get("output_dir", "")))
    if not output_dir.exists():
        return jsonify({"error": "输出目录不存在"}), 404

    zip_path = output_dir.parent / f"{job_id}_output.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file in output_dir.rglob("*"):
            if file.is_file():
                zf.write(file, arcname=file.relative_to(output_dir))
    return send_file(zip_path, as_attachment=True, download_name=zip_path.name)


def _read_job_state(job_id: str) -> dict[str, Any]:
    state_file = jobs_root / job_id / "job_state.json"
    state = read_state(state_file)
    if not state:
        return {}

    status = str(state.get("status", ""))
    pid = int(state.get("pid", 0) or 0)
    if status in {"queued", "running"} and pid > 0 and not is_pid_alive(pid):
        report_file = Path(str(state.get("report_path", "")))
        if report_file.exists():
            state = patch_state(
                state_file,
                status="completed",
                message="任务完成",
                overall_percent=100,
            )
        else:
            state = patch_state(
                state_file,
                status="failed",
                message="任务进程已退出",
                error="worker process exited unexpectedly",
            )

    return state


def _to_int(value: Any, default_value: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default_value


def _build_translation_config(payload: dict[str, Any]) -> TranslationConfig:
    local_config = load_local_config(str(workspace_root / "local.config.json"))
    provider = str(payload.get("provider", "") or local_config.get("LLM_PROVIDER", "openai"))
    provider_lower = provider.strip().lower()

    if provider_lower == "openai":
        default_base_url = str(local_config.get("OPENAI_BASE_URL", "") or local_config.get("LLM_BASE_URL", ""))
        default_endpoint = str(local_config.get("OPENAI_ENDPOINT", "") or local_config.get("LLM_ENDPOINT", "/chat/completions"))
    else:
        default_base_url = str(local_config.get("LLM_BASE_URL", ""))
        default_endpoint = str(local_config.get("LLM_ENDPOINT", "/chat/completions"))

    return TranslationConfig(
        source_lang=str(payload.get("source", "zh") or "zh"),
        target_lang=str(payload.get("target", "en") or "en"),
        domain=str(payload.get("domain", "") or local_config.get("TRANSLATION_DOMAIN", "general")),
        provider=provider,
        api_key=str(payload.get("api_key", "") or local_config.get("OPEN_API_KEY", "")),
        base_url=str(payload.get("base_url", "") or default_base_url),
        endpoint=str(payload.get("endpoint", "") or default_endpoint),
        batch_size=_to_int(payload.get("batch_size", 20), 20),
        max_retries=_to_int(payload.get("max_retries", 3), 3),
        rate_limit_rpm=_to_int(payload.get("rate_limit_rpm", 60), 60),
        model=str(payload.get("model", "") or local_config.get("LLM_MODEL", local_config.get("OPENAI_MODEL", ""))),
    )


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _translate_texts_with_optional_glossary(texts: list[str], translator, payload: dict[str, Any]) -> list[str]:
    use_glossary = _parse_bool(payload.get("use_glossary"))
    glossary_path = str(payload.get("glossary_path", "")).strip()

    if not use_glossary:
        return translator.translate(texts)

    glossary = Glossary.load(glossary_path)
    preprocessed_texts: list[str] = []
    placeholders_list: list[dict[str, str]] = []

    for text in texts:
        updated_text, placeholders, _ = glossary.preprocess_locks(text)
        preprocessed_texts.append(updated_text)
        placeholders_list.append(placeholders)

    translated = translator.translate(preprocessed_texts)
    finalized: list[str] = []
    for index, text in enumerate(translated):
        post_text, _ = glossary.postprocess(text, placeholders_list[index])
        finalized.append(post_text)
    return finalized


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=True)
