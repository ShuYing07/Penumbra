# 疏影·知微 v0.7.0 市场对标报告
## —— 市面最佳同类产品全面对标与差距分析

> **调研日期**：2026-09-29
> **对象**：疏影·知微（开源桌面金融研究终端，PyQt6，GitHub: ShuYing07/Penumbra，v0.7.0）
> **对标产品**：OpenBB、TradingView、同花顺（iFinD/普通版+i问财）、东方财富（Choice/免费版+妙想）、Freqtrade、Backtrader、QuantConnect/LEAN、Finviz、StockAnalysis.com、Polygon.io（现 Massive）、Bloomberg Terminal（行业天花板参照）
> **范围说明**：本报告为**外部对标研究**，聚焦"我的程序功能是否达到市面最好水平"；程序本地功能可用性自测不在本报告范围（可另立任务执行）。
> **来源类型约定**：`【官方文档】`= 官网/官方 docs/定价页/GitHub 仓库；`【公开评测】`= 第三方评测/媒体/论文；`【一方称】`= 厂商自述（未独立验证）。每条关键论断均附来源 URL。价格与功能随时间变化，均为调研时点快照，以官方页面为准。

---

## 1. 执行摘要

1. **组合定位无直接同构竞品，差异化占位真实存在。** 市面没有任何一个产品同时具备"本地优先 + 免费开源 + AI 多模型 + A股/港股/美股多市场 + 数据→图表→AI→回测→模拟→合规审计全流程"。最接近的参照系是 OpenBB（开源数据平台 + AI Copilot）与 QuantConnect（开源引擎 + 云平台），但两者原生都不支持 A 股/港股；国内的同花顺 iFinD 与东方财富 Choice 数据最深但闭源、昂贵、面向机构。疏影·知微的"本地隐私 + 免费开源 + 中国市场"组合是空白位。

2. **三大核心差距决定"是否市面最好"：**
   - **回测严谨性**：行业先进水平已到"绩效指标全 + 样本外/Walk-Forward + 前视偏差审计"（Freqtrade 的 `lookahead-analysis`/`recursive-analysis` 命令、QuantConnect 的全套 PortfolioStatistics 与云端参数优化热力图），疏影目前是"回测 + 组合回测 + 参数寻优"级别，缺偏差审计与滚动样本外工具。
   - **图表交互深度**：TradingView（110+ 绘图工具、400+ 指标、多图联动、K 线回放、Ctrl+K）与同花顺（F5/F10 快捷键、十字光标、画线、区间统计）是标杆；疏影已有缩放/平移/十字光标/均线/布林带/成交量副图，缺绘图工具与多时间框架。
   - **AI 集成形态**：行业领先者已从"文本问答"进化到"可调用工具的 Agent"——OpenBB Copilot + MCP server + 开源 Agent Rita、同花顺 iFinD MCP（2026）、QuantConnect Mia、Bloomberg ASKB（带引用回答）。疏影已有 DeepSeek/通义/GLM/Groq/OpenAI/Ollama 多模型路由 + 离线 mock 降级（这本身强于多数竞品），但输出仍是文本，不能替用户执行查询/回测/落盘。

3. **数据层是最大软肋、也是最大机会。** 免费源（AKShare/yfinance）的延迟与稳定性天然不如 Polygon/Massive（实时 <20ms、公开状态页 90 天 Stocks 99.97%）与国内 Level-2（同花顺宣称比普通行情快 3 秒以上）。建议学习 Polygon 的**分层透明定价与公开状态页**、OpenBB 的**数据接入层与消费端解耦**架构，做"免费优先 + 可选付费增强源"，而不是硬碰免费源的延迟上限。

4. **值得直接复用的成熟设计（按成本从低到高）**：Freqtrade 的偏差审计命令化、QuantConnect 的回测报告 PDF 化、OpenBB 的 MCP server 思路、同花顺的快捷键体系、Finviz 的市值热力图、StockAnalysis.com 的"免注册即用"免费门槛、Polygon 的公开状态页、Backtrader 的 Analyzer 插件化架构。这些单项都可用有限工作量追平或超越。

5. **商业与合规红线已明确。** OpenBB 的教训（纯开源数据平台未找到可持续商业模式，2026-08-25 宣布整个产品套件转向宽松许可开源）与 Bloomberg 的护城河（数据深度 + 网络效应）都不可模仿；同花顺式"投顾话术 + 高端荐股订阅"营销（金融大师 8 万元/年）必须回避。疏影应坚持"本地优先、隐私优先、免费开源、不做投资建议"，把**合规审计 + 隐私承诺明示化**做成差异化卖点（见第 5 章"不该做"清单）。

---

## 2. 对标总表

图例：✔ = 达到/超过市面领先水平；✘ = 不具备或明显短板；部分 = 具备但不完整。关键事实见单元格，详情与来源见第 3、6 章。

