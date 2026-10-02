# 疏影·知微 — AI 知识库（历轮优化建议 × 落地实现）

> **本文件用途**：沉淀「疏影·知微」全部历轮优化建议与对应实现，供任何接手本项目的
> AI（Claude / ChatGPT / Cursor / Copilot 等）直接读取使用。AI 首次接入请同时读取
> 项目根 `AGENTS.md`（快速上手 + 红线）。
>
> 维护约定：每轮优化完成后，在本文件对应主题下追加「落地记录」，保持与代码同步。

---

## 0. 一句话定位

**本地优先的开源 AI 金融数据分析终端**：PyQt6 桌面 + 多智能体投研 + 严格回测纪律
+ 2026 前沿开源模型路由 + 合规沙箱，仅供研究学习，不构成投资建议。

**技术栈**：Python 3.11+ / PyQt6 / SQLite / AKShare·Tushare·yfinance / Ollama·OpenAI 兼容端点
**入口**：`launch.py`（零配置）→ `app/main.py`
**测试**：`tests/run_all.py` 自动发现，**75/75 全绿**（mock 模式）

---

## 1. 历轮优化建议时间线（用户原始需求总览）

| # | 轮次主题 | 参考开源项目 | 落地状态 |
|---|---|---|---|
| 1 | 实时行情接入 + 数据质量校验 + 启动/运行性能 | QOS 行情 API / FinReg-Validator / Ibis Profiling / Fincept Terminal | ✅ |
| 2 | 多智能体投研团队（7 分析师 + 并行执行组 + 层级编排） | FinSight / TradingAgents | ✅ |
| 3 | 回测严谨性与数据泄漏防护（PIT-Guard） | AlphaAgent | ✅ |
| 4 | 组合优化与风险管理（skfolio） | skfolio | ✅ |
| 5 | 财务报告深度解析（50+ 比率 / DCF / 摘要卡片） | financial-ai-analyst / FinKario | ✅ |
| 6 | AI 推理过程可观测性（Execution Console 三模式追踪） | FinSight Execution Console | ✅ |
| 7 | 多模态解析 + 流处理管道 + 领域微调 RAG + 合规沙箱 + 插件化 | Nemotron / FinVLM / Kafka / Ling / FinVault / Wealthfolio | ✅ |
| 8 | 数据层/AI推理/回测/UI/工程/合规 18 方向 | Ling-3.0-flash-Fin / quantlint / VeriFin / FinChain / GenA.I.沙盒++ | ✅ |
| 9 | AI推理增强/回测审计强化/数据管道/UI专业深化/合规 18 方向 | quant-backtest-guard / Nullius / OpenTerminalUI / Libra Design / Kepler / zolva | ✅ |
| 10 | AGI 路由 / A股分析师 / 数据基础设施 / 诚实回测 / 工作流 / 哈希链审计 | TOPO-2026 / QuantPilot / kbot-finance / wickra / QuestDB | ✅（部分可选依赖提示安装） |
| 11 | 评测基准 / 实时管道 / 事件图谱 / AI 评审员 / 高级图表 / 自我进化 | FORCE-Bench / KEEKG / EvoTraders / ReMe / VNInvestCharts | ✅ |
| 12 | 评测体系 / 回测审计 / 事件图谱 / 多模态 / 进化 Agent / 终端对标 | 财跃星辰 / 九章·ALGOR / FinKG-News / FactorMiner / AQuA | ✅ |
| 13 | 八大模块终极优化（含断点续传 / 高保真模拟盘 / 意图驱动） | 华泰 AI 涨乐 / EvolveTrade / SHARP / PaddleOCR-VL-1.5 | ✅ |
| 14 | UI/UX 终极升级（布局/暗色玻璃态/命令面板/浮动AI；2026-10 起纯玻璃拟态无背景图） | TradingView / Robinhood / OpenTerminal / VoidAssets | ✅ |
| 15 | 全板块极致 + AI 模型极致升级（2026 前沿模型路由 + 自主学习） | Ling-3.0-flash-Fin（Finance Agent v2 榜首）/ Qwen3.5 / DeepSeek-V4 | ✅ |
| 16 | 审计八规则深化 + 管道断点续传 + 投研 Skill 化 + 知识蒸馏库 | fin-skills 五门审计 / 东吴证券 Skill 化 / Bonferroni 校正 | ✅ |

