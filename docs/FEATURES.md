# 高级功能（Features）

本文档介绍 X_Translate 在基础翻译流程之上的四项增强能力：

1. 术语表分类与摘要（Glossary）
2. 翻译记忆库（Translation Memory, TM）
3. LQA 自动质量检查
4. 多模型 / 多 API 对比选优

这些能力中的 LQA 与 TM 暂未暴露为 CLI 参数，只能通过 **Python API** 或直接实例化 `TranslationPipeline` 启用；多模型对比则已提供 `--compare-apis` 等 CLI 开关。本文给出每项能力的设计意图、接入位置、示例代码与局限性。

---

## 1. 术语表（Glossary）

### 1.1 文件格式

支持 CSV（推荐）和 JSON。CSV 示例见 [`glossary.sample.csv`](../glossary.sample.csv)。字段：

| 字段 | 必填 | 说明 |
|------|:---:|------|
| `source` | ✔ | 原词 |
| `target` | ✔ | 目标词（若 `lock=true` 可空，表示原样保留） |
| `case_sensitive` |  | `true/false`，默认 false |
| `lock` |  | `true/false`；true 时匹配到的源词会被**原样保留**，通过占位符保护 |
| `category` |  | 术语分类，便于筛选（如 `Geometry / UI / Command / General`） |
| `comment` |  | 术语说明 |

### 1.2 加载与基础用法

```python
from doc_translator.glossary import Glossary

glossary = Glossary.load("glossary.csv")

# 按分类查看
for term in glossary.get_terms_by_category("Geometry"):
    print(term.source, "→", term.target)

# 生成摘要供 prompt 注入
summary = glossary.get_glossary_summary(max_items=20)
```

### 1.3 与翻译流程的集成

- **CLI**：`--glossary glossary.csv`，`TranslationPipeline` 自动完成：预处理锁定（占位符替换）→ LLM → 后处理还原 + 强制替换。
- **LLM Prompt 注入**：`TranslationConfig.glossary_summary` 如果非空，会拼接到系统 prompt 里。`BaseBatchTranslator._build_prompt()` 负责装配，默认一次给模型最多 20 条术语，避免上下文爆炸。
- **报告**：`report.json` 的 `glossary_hits` 字段累计命中次数。

### 1.4 建议

- 把产品名、专有 UI 标签放进术语表并 `lock=true`，可显著稳定跨文件用词。
- `case_sensitive=true` 仅对英文缩写类术语有意义（如 API、CAD）；中文基本没必要。
- 不同领域的术语独立成文件（`test_materials/glossary_templates/` 下已有样例），通过 `--glossary` 切换。

---

## 2. 翻译记忆库（TM）

### 2.1 定位

TM 保存"源文本 → 目标文本"的历史映射，用于：

- **直接命中时跳过 LLM 调用**（节省费用与时间）；
- **相似命中时作为上下文注入 prompt**（提高术语一致性）。

存储形式：JSON 文件，可跨任务复用；通过 `merge()` 合并多份。

### 2.2 启用方式（Python API）

```python
from pathlib import Path
from doc_translator.pipeline import TranslationPipeline
from doc_translator.translator import TranslationConfig, create_translator
from doc_translator.glossary import Glossary

glossary = Glossary.load("glossary.csv")
config = TranslationConfig(
    provider="openai", model="gpt-4o-mini",
    api_key="sk-...",
    source_lang="auto", target_lang="zh",
    domain="general",
)
translator = create_translator(config)

pipeline = TranslationPipeline(
    translator=translator,
    glossary=glossary,
    tm_path=Path("./tm.json"),    # 本项开启 TM
    enable_lqa=False,
)

pipeline.run(
    input_paths=[Path("./docs")],
    output_dir=Path("./out"),
    suffix="zh",
)
```

CLI 现阶段**不直接暴露** `--tm-path`；如需按项目启用，建议自行写一个包装脚本（几十行）调用上面的 API。

### 2.3 相似度匹配

`TranslationMemory.find_matches(query, min_similarity=...)` 当前实现的是：

- 精确匹配优先（similarity=1.0）；
- 否则用 token 重叠率近似（简单快速，不做向量化）。

如需更准确的语义相似度，扩展点：
- 把 `find_matches` 改成调用本地嵌入模型（如 `sentence-transformers`）；
- 持久化切换到 sqlite / DuckDB 以支持亿级条目。

### 2.4 上下文注入

```python
matches = tm.find_matches("用户登录后跳转首页", min_similarity=0.7)
context = tm.get_tm_context([t["source"] for t in texts], max_items=10)
# context 是一段可以拼接到 prompt 前的字符串：
# "以下是相关的历史翻译，请保持风格一致：\n原文：... / 译文：...\n..."
```

`TranslationConfig.context` 字段接收这段字符串；`BaseBatchTranslator._build_prompt()` 会把它放到 system prompt 尾部。

### 2.5 注意事项

- TM 文件体积会随时间增长，超过 200MB 加载会慢，建议按项目拆分或定期合并去重。
- 多人协作场景：每人本地一份 TM，定期 `merge()` 到共享版本。
- 不要把敏感内容的 TM 提交到 Git 公共仓库。

---

## 3. LQA 自动质量检查

### 3.1 定位

在模型返回后、写入目标文件前，按规则做一轮检查并给出问题列表 + 0–100 的质量分。**不是**人工 LQA 的替代，而是**卡掉明显错误**的最后一道过滤。

### 3.2 检查项

