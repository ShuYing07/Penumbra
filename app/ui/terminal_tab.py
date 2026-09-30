# -*- coding: utf-8 -*-
"""终端模式（模块四 · 参考 OpenTerminalUI / Bloomberg 终端风格）。

在 PyQt6 界面内提供命令行交互：输入 Bloomberg 风格命令（DES / GP / BT /
TECH / SCREEN / HELP / QUIT）即可直达行情、K线、回测等功能。

- parse_command(line)：纯函数命令解析（可单测）；
- TerminalTab：终端 UI（输入行 + 输出浏览），执行走确定性 service /
  回测引擎，全部降级安全（mock / 网络失败不抛窗）。
"""
from __future__ import annotations

import logging

import pandas as pd

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QTextBrowser,
                             QVBoxLayout, QWidget)

log = logging.getLogger("stockai.ui.terminal")

# ---------------------------------------------------------------------------
# 命令解析（纯函数）
# ---------------------------------------------------------------------------
CMD_HELP = """可用命令（Bloomberg 风格）：
  HELP              查看帮助
  DES <代码>         标的详情（现价/涨跌/成交额）
  GP <代码>          查看K线摘要（近20日 OHLC + 区间涨跌）
  TECH <代码>        技术指标快照（RSI/MACD/布林带）
  BT <策略>          运行回测（ma_cross / rsi / boll）
  SCREEN             市场概览（主要指数）
  QUIT / EXIT        关闭终端
示例：DES 600519    GP AAPL    BT rsi"""

_KNOWN = ("HELP", "DES", "GP", "TECH", "BT", "SCREEN", "QUIT", "EXIT")


def parse_command(line: str) -> dict:
    """解析一行终端命令。返回 {action, args, raw}。"""
    raw = (line or "").strip()
    if not raw:
        return {"action": "EMPTY", "args": [], "raw": raw}
    parts = [p for p in raw.split() if p]
    head = parts[0].upper()
    args = parts[1:]
    if head == "HELP":
        return {"action": "HELP", "args": args, "raw": raw}
    if head == "QUIT" or head == "EXIT":
        return {"action": "QUIT", "args": args, "raw": raw}
    if head == "SCREEN":
        return {"action": "SCREEN", "args": args, "raw": raw}
    if head in ("DES", "GP", "TECH"):
        if not args:
            return {"action": "ERR", "args": args, "raw": raw,
                    "error": f"{head} 需要股票代码，例如 {head} 600519"}
        return {"action": head, "args": args, "raw": raw, "code": args[0].upper()}
    if head == "BT":
        if not args:
            return {"action": "ERR", "args": args, "raw": raw,
                    "error": "BT 需要策略名，例如 BT rsi（可选 ma_cross / boll）"}
        strat = args[0].lower()
        if strat not in ("ma_cross", "rsi", "boll"):
            return {"action": "ERR", "args": args, "raw": raw,
                    "error": f"未知策略 {strat}（支持 ma_cross / rsi / boll）"}
        return {"action": "BT", "args": args, "raw": raw, "strategy": strat}
    if head in _KNOWN:
        return {"action": "ERR", "args": args, "raw": raw,
                "error": f"命令 {head} 参数不正确"}
    return {"action": "ERR", "args": args, "raw": raw,
            "error": f"未知命令 {head}（输入 HELP 查看帮助）"}


# ---------------------------------------------------------------------------
# 命令执行（确定性，全部降级安全）
# ---------------------------------------------------------------------------
def _safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:  # noqa: BLE001
        log.debug("terminal exec fail: %s", e)
        return None


def execute_command(cmd: dict) -> str:
    """执行已解析命令，返回文本输出（HTML 片段，暗色主题兼容）。"""
    action = cmd["action"]
    if action == "EMPTY":
        return ""
    if action == "HELP":
        return "<pre style='font-family:Consolas,monospace'>" + CMD_HELP + "</pre>"
    if action == "QUIT":
        return "已退出终端模式。可随时返回对话分析页继续使用。"
    if action == "SCREEN":
        return _exec_screen()
    if action == "DES":
        return _exec_des(cmd["code"])
    if action == "GP":
        return _exec_gp(cmd["code"])
    if action == "TECH":
        return _exec_tech(cmd["code"])
    if action == "BT":
        return _exec_bt(cmd["strategy"])
    if action == "ERR":
        return f"<span style='color:#FFA726'>✗ {cmd.get('error', '参数错误')}</span>"
    return f"<span style='color:#8B949E'>未知命令</span>"


