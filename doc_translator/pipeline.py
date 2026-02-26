from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Dict, Iterable, List

from doc_translator.adapters.base import FileAdapter
from doc_translator.glossary import Glossary
from doc_translator.reporting import FileResult, RunReport
from doc_translator.translator import TranslatorProtocol


SUPPORTED_SUFFIXES = {".docx", ".xlsx", ".pdf"}


class TranslationPipeline:
    def __init__(self, translator: TranslatorProtocol, glossary: Glossary):
        from doc_translator.adapters.docx_adapter import DocxAdapter

        self.translator = translator
        self.glossary = glossary
        self.adapters: Dict[str, FileAdapter] = {}

        adapter_instances = [DocxAdapter()]
        try:
            from doc_translator.adapters.xlsx_adapter import XlsxAdapter

            adapter_instances.append(XlsxAdapter())
        except ModuleNotFoundError:
            pass

        try:
            from doc_translator.adapters.pdf_adapter import PdfAdapter

            adapter_instances.append(PdfAdapter())
        except ModuleNotFoundError:
            pass

        for adapter in adapter_instances:
            for suffix in adapter.suffixes:
                self.adapters[suffix] = adapter

    def collect_files(self, inputs: Iterable[str]) -> List[Path]:
        files: List[Path] = []
        for raw in inputs:
            path = Path(raw)
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                files.append(path)
                continue
            if path.is_dir():
                for child in path.rglob("*"):
                    if child.is_file() and child.suffix.lower() in SUPPORTED_SUFFIXES:
                        files.append(child)
        dedup = sorted(set(files))
        return dedup

    def make_output_path(self, input_file: Path, output_dir: Path, suffix: str) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_name = f"{input_file.stem}_{suffix}{input_file.suffix}"
        return output_dir / output_name

    def process_files(
        self,
        files: List[Path],
        output_dir: Path,
        suffix: str,
        report: RunReport,
        logger,
        file_progress_callback: Callable[[Path, int, int, int], None] | None = None,
        file_finished_callback: Callable[[Path, str], None] | None = None,
    ) -> None:
        for input_file in files:
            adapter = self.adapters.get(input_file.suffix.lower())
            output_file = self.make_output_path(input_file, output_dir, suffix)
            if not adapter:
                logger.warning("跳过不支持的文件类型: %s", input_file)
                continue
            try:
                logger.info("开始处理: %s", input_file)
                last_logged_percent = -1

                def on_progress(done: int, total: int) -> None:
                    nonlocal last_logged_percent
                    if total <= 0:
                        return
                    percent = int(done * 100 / total)
                    if percent >= 100 or percent - last_logged_percent >= 5:
                        last_logged_percent = percent
                        logger.info("翻译进度: %s | %d/%d (%d%%)", input_file.name, done, total, percent)
                    if file_progress_callback:
                        file_progress_callback(input_file, done, total, percent)

                stats = adapter.process(
                    input_file,
                    output_file,
                    self.translator,
                    self.glossary,
                    progress_callback=on_progress,
                )
                report.add_result(
                    FileResult(
                        input_path=str(input_file),
                        output_path=str(output_file),
                        status="success",
                        segments_total=stats.segments_total,
                        segments_translated=stats.segments_translated,
                        glossary_hits=stats.glossary_hits,
                    )
                )
                logger.info("完成处理: %s -> %s", input_file, output_file)
                if file_finished_callback:
                    file_finished_callback(input_file, "success")
            except Exception as exc:
                report.add_result(
                    FileResult(
                        input_path=str(input_file),
                        output_path=str(output_file),
                        status="failed",
                        error=str(exc),
                    )
                )
                logger.exception("处理失败: %s", input_file)
                if file_finished_callback:
                    file_finished_callback(input_file, "failed")
