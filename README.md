# 文档翻译工具（Doc Translator）

基于需求文档实现的命令行翻译工具，支持：

- `.docx`：复制原文档并仅替换文本节点（`w:t`）
- `.xlsx`：遍历字符串单元格并替换文本（保留单元格样式）
- `.pdf`（文本型）：按文本块覆盖翻译（扫描件不支持）
- 术语表（`CSV/JSON`）：支持锁定词与强制替换
- 批量处理：文件/目录均可
- 日志与报告：输出运行日志与 JSON 摘要
- Web 前端：上传文件、配置参数、实时查看任务进度并下载结果
- **打印为 PDF**：将 `.docx`/`.xlsx` 打印为 PDF（`.pdf` 透传），可独立使用或对翻译结果一键打印。
  需要本机安装 [LibreOffice](https://www.libreoffice.org/)（推荐，跨平台）；Windows 下若已安装 MS Office + `pywin32` 也会自动回退使用 Word/Excel COM。

## 文档导航

- 本文档 (README.md)：用户使用指南 — 安装、配置、CLI、Web。
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)：架构与模块职责。
- [docs/API.md](docs/API.md)：HTTP API 参考。
- [docs/PDF_PRINTING.md](docs/PDF_PRINTING.md)：打印为 PDF 专题（引擎安装、三种用法、故障排查）。
- [docs/FEATURES.md](docs/FEATURES.md)：高级功能（LQA、翻译记忆、多模型对比）使用与 Python API。
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)：常见错误与排查手册。
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)：生产部署、反向代理、Docker、systemd。
- [CONTRIBUTING.md](CONTRIBUTING.md)：贡献流程、编码规范、新增 adapter/LLM 指南。
- [tests/README.md](tests/README.md)：测试说明与 mock 约定。

## 1. 安装

```bash
git clone <repo-url>
cd X_Translate
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

> 如需使用"打印为 PDF"功能，另需本机安装 [LibreOffice](https://www.libreoffice.org/)；Windows 用户若已装 MS Office，也可额外 `pip install pywin32` 启用 COM 备选引擎。具体见 [docs/PDF_PRINTING.md](docs/PDF_PRINTING.md)。

## 2. 本地配置（推荐）

复制示例配置并填写密钥：

```bash
copy local.config.sample.json local.config.json
```

`local.config.json` 示例：

```json
{
	"LLM_PROVIDER": "openai",
	"OPEN_API_KEY": "sk-xxxx",
	"LLM_MODEL": "gpt-4.1-mini",
	"TRANSLATION_DOMAIN": "general",
	"OPENAI_BASE_URL": "https://api.openai.com/v1",
	"OPENAI_ENDPOINT": "/chat/completions",
	"LLM_BASE_URL": "",
	"LLM_ENDPOINT": "/chat/completions",
	"LLM_PROFILES": [
		{
			"name": "openai-gpt4o-mini",
			"provider": "openai",
			"model": "gpt-4o-mini",
			"base_url": "https://api.openai.com/v1",
			"endpoint": "/chat/completions",
			"api_key": "sk-xxxx"
		},
		{
			"name": "deepseek-chat",
			"provider": "openai_compatible",
			"model": "deepseek-chat",
			"base_url": "https://api.deepseek.com/v1",
			"endpoint": "/chat/completions",
			"api_key": "sk-xxxx"
		}
	]
}
```

工具默认读取 `./local.config.json`，也可通过 `--config` 指定其他路径。

- `LLM_PROVIDER`: `openai` 或 `openai_compatible`
- `OPENAI_BASE_URL`: OpenAI 专用 base URL（可配置代理/网关路径）
- `OPENAI_ENDPOINT`: OpenAI 路径配置（默认 `/chat/completions`）
- `LLM_BASE_URL`: 兼容接口的 base URL（如 `https://api.deepseek.com/v1`）
- `LLM_ENDPOINT`: 兼容接口 endpoint，默认 `/chat/completions`
- `LLM_PROFILES`: 可配置多个模型/API，用于自动对比选优
- `TRANSLATION_DOMAIN`: 默认翻译专业场景，如 `general`/`legal`/`finance`

