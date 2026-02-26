from __future__ import annotations

import argparse
import json
import os
import traceback
from pathlib import Path

from doc_translator.glossary import Glossary
from doc_translator.pipeline import SUPPORTED_SUFFIXES
from doc_translator.pipeline import TranslationPipeline
from doc_translator.reporting import RunReport
from doc_translator.reporting import build_logger
from doc_translator.translator import TranslationConfig
from doc_translator.translator import create_translator
from doc_translator.web_state import patch_state
from doc_translator.web_state import read_state
from doc_translator.web_state import write_state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Web worker for doc translator")
    parser.add_argument("--jobs-root", required=True)
    parser.add_argument("--job-id", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    jobs_root = Path(args.jobs_root)
    job_id = args.job_id
    job_dir = jobs_root / job_id
    state_file = job_dir / "job_state.json"
    input_dir = job_dir / "input"
    output_dir = job_dir / "output"
    log_file = output_dir / "logs" / "translator.log"
    logger = build_logger(log_file)

    state = read_state(state_file)
    if not state:
        raise RuntimeError(f"任务状态不存在: {state_file}")

    patch_state(
        state_file,
        status="running",
        message="任务运行中",
        pid=os.getpid(),
        log_path=str(log_file),
    )

    config_payload = json.loads((job_dir / "job_config.json").read_text(encoding="utf-8"))

    try:
        files = sorted([file for file in input_dir.rglob("*") if file.is_file() and file.suffix.lower() in SUPPORTED_SUFFIXES])
        if not files:
            report = RunReport(
                source_lang=str(config_payload["source"]),
                target_lang=str(config_payload["target"]),
                model=str(config_payload["model"]),
            )
            report_file = output_dir / "report.json"
            report.write(report_file)
            patch_state(
                state_file,
                status="completed",
                message="未检测到受支持文件，任务已完成",
                overall_percent=100,
                total_files=0,
                report_path=str(report_file),
            )
            logger.warning("未检测到可翻译文件，任务结束: %s", job_id)
            return

        config = TranslationConfig(
            source_lang=str(config_payload["source"]),
            target_lang=str(config_payload["target"]),
            provider=str(config_payload["provider"]),
            api_key=str(config_payload["api_key"]),
            model=str(config_payload["model"]),
            base_url=str(config_payload["base_url"]),
            endpoint=str(config_payload["endpoint"]),
            batch_size=int(config_payload["batch_size"]),
            max_retries=int(config_payload["max_retries"]),
            rate_limit_rpm=int(config_payload["rate_limit_rpm"]),
        )
        translator = create_translator(config)
        glossary = Glossary.load(None)
        pipeline = TranslationPipeline(translator=translator, glossary=glossary)
        files = pipeline.collect_files([str(input_dir)])

        patch_state(state_file, total_files=len(files))

        report = RunReport(
            source_lang=config.source_lang,
            target_lang=config.target_lang,
            model=config.model,
        )

        def on_file_progress(file_path: Path, done: int, total: int, percent: int) -> None:
            state = read_state(state_file)
            completed_files = int(state.get("completed_files", 0) or 0)
            total_files = max(1, int(state.get("total_files", 0) or 0))
            overall_percent = int(((completed_files + percent / 100.0) / total_files) * 100)
            patch_state(
                state_file,
                current_file=file_path.name,
                file_done=done,
                file_total=total,
                file_percent=percent,
                overall_percent=overall_percent,
            )

        def on_file_finished(_file_path: Path, _status: str) -> None:
            state = read_state(state_file)
            completed_files = int(state.get("completed_files", 0) or 0) + 1
            total_files = max(1, int(state.get("total_files", 0) or 0))
            overall_percent = int((completed_files / total_files) * 100)
            patch_state(
                state_file,
                completed_files=completed_files,
                overall_percent=overall_percent,
            )

        pipeline.process_files(
            files=files,
            output_dir=output_dir,
            suffix=str(config_payload["suffix"]),
            report=report,
            logger=logger,
            file_progress_callback=on_file_progress,
            file_finished_callback=on_file_finished,
        )

        report_file = output_dir / "report.json"
        report.write(report_file)
        patch_state(
            state_file,
            status="completed",
            message="任务完成",
            overall_percent=100,
            report_path=str(report_file),
        )
    except Exception as exc:
        patch_state(
            state_file,
            status="failed",
            message="任务失败",
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        logger.exception("任务失败: %s", job_id)


if __name__ == "__main__":
    main()
