# 贡献指南

欢迎参与 X_Translate（doc_translator）的开发！本文档介绍开发环境、分支与提交约定、编码规范、测试要求。

---

## 1. 本地开发环境

```bash
git clone <repo>
cd X_Translate
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest  # 测试依赖（不打进 runtime）
```

可选：安装 [LibreOffice](https://www.libreoffice.org/) 以启用"打印为 PDF"功能；Windows 用户若已装 MS Office，可 `pip install pywin32` 使用 COM 备选引擎。

## 2. 目录结构速览

请先阅读 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) 了解模块分层。简要：

```
X_Translate/
├── doc_translator/        # 核心包（CLI / pipeline / adapters / 翻译 / PDF 打印）
├── webapp.py              # Flask 网关
├── templates/ static/     # Web 前端
├── office_addin/          # Office Add-in（manifest + 前端）
├── tests/                 # pytest 测试
├── docs/                  # 开发者文档（本指南、API、架构）
├── README.md              # 用户文档
└── .github/workflows/     # CI 配置
```

## 3. 分支与提交

- 主分支：`main`
- 特性分支：`feature/<short-desc>`；修复：`fix/<short-desc>`
- Commit message 推荐使用 [Conventional Commits](https://www.conventionalcommits.org/)：
  - `feat(pdf): add --to-pdf flag to CLI`
  - `fix(adapters): handle empty docx cells`
  - `docs(api): document /api/print_pdf`

## 4. 编码规范

- Python 3.10+；所有新代码使用 `from __future__ import annotations` 并显式类型注解。
- 公开的函数 / 类 / 方法必须有中文或英文 docstring，描述：用途、参数、返回值、抛出的异常。
- 模块顶部必须有简要的模块级 docstring。
- 异常层次尽量使用自定义异常（参考 `pdf_printer.PdfPrinterError`），避免裸 `Exception`。
- 外部命令调用必须设置 `timeout`；Windows 下建议 `creationflags=CREATE_NO_WINDOW`。
- 路径参数优先使用 `pathlib.Path` 而非 `str`。
- 不提交 `local.config.json`（含密钥）、`web_runs/`、`output/`。

## 5. 测试要求

参见 [tests/README.md](tests/README.md)。**任何新增功能必须带测试**，且：

```bash
python -m pytest tests/ -v
```

必须全部通过。

- 单元测试使用 `pytest` + `unittest.mock`；不要依赖真实的 LLM / LibreOffice / Word。
- 涉及 subprocess 的逻辑，mock `subprocess.run`；涉及网络的 LLM 请求，mock `urllib.request`。
- Flask 路由测试使用 `webapp.app.test_client()`（示例见 `tests/test_webapp_pdf.py`）。

## 6. 新增功能时的检查清单

- [ ] 实现代码有 docstring + 类型注解
- [ ] 新增 `tests/test_xxx.py`，覆盖正常路径 + 至少一个边界/失败路径
- [ ] 若新增 HTTP 路由：更新 [docs/API.md](docs/API.md)
- [ ] 若新增 CLI 子命令或参数：更新 [README.md](README.md) 与 `--help` 输出
- [ ] 若涉及模块职责变化：更新 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [ ] 跑 `python -m pytest tests/ -v` 全绿

## 7. 新增 adapter（新文件格式）

1. 在 `doc_translator/adapters/` 新建 `<format>_adapter.py`，继承 `FileAdapter`；
2. 实现 `suffixes`（如 `{".csv"}`）和 `process(input, output, translator, glossary, progress_callback)`；
3. 返回 `FileStats(segments_total, segments_translated, glossary_hits, source_segments, target_segments)`；
4. 在 `pipeline.TranslationPipeline.__init__` 加 `try/except ModuleNotFoundError` 导入分支；
5. 在 `pipeline.SUPPORTED_SUFFIXES` 添加新后缀；
6. 添加 `tests/test_<format>_adapter.py`。

## 8. 新增 LLM 提供方

1. 在 `translator.py` 继承 `BaseBatchTranslator`；
2. 实现 `_call_llm(messages)` 返回字符串；
3. 在 `create_translator()` 的 provider 分支中注册；
4. 测试 mock 该提供方的 HTTP 响应。

## 9. 发布流程（当前由 CI 验证）

现阶段尚无正式打包发布；`.github/workflows/ci.yml` 会自动做语法检查与 Flask 冒烟测试。合并到 `main` 前请确保 CI 绿。

---

有任何问题请开 Issue 或联系维护者。感谢你的贡献！
