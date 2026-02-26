from __future__ import annotations

from collections.abc import Callable
import shutil
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from doc_translator.adapters.base import ProcessStats
from doc_translator.glossary import Glossary
from doc_translator.translator import TranslatorProtocol


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


@dataclass
class NodeRef:
    part_name: str
    node: ET.Element
    placeholders: Dict[str, str]


class DocxAdapter:
    suffixes = (".docx",)

    def process(
        self,
        input_file: Path,
        output_file: Path,
        translator: TranslatorProtocol,
        glossary: Glossary,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> ProcessStats:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input_file, output_file)

        stats = ProcessStats()

        with zipfile.ZipFile(output_file, "r") as zin:
            files = {name: zin.read(name) for name in zin.namelist()}

        part_names = [
            name
            for name in files.keys()
            if name.startswith("word/") and name.endswith(".xml") and _is_translatable_part(name)
        ]

        part_tasks: List[Tuple[str, ET.Element, List[NodeRef], List[str]]] = []
        total_segments = 0

        for part_name in part_names:
            xml_bytes = files[part_name]
            root = ET.fromstring(xml_bytes)
            text_nodes = [node for node in root.iter(f"{{{W_NS}}}t") if (node.text or "").strip()]
            if not text_nodes:
                continue

            source_texts: List[str] = []
            refs: List[NodeRef] = []

            for node in text_nodes:
                original = node.text or ""
                prepared, placeholders, lock_hits = glossary.preprocess_locks(original)
                source_texts.append(prepared)
                refs.append(NodeRef(part_name=part_name, node=node, placeholders=placeholders))
                stats.glossary_hits += lock_hits

            total_segments += len(source_texts)
            part_tasks.append((part_name, root, refs, source_texts))

        translated_so_far = 0
        if progress_callback and total_segments == 0:
            progress_callback(0, 0)

        for part_name, root, refs, source_texts in part_tasks:
            translated = translator.translate(
                source_texts,
                progress_callback=(
                    (lambda done, _total, translated_so_far=translated_so_far: progress_callback(translated_so_far + done, total_segments))
                    if progress_callback
                    else None
                ),
            )

            for idx, translated_text in enumerate(translated):
                restored, hits = glossary.postprocess(translated_text, refs[idx].placeholders)
                refs[idx].node.text = restored
                stats.glossary_hits += hits

            stats.segments_total += len(source_texts)
            stats.segments_translated += len(source_texts)
            files[part_name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            translated_so_far += len(source_texts)

        if progress_callback and total_segments > 0:
            progress_callback(total_segments, total_segments)

        with zipfile.ZipFile(output_file, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for name, payload in files.items():
                zout.writestr(name, payload)

        return stats


def _is_translatable_part(name: str) -> bool:
    if name == "word/document.xml":
        return True
    if name.startswith("word/header") and name.endswith(".xml"):
        return True
    if name.startswith("word/footer") and name.endswith(".xml"):
        return True
    if name in {
        "word/footnotes.xml",
        "word/endnotes.xml",
        "word/comments.xml",
    }:
        return True
    return False
