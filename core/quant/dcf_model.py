# -*- coding: utf-8 -*-
"""轻量级DCF估值引擎。

用程序化的DCF计算锚定估值，而不是让LLM"想象"目标价。
数据来源：基本面快照 + 用户假设的增长率/折现率。
免费数据源字段有限，很多用默认假设。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger("stockai.dcf")


@dataclass
class DCFInput:
    """DCF输入参数。"""
    ticker: str = ""
    current_price: float = 0.0
    # 自由现金流相关
    fcf: float = 0.0           # 最新年度自由现金流（元）
    shares_outstanding: float = 0.0  # 总股本（股）
    # 增长率假设
    growth_5y: float = 0.08     # 前5年增长率
    growth_10y: float = 0.05    # 5-10年增长率
    terminal_growth: float = 0.025  # 永续增长率
    discount_rate: float = 0.10  # WACC/折现率
    # 其他
    net_cash: float = 0.0       # 净现金（现金-债务）


@dataclass
class DCFResult:
    intrinsic_value: float       # 每股内在价值
    upside_pct: float           # 上行空间%
    margin_of_safety: float      # 安全边际%
    assumptions: dict            # 使用的假设
    notes: list[str]             # 备注/局限


def run_dcf(inp: DCFInput) -> DCFResult:
    """简化DCF：预测未来10年FCF + 永续增长。

    假设：前5年growth_5y增长，后5年线性衰减到growth_10y，之后永续terminal_growth。
    """
    if inp.fcf <= 0 or inp.shares_outstanding <= 0:
        return DCFResult(
            intrinsic_value=0.0, upside_pct=0.0, margin_of_safety=0.0,
            assumptions={"fcf": inp.fcf, "shares": inp.shares_outstanding},
            notes=["自由现金流或股本数据不足，DCF无法计算"],
        )

    notes = []
    fcf = inp.fcf
    pv_sum = 0.0

    # 前10年FCF折现
    annual_fcf = fcf
    for year in range(1, 11):
        # 前5年高速增长，后5年线性衰减
        if year <= 5:
            g = inp.growth_5y
        else:
            g = inp.growth_5y - (year - 5) * (inp.growth_5y - inp.growth_10y) / 5
        annual_fcf *= (1 + g)
        pv = annual_fcf / ((1 + inp.discount_rate) ** year)
        pv_sum += pv

    # 终值（Gordon Growth）
    terminal_fcf = annual_fcf * (1 + inp.terminal_growth)
    terminal_value = terminal_fcf / (inp.discount_rate - inp.terminal_growth)
    pv_terminal = terminal_value / ((1 + inp.discount_rate) ** 10)

    # 企业价值 → 股权价值 → 每股
    enterprise_value = pv_sum + pv_terminal
    equity_value = enterprise_value + inp.net_cash
    intrinsic_per_share = equity_value / inp.shares_outstanding

    # 上行空间
    upside = ((intrinsic_per_share / inp.current_price) - 1) * 100 if inp.current_price > 0 else 0
    # 安全边际 = (内在价值 - 当前价) / 内在价值
    mos = ((intrinsic_per_share - inp.current_price) / intrinsic_per_share * 100
           if intrinsic_per_share > 0 else 0)

    if inp.fcf < 0:
        notes.append("自由现金流为负，DCF结果仅供参考")
    if inp.discount_rate < 0.07:
        notes.append("折现率偏低（<7%），可能高估")
    notes.append("基于简化假设，非精确估值，仅作参考")

    return DCFResult(
        intrinsic_value=round(intrinsic_per_share, 2),
        upside_pct=round(upside, 1),
        margin_of_safety=round(mos, 1),
        assumptions={
            "growth_5y": inp.growth_5y,
            "growth_10y": inp.growth_10y,
            "terminal_growth": inp.terminal_growth,
            "discount_rate": inp.discount_rate,
            "fcf_base": fcf,
        },
        notes=notes,
    )


def dcf_from_fundamentals(funda: dict, price: float) -> DCFResult:
    """从基本面快照自动构建DCF输入。

    免费数据源字段有限，缺失的用行业默认值。
    """
    # 尝试从基本面数据提取（字段名因源而异）
    fcf = float(funda.get("fcf") or funda.get("free_cash_flow") or 0)
    shares = float(funda.get("shares_outstanding") or funda.get("total_shares") or 0)
    net_cash = float(funda.get("net_cash") or 0)

    # 如果没有FCF，用净利润近似
    if fcf <= 0:
        net_income = float(funda.get("net_income") or 0)
        fcf = net_income * 0.8  # 粗略：FCF≈净利润*80%

    inp = DCFInput(
        ticker=funda.get("code", ""),
        current_price=price,
        fcf=fcf,
        shares_outstanding=shares,
        net_cash=net_cash,
    )
    return run_dcf(inp)
