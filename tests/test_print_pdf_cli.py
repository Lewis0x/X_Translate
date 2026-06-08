"""独立 PDF 打印 CLI 测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from doc_translator import print_pdf_cli
from doc_translator.pdf_printer import EngineInfo, EngineNotAvailableError


def _fake_libreoffice_run(cmd, **_kwargs):
    outdir = Path(cmd[cmd.index("--outdir") + 1])
    input_path = Path(cmd[-1])
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"{input_path.stem}.pdf").write_bytes(b"%PDF-1.4 fake")
    res = MagicMock()
    res.returncode = 0
    res.stdout = ""
    res.stderr = ""
    return res


def test_collect_files_filters_by_suffix(tmp_path: Path):
    (tmp_path / "a.docx").write_bytes(b"x")
    (tmp_path / "b.xlsx").write_bytes(b"x")
    (tmp_path / "c.txt").write_text("ignore")
    (tmp_path / "d.pdf").write_bytes(b"%PDF")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "e.docx").write_bytes(b"x")

    files = print_pdf_cli.collect_files([str(tmp_path)], recursive=False)
    names = {f.name for f in files}
    # 非递归：不应该收集到 sub/e.docx
    assert names == {"a.docx", "b.xlsx", "d.pdf"}

    files_r = print_pdf_cli.collect_files([str(tmp_path)], recursive=True)
    names_r = {f.name for f in files_r}
    assert "e.docx" in names_r


def test_collect_files_accepts_individual_files(tmp_path: Path):
    f1 = tmp_path / "a.docx"
    f1.write_bytes(b"x")
    f2 = tmp_path / "b.pdf"
    f2.write_bytes(b"%PDF")
    bogus = tmp_path / "nope.docx"  # 不存在

    files = print_pdf_cli.collect_files([str(f1), str(f2), str(bogus)], recursive=False)
    assert [p.name for p in files] == ["a.docx", "b.pdf"]


def test_main_dry_run_lists_files_without_engine(tmp_path: Path, capsys):
    (tmp_path / "a.docx").write_bytes(b"x")
    out = tmp_path / "out"

    rc = print_pdf_cli.main(
        [
            "--input",
            str(tmp_path),
            "--output-dir",
            str(out),
            "--dry-run",
        ]
    )
    captured = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN" in captured
    assert "a.docx" in captured
    # 不应实际生成 pdf
    assert not out.exists() or not any(out.iterdir())


def test_main_exits_2_when_no_files(tmp_path: Path):
    rc = print_pdf_cli.main(["--input", str(tmp_path), "--output-dir", str(tmp_path / "out")])
    assert rc == 2


def test_main_exits_3_when_engine_unavailable(tmp_path: Path):
    (tmp_path / "a.docx").write_bytes(b"x")
    with patch("doc_translator.print_pdf_cli.detect_engine", side_effect=EngineNotAvailableError("no")):
        rc = print_pdf_cli.main(
            [
                "--input",
                str(tmp_path),
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
    assert rc == 3


def test_main_success_returns_0(tmp_path: Path):
    (tmp_path / "a.docx").write_bytes(b"x")
    out = tmp_path / "out"

    fake_engine = EngineInfo(name="libreoffice", executable="/fake/soffice", description="fake")
    with patch("doc_translator.print_pdf_cli._resolve_engine", return_value=fake_engine), patch(
        "doc_translator.pdf_printer.subprocess.run", side_effect=_fake_libreoffice_run
    ):
        rc = print_pdf_cli.main(
            [
                "--input",
                str(tmp_path),
                "--output-dir",
                str(out),
            ]
        )

    assert rc == 0
    assert (out / "a.pdf").exists()


def test_main_returns_1_when_any_failure(tmp_path: Path):
    good = tmp_path / "a.docx"
    good.write_bytes(b"x")
    bad = tmp_path / "b.xlsx"  # 会在 subprocess 中失败
    bad.write_bytes(b"x")
    out = tmp_path / "out"

    fake_engine = EngineInfo(name="libreoffice", executable="/fake/soffice")

    def _selective_run(cmd, **kwargs):
        input_path = Path(cmd[-1])
        if input_path.name == "b.xlsx":
            res = MagicMock()
            res.returncode = 1
            res.stdout = ""
            res.stderr = "boom"
            return res
        return _fake_libreoffice_run(cmd, **kwargs)

    with patch("doc_translator.print_pdf_cli._resolve_engine", return_value=fake_engine), patch(
        "doc_translator.pdf_printer.subprocess.run", side_effect=_selective_run
    ):
        rc = print_pdf_cli.main(["--input", str(tmp_path), "--output-dir", str(out)])

    assert rc == 1
    assert (out / "a.pdf").exists()
    assert not (out / "b.pdf").exists()


def test_resolve_engine_explicit_libreoffice_missing(monkeypatch):
    monkeypatch.setattr("doc_translator.pdf_printer._find_libreoffice", lambda: None)
    with pytest.raises(EngineNotAvailableError):
        print_pdf_cli._resolve_engine("libreoffice")


def test_resolve_engine_auto_delegates(monkeypatch):
    fake = EngineInfo(name="libreoffice", executable="/x/soffice")
    monkeypatch.setattr("doc_translator.print_pdf_cli.detect_engine", lambda: fake)
    assert print_pdf_cli._resolve_engine("auto") is fake