| 能力维度 | OpenBB | TradingView | 同花顺(iFinD/普通) | 东财Choice | Freqtrade | Backtrader | QuantConnect | Finviz | StockAnalysis | Polygon.io(Massive) | Bloomberg |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 数据覆盖与延迟 | 部分：聚合100+供应商，无自有行情，延迟取决供应商档位 | ✔：350万+品种全球；免费延迟10-15分钟，实时需加购 | ✔：A股/港股/美股/基金/期货全，Level-2付费，免费版基本同步 | ✔：50万+标的，历史溯至19世纪 | 部分：仅加密，实盘WebSocket实时 | 部分：CSV/Yahoo/pandas，无实时推送 | ✔：多资产多分辨率，数据市场数百TB | 部分：美股+期货/外汇/BTC；免费延迟15-20分钟 | 部分：13万+全球标的，美股深度为主 | ✔：美股全+期权/指数/外汇/加密/CME期货；实时<20ms(Advanced档) | ✔：3,500万工具，毫秒级机构实时 |
| 行情接口稳定性 | 部分：本地FastAPI+供应商，无公开SLA | 部分：无开放API，Webhook限流60次/分，无公开SLA | 部分：QPS≤20、周配额透明；无公开故障记录 | 部分：截面/序列≤700次/分；无公开故障记录 | 部分：CCXT聚合100+交易所；无公开SLA | ✘：内置Yahoo feed已被上游变更破坏 | ✔：自建清洗、point-in-time交付，对接25+券商 | 部分：无API（仅受限导出） | 部分：无API | ✔：公开状态页，90天Stocks 99.97%、REST 99.88% | ✔：机构级BLPAPI，行业口碑 |
| K线/图表交互 | 部分：Workspace拖拽widget，非终端级 | ✔：行业标杆——110+绘图工具、400+指标、多图联动、K线回放 | ✔：F5/F10快捷键、十字光标、画线、区间统计、多图组合 | ✔：多面板暗色终端、F9深度资料 | 部分：FreqUI Web（明暗主题） | 部分：matplotlib静态出图，无Web交互 | 部分：回测图表+PDF报告，Research(Jupyter)自绘 | 部分：Elite交互图15+绘图工具；免费档静态图 | 部分：100+技术研究，深度弱于TV | ✘：纯API无UI | 部分：G<GO>取数型，DIY弱于TV |
| AI/LLM集成 | ✔：Copilot自然语言+Agent Rita(MIT)+MCP server | 部分：AI筛选器(2026-08公测)、AI Copilot副驾，深度有限 | ✔：i问财NL选股+Hithink大模型+MCP(2026) | ✔：妙想大模型+MCP/Skills，首批网信办备案 | 部分：FreqAI自适应ML(非LLM)，无对话 | ✘：无 | ✔：Mia agentic AI+MCP，嵌入研究闭环 | ✘：无 | ✘：无 | ✘：无 | ✔：BloombergGPT→新闻/电话会摘要→ASKB agent |
| 回测引擎 | ✘：不内置，靠Python生态 | 部分：Strategy Tester指标齐，默认收盘价成交、无WFA | 部分：SuperMind回测(Alpha/Beta/Sharpe/回撤)，无WFA | ✘：仅取数+组合，无完整回测引擎 | ✔：指标全+lookahead/recursive偏差审计；无原生WFA | 部分：Analyzer插件化指标全；无WFA，项目停更 | 部分：绩效统计全+云参数优化热力图；无一键WFA | 部分：Elite轻量日线单条件回测 | ✘：无 | ✘：无（数据可被回测） | 部分：BQuant/BQL自建 |
| 策略研究生态 | 部分：App Marketplace、200+扩展 | ✔：15万+脚本，发布/邀请/受保护商业化 | 部分：SuperMind社区、问财选股池 | 部分：条件选股/组合管理（机构向） | ✔：freqtrade-strategies仓库一键加载 | ✘：无官方分享机制 | ✔：Dataset Market+Alpha Streams+Strategy Explorer | ✘：无 | ✘：无 | ✘：无 | ✘：封闭机构内共享 |
| UI/UX设计 | 部分：拖拽dashboard、暗色、Ctrl+M | ✔：Ctrl+K命令面板、可自定义快捷键、默认暗色 | ✔：C端快捷键体系最成熟(F5/F10/F12等) | ✔：暗色多屏专业终端、快捷命令 | 部分：FreqUI+Telegram，无桌面GUI | ✘：无GUI | 部分：Web IDE+Jupyter，无桌面GUI | 部分：信息密度极高、市值热力图 | 部分：极简、Pro暗色、移动App | ✘：无UI | ✔：<GO>助记符+专用键盘 |
| 隐私与本地运行 | ✔：ODP本地localhost、Workspace可VPC/on-prem，"数据不用于训练" | ✘：云端SaaS，Pine沙箱 | ✘：云端为主 | ✘：云端为主 | ✔：完全本地，数据全在本机 | ✔：完全本地 | 部分：LEAN可完全本地，云/本地分离 | ✘：纯云端 | ✘：纯云端 | ✘：云API | ✘：专有云端 |
| 开源程度与许可证 | 部分：ODP=AGPLv3；2026-08-25宣布全套转宽松许可 | ✘：主平台闭源（Lightweight Charts开源，Apache-2.0） | ✘：闭源 | ✘：闭源 | ✔：GPL-3.0 | ✔：GPL-3.0 | ✔：Apache-2.0 | ✘：闭源 | ✘：闭源 | 部分：核心闭源，官方SDK=MIT | ✘：完全专有 |
| 免费可用性 | ✔：Community免费(20 Copilot/天)；Lite $1,200/年 | ✔：免费层延迟数据；Essential $12.95/月起 | ✔：免费看盘；Level-2约¥88/年起 | ✘：机构付费约¥5,800-18,000/年 | ✔：完全免费 | ✔：完全免费 | ✔：Free层无限回测；Researcher约$60/月起 | ✔：免费延迟；Elite $299.5/年 | ✔：免费免注册；Pro $79/年 | ✔：$0档5次/分EOD；实时Advanced $199/月 | ✘：$31,980/年，无免费 |
| 多市场支持 | 部分：原生美股/加密/宏观为主，A股港股靠AKShare/Tushare扩展 | ✔：全球350万+品种，含沪深A股板块页 | ✔：A股/港股/美股/基金/期货/外汇 | ✔：沪京深/港/台/美/韩/日 | ✘：仅加密 | 部分：IB/Oanda/CSV，无原生A股港股 | 部分：多资产，无原生A股/港股 | ✘：无A股/港股 | 部分：有ticker但深度弱 | ✘：无A股/港股 | ✔：全资产全球含A股工具包 |
| 社区与文档 | ✔：GitHub 73.6k stars、140k+用户、Discord、文档全 | ✔：5000万+用户量级、15万+脚本 | ✔：同花顺APP月活约3,786万(行业第一) | 部分：数据学院/机构向，C端社区弱 | ✔：54.9k stars、32,999+ commits、中文文档站 | 部分：23.4k stars但停更，文档详尽 | ✔：546K注册用户、论坛+Discord | 部分：知识库完善，无社区 | 部分：无社区，活跃changelog | ✔：多语言SDK、Discord、公开状态页 | 部分：31.5-35.5万订阅者，HELP系统 |

---

## 3. 逐产品剖析

