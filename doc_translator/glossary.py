from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


@dataclass
class GlossaryTerm:
    source: str
    target: str
    case_sensitive: bool = False
    lock: bool = False
    category: str = ""
    comment: str = ""


def _to_bool(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


class Glossary:
    def __init__(self, terms: Iterable[GlossaryTerm] | None = None):
        self.terms: List[GlossaryTerm] = list(terms or [])
        self.lock_terms = [term for term in self.terms if term.lock]
        self.force_terms = [term for term in self.terms if not term.lock]

    @staticmethod
    def load(path: str | Path | None) -> "Glossary":
        if not path:
            return Glossary([])
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"术语表不存在: {file_path}")

        if file_path.suffix.lower() == ".json":
            return Glossary(_load_json(file_path))
        return Glossary(_load_csv(file_path))

    def preprocess_locks(self, text: str) -> Tuple[str, Dict[str, str], int]:
        placeholders: Dict[str, str] = {}
        hit_count = 0
        updated = text

        for index, term in enumerate(self.lock_terms):
            placeholder = f"__LOCK_{index}__"
            flags = 0 if term.case_sensitive else re.IGNORECASE
            pattern = re.compile(re.escape(term.source), flags)

            def repl(match: re.Match[str]) -> str:
                nonlocal hit_count
                hit_count += 1
                key = f"{placeholder}_{hit_count}"
                placeholders[key] = match.group(0)
                return key

            updated = pattern.sub(repl, updated)
        return updated, placeholders, hit_count

    def postprocess(self, text: str, placeholders: Dict[str, str]) -> Tuple[str, int]:
        updated = text
        hit_count = 0

        for token, original in placeholders.items():
            if token in updated:
                updated = updated.replace(token, original)

        for term in self.force_terms:
            flags = 0 if term.case_sensitive else re.IGNORECASE
            pattern = re.compile(re.escape(term.source), flags)
            found = len(pattern.findall(updated))
            if found:
                hit_count += found
                updated = pattern.sub(term.target, updated)

        return updated, hit_count

    def get_terms_by_category(self, category: str) -> "Glossary":
        """按分类获取术语，返回新的 Glossary 实例"""
        filtered = [term for term in self.terms if term.category == category]
        return Glossary(filtered)

    def get_glossary_summary(self, max_items: int = 20) -> str:
        """获取术语摘要，用于注入 LLM prompt"""
        if not self.terms:
            return ""
        lines = ["术语表:"]
        for term in self.terms[:max_items]:
            lines.append(f"  {term.source} -> {term.target}")
        if len(self.terms) > max_items:
            lines.append(f"  ... 共 {len(self.terms)} 条术语")
        return "\n".join(lines)


def _load_csv(path: Path) -> List[GlossaryTerm]:
    terms: List[GlossaryTerm] = []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            source = (row.get("source") or "").strip()
            target = (row.get("target") or "").strip()
            if not source:
                continue
            terms.append(
                GlossaryTerm(
                    source=source,
                    target=target or source,
                    case_sensitive=_to_bool(row.get("case_sensitive")),
                    lock=_to_bool(row.get("lock")),
                    category=(row.get("category") or "").strip(),
                    comment=(row.get("comment") or "").strip(),
                )
            )
    return terms


def _load_json(path: Path) -> List[GlossaryTerm]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    terms: List[GlossaryTerm] = []
    for item in raw:
        source = str(item.get("source", "")).strip()
        target = str(item.get("target", "")).strip()
        if not source:
            continue
        terms.append(
            GlossaryTerm(
                source=source,
                target=target or source,
                case_sensitive=_to_bool(item.get("case_sensitive")),
                lock=_to_bool(item.get("lock")),
                category=str(item.get("category", "")).strip(),
                comment=str(item.get("comment", "")).strip(),
            )
        )
    return terms
