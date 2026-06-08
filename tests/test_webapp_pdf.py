"""Flask PDF 接口的集成测试（使用 Flask test client + mock 的引擎）。"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pytest

import webapp
from doc_translator.pdf_printer import EngineInfo, EngineNotAvailableError


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    # 把 PDF 根目录指向 tmp 避免污染
    monkeypatch.setattr(webapp, "pdf_root", tmp_path / "_pdf_prints", raising=True)
    (tmp_path / "_pdf_prints").mkdir()
    webapp.app.config.update(TESTING=True)
    with webapp.app.test_client() as c:
        yield c


def _fake_libreoffice_side_effect(output_dir_resolver):
    """output_dir_resolver(cmd) -> Path: 把 --outdir 后面的路径找出来。"""
    from unittest.mock import MagicMock

    def _side_effect(cmd, **_kwargs):
        outdir = Path(cmd[cmd.index("--outdir") + 1])
        input_path = Path(cmd[-1])
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / f"{input_path.stem}.pdf").write_bytes(b"%PDF-1.4 fake")
        res = MagicMock()
        res.returncode = 0
        res.stdout = ""
        res.stderr = ""
        return res

    return _side_effect


def test_get_pdf_engine_available(client):
    fake_engine = EngineInfo(name="libreoffice", executable="/fake/soffice", description="LibreOffice (fake)")
    with patch("webapp.detect_engine", return_value=fake_engine):
        resp = client.get("/api/pdf/engine")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["available"] is True
    assert data["engine"] == "libreoffice"


def test_get_pdf_engine_unavailable(client):
    with patch("webapp.detect_engine", side_effect=EngineNotAvailableError("没装")):
        resp = client.get("/api/pdf/engine")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["available"] is False
    assert "没装" in data["error"]


def test_print_pdf_requires_files(client):
    resp = client.post("/api/print_pdf", data={})
    assert resp.status_code == 400
    assert resp.get_json()["error"]


def test_print_pdf_returns_engine_error_when_unavailable(client):
    with patch("webapp.detect_engine", side_effect=EngineNotAvailableError("no engine")):
        data = {"files": (io.BytesIO(b"FAKE"), "x.docx")}
        resp = client.post("/api/print_pdf", data=data, content_type="multipart/form-data")
    assert resp.status_code == 503


def test_print_pdf_single_file_returns_pdf(client):
    fake_engine = EngineInfo(name="libreoffice", executable="/fake/soffice", description="fake")
    with patch("webapp.detect_engine", return_value=fake_engine), patch(
        "doc_translator.pdf_printer.subprocess.run", side_effect=_fake_libreoffice_side_effect(None)
    ):
        data = {"files": (io.BytesIO(b"FAKE_DOCX_BYTES"), "demo.docx")}
        resp = client.post("/api/print_pdf", data=data, content_type="multipart/form-data")

    assert resp.status_code == 200
    assert resp.content_type.startswith("application/pdf")
    assert resp.headers.get("X-PDF-Engine") == "libreoffice"
    # Content-Disposition 应指向 demo.pdf
    disposition = resp.headers.get("Content-Disposition", "")
    assert "demo.pdf" in disposition


def test_print_pdf_multiple_files_returns_zip(client):
    fake_engine = EngineInfo(name="libreoffice", executable="/fake/soffice", description="fake")
    with patch("webapp.detect_engine", return_value=fake_engine), patch(
        "doc_translator.pdf_printer.subprocess.run", side_effect=_fake_libreoffice_side_effect(None)
    ):
        data = {
            "files": [
                (io.BytesIO(b"A"), "a.docx"),
                (io.BytesIO(b"B"), "b.docx"),
            ]
        }
        resp = client.post("/api/print_pdf", data=data, content_type="multipart/form-data")

    assert resp.status_code == 200
    assert resp.content_type.startswith("application/zip")


def test_print_pdf_json_returns_structured_results(client):
    fake_engine = EngineInfo(name="libreoffice", executable="/fake/soffice", description="fake")
    with patch("webapp.detect_engine", return_value=fake_engine), patch(
        "doc_translator.pdf_printer.subprocess.run", side_effect=_fake_libreoffice_side_effect(None)
    ):
        data = {
            "files": [
                (io.BytesIO(b"A"), "a.docx"),
                (io.BytesIO(b"%PDF-1.4 already"), "b.pdf"),
            ]
        }
        resp = client.post("/api/print_pdf/json", data=data, content_type="multipart/form-data")

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["engine"] == "libreoffice"
    assert len(payload["results"]) == 2
    statuses = {item["input"]: item["status"] for item in payload["results"]}
    assert statuses["a.docx"] == "success"
    assert statuses["b.pdf"] == "success"

    # 下载 URL 应可用
    task_id = payload["task_id"]
    a_item = next(item for item in payload["results"] if item["input"] == "a.docx")
    download_resp = client.get(a_item["download_url"])
    assert download_resp.status_code == 200
    assert download_resp.content_type.startswith("application/pdf")


def test_print_pdf_download_rejects_path_traversal(client):
    # 任何 task_id/文件名都应被当作普通文件名处理
    resp = client.get("/api/print_pdf/abc/download/..%2F..%2Fetc%2Fpasswd")
    assert resp.status_code == 404