路径优先级：

- 当 `LLM_PROVIDER=openai`：`--base-url` > `OPENAI_BASE_URL` > `LLM_BASE_URL`
- 当 `LLM_PROVIDER=openai`：`--endpoint` > `OPENAI_ENDPOINT` > `LLM_ENDPOINT`

## 3. 环境变量（可选兜底）

```bash
set OPEN_API_KEY=你的key
set OPENAI_API_KEY=你的key
```

## 4. 术语表示例

参考 `glossary.sample.csv`：

- `source`: 原词
- `target`: 目标词
- `case_sensitive`: 是否大小写敏感（true/false）
- `lock`: 是否锁定不翻译（true/false）
- `category`: 术语分类（可选，如 Geometry, UI, Command, General）
- `comment`: 术语说明（可选）

### 4.1 术语分类

术语表支持分类管理，便于按场景筛选：

```python
# 按分类获取术语
glossary = Glossary.load("glossary.csv")
geometry_terms = glossary.get_terms_by_category("Geometry")

# 获取术语摘要用于 LLM prompt
summary = glossary.get_glossary_summary(max_items=20)
```

### 4.2 翻译记忆库 (TM)

支持自动保存和复用历史翻译：

```python
from doc_translator.translation_memory import TranslationMemory

# 加载已有 TM
tm = TranslationMemory("tm.json")

# 查找相似翻译
matches = tm.find_matches("Hello world", min_similarity=0.8)

# 获取 TM 上下文用于 prompt
context = tm.get_tm_context(texts, max_items=10)
```

### 4.3 LQA 自动检查

翻译后自动执行质量检查：

```python
from doc_translator.lqa import LQAChecker

checker = LQAChecker(glossary)
result = checker.check(source_segments, target_segments, glossary)

print(f"质量分数: {result.score}")
for issue in result.issues:
    print(f"[{issue.severity}] {issue.message}")
```

检查类型：
- **术语一致性**: 验证目标文本是否包含 glossary 中的目标术语
- **占位符完整性**: 验证 %s, %d, {0} 等参数占位符是否保留
- **数字保留**: 验证原文数字是否在译文中保留

## 5. 使用方式

```bash
python run.py --input d:/Work/docs --target en --glossary glossary.sample.csv --output-dir ./output
```

或指定本地配置文件：

```bash
python run.py --input d:/Work/docs --target en --config ./local.config.json
```

使用 OpenAI-Compatible 接口示例：

```bash
python run.py --input d:/Work/docs --target en --provider openai_compatible --base-url https://api.deepseek.com/v1 --model deepseek-chat
```

多 API 自动对比并选优示例：

```bash
python run.py --input d:/Work/docs --target zh --compare-apis --compare-models gpt-4o-mini,gpt-4.1-mini --output-dir ./output

自动识别源语言 + 法律场景示例：

```bash
python run.py --input ./test_materials --target en --source auto --domain legal
```
```

常见参数：