def _exec_screen() -> str:
    from core.data import market_overview
    rows = _safe(market_overview.fetch_overview) or []
    if not rows:
        return "<span style='color:#FFA726'>市场概览数据不可用（网络受限或离线）。</span>"
    lines = ["<b>市场概览（主要指数）</b>", "<table border='0' cellspacing='4'>"]
    for it in rows:
        name = it.get("name", "")
        price = it.get("price", "")
        chg = it.get("chg_pct")
        col = "#FF5252" if (chg or 0) >= 0 else "#26A69A"  # A股：红涨绿跌
        chg_txt = f"{chg:+.2f}%" if chg is not None else "—"
        lines.append(f"<tr><td>{name}</td><td>{price}</td>"
                     f"<td style='color:{col}'>{chg_txt}</td></tr>")
    lines.append("</table>")
    return "".join(lines)


def _fetch(code: str) -> dict | None:
    from core.data import service
    q = _safe(service.get_realtime, code)
    if q:
        return q
    bars = _safe(service.get_daily, code)
    if bars is not None and len(bars):
        last = bars.iloc[-1]
        prev = bars.iloc[-2] if len(bars) > 1 else last
        chg = (last["close"] / prev["close"] - 1) * 100 if prev["close"] else 0
        return {"name": code, "code": code, "close": float(last["close"]),
                "chg_pct": float(chg), "date": str(bars.index[-1])[:10],
                "source": "日线末值"}
    return None


def _exec_des(code: str) -> str:
    q = _fetch(code)
    if not q:
        return f"<span style='color:#FFA726'>DES {code}：行情不可用（网络受限）。</span>"
    chg = q.get("chg_pct")
    col = "#FF5252" if (chg or 0) >= 0 else "#26A69A"
    return (f"<b>{q.get('name') or code}（{code}）</b><br>"
            f"最新价 <b>{q.get('close')}</b>　"
            f"<span style='color:{col}'>{chg:+.2f}%</span>"
            f"<br>成交额 {q.get('amount') or q.get('成交额') or '—'}　"
            f"换手率 {q.get('turnover') or q.get('换手率') or '—'}％<br>"
            f"<span style='color:#8B949E'>来源：{q.get('source', '实时')} · "
            f"{q.get('date', '')}</span>")


def _exec_gp(code: str) -> str:
    from core.data import service
    bars = _safe(service.get_daily, code)
    if bars is None or not len(bars):
        return f"<span style='color:#FFA726'>GP {code}：K线数据不可用。</span>"
    tail = bars.tail(20)
    first_c = float(tail["close"].iloc[0])
    last_c = float(tail["close"].iloc[-1])
    chg = (last_c / first_c - 1) * 100 if first_c else 0
    col = "#FF5252" if chg >= 0 else "#26A69A"
    hi = float(tail["high"].max())
    lo = float(tail["low"].min())
    rows = "".join(
        f"<tr><td>{str(d)[:10]}</td><td>{float(r['open']):.2f}</td>"
        f"<td>{float(r['high']):.2f}</td><td>{float(r['low']):.2f}</td>"
        f"<td>{float(r['close']):.2f}</td><td>{int(r['volume']):,}</td></tr>"
        for d, r in tail.iterrows())
    return (f"<b>{code} K线摘要（近{len(tail)}日）</b>　"
            f"区间 <span style='color:{col}'>{chg:+.2f}%</span>　高 {hi:.2f} 低 {lo:.2f}<br>"
            f"<table border='0' cellspacing='3' cellpadding='2'>"
            f"<tr><td>日期</td><td>开</td><td>高</td><td>低</td><td>收</td><td>量</td></tr>"
            f"{rows}</table>")