### 3.1 OpenBB（开源数据平台 + 企业 Workspace）
**定位**：分析师/量化研究员/AI agent 用的开源金融数据平台。开源主体 Open Data Platform（ODP，AGPLv3），商业 Workspace 为企业 UI 层；**2026-08-25 官方宣布将整个产品套件（Workspace/ODP/Copilot/Excel Add-in）以宽松许可证开源**【官方文档：https://openbb.co/blog/ 、https://openbb.co/pricing/?type=bot 】。
**亮点**：①"连接一次、随处消费"架构——ODP 数据层与 Workspace/Excel/MCP/Python 消费端解耦；②AI-native 走得最远：Copilot 自然语言分析 + Agent Rita（MIT 开源可自托管）+ MCP server，把金融数据直接暴露给外部 LLM agent【官方文档：https://openbb.co/blog/introducing-agent-rita/ 】；③本地优先：ODP 跑本地 localhost，Workspace 支持 VPC/on-prem，"客户数据不用于训练"对机构合规友好【官方文档：https://openbb.co/security/ 】；④App Marketplace 生态（200+ 扩展，含 AKShare/Tushare 社区扩展接 A 股/港股）。
**值得借鉴**：数据接入层与消费 UI 解耦的架构；MCP server + 开源 agent 的做法；隐私承诺明示化。**教训**：纯开源 + 不收数据钱的模式未找到可持续商业模式（CEO 公告自述），最终整体开源——**技术架构值得抄，商业模式不可抄**。

### 3.2 TradingView
**定位**：全球最大云端图表/社交交易平台（闭源 SaaS；Lightweight Charts 以 Apache-2.0 开源引流）。用户量级 5000 万+【公开评测：https://www.pinecode.ai/learn/tradingview-pine-script-tutorial 】。
**亮点**：①图表交互行业标杆：110+ 绘图工具、400+ 预置指标、多图联动同步、K 线回放【官方文档：https://cn.tradingview.com/gopro/ 】；②**Ctrl+K 命令面板 + 可自定义快捷键 + 默认暗色主题**，把专业效率做到散户可用【官方文档：https://cn.tradingview.com/support/shortcuts/ 】；③15 万+ 社区脚本、每年新增约 5 万份、支持发布/仅邀请/受保护脚本商业化【官方文档：https://cn.tradingview.com/support/solutions/43000549905/ 】；④分层配额（图表数/指标数/历史 K 线/告警数）卡点清晰，年付 Essential $12.95 / Plus $29.95 / Premium $59.95 / Ultimate $199.95【官方文档：https://tw.tradingview.com/pricing/ ；公开评测：https://www.financialtechwiz.com/post/how-much-is-tradingview/ 】。
**局限**：云端 SaaS、无开放 API、免费层延迟 10-15 分钟、实时数据另购（美股直连约 $2-3/月、Bundle 约 $9.95/月【公开评测：https://chartwisehub.com/tradingview-real-time-data/ 】）；Strategy Tester 默认收盘价成交有前视偏差隐患、无原生 walk-forward【公开评测：https://backtestme.com/guides/tradingview-backtesting/ 】。
**值得借鉴**：命令面板与快捷键体系、免费即用完整图表的转化漏斗、分层配额设计、Lightweight Charts 开源引流策略。

### 3.3 同花顺（iFinD / 普通版+i问财）
**定位**：A 股生态最深的国产平台——机构级 iFinD 数据终端 + C 端免费看盘客户端 + i问财自然语言选股。
**亮点**：①数据全覆盖（A股/港股/美股/基金/期货/债券/宏观），iFinD 接口**限流/配额/错误码工程化透明**（单函数 QPS≤10、账号总 QPS≤20、行情 1.5 亿条/周）【官方文档：https://quantapi.51ifind.com/ 】；②**i问财"自然语言→结构化选股→回测选股池"是 C 端 AI 范式**，已升级为 Hithink 金融大模型智能体【官方文档：https://quant.10jqka.com.cn/view/dataplatform/detail/398 】，2026 年上线 **iFinD MCP** 把行情/财务/公告封装为 agent 可调用工具【一方称：https://mcp.51ifind.com/ 】；③C 端快捷键体系最成熟（F5 分时/K线、F10 公司资料、F12 下单、Alt+1~9 多图、十字光标、画线、区间统计）【官方文档：https://www.10jqka.com.cn/ad_mar/man/ 】；④免费看盘 + Level-2 约 ¥88/年起 + 高端投顾订阅的分层【一方称：http://pay.10jqka.com.cn/eq3_release.php?op=appvpos&platform=ipad&s_id=101 】。月活约 3,786 万（2026-08，行业第一）【公开评测：https://finance.sina.com.cn/stock/relnews/cn/2026-09-20/doc-inismvpc2554893.shtml 】。
**价格参考**：iFinD 标准账号约 1.4 万元/年（2026-01 报道，官方不公开标价）【公开评测：https://stcn.com/article/detail/3620915.html 】。
**值得借鉴**：接口限流文档化、数据 MCP 化、快捷键体系、免费层 + 增值付费点设计。**警示**：投顾式营销（金融大师 8 万元/年、荐股话术）不可模仿。

### 3.4 东方财富（Choice / 免费版+妙想）
**定位**：机构数据终端 Choice + 免费门户/APP（月活约 1,894 万，行业第二）+ 妙想金融大模型【公开评测：https://finance.sina.com.cn/stock/relnews/cn/2026-09-20/doc-inismvpc2554893.shtml 】。
**亮点**：①数据历史极长（可溯至 19 世纪 80 年代）、覆盖沪京深/港/台/美/韩/日、核心指标 280 万+【一方称：https://www.stcn.com/article/detail/1223958.html 】；②**妙想为首批网信办备案金融大模型**，发布妙想 MCP 与 Skills 押注 Agent 生态【一方称：https://choice.eastmoney.com/ ；公开评测：http://finance.ce.cn/stock/gsgdbd/202401/11/t20240111_38862416.shtml 】；③**股吧社区是护城河**：注册约 4.2 亿、日活约 300 万、日均发帖超百万【公开评测：https://caifuhao.eastmoney.com/news/20260529115729216434840 】；④跨 Windows/macOS/国产 Linux。
**价格参考**：Choice 活动价曾列 ¥5,800/年（专业版 ¥6,980）、2026-01 报道标准账号约 1.8 万元/年【公开评测：https://stcn.com/article/detail/3620915.html 】；妙想进阶版 ¥518/季、专业版 ¥818/季【公开评测：https://finance.sina.com.cn/roll/2025-08-23/doc-infmxxvk4723646.shtml 】。
**短板**：量化侧偏"取数 + 组合管理"，EMQuantAPI 无类似 SuperMind 的完整 Python 回测引擎【官方文档：https://quantapi.eastmoney.com/Upload/EMQuantAPI_Python.pdf 】。
**值得借鉴**：Agent 生态布局（MCP/Skills）、社区资产、跨平台适配、按使用次数分级的 C 端 AI 变现（仅作了解，不与疏影定位冲突）。

