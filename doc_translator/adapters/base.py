from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from doc_translator.translator import TranslatorProtocol
from doc_translator.glossary import Glossary


@dataclass
class ProcessStats:
    segments_total: int = 0
    segments_translated: int = 0
    glossary_hits: int = 0
    source_segments: list[str] = field(default_factory=list)
    target_segments: list[str] = field(default_factory=list)


class FileAdapter(Protocol):
    suffixes: tuple[str, ...]

    def process(
        self,
        input_file: Path,
        output_file: Path,
        translator: TranslatorProtocol,
        glossary: Glossary,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> ProcessStats:
        ...
