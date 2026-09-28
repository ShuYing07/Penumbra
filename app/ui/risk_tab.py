# -*- coding: utf-8 -*-
"""风控 Tab（企业版）：组合 VaR / 压力测试 / 收益归因 / 合规规则检查。

输入格式：持仓行 "代码,权重[,行业]" 每行一条，如：
    600519,0.4,消费
    AAPL,0.4,科技
    0700.HK,0.2,科技
"""
from __future__ import annotations

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QTextEdit, QPushButton, QTableWidget,
                             QTableWidgetItem, QLineEdit)
from PyQt6.QtCore import Qt

from app.ui.ui_theme import BG_CARD, BORDER, TEXT_MAIN, TEXT_SUB, ACCENT


class RiskTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        title = QLabel("🛡️ 风控中心（企业版）")
        title.setStyleSheet(f"font-size:15px; font-weight:bold; color:{TEXT_MAIN};")
        lay.addWidget(title)
        tip = QLabel("历史统计工具：VaR / 压力测试 / 归因 / 合规规则。不构成投资建议。")
        tip.setStyleSheet(f"color:{TEXT_SUB}; font-size:11px;")
        lay.addWidget(tip)

        row = QHBoxLayout()
        row.addWidget(QLabel("持仓（代码,权重[,行业]，每行一条）："), 0)
        lay.addLayout(row)
        self.positions = QTextEdit()
        self.positions.setPlainText("600519,0.4,消费\nAAPL,0.4,科技\n0700.HK,0.2,科技")
        self.positions.setMaximumHeight(90)
        self.positions.setStyleSheet(
            f"background:{BG_CARD}; border:1px solid {BORDER}; border-radius:8px; color:{TEXT_MAIN};")
        lay.addWidget(self.positions)

        row2 = QHBoxLayout()
        for txt, fn in (("计算 VaR(95%)", self._var), ("压力测试", self._stress),
                        ("收益归因", self._attr), ("合规检查", self._compliance)):
            b = QPushButton(txt)
            b.setStyleSheet(f"background:{ACCENT}; color:#0A0E17; border-radius:6px; padding:6px 12px;")
            b.clicked.connect(fn)
            row2.addWidget(b)
        lay.addLayout(row2)

        self.table = QTableWidget(0, 3)
        self.table.setStyleSheet(
            f"QTableWidget {{ background:{BG_CARD}; border:1px solid {BORDER};"
            f" border-radius:8px; color:{TEXT_MAIN}; gridline-color:{BORDER}; }}")
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table, 1)
        self.result_label = QLabel("")
        self.result_label.setStyleSheet(f"color:{TEXT_SUB}; font-size:11px;")
        lay.addWidget(self.result_label)

    # ---------------- 数据 ----------------
    def _parse(self) -> list[dict]:
        rows = []
        for line in self.positions.toPlainText().splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.replace("，", ",").split(",")]
            if len(parts) < 2:
                continue
            rows.append({"ticker": parts[0], "weight": float(parts[1]),
                         "sector": parts[2] if len(parts) > 2 else ""})
        return rows

    def _show(self, headers: list[str], rows: list[list], note: str) -> None:
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, v in enumerate(r):
                self.table.setItem(i, j, QTableWidgetItem(str(v)))
        self.result_label.setText(note)

    def _fetch_returns(self, tickers: list[str]):
        import pandas as pd
        from core.data import service
        df_list = []
        for t in tickers:
            try:
                d, _ = service.get_daily(t)
                if len(d) >= 20:
                    df_list.append(d["close"].pct_change().rename(t))
            except Exception:  # noqa: BLE001
                continue
        if not df_list:
            raise ValueError("无法获取行情数据（检查网络或代码）")
        return pd.concat(df_list, axis=1).dropna()

    def _var(self) -> None:
        try:
            from core.risk_engine import calculate_var
            pos = self._parse()
            rets = self._fetch_returns([p["ticker"] for p in pos])
            weights = [p["weight"] for p in pos]
            r = calculate_var(rets, weights, confidence=0.95)
            self._show(["指标", "数值", "说明"],
                       [[k, v, ""] for k, v in r.items()],
                       f"VaR(95%) {r['var_pct']}% ｜ CVaR {r['cvar_pct']}% ｜ 样本 {r['samples']}")
        except Exception as e:  # noqa: BLE001
            self._show(["错误"], [[str(e)]], "计算失败")

    def _stress(self) -> None:
        try:
            from core.risk_engine import stress_test
            pos = self._parse()
            rets = self._fetch_returns([p["ticker"] for p in pos])
            weights = [p["weight"] for p in pos]
            st = stress_test(rets, weights)
            self._show(["情景", "市场变动%", "组合冲击%"],
                       [[s["scenario"], s["market_shift_pct"], s["portfolio_impact_pct"]]
                        for s in st],
                       "历史统计模拟，不构成投资建议")
        except Exception as e:  # noqa: BLE001
            self._show(["错误"], [[str(e)]], "计算失败")

    def _attr(self) -> None:
        try:
            from core.risk_engine import attribution
            pos = self._parse()
            rets = self._fetch_returns([p["ticker"] for p in pos])
            weights = [p["weight"] for p in pos]
            att = attribution(rets, weights)
            rows = att.values.tolist()
            self._show(list(att.columns), rows, "收益归因分解")
        except Exception as e:  # noqa: BLE001
            self._show(["错误"], [[str(e)]], "计算失败")

    def _compliance(self) -> None:
        try:
            from core.compliance_checker import check_portfolio
            pos = self._parse()
            res = check_portfolio(pos)
            vs = res["violations"]
            rows = [[v.get("type"), v.get("ticker") or v.get("sector"),
                     v["message"]] for v in vs] if vs else [["OK", "-", "组合合规"]]
            self._show(["类型", "标的/行业", "说明"], rows,
                       f"合规：{'通过' if res['pass'] else f'违规 {len(vs)} 项'} ｜ 行业暴露 {res['exposure']}")
        except Exception as e:  # noqa: BLE001
            self._show(["错误"], [[str(e)]], "检查失败")