| 类型 | 含义 | 严重程度 |
|------|------|----------|
| 术语一致性 | glossary 中 `target` 是否出现在翻译结果 | medium |
| 占位符完整性 | `%s / %d / {0} / {name}` 是否保留 | high |
| 数字保留 | 原文数字是否在译文中出现 | medium |

扣分规则（`lqa.py` 内）：high = -10，medium = -5，low = -2；下限 0。

### 3.3 启用方式（Python API）

```python
pipeline = TranslationPipeline(
    translator=translator,
    glossary=glossary,
    enable_lqa=True,     # 本项开启 LQA
)
```

也可以单独调用 `LQAChecker` 复查已有译文：

```python
from doc_translator.lqa import LQAChecker

checker = LQAChecker(glossary)
result = checker.check(source_segments, target_segments, glossary)

print(f"质量分数: {result.score}")
for issue in result.issues:
    print(f"[{issue.severity}] seg#{issue.segment_index} {issue.issue_type}: {issue.message}")
    if issue.suggestion:
        print("  建议:", issue.suggestion)
```

### 3.4 在报告中的位置

`report.json > results[] > lqa_score` / `lqa_issues`。前端可按分数排序列出最差的文件；CI 可在分数 <阈值 时失败。

### 3.5 常见误报与应对

- 数字被本地化（如 `1,000` → `1.000`）会被误判，可在规则里扩展容忍；
- 英中翻译里占位符 `%s` 本应保留但模型写成 `%S`，会被判定缺失 —— 这通常是真的错，让模型重译；
- 术语检查对长句命中较宽松：glossary target 只要在整条翻译里出现即通过，不检查位置。

---

## 4. 多模型 / 多 API 对比选优

### 4.1 用途

当你有多个 API Key（OpenAI / DeepSeek / Moonshot ...）或多个模型（gpt-4o / gpt-4o-mini / deepseek-chat），希望自动挑出对当前领域表现最好的一个时使用。

### 4.2 触发

CLI：

```bash
python run.py \
    --input ./docs --target zh \
    --compare-apis \
    --compare-models gpt-4o-mini,gpt-4.1-mini,deepseek-chat \
    --compare-sample-size 80 \
    --compare-report compare_report.json \
    --output-dir ./out
```

工作流程（`comparison.py`）：

1. 从 `local.config.json` 的 `LLM_PROFILES` 与 `--compare-models` 组合生成候选列表；
2. 对每个候选，用采样的 N 条源段落做翻译（默认 80 条）；
3. 按评分算法（token 重叠率 + 长度偏差 + 是否保留数字/占位符）给每个候选打分；
4. 选分数最高的作为本轮正式翻译的 profile；
5. 输出 `compare_report.json`，字段包括：候选名、模型、base_url、分数、耗时、失败段落数。

### 4.3 注意

- 采样数越大越准，也越贵。**80 条**是经验值；如文档极短，改成 20 也可；如文档极长（几万段），100–200 更稳。
- 不同候选的费用差异大（gpt-4o vs gpt-4o-mini 能差 10×），先在小文档上跑 `--compare-apis` 定出赢家，再对大批量关闭该开关直接使用赢家。
- 评分算法是启发式的，不保证语义最优。对专业领域请以人工抽检为准。

---

## 5. 高级组合示例

### 5.1 企业知识库持续翻译

```python
from pathlib import Path
from doc_translator.glossary import Glossary
from doc_translator.pipeline import TranslationPipeline
from doc_translator.translator import TranslationConfig, create_translator

glossary = Glossary.load("kb_glossary.csv")

config = TranslationConfig(
    provider="openai_compatible",
    model="deepseek-chat",
    base_url="https://api.deepseek.com/v1",
    api_key="sk-...",
    source_lang="zh", target_lang="en",
    domain="it",
)
translator = create_translator(config)

pipeline = TranslationPipeline(
    translator=translator,
    glossary=glossary,
    tm_path=Path("./kb_tm.json"),  # 跨任务积累
    enable_lqa=True,                # 坏翻译直接暴露
)

pipeline.run(
    input_paths=[Path("./kb/2026Q1")],
    output_dir=Path("./out/2026Q1"),
    suffix="en",
)
```

### 5.2 结合 `--to-pdf` 的一键双语归档

```bash
python run.py \
    --input ./contracts --target en --domain legal \
    --glossary ./glossaries/legal.csv \
    --output-dir ./out \
    --to-pdf --pdf-engine auto --pdf-timeout 300
```

产物：

```
out/
├── <name>_en.docx            # 翻译结果
├── report.json               # 含 glossary_hits；若用 Python API 开了 LQA 还有 lqa_score
├── logs/translator.log
└── pdf/
    ├── original/<name>.pdf
    └── translated/<name>_en.pdf
```

---

## 6. 扩展建议

| 想做 | 改哪里 |
|------|--------|
| 给 TM 换向量相似度 | `translation_memory.py::find_matches` |
| 新增 LQA 规则 | `lqa.py::LQAChecker.check` |
| 把对比评分改成 BLEU / COMET | `comparison.py::_score_output` |
| 暴露 CLI `--tm-path` / `--enable-lqa` | `cli.py::build_parser`，然后在 `_build_pipeline` 处传参 |

参考 [CONTRIBUTING.md](../CONTRIBUTING.md) 的新增 adapter / LLM 提供方章节；扩展思路类似。

---

## 7. 相关文档

- 用户使用说明：[README.md](../README.md)
- 架构与数据流：[ARCHITECTURE.md](ARCHITECTURE.md)
- HTTP 接口：[API.md](API.md)
- 测试说明：[../tests/README.md](../tests/README.md)
- 故障排查：[TROUBLESHOOTING.md](TROUBLESHOOTING.md)
