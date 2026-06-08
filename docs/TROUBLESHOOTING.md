# 故障排查手册（Troubleshooting）

本文档汇总 X_Translate（doc_translator）在安装、配置、翻译、PDF 打印、Web 服务各阶段的常见问题及定位方法。排查顺序建议遵循"看日志 → 复现最小用例 → 核对配置 → 核对依赖"四步。

---

## 1. 日志与自检入口

在提交 issue 或深入调试前，请先确认：

```bash
# 1) CLI 帮助能正常输出（验证 Python 环境与依赖）
python run.py --help

# 2) Flask 能成功启动并响应
python webapp.py
curl -s http://127.0.0.1:5050/ | head -5

# 3) PDF 引擎是否可用
curl -s http://127.0.0.1:5050/api/pdf/engine

# 4) 查看最近一次翻译日志
tail -n 200 output/logs/translator.log        # CLI
tail -n 200 web_runs/<job_id>/output/logs/translator.log  # Web
```

`translator.log` 里 `ERROR` 级别行通常直接指向根因；`WARNING` 常见于单个 segment 失败但整体完成的情况。

---

## 2. 安装 / 依赖

### `ModuleNotFoundError: No module named 'flask'` / `openpyxl` / `fitz`

- 确认已激活虚拟环境（Windows `.venv\Scripts\activate`，Linux `source .venv/bin/activate`）。
- 重新安装：`pip install -r requirements.txt`。
- 若使用公司内网，需配置 pip 镜像或代理。

### `ImportError: No module named 'win32com'`（仅 Windows）

- `pip install pywin32`，然后以管理员身份再跑一次 `python -m pywin32_postinstall -install` 注册 COM。
- 若仍不可用但你装有 LibreOffice，PDF 打印会自动回退，不受影响。

### Python 版本过低

- 项目要求 Python 3.10+。`python --version` 验证；Windows 多版本共存时使用 `py -3.11` 明确指定。

---

## 3. LLM API 调用

### `401 Unauthorized` / `Invalid API Key`

- 检查 `local.config.json` 中 `OPEN_API_KEY` 或 `LLM_PROFILES[].api_key` 是否被 Git 误清空。
- CLI 参数 `--api-key` 会覆盖配置；若你在 CI 中不小心传了空字符串 `--api-key ""`，会覆盖配置里的正确值。
- 兼容接口（如 DeepSeek）要确保 `LLM_BASE_URL` 末尾不带多余 `/`，`LLM_ENDPOINT` 通常是 `/chat/completions`。

### `HTTP 400: model not found`

- 当 `provider=openai` 却指定 DeepSeek 模型时会出现。确认 provider 与 model 匹配。
- 使用 `--compare-apis` 时，请确保 `LLM_PROFILES` 中每条记录的 provider/model 都能被实际调用。

### 返回 HTML 页面 / 网关错误

- `translator.py` 会显式拦截 HTML 响应。日志会打印 `provider/base_url/endpoint` 信息，据此判断是否配错 Base URL（常见：把 `https://api.openai.com/v1` 写成 `https://api.openai.com`）。
- 公司代理网关可能返回登录页；改用 `OPENAI_BASE_URL` 指向有效网关。

### 限流 `429` 或大量重试

- 降低 `--rate-limit-rpm` 或 `--batch-size`；增加 `--max-retries`。
- 多模型对比时，`comparison.py` 内部会按 profile 串行采样，单次请求节奏由 `--compare-sample-size` 控制。

### 长段落输出被截断

- 主要是模型 `max_tokens` 限制。可在 profile 中手动加 `max_tokens`（如 `4096`）；或者减小 `--batch-size`。
- 若模型返回非严格 JSON，`translator.py` 已有多重回退：markdown code block 解析、`translations/result/data` 字段回退、单段落字符串回退。若仍失败，`translator.log` 会记录原始响应的前若干字节。

---

## 4. 文件格式适配

### `.docx` 翻译后样式错位

- 本项目只替换 `w:t` 节点，不改样式。若出现错位，通常因为：
  - 原文档是从 PDF/OCR 导出的 Word，段落被拆成过多小文本框；
  - 翻译结果长度差异大导致行高/列宽被撑开。
- 解决：在术语表里把关键固定词锁定（`lock=true`）；或对目标文件手动微调排版。

### `.xlsx` 公式单元格没翻

- 故意跳过以 `=` 开头的单元格，避免破坏公式。
- 若需要翻译公式中的字符串常量，请先在源文件中把常量改成值单元格。

### `.pdf` 翻译文字错位 / 覆盖不完整

- `pdf_adapter.py` 以白底矩形遮盖 + 目标文本插入。对于：
  - 多列排版；
  - 透明背景文字；
  - 嵌入图像中的文字（扫描件）；
  结果可能不佳。**扫描件 PDF 不在本工具范围内**。
- 替代方案：先用外部 OCR 转 Word，再翻译 Word，最后 `--to-pdf` 输出。

### `UnsupportedFormatError: 不支持的格式`

