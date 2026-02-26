from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List


def build_logger(log_file: Path) -> logging.Logger:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("doc_translator")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger


@dataclass
class FileResult:
    input_path: str
    output_path: str
    status: str
    segments_total: int = 0
    segments_translated: int = 0
    glossary_hits: int = 0
    error: str = ""


@dataclass
class RunReport:
    source_lang: str
    target_lang: str
    model: str
    files_total: int = 0
    files_succeeded: int = 0
    files_failed: int = 0
    segments_total: int = 0
    segments_translated: int = 0
    glossary_hits: int = 0
    results: List[FileResult] = field(default_factory=list)

    def add_result(self, result: FileResult) -> None:
        self.results.append(result)
        self.files_total += 1
        self.segments_total += result.segments_total
        self.segments_translated += result.segments_translated
        self.glossary_hits += result.glossary_hits
        if result.status == "success":
            self.files_succeeded += 1
        else:
            self.files_failed += 1

    def write(self, output_file: Path) -> None:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        temp_file = output_file.with_suffix(output_file.suffix + ".tmp")
        temp_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_file.replace(output_file)
