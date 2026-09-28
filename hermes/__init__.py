# -*- coding: utf-8 -*-
"""HERMES：分层检索增强多 Agent 架构（Hierarchical Retrieval-augmented Multi-Agent System）。

参考 HERMES 五层架构：数据检索层 → 验证层 → 合成层 → 共识层 → 报告生成层，
配合动态知识图谱演化与对抗数据验证，保证复杂分析任务的语义一致性与可靠性。

所有实现均为标准库 + 可选降级，不引入未安装依赖；导入失败不影响主程序。
"""
from hermes.hierarchical_agents import HERMES, run_analysis
from hermes.dynamic_kg import DynamicKG, financial_ner, link_entities
from hermes.adversarial_validator import AdversarialValidator, verify_facts

__all__ = [
    "HERMES", "run_analysis",
    "DynamicKG", "financial_ner", "link_entities",
    "AdversarialValidator", "verify_facts",
]
