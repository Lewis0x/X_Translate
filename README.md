# 文档翻译工具（Doc Translator）

基于需求文档实现的命令行翻译工具，支持：

- `.docx`：复制原文档并仅替换文本节点（`w:t`）
- `.xlsx`：遍历字符串单元格并替换文本（保留单元格样式）
- `.pdf`（文本型）：按文本块覆盖翻译（扫描件不支持）
- 术语表（`CSV/JSON`）：支持锁定词与强制替换
- 批量处理：文件/目录均可
- 日志与报告：输出运行日志与 JSON 摘要
- Web 前端：上传文件、配置参数、实时查看任务进度并下载结果

## 1. 安装

```bash
cd d:/Work/Lewis/doc_translator_tool
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
```

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

## 6. 输出内容

## 测试素材目录

- 已提供 `test_materials/` 目录用于放置测试文件。
- 可按场景自行建子目录（如 `legal/`、`finance/`）。

运行后会在输出目录生成：

- 翻译后的文档（`原名_后缀.ext`）
- `logs/translator.log`
- `report.json`（总量、成功失败、术语命中等统计）

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

## 8. 说明

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

- `.docx` 采用“复制 + 文本节点替换”策略，尽量保持版式。
- `.pdf` 为文本块覆盖方案，复杂排版可能需人工抽检。
- 扫描件 PDF / 图片内容 OCR 不在本工具范围内。
- 输出目录包含运行锁（`.run.lock`），避免并发覆盖同一输出。
