"""pdf_printer 模块单元测试。

这些测试通过 mock subprocess 与依赖检测来验证调度逻辑，
无需系统上实际安装 LibreOffice/Word。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from doc_translator import pdf_printer
from doc_translator.pdf_printer import (
    EngineInfo,
    EngineNotAvailableError,
    PdfConversionError,
    UnsupportedFormatError,
    detect_engine,
    print_many,
    print_to_pdf,
)


# --------- detect_engine ---------


def test_detect_engine_prefers_libreoffice(monkeypatch):
    monkeypatch.setattr(pdf_printer, "_find_libreoffice", lambda: "/usr/bin/soffice")
    # 即使 word_com 可用也应返回 libreoffice
    monkeypatch.setattr(pdf_printer, "_is_word_com_available", lambda: True)
    engine = detect_engine()
    assert engine.name == "libreoffice"
    assert engine.executable == "/usr/bin/soffice"


def test_detect_engine_falls_back_to_word_com(monkeypatch):
    monkeypatch.setattr(pdf_printer, "_find_libreoffice", lambda: None)
    monkeypatch.setattr(pdf_printer, "_is_word_com_available", lambda: True)
    engine = detect_engine()
    assert engine.name == "word_com"


def test_detect_engine_raises_when_none(monkeypatch):
    monkeypatch.setattr(pdf_printer, "_find_libreoffice", lambda: None)
    monkeypatch.setattr(pdf_printer, "_is_word_com_available", lambda: False)
    with pytest.raises(EngineNotAvailableError):
        detect_engine()


# --------- print_to_pdf: passthrough ---------


def test_pdf_passthrough_copies_file(tmp_path: Path):
    src = tmp_path / "sample.pdf"
    src.write_bytes(b"%PDF-1.4 fake pdf content")
    out_dir = tmp_path / "out"

    # 即使没有任何引擎也应成功（透传不需要引擎）
    with patch.object(pdf_printer, "detect_engine", side_effect=EngineNotAvailableError("no")):
        result = print_to_pdf(src, out_dir)

    assert result == out_dir / "sample.pdf"
    assert result.read_bytes() == b"%PDF-1.4 fake pdf content"


def test_pdf_passthrough_idempotent_on_same_path(tmp_path: Path):
    """当 input_file 与期望的 output 路径相同时不应自 copy 触发错误。"""
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"x")
    # output_dir 就是 pdf_path 所在目录 => output_file 与 input_file 相同
    result = print_to_pdf(pdf_path, tmp_path)
    assert result == pdf_path
    assert result.read_bytes() == b"x"


# --------- print_to_pdf: unsupported / missing ---------


def test_print_to_pdf_rejects_unsupported_format(tmp_path: Path):
    src = tmp_path / "hello.txt"
    src.write_text("hi")
    with pytest.raises(UnsupportedFormatError):
        print_to_pdf(src, tmp_path / "out")


def test_print_to_pdf_missing_input(tmp_path: Path):
    with pytest.raises(PdfConversionError):
        print_to_pdf(tmp_path / "nope.docx", tmp_path / "out")


# --------- print_to_pdf: libreoffice path (mocked subprocess) ---------


def _make_libreoffice_side_effect(output_dir: Path, input_stem: str, *, returncode: int = 0, stderr: str = ""):
    """构造一个 subprocess.run 的 side_effect：执行时在 output_dir 创建 <stem>.pdf。"""

    def _side_effect(cmd, **_kwargs):
        if returncode == 0:
            (output_dir / f"{input_stem}.pdf").write_bytes(b"%PDF-1.4 generated")
        result = MagicMock()
        result.returncode = returncode
        result.stdout = ""
        result.stderr = stderr
        return result

    return _side_effect


def test_libreoffice_conversion_success(tmp_path: Path):
    src = tmp_path / "demo.docx"
    src.write_bytes(b"FAKE_DOCX")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    engine = EngineInfo(name="libreoffice", executable="/fake/soffice", description="fake")

    with patch("doc_translator.pdf_printer.subprocess.run", side_effect=_make_libreoffice_side_effect(out_dir, "demo")) as run_mock:
        pdf = print_to_pdf(src, out_dir, engine=engine)

    assert pdf == out_dir / "demo.pdf"
    assert pdf.exists()
    # 命令行应当包含 --convert-to pdf 与 input 路径
    called_cmd = run_mock.call_args.args[0]
    assert "--convert-to" in called_cmd
    assert "pdf" in called_cmd
    assert str(src) in called_cmd


def test_libreoffice_conversion_nonzero_returncode(tmp_path: Path):
    src = tmp_path / "demo.docx"
    src.write_bytes(b"x")
    out_dir = tmp_path / "out"
    engine = EngineInfo(name="libreoffice", executable="/fake/soffice")

    with patch(
        "doc_translator.pdf_printer.subprocess.run",
        side_effect=_make_libreoffice_side_effect(out_dir, "demo", returncode=2, stderr="boom"),
    ):
        with pytest.raises(PdfConversionError) as excinfo:
            print_to_pdf(src, out_dir, engine=engine)
    assert "exit=2" in str(excinfo.value)


def test_libreoffice_conversion_timeout(tmp_path: Path):
    src = tmp_path / "demo.docx"
    src.write_bytes(b"x")
    out_dir = tmp_path / "out"
    engine = EngineInfo(name="libreoffice", executable="/fake/soffice")

    with patch(
        "doc_translator.pdf_printer.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="soffice", timeout=5),
    ):
        with pytest.raises(PdfConversionError) as excinfo:
            print_to_pdf(src, out_dir, engine=engine, timeout=5)
    assert "超时" in str(excinfo.value)


def test_libreoffice_missing_output_raises(tmp_path: Path):
    """即使 returncode=0，若未生成 PDF 也应报错。"""
    src = tmp_path / "demo.docx"
    src.write_bytes(b"x")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    engine = EngineInfo(name="libreoffice", executable="/fake/soffice")

    def _side_effect(cmd, **_kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = "ok"
        result.stderr = ""
        return result  # 不创建 pdf

    with patch("doc_translator.pdf_printer.subprocess.run", side_effect=_side_effect):
        with pytest.raises(PdfConversionError) as excinfo:
            print_to_pdf(src, out_dir, engine=engine)
    assert "未生成 PDF" in str(excinfo.value)


# --------- print_many ---------


def test_print_many_aggregates_success_and_failure(tmp_path: Path):
    good = tmp_path / "a.docx"
    good.write_bytes(b"good")
    bad = tmp_path / "b.txt"
    bad.write_text("unsupported")
    passthrough = tmp_path / "c.pdf"
    passthrough.write_bytes(b"%PDF already")

    out_dir = tmp_path / "out"
    engine = EngineInfo(name="libreoffice", executable="/fake/soffice")

    with patch(
        "doc_translator.pdf_printer.subprocess.run",
        side_effect=_make_libreoffice_side_effect(out_dir, "a"),
    ):
        results = print_many([good, bad, passthrough], out_dir, engine=engine)

    assert len(results) == 3
    src_to_result = {src.name: (pdf, err) for src, pdf, err in results}

    assert src_to_result["a.docx"][0] is not None
    assert src_to_result["a.docx"][1] is None

    assert src_to_result["b.txt"][0] is None
    assert src_to_result["b.txt"][1] is not None
    assert "不支持" in src_to_result["b.txt"][1]

    assert src_to_result["c.pdf"][0] is not None
    assert src_to_result["c.pdf"][1] is None
