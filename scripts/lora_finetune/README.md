# 领域微调（可选）· 使用说明

疏影·知微 支持对本地金融模型做 LoRA 领域微调，参考 finance-specialist-v7 的
LoRA 配置（r=8, alpha=16, attention-only）。

## 前置依赖（需手动安装）

```bash
pip install peft transformers datasets accelerate trl
```

## 准备训练数据

在 `scripts/lora_finetune/data/` 下放置 JSON Lines 文件（*.jsonl），每行一条：

```json
{"instruction": "贵州茅台2026年三季度营收多少？", "input": "", "output": "营收同比增长15%。"}
{"instruction": "总结这篇研报要点", "input": "<研报正文>", "output": "<3-5条要点>"}
{"instruction": "判断该新闻情绪", "input": "公司发布回购公告，股价大涨", "output": "利好"}
```

建议覆盖三类任务：财报QA对 / 研报摘要 / 新闻情感标注。

## 运行训练

```bash
python scripts/lora_finetune/finetune_example.py --base-model Qwen/Qwen2.5-7B-Instruct
```

## 导出到 Ollama（可选）

训练完成后合并权重并导出为 GGUF，再 `ollama create` 为本地模型，
然后在设置/ config.yaml 的 `models.finance_engine` 中指定模型名，
程序即优先使用该金融专用模型。

## 注意事项

- 本脚本是占位模板：无训练数据时不执行训练（打印提示并退出）；
- 模型下载体积大，请在有 GPU 且网络允许的环境运行；
- 微调不改变核心功能：程序始终可无模型运行（自动降级云端/规则）。