---

## 2. 八大主题优化建议 × 落地实现对照

### 2.1 数据层

| 用户建议要点 | 参考设计 | 落地文件 | 实现说明 |
|---|---|---|---|
| 实时行情接入（WebSocket 自动重连/心跳/多市场） | QOS 行情 API / ark-market-data-mcp | `core/realtime_engine.py` | 指数退避重连（1s→30s）、30s 心跳、A股/港股/美股订阅；数据源优先级 WebSocket→AKShare 轮询→缓存兜底；UI 显示「实时/延迟 X 秒」标签 |
| 数据质量校验（缺失/异常/时间连续性） | FinReg-Validator / Ibis Profiling / Qualitis | `core/data_quality.py` + `app/ui/data_quality_tab.py` | `validate_stock_data(df)`→`{passed, issues, score}`；`validate_financial_report(report)`；管道自动校验、不合格自动切换备源；UI 显示质量评分 |
| 数据来源标注 | FinReg-Validator | `core/data_fetcher.py`（沿用） | 每条数据记录来源（AKShare/Tushare/yfinance）+ 获取时间；分析报告标注引擎名（`model_router.chat_for` 返回实际引擎） |
| 多模态金融数据解析（图表/PDF/音频） | Amsi-fin-o1 / COMPASS-VLM / PaddleOCR-VL-1.5 / AgenticOCR | `core/multimodal_parser.py` + `app/ui/multimodal_tab.py` | `parse_chart_image`（趋势线/支撑阻力/形态）、`parse_pdf_report`（表格+关键数据）、`parse_earnings_call`（转录+语气）；视觉平台路由（Qwen3-VL 优先）；UI 上传解析标签页 |
| 流处理管道（Kafka topic / 窗口聚合 / 增量更新） | fin-intelligence-dashboard / Finnhub / 秒级行情五层架构 | `streaming/stream_engine.py` + `streaming/stream_processor.py` + `app/ui/stream_monitor_tab.py` | topic：news.raw/news.processed/market.tick/filings.new；StreamProcessor 窗口聚合+去重+情感；UI 实时流状态面板（速率/延迟/积压） |
| 管道断点续传（2026-10 翻新） | Finnhub Streaming Pipeline / Flink checkpoint | `streaming/stream_checkpoint.py` | `CheckpointStore`：锚点时间 SQLite 持久化（单调推进防回拨）+ 幂等去重表；`ResumeManager.backfill()` 补数不重不漏（窗口封顶 24h）；`TumblingWindow` 5 秒滚动窗口；StreamProcessor 挂 checkpoint 后重启仍幂等 |
| 事件驱动金融知识图谱（实体-事件-风险三层） | FinKG-News / KEEKG / FinGraphRAG | `core/event_graph.py` + `app/ui/event_graph_tab.py` | `query_event_chain(event_type, depth)` 传导链；力导向图可视化；新闻事件锚点提取 |

### 2.2 AI 推理层

