# -*- coding: utf-8 -*-
"""回测审计 CI 入口（模块二 · 参考 quant-backtest-guard「回测照妖镜」）。

用法（本地 CI / git hook / 发布前检查）：
    venv\\Scripts\\python.exe scripts\\ci_audit.py --market CN --strategy ma_cross \\
        --params '{"fast":5,"slow":20}' [--data bars.csv]

行为：
- 对指定策略跑 8 条分级审计规则（前视偏差/时间对齐/过拟合/成本忽视/
  数据窥探/多重检验/幸存者偏差/流动性假设）；
- 并排输出「诚实结果」与「被偏差吹大的结果」（成本/前视两维度）；
- 命中 critical/high 规则 → 输出结构化 JSON 报告并以 exit 1 阻断
  （阻止有严重偏差的策略进入实盘 / 合并）；
- 全部通过 → exit 0。

数据来源：--data 指定 CSV（date,open,high,low,close,volume）；
未指定时生成 400 日确定性合成 K 线（可复现，CI 环境无网络可用）。
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Optional

import pandas as pd

sys.path.insert(0, "")  # 兼容直接从项目根运行


def _load_bars(path: Optional[str]) -> pd.DataFrame:
    if path:
        df = pd.read_csv(path)
        for col in ("date", "open", "high", "low", "close"):
            assert col in df.columns, f"数据缺少列: {col}"
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
        return df
    # 确定性合成 K 线（可复现）
    import numpy as np
    rng = np.random.default_rng(11)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0.001, 0.02, 400)))
    return pd.DataFrame({
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close,
        "volume": rng.integers(10000, 50000, len(close)),  # numpy>=2: integers
    }, index=pd.date_range("2025-01-01", periods=len(close), freq="B"))


def _parse_params(raw: Optional[str]) -> Dict[str, Any]:
    """宽松 JSON 解析：兼容 PowerShell/bash 剥离引号后的 {fast:5,slow:20}。"""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 键补双引号后重试（值保留原样）
        import re
        fixed = re.sub(r"([A-Za-z_][\w]*)\s*:", r'"\1":', raw)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError as e:
            raise ValueError(f"params 无法解析为 JSON: {raw!r}") from e


def main() -> int:
    from core.quant.backtest_auditor import audit_ci, honest_vs_biased

    ap = argparse.ArgumentParser(description="回测审计 CI 入口")
    ap.add_argument("--market", default="CN")
    ap.add_argument("--strategy", default="ma_cross")
    ap.add_argument("--params", default=None, help='JSON，如 {"fast":5,"slow":20}')
    ap.add_argument("--data", default=None, help="CSV 路径（date,open,high,low,close,volume）")
    ap.add_argument("--json", action="store_true", help="仅输出 JSON")
    args = ap.parse_args()

    params = _parse_params(args.params)
    df = _load_bars(args.data)

    gate = audit_ci(df, market=args.market, strategy=args.strategy, params=params)
    hvb = honest_vs_biased(df, market=args.market, strategy=args.strategy, params=params)

    if args.json:
        print(json.dumps({"gate": gate, "honest_vs_biased": hvb},
                         ensure_ascii=False, indent=2))
    else:
        print(f"=== 回测审计 CI | market={args.market} strategy={args.strategy} "
              f"params={params} ===")
        for c in gate["report"]["checks"]:
            mark = {"critical": "🔴", "high": "🟠", "info": "🟢"}.get(c["severity"], "⚪")
            print(f"{mark} [{c['severity']:>8}] {c['rule']} {c['name']} "
                  f"@ {c['location']}\n    {c['detail']}")
        print("\n=== 诚实 vs 被偏差吹大 ===")
        for k, v in (hvb or {}).items():
            if isinstance(v, dict):
                print(f"- {k}: " + ", ".join(f"{kk}={vv}" for kk, vv in v.items()))
            else:
                print(f"- {k}: {v}")
        if gate["block"]:
            print(f"\n❌ BLOCKED：{len(gate['blocked_rules'])} 条 critical/high 规则命中，"
                  f"禁止进入实盘/合并。")
        else:
            print("\n✅ PASS：无 critical/high 规则命中，审计通过。")

    return 1 if gate["block"] else 0


if __name__ == "__main__":
    sys.exit(main())