- `--input`: 文件或目录，可传多个
- `--target`: 目标语言代码（如 `en`）
- `--source`: 源语言代码，支持 `auto` 自动识别，默认 `auto`
- `--domain`: 专业场景，如 `general`/`legal`/`finance`/`medical`/`it`/`academic`
- `--glossary`: 术语表路径（可选）
- `--output-dir`: 输出目录（建议新目录）
- `--suffix`: 输出语言后缀，默认与 `--target` 一致
- `--batch-size`: 翻译批次大小，默认 `20`
- `--max-retries`: 失败重试次数，默认 `3`
- `--rate-limit-rpm`: 每分钟请求数，默认 `60`
- `--provider`: 模型提供商，`openai` 或 `openai_compatible`
- `--model`: 模型名称，默认按配置/环境变量解析
- `--base-url`: 兼容接口 Base URL
- `--endpoint`: 兼容接口 endpoint，默认 `/chat/completions`
- `--api-key`: API Key（优先级高于本地配置）
- `--config`: 本地配置文件路径，默认 `./local.config.json`
- `--compare-apis`: 启用多模型/多API对比选优
- `--compare-models`: 临时对比模型列表（逗号分隔）
- `--compare-sample-size`: 对比采样段落数，默认 `80`
- `--compare-report`: 对比报告文件名，默认 `compare_report.json`
- `--force-run`: 忽略运行锁强制执行
- `--to-pdf`: 翻译完成后将原始文件和翻译文件分别打印为 PDF，输出到 `<output-dir>/pdf/original` 与 `<output-dir>/pdf/translated`
- `--pdf-engine`: `--to-pdf` 所用引擎，`auto`（默认）/ `libreoffice` / `word_com`
- `--pdf-timeout`: `--to-pdf` 单文件转换超时（秒），默认 `180`

> **关于 LQA / TM**：这两个能力目前只通过 Python API (`TranslationPipeline(tm_path=..., enable_lqa=True)`) 使用，CLI 暂无直接开关。详见 [docs/FEATURES.md](docs/FEATURES.md)。

## 6. 输出内容

翻译结束后，`<output-dir>/` 目录下会生成：

```
output/
├── <原名>_<后缀>.<ext>          # 翻译结果（docx/xlsx/pdf）
├── report.json                  # 汇总报告
├── logs/translator.log          # 运行日志（按行）
├── .run.lock                    # 运行锁（进程结束后自动移除）
├── compare_report.json          # （仅 --compare-apis）多模型对比结果
└── pdf/                         # （仅 --to-pdf）
    ├── original/                # 原始文件的 PDF
    └── translated/              # 翻译后文件的 PDF
```

`report.json` 字段概览：

| 字段 | 说明 |
|------|------|
| `source_lang` / `target_lang` / `model` | 本轮运行参数 |
| `files_total` / `files_succeeded` / `files_failed` | 文件级统计 |
| `segments_total` / `segments_translated` / `glossary_hits` | 文本段统计 |
| `results[]` | 每个文件的 `input_path / output_path / status / segments_* / glossary_hits / lqa_score / lqa_issues / error` |

## 测试素材目录

- 已提供 `test_materials/` 目录用于放置测试文件。
- 可按场景自行建子目录（如 `legal/`、`finance/`）。
- 已提供场景术语模板目录 `test_materials/glossary_templates/`：
	- `general_glossary.csv`
	- `legal_glossary.csv`
	- `finance_glossary.csv`
	- `it_glossary.csv`
	- `medical_glossary.csv`
	- `academic_glossary.csv`

示例：

```bash
python run.py --input ./test_materials --target en --source auto --domain legal --glossary ./test_materials/glossary_templates/legal_glossary.csv
```

运行后会在输出目录生成：

- 翻译后的文档（`原名_后缀.ext`）
- `logs/translator.log`
- `report.json`（总量、成功失败、术语命中、LQA 分数等统计）

### 6.1 报告字段说明

`report.json` 新增字段：

- `lqa_score`: LQA 质量分数（0-100）
- `lqa_issues`: LQA 问题列表（按段落索引、类型、严重程度）
- TM 相关：翻译记忆自动保存到指定路径

## 7. Web界面

启动 Web 服务：

```bash
python webapp.py
```

打开浏览器访问：

- `http://127.0.0.1:5050`

界面功能：

- 多文件上传
- 选择源/目标语言
- 配置 provider、model、api key、base_url、endpoint
- 配置 batch/retry/rpm 参数
- 展示文件级进度与总体进度
- 轮询实时日志（`/api/jobs/<job_id>/logs`）
- 任务完成后一键下载结果包

运行机制：

- Web 任务会启动独立 worker 子进程执行翻译，避免轮询状态/日志时影响翻译进程。
- 任务状态持久化到 `web_runs/<job_id>/job_state.json`，Web 重载后仍可继续查询任务状态。