### 3.5 Freqtrade
**定位**：免费开源（GPL-3.0）加密货币交易机器人，GitHub 54.9k stars，社区极活跃【官方文档：https://github.com/freqtrade/freqtrade 】。
**亮点**：①**`lookahead-analysis`（前视偏差）/`recursive-analysis`（递归公式）审计命令**——把回测健壮性检查工具化，行业独家【官方文档：https://docs.freqtrade.io/en/2026.1/bot-usage/ 】；②FreqAI 实盘自适应重训练闭环 + JOSS 论文【公开评测/论文：https://joss.theoj.org/papers/10.21105/joss.04864.pdf 】；③FreqUI Web（明暗主题）+ Telegram 远程控制；④freqtrade-strategies 社区仓库（5.5k stars），**策略即 Python 文件，复制进 `user_data/strategies/` 即可加载**【官方文档：https://github.com/freqtrade/freqtrade-strategies 】。
**局限**：仅加密货币；**无原生 walk-forward 命令**（第三方评测确认【公开评测：https://www.backtestscore.com/tools/freqtrade 】，官方命令列表亦无该项，仅有 `--timerange` 手动分段 + Hyperopt 参数优化）。
**值得借鉴**：偏差审计命令化、策略即文件、Hyperopt 文档自警过拟合的诚实态度。

### 3.6 Backtrader
**定位**：经典开源 Python 回测框架（GPL-3.0），23.4k stars，但官方实质停更（最后 PyPI 发布 2023-04）【官方文档：https://pypi.org/project/backtrader/1.9.74.123/ 】。
**亮点**：①**Analyzer 插件化架构**（TimeReturn/SharpeRatio/DrawDown/TradeAnalyzer/SQN/Transactions 可组合）【官方文档：https://backtrader.ru/docu/analyzers/analyzers-reference/ 】；②122 个内置技术指标 + 自定义指标易写；③多数据源抽象（CSV/Yahoo/pandas/IB/Oanda 统一接口）。
**局限与警示**：内置 YahooFinanceData 已被 yfinance 上游变更破坏【公开评测：https://rmbell09-lang.github.io/tradesight/blog/backtrader-alternative-python-2026.html 】——**依赖第三方免费源的脆弱性实证**；无 GUI、无内置 walk-forward、GPL copyleft 对商业分发不友好。
**值得借鉴**：Analyzer 插件模式可直接移植到疏影回测模块设计。

### 3.7 QuantConnect / LEAN
**定位**：Apache-2.0 开源引擎 LEAN + 商业量化云平台，546K 注册用户、GitHub 21.8k stars【官方文档：https://github.com/QuantConnect/Lean ；https://www.quantconnect.com/forum/discussion/10888 】。
**亮点**：①**引擎/云分离**：LEAN 可完全本地跑（`pip install lean` + Docker），云端靠数据/算力/AI 变现【官方文档：https://github.com/QuantConnect/Lean 】；②**Mia agentic AI 结对编程助手 + 开放 MCP Server**（桥接 Cursor/Devin/Claude Desktop）【官方文档：https://www.quantconnect.com/docs/v2/ai-assistance/mcp-server/key-concepts 】；③生态最完整：Dataset Market（数百 TB 数据）+ Alpha Streams（alpha 授权市场）+ Strategy Explorer（官方+社区策略可 clone）【官方文档：https://www.quantconnect.com/announcements/15944/pioneering-a-free-market-for-alpha/ 】；④回测自动生成 PDF 报告（Performance/Backtest/Portfolio/Search）。
**价格**：Free 层含所有资产 minute-daily 数据 + 无限回测；付费 Researcher 约 $60/月（官方 Tradier 合作页确认）【官方文档：https://www.quantconnect.com/brokerages/tradier 】。
**局限**：不原生支持 A 股/港股（需自定义数据接口导入 Tushare/Baostock）；无"一键 walk-forward"产品（官方文档未找到权威来源，需 Notebook 自行滚动）；云价不透明（customizable）。
**值得借鉴**：PDF 回测报告、AI 嵌入研究闭环、本地/云双轨、数据市场思路。

### 3.8 Finviz
**定位**：私有闭源 Web screener，主打极速可视化。免费档延迟行情，Elite $39.50/月或 $299.50/年【官方文档：https://finviz.com/knowledge-base/getting-started/plans-pricing/finviz-free-vs-elite 】。
**亮点**：①**市值热力图是行业范式**——一眼看全市场板块强弱；②70+ 过滤器（基本面/技术面/描述）三 tab 极速 screener，免费档即可用（NASDAQ 延迟 15 分钟、NYSE/AMEX 20 分钟）【官方文档：https://finviz.com/knowledge-base/learn-reference/data-sources-calculations/update-frequency 】；③Elite 交互图（15+ 绘图工具、11 个 overlay、19 个技术指标、多时间框架）+ 轻量日线回测【官方文档：https://finviz.com/knowledge-base/charts-technical-analysis/customization-drawing/drawing-tools 】。
**局限**：无 API、无 AI、无 A 股/港股、回测仅日线单条件、无样本外/WFA。
**值得借鉴**：热力图范式、免费档即给完整 screener 的转化漏斗、极速渲染的信息密度设计。

### 3.9 StockAnalysis.com
**定位**：闭源 Web 基础研究站——"机构级数据（S&P Global Compustat）+ 免注册免费"。免费档 $0（无需注册），Pro $79/年，Unlimited $199/年【公开评测：https://www.financialtechwiz.com/post/stockanalysis-review/ 】。
**亮点**：①13 万+ 全球股票/ETF/基金，财务数据主源 S&P Global，Fiscal.AI 财报披露后分钟级更新【官方文档：https://stockanalysis.com/changelog/ 】；②免费零门槛（无注册、无信用卡）；③"As Reported"财报视图 + 极简无干扰 UI + 100+ 技术研究。
**局限**：无回测、无 AI、无 API——明确的能力边界（"数据查阅站"而非"研究工作台"）。
**值得借鉴**：免费零门槛策略、专业数据源可信度、极简 UI 的信息组织。