| 用户建议要点 | 参考设计 | 落地文件 | 实现说明 |
|---|---|---|---|
| 多平台模型路由 + 任务类型路由 | TOPO-2026 AGI 路由器 | `core/model_router.py`（2026-10 升级） | 平台：ling（Ling-3.0-flash-Fin）/openrouter/deepseekv4/deepseek/qwen/qwen35/glm/groq/siliconflow/ollama/ollama_fin；`chat_for(task_type)` 金融任务优先 Ling；视觉平台 Qwen3-VL 优先 |
| 金融专用大模型（Ling-3.0-flash-Fin） | 蚂蚁百灵 Ling-3.0-flash-Fin（Finance Agent v2 榜首） | `core/local_fin_engine.py` | Ollama 拉取 `ling-3.0-flash-fin`（GGUF）；降级链：金融模型→本地任意模型→云端主模型；UI 本地模型管理对话框一键复制安装命令（绝不自动安装） |
| RAG 增强财报分析（混合检索+原文引用+拒答） | rag-financial-copilot / VeriFin / sec-intelligence-mcp | `core/financial_rag.py` + `core/evidence_manager.py` | 索引财报/公告/研报（ChromaDB 可选）；BM25+向量混合检索；结论附 🔗 证据面板（`evidence_manager`）；找不到证据拒答 |
| 点时间数据隔离（PIT-Guard） | AlphaAgent / AlphaGuard | `core/pit_guard.py` | 工具调用边界强制 `available_at <= as_of` 时间戳过滤；`leakage_probe()` 泄漏探测；`guard_bars` K线截断 |
| 可验证思维链（每步标注数据来源与公式） | FinChain / FORCE-Bench | `core/verifiable_chain.py` + `app/ui/agent_trace_viewer.py` | 推理步骤结构化；UI 推理链查看，点击展开详情 |
| AI 自主学习闭环（分析后自动反思） | ReMe / FactorMiner Ralph Loop / EvoTraders | `core/agents/evo_memory.py`（2026-10 新增 `analyze_reflect`） | 每次分析完成自动沉淀经验（`evo_analysis_reflections` 表）；`analysis_lessons()` 聚合；`alpha_factors()`/`recursive_improve()` 因子发现与改进建议；UI 进化追踪页 |
| 投研成果 Skill 化（2026-10 翻新） | 东吴证券 Skill 化 / FinceptTerminal 工具封装 | `core/research_skills.py` | 三大可调用 Skill：factor_iteration（因子候选池+样本内 Rank IC）、kline_pattern_search（10 形态确定性识别，无前视）、deep_research（五段式脚手架）；四要素=输入 Schema/确定性执行/可解释输出/SQLite 留痕（research_skill_traces） |
| 本地金融知识蒸馏库（2026-10 翻新） | 结构化蒸馏+检索注入（业界标准 RAG 替代） | `core/distilled_knowledge.py` + `core/knowledge_distiller.py` | 58+ 条目 × 15 领域（宏观/市场/股票/估值/法律/政策/金融史/数学/行为/风险/财务/制度/金工/行业/信息科技）；原理/应用/边界三要素；SQLite 索引 + `distill_context()` 注入 Agent（`agent/agent_core._llm_compose` 已接入） |

### 2.3 多智能体

| 用户建议要点 | 参考设计 | 落地文件 | 实现说明 |
|---|---|---|---|
| 7 分析师团队（技术/基本面/新闻/情绪/宏观/风险/深度） | FinSight / TradingAgents / marvel | `core/agents/analyst_team.py` + `ashare_analysts.py` | 角色：技术分析师、基本面分析师、新闻分析师、情绪分析师、宏观分析师、风险评估师、深度研究员；A股特色：政策/游资/解禁/量价分析师 |
| 并行执行组（数据组→综合组） | FinSight parallel groups | `core/agents/graph.py` + `nodes.py` | asyncio.gather 并行；共享 `analysis_context.json` |
| 层级式编排（首席→多空辩论→风控→组合经理） | TradingAgents / FinRobot | `core/agents/graph.py` + `app/ui/debate_tab.py` | 结构化辩论；风控否决权；最终报告合成 |
| 可插拔协作模式（panel/debate/vote） | AlphaAgent | `config.yaml` collaboration.mode | 配置切换多 Agent 拓扑 |

### 2.4 回测引擎

