# 架构设计（Architecture）

本文档面向开发者，介绍 **X_Translate（doc_translator）** 的分层结构、关键模块职责、数据流与扩展点。终端使用说明请看 [README.md](../README.md)。

---

## 1. 总览

```
             ┌──────────────────┐          ┌────────────────────┐
             │  浏览器 / Office │          │  命令行 / CI / 脚本│
             └────────┬─────────┘          └─────────┬──────────┘
                      │ HTTP                         │ stdin/argv
                      ▼                              ▼
             ┌──────────────────┐          ┌────────────────────┐
             │     webapp.py    │          │ doc_translator.cli │
             │  (Flask 网关)    │          │  print_pdf_cli     │
             └────────┬─────────┘          └─────────┬──────────┘
                      │ 创建任务/转发                  │
                      ▼                              │
              ┌─────────────────────────────────────▼────────┐
              │           doc_translator.pipeline            │
              │ （翻译主流程；协调 adapter / translator / 术语│
              │   / TM / LQA / 进度回报）                    │
              └──────────┬──────────────────┬────────────────┘
                         │                  │
       ┌─────────────────▼────────┐  ┌──────▼──────────────────┐
       │ adapters/ (格式层)        │  │ translator.py           │
       │  docx / xlsx / pdf        │  │  OpenAI / 兼容接口      │
       └───────────────────────────┘  └─────────────────────────┘

                   ┌──────────── 横切模块 ────────────┐
                   │ glossary.py  (术语锁定)            │
                   │ translation_memory.py (TM)         │
                   │ lqa.py (质量检查)                  │
                   │ reporting.py (日志与 JSON 摘要)     │
                   │ config.py (本地配置 / 进程锁)       │
                   │ pdf_printer.py (docx/xlsx → PDF)   │
                   └──────────────────────────────────┘
```

## 2. 分层与模块职责

### 2.1 入口层
| 模块 | 职责 |
|------|------|
| `webapp.py` | Flask 网关；上传文件 → 创建 job → 启动独立 worker 进程 → 轮询进度；还暴露 PDF 打印 / 文本翻译 / Office Add-in 等端点 |
| `doc_translator/cli.py` | 命令行入口；支持批量翻译、模型自动对比、`--to-pdf` 打印 |
| `doc_translator/print_pdf_cli.py` | 独立的 PDF 打印 CLI（无需启动 Flask） |
| `doc_translator/web_worker.py` | 被 `webapp.py` 子进程方式启动；读取 `job_state.json` → 调用 `pipeline` → 实时回写状态 |

### 2.2 核心流程层
| 模块 | 职责 |
|------|------|
| `pipeline.py` | 翻译主流程：收集文件、选择 adapter、调用 translator、触发术语表 / TM / LQA、进度回调、写 `RunReport` |
| `translator.py` | `TranslationConfig` 数据类 + `BaseBatchTranslator` 抽象类 + OpenAI / OpenAI-Compatible 实现；限流、重试、批量切分 |
| `comparison.py` | 多模型对比：采样翻译 → 评分 → 自动选择最佳 profile |

### 2.3 格式适配层（`adapters/`）
| 模块 | 职责 |
|------|------|
| `docx_adapter.py` | 解压 docx → 解析 `w:t` 节点 → 替换文本 → 打包 |
| `xlsx_adapter.py` | 基于 openpyxl 遍历字符串单元格 → 替换 |
| `pdf_adapter.py` | 基于 PyMuPDF 按文本块覆盖（扫描件不支持） |
| `base.py` | `FileAdapter` 协议与 `FileStats` 数据类 |

扩展新格式只需实现 `FileAdapter.suffixes` 与 `process()`，然后在 `TranslationPipeline.__init__` 加一个 try/except 导入分支即可。

### 2.4 横切功能
| 模块 | 职责 |
|------|------|
| `glossary.py` | 术语表加载 / 锁定词占位 / 后处理还原 / 强制替换 |
| `translation_memory.py` | SQLite/JSON 翻译记忆；命中时跳过调 LLM |
| `lqa.py` | 翻译质量检查（数字一致性、占位符完整性、术语命中率等） |
| `reporting.py` | 日志 logger 工厂 + `RunReport` / `FileResult` 数据结构 + JSON 写盘 |
| `config.py` | 本地配置读取、LLM profiles 列表、进程活性检测、`.run.lock` 管理 |
| `web_state.py` | Web 任务状态原子读写（带临时文件 + rename） |
| `pdf_printer.py` | 引擎自动检测（LibreOffice / Word COM）；docx/xlsx → PDF；pdf 透传 |

## 3. 数据流（翻译流程）

```
     input files ──▶ collect_files()  ──▶  files[]
                                                 │
                                                 ▼
                          ┌────── for each file ──────┐
                          │  adapter = adapters[ext]  │
                          │  adapter.process(         │
                          │    input, output,         │
                          │    translator, glossary)  │
                          │  ├── 解析文本段          │
                          │  ├── glossary.preprocess │
                          │  ├── translator.translate│
                          │  ├── glossary.postprocess│
                          │  └── 写回格式             │
                          └──────────┬────────────────┘
                                     ▼
                      RunReport.add_result(FileResult)
                                     ▼
                    report.json  +  translator.log
                                     ▼
                    [--to-pdf] → pdf_printer.print_many
                                  (original + translated)
```

## 4. 状态与持久化

- Web 任务根目录：`web_runs/<job_id>/`
  - `input/` 用户上传的原始文件
  - `output/` 翻译后的文件 + `logs/translator.log`
  - `job_config.json`、`job_state.json`
  - `pdf/` （可选）PDF 打印结果：`original/` + `translated/`
- CLI 模式：所有产物都写到 `--output-dir` 下，结构相同。
- 进程锁：`<output-dir>/.run.lock`，格式 `{pid, owner, ts}`；`--force-run` 可忽略。

## 5. 并发与进程模型

- Web UI 每个 job 启动一个独立 Python 子进程（`subprocess.Popen`），互不阻塞，主进程只做状态查询；进程组独立便于独立杀死。
- `web_state.py` 采用临时文件 + `os.replace()` 实现原子写；读取端无锁，接受最终一致。
- 外部命令（LibreOffice / Word）在 `pdf_printer.py` 内走 `subprocess.run()` + `timeout`，Windows 下 `CREATE_NO_WINDOW` 隐藏控制台。

## 6. 扩展点一览

| 扩展意图 | 改这里 |
|----------|--------|
| 新增文件格式 | `adapters/` 新增类 + `pipeline.py` 注册 |
| 新增 LLM 提供方 | `translator.py` 继承 `BaseBatchTranslator` + `create_translator()` 分支 |
| 自定义质量检查规则 | `lqa.py` 中 `LQAChecker` 追加规则 |
| 替换 PDF 引擎 | `pdf_printer.py` 内实现 `_run_xxx(input, output)` + 在 `detect_engine()` 注册 |
| 新增 Web 接口 | `webapp.py` 添加路由；状态持久化建议复用 `web_state.py` |

## 7. 相关文档

- 用户使用说明：[README.md](../README.md)
- HTTP API 规范：[API.md](API.md)
- 贡献指南：[../CONTRIBUTING.md](../CONTRIBUTING.md)
- 测试说明：[../tests/README.md](../tests/README.md)
- 历史需求：[../翻译工具需求方案.md](../翻译工具需求方案.md)
- 版本迭代：[../开发日志.md](../开发日志.md)