### 3.10 Polygon.io（现 Massive.com）
**定位**：行情数据 API 基础设施（非终端），**2025-10-30 更名 Massive.com，API/账户无缝迁移**（api.polygon.io 与 api.massive.com 并行）【官方文档：https://staging.polygon.io/ ；公开评测：https://www.prwireindia.com/press-release/polygon-io-is-now-massive 】。核心数据服务闭源，官方 SDK（Python/JVM）MIT 开源【官方文档：https://github.com/polygon-io 】。
**亮点**：①**分层定价极清晰**：$0（EOD、5 calls/分、2 年历史）→ Starter $29（15 分钟延迟、unlimited）→ Developer $79（+trades、10 年）→ Advanced $199（实时 <20ms、20+ 年）→ Business $1,999/月【官方文档：https://polygon.io/pricing 】；②REST + WebSocket + S3 flat files 三形态交付；③**公开状态页按组件披露 90 天 uptime**（Stocks 99.97%、Market Data REST 99.88%、WebSocket 100%）【官方文档：https://polygonstatus.com 】。
**局限**：无 A 股/港股、无终端 UI、无回测引擎。
**值得借鉴**：分层透明定价、公开状态页透明度、三形态交付。**对疏影的直接启示**：它是数据上游供应商而非终端竞品——可作为"可选付费增强源"的候选供应商。

### 3.11 Bloomberg Terminal（行业天花板参照）
**定位**：机构级金融数据/分析/交易/即时通讯一体化工作站，**完全专有**，无免费层，单座 **$31,980/年**（2025-01-01 起、涨 6.5%）【公开评测：https://godeldiscount.com/blog/bloomberg-terminal-cost-2026 ；https://www.stratrix.com/business-model/how-a-30k-terminal-funds-a ；https://investingintheageofai.com/claude-vs-bloomberg-terminal 】。
**亮点**：①数据深度护城河：整合 330+ 交易所、5,000+ 供应商、约 3,500 万种工具，债券/信用数据全球最深【官方文档：https://www.bloombergchina.com/solution/data-content/market-data/ 】；②**<GO> 助记符命令体系 + 专用键盘**（绿色 Action 键等），高手效率极致【官方文档：https://data.bloomberglp.com/professional/sites/10/Getting-Started-Guide-for-Students-English.pdf 】；③**AI 渐进落地**：BloombergGPT → AI 新闻摘要（2025-01）→ AI 财报电话会摘要 → 文档检索 → ASKB 对话式 agent（beta，带引用摘要），每条输出扎根自有数据【官方文档：https://www.bloombergchina.com/press/press-release-20250115/ ；一方称：https://assets.bbhub.io/professional/sites/27/1007635_BBGT_AI_Equity_Analyst_BCH_DIG_260325.pdf 】；④IB 即时通讯的网络效应（OTC 交易事实通讯层）。
**值得借鉴**：命令式导航思想（需图形化降门槛）、AI 每条输出带引用、数据深度护城河。**不可模仿**：价格、封闭性、机构销售模式。

---

## 4. 差距与优先级优化清单
（现状 = 疏影·知微 v0.7.0 功能基线；工作量估值为单人全栈开发口径）

### 高优先（决定"市面最好"的关键差距）

**P1. AI 从"文本问答"升级为"可调用工具的 Agent"｜工作量 M/L（4-8 周）**
- 现状差距：已有 DeepSeek/通义/GLM/Groq/OpenAI/Ollama 多模型路由 + 离线 mock 降级（优于多数竞品），但 AI 输出仍为纯文本，不能替用户查询行情/财报、跑回测、生成图表、落盘决策记录。
- 建议：给 AI 加工具调用层（查询行情 → 跑回测 → 生成图表卡片 → 写入决策记录/合规审计），输出结构化卡片而非纯文本；对外提供 **MCP server**，让 Claude/Cursor 等外部 agent 也可消费数据。
- 参考产品：OpenBB Copilot + Agent Rita + MCP【https://openbb.co/blog/introducing-agent-rita/ 】；同花顺 iFinD MCP【https://mcp.51ifind.com/ 】；QuantConnect Mia【https://www.quantconnect.com/docs/v2/ai-assistance/predefined-assistants/mia 】；Bloomberg ASKB。
- 这是拉开"市面最好"差距的最大单项，与现有多模型路由无缝衔接。

**P2. 回测引擎补"严谨性三件套"：样本外切分 + Walk-Forward + 偏差审计｜工作量 M（2-4 周）**
- 现状差距：已有回测/组合回测/参数寻优，但无 walk-forward、无样本外分段、无前视偏差/递归公式审计。行业先进水平已把这些做成标准动作。
- 建议：回测模块增加时间范围分段、walk-forward 滚动窗口（训练/测试分窗），参数寻优输出热力图 + 过拟合警告；**一键前视偏差扫描**（对同一策略用"当日收盘后数据"与"当日收盘前数据"各跑一遍比对）。
- 参考产品：Freqtrade `lookahead-analysis`/`recursive-analysis`【https://docs.freqtrade.io/en/2026.1/bot-usage/ 】；QuantConnect 云参数优化热力图 + Monte Carlo【https://www.quantconnect.com/pricing/ 】。

**P3. 图表交互补"绘图工具 + 多时间框架 + 多图联动"｜工作量 M（3-6 周）**
- 现状差距：已有缩放/平移/十字光标/均线/布林带/成交量副图，缺趋势线/水平线/斐波那契回撤/测量工具、多时间框架切换、多图布局与品种同步。
- 建议：优先做绘图四件套（趋势线/水平线/斐波那契回撤/测量）+ 多时间框架 + 双图联动（十字光标同步）；K 线回放作为二期。
- 参考产品：TradingView【https://cn.tradingview.com/gopro/ 】；Finviz Elite 绘图工具【https://finviz.com/knowledge-base/charts-technical-analysis/customization-drawing/drawing-tools 】；同花顺画线/区间统计。

