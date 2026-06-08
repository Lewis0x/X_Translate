# 测试说明

所有测试基于 [pytest](https://docs.pytest.org/)，位于 `tests/` 目录。它们只使用本地 mock，**不会**调用真实的 LLM / LibreOffice / Word，可在 CI 中安全运行。

## 1. 安装依赖

```bash
pip install -r requirements.txt
pip install pytest
```

## 2. 运行

```bash
# 全量
python -m pytest tests/ -v

# 仅运行某个文件
python -m pytest tests/test_pdf_printer.py -v

# 带简短输出
python -m pytest tests/

# 失败时停止
python -m pytest tests/ -x
```

## 3. 测试清单

| 文件 | 覆盖范围 |
|------|----------|
| `test_pdf_printer.py` | `doc_translator.pdf_printer` 模块：引擎自动检测、PDF 透传、subprocess mock 的 LibreOffice 成功/失败/超时/产物缺失、批量结果聚合 |
| `test_webapp_pdf.py` | Flask PDF 接口：`/api/pdf/engine`、`/api/print_pdf`（单/多文件，zip）、`/api/print_pdf/json`（结构化响应）、下载路径穿越防护 |
| `test_print_pdf_cli.py` | 独立 PDF 打印 CLI：文件收集（含递归）、dry-run、退出码、引擎选择 |
| `test_cli_to_pdf.py` | 翻译 CLI 的 `--to-pdf` 开关：参数解析、`_run_post_translation_pdf()` 流程、引擎不可用时降级 |

## 4. 常用 mock 模式

**mock LibreOffice**：所有需要真正调用 `soffice` 的测试都 mock `doc_translator.pdf_printer.subprocess.run`。参考 `tests/test_pdf_printer.py::_make_libreoffice_side_effect`。

```python
def _fake_run(cmd, **_kwargs):
    outdir = Path(cmd[cmd.index("--outdir") + 1])
    input_path = Path(cmd[-1])
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"{input_path.stem}.pdf").write_bytes(b"%PDF-1.4 fake")
    res = MagicMock()
    res.returncode = 0
    res.stdout = ""
    res.stderr = ""
    return res

with patch("doc_translator.pdf_printer.subprocess.run", side_effect=_fake_run):
    ...
```

**mock 引擎检测**：

```python
from doc_translator.pdf_printer import EngineInfo
fake_engine = EngineInfo(name="libreoffice", executable="/fake/soffice", description="fake")
with patch("webapp.detect_engine", return_value=fake_engine):
    ...
```

**mock Flask 路由**：

```python
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "pdf_root", tmp_path / "_pdf_prints", raising=True)
    (tmp_path / "_pdf_prints").mkdir()
    webapp.app.config.update(TESTING=True)
    with webapp.app.test_client() as c:
        yield c
```

## 5. CI

项目的 CI 工作流定义于 `.github/workflows/ci.yml`（按需查看）。目前主要做：
- Python 语法检查（`py_compile`）
- 本地配置样例的 JSON 结构校验
- Flask 网关冒烟测试（能否成功 import 并响应 `/`）

如果你在 CI 中新增一个 pytest 步骤（推荐），参考示例：

```yaml
- name: Run pytest
  run: |
    pip install -r requirements.txt
    pip install pytest
    python -m pytest tests/ -v
```

## 6. 新增测试时的约定

1. 文件命名：`test_<模块名>.py`；类名 `TestXxx`，函数名 `test_xxx_<场景>`。
2. **不要依赖真实文件**：用 pytest 的 `tmp_path` fixture 构造临时目录。
3. **不要依赖网络**：所有 LLM 调用必须 mock。
4. 一个 test 聚焦一个行为；多场景请拆成多个 test（便于定位失败）。
5. 失败用例优先：为每个新功能至少写一个 happy path + 一个失败/边界 case。

详见 [CONTRIBUTING.md](../CONTRIBUTING.md) 第 5 节。
