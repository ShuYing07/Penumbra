# AGENTS.md — 疏影·知微（Shuying Insight）

> 本文件是给「接手本项目的任何 AI」的快速上手入口。完整知识库见
> [`docs/AI_KNOWLEDGE_BASE.md`](docs/AI_KNOWLEDGE_BASE.md)（历轮优化建议 × 落地实现对照、
> 模块地图、参考开源项目、常见坑、后续路线）。开发本程序前请先读这两份文件。

## 项目是什么

本地优先的开源 AI 金融数据分析终端（Windows + Python 3.11+ + PyQt6）。
定位：**研究学习用**——不提供证券投资建议，非荐股软件，不构成投资建议。
所有 AI 输出仅做客观数据描述，程序内已内置合规审查层（AI 评审员 + 敏感词拦截）。

## 技术栈与运行

- GUI：PyQt6（`app/ui/`，50+ 页面/组件；暗色玻璃态主题 `ui_theme.py`）
- 数据：AKShare / Tushare / yfinance / 新浪 / 东方财富（mock 模式 `STOCKAI_MOCK=1`）
- AI：`core/llm.py`（DeepSeek 云端默认）→ `core/model_router.py`（多平台任务路由，
  2026 前沿：Ling-3.0-flash-Fin / DeepSeek-V4-Flash / Qwen3.5 / GLM / 本地 Ollama）
- 存储：SQLite（`data/`，含进化记忆 `evo_memory.db`、推理轨迹、合规审计、RAG 索引）
- 入口：`launch.py`（零配置启动，缺失依赖只提示不自动安装）→ `app/main.py`

```powershell
# 运行
venv\Scripts\python.exe launch.py
# 全量回归（mock 模式，offscreen）
$env:STOCKAI_MOCK=1; $env:QT_QPA_PLATFORM="offscreen"
venv\Scripts\python.exe -B tests\run_all.py        # 预期 75/75
# 单个测试
venv\Scripts\python.exe -B tests\test_xxx.py
```

## 目录地图（高层）

| 目录 | 职责 |
|---|---|
| `app/ui/` | 全部 PyQt6 界面（标签页 37 个，意图导航三大工作区，浮动 AI，命令面板） |
| `core/` | 核心逻辑：数据（`data_fetcher`/`realtime_engine`/`data_quality`/`multimodal_parser`）、量化（`quant/` 回测/审计/前视扫描）、AI（`model_router`/`local_fin_engine`/`financial_rag`/`pit_guard`）、智能体（`agents/` 7 分析师+多空辩论+风控）、事件图谱（`event_graph`）、评测（`eval/`） |
| `agent/` | Agent 核心运行时：`agent_core`（工具调用循环）、`agent_events`/`execution_console`/`agent_trace_store`（推理可观测性） |
| `security/` | 合规：`ai_reviewer`（AI 评审员）、`compliance_sandbox`（监管沙箱）、审计 |
| `streaming/` | 流处理：`stream_engine`/`stream_processor`（Kafka 可选） |
| `plugins/` | 插件系统（`plugin_system.py` 根目录）：情感分析/回测/导出示例插件 |
| `tests/` | 73+ 测试文件，`run_all.py` 自动发现（75 项全绿） |
| `scripts/` | 运维：`ci_audit.py`（回测审计 CLI，阻断严重偏差）、打包 |
| `docs/` | 文档（本知识库 + API/UI/合规/发布说明） |

## 开发红线（用户硬约束，必须遵守）

1. **不设置开机自启动**（程序中无任何自启动逻辑，勿添加）。
2. **新依赖只提示手动安装，绝不自动 pip**（`launch.py` 缺失依赖 → 打印指引 exit 2）。
3. **未获用户指示不 push / 不打标签 / 不发布**（GitHub 发布须用户明确确认）。
4. **程序文件只用编辑器读写工具创建/修改**（禁用终端命令改文件），UTF-8 编码。
5. **AI 输出合规**：不输出荐股建议/目标价/收益承诺/敏感词；AI 评审员拦截。
6. **A股红涨绿跌**：绿色=涨 `#00C853`，红色=跌 `#FF1744`，红绿只用于涨跌语义。

## 修改后必做

1. 写对应 `tests/test_*.py`（确定性规则可单测；LLM 调用一律 mock）。
2. 跑全量回归 `tests\run_all.py` 保持 75/75（新增测试文件自动被发现）。
3. 涉及 UI 用 offscreen 渲染验证；涉及打包确认 `ShuyingInsight.spec` datas 配置正确
   （背景为纯玻璃拟态，无背景图片；`assets/bg/` 仅作历史资产保留，不参与渲染）。

## 已知坑（不要重复踩）

- QThread 在窗口销毁时仍运行 → 0xC0000409 崩溃：用 daemon 标准库线程 + `QTimer.singleShot` 回 UI 线程。
- QSS `url()` 对 Windows 反斜杠路径不可靠 → 背景图用 `paintEvent` 代码级绘制。
- `walk_forward` 需 market/strategy/params 三参，缺参会令过拟合规则永远假阳性。
- PowerShell 传 JSON 给 CLI 会剥双引号 → `scripts/ci_audit.py` 已加宽松 JSON 解析。
- numpy2 用 `rng.integers`，勿用 `rng.randint`（已废弃）。
- `calculate_ratios` 返回 `{ok, ratios, missing, note}` 包装结构，读取用 `["ratios"]`。

## 快捷键

`Ctrl+K` 命令面板 · `Ctrl+Shift+A` 浮动 AI · `Ctrl+M` 明暗主题 · `Ctrl+1~9` 切换导航
