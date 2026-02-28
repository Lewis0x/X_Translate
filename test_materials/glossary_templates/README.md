# 场景术语模板目录

本目录提供不同专业场景的术语表示例（CSV）：

- `general_glossary.csv`
- `legal_glossary.csv`
- `finance_glossary.csv`
- `it_glossary.csv`
- `medical_glossary.csv`
- `academic_glossary.csv`

CSV 字段说明：

- `source`: 原文术语
- `target`: 译文术语
- `case_sensitive`: 是否大小写敏感（`true/false`）
- `lock`: 是否锁定不翻译（`true/false`）

使用示例：

```bash
python run.py --input ./test_materials --target en --source auto --domain legal --glossary ./test_materials/glossary_templates/legal_glossary.csv
```