**P4. 股票筛选器（结构化 Screener）+ 自然语言转条件｜工作量 M（3-5 周）**
- 现状差距：已有 1.8 万+ 股票大全（虚拟滚动），但无筛选器；市面免费档标配 screener。
- 建议：给股票大全加可组合、可保存的筛选器（价格/市值/PE/涨跌幅/技术指标），本地 LLM 把自然语言转成筛选条件（离线可用）；结果一键进 K 线或回测。
- 参考产品：Finviz screener【https://finviz.com/knowledge-base/ 】；同花顺 i问财【https://www.iwencai.com 】；TradingView AI Screener【https://www.tradingview.com/blog/tw/ai-screener-60101/ 】。

### 中优先（显著提升专业度与可用性）

**P5. 数据层：适配器抽象 + 公开状态页 + 缓存/重试 + 可选付费增强源｜工作量 M（3-6 周）**
- 现状差距：AKShare/yfinance 免费源延迟与稳定性不可控（对照 Polygon 实时 <20ms + 公开状态页 99.9% 量级；国内 Level-2 快数秒）。
- 建议：①统一数据适配器接口、供应商可插拔（OpenBB "connect once, consume everywhere"）；②内置数据源健康检查 + 状态页（Polygon 模式）；③本地缓存 + 自动重试 + 失效降级；④预留"用户自带 Key 的可选付费源"（Polygon Advanced 档 / 国内 Level-2）作为高级选项，保持免费优先。
- 参考产品：OpenBB ODP【https://www.openbb.co/products/odp 】；Polygon/Massive【https://polygon.io/pricing 、https://polygonstatus.com 】。

**P6. 回测报告标准化与可视化（PDF/HTML 一键导出）｜工作量 S/M（2-3 周）**
- 现状差距：有回测/组合回测，但报告形式待标准化。
- 建议：定义统一绩效报告 schema（收益/夏普/最大回撤/胜率/盈亏比/多空分解/权益曲线），Web 端可视图表 + 一键导出 PDF/HTML，同步写入合规审计。
- 参考产品：QuantConnect 自动 PDF 报告【https://www.quantconnect.com/docs/v2/cloud-platform/backtesting/ 】；Freqtrade JSON 导出【https://docs.freqtrade.io/en/2026.3/backtesting/ 】。

**P7. 策略文件化 + 一键导入/导出（本地策略库）｜工作量 S/M（2-3 周）**
- 现状差距：有信号回放/模拟盘，策略不可移植、无版本化。
- 建议：策略声明式文件化（YAML/JSON 规则 + 参数），内置模板库，一键导入导出——为将来社区分享打基础（守住"研究交流、不构成投资建议"边界）。
- 参考产品：Freqtrade 策略即文件【https://github.com/freqtrade/freqtrade-strategies 】；QuantConnect Strategy Explorer【https://www.quantconnect.com/strategies 】。

**P8. 快捷键体系全面化 + 命令面板扩展｜工作量 S（1-2 周）**
- 现状差距：已有 Ctrl+K 命令面板，但覆盖不全、不可自定义。
- 建议：建立全局快捷键注册表（K线/资料/回测/主题/语言切换等），可自定义 + 冲突检测；命令面板覆盖所有功能并可中英文搜索。
- 参考产品：TradingView【https://cn.tradingview.com/support/shortcuts/ 】；同花顺【https://www.10jqka.com.cn/ad_mar/man/f1-4.htm 】；Bloomberg <GO>。

**P9. 市值热力图 + 板块强弱可视化｜工作量 S/M（1-3 周）**
- 现状差距：已有产业图谱，缺"一眼看全市场强弱"的宏观视图。
- 建议：基于 1.8 万+ 股票数据实现按板块/市值着色热力图（本地渲染），点击下钻到个股 K 线。
- 参考产品：Finviz 热力图【https://finviz.com/map 】。

### 基础建设（定位与信任工程）

**P10. 隐私承诺产品化：隐私中心 + 离线模式开关 + 许可证声明｜工作量 S（1 周）**
- 现状差距：定位"本地优先、隐私优先"但无显性隐私文档与开关。
- 建议：①应用内"隐私中心"——网络请求可视化（哪些功能联网、传了什么）；②全局"离线模式"开关；③仓库/官网补隐私政策与数据流说明；④LICENSE 明确开源许可类型。
- 参考产品：OpenBB 定价页/安全页"数据留在你的环境、客户数据不用于训练"【https://openbb.co/pricing/ 、https://openbb.co/security/ 】；Finviz 隐私页【https://finviz.com/privacy 】。

**P11. 文档与教程体系（docs 站 + 功能对照 + 中文）｜工作量 M（3-5 周）**
- 现状差距：功能面大但对外文档待体系化。
- 建议：建立 docs 站（架构图/功能清单/API 参考/教程/FAQ），每个功能一页；README 突出"本地优先 + 免费开源 + 不做投资建议"的差异化定位。
- 参考产品：QuantConnect docs【https://www.quantconnect.com/docs/v2/ 】；Freqtrade 中文站【https://www.freqtrade.cn/ 】。

**P12. 实时推送与条件告警（WebSocket 层）｜工作量 M/L（4-8 周）【低优先，建议最后做】**
- 现状差距：REST API + Web 混合界面，无 WebSocket 推送与告警。
- 建议：Web 层加 WebSocket 订阅行情增量；简单条件告警（价格/涨跌幅/指标交叉）落地为本地通知。
- 参考产品：Polygon WebSocket【https://polygon.readthedocs.io 】；TradingView 告警体系。

---

## 5. "不该做"清单（合规红线与定位守护）

