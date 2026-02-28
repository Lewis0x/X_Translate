# 测试素材目录

将用于翻译测试的文件放在此目录，例如：

- docx 文档
- xlsx 报表
- pdf 文本型文件

建议按场景分子目录：

- legal/
- finance/
- general/

你可以直接将该目录作为输入路径：

```bash
python run.py --input ./test_materials --target en --source auto --domain legal
```
