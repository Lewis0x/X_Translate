"""PDF 打印模块 —— 将 .docx / .xlsx 等 Office 文档转换为 PDF。

支持的转换引擎（按优先级自动检测）：
    1. LibreOffice (``soffice`` / ``libreoffice``) —— 跨平台、无需 MS Office
    2. Microsoft Word COM (Windows 专用，需已安装 MS Office 并装有 pywin32)

对于 ``.pdf`` 文件采取直接透传（复制）策略。

典型用法::

    from doc_translator.pdf_printer import print_to_pdf, detect_engine

    engine = detect_engine()
    out_path = print_to_pdf(Path("demo.docx"), Path("output"))

模块对未知/不支持的文件类型抛出 :class:`UnsupportedFormatError`，
对转换失败抛出 :class:`PdfConversionError`。
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 支持直接转为 PDF 的后缀
_CONVERTIBLE_SUFFIXES = {".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".odt", ".ods", ".odp", ".rtf"}
# 直接透传的后缀（已经是 PDF）
_PASSTHROUGH_SUFFIXES = {".pdf"}


class PdfPrinterError(Exception):
    """PDF 打印模块的基类异常。"""


class UnsupportedFormatError(PdfPrinterError):
    """不支持的文件格式。"""


class EngineNotAvailableError(PdfPrinterError):
    """没有可用的 PDF 转换引擎。"""


class PdfConversionError(PdfPrinterError):
    """转换过程中发生错误。"""


@dataclass(frozen=True)
class EngineInfo:
    """可用引擎的描述。"""

    name: str  # 引擎标识："libreoffice" / "word_com"
    executable: Optional[str] = None  # LibreOffice 下为可执行文件路径
    description: str = ""


def _find_libreoffice() -> Optional[str]:
    """在 PATH 中查找 LibreOffice 可执行文件，找到则返回其绝对路径。"""
    candidates = ["soffice", "libreoffice"]
    if platform.system() == "Windows":
        # Windows 安装后 soffice.exe 通常不在 PATH，尝试常见安装路径
        candidates = ["soffice.exe", "soffice", "libreoffice.exe", "libreoffice"]

    for name in candidates:
        found = shutil.which(name)
        if found:
            return found

    # Windows 常见安装路径兜底
    if platform.system() == "Windows":
        common_paths = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
        for path in common_paths:
            if os.path.isfile(path):
                return path

    return None


def _is_word_com_available() -> bool:
    """检查 Windows 下是否可以通过 COM 调用 Word。"""
    if platform.system() != "Windows":
        return False
    try:
        import win32com.client  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


def detect_engine() -> EngineInfo:
    """自动检测可用的 PDF 转换引擎。

    优先返回 LibreOffice；在 Windows 上若 LibreOffice 不可用，则回退到 Word COM。

    :raises EngineNotAvailableError: 若没有任何可用引擎。
    """
    soffice = _find_libreoffice()
    if soffice:
        return EngineInfo(name="libreoffice", executable=soffice, description=f"LibreOffice ({soffice})")

    if _is_word_com_available():
        return EngineInfo(name="word_com", description="Microsoft Word (COM, Windows only)")

    raise EngineNotAvailableError(
        "未检测到任何 PDF 转换引擎。请安装 LibreOffice (推荐) "
        "或在 Windows 上安装 Microsoft Office + pywin32。",
    )


def _run_libreoffice(soffice: str, input_file: Path, output_dir: Path, timeout: int) -> Path:
    """调用 LibreOffice 将 ``input_file`` 转为 PDF，输出到 ``output_dir``。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        soffice,
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(input_file),
    ]
    logger.info("LibreOffice 转换命令: %s", " ".join(cmd))

    # 隐藏 Windows 控制台窗口
    creationflags = 0
    if platform.system() == "Windows":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired as exc:
        raise PdfConversionError(f"LibreOffice 转换超时（>{timeout}s）: {input_file.name}") from exc
    except FileNotFoundError as exc:
        raise PdfConversionError(f"LibreOffice 可执行文件不存在: {soffice}") from exc

    if result.returncode != 0:
        raise PdfConversionError(
            f"LibreOffice 转换失败 (exit={result.returncode})\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

    generated = output_dir / f"{input_file.stem}.pdf"
    if not generated.exists():
        raise PdfConversionError(
            f"LibreOffice 转换结束但未生成 PDF: 期望 {generated}\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
    return generated


def _run_word_com(input_file: Path, output_file: Path, timeout: int) -> Path:  # noqa: ARG001
    """在 Windows 下通过 COM 调用 Word 将文档另存为 PDF。

    ``timeout`` 目前未使用，保留以便未来接入异步超时。
    """
    if platform.system() != "Windows":
        raise PdfConversionError("Word COM 仅在 Windows 上可用。")

    try:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore
    except ImportError as exc:
        raise PdfConversionError("未安装 pywin32，无法使用 Word COM。") from exc

    suffix = input_file.suffix.lower()
    if suffix in {".docx", ".doc", ".rtf", ".odt"}:
        app_name = "Word.Application"
        save_format = 17  # wdFormatPDF
    elif suffix in {".xlsx", ".xls", ".ods"}:
        app_name = "Excel.Application"
        save_format = 57  # xlTypePDF / xlFixedFormatTypePDF = 0 via ExportAsFixedFormat
    elif suffix in {".pptx", ".ppt", ".odp"}:
        app_name = "PowerPoint.Application"
        save_format = 32  # ppSaveAsPDF
    else:
        raise UnsupportedFormatError(f"Word COM 不支持该格式: {suffix}")

    pythoncom.CoInitialize()
    try:
        app = win32com.client.DispatchEx(app_name)
        try:
            if app_name == "Excel.Application":
                app.Visible = False
                app.DisplayAlerts = False
                wb = app.Workbooks.Open(str(input_file), ReadOnly=True)
                try:
                    wb.ExportAsFixedFormat(0, str(output_file))  # 0 = xlTypePDF
                finally:
                    wb.Close(SaveChanges=False)
            elif app_name == "PowerPoint.Application":
                # PowerPoint 在无窗口模式下无法 Open，需要 WithWindow=False 参数
                pres = app.Presentations.Open(str(input_file), WithWindow=False, ReadOnly=True)
                try:
                    pres.SaveAs(str(output_file), save_format)
                finally:
                    pres.Close()
            else:  # Word
                app.Visible = False
                doc = app.Documents.Open(str(input_file), ReadOnly=True)
                try:
                    doc.SaveAs(str(output_file), FileFormat=save_format)
                finally:
                    doc.Close(SaveChanges=False)
        finally:
            try:
                app.Quit()
            except Exception:  # noqa: BLE001
                pass
    finally:
        pythoncom.CoUninitialize()

    if not output_file.exists():
        raise PdfConversionError(f"Word COM 转换完成但未生成文件: {output_file}")
    return output_file


def print_to_pdf(
    input_file: Path,
    output_dir: Path,
    engine: Optional[EngineInfo] = None,
    timeout: int = 180,
) -> Path:
    """将单个文档转换为 PDF。

    :param input_file: 输入文件路径。
    :param output_dir: PDF 输出目录；不存在则会被创建。
    :param engine: 可选的引擎描述；为 ``None`` 时自动检测。
    :param timeout: 外部命令执行超时（秒）。
    :return: 生成的 PDF 文件路径。

    :raises UnsupportedFormatError: 文件类型不支持。
    :raises EngineNotAvailableError: 没有可用引擎。
    :raises PdfConversionError: 其他转换失败。
    """
    input_file = Path(input_file)
    output_dir = Path(output_dir)

    if not input_file.exists():
        raise PdfConversionError(f"输入文件不存在: {input_file}")

    suffix = input_file.suffix.lower()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{input_file.stem}.pdf"

    # PDF 透传
    if suffix in _PASSTHROUGH_SUFFIXES:
        if input_file.resolve() != output_file.resolve():
            shutil.copy2(input_file, output_file)
        logger.info("PDF 透传: %s -> %s", input_file, output_file)
        return output_file

    if suffix not in _CONVERTIBLE_SUFFIXES:
        raise UnsupportedFormatError(
            f"不支持转换为 PDF 的格式: {suffix}（支持: {sorted(_CONVERTIBLE_SUFFIXES | _PASSTHROUGH_SUFFIXES)}）"
        )

    chosen = engine or detect_engine()
    logger.info("使用引擎: %s", chosen.description or chosen.name)

    if chosen.name == "libreoffice":
        if not chosen.executable:
            raise PdfConversionError("LibreOffice 引擎缺少 executable 路径。")
        return _run_libreoffice(chosen.executable, input_file, output_dir, timeout=timeout)

    if chosen.name == "word_com":
        return _run_word_com(input_file, output_file, timeout=timeout)

    raise PdfConversionError(f"未知引擎: {chosen.name}")


def print_many(
    input_files: list[Path],
    output_dir: Path,
    engine: Optional[EngineInfo] = None,
    timeout: int = 180,
) -> list[tuple[Path, Optional[Path], Optional[str]]]:
    """批量转换多个文件为 PDF。

    返回 ``[(input_file, output_pdf_or_None, error_or_None), ...]`` 三元组列表。
    转换失败的条目 ``output_pdf`` 为 ``None``，``error`` 为错误描述。
    """
    chosen = engine or detect_engine()
    results: list[tuple[Path, Optional[Path], Optional[str]]] = []
    for input_file in input_files:
        try:
            pdf = print_to_pdf(Path(input_file), output_dir, engine=chosen, timeout=timeout)
            results.append((Path(input_file), pdf, None))
        except PdfPrinterError as exc:
            logger.exception("转换失败: %s", input_file)
            results.append((Path(input_file), None, str(exc)))
    return results
