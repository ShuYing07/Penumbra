# -*- coding: utf-8 -*-
"""每日自动简报：自选股涨跌 + 主要指数 + 今日要点，生成 Markdown 并存档。

参考 go-stock 的定时任务与自动预警：
- 每日 07:30 自动生成（由 main_window 的 QTimer 触发检查）；
- 内容：主要指数、自选股涨跌、合规提示；
- 输出：data/reports/daily_brief_YYYYMMDD.md + 返回 HTML 供托盘通知。
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime

log = logging.getLogger("stockai.daily_briefing")


def _fmt_chg(x) -> str:
    try:
        v = float(x)
        return f"{v:+.2f}%"
    except (TypeError, ValueError):
        return "—"


def _index_rows() -> list[dict]:
    """主要宽基指数（降级友好，失败返回空）。"""
    try:
        from core.data.market_overview import list_market_indices
        return list_market_indices()[:6]
    except Exception as e:  # noqa: BLE001
        log.warning("简报-指数获取失败: %s", e)
        return []


def _watchlist_rows() -> list[dict]:
    """自选股实时快照（降级友好）。"""
    try:
        from core.data.service import get_daily
        from core.quant.indicators import latest_snapshot
        rows = []
        for code in ("SH600519", "AAPL", "SZ300750", "HK00700"):
            df, _src = get_daily(code)
            if df is None or len(df) < 2:
                continue
            s = latest_snapshot(df)
            rows.append({"code": code, "close": s.get("close"),
                         "chg": s.get("chg_pct_1d")})
        return rows
    except Exception as e:  # noqa: BLE001
        log.warning("简报-自选股获取失败: %s", e)
        return []


def build_briefing(now: datetime | None = None) -> str:
    """生成今日简报 Markdown 并写入 data/reports/，返回 HTML 摘要。"""
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")

    lines = [f"# 疏影·知微 每日市场简报 · {today}", ""]
    lines.append("> 本简报为客观数据展示，不构成任何投资建议。")
    lines.append("")

    # 主要指数
    lines.append("## 📊 主要指数")
    lines.append("")
    lines.append("| 指数 | 点位 | 涨跌幅 | 信号 |")
    lines.append("|---|---|---|---|")
    idx = _index_rows()
    if not idx:
        lines.append("| _数据暂不可用_ | — | — | — |")
    for it in idx:
        chg = it.get("chg_pct") or 0
        sig = "偏强" if chg >= 0.5 else ("偏弱" if chg <= -0.5 else "平")
        lines.append(f"| {it.get('name','')} | {it.get('price','—')} | {_fmt_chg(chg)} | {sig} |")
    lines.append("")

    # 自选股
    lines.append("## ⭐ 自选股快照")
    lines.append("")
    lines.append("| 代码 | 最新价 | 涨跌幅 |")
    lines.append("|---|---|---|")
    wl = _watchlist_rows()
    if not wl:
        lines.append("| _自选股为空或数据不可用_ | — | — |")
    for r in wl:
        lines.append(f"| {r['code']} | {r['close'] or '—'} | {_fmt_chg(r['chg'])} |")
    lines.append("")

    lines.append("## 🧭 今日关注")
    lines.append("- 数据源：AKShare（A股/指数）/ yfinance（美股/港股）")
    lines.append("- 分析引擎：按 .env 配置自动路由（DeepSeek / Qwen / GLM / Ollama）")
    lines.append("- 提示：历史回测不代表未来表现，投资有风险。")
    lines.append("")

    md = "\n".join(lines)
    report_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "data", "reports")
    os.makedirs(report_dir, exist_ok=True)
    path = os.path.join(report_dir, f"daily_brief_{today}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)

    # HTML 摘要（供桌面通知）
    html = (
        f"<b>{today} 市场简报已生成</b><br/>"
        f"指数：{len(idx)} 个 · 自选股：{len(wl)} 只<br/>"
        f"详情：{path}"
    )
    return html


def briefing_path(today: str | None = None) -> str:
    today = today or date.today().strftime("%Y-%m-%d")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "reports", f"daily_brief_{today}.md")