| 用户建议要点 | 参考设计 | 落地文件 | 实现说明 |
|---|---|---|---|
| 前视偏差扫描（截断重算+分级报告） | quantlint / quant-backtest-guard | `core/quant/audit.py`（`scan_lookahead`）+ `core/quant/lookahead_scanner.py`（2026-10 新建） | 触发点截断未来数据重算信号；`{passed, severity, suspicious_points, details}`；六条分级检查清单（未来函数/过拟合/幸存者偏差/成交成本/标签泄漏/多重检验） |
| Walk-Forward 样本内/外验证 | QuantPilot / Qlib | `core/quant/audit.py`（`walk_forward`） | 样本内外分别报告绩效；退化标注 |
| 阴性对照（随机信号 1000 次） | Nullius | `core/quant/backtest.py`（沿用）+ 测试 | 真实策略 vs 随机分布显著性 |
| 诚实回测（摩擦成本/整手/T+1/滑点） | QuantPilot | `core/quant/backtest.py` | 佣金/印花税/滑点逐笔计费；t+1 开盘成交 |
| CI 审计阻断（严重偏差阻止上线） | gobacktest-audit | `scripts/ci_audit.py` | 8 条规则分级；critical/high → exit 1 |
| 八条可计算审计规则（2026-10 翻新） | fin-skills 五门审计 / quant-backtest-guard | `core/quant/audit_rules8.py` | 前视/幸存者/过拟合/数据窥探（阴性对照）/多重检验（Bonferroni 校正）/成本忽视（零费对照）/流动性（参与率约束）/时间对齐（周末/重复/未来日期）；`honest_vs_inflated()` 诚实 vs 吹大并排 |
| 审计假阳性/假阴性修复（2026-10） | — | `core/quant/backtest_audit.py`、`backtest_auditor.py` | 修复四处：①误读 scan_lookahead 不存在的 passed 字段→永远 critical；②walk_forward 缺 market/strategy 参→永远「不可计算」high；③`_check_cost_neglect` 给 BacktestConfig 赋不存在的 fee_rate 属性→对照组仍计费，成本规则永远假阴性；④`_check_overfit` 误读 wf["oos"]/annual_return（正确键 out/annual_return_pct）→过拟合规则永远假阴性 |
| 高级指标（GT-Score/Sharpe 稳定性/多空/持仓统计） | GT-Score / 天软 | `core/quant/audit.py` | 稳健性指标集 |

### 2.5 UI 交互

| 用户建议要点 | 参考设计 | 落地文件 | 实现说明 |
|---|---|---|---|
| 核心布局重构（图表居中/工具左侧/上下文右侧） | TradingView / FinceptTerminal | `app/ui/main_window.py` + `chart_tab.py` | 顶部命令栏（搜索/周期/指标开关）；右侧信息面板（个股信息/AI 摘要/技术快照/多空入口） |
| 意图驱动导航（早点听/特别提醒/任务助手） | 华泰 AI 涨乐 | `app/ui/main_window.py` `INTENT_GROUPS` | 默认意图模式，可切回经典分组 |
| 暗色玻璃态主题（纯玻璃拟态，无背景图片） | Apple 发布会极简 / VoidAssets | `app/ui/ui_theme.py` + `main_window.py` `paintEvent` | 主背景 `#0A0C10`；卡片 `rgba(20,24,32,0.82)`；paintEvent 绘制深色纵向渐变 + 顶部冷光环境渐变 + 1px 顶部高光；2026-10 按用户要求移除背景图片（`set_bg_image` 已弃用仅兼容）；浅色主题纯净 |
| 全局命令面板（Ctrl+K） | 专业终端 | `app/ui/command_palette.py` | 搜索股票/功能/历史；键盘导航 |
| 浮动 AI 助手（自动感知当前股票） | 华泰 AI 涨乐 | `app/ui/floating_ai.py` | 右下角 48px 玻璃按钮；「正在查看：XX」；自然语言指令 |
| 专业图表（高级绘图/多图表同步/回放） | VNInvestCharts / Highcharts Boost | `core/drawings_advanced.py` + `core/chart_sync.py` + `core/replay/` + `app/ui/replay_tab.py` | Gann/Pitchfork/谐波/艾略特波浪；十字光标+时间周期联动；Tick 级回放 |
| 高保真模拟盘（市价/限价/止损+真实成本） | Robinhood / Kepler Mobile | `core/portfolio/paper.py`（`place_order`）+ `app/ui/paper_tab.py` | 佣金 0.025%/边、A股最低 5 元、印花税 0.1% 卖出、滑点 0.1%、整手规则、8 种边界判定 |
| 终端模式（Bloomberg 风格命令） | OpenTerminalUI | `app/ui/terminal_tab.py` | DES/GP/BT 命令 |
| 数字翻牌动画 / 金额承重墙 | Kepler Mobile | `app/ui/ticker_components.py` | 涨跌色独立体系 |

### 2.6 工程架构

