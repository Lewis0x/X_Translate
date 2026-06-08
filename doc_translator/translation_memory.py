from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List


@dataclass
class TMMatch:
    """翻译记忆库匹配结果"""
    source: str
    target: str
    similarity: float  # 0.0-1.0
    created_at: str
    source_doc: str | None = None


class TranslationMemory:
    """翻译记忆库 - 存储和复用历史翻译结果"""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.entries: Dict[str, TMMatch] = {}  # source -> TMMatch
        if self.path and self.path.exists():
            self._load()

    def add(self, source: str, target: str, source_doc: str | None = None) -> None:
        """添加新的翻译记忆条目"""
        if not source.strip() or not target.strip():
            return
        # 使用源文本作为 key，去除空白后存储
        key = source.strip()
        self.entries[key] = TMMatch(
            source=source,
            target=target,
            similarity=1.0,
            created_at=datetime.now(timezone.utc).isoformat(),
            source_doc=source_doc,
        )

    def find_matches(
        self, text: str, min_similarity: float = 0.8
    ) -> List[TMMatch]:
        """查找与给定文本相似的翻译记忆"""
        if not text.strip():
            return []

        matches: List[TMMatch] = []
        text_lower = text.strip().lower()

        for source, match in self.entries.items():
            source_lower = source.lower()
            # 精确匹配
            if source_lower == text_lower:
                matches.append(match)
                continue

            # 包含匹配
            if source_lower in text_lower or text_lower in source_lower:
                similarity = len(source) / max(len(text), len(source))
                if similarity >= min_similarity:
                    matches.append(match)

        # 按相似度排序
        matches.sort(key=lambda m: m.similarity, reverse=True)
        return matches[:5]  # 最多返回5个结果

    def get_tm_context(self, texts: List[str], max_items: int = 10) -> str:
        """获取翻译记忆上下文，用于注入 LLM prompt"""
        if not texts:
            return ""

        context_lines = ["参考翻译 (TM):"]
        for text in texts[:max_items]:
            matches = self.find_matches(text, min_similarity=0.6)
            if matches:
                context_lines.append(f"  {text} -> {matches[0].target}")

        if len(context_lines) == 1:
            return ""

        return "\n".join(context_lines)

    def save(self) -> None:
        """保存到文件"""
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(entry) for entry in self.entries.values()]
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load(self) -> None:
        """从文件加载"""
        if not self.path or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for item in data:
                self.entries[item["source"]] = TMMatch(
                    source=item["source"],
                    target=item["target"],
                    similarity=item.get("similarity", 1.0),
                    created_at=item.get("created_at", ""),
                    source_doc=item.get("source_doc"),
                )
        except (json.JSONDecodeError, KeyError):
            pass  # 忽略损坏的文件

    def merge(self, other: "TranslationMemory") -> None:
        """合并另一个 TM 的内容"""
        for source, match in other.entries.items():
            if source not in self.entries:
                self.entries[source] = match

    @property
    def size(self) -> int:
        """返回条目数量"""
        return len(self.entries)
