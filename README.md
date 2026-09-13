# StockAIPredictor

一个**在你本机运行的金融数据分析工具**：汇总行情、技术指标、新闻情感与历史统计，用你自己配置的大模型做客观数据描述。

---

> # ⚠️ 免责声明（请务必先阅读）
> **本工具仅供研究学习，不构成投资建议。**
> **本工具不提供证券投资咨询业务，未取得中国证监会证券投资咨询业务资格，不提供任何具体证券品种的分析意见、买卖建议或价格预测。**
> **所有输出均为客观历史数据展示，用户应自行判断并承担投资决策的全部风险，开发者不对任何投资损失承担责任。**
>
> 详见 [DISCLAIMER.md](./DISCLAIMER.md)、[PRIVACY.md](./PRIVACY.md)、[TERMS_OF_SERVICE.md](./TERMS_OF_SERVICE.md)。

---

## 功能

- 多市场（A股 / 美股 / 港股）行情本地拉取与缓存；
- 技术指标计算（均线、MACD、RSI、布林带、ATR 等）与多因子统计；
- 新闻聚合与金融情感分析；
- 历史数据统计、相似形态回放与策略回测（仅统计验证）；
- 本地 GUI（PyQt6），数据不出本机；
- 应用内意见反馈、检查更新（仅提示，不自动下载）。

## 环境要求

- Windows 10/11（64 位），Python 3.11 ~ 3.13

## 安装

```bash
# 1. 克隆
git clone https://github.com/<your-username>/StockAIPredictor.git
cd StockAIPredictor

# 2. 创建虚拟环境
python -m venv venv
venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt
```

## 配置 API Key

```bash
copy .env.example .env
```

编辑 `.env`，填入你自己的大模型 API Key（任意 OpenAI 兼容端点，如通义千问 / DeepSeek / 智谱GLM / OpenAI）。

> Key 只保存在本机 `.env`，不会上传或记录。`.env` 已在 `.gitignore` 中。

## 运行

```bash
python -m app.main
```

1. 首次启动弹出免责声明，点"我已阅读并理解"；
2. 输入股票代码（如 `SH600519` / `AAPL`）；
3. 查看技术指标、新闻情感与统计结果；
4. 界面底部固定显示免责小字。

## 本地 AI 模式（可选）

默认用云端 API。你也可以切到**完全离线**的本地推理（数据不出本机、零 API 成本）：

1. 装 Ollama（https://ollama.com）；
2. `ollama pull moziAI:35b`（需 20GB 显存）或 `qwen2.5:7b`；
3. `.env` 设 `LOCAL_AI_ENABLED=true`、`STOCKAI_LLM_BACKEND=auto`。

详见 [LOCAL_AI_GUIDE.md](./LOCAL_AI_GUIDE.md)。

## 开发者模式（可选）

在 `.env` 中加一行 `DEV_MODE=true`，重启后会出现"开发者工具"页（清空缓存、查看日志），更新检查走 dev 频道。默认关闭。

## 检查更新

菜单"帮助 → 检查更新"：仅查询 GitHub Release 并弹窗提示，由你自行决定是否下载，**程序绝不自动下载或替换**。

## 隐私

不收集、不存储、不传输任何用户个人信息或金融数据，所有处理在本地完成。见 [PRIVACY.md](./PRIVACY.md)。

## 社区

- 贡献：[CONTRIBUTING.md](./CONTRIBUTING.md)
- 行为准则：[CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md)
- 安全：[SECURITY.md](./SECURITY.md)
- 反馈：菜单"帮助 → 意见反馈"（跳转 GitHub Issues，不上传数据）

## ❤️ 支持开发者

这个项目由我利用课余时间独立开发维护。你的支持将用于：

- 支付 AI API 调用费用
- 服务器和域名成本
- 持续的功能开发和文档完善

如果这个工具对你有帮助，欢迎通过以下方式支持：

- **爱发电（推荐，支持支付宝）**：https://afdian.com/shuying07
- **GitHub Sponsors**：https://github.com/sponsors/ShuYing07

您的每一份支持，都是我持续更新的动力 🙏

## 许可证

[MIT License](./LICENSE)，**仅供研究学习使用**。
