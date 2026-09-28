# 企业级私有化部署指南

本工具坚持"本地优先、数据主权归还个体"；企业版进一步提供
**主权 Agent 框架（SAFE 理念）**：所有 Agent 在客户自有基础设施上运行，
数据不出企业边界，可选接入客户自带模型（BYOM）。

## 部署模式

| 模式 | 说明 | 适用 |
|---|---|---|
| `local` | 全部本机/内网运行，外发被拦截 | 数据敏感、完全离线 |
| `hybrid` | 核心数据本地，计算可上云；敏感字段拦截 | 兼顾算力与合规 |
| `saas` | 托管云端 | 个人/小团队 |

代码入口：`sovereign_agent/private_deployment.py`

```python
from sovereign_agent import PrivateDeployment, DeploymentMode
d = PrivateDeployment(DeploymentMode.HYBRID)
assert not d.allow_egress({"portfolio": {...}})   # 敏感字段被拦截
```

## 自带模型（BYOM）

`sovereign_agent/model_registry.py` 支持三类端点：

- **本地权重**：`ModelRegistry().register_local("qwen-3b", "models/Qwen2.5-3B-Instruct")`
- **Ollama**：`register_ollama("qwen-ollama", "qwen3:7b")`
- **OpenAI 兼容 API**：`register_openai_compatible("deepseek", base_url, model, api_key)`

未配置时自动降级（`resolve()` 返回 None），不影响主程序。

## 成本追踪与预算

`sovereign_agent/cost_tracker.py`：Token/成本 SQLite 持久化，
支持月度预算检查与年度合同承诺：

```python
ct = CostTracker(annual_commitment=100000)   # 年度承诺 10 万元
ct.track("deepseek-chat", 100_000, 50_000)
ct.budget_check(monthly_budget=5000)         # 月度 5000 元
```

## Docker 化（推荐）

```bash
docker build -t shuying-insight .
docker run -d -p 8200:8200 -v ./data:/app/data shuying-insight
```

## 数据隔离红线

- `hybrid` 模式下自选股/持仓/回测结果默认不出域；
- 审计留痕（`security/audit_ledger.py`）不可篡改，支持导出 CSV/JSON；
- GDPR/CCPA 数据导出与删除：`compliance/gdpr.py` / `compliance/ccpa.py`。
