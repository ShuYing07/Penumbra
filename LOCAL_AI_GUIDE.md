# 本地 AI 配置指南

本指南教你把程序切到**完全离线的本地 AI 推理**模式（不耗云端 API 额度、数据不出本机）。

> 合规提醒：本地模型同样只做客观数据描述，不构成投资建议。

## 硬件要求（重要）

| 模型 | 参数量 | 硬件 | 说明 |
|---|---|---|---|
| Kronos-small（K线预测） | 24.7M | 普通 CPU | 本机即可，已集成 |
| MoziAI-35B（金融对话） | ~15.5GB | **20GB 以上显存 GPU** | 纯 CPU 跑不动，请先确认有独显 |
| Qwen2.5-7B（通用兜底） | ~4.5GB(Q4) | 8GB 显存 / 16GB 内存 | 无独显也能勉强跑 |

## 第一步：安装 Ollama

1. 访问 https://ollama.com 下载对应系统安装包并安装；
2. 启动后确认任务栏有 Ollama 图标（默认监听 http://localhost:11434）。

## 第二步：拉取模型

```bash
# 金融专用（需 20GB 显存）
ollama pull moziAI:35b

# 或通用轻量兜底（无独显也能跑）
ollama pull qwen2.5:7b-instruct-q4_K_M
```

## 第三步：配置 .env

复制 `.env.example` 为 `.env`，按需要改：

```ini
# 优先本地推理
LOCAL_AI_ENABLED=true
# 本地模型名（与 ollama pull 的一致）
OLLAMA_MODEL_NAME=moziAI:35b
# 引擎切到 local（纯本地）或 auto（云端失败自动降级本地）
STOCKAI_LLM_BACKEND=auto
```

## 第四步（可选）：GGUF 直读后端

如果你从 Hugging Face 下载了 GGUF 模型文件：

1. 安装 llama-cpp-python（Windows 需编译工具，推荐用预编译 wheel）：
   ```powershell
   pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
   ```
2. 在 `.env` 中填入文件路径：
   ```ini
   LOCAL_MODEL_PATH=D:\models\moziai.Q4_K_M.gguf
   ```

## Kronos K线预测

已随程序集成（`core/ml/kronos_forecast.py`）。首次会自动从 Hugging Face 拉权重：

```python
from transformers import AutoModel
model = AutoModel.from_pretrained("NeoQuasar/Kronos-small", trust_remote_code=True)
```

仅 24.7M 参数，普通电脑可跑。

## 验证本地模式生效

```powershell
cd D:\StockAIPredictor
venv\Scripts\python.exe -m app.main --localping
```

会打印 Ollama 是否就绪、已装模型、一次真实本地推理结果。