| 用户建议要点 | 参考设计 | 落地文件 | 实现说明 |
|---|---|---|---|
| 插件化架构（生命周期/加载器/权限） | Wealthfolio / OpenTerminalUI / DSH-Quant | `plugin_system.py`（根目录）+ `app/ui/plugin_manager_tab.py` + `plugins/` | PluginBase（on_load/on_unload/register_ui/register_tools/get_metadata）；动态加载；权限声明；.zip 安装；示例插件（情感/回测/导出） |
| 零配置启动 | 九章·ALGOR / OpenTerminal | `launch.py` | 环境自检；缺失依赖打印手动安装指引（绝不自动 pip） |
| 启动/内存/打包优化 | Fincept Terminal / 百万级终端实践 | `app/main.py` + `ShuyingInsight.spec` | 延迟加载非核心模块；股票索引预热；虚拟滚动/分页；排除大依赖；Kronos 模型外置 |
| 运行时监控（启动耗时/内存/延迟/API 次数） | 九章·ALGOR | `app/ui/health_tab.py` | 系统健康面板；异常自动提示 |
| 工作流编辑器（拖拽节点） | FinceptTerminal Node Editor | `app/ui/workflow_tab.py` | 数据获取→指标→AI→回测→报告 |
| AI 推理可观测性（三模式追踪/瀑布图/持久化） | FinSight Execution Console | `agent/agent_events.py` + `agent/execution_console.py` + `agent/agent_trace_store.py` + `app/ui/agent_trace_viewer.py` | EventType（THINKING/TOOL_CALL/TOOL_RESULT/REASONING/FINAL_REPORT）；User/Expert/Dev 三模式；并行瀑布图；SQLite `agent_traces` 持久化 |

### 2.7 合规治理

| 用户建议要点 | 参考设计 | 落地文件 | 实现说明 |
|---|---|---|---|
| 合规沙箱（监管场景/状态可写 DB） | FinVault / mcp-banking-auditor | `security/compliance_sandbox.py` + `app/ui/compliance_test_tab.py` | SandboxEnvironment；可疑交易/反洗钱/适当性评估等场景；`run_agent_in_sandbox` |
| AI 评审员（输出前独立审核） | GenA.I. 沙盒++ / 恒生 AI 评审员 | `security/ai_reviewer.py` + `app/ui/compliance_monitor_tab.py` | 审核荐股建议/目标价/收益承诺/敏感词；不通过自动拦截 |
| LLM 与数据库解耦（验证 schema 交互） | mcp-banking-auditor | `audit_trail.py` + `security/` | 工具调用经合规检查层；审计日志 |
| 可防篡改审计（哈希链） | zolva / kbot-finance | `audit_trail.py` + `app/ui/compliance_audit_tab.py` | 哈希链链接审计记录；CSV/JSON 导出；外部验证 |
| 证据链（结论附原文引用） | VeriFin | `core/evidence_manager.py` + `app/ui/evidence_dialog.py` | register_evidence/get_evidence；UI 🔗 图标 |

### 2.8 金融智能体评测

| 用户建议要点 | 参考设计 | 落地文件 | 实现说明 |
|---|---|---|---|
| 四维评测（正确性/适配性/鲁棒性/合规性） | 财跃星辰评测框架 | `core/eval/eval_framework.py` + `app/ui/eval_tab.py` | 资本-资产匹配：4 类资金画像×7 类资产×六维匹配度；「主动拒答」判合格 |
| 八维评分（准确性/引用/清晰度/深度/有据可依/时效/相关性/结构） | FORCE-Bench | `core/eval/eval_benchmark.py` | `evaluate_analysis()` 返回评分报告 |
| 标准评测套件 + 历史趋势 | FinToolBench | `core/eval/eval_suite.py` | 标准测试用例；AI 升级后自动评测；评分雷达图 |

---

## 3. 关键模块地图（继续开发必读）

