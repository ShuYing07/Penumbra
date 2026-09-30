# -*- coding: utf-8 -*-
"""多模态标签页（模块一）：上传 PDF/音频/图片，自动解析生成分析报告。

后端降级链：
- 音频 → faster-whisper 转录（未装则提示，可用 .txt 逐字稿替代）
- 图片 → 视觉 LLM（SILICONFLOW_API_KEY / ollama 视觉模型；未配置则提示，可用 .txt 描述替代）
- PDF → pdfplumber/pypdf（未装则提示，可用 .txt 文本替代）
"""
from __future__ import annotations

import json
import logging

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QPushButton,
                             QScrollArea, QTextEdit, QVBoxLayout, QWidget)

log = logging.getLogger("stockai.ui.multimodal")


def _render(result: dict) -> str:
    """渲染解析结果为 HTML 卡片（暗色主题）。"""
    lines = ["<div style='font-family:Microsoft YaHei,Segoe UI,sans-serif;color:#DCE1EB'>"]
    if not result.get("ok"):
        lines.append("<h2>🧩 多模态解析</h2>")
        lines.append(f"<p style='color:#FFA726'>⚠️ {result.get('note', '未知错误')}</p>")
        lines.append("</div>")
        return "".join(lines)

    kind = result.get("kind", "")
    lines.append(f"<h2>🧩 多模态解析报告 · {kind}</h2>")
    lines.append(f"<p style='color:#8B949E'>来源：{result.get('source', 'N/A')}　"
                 f"时间：{result.get('created_at', '')}</p><hr>")

    if kind == "earnings_call":
        tone = result.get("tone", "")
        color = {"乐观": "#00C853", "谨慎": "#FFA726", "中性": "#8B949E"}.get(tone, "#DCE1EB")
        lines.append(f"<h3>管理层语气：<span style='color:{color}'>{tone}</span></h3>")
        lines.append(f"<h3>AI 分析</h3><p>{result.get('analysis', '')}</p>")
        lines.append("<h3>转录文本（节选）</h3>")
        trans = result.get("transcript", "")
        lines.append(f"<pre style='white-space:pre-wrap;color:#8B949E;max-height:220px;"
                     f"overflow:auto;border:1px solid #1E2530;padding:8px'>{trans[:3000]}</pre>")
    elif kind == "chart_image":
        lines.append(f"<h3>趋势判断：<span style='color:#00B4D8'>{result.get('trend', '')}</span></h3>")
        forms = result.get("forms", [])
        lines.append(f"<p>形态：<b>{'、'.join(forms)}</b></p>")
        sup = result.get("support_levels", []) or []
        res = result.get("resistance_levels", []) or []
        lines.append(f"<p>支撑位：{', '.join(sup) if sup else '—'}　"
                     f"阻力位：{', '.join(res) if res else '—'}</p>")
        lines.append(f"<h3>AI 分析</h3><p>{result.get('analysis', '')}</p>")
    elif kind == "pdf_report":
        figs = result.get("figures", {}) or {}
        lines.append("<h3>关键财务数据（规则提取）</h3><table style='border-collapse:collapse'>")
        for k, v in figs.items():
            lines.append(f"<tr><td style='border:1px solid #1E2530;padding:6px;color:#8B949E'>{k}</td>"
                         f"<td style='border:1px solid #1E2530;padding:6px'><b>{v}</b></td></tr>")
        lines.append("</table>")
        tables = result.get("tables", []) or []
        if tables:
            lines.append(f"<p style='color:#8B949E'>共提取 {len(tables)} 张表格（第一张预览）</p>")
            rows = "".join("<tr>" + "".join(f"<td style='border:1px solid #1E2530;padding:4px'>{c[:40]}</td>"
                                            for c in r[:6]) + "</tr>" for r in tables[:5])
            lines.append(f"<table style='border-collapse:collapse'>{rows}</table>")
        lines.append(f"<h3>AI 分析</h3><p>{result.get('analysis', '')}</p>")
    lines.append("</div>")
    return "".join(lines)


class _ParseWorker(QThread):
    done = pyqtSignal(dict)

    def __init__(self, path: str, kind: str | None, parent=None):
        super().__init__(parent)
        self._path = path
        self._kind = kind

    def run(self):
        try:
            from core.multimodal_parser import parse_multimodal_file
            result = parse_multimodal_file(self._path, self._kind)
        except Exception as e:  # noqa: BLE001
            log.exception("multimodal parse error")
            result = {"ok": False, "kind": self._kind or "unknown",
                      "note": f"解析异常：{str(e)[:120]}"}
        self.done.emit(result)


class MultimodalTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        self.lbl = QLabel("文件：")
        top.addWidget(self.lbl)
        self.file_label = QLabel("（未选择）")
        self.file_label.setStyleSheet("color:#8B949E")
        top.addWidget(self.file_label, 1)
        self.btn_open = QPushButton("选择文件")
        self.btn_open.clicked.connect(self._pick)
        top.addWidget(self.btn_open)
        self.btn_run = QPushButton("开始解析")
        self.btn_run.clicked.connect(self._run)
        top.addWidget(self.btn_run)
        lay.addLayout(top)

        hint = QLabel("支持：PDF 财报 / 音频（电话会议录音 MP3·WAV·M4A）/ 图表图片（PNG·JPG）。\n"
                      "未装转录或视觉模型时，可把逐字稿/描述保存为 .txt 上传，自动降级进入分析。")
        hint.setStyleSheet("color:#6B7488")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setText("选择文件后点击「开始解析」。解析过程展示：转录文本、关键信息、语气/形态判断。")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.out)
        lay.addWidget(scroll, 1)

        self._worker: _ParseWorker | None = None
        self._path: str | None = None
        self._kind: str | None = None

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择要解析的文件",
            "", "金融文档 (*.pdf *.txt *.md *.json);;音频 (*.mp3 *.wav *.m4a *.flac *.ogg);;"
                "图表图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            self._path = path
            self._kind = None
            self.file_label.setText(path)

    def _run(self):
        if not self._path:
            self.out.setHtml("<p style='color:#FFA726'>请先选择文件。</p>")
            return
        self.btn_run.setEnabled(False)
        self.out.setHtml("<p style='color:#8B949E'>解析中，请稍候…</p>")
        self._worker = _ParseWorker(self._path, self._kind, self)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_done(self, result: dict):
        self.btn_run.setEnabled(True)
        self.out.setHtml(_render(result))
        if result.get("ok"):
            try:
                from security.audit_ledger import append
                append("multimodal", "parse_ok",
                       json.dumps({"file": self._path, "kind": result.get("kind"),
                                   "source": result.get("source")}, ensure_ascii=False)[:300])
            except Exception:  # noqa: BLE001
                pass
