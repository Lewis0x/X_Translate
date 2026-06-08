"""翻译 CLI 的 ``--to-pdf`` 开关测试。

只测试 ``_run_post_translation_pdf`` 与 argparse 解析，
不实际调用翻译流程（那部分依赖 LLM）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

from doc_translator import cli
from doc_translator.pdf_printer import EngineInfo, EngineNotAvailableError
from doc_translator.reporting import FileResult, RunReport


def test_parser_accepts_to_pdf_flags():
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "--input",
            "x.docx",
            "--target",
            "en",
            "--to-pdf",
            "--pdf-engine",
            "libreoffice",
            "--pdf-timeout",
            "60",
        ]
    )
    assert args.to_pdf is True
    assert args.pdf_engine == "libreoffice"
    assert args.pdf_timeout == 60


def test_parser_to_pdf_defaults():
    parser = cli.build_parser()
    args = parser.parse_args(["--input", "x.docx", "--target", "en"])
    assert args.to_pdf is False
    assert args.pdf_engine == "auto"
    assert args.pdf_timeout == 180


def _fake_libreoffice_run(cmd, **_kwargs):
    outdir = Path(cmd[cmd.index("--outdir") + 1])
    input_path = Path(cmd[-1])
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"{input_path.stem}.pdf").write_bytes(b"%PDF-1.4")
    res = MagicMock()
    res.returncode = 0
    res.stdout = ""
    res.stderr = ""
    return res


def test_run_post_translation_pdf_generates_both(tmp_path: Path):
    # 准备一个模拟的 "翻译结束" 的目录结构
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    original = input_dir / "a.docx"
    original.write_bytes(b"x")

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    translated = output_dir / "a_en.docx"
    translated.write_bytes(b"x")

    report = RunReport(source_lang="zh", target_lang="en", model="fake")
    report.add_result(FileResult(input_path=str(original), output_path=str(translated), status="success"))

    logger = logging.getLogger("test_cli_to_pdf")
    fake_engine = EngineInfo(name="libreoffice", executable="/fake/soffice", description="fake")

    with patch("doc_translator.print_pdf_cli._resolve_engine", return_value=fake_engine), patch(
        "doc_translator.pdf_printer.subprocess.run", side_effect=_fake_libreoffice_run
    ):
        cli._run_post_translation_pdf(
            files=[original],
            output_dir=output_dir,
            report=report,
            logger=logger,
            engine_name="auto",
            timeout=30,
        )

    assert (output_dir / "pdf" / "original" / "a.pdf").exists()
    assert (output_dir / "pdf" / "translated" / "a_en.pdf").exists()


def test_run_post_translation_pdf_skips_failed_translations(tmp_path: Path):
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    original = input_dir / "a.docx"
    original.write_bytes(b"x")

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    # 一个成功 + 一个失败
    translated_ok = output_dir / "ok_en.docx"
    translated_ok.write_bytes(b"x")

    report = RunReport(source_lang="zh", target_lang="en", model="fake")
    report.add_result(FileResult(input_path=str(original), output_path=str(translated_ok), status="success"))
    report.add_result(
        FileResult(
            input_path=str(original),
            output_path=str(output_dir / "fail_en.docx"),  # 文件不存在
            status="failed",
        )
    )

    logger = logging.getLogger("test_cli_to_pdf2")
    fake_engine = EngineInfo(name="libreoffice", executable="/fake/soffice")

    with patch("doc_translator.print_pdf_cli._resolve_engine", return_value=fake_engine), patch(
        "doc_translator.pdf_printer.subprocess.run", side_effect=_fake_libreoffice_run
    ):
        cli._run_post_translation_pdf(
            files=[original],
            output_dir=output_dir,
            report=report,
            logger=logger,
            engine_name="auto",
            timeout=30,
        )

    # 失败那条不应该被打印
    assert (output_dir / "pdf" / "translated" / "ok_en.pdf").exists()
    assert not (output_dir / "pdf" / "translated" / "fail_en.pdf").exists()


def test_run_post_translation_pdf_gracefully_handles_missing_engine(tmp_path: Path, caplog):
    original = tmp_path / "a.docx"
    original.write_bytes(b"x")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    report = RunReport(source_lang="zh", target_lang="en", model="fake")
    logger = logging.getLogger("test_cli_to_pdf3")

    with patch("doc_translator.print_pdf_cli._resolve_engine", side_effect=EngineNotAvailableError("no engine")):
        with caplog.at_level(logging.ERROR):
            # 不应抛异常；只记录日志
            cli._run_post_translation_pdf(
                files=[original],
                output_dir=output_dir,
                report=report,
                logger=logger,
                engine_name="auto",
                timeout=30,
            )

    # 没有生成任何 pdf 目录
    assert not (output_dir / "pdf").exists()
