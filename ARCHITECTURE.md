# 架构说明（ARCHITECTURE）

疏影·知微是一个本地优先、数据不出本机的桌面金融数据分析工具。整体分为四层：
**数据层 → 量化/模型层 → 合规层 → UI 层**。所有 AI 分析结果都经过合规过滤与审计留痕。

## 分层结构

```mermaid
flowchart TD
    subgraph UI["UI 层 (PyQt6)"]
        A1[对话分析]
        A2[自选股/K线图]
        A3[多空辩论/回测/产业图谱]
        A4[分析日志/合规审计]
    end

    subgraph AGENT["Agent / 编排层"]
        B1[技术面/基本面/舆情分析师]
        B2[多空辩论 Agent]
        B3[交易员/风控裁决]
        B4[LangGraph 编排]
    end

    subgraph QUANT["量化 / 模型层"]
        C1[技术指标 indicators]
        C2[形态识别 pattern_recognition]
        C3[Kronos / FinBERT / ML集成]
        C4[回测 backtest]
    end

    subgraph COMP["合规与审计层"]
        D1[compliance 输出过滤]
        D2[audit_trail 审计留痕]
        D3[decision_logger 决策落库]
    end

    subgraph DATA["数据层"]
        E1[AKShare / yfinance / Tushare]
        E2[新闻/Tavily]
        E3[SQLite 本地缓存]
    end

    UI --> AGENT
    AGENT --> QUANT
    AGENT --> COMP
    QUANT --> DATA
    COMP --> DATA
```

## 各模块职责

| 层 | 模块 | 职责 |
|---|---|---|
| 数据层 | `core/data/*` | 多源行情/新闻获取、SQLite 缓存、行业图谱 |
| 量化层 | `core/quant/*` | 技术指标、回测、多因子、市场状态、ML 信号 |
| 模型层 | `core/ml/*` | Kronos K线预测、FinBERT 情感 |
| Agent 层 | `core/agents/*` | 多智能体编排（LangGraph）与 Pydantic 输出契约 |
| 合规层 | `core/compliance.py` | 敏感词过滤；`core/audit_trail.py` 审计留痕 |
| 记录层 | `decision_logger.py` | AI 分析日志（JSON/CSV 导出） |
| 研究层 | `core/research_journal.py` | 研究笔记与复盘报告 |
| 报告层 | `core/report_generator.py` | Markdown/HTML 报告导出 |
| UI 层 | `app/ui/*` | 各功能标签页与三栏联动 |

## 关键设计原则
- **point-in-time**：历史数据只增不改，回测无未来函数（信号 `shift(1)` 后生效）。
- **本地优先**：除用户自己配置的云端 LLM API Key 外，不向开发者上传任何数据。
- **合规兜底**：任何 AI 输出都过 `sanitize_ai_output`，并写入 `audit_trail`。
- **永不崩主流程**：日志、审计、报告等横切模块全部 try-except 静默兜底。
