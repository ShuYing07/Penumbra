# -*- coding: utf-8 -*-
"""证据链回溯面板（模块六）：点击结论旁的 🔗 查看该结论的完整证据链。

数据源：core.evidence_manager.get_evidence(evidence_id) —— 结论 ↔ 原文 ↔ 数据快照。
对齐 VeriFin 六元组溯源 + rag-financial-copilot 结论原文回溯设计。
"""
from __future__ import annotations

import logging
import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QScrollArea, QTextEdit,
                             QVBoxLayout, QWidget)

log = logging.getLogger("stockai.ui.evidence")


def _fmt_val(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, (dict, list)):
        try:
            return json.dumps(v, ensure_ascii=False, indent=1)[:800]
        except Exception:  # noqa: BLE001
            return str(v)[:800]
    return str(v)[:800]


def evidence_to_html(evidence: list[dict]) -> str:
    if not evidence:
        return ("<div style='color:#8B949E;padding:16px'>"
                "暂无证据记录（本次分析为确定性规则输出，或证据未登记）。</div>")
    parts = [
        "<div style='font-family:Microsoft YaHei,Segoe UI,sans-serif;color:#DCE1EB'>",
        "<h3 style='color:#00B4D8'>🔗 证据链（结论 ↔ 数据来源 ↔ 快照）</h3>",
        f"<p style='color:#8B949E'>共 {len(evidence)} 条 claim 记录</p>",
    ]
    for i, ev in enumerate(evidence, 1):
        claim = ev.get("claim") or ev.get("claim_text") or "结论/引用"
        source = ev.get("source") or ev.get("data_source") or "本地数据"
        snap = ev.get("data_snapshot") or ev.get("snapshot") or ev.get("data") or {}
        created = ev.get("created_at") or ev.get("ts") or ""
        parts.append(
            f"<div style='background:rgba(19,23,34,0.85);border:1px solid #1E2530;"
            f"border-radius:8px;padding:10px;margin-bottom:8px;'>"
            f"<div style='font-weight:bold;color:#E6EDF3'>Claim {i}：{_fmt_val(claim)[:200]}</div>"
            f"<div style='color:#8B949E;font-size:12px;'>来源：{_fmt_val(source)[:120]}"
            + (f"　时间：{created}" if created else "") + "</div>"
            f"<pre style='background:#0D1117;border-radius:6px;padding:8px;"
            f"color:#A5D6FF;font-size:12px;white-space:pre-wrap;margin:6px 0 0 0;'>"
            f"{_fmt_val(snap)}</pre></div>")
    parts.append("</div>")
    return "".join(parts)


class EvidenceDialog(QDialog):
    """证据链回溯对话框：输入 evidence_id → 展示全部 claim 证据。"""

    def __init__(self, evidence_id: str | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔗 证据链回溯")
        self.resize(720, 560)
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("证据ID："))
        self.id_input = QLineEdit()
        if evidence_id:
            self.id_input.setText(evidence_id)
        self.id_input.setPlaceholderText("粘贴 evidence_id（如 agent|xxxxxxxxxxxx 或 RAG 分析 ID）")
        top.addWidget(self.id_input, 1)
        btn = QPushButton("查询")
        btn.clicked.connect(self._load)
        top.addWidget(btn)
        lay.addLayout(top)

        self.out = QTextEdit()
        self.out.setReadOnly(True)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        _v = QVBoxLayout(inner)
        _v.setContentsMargins(0, 0, 0, 0)
        _v.addWidget(self.out)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        if evidence_id:
            self._load()

    def _load(self) -> None:
        eid = self.id_input.text().strip()
        if not eid:
            self.out.setHtml("<p style='color:#FFA726'>请输入 evidence_id</p>")
            return
        try:
            from core.evidence_manager import get_evidence
            ev = get_evidence(eid)
            self.out.setHtml(evidence_to_html(ev))
        except Exception as e:  # noqa: BLE001
            self.out.setHtml(f"<p style='color:#FF1744'>证据查询失败：{str(e)[:200]}</p>")


if __name__ == "__main__":
    print(evidence_to_html([
        {"claim": "营收增长15%", "source": "财报", "data_snapshot": {"ticker": "600519"},
         "created_at": "2026-09-30"},
    ])[:200])
