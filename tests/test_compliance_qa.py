# -*- coding: utf-8 -*-
"""
合规治理 · 单元测试（第17轮·模块六）。

验证 core/compliance_qa.py 中的 run_qa 与 local_eval 函数在不同输入下的正确性。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from core.compliance_qa import run_qa, local_eval, qa_report

# 测试数据集：包含一个有害样本与一个合规样本，覆盖 H01 / 合规放行
TEST_SAMPLES = [
    # H01: 荐股（应拦截）
    ("建议买入 SH600519 贵州茅台，明天就建仓。", ["H01"], False),
    # H02: 目标价（应拦截）
    ("贵州茅台目标价 2500 元，上看 3000。", ["H02"], False),
    # S03: 内容过短且缺声明（应拦截）
    ("估值偏低。", ["S01", "S02", "S03"], False),
    # 合规样本（应放行）
    ("贵州茅台今日收涨 2%，成交量温和放大，仅供参考，不构成投资建议；投资有风险，入市需谨慎。",
     [], True),
]


@pytest.mark.parametrize("text, expected_ids, expect_ok", TEST_SAMPLES)
def test_run_qa(text, expected_ids, expect_ok):
    """测试 run_qa 函数对单个样本的处理结果"""
    # 注意：run_qa 接收「样本列表」，每条样本是 (text, ids, ok) 三元组
    result = run_qa([(text, expected_ids, expect_ok)])

    # 验证总样本数和正确处置数
    assert result.total == 1
    assert result.triggered == 1

    # 验证期望行为：有害样本应被拦截，且所有 expected 约束必须命中（子集语义）
    if not expect_ok:
        assert not result.per_sample[0]["approved"]
        hit = set(result.per_sample[0]["hit"])
        assert set(expected_ids).issubset(hit), f"{expected_ids} 未被全部命中，仅 {sorted(hit)}"
    else:
        assert result.per_sample[0]["approved"]


def test_local_eval():
    """测试 local_eval 函数的汇总统计功能"""
    texts = [
        "贵州茅台今日收涨 2%，成交量温和放大，仅供参考，不构成投资建议；投资有风险，入市需谨慎。",
        "建议买入 SH600519 贵州茅台，明天就建仓。",
        "该策略历史表现稳健，适合长期持有。",
    ]
    result = local_eval(texts, None)

    # 验证总数和通过率
    assert result["n"] == 3
    assert result["passed"] == 1
    assert result["blocked"] == 2
    assert result["pass_rate"] == 0.3333

    # 验证违规计数（真实输出：H01 1 次、S01 2 次、S02 2 次、S03 1 次）
    assert result["viol_id_counts"] == {"H01": 1, "S01": 2, "S02": 2, "S03": 1}


def test_full_qa_gateway():
    """全量回放默认数据集，验证上线闸门（0 漏报 + 0 误报）"""
    r = run_qa()
    assert r.false_neg == 0, "存在漏报"
    assert r.false_pos == 0, "存在误报"
    assert r.recall == 1.0
    assert r.precision_safe == 1.0

    report = qa_report(r)
    assert "GATE PASS" in report or ("违规召回率 100%" in report and "合规样本精准率 100%" in report)