| 模块 | 文件 | 说明 |
|---|---|---|
| 统一模型路由 | `core/model_router.py` | 任务类型路由 + 10 平台降级 + 本地探测（2026-10 升级） |
| 金融引擎 | `core/local_fin_engine.py` | Ling-3.0-flash-Fin Ollama 封装 + 降级链 |
| Agent 核心 | `agent/agent_core.py` | 工具调用循环 + 事件桥 + 证据链 |
| 分析师团队 | `core/agents/analyst_team.py`、`ashare_analysts.py` | 7+A股特色分析师 |
| 进化记忆 | `core/agents/evo_memory.py` | 交易反思 + 分析反思 + Alpha 因子 + 递归改进 |
| 回测审计 | `core/quant/audit.py`、`backtest_audit.py`、`lookahead_scanner.py` | 前视扫描 + Walk-Forward + 分级体检 |
| 数据质量 | `core/data_quality.py` | OHLCV/财报校验 + 评分 + 备源切换 |
| 实时行情 | `core/realtime_engine.py` | WebSocket 客户端 + 降级策略 |
| 流处理 | `streaming/stream_engine.py` | Kafka topic + 窗口聚合（可选依赖） |
| 事件图谱 | `core/event_graph.py` | 三层结构 + 传导链查询 |
| 多模态 | `core/multimodal_parser.py` | 图表/PDF/音频解析 |
| 合规 | `security/ai_reviewer.py`、`compliance_sandbox.py`、`audit_trail.py` | 评审/沙箱/哈希链审计 |
| 插件 | `plugin_system.py` + `plugins/` | 生命周期 + 权限 + 动态加载 |
| 评测 | `core/eval/` | eval_framework / benchmark / suite |
| 模拟盘 | `core/portfolio/paper.py` | 高保真订单引擎（市价/限价/止损） |
| 财报卡片 | `core/report_summary_card.py`（2026-10 新建） | 摘要卡片 + 多期对比 + 同行雷达 |

---

## 4. 参考开源项目（调研沉淀）

数据层：QOS 行情 API、ark-market-data-mcp、FinReg-Validator、Ibis Profiling、Qualitis、
fin-intelligence-dashboard（Kafka+PySpark）、秒级行情五层架构、wickra-feature-store、
QuestDB、九章·ALGOR

AI 推理：Ling-3.0-flash-Fin（蚂蚁百灵，Finance Agent v2 榜首）、DeepSeek-V4、
Qwen3.5/Qwen3-VL、GLM、TOPO-2026 AGI 路由器、FinChain、sec-intelligence-mcp、
Amsi-fin-o1、COMPASS-VLM、PaddleOCR-VL-1.5、AgenticOCR、rag-financial-copilot、VeriFin

智能体：FinSight（7 Agent 并行组）、TradingAgents（层级编排/WebSocket 解耦）、
marvel（A股 9 分析师）、invest-research-agent（Human-in-the-loop）、FactorMiner、
EvoTraders、ReMe、AQuA、SHARP、EvolveTrade、PandaAI L0-L4

回测：quant-backtest-guard（回测照妖镜）、quantlint、gobacktest-audit、Nullius（证伪优先）、
QuantPilot（诚实回测）、AlphaAgent/AlphaGuard（PIT-Guard）、Look-Ahead-Bench、GT-Score

UI/工程：TradingView、FinceptTerminal（C++20+Qt6）、OpenTerminalUI、Robinhood、
Libra Design（64 金融组件）、Kepler Mobile（翻牌/承重墙）、VNInvestCharts（76 绘图工具）、
Highcharts Boost、ui-profitmaker-cc、Exness、VoidAssets、华泰 AI 涨乐（意图驱动）

合规：FinVault（31 监管场景沙箱）、mcp-banking-auditor（LLM 解耦）、GenA.I. 沙盒++（AI 评审员）、
zolva、kbot-finance（哈希链审计）、财跃星辰评测框架

图谱：FinKG-News（事件驱动，12K 公司）、FinKario（305K 实体）、FinGraphRAG、KEEKG、Motif Clarity

---

## 5. 技术选型理由（供 AI 决策参考）

1. **PyQt6 而非 Electron/Web**：本地金融终端重 IO 低延迟，Qt 原生渲染避免浏览器运行时开销
   （对标 FinceptTerminal C++20+Qt6 的取舍；Python 保留快速迭代与数据生态）。
