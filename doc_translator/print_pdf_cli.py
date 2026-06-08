"""独立的 PDF 打印命令行入口。

用于在本地批量把 ``.docx`` / ``.xlsx`` / ``.pdf`` 文件打印为 PDF，
不需要启动 Flask Web 服务。

用法示例::

    # 打印单个文件
    python -m doc_translator.print_pdf_cli --input demo.docx --output-dir ./pdf_out

    # 打印目录下所有支持的文件（递归）
    python -m doc_translator.print_pdf_cli --input ./docs --output-dir ./pdf_out --recursive

    # 指定引擎 & 超时
    python -m doc_translator.print_pdf_cli -i a.docx -i b.xlsx -o ./out \\
        --engine libreoffice --timeout 300

退出码：
  0 — 全部成功
  1 — 至少一个失败
  2 — 参数错误 / 无可处理文件
  3 — 引擎不可用
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Iterable, List

from doc_translator.pdf_printer import (
    EngineInfo,
    EngineNotAvailableError,
    PdfPrinterError,
    detect_engine,
    print_many,
)

# 所有这些后缀在 pdf_printer 中都支持
_COLLECTABLE_SUFFIXES = {
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".pptx",
    ".ppt",
    ".odt",
    ".ods",
    ".odp",
    ".rtf",
    ".pdf",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m doc_translator.print_pdf_cli",
        description="批量把 Office 文档打印为 PDF（.pdf 文件直接透传）。",
    )
    parser.add_argument(
        "--input",
        "-i",
        action="append",
        required=True,
        help="输入文件或目录；可重复传入多个 -i。",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        required=True,
        help="PDF 输出目录（不存在会自动创建）。",
    )
    parser.add_argument(
        "--recursive",
        "-r",
        action="store_true",
        help="对于目录输入递归扫描（默认仅扫描一层顶层文件）。",
    )
    parser.add_argument(
        "--engine",
        choices=["auto", "libreoffice", "word_com"],
        default="auto",
        help="指定转换引擎，默认 auto（优先 LibreOffice，回退 Word COM）。",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="单文件转换超时（秒），默认 180。",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="输出详细日志。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅列出将要处理的文件，不实际执行转换。",
    )
    return parser


def collect_files(inputs: Iterable[str], *, recursive: bool) -> List[Path]:
    """收集所有可处理的文件路径（去重、排序）。"""
    collected: list[Path] = []
    for raw in inputs:
        path = Path(raw)
        if path.is_file():
            if path.suffix.lower() in _COLLECTABLE_SUFFIXES:
                collected.append(path)
            continue
        if path.is_dir():
            iterator = path.rglob("*") if recursive else path.iterdir()
            for child in iterator:
                if child.is_file() and child.suffix.lower() in _COLLECTABLE_SUFFIXES:
                    collected.append(child)
            continue
        logging.warning("跳过：不存在或不是文件/目录: %s", raw)
    return sorted(set(collected))


def _resolve_engine(engine_name: str) -> EngineInfo:
    """按 ``--engine`` 选项解析引擎。``auto`` 调用 :func:`detect_engine`。"""
    if engine_name == "auto":
        return detect_engine()
    if engine_name == "libreoffice":
        from doc_translator.pdf_printer import _find_libreoffice  # type: ignore

        soffice = _find_libreoffice()
        if not soffice:
            raise EngineNotAvailableError("未在系统中找到 LibreOffice 可执行文件。")
        return EngineInfo(name="libreoffice", executable=soffice, description=f"LibreOffice ({soffice})")
    if engine_name == "word_com":
        from doc_translator.pdf_printer import _is_word_com_available  # type: ignore

        if not _is_word_com_available():
            raise EngineNotAvailableError("Word COM 不可用（需要 Windows + MS Office + pywin32）。")
        return EngineInfo(name="word_com", description="Microsoft Word (COM)")
    raise EngineNotAvailableError(f"未知引擎: {engine_name}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    files = collect_files(args.input, recursive=args.recursive)
    if not files:
        logging.error("未找到可处理文件。支持的后缀: %s", sorted(_COLLECTABLE_SUFFIXES))
        return 2

    logging.info("共收集到 %d 个文件", len(files))
    for f in files:
        logging.debug("  - %s", f)

    if args.dry_run:
        print(f"[DRY-RUN] 将处理 {len(files)} 个文件，输出目录: {args.output_dir}")
        for f in files:
            print(f"  {f}")
        return 0

    try:
        engine = _resolve_engine(args.engine)
    except EngineNotAvailableError as exc:
        logging.error("引擎不可用: %s", exc)
        return 3

    logging.info("使用引擎: %s", engine.description or engine.name)

    output_dir = Path(args.output_dir)
    try:
        results = print_many(files, output_dir, engine=engine, timeout=args.timeout)
    except PdfPrinterError as exc:
        logging.error("批量打印失败: %s", exc)
        return 1

    ok = sum(1 for _src, pdf, err in results if pdf and not err)
    bad = len(results) - ok

    print("")
    print(f"完成：{ok} 成功 / {bad} 失败 / 共 {len(results)}")
    print(f"输出目录: {output_dir.resolve()}")
    if bad:
        print("\n失败明细:")
        for src, _pdf, err in results:
            if err:
                print(f"  ✗ {src.name}: {err}")

    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
