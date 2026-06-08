from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from doc_translator.glossary import Glossary


@dataclass
class LQAIssue:
    """LQA 问题项"""
    segment_index: int
    issue_type: str  # "terminology", "placeholder", "consistency", "number"
    severity: str    # "error", "warning", "info"
    message: str
    suggestion: str | None = None


@dataclass
class LQAResult:
    """LQA 检查结果"""
    issues: List[LQAIssue]
    score: float  # 0.0-100.0


class LQAChecker:
    """自动翻译质量检查器"""

    def __init__(self, glossary: Glossary | None = None):
        self.glossary = glossary

    def check(
        self,
        source_segments: List[str],
        target_segments: List[str],
        glossary: Glossary | None = None,
    ) -> LQAResult:
        """执行 LQA 检查"""
        gloss = glossary or self.glossary
        issues: List[LQAIssue] = []

        # 确保长度一致
        if len(source_segments) != len(target_segments):
            issues.append(
                LQAIssue(
                    segment_index=-1,
                    issue_type="consistency",
                    severity="error",
                    message=f"段落数量不匹配: 原文 {len(source_segments)} 段, 译文 {len(target_segments)} 段",
                )
            )

        min_len = min(len(source_segments), len(target_segments))

        for i in range(min_len):
            source = source_segments[i]
            target = target_segments[i]

            # 1. 术语一致性检查
            issues.extend(self._check_terminology(source, target, gloss, i))

            # 2. 占位符检查
            issues.extend(self._check_placeholders(source, target, i))

            # 3. 数字保留检查
            issues.extend(self._check_numbers(source, target, i))

        # 计算分数
        score = self._calculate_score(issues, min_len)

        return LQAResult(issues=issues, score=score)

    def _check_terminology(
        self, source: str, target: str, glossary: Glossary, index: int
    ) -> List[LQAIssue]:
        """检查术语一致性"""
        issues: List[LQAIssue] = []
        if not glossary or not glossary.terms:
            return issues

        for term in glossary.terms:
            if not term.source.strip():
                continue

            # 检查源文本中是否包含该术语
            flags = 0 if term.case_sensitive else re.IGNORECASE
            pattern = re.compile(re.escape(term.source), flags)

            if pattern.search(source):
                # 如果源文本包含术语，检查目标是否也包含正确的翻译
                target_pattern = re.compile(re.escape(term.target), flags)
                if not target_pattern.search(target):
                    issues.append(
                        LQAIssue(
                            segment_index=index,
                            issue_type="terminology",
                            severity="warning",
                            message=f"术语 '{term.source}' 未翻译为 '{term.target}'",
                            suggestion=term.target,
                        )
                    )

        return issues

    def _check_placeholders(
        self, source: str, target: str, index: int
    ) -> List[LQAIssue]:
        """检查参数占位符完整性"""
        issues: List[LQAIssue] = []

        # 常见的占位符模式
        placeholder_pattern = re.compile(r'%[sd]|%[0-9]*[df]|%[0-9.]*f|\{\d+\}|\$\d+|\{\{?\w+\}?\}')

        source_placeholders = set(placeholder_pattern.findall(source))
        target_placeholders = set(placeholder_pattern.findall(target))

        missing = source_placeholders - target_placeholders
        if missing:
            issues.append(
                LQAIssue(
                    segment_index=index,
                    issue_type="placeholder",
                    severity="error",
                    message=f"缺少占位符: {missing}",
                )
            )

        return issues

    def _check_numbers(
        self, source: str, target: str, index: int
    ) -> List[LQAIssue]:
        """检查数字是否保留"""
        issues: List[LQAIssue] = []

        # 提取数字（包括小数）
        source_numbers = set(re.findall(r'\d+(?:\.\d+)?', source))
        target_numbers = set(re.findall(r'\d+(?:\.\d+)?', target))

        # 排除明显的年份等常见数字
        source_numbers -= {'20', '202', '2024', '2025', '2026'}

        missing_numbers = source_numbers - target_numbers
        if missing_numbers:
            issues.append(
                LQAIssue(
                    segment_index=index,
                    issue_type="number",
                    severity="warning",
                    message=f"数字丢失: {missing_numbers}",
                )
            )

        return issues

    def _calculate_score(self, issues: List[LQAIssue], segment_count: int) -> float:
        """计算质量分数"""
        if segment_count == 0:
            return 100.0

        # 基础分数
        base_score = 100.0

        # 根据问题严重程度扣分
        for issue in issues:
            if issue.severity == "error":
                base_score -= 5.0
            elif issue.severity == "warning":
                base_score -= 2.0
            else:  # info
                base_score -= 0.5

        return max(0.0, min(100.0, base_score))
