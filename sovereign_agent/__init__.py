# -*- coding: utf-8 -*-
"""主权 Agent 框架（SAFE 理念）：私有化部署 + 模型注册 + 成本追踪。

参考 Sidetrade SAFE：企业完全掌控基础设施、算力与模型，数据不出企业边界。
- 私有化部署：DeploymentMode(local/saas/hybrid) + 数据出域拦截；
- 模型注册表：BYOM（自带模型），支持本地权重/Ollama/OpenAI 兼容端点；
- 成本追踪：Token/成本 SQLite 持久化，预算与年度合同承诺。
"""
from sovereign_agent.private_deployment import DeploymentMode, PrivateDeployment
from sovereign_agent.model_registry import ModelRegistry, ModelEntry
from sovereign_agent.cost_tracker import CostTracker

__all__ = [
    "DeploymentMode", "PrivateDeployment",
    "ModelRegistry", "ModelEntry",
    "CostTracker",
]
