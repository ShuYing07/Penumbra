# 常见问题（FAQ）

## 🔑 API Key 配置

### Q: 需要 API Key 吗？
A: **基础功能不需要**。行情展示、K线、技术指标、回测、股票大全等纯数据功能全部免费可用。
**AI 分析功能**（多空辩论、综合报告）需要配置至少一个 OpenAI 兼容的 API Key，推荐 DeepSeek。

### Q: 如何配置 API Key？
A: 两种方式：
1. **启动引导**：首次启动时在欢迎窗口直接粘贴 Key，或点"跳过"稍后配置；
2. **手动配置**：复制 `.env.example` 为 `.env`，填入对应 Key：
   ```
   DEEPSEEK_API_KEY=sk-xxx     # https://platform.deepseek.com
   QWEN_API_KEY=sk-xxx         # 通义千问 https://dashscope.aliyun.com
   GLM_API_KEY=xxx             # 智谱 https://open.bigmodel.cn
   GROQ_API_KEY=gsk_xxx        # https://console.groq.com
   SILICONFLOW_API_KEY=sk-xxx  # 硅基流动 https://siliconflow.cn
   ```
   Key 只存本机 `.env`，绝不上传。

### Q: 没有 API Key 能用吗？
A: 能。程序自动降级到**本地模型**（若已装 Ollama）或 **MOCK 演示模式**（展示完整分析流程但不联网）。

## 📊 数据源说明

### Q: 沪深300等指数数据来自哪里？
A: A股指数走 **AKShare** 专用接口（东财 `index_zh_a_hist` → 新浪 `stock_zh_index_daily` → Tushare），失败自动降级到 yfinance，再到本地缓存。
- 输入 `000300` / `sh000300` / `000300.SS` 均可识别为沪深300；
- 已内置 12 个指数映射（沪深300、中证500、上证50、科创50、创业板指、深证成指等）；
- 缓存新鲜度 7 天，长假/休市不会反复联网。

### Q: 个股数据来自哪里？
A: 多源冗余 + 自动降级：
- **A股**：AKShare（东财→新浪→腾讯），主源失败自动切换；
- **美股/港股**：yfinance，自动检测代理可用性（Clash 127.0.0.1:7897）；
- **实时价**：新浪/东财实时接口，休市时自动用最近收盘价兜底。

### Q: 数据多久更新一次？
A: 日线按需增量更新（缓存 7 天新鲜度内直接用缓存）；市场概览每 30 秒自动刷新；个股分析每次实时拉取。

## 🤖 本地模型

### Q: 如何完全离线使用？
A: 1) 安装 Ollama（https://ollama.com）；2) 拉取模型 `ollama pull qwen3:7b`；3) 程序自动检测本地模型并降级使用。

### Q: models/ 目录是空的？
A: 正常。`models/` 用于存放可选本地大模型（如 Qwen2.5-3B-Instruct、Kronos），需手动下载放置，详见 [models/README.md](../models/README.md)。不下载也不影响使用——自动走云端 API 或 MOCK。

## 🐞 常见报错

### Q: 分析结果全是 [MOCK]？
A: 说明没有配置 API Key 且未安装本地模型。配置 Key 后即走真实 AI；或勾选"离线演示"继续用 MOCK。

### Q: 网络失败怎么办？
A: 程序自动降级：状态栏显示红色提示 + "重试"按钮，数据从本地缓存读取；无缓存则加载示例数据（贵州茅台）。启动时不会因网络问题阻塞。

### Q: 提示 database is locked / no such table？
A: 首次运行会自动建表（decisions、trades、positions、analysis_history 等）。`database is locked` 说明上次未正常退出，删除 `~/.shuying/memory.db-journal` 后重开即可。

### Q: K线图 Y 轴显示 0.1~0.9 或空白？
A: 说明该代码暂时无数据。检查：1) 代码是否正确（A股 600519，美股 AAPL，港股 0700.HK，指数 000300）；2) 网络是否可用；3) 稍后重试（数据源会自动降级）。

## 📁 数据与隐私

### Q: 数据存在哪里？
A: 全部在本地：`~/.shuying/`（SQLite 记忆库）+ 项目 `data/`（行情缓存）。无账号、无云同步、无任何上传。

### Q: 支持 Mac/Linux 吗？
A: 源码版支持（Python 3.11+）。一键打包版目前仅 Windows。

## ⚖️ 合规

### Q: 这是荐股软件吗？
A: 不是。本工具为开源金融数据分析软件，仅做客观数据展示与历史统计，不提供任何买卖建议、价格预测或个股推荐。详见 [DISCLAIMER.md](../DISCLAIMER.md)。
