# -*- coding: utf-8 -*-
"""合规测试标签页（模块四）：31 个监管场景沙箱运行 + ToolGate 解耦展示 + 报告导出。"""
from __future__ import annotations

import json
import logging

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QScrollArea, QTextEdit, QVBoxLayout, QWidget)

log = logging.getLogger("stockai.ui.compliancetest")


def _render(results: list[dict], gate_ok: int, gate_deny: int) -> str:
    lines = ["<div style='font-family:Microsoft YaHei,Segoe UI,sans-serif;color:#DCE1EB'>",
             "<h2>🛡️ 合规沙箱测试</h2>",
             f"<p>共 <b>{len(results)}</b> 个监管场景　工具门控：允许 <b style='color:#00C853'>{gate_ok}</b> / "
             f"拒绝 <b style='color:#FF1744'>{gate_deny}</b></p>"]
    by_cat: dict[str, int] = {}
    for r in results:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
    lines.append("<p style='color:#8B949E'>类别分布：" +
                 "　".join(f"{k}×{v}" for k, v in by_cat.items()) + "</p>")
    lines.append("<table style='border-collapse:collapse;width:100%'>")
    lines.append("<tr><th style='border:1px solid #1E2530;padding:5px;color:#8B949E'>ID</th>"
                 "<th style='border:1px solid #1E2530;padding:5px;color:#8B949E'>场景</th>"
                 "<th style='border:1px solid #1E2530;padding:5px;color:#8B949E'>类别</th>"
                 "<th style='border:1px solid #1E2530;padding:5px;color:#8B949E'>规则数</th>"
                 "<th style='border:1px solid #1E2530;padding:5px;color:#8B949E'>初始状态</th></tr>")
    for r in results:
        n_flag = len(r["initial_flags"])
        state = ("<span style='color:#00C853'>✅ 基线干净</span>" if n_flag == 0
                 else f"<span style='color:#FFA726'>⚠️ 初始触发 {n_flag} 条</span>")
        lines.append(
            f"<tr><td style='border:1px solid #1E2530;padding:5px'>{r['scenario_id']}</td>"
            f"<td style='border:1px solid #1E2530;padding:5px'>{r['name']}</td>"
            f"<td style='border:1px solid #1E2530;padding:5px;color:#8B949E'>{r['category']}</td>"
            f"<td style='border:1px solid #1E2530;padding:5px'>{r['rule_count']}</td>"
            f"<td style='border:1px solid #1E2530;padding:5px'>{state}</td></tr>")
    lines.append("</table>")
    lines.append("<p style='color:#8B949E'>点击「运行违规路径演示」可对 aml-01 场景执行 120 万未报告转账，"
                 "验证合规约束触发与审计记录。</p>")
    lines.append("</div>")
    return "".join(lines)


def _violation_demo() -> dict:
    """对 aml-01 跑违规路径 + 合规补救路径，返回对比结果。"""
    from security.compliance_sandbox import run_agent_in_sandbox

    def bad_agent(env):
        return [{"type": "transfer", "from": "a1", "to": "a2", "amount": 1_200_000,
                 "id": "tx-bad"}]
    bad = run_agent_in_sandbox(bad_agent, "aml-01")

    def good_agent(env):
        # 合规路径：转账后立即提交 STR
        acts = [{"type": "transfer", "from": "a1", "to": "a2", "amount": 1_200_000,
                 "id": "tx-ok"}]
        return acts
    good = run_agent_in_sandbox(good_agent, "aml-01")
    # 合规路径需带 STR 标记 —— 在动作序列里补 mark_str
    def good_agent2(env):
        acts = [{"type": "transfer", "from": "a1", "to": "a2", "amount": 1_200_000,
                 "id": "tx-ok"}]
        acts.append({"type": "mark_str", "tx_id": "tx-ok"})
        return acts
    good2 = run_agent_in_sandbox(good_agent2, "aml-01")
    return {"bad": bad, "good": good2}


class _Worker(QThread):
    done = pyqtSignal(dict)

    def __init__(self, mode: str, parent=None):
        super().__init__(parent)
        self._mode = mode

    def run(self):
        try:
            if self._mode == "scan":
                from security.compliance_sandbox import run_all_scenarios
                from security.compliance_sandbox import ToolGate
                gate = ToolGate()
                gate_ok, gate_deny = 0, 0
                for t in ("transfer", "disclose", "query"):
                    ok, _ = gate.check_tool_call(t, {"from": "a1", "to": "a2",
                                                     "amount": 1.0} if t == "transfer"
                                                 else ({"symbol": "x", "text": "y"}
                                                       if t == "disclose" else {"sql": "SELECT 1"}))
                    gate_ok += int(ok)
                ok, _ = gate.check_tool_call("hack_db", {})
                gate_deny += int(not ok)
                results = run_all_scenarios()
                self.done.emit({"mode": "scan", "results": results,
                                "gate_ok": gate_ok, "gate_deny": gate_deny})
            else:
                self.done.emit({"mode": "violation", **(_violation_demo())})
        except Exception as e:  # noqa: BLE001
            log.exception("compliance worker error")
            self.done.emit({"mode": "error", "error": str(e)[:200]})


class ComplianceTestTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        self.btn_scan = QPushButton("扫描全部场景")
        self.btn_scan.clicked.connect(lambda: self._run("scan"))
        top.addWidget(self.btn_scan)
        self.btn_vio = QPushButton("运行违规路径演示")
        self.btn_vio.clicked.connect(lambda: self._run("violation"))
        top.addWidget(self.btn_vio)
        self.btn_review = QPushButton("🔎 AI 评审员")
        self.btn_review.setToolTip("对一段 AI 输出做合规评审（承诺收益/无风险/荐股/内幕/免责声明）")
        self.btn_review.clicked.connect(self._review)
        top.addWidget(self.btn_review)
        self.status = QLabel("")
        self.status.setStyleSheet("color:#8B949E")
        top.addWidget(self.status, 1)
        lay.addLayout(top)

        rev_row = QHBoxLayout()
        rev_row.addWidget(QLabel("评审文本："))
        self.review_input = QLineEdit()
        self.review_input.setPlaceholderText("粘贴要评审的 AI 输出（如“这只股票必涨，无风险稳赚…”）")
        self.review_input.returnPressed.connect(self._review)
        rev_row.addWidget(self.review_input, 1)
        lay.addLayout(rev_row)

        hint = QLabel("基于 FinVault 的 31 个监管案例场景（反洗钱/可疑交易/适当性/披露/市场操纵/内幕/投资者保护/数据隐私）。\n"
                      "LLM 与数据库解耦：所有工具调用必须通过 ToolGate schema 校验 + 合规检查层，违规调用被拒绝并写入哈希链审计。")
        hint.setStyleSheet("color:#6B7488")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setText("点击「扫描全部场景」查看 31 个场景基线；「运行违规路径演示」验证约束触发。")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.out)
        lay.addWidget(scroll, 1)

        self._worker: _Worker | None = None

    def _run(self, mode: str):
        self.status.setText("运行中…")
        self._worker = _Worker(mode, self)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _review(self):
        """AI 评审员：对输入文本做输出前合规评审。"""
        text = self.review_input.text().strip()
        if not text:
            self.status.setText("请输入评审文本")
            return
        self.status.setText("评审中…")
        try:
            from security.ai_reviewer import review_output
            r = review_output(text)
        except Exception as e:  # noqa: BLE001
            self.out.setHtml(f"<p style='color:#FF1744'>评审失败：{str(e)[:200]}</p>")
            self.status.setText("失败")
            return
        self.status.setText("完成")
        color = "#00C853" if r["passed"] else "#FF1744"
        lines = [
            "<div style='font-family:Microsoft YaHei,Segoe UI,sans-serif;color:#DCE1EB'>",
            "<h2>🔎 AI 评审员（输出前合规审核）</h2>",
            f"<p>结论：<b style='color:{color}'>{'✅ 通过' if r['passed'] else '❌ 需整改'}</b>　"
            f"合规评分：<b>{r['score']}/100</b>　评审引擎：{r['engine']}</p>",
            f"<p style='color:#8B949E'>免责声明：{'✅ 已含' if r['disclaimer_ok'] else '❌ 缺失'}</p>",
        ]
        if r["issues"]:
            lines.append("<ul>")
            for i in r["issues"]:
                sev_color = {"high": "#FF1744", "medium": "#FFA726", "low": "#8B949E"}.get(i["severity"], "#FFA726")
                lines.append(
                    f"<li style='color:{sev_color}'>[{i['severity']}] {i['label']}"
                    + (f"（命中“{i['keyword']}”）" if i.get("keyword") else "")
                    + f"<br/><span style='color:#8B949E'>建议：{i.get('suggestion', '')}</span></li>")
            lines.append("</ul>")
        else:
            lines.append("<p style='color:#00C853'>未命中合规风险规则。</p>")
        if r.get("llm_review"):
            lr = r["llm_review"]
            lines.append(f"<p style='color:#8B949E'>LLM 独立评审：{'通过' if lr.get('passed') else '提示整改'} "
                        f"（{'；'.join(lr.get('issues') or [])}）</p>")
        lines.append("<p style='color:#6B7488'>对齐 GenA.I. 沙盒++「AI 评审员」方案：AI 内容对外输出前由独立评审层把关。</p>")
        lines.append("</div>")
        self.out.setHtml("".join(lines))

    def _on_done(self, payload: dict):
        self.status.setText("完成")
        if payload.get("mode") == "error":
            self.out.setHtml(f"<p style='color:#FF1744'>错误：{payload['error']}</p>")
            return
        if payload["mode"] == "scan":
            self.out.setHtml(_render(payload["results"], payload["gate_ok"],
                                     payload["gate_deny"]))
        else:
            bad = payload.get("bad") or {}
            good = payload.get("good") or {}
            html = [
                "<div style='font-family:Microsoft YaHei,Segoe UI,sans-serif;color:#DCE1EB'>",
                "<h2>⚖️ aml-01 违规 vs 合规路径对比</h2>",
                f"<h3>❌ 违规路径（120万转账未报告STR）</h3>",
                f"<p>结果：<b style='color:#FF1744'>{bad.get('status', '')}</b></p>",
                "<ul>",
            ]
            for v in (bad.get("violations") or []):
                html.append(f"<li style='color:#FFA726'>[{v['severity']}] {v['desc']}</li>")
            html.append("</ul>")
            html.append("<h3>✅ 合规路径（转账 + 提交 STR）</h3>")
            html.append(f"<p>结果：<b style='color:#00C853'>{good.get('status', '')}</b>　"
                        f"违规数：{len(good.get('violations') or [])}</p>")
            html.append("<p style='color:#8B949E'>每次运行自动写入 security.audit_ledger 哈希链审计日志。</p>")
            html.append("</div>")
            self.out.setHtml("".join(html))
