# 打印为 PDF（PDF Printing）

本文档是 X_Translate "打印为 PDF" 功能的完整手册，涵盖引擎选择/安装、四种调用方式、输出结构、常见故障排查，以及与翻译流程配合的两种典型工作流。

所有功能背后是同一个模块 —— [`doc_translator.pdf_printer`](../doc_translator/pdf_printer.py)，它对外暴露：

- `detect_engine()` — 自动探测本机可用引擎
- `print_to_pdf(input, output_dir, engine=None, timeout=180)` — 单文件
- `print_many(files, output_dir, engine=None, timeout=180)` — 批量（不抛异常，失败信息逐条返回）

---

## 1. 支持的格式

| 分类 | 后缀 | 处理方式 |
|------|------|---------|
| Word / 富文本 | `.docx`, `.doc`, `.rtf`, `.odt` | 引擎导出为 PDF |
| Excel | `.xlsx`, `.xls`, `.ods` | 引擎导出为 PDF |
| PowerPoint | `.pptx`, `.ppt`, `.odp` | 引擎导出为 PDF |
| **PDF** | `.pdf` | **直接透传**（复制到输出目录，不需要引擎） |
| 其他 | 其他 | 抛 `UnsupportedFormatError` |

> 透传策略意味着：即使本机没有任何引擎，只要输入是 `.pdf`，也可以正常"打印"，这对于把翻译产物打包（原始 + 翻译都要 PDF）的场景非常方便。

---

## 2. 引擎选择

`detect_engine()` 按以下顺序尝试：