- `pipeline.SUPPORTED_SUFFIXES` 目前限定在 `.docx/.xlsx/.pdf`。扩展请参考 [CONTRIBUTING.md § 7](../CONTRIBUTING.md#7-新增-adapter新文件格式)。

---

## 5. 打印为 PDF

见 [PDF_PRINTING.md § 6](PDF_PRINTING.md#6-故障排查) 的完整列表。最高频问题汇总：

| 症状 | 优先排查 |
|------|----------|
| `EngineNotAvailableError` | `which soffice`（Linux/macOS）/ `where soffice`（Windows） |
| LibreOffice `exit=1` + 提到 `UserInstallation` | 串行调用；或传不同的 `-env:UserInstallation=` 目录 |
| 转换超时 | 增大 `--pdf-timeout`；大 Excel 建议 300–600 秒 |
| 输出 PDF 中文方块 | 安装 Noto Sans CJK / 微软雅黑 |
| Word COM `com_error` | `taskkill /F /IM winword.exe` 清理残留；或禁用企业 GPO COM 限制 |

---

## 6. Web 服务

### `Address already in use (:5050)`

- 已有一份 `webapp.py` 在跑：`lsof -i :5050`（Linux/macOS）/ `netstat -ano | findstr :5050`（Windows）。
- 或修改 `webapp.py` 末尾的 `port=5050` 为其他端口。

### 任务长时间 `queued` 或 `running` 但无日志

- `_jobs` 字典只保存本进程启动过的 job；若 Flask 重启，仍可通过 `job_state.json` 读取状态。
- 查看 `web_runs/<job_id>/job_state.json` 的 `pid` 字段，配合 `ps -p <pid>`（Linux）/ `tasklist /FI "PID eq <pid>"`（Windows）确认 worker 是否存活。
- 若 worker 已死但状态仍是 `running`：通常是被 OS kill 或代码抛未捕获异常。查看 `logs/translator.log` 末尾。

### `413 Request Entity Too Large`

- Flask 默认无限制，但前置反代（Nginx）可能限制。Nginx 加 `client_max_body_size 100m;`。

### 页面显示正常但进度一直 0%

- 常见原因：LLM API Key 不对，worker 一开始就失败。
- `GET /api/jobs/<job_id>/logs?tail=200` 取最近日志；若看到连续 `HTTP 401`，去检查 `local.config.json`。

### Office 插件面板空白 / 插件打不开

- 确认 `python webapp.py` 已启动且返回 `200 /office/addin`。
- 某些 Office 版本对 `http://127.0.0.1` 有策略限制，需要改用本地 HTTPS（可用 `mkcert` 生成证书 + Nginx 反代）。
- 仔细检查 `office_addin/manifest.xml` 中 URL 是否与后端一致。

---

## 7. 进程锁 `.run.lock`

### `已有进程正在使用输出目录`

- 上次运行异常退出留下的锁文件。
- 正常情况下 `--force-run` 可忽略；确认无其他 Python 进程在跑后手动删除 `<output-dir>/.run.lock` 也可。
- `is_pid_alive()`（`config.py`）会判断锁里的 pid 是否真的活着；活着时即使 `--force-run` 也会提示风险。

---

## 8. 术语表 / TM / LQA

### 术语表命中数明显偏低

- 检查术语表的 `case_sensitive` 与 `lock` 字段；`case_sensitive=false` 时会匹配任意大小写。
- 确认 CSV 的编码：必须 UTF-8（可选 BOM）；Windows 记事本默认 GB2312 会导致中文列全部乱码。
- `glossary.sample.csv` 中 `category` 字段为可选筛选用，非必填。

### LQA 分数一直很低 / 全是占位符报错

- 源文本若含大量 `%s %d {0}` 之类原样保留的占位符，而模型把它们翻成了中文符号，会被判定为"占位符缺失"。
- 若是误报，可在术语表里把这些占位符设为 `lock=true`，或在 prompt 里加入"保留所有 %s/%d/{n}"的说明。

### TM 文件越来越大

- `translation_memory.py` 用 JSON 存储，超过 ~200MB 读写会明显变慢。
- 解决：定期 `merge()` 合并到去重后的新文件；或切到按项目分文件。

---

## 9. 性能与资源

- CPU 瓶颈多出现在 LibreOffice 批量转 PDF 场景（每次新启 `soffice` 进程，冷启 1–3 秒）。
- 内存瓶颈：大 `.xlsx` 用 openpyxl 加载整个工作簿；>200MB 的文件建议先拆分。
- 网络瓶颈：模型请求串行 + `rate-limit-rpm` 节流，单机带宽几乎不是瓶颈；分布式需求请自行做任务队列。

---

## 10. 还是不行？

1. 收集：`translator.log` 最后 200 行 + `report.json`（如果有）+ 触发命令。
2. 复现：用 `test_materials/` 里的小样例是否也能复现？能则大概率是代码/环境问题；不能则大概率是数据问题。
3. 搜索已解决问题：先翻 [docs/PDF_PRINTING.md](PDF_PRINTING.md) / [CONTRIBUTING.md](../CONTRIBUTING.md)。
4. 开 Issue 时附上：
   - OS / Python 版本 / `pip list` 关键依赖版本
   - 复现命令
   - 删节后的日志片段（去除 API Key 等敏感信息）