def _exec_tech(code: str) -> str:
    from core.data import service
    bars = _safe(service.get_daily, code)
    if bars is None or not len(bars):
        return f"<span style='color:#FFA726'>TECH {code}：K线数据不可用。</span>"
    from core.quant.indicators import boll, macd, rsi, sma
    close = bars["close"]
    last_c = float(close.iloc[-1])
    r = float(rsi(close, 14).iloc[-1])
    m = macd(close)
    macd_v = float(m["macd"].iloc[-1]) if "macd" in m and not pd.isna(m["macd"].iloc[-1]) else None
    b = boll(close)
    up_b = float(b["upper"].iloc[-1])
    dn_b = float(b["lower"].iloc[-1])
    ma20 = float(sma(close, 20).iloc[-1])
    return (f"<b>{code} 技术指标快照</b>　收盘 {last_c:.2f}<br>"
            f"RSI(14) = {r:.1f}　MACD = {macd_v:.3f}　MA20 = {ma20:.2f}<br>"
            f"布林带：上轨 {up_b:.2f} / 下轨 {dn_b:.2f}"
            f"（{'偏强' if last_c > ma20 else '偏弱'}）")


def _exec_bt(strategy: str) -> str:
    from core.data import service
    from core.quant.backtest import run_backtest
    bars = _safe(service.get_daily, "600519")
    if bars is None or not len(bars):
        return f"<span style='color:#FFA726'>BT {strategy}：演示数据不可用。</span>"
    res = _safe(run_backtest, bars, "CN", strategy, None, None)
    if not res:
        return f"<span style='color:#FFA726'>BT {strategy}：回测失败。</span>"
    m = res.metrics
    f = lambda k: m.get(k)
    return (f"<b>回测 {strategy}（600519 示例）</b><br>"
            f"总收益 {f('total_return'):+.2%}　年化 {f('annual_return'):+.2%}　"
            f"最大回撤 {f('max_drawdown'):.2%}<br>"
            f"夏普 {f('sharpe'):.2f}　胜率 {f('win_rate'):.0%}　"
            f"交易 {f('n_trades')} 次　盈利因子 {f('profit_factor'):.2f}<br>"
            f"<span style='color:#8B949E'>回测为确定性规则结果，不构成投资建议。</span>")


# ---------------------------------------------------------------------------
# 终端 UI
# ---------------------------------------------------------------------------
class TerminalTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        tip = QLabel("🖥️ 终端模式（Bloomberg 风格）——输入 HELP 查看命令")
        tip.setStyleSheet("color:#8B949E;font-size:12px;")
        lay.addWidget(tip)

        self.out = QTextBrowser()
        self.out.setOpenExternalLinks(False)
        lay.addWidget(self.out, 1)

        row = QHBoxLayout()
        row.addWidget(QLabel(">"))
        self.inp = QLineEdit()
        self.inp.setPlaceholderText("输入命令，如 DES 600519 / GP AAPL / BT rsi")
        self.inp.returnPressed.connect(self._submit)
        row.addWidget(self.inp, 1)
        lay.addLayout(row)

        self.out.setHtml(self._banner())

    @staticmethod
    def _banner() -> str:
        return (f"<div style='font-family:Consolas,monospace;line-height:1.6'>"
                f"<b>疏影·知微 Terminal</b> v0.8.0<br>"
                f"<span style='color:#8B949E'>" + CMD_HELP.replace("\n", "<br>")
                + "</span></div>")

    def _submit(self) -> None:
        line = self.inp.text().strip()
        self.inp.clear()
        if not line:
            return
        cmd = parse_command(line)
        self.out.append(f"<div style='color:#00E5FF;font-family:Consolas,monospace'>"
                        f"> {line}</div>")
        text = execute_command(cmd)
        if text:
            self.out.append(text)


if __name__ == "__main__":
    # 自检：命令解析 + 执行（无 Qt 事件循环）
    assert parse_command("DES 600519")["action"] == "DES"
    assert parse_command("bt rsi")["strategy"] == "rsi"
    assert parse_command("FOO x")["action"] == "ERR"
    assert parse_command("BT nope")["error"]
    print("terminal parse self-check ok")