1. **LibreOffice**（推荐）— 跨平台、命令行驱动 (`soffice --headless --convert-to pdf`)
   - Linux：`apt install libreoffice` / `dnf install libreoffice`
   - macOS：`brew install --cask libreoffice`
   - Windows：从 [libreoffice.org](https://www.libreoffice.org/) 下载安装包，默认路径 `C:\Program Files\LibreOffice\program\soffice.exe` 会被自动识别；也可把 `soffice` 加入 PATH。
2. **Microsoft Word / Excel / PowerPoint COM**（仅 Windows）— 需要本机已安装 MS Office **并** `pip install pywin32`
   - 实际走 `win32com.client.DispatchEx("Word.Application")` 等，弹窗全部关闭（`Visible=False, DisplayAlerts=False`）
   - 无窗口模式下 PowerPoint 使用 `Presentations.Open(..., WithWindow=False)`

两者都不可用时，所有"打印为 PDF"入口返回：

- Python API：`EngineNotAvailableError`
- HTTP：`503 Service Unavailable` + `{"error": "..."}`
- CLI：退出码 `3`

**显式选择引擎：** `print_pdf_cli` 的 `--engine libreoffice|word_com|auto`、翻译 CLI 的 `--pdf-engine`、HTTP 暂时仅支持 auto。

---

## 3. 四种调用方式

### 3.1 Python 模块直调

```python
from pathlib import Path
from doc_translator.pdf_printer import (
    print_to_pdf, print_many, detect_engine,
    EngineInfo, EngineNotAvailableError, UnsupportedFormatError, PdfConversionError,
)

# 探测
try:
    engine = detect_engine()
    print("使用:", engine.description)
except EngineNotAvailableError as e:
    print("没有可用引擎:", e)

# 单文件
out = print_to_pdf(Path("report.docx"), Path("./pdf_out"))
print("生成:", out)

# 批量；失败不会抛，在 results 中报告
results = print_many(
    [Path("a.docx"), Path("b.xlsx"), Path("c.pdf"), Path("d.rtf")],
    Path("./pdf_out"),
    timeout=300,
)
for src, pdf, err in results:
    print(src.name, "->", pdf.name if pdf else f"FAIL: {err}")
```

### 3.2 独立 CLI（`print_pdf_cli`）

不需要启动 Flask。**用途：** 本地批处理、定时任务、CI 中的打包环节。

```bash
# 打印单个文件
python -m doc_translator.print_pdf_cli \
    --input demo.docx --output-dir ./pdf_out

# 打印目录下所有支持的文件（递归）
python -m doc_translator.print_pdf_cli \
    --input ./docs --output-dir ./pdf_out --recursive

# 多个输入 + 指定引擎 + 超时
python -m doc_translator.print_pdf_cli \
    -i a.docx -i b.xlsx -i ./subdir \
    -o ./out --engine libreoffice --timeout 300

# 仅列出将要处理的文件（不执行）
python -m doc_translator.print_pdf_cli \
    -i ./docs -o ./out --recursive --dry-run

# 详细日志
python -m doc_translator.print_pdf_cli -i a.docx -o ./out -v
```

**参数：**

| 参数 | 说明 | 默认 |
|------|------|------|
| `-i, --input` | 输入文件或目录；可重复 | 必填 |
| `-o, --output-dir` | 输出目录（不存在会自动创建） | 必填 |
| `-r, --recursive` | 对目录递归扫描 | false |
| `--engine` | `auto` / `libreoffice` / `word_com` | `auto` |
| `--timeout` | 单文件转换超时秒数 | `180` |
| `-v, --verbose` | DEBUG 级日志 | false |
| `--dry-run` | 只列出将处理的文件 | false |

**退出码：**

| 码 | 含义 |
|----|------|
| 0 | 全部成功（或 dry-run） |
| 1 | 至少一个文件转换失败 |
| 2 | 参数错误 / 无可处理文件 |
| 3 | 没有可用引擎 |

### 3.3 翻译 CLI 的 `--to-pdf`

翻译跑完 **并且** 报告生成后，自动把原始文件与翻译文件各自打印一份 PDF。

```bash
python run.py \
    --input ./docs --target en --output-dir ./out \
    --to-pdf --pdf-engine auto --pdf-timeout 180
```

产物结构：

```
out/
├── <file>_en.docx        # 翻译结果
├── report.json
├── logs/translator.log
└── pdf/
    ├── original/
    │   └── <file>.pdf
    └── translated/
        └── <file>_en.pdf
```

**容错：** PDF 打印失败不会影响翻译本身的退出码；所有失败都以 `WARNING` / `ERROR` 写入 `translator.log`。

### 3.4 HTTP 接口

需要先启动 `python webapp.py`（默认 `127.0.0.1:5050`）。

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/api/pdf/engine` | 探测可用引擎 |
| `POST` | `/api/print_pdf` | 批量打印，单文件返回 PDF，多文件返回 zip |
| `POST` | `/api/print_pdf/json` | 批量打印，返回每个文件的成功/失败与下载 URL |
| `GET` | `/api/print_pdf/<task_id>/download/<filename>` | 下载单个已生成 PDF |
| `POST` | `/api/jobs/<job_id>/print_pdf` | 把指定翻译任务的原始 + 翻译文件打成一个 zip |
| `GET` | `/api/jobs/<job_id>/download_pdf` | 下载上一步生成的 zip |

接口的入参、响应体、状态码详见 [API.md](API.md)。

---

## 4. 工作流示例

### 工作流 A — 纯 PDF 归档（不做翻译）

```bash
# 把甲方提交的杂混格式全部转 PDF 存档
python -m doc_translator.print_pdf_cli \
    -i ./received -o ./archive/pdf -r -v
```

### 工作流 B — 翻译 + 双语 PDF 一体化

```bash
# 一行命令产出：翻译后的 docx + 原件 PDF + 译件 PDF
python run.py \
    --input ./source --target en --output-dir ./out --to-pdf
```

### 工作流 C — Web 上传 → 翻译 → 一键出两份 PDF

1. 浏览器访问 `http://127.0.0.1:5050`，上传文件、点击"开始翻译"。
2. 任务 `completed` 后，页面上会出现"将原始+翻译文件打印为 PDF"按钮。
3. 点击后，前端调用 `POST /api/jobs/<job_id>/print_pdf`；生成的 zip 结构为：
   ```
   <job_id>_pdfs.zip
   ├── original/*.pdf
   └── translated/*.pdf
   ```
4. 通过 `GET /api/jobs/<job_id>/download_pdf` 下载。

### 工作流 D — CI 里验证引擎可用

```bash
set +e
python -m doc_translator.print_pdf_cli \
    -i sample.docx -o /tmp/pdf_check >/dev/null
rc=$?
if [ $rc -eq 3 ]; then
  echo "::error::PDF engine not installed on the runner"
  exit 1
fi
```

---

## 5. 超时与资源

- **`--timeout` 默认 180 秒**。大 Excel / 含图 Word 请酌情加大。
- LibreOffice 启动有 1–3 秒冷启动成本；批量场景 `print_many` 会**复用** `EngineInfo` 但每次仍新启一个 `soffice` 进程（LibreOffice 单例限制）。
- Word COM 会在每次调用时 `DispatchEx` + `Quit`，比 LibreOffice 略慢但更稳定。
- Windows 下外部进程使用 `CREATE_NO_WINDOW` 隐藏黑窗；Linux/macOS 无此问题。

---

## 6. 故障排查

### `EngineNotAvailableError: 未检测到任何 PDF 转换引擎`

- 确认 LibreOffice 已安装：`which soffice` / `where soffice.exe`。
- Windows：若安装路径非默认（非 `C:\Program Files\LibreOffice\...`），把 `...\LibreOffice\program` 加入 `PATH`。
- 或在 Windows 上 `pip install pywin32` 并确认 MS Office 已授权启动。

### `LibreOffice 转换失败 (exit=1)` / 输出中含 `UserInstallation`

- 常见于**同一用户**同时跑多个 soffice 实例导致配置目录锁冲突；解决：串行调用（`print_many` 内部已经是串行），或给每个进程传不同的 `-env:UserInstallation=file:///tmp/lo-<pid>`（可扩展 `_run_libreoffice`）。
- 也可能是输入文件损坏；先用 LibreOffice 手动打开验证。

### `LibreOffice 转换超时`

- 大文件需要把 `--timeout` / `timeout=` 提到 300–600；若是服务器环境，增配 CPU/内存。
- 若仍然超时，先 `soffice --headless --convert-to pdf <file>` 手动复现。

### `LibreOffice 转换结束但未生成 PDF`

- 通常是 LibreOffice 报错写到 stderr 但 returncode 仍为 0；查看日志里的 `STDOUT/STDERR` 判断。
- 对于只读文件，先 `chmod +r` / 复制到可读位置。

### Word COM `pywintypes.com_error`

- 目标文件可能被其他 Word 实例占用 —— 确保没有 Word 进程残留（`taskkill /F /IM winword.exe`）。
- 禁用 Word 的"修复文档"对话框：已在代码中设置 `DisplayAlerts=False`。
- 企业环境 GPO 可能禁止 COM 自动化；联系 IT 或改用 LibreOffice。

### HTTP 上传后一直 `503`

- `curl http://127.0.0.1:5050/api/pdf/engine` 查看 `available` 字段；为 `false` 时按上述安装引擎。

### 生成的 PDF 中文乱码 / 方块

- 仅当目标机器没有安装对应字体时发生。LibreOffice 路径：安装 Noto Sans CJK / 微软雅黑。
- Linux：`apt install fonts-noto-cjk`

---

## 7. 与翻译流程的设计取舍

- PDF 打印**独立于**翻译 Adapter 体系，不读取/解析 Office 文档 XML，不会影响翻译逻辑。
- `--to-pdf` 与 `/api/jobs/<id>/print_pdf` 都是**翻译后**执行的，失败不影响已翻译产物。
- `.pdf` 输入在翻译场景下会走 `pdf_adapter.py`（文本块覆盖）；在打印场景下会直接透传到输出目录。**两条路径互不干扰。**

---

## 8. 关联文档

- [API.md](API.md) § PDF 打印 — 所有 HTTP 接口的字段、状态码
- [ARCHITECTURE.md](ARCHITECTURE.md) § 2.4 / § 6 — PDF 模块在整体架构中的位置
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — 项目级故障排查，含 PDF 章节索引
