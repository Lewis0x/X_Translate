# HTTP API 参考

Flask 网关默认监听在 `http://127.0.0.1:5050`，所有响应（除二进制下载外）都是 `application/json; charset=utf-8`。

目录：
- [页面路由](#页面路由)
- [翻译任务](#翻译任务)
- [文本翻译](#文本翻译)
- [PDF 打印](#pdf-打印)
- [错误返回](#错误返回)

---

## 页面路由

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 主页（`templates/index.html`） |
| GET | `/office/addin` | Office 插件入口页 |
| GET | `/office/manifest.xml` | Office 插件 manifest（text/xml） |

---

## 翻译任务

### `POST /api/jobs` — 创建翻译任务

提交 `multipart/form-data`，立即返回 `job_id`，任务在独立进程执行。

**表单字段**

| 字段 | 必填 | 默认 | 说明 |
|------|:---:|------|------|
| `files` | ✔ | — | 一个或多个待翻译文件（.docx / .xlsx / .pdf） |
| `source` |  | `zh` | 源语言（`auto` 自动检测） |
| `target` |  | `en` | 目标语言 |
| `domain` |  | `general` | 翻译领域：general / legal / finance / medical / it / academic |
| `provider` |  | `openai` | `openai` / `openai_compatible` |
| `model` |  | 本地配置 | 模型名 |
| `api_key` |  | 本地配置 | API Key（本地配置优先覆盖） |
| `base_url` |  | 本地配置 | API Base URL |
| `endpoint` |  | `/chat/completions` | API 路径 |
| `batch_size` |  | `20` | 单次翻译批大小 |
| `max_retries` |  | `3` | 失败重试次数 |
| `rate_limit_rpm` |  | `60` | 每分钟最大请求数 |
| `suffix` |  | `target` | 输出文件名后缀 |

**响应 200**

```json
{ "job_id": "ab12cd34ef56" }
```

### `GET /api/jobs/<job_id>` — 查询任务状态

```json
{
  "status": "running",
  "message": "...",
  "current_file": "report.docx",
  "file_done": 12,
  "file_total": 40,
  "file_percent": 30,
  "overall_percent": 50,
  "output_dir": "/abs/path",
  "log_path": "/abs/path/logs/translator.log",
  "pid": 12345,
  "error": ""
}
```

`status` 取值：`queued` / `running` / `completed` / `failed`。

### `GET /api/jobs/<job_id>/logs?tail=N` — 查询实时日志

```json
{ "status": "running", "logs": ["...", "..."] }
```

`tail` 范围 10–1000，默认 120。

### `GET /api/jobs/<job_id>/download` — 下载翻译结果压缩包

返回 `application/zip`，仅在 `status=completed` 时可用。

---

## 文本翻译

### `POST /api/translate_text`

请求 JSON：

```json
{
  "text": "Hello world",
  "source": "auto",
  "target": "zh",
  "provider": "openai",
  "model": "gpt-4o-mini",
  "api_key": "sk-...",
  "use_glossary": false,
  "glossary_path": ""
}
```

响应：`{ "translated_text": "..." }`

### `POST /api/translate_batch`

请求 JSON 与 `translate_text` 类似，但传 `texts: ["...", "..."]`。
响应：`{ "translations": ["...", "..."] }`

---

## PDF 打印

### `GET /api/pdf/engine` — 探测可用引擎

```json
{
  "available": true,
  "engine": "libreoffice",
  "description": "LibreOffice (/usr/bin/soffice)",
  "executable": "/usr/bin/soffice"
}
```

或（未检测到引擎时仍返回 200）：

```json
{ "available": false, "error": "未检测到任何 PDF 转换引擎..." }
```

### `POST /api/print_pdf` — 打印为 PDF（二进制下载）

提交 `multipart/form-data` 字段 `files`（可多个）。

- **单文件成功**：返回 `application/pdf`
- **多文件或混合结果**：返回 `application/zip`

响应头：
- `X-PDF-Engine: libreoffice | word_com`
- `X-PDF-Errors: <json 数组>`（仅当有部分失败）

失败响应：
- `400`：未提供文件
- `503`：系统无可用引擎
- `500`：全部失败

### `POST /api/print_pdf/json` — 打印为 PDF（结构化响应）

与上一个接口相同的表单，但以 JSON 返回逐文件结果，便于前端批量场景展示：

```json
{
  "task_id": "abc123",
  "engine": "libreoffice",
  "results": [
    {
      "input": "a.docx",
      "status": "success",
      "pdf": "a.pdf",
      "download_url": "/api/print_pdf/abc123/download/a.pdf",
      "error": null
    },
    {
      "input": "b.xlsx",
      "status": "failed",
      "pdf": null,
      "download_url": null,
      "error": "LibreOffice 转换失败 (exit=1) ..."
    }
  ]
}
```

### `GET /api/print_pdf/<task_id>/download/<filename>` — 下载单个 PDF

返回 `application/pdf`。路径穿越会被拒绝（`os.path.basename`）。

### `POST /api/jobs/<job_id>/print_pdf` — 把翻译任务的全部文件打印为 PDF

对指定翻译任务（必须存在 `input/` 与 `output/`），同时生成 **原始文件** 与 **翻译文件** 的 PDF：

```json
{
  "job_id": "ab12cd34ef56",
  "engine": "libreoffice",
  "original": [
    { "input": "a.docx", "status": "success", "pdf": "a.pdf", "error": null }
  ],
  "translated": [
    { "input": "a_en.docx", "status": "success", "pdf": "a_en.pdf", "error": null }
  ],
  "download_url": "/api/jobs/ab12cd34ef56/download_pdf"
}
```

结果压缩包结构：

```
ab12cd34ef56_pdfs.zip
├── original/<file>.pdf
└── translated/<file>.pdf
```

### `GET /api/jobs/<job_id>/download_pdf`

下载上一步生成的 zip（`application/zip`）。若未先调用 `print_pdf` 会返回 404。

---

## 错误返回

所有错误返回形如：

```json
{ "error": "任务不存在" }
```

常见状态码：

| 状态 | 含义 |
|------|------|
| 400 | 请求参数缺失或错误（没有文件、texts 为空等） |
| 404 | 资源不存在（任务 ID / PDF 文件） |
| 500 | 服务器内部异常（翻译失败、全部打印失败） |
| 503 | 依赖不可用（没有安装 LibreOffice/Office） |

---

## cURL 快速示例

```bash
# 1) 提交翻译任务
curl -F "files=@a.docx" -F "target=en" \
     http://127.0.0.1:5050/api/jobs

# 2) 轮询状态
curl http://127.0.0.1:5050/api/jobs/ab12cd34ef56

# 3) 下载翻译结果
curl -O http://127.0.0.1:5050/api/jobs/ab12cd34ef56/download

# 4) 对任务打印原始 + 翻译 PDF
curl -X POST http://127.0.0.1:5050/api/jobs/ab12cd34ef56/print_pdf
curl -O http://127.0.0.1:5050/api/jobs/ab12cd34ef56/download_pdf

# 5) 独立 PDF 打印（不经过翻译）
curl -F "files=@a.docx" -F "files=@b.xlsx" \
     http://127.0.0.1:5050/api/print_pdf -o pdfs.zip
```