1. **不做荐股/投资建议输出**。AI 分析必须带免责声明、可追溯引用、明确"不构成投资建议"；不输出目标价、买卖指令式结论。这是疏影的立身之本，也是市面多数"AI 选股"竞品的合规软肋——**不学它们，守住自己**。
2. **不模仿"AI 牛股推荐/投顾话术"式营销功能**。同花顺高端投顾（金融大师 8 万元/年）、东财妙想按次数变现的模式与"隐私优先、免费开源"定位冲突且易踩合规线。
3. **不搞数据变现/出售用户数据**。本地工具的生命线是用户信任；隐私承诺要像 OpenBB 一样明示"数据留在你的环境、不用于训练"。
4. **不做广告变现、弹窗、信息流广告**。TradingView/Finviz 免费层靠广告，但桌面研究工具插广告会毁掉"专业终端"体验与隐私定位。
5. **不转售交易所行情数据**。Level-2/实时行情的再分发有许可限制（参考 Polygon/Massive 市场数据条款【https://massive.com/terms/market_data_terms.pdf 】）；增值数据只能作为"用户自带 Key 的可选源"，不能打包转售。
6. **不绑定单一闭源供应商/单一 API**。数据适配器必须可插拔——Backtrader 内置 Yahoo feed 被上游变更破坏是反面教材；AKShare/yfinance 免费源同样有断供风险，需缓存与降级兜底。
7. **不做强制云账户/强制联网**。本地优先是差异化，注册/联网只能是可选能力（参考 QuantConnect 云/本地双轨分离）。
8. **不追"脚本公开市场"的虚荣指标**。TradingView 15 万脚本的规模背后是完整商业变现体系；疏影做策略分享要守住"研究交流、不构成建议"的边界，规模其次、合规第一。

---

## 6. 参考来源列表

> 类型标注：【官方文档】【公开评测】【一方称】。价格为调研时点快照（2026-09-29）。

### OpenBB
- 官网 https://openbb.co ；定价 https://openbb.co/pricing/ ；文档 https://docs.openbb.co ；GitHub https://github.com/OpenBB-finance/OpenBB 【官方文档】
- 全产品套件开源公告（2026-08-25）https://openbb.co/blog/ ；https://openbb.co/pricing/?type=bot 【官方文档】
- ODP 产品页（AGPLv3）https://www.openbb.co/products/odp 【官方文档】
- PyPI openbb-core（AGPL-3.0-only）https://pypi.org/project/openbb-core/1.6.10/ 【官方文档】
- Agent Rita（MIT）https://openbb.co/blog/introducing-agent-rita/ 【官方文档】
- A股/港股接入 AKShare/Tushare https://openbb.co/blog/extending-openbb-for-a-share-and-hong-kong-stock-analysis-with-akshare-and-tushare/ 【官方文档】
- Terminal 停更公告 https://openbb.co/blog/sunsetting-openbb-terminal-why-how-and-what-now/ 【官方文档】
- 安全/隐私页 https://openbb.co/security/ 【官方文档】
- 第三方评测（Lite 价格交叉验证）https://aitools.fyi/openbb 【公开评测】

### TradingView
- 定价页 https://cn.tradingview.com/gopro/ ；https://tw.tradingview.com/pricing/ 【官方文档】
- Pine Script 文档 https://www.tradingview.com/pine-script-docs/ 【官方文档】
- 快捷键列表 https://cn.tradingview.com/support/shortcuts/ 【官方文档】
- 中国市场板块页 https://cn.tradingview.com/markets/stocks-china/ 【官方文档】
- 社区脚本规模（15 万+）https://cn.tradingview.com/support/solutions/43000549905/ 【官方文档】
- AI Screener 公告 https://www.tradingview.com/blog/tw/ai-screener-60101/ 【官方文档】
- Lightweight Charts（Apache-2.0）https://tw.tradingview.com/lightweight-charts/ 【官方文档】
- 实时数据费用 https://chartwisehub.com/tradingview-real-time-data/ 【公开评测】
- 定价评测 https://www.financialtechwiz.com/post/how-much-is-tradingview/ 【公开评测】
- 回测局限 https://backtestme.com/guides/tradingview-backtesting/ ；https://nexusfi.com/a/platforms/pine-script-strategy-backtesting 【公开评测】

### 同花顺（iFinD / 普通版+i问财）
- iFinD 官网 https://www.51ifind.com 【一方称】；接口文档 https://quantapi.51ifind.com/ 【官方文档】；iFinD MCP https://mcp.51ifind.com/ 【一方称】
- SuperMind 量化平台 https://quant.10jqka.com.cn/ 【官方文档】；回测指标（Alpha/Beta/Sharpe/回撤）https://quant.10jqka.com.cn/view/help/12?from=ifind 【官方文档】
- i问财 https://www.iwencai.com 【官方文档】；问财 domain/能力 https://quant.10jqka.com.cn/view/dataplatform/detail/398 【官方文档】
- 普通版官网 https://www.10jqka.com.cn ；Level-2 https://www.10jqka.com.cn/L2/ ；帮助手册 https://www.10jqka.com.cn/ad_mar/man/ 【官方文档】
- 快捷键/画线 https://www.10jqka.com.cn/ad_mar/man/f1-4.htm ；http://www.10jqka.com.cn/ad_mar/man/f6-4.htm 【官方文档】
- iFinD 价格报道（约 1.4 万/年，2026-01）https://stcn.com/article/detail/3620915.html 【公开评测】
- 月活数据（3,786 万，2026-08）https://finance.sina.com.cn/stock/relnews/cn/2026-09-20/doc-inismvpc2554893.shtml 【公开评测】
- Level-2 价格 http://pay.10jqka.com.cn/eq3_release.php?op=appvpos&platform=ipad&s_id=101 【一方称】

### 东方财富（Choice / 免费版+妙想）
- Choice 官网 https://choice.eastmoney.com 【一方称】；使用指南 https://choice.eastmoney.com/choicewebfile/UserGuide.pdf 【官方文档】
- EMQuantAPI 手册 https://quantapi.eastmoney.com/Upload/EMQuantAPI_Python.pdf 【官方文档】
- 数据学院 https://choice.eastmoney.com/school 【官方文档】
- 免费版 https://www.eastmoney.com/default.html ；行情中心 https://quote.eastmoney.com/center/gridlist.html ；妙想 https://ai.eastmoney.com/miaoxiang/ ；股吧 https://guba.eastmoney.com 【一方称】
- 数据覆盖 https://www.stcn.com/article/detail/1223958.html 【一方称】
- Choice 价格（¥5,800/¥6,980 活动价；约 1.8 万/年报道）https://zqhd.eastmoney.com/Html/aghd/native/6/20171104/html/activity1.html 【一方称】；https://stcn.com/article/detail/3620915.html 【公开评测】
- 妙想备案与规格 http://finance.ce.cn/stock/gsgdbd/202401/11/t20240111_38862416.shtml 【公开评测】
- 妙想定价（518/818 元/季）https://finance.sina.com.cn/roll/2025-08-23/doc-infmxxvk4723646.shtml 【公开评测】
- 股吧规模（4.2 亿注册/300 万日活）https://caifuhao.eastmoney.com/news/20260529115729216434840 【公开评测】