2. **SQLite 而非时序库**：单机研究场景数据量可控；QuestDB/TimescaleDB 已出评估文档
   （`docs/QUESTDB_EVALUATION.md`），未来大数据量再迁移。
3. **OpenAI 兼容端点统一接入**：所有云端/本地模型（DeepSeek/Ling/Qwen/Ollama）同一
   SDK 调用，平台可插拔，天然支持任务路由与降级。
4. **零硬依赖（可选项全部手动安装）**：Kafka/skfolio/ChromaDB/Ollama 模型等均为可选，
   缺失时确定性降级，保证开箱即用。
5. **机械层/Agent 层分离**：回测只跑确定性规则（不依赖 LLM），LLM 仅做定性判断，
   防止幻觉污染资金曲线（AlphaAgent 原则）。

---

## 6. 测试与验证

```powershell
# 全量回归（75/75）
$env:STOCKAI_MOCK=1; $env:QT_QPA_PLATFORM="offscreen"
venv\Scripts\python.exe -B tests\run_all.py

# 关键单测
tests\test_model_router2.py     # 任务路由/2026 平台（8 项）
tests\test_lookahead_scanner.py # 前视扫描分级审计（5 项）
tests\test_audit_rules8.py      # 八条可计算审计规则（9 项，2026-10）
tests\test_stream_checkpoint.py # 锚点持久化+断点续传+5秒滚动窗口（9 项，2026-10）
tests\test_research_skills.py   # 投研 Skill 化（12 项，2026-10）
tests\test_knowledge_distiller.py # 知识蒸馏库（10 项，2026-10）
tests\test_report_summary_card.py # 财报卡片（5 项）
tests\test_evo_analysis_reflect.py # 自主学习闭环（4 项）
tests\test_paper_order.py       # 高保真订单引擎（11 项）
tests\test_eval_framework.py    # 评测框架（11 项）
tests\test_ui_smoke.py          # UI 冒烟（37 标签页）
```

验证纪律：确定性规则必有单测；LLM 调用一律 mock；UI 改动 offscreen 渲染验证；
打包验证 `ShuyingInsight.spec` datas 配置正确（背景为纯玻璃拟态，无背景图片；`assets/bg/` 仅作历史资产保留，不参与渲染）。

---

## 7. 未落地 / 可选项（诚实清单）

| 项 | 状态 | 说明 |
|---|---|---|
| Kafka 实装 | 可选 | `streaming/` 已实现引擎，需用户安装 confluent-kafka/kafka-python 并起 Kafka |
| Ling-3.0-flash-Fin 本地模型 | 可选 | UI 一键复制 `ollama pull ling-3.0-flash-fin`（~78GB Q4，需 24GB+ 显存）；无则自动降级 |
| Qwen3-14B 本地模型 | 可选 | 12-16GB 显存档最佳；`ollama pull qwen3:14b` |
| skfolio 组合优化 | 可选 | `core/portfolio_optimizer.py` 已实现封装；需用户 `pip install skfolio` |
| ChromaDB RAG 向量库 | 可选 | `core/financial_rag.py` 无向量库时降级为关键词检索 |
| PaddleOCR-VL-1.5 / 本地视觉模型 | 可选 | 多模态默认走云端视觉或 Ollama qwen3-vl |
| QuestDB 替换 SQLite | 评估完成未迁移 | 见 `docs/QUESTDB_EVALUATION.md` |
| 全量知识蒸馏进本地模型 | **不可行** | 需几十 GB 权重+版权语料；替代=进化记忆/学习库/RAG/Ling 金融引擎 |

---

## 8. 给其他 AI 的继续开发指南

1. **先读**：`AGENTS.md`（红线+坑）→ 本文件 → 目标模块源码 → 对应测试。
2. **改动纪律**：遵守红线（不自动装依赖/不设自启动/不擅自发布）；文件用编辑器工具写，
   UTF-8；每模块配单测；跑全量 75/75。
3. **新增优化轮次**：在 §1 时间线追加一行、§2 对应主题追加落地记录，保持知识库与代码同步。
4. **AI 升级方向参考**：模型路由（`model_router.chat_for`）、自主学习（`evo_memory.analyze_reflect`）、
   评测闭环（`core/eval/`）是三大持续增强点。