## 8. 打印为 PDF

项目内置 `.docx` / `.xlsx` / `.pptx` / `.odt` / `.rtf` 等格式 → PDF 的批量转换能力，`.pdf` 文件直接透传。**不依赖**翻译流程，也可独立使用。详细指南见 [docs/PDF_PRINTING.md](docs/PDF_PRINTING.md)。

**四种触发方式：**

```bash
# (1) 独立 CLI：批量把目录里的 Office 文档转为 PDF
python -m doc_translator.print_pdf_cli \
    --input ./docs --output-dir ./pdf_out --recursive

# (2) 翻译 + 同时生成两份 PDF（原始 + 翻译）
python run.py --input ./docs --target en --output-dir ./out --to-pdf

# (3) HTTP 独立接口（需启动 webapp.py）
curl -F "files=@a.docx" http://127.0.0.1:5050/api/print_pdf -o a.pdf

# (4) HTTP 对翻译任务打印（原始 + 翻译 → zip）
curl -X POST http://127.0.0.1:5050/api/jobs/<job_id>/print_pdf
curl -O http://127.0.0.1:5050/api/jobs/<job_id>/download_pdf
```

或 Python 模块直调：

```python
from pathlib import Path
from doc_translator.pdf_printer import print_to_pdf, print_many

print_to_pdf(Path("报告.docx"), Path("./pdf_out"))

results = print_many(
    [Path("a.docx"), Path("b.xlsx"), Path("c.pdf")],
    Path("./pdf_out"),
)
```

**引擎要求：** 至少安装 LibreOffice 或在 Windows 上安装 MS Office (+ `pywin32`)。可通过 `GET /api/pdf/engine` 或 `python -m doc_translator.print_pdf_cli --input . --output-dir /tmp --dry-run` 检查可用性。

## 9. Office 插件（Word/Excel）

除 Web 页面外，项目已提供 Office Task Pane 插件，可在 Word/Excel 内直接翻译选区。

### 9.1 启动后端

```bash
python webapp.py
```

插件页面地址：

- `http://127.0.0.1:5050/office/addin`

插件 manifest 地址：

- `http://127.0.0.1:5050/office/manifest.xml`

manifest 文件位置：

- `office_addin/manifest.xml`

### 9.2 功能

- Word：读取当前选区文本，翻译后可一键替换选区。
- Excel：读取当前选区所有字符串单元格，批量翻译并回写到原单元格。
- 插件支持配置 `provider/model/api_key/base_url/endpoint`，空 API Key 时使用服务端 `local.config.json`。
- 插件支持“启用术语表”开关与 `glossary_path` 路径配置（CSV/JSON，路径为服务端机器本地路径）。

### 9.3 侧载（Sideload）

在 Office（Word/Excel）中通过“我的加载项 / Upload My Add-in”上传 `office_addin/manifest.xml`。

若你的 Office 环境对 `http://127.0.0.1` 有策略限制，可将 `manifest.xml` 中 URL 改为你本机可访问的 HTTPS 地址（如本地反向代理证书域名）。

## 10. 实现说明与已知限制

- `.docx` 采用"复制 + 文本节点替换"策略，尽量保持版式。
- `.xlsx` 基于 openpyxl 遍历字符串单元格；含公式的单元格（`=...`）会被跳过。
- `.pdf` 为文本块覆盖方案（白底矩形遮盖 + 目标文本插入），复杂排版可能需人工抽检。
- 扫描件 PDF / 图片内容 OCR **不在**本工具范围内。
- "打印为 PDF"依赖外部引擎（LibreOffice 或 Word COM），不安装则相关接口/CLI 会返回明确的 `EngineNotAvailableError`。
- 输出目录包含运行锁（`.run.lock`），避免并发覆盖同一输出；如需强行运行，传 `--force-run`。
- 更多疑难问题请参阅 [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)。
