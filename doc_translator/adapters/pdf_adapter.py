from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Dict, List, Tuple

import fitz

from doc_translator.adapters.base import ProcessStats
from doc_translator.glossary import Glossary
from doc_translator.translator import TranslatorProtocol


class PdfAdapter:
    suffixes = (".pdf",)

    def process(
        self,
        input_file: Path,
        output_file: Path,
        translator: TranslatorProtocol,
        glossary: Glossary,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> ProcessStats:
        output_file.parent.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(input_file)
        stats = ProcessStats()

        page_blocks: Dict[int, List[Tuple[fitz.Rect, Dict[str, str]]]] = {}
        all_source_texts: List[str] = []

        for page_index, page in enumerate(doc):
            blocks = page.get_text("blocks")
            translatable_blocks: List[Tuple[fitz.Rect, Dict[str, str]]] = []

            for block in blocks:
                x0, y0, x1, y1, text, _block_no, block_type = block
                if int(block_type) != 0:
                    continue
                raw = (text or "").strip()
                if not raw:
                    continue

                prepared, placeholders, lock_hits = glossary.preprocess_locks(raw)
                translatable_blocks.append((fitz.Rect(x0, y0, x1, y1), placeholders))
                all_source_texts.append(prepared)
                stats.glossary_hits += lock_hits

            if translatable_blocks:
                page_blocks[page_index] = translatable_blocks

        if not all_source_texts:
            if progress_callback:
                progress_callback(0, 0)
            doc.save(output_file)
            doc.close()
            return stats

        translated = translator.translate(all_source_texts, progress_callback=progress_callback)

        cursor = 0
        for page_index in sorted(page_blocks.keys()):
            page = doc[page_index]
            translatable_blocks = page_blocks[page_index]
            translated_slice = translated[cursor : cursor + len(translatable_blocks)]
            for index, translated_text in enumerate(translated_slice):
                rect, placeholders = translatable_blocks[index]
                restored, hits = glossary.postprocess(translated_text, placeholders)
                stats.glossary_hits += hits
                page.add_redact_annot(rect, fill=(1, 1, 1))
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
                page.insert_textbox(rect, restored, fontsize=10, color=(0, 0, 0), align=fitz.TEXT_ALIGN_LEFT)
            cursor += len(translatable_blocks)

        stats.segments_total += len(all_source_texts)
        stats.segments_translated += len(all_source_texts)

        doc.save(output_file)
        doc.close()
        return stats
