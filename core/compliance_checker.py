# -*- coding: utf-8 -*-
"""合规检查引擎（企业版模块六）：投资限制规则自动校验。

规则类型：
- 禁投清单（blacklist）    : 股票/行业/证券类型禁投；
- 仓位上限（position cap）: 单标的权重上限；
- 行业上限（sector cap）  : 单行业暴露上限；
- 流动性下限（可选）      : 日均成交额下限（防小盘流动性风险）。

- check_position / check_portfolio : 返回违规清单（violations）；
- 与 core/compliance.py（AI 输出合规过滤）互补：本引擎管**投资限制**，
  那个管**输出话术**。
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

DEFAULT_RULES = {
    "blacklist": [],                 # ["600xxx", "industry:军工", "type:ST"]
    "position_cap": 0.30,            # 单标的 ≤ 30%
    "sector_cap": 0.40,              # 单行业 ≤ 40%
    "min_daily_amount": 0,           # 0=不检查（需外部成交额数据）
}


def _db() -> Path:
    root = Path(__file__).resolve().parents[1]
    p = root / "data" / "compliance_rules.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def save_rules(rules: dict, tenant_id: str = "default") -> None:
    """保存租户级合规规则（JSON 序列化）。"""
    import json
    with sqlite3.connect(_db()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rules(
                tenant_id TEXT PRIMARY KEY, rules TEXT NOT NULL,
                updated_at TEXT NOT NULL)""")
        conn.execute(
            "INSERT OR REPLACE INTO rules(tenant_id, rules, updated_at) VALUES(?,?,?)",
            (tenant_id, json.dumps(rules, ensure_ascii=False),
             time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))


def load_rules(tenant_id: str = "default") -> dict:
    import json
    with sqlite3.connect(_db()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rules(
                tenant_id TEXT PRIMARY KEY, rules TEXT NOT NULL,
                updated_at TEXT NOT NULL)""")
        row = conn.execute("SELECT rules FROM rules WHERE tenant_id=?",
                           (tenant_id,)).fetchone()
    if not row:
        return dict(DEFAULT_RULES)
    merged = dict(DEFAULT_RULES)
    merged.update(json.loads(row[0]))
    return merged


def check_position(ticker: str, weight: float,
                   sector: str = "", is_st: bool = False,
                   tenant_id: str = "default") -> list[dict]:
    """检查单个持仓是否违规。返回违规清单（空=合规）。"""
    rules = load_rules(tenant_id)
    violations: list[dict] = []
    if ticker in rules["blacklist"]:
        violations.append({"type": "blacklist", "ticker": ticker,
                           "message": f"{ticker} 在禁投清单中"})
    if sector and f"industry:{sector}" in rules["blacklist"]:
        violations.append({"type": "blacklist_sector", "ticker": ticker,
                           "message": f"行业 {sector} 禁投"})
    if is_st and "type:ST" in rules["blacklist"]:
        violations.append({"type": "blacklist_st", "ticker": ticker,
                           "message": "ST 标的不允许持有"})
    cap = rules["position_cap"]
    if cap and weight > cap:
        violations.append({"type": "position_cap", "ticker": ticker,
                           "weight": weight, "cap": cap,
                           "message": f"仓位 {weight:.1%} 超上限 {cap:.1%}"})
    return violations


def check_portfolio(positions: list[dict], tenant_id: str = "default") -> dict:
    """检查整个组合。positions: [{ticker, weight, sector, is_st}]。

    返回 {pass: bool, violations: [...], exposure: {...}}
    """
    rules = load_rules(tenant_id)
    violations: list[dict] = []
    sector_exposure: dict[str, float] = {}
    for p in positions:
        violations += check_position(p["ticker"], p["weight"],
                                     p.get("sector", ""), p.get("is_st", False),
                                     tenant_id)
        sec = p.get("sector", "未知")
        sector_exposure[sec] = sector_exposure.get(sec, 0.0) + p["weight"]
    for sec, w in sector_exposure.items():
        cap = rules["sector_cap"]
        if cap and w > cap:
            violations.append({"type": "sector_cap", "sector": sec,
                               "weight": w, "cap": cap,
                               "message": f"行业 {sec} 暴露 {w:.1%} 超上限 {cap:.1%}"})
    return {"pass": len(violations) == 0, "violations": violations,
            "exposure": {k: round(v, 4) for k, v in sector_exposure.items()}}


def mark_violation(violations: list[dict], actor: str) -> None:
    """违规标记留痕（审计联动）。"""
    try:
        from core.audit_logger import log_operation
        log_operation(actor, "compliance_violation",
                      f"violations={len(violations)}",
                      resource="portfolio")
    except Exception:  # noqa: BLE001
        pass