### Freqtrade
- 官网 https://www.freqtrade.io/ ；文档 https://docs.freqtrade.io/ ；GitHub https://github.com/freqtrade/freqtrade 【官方文档】
- 命令列表（含 lookahead-analysis/recursive-analysis；无 walk-forward）https://docs.freqtrade.io/en/2026.1/bot-usage/ 【官方文档】
- 回测文档（指标清单）https://docs.freqtrade.io/en/2026.3/backtesting/ 【官方文档】
- FreqUI https://docs.freqtrade.io/en/latest/freq-ui/ 【官方文档】
- FreqAI 论文 https://joss.theoj.org/papers/10.21105/joss.04864.pdf 【公开评测/论文】
- freqtrade-strategies https://github.com/freqtrade/freqtrade-strategies 【官方文档】
- 第三方评测（无原生 WFA）https://www.backtestscore.com/tools/freqtrade 【公开评测】

### Backtrader
- 官网 https://www.backtrader.com/ ；文档 https://www.backtrader.com/docu/ ；GitHub https://github.com/mementum/backtrader 【官方文档】
- Analyzer 参考 https://backtrader.ru/docu/analyzers/analyzers-reference/ 【官方文档】
- PyPI 最后发布（1.9.74.123，2023-04）https://pypi.org/project/backtrader/1.9.74.123/ 【官方文档】
- Yahoo feed 破坏评测 https://rmbell09-lang.github.io/tradesight/blog/backtrader-alternative-python-2026.html 【公开评测】
- 对比评测 https://www.backtestscore.com/compare/quantconnect-vs-backtrader 【公开评测】

### QuantConnect / LEAN
- 官网 https://www.quantconnect.com/ ；引擎 https://www.lean.io/ ；文档 https://www.quantconnect.com/docs/v2/ ；GitHub https://github.com/QuantConnect/Lean 【官方文档】
- 定价 https://www.quantconnect.com/pricing/ 【官方文档】
- Mia https://www.quantconnect.com/docs/v2/ai-assistance/predefined-assistants/mia 【官方文档】
- MCP Server https://www.quantconnect.com/docs/v2/ai-assistance/mcp-server/key-concepts 【官方文档】
- Tradier 合作页（Researcher $60/月）https://www.quantconnect.com/brokerages/tradier 【官方文档】
- Alpha Streams 公告 https://www.quantconnect.com/announcements/15944/pioneering-a-free-market-for-alpha/ 【官方文档】
- 用户规模（546K）https://www.quantconnect.com/forum/discussion/10888 【官方文档】
- 第三方评测（定价交叉验证）https://www.toolworthy.ai/tool/quantconnect ；https://tradingtoolshub.com/review/quantconnect/ 【公开评测】

### Finviz
- 官网 https://finviz.com ；知识库 https://finviz.com/knowledge-base/ 【官方文档】
- Free vs Elite https://finviz.com/knowledge-base/getting-started/plans-pricing/finviz-free-vs-elite 【官方文档】
- 数据更新频率/延迟 https://finviz.com/knowledge-base/learn-reference/data-sources-calculations/update-frequency 【官方文档】
- 绘图工具 https://finviz.com/knowledge-base/charts-technical-analysis/customization-drawing/drawing-tools 【官方文档】
- 自动蜡烛形态识别 https://finviz.com/blog/introducing-automatic-candlestick-detection-on-finviz-charts/ 【官方文档】
- 隐私政策 https://finviz.com/privacy 【官方文档】
- 对比评测 https://thesovereigninvestor.net/finviz-vs-tradingview/ ；https://traderhq.com/koyfin-vs-finviz/ 【公开评测】

### StockAnalysis.com
- 官网 https://stockanalysis.com ；Changelog https://stockanalysis.com/changelog/ 【官方文档】
- App Store https://apps.apple.com/cn/app/stock-analysis-stocks-funds/id6751272467 【官方文档】
- 评测（价格/功能）https://www.financialtechwiz.com/post/stockanalysis-review/ ；https://propfirmshop.com/trading-tools/stockanalysis-com-review/ 【公开评测】

### Polygon.io / Massive
- 官网 https://polygon.io （现 massive.com）；文档 https://polygon.readthedocs.io ；状态页 https://polygonstatus.com ；GitHub https://github.com/polygon-io 【官方文档】
- 定价 https://polygon.io/pricing 【官方文档】
- 更名公告（2025-10-30）https://staging.polygon.io/ 【官方文档】；https://www.prwireindia.com/press-release/polygon-io-is-now-massive 【公开评测】
- 市场数据条款 https://massive.com/terms/market_data_terms.pdf 【官方文档】
- SDK（MIT）https://pypi.org/project/polygon/1.0.0/ 【官方文档】

### Bloomberg Terminal
- 官网 https://www.bloomberg.com/professional/products/bloomberg-terminal/ 【官方文档】
- 入门指南 https://data.bloomberglp.com/professional/sites/10/Getting-Started-Guide-for-Students-English.pdf 【官方文档】
- 数据覆盖 https://www.bloombergchina.com/solution/data-content/market-data/ 【官方文档】
- AI 新闻/电话会摘要 https://www.bloombergchina.com/press/press-release-20250115/ 【官方文档】
- ASKB（AI Equity Analyst，beta）https://assets.bbhub.io/professional/sites/27/1007635_BBGT_AI_Equity_Analyst_BCH_DIG_260325.pdf 【一方称】
- BQuant/BQL https://data.bloomberglp.com/professional/sites/10/489937_BBGT_BQUANT_Overview_MINI-1.pdf 【一方称】
- 价格 $31,980/年 https://godeldiscount.com/blog/bloomberg-terminal-cost-2026 ；https://www.stratrix.com/business-model/how-a-30k-terminal-funds-a ；https://investingintheageofai.com/claude-vs-bloomberg-terminal 【公开评测】

---

*报告结束。调研时间 2026-09-29；价格、版本与功能以各官方页面为准。核心结论的可追溯性：本报告每个关键论断均附来源 URL 与来源类型；凡未找到权威来源处已如实标注「未找到权威来源」。*
