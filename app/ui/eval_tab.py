# -*- coding: utf-8 -*-
"""分析质量总览标签页（模块一 + 第20轮升级）。

三个子页，从「文本好不好」到「结论能不能信」逐级递进：

1. **八维评测**：FORCE-Bench 八维打分 + 历史趋势（原有能力，保持不变）；
2. **四维质量**：机构级四维（正确性/适配性/鲁棒性/合规性）**雷达图**
   + 资本-资产匹配结论；
3. **可信度与护栏**：结论级**置信度自评**（七因子 + 限制条件）
   + **红队对抗**护栏得分卡（十大攻击技术族的防守率）。

设计约束：
- 纯 QPainter 画雷达/折线，**不引入任何新依赖**；
- 涨跌语义色（#00C853/#FF1744）**只用于涨跌**，本页一律用中性色
  （ACCENT / WARN / TEXT_SUB），避免视觉语义串台；
- 所有核心逻辑调用均有 try/except 兜底，单个子页失败不影响主窗口。
"""
from __future__ import annotations

import json
import logging
import math

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QLabel,
                             QLineEdit, QPlainTextEdit, QProgressBar,
                             QPushButton, QSlider, QSpinBox, QSplitter,
                             QTabWidget, QTableWidget, QTableWidgetItem,
                             QTextEdit, QVBoxLayout, QWidget)

from app.ui.ui_theme import (ACCENT, BG_CARD, BORDER, TEXT_MAIN, TEXT_SUB, WARN)

log = logging.getLogger("stockai.ui.eval")

_DIMS_CN = {"accuracy": "准确性", "citation": "引用", "clarity": "清晰度",
            "depth": "深度", "evidence": "有据可依", "timeliness": "时效性",
            "relevance": "相关性", "structure": "结构"}

# 四维 bureaucratic 名称本地化
_FRAME_CN = {"correctness": "正确性", "fitness": "适配性",
             "robustness": "鲁棒性", "compliance": "合规性"}

_MATCH_CN = {"matched": "适配（推荐与资金属性相符）",
             "mismatched": "不匹配（推荐与资金属性冲突）",
             "refused_ok": "主动拒答（审慎，视为合格）",
             "unknown": "未明确（无法判定）"}

_SOURCE_CN = [("exchange", "交易所公告"), ("filing", "定期报告"),
              ("official", "公司官方"), ("regulator", "监管披露"),
              ("financial", "结构化财报"), ("market", "行情数据"),
              ("research", "券商研报"), ("news", "新闻"),
              ("social", "社交论坛"), ("model", "模型推断")]


# ---------------------------------------------------------------------------
# 自绘图组件
# ---------------------------------------------------------------------------
class _RadarChart(QWidget):
    """N 维雷达图（QPainter，无外部依赖）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[tuple[str, float]] = []
        self.setMinimumHeight(200)

    def set_data(self, items: list[tuple[str, float]]) -> None:
        """items: [(维度名, 0~1 分值)]。"""
        self._items = list(items)
        self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(BG_CARD))
        n = len(self._items)
        if n < 3:
            p.setPen(QColor(TEXT_SUB))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter,
                       "暂无评测结果，先在上方评测一次")
            return
        cx, cy = w / 2.0, h / 2.0 + 4
        r = min(w, h) / 2.0 - 34
        # 背景同心多边形
        for ring in (0.25, 0.5, 0.75, 1.0):
            pts = []
            for i in range(n):
                a = -math.pi / 2 + 2 * math.pi * i / n
                pts.append((cx + r * ring * math.cos(a),
                            cy + r * ring * math.sin(a)))
            p.setPen(QPen(QColor(BORDER), 1))
            for i in range(n):
                p.drawLine(int(pts[i][0]), int(pts[i][1]),
                           int(pts[(i + 1) % n][0]), int(pts[(i + 1) % n][1]))
        pts = []
        vals = []
        for i, (_name, v) in enumerate(self._items):
            a = -math.pi / 2 + 2 * math.pi * i / n
            v = min(1.0, max(0.0, float(v)))
            vals.append(v)
            x = cx + r * v * math.cos(a)
            y = cy + r * v * math.sin(a)
            pts.append((x, y))
            p.setPen(QPen(QColor(BORDER), 1))
            p.drawLine(int(cx), int(cy), int(cx + r * math.cos(a)),
                       int(cy + r * math.sin(a)))
        # 数据多边形（中性色，不占用涨跌红绿）
        poly = QColor(ACCENT)
        poly.setAlpha(70)
        p.setBrush(poly)
        p.setPen(QPen(QColor(ACCENT), 2))
        for i in range(n):
            p.drawLine(int(pts[i][0]), int(pts[i][1]),
                       int(pts[(i + 1) % n][0]), int(pts[(i + 1) % n][1]))
        for (x, y) in pts:
            p.setBrush(QColor(ACCENT))
            p.drawEllipse(int(x) - 3, int(y) - 3, 6, 6)
        # 轴标签
        p.setPen(QColor(TEXT_SUB))
        for i, (name, v) in enumerate(self._items):
            a = -math.pi / 2 + 2 * math.pi * i / n
            lx = cx + (r + 20) * math.cos(a)
            ly = cy + (r + 20) * math.sin(a)
            rect = QRectF(lx - 34, ly - 9, 68, 18)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                       f"{name} {vals[i]:.2f}")


class _TrendChart(QWidget):
    """历史总分趋势（QPainter 折线）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: list[float] = []
        self.setMinimumHeight(120)

    def set_data(self, totals: list[float]) -> None:
        self._points = list(totals)
        self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(BG_CARD))
        if not self._points:
            p.setPen(QColor(TEXT_SUB))
            p.drawText(QRectF(8, 8, w - 16, h - 16),
                       Qt.AlignmentFlag.AlignCenter,
                       "暂无评测历史，先在上方评测一次")
            return
        pad = 10
        max_v, min_v = 1.0, 0.0
        px = py = 0.0
        for i, v in enumerate(self._points):
            x = pad + i * (w - 2 * pad) / max(1, len(self._points) - 1)
            y = h - pad - (v - min_v) / (max_v - min_v) * (h - 2 * pad)
            p.setPen(QPen(QColor(ACCENT), 2))
            if i > 0:
                p.drawLine(int(px), int(py), int(x), int(y))
            p.setBrush(QColor(ACCENT))
            p.drawEllipse(int(x) - 3, int(y) - 3, 6, 6)
            px, py = x, y
        p.setPen(QColor(TEXT_SUB))
        p.drawText(QRectF(pad, 2, w - 2 * pad, 18), Qt.AlignmentFlag.AlignLeft,
                   f"最近 {len(self._points)} 次评测总分趋势")


# ---------------------------------------------------------------------------
# 主面板
# ---------------------------------------------------------------------------
class EvalTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._profiles: list[dict] = []
        self._build()

    # ---------------------------------------------------------------- 构建
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        title = QLabel("分析质量总览")
        title.setStyleSheet(f"color:{TEXT_MAIN};font-size:16px;font-weight:bold;")
        root.addWidget(title)
        sub = QLabel("八维打分 · 四维机构评测 · 结论置信度与红队护栏")
        sub.setStyleSheet(f"color:{TEXT_SUB};font-size:12px;")
        root.addWidget(sub)

        self.sub = QTabWidget()
        self.sub.addTab(self._page_force(), "八维评测")
        self.sub.addTab(self._page_quality(), "四维质量")
        self.sub.addTab(self._page_trust(), "可信度与护栏")
        root.addWidget(self.sub, 1)

        self._refresh_history()

    # ---------------- 页 1：八维（原能力） ----------------
    def _page_force(self) -> QWidget:
        page = QWidget()
        rl = QVBoxLayout(page)
        split = QSplitter(Qt.Orientation.Vertical)
        inp = QWidget()
        il = QVBoxLayout(inp)
        il.addWidget(QLabel("AI 输出文本"))
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText(
            "粘贴要评测的分析文本…（含数字、数据来源、结构标记得分更高）")
        self.text.setStyleSheet(_box_style())
        self.text.setMinimumHeight(90)
        il.addWidget(self.text)
        row = QHBoxLayout()
        row.addWidget(QLabel("查询"))
        self.query = QLineEdit()
        self.query.setPlaceholderText("如：分析茅台技术面")
        self.query.setStyleSheet(_box_style())
        row.addWidget(self.query, 3)
        row.addWidget(QLabel("参考数据(JSON)"))
        self.ref = QLineEdit()
        self.ref.setPlaceholderText('{"close":320.5,"rsi14":62.9}（可选）')
        self.ref.setStyleSheet(_box_style())
        row.addWidget(self.ref, 3)
        il.addLayout(row)
        b_run = QPushButton("▶ 评测")
        b_run.setStyleSheet(_btn(primary=True))
        b_run.clicked.connect(self._run)
        il.addWidget(b_run, 0, Qt.AlignmentFlag.AlignRight)
        split.addWidget(inp)

        res = QWidget()
        rl2 = QVBoxLayout(res)
        self.total_lbl = QLabel("总分：—")
        self.total_lbl.setStyleSheet(
            f"color:{ACCENT};font-size:14px;font-weight:bold;")
        rl2.addWidget(self.total_lbl)
        self.bars: dict[str, QProgressBar] = {}
        for key in ("accuracy", "citation", "clarity", "depth", "evidence",
                    "timeliness", "relevance", "structure"):
            h = QHBoxLayout()
            lbl = QLabel(_DIMS_CN[key])
            lbl.setStyleSheet(f"color:{TEXT_SUB};min-width:64px;")
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(True)
            bar.setStyleSheet(
                f"QProgressBar{{background:{BG_CARD};border:1px solid {BORDER};"
                f"border-radius:4px;height:16px;}}"
                f"QProgressBar::chunk{{background:{ACCENT};border-radius:4px;}}")
            h.addWidget(lbl)
            h.addWidget(bar, 1)
            rl2.addLayout(h)
            self.bars[key] = bar
        rl2.addWidget(QLabel("历史趋势"))
        self.trend = _TrendChart()
        rl2.addWidget(self.trend, 1)
        split.addWidget(res)
        split.setSizes([240, 380])
        rl.addWidget(split, 1)
        return page

    # ---------------- 页 2：四维质量 ----------------
    def _page_quality(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(QLabel("AI 输出文本"))
        self.q_text = QPlainTextEdit()
        self.q_text.setPlaceholderText(
            "粘贴机构场景下的分析输出…（正确性/适配性/鲁棒性/合规性四维评测）")
        self.q_text.setStyleSheet(_box_style())
        self.q_text.setMinimumHeight(80)
        v.addWidget(self.q_text)

        row = QHBoxLayout()
        row.addWidget(QLabel("资金画像"))
        self.profile = QComboBox()
        self.profile.addItem("未指定", None)
        try:
            from core.eval.eval_framework import CAPITAL_PROFILES
            self._profiles = list(CAPITAL_PROFILES)
            for p in self._profiles:
                self.profile.addItem(p["name"], p["id"])
        except Exception as e:  # noqa: BLE001
            log.debug("资金画像加载失败：%s", e)
        self.profile.setStyleSheet(_box_style())
        row.addWidget(self.profile, 2)
        self.q_ref = QLineEdit()
        self.q_ref.setPlaceholderText('参考数据 JSON（可选）')
        self.q_ref.setStyleSheet(_box_style())
        row.addWidget(self.q_ref, 2)
        b = QPushButton("▶ 四维评测")
        b.setStyleSheet(_btn(primary=True))
        b.clicked.connect(self._run_quality)
        row.addWidget(b)
        v.addLayout(row)

        self.q_result = QLabel("尚未评测")
        self.q_result.setStyleSheet(
            f"color:{TEXT_MAIN};font-size:13px;font-weight:bold;")
        self.q_result.setWordWrap(True)
        v.addWidget(self.q_result)
        self.radar = _RadarChart()
        v.addWidget(self.radar, 1)
        self.q_match = QLabel("")
        self.q_match.setStyleSheet(f"color:{TEXT_SUB};font-size:12px;")
        self.q_match.setWordWrap(True)
        v.addWidget(self.q_match)
        return page

    # ---------------- 页 3：可信度与护栏 ----------------
    def _page_trust(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)

        # 置信度输入
        grid = QHBoxLayout()
        self.ev_count = QSpinBox()
        self.ev_count.setRange(0, 50)
        self.ev_count.setValue(3)
        self.ev_source = QComboBox()
        for sid, sname in _SOURCE_CN:
            self.ev_source.addItem(sname, sid)
        self.ev_days = QSpinBox()
        self.ev_days.setRange(0, 3650)
        self.ev_days.setValue(5)
        self.sample = QSpinBox()
        self.sample.setRange(0, 100000)
        self.sample.setValue(250)
        for spin, label in ((self.ev_count, "证据条数"),
                            (self.ev_days, "时效(天)"),
                            (self.sample, "样本量")):
            spin.setStyleSheet(_box_style())
            cell = QHBoxLayout()
            cell.addWidget(QLabel(label))
            cell.addWidget(spin)
            grid.addLayout(cell)
        self.ev_source.setStyleSheet(_box_style())
        cell_s = QHBoxLayout()
        cell_s.addWidget(QLabel("来源"))
        cell_s.addWidget(self.ev_source)
        grid.addLayout(cell_s)
        v.addLayout(grid)

        grid2 = QHBoxLayout()
        self.disagree = QSlider(Qt.Orientation.Horizontal)
        self.disagree.setRange(0, 100)
        self.disagree.setValue(15)
        self.decay = QSlider(Qt.Orientation.Horizontal)
        self.decay.setRange(0, 100)
        self.decay.setValue(10)
        self.unresolved = QSpinBox()
        self.unresolved.setRange(0, 20)
        self.unresolved.setValue(0)
        self.unresolved.setStyleSheet(_box_style())
        for sld, label in ((self.disagree, "多空分歧%"), (self.decay, "样本外衰减%")):
            cell = QHBoxLayout()
            cell.addWidget(QLabel(label))
            cell.addWidget(sld)
            grid2.addLayout(cell)
        cell_u = QHBoxLayout()
        cell_u.addWidget(QLabel("未决争议"))
        cell_u.addWidget(self.unresolved)
        grid2.addLayout(cell_u)
        v.addLayout(grid2)

        row = QHBoxLayout()
        b_conf = QPushButton("▶ 评估置信度")
        b_conf.setStyleSheet(_btn(primary=True))
        b_conf.clicked.connect(self._run_confidence)
        row.addWidget(b_conf)
        b_red = QPushButton("🛡️ 运行红队")
        b_red.setStyleSheet(_btn())
        b_red.clicked.connect(self._run_redteam)
        row.addWidget(b_red)
        row.addStretch(1)
        v.addLayout(row)

        self.conf_lbl = QLabel("置信度：—")
        self.conf_lbl.setStyleSheet(
            f"color:{TEXT_MAIN};font-size:14px;font-weight:bold;")
        v.addWidget(self.conf_lbl)
        self.conf_bar = QProgressBar()
        self.conf_bar.setRange(0, 100)
        self.conf_bar.setTextVisible(True)
        self.conf_bar.setStyleSheet(
            f"QProgressBar{{background:{BG_CARD};border:1px solid {BORDER};"
            f"border-radius:4px;height:18px;}}"
            f"QProgressBar::chunk{{background:{ACCENT};border-radius:4px;}}")
        v.addWidget(self.conf_bar)
        self.caveats = QTextEdit()
        self.caveats.setReadOnly(True)
        self.caveats.setPlaceholderText("限制条件将在此列出")
        self.caveats.setStyleSheet(_box_style())
        self.caveats.setMinimumHeight(70)
        v.addWidget(self.caveats)

        v.addWidget(QLabel("红队护栏得分卡"))
        self.red_table = QTableWidget(0, 5)
        self.red_table.setHorizontalHeaderLabels(
            ["攻击技术族", "总数", "突破", "防守率", "状态"])
        self.red_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.red_table.verticalHeader().setVisible(False)
        self.red_table.setStyleSheet(
            f"QTableWidget{{background:{BG_CARD};color:{TEXT_MAIN};"
            f"gridline-color:{BORDER};border:1px solid {BORDER};}}")
        v.addWidget(self.red_table, 1)
        return page

    # ---------------------------------------------------------------- 行为
    def _run(self) -> None:
        from core.eval.eval_benchmark import evaluate_analysis
        from core.eval.eval_suite import _record
        ref = {}
        if self.ref.text().strip():
            try:
                ref = json.loads(self.ref.text().strip())
            except Exception as e:  # noqa: BLE001
                self.total_lbl.setText(f"参考数据 JSON 解析失败：{e}")
                return
        r = evaluate_analysis(self.text.toPlainText(), self.query.text(), ref)
        scores, total = r["scores"], r["total"]
        self.total_lbl.setText(
            f"总分：{total:.2f}（{r['verdict']}） · 八维："
            f"{', '.join(f'{_DIMS_CN[k]}={v:.2f}' for k, v in scores.items())}")
        for k, bar in self.bars.items():
            bar.setValue(int(scores.get(k, 0) * 100))
        try:
            _record({"case_id": "manual", "query": self.query.text(),
                     "total": total, "verdict": r["verdict"],
                     "scores": scores}, "manual")
        except Exception as e:  # noqa: BLE001
            log.debug("评测历史记录失败：%s", e)
        self._refresh_history()

    def _refresh_history(self) -> None:
        try:
            from core.eval.eval_suite import history
            rows = history(limit=20)
        except Exception as e:  # noqa: BLE001
            log.debug("评测历史读取失败：%s", e)
            rows = []
        totals = [float(r["total"]) for r in rows if r.get("total") is not None]
        self.trend.set_data(list(reversed(totals)))

    def _run_quality(self) -> None:
        try:
            from core.eval.eval_framework import evaluate_framework
        except Exception as e:  # noqa: BLE001
            self.q_result.setText(f"评测框架不可用：{e}")
            return
        profile = None
        pid = self.profile.currentData()
        if pid:
            profile = next((p for p in self._profiles if p["id"] == pid), None)
        ref = {}
        if self.q_ref.text().strip():
            try:
                ref = json.loads(self.q_ref.text().strip())
            except Exception as e:  # noqa: BLE001
                self.q_result.setText(f"参考数据 JSON 解析失败：{e}")
                return
        try:
            r = evaluate_framework(self.q_text.toPlainText(),
                                   self.query.text() if hasattr(self, "query") else "",
                                   profile, ref)
        except Exception as e:  # noqa: BLE001
            self.q_result.setText(f"评测失败：{type(e).__name__}: {e}")
            return
        sc = r["scores"]
        self.q_result.setText(
            f"总分：{r['total']:.2f}（{r['verdict']}） · "
            + " / ".join(f"{_FRAME_CN[k]}={v:.2f}" for k, v in sc.items()))
        self.radar.set_data([(_FRAME_CN[k], float(sc[k]))
                             for k in ("correctness", "fitness",
                                       "robustness", "compliance")])
        assets = r.get("mentioned_assets") or []
        names = []
        if assets:
            try:
                from core.eval.eval_framework import ASSET_CLASSES
                names = [a["name"] for a in ASSET_CLASSES if a["id"] in assets]
            except Exception:  # noqa: BLE001
                names = assets
        self.q_match.setText(
            f"资金画像：{r.get('profile') or '未指定'} · "
            f"匹配结论：{_MATCH_CN.get(r.get('match_verdict', 'unknown'), '未知')}"
            + (f"\n识别到的资产类别：{'、'.join(names)}" if names else ""))

    def _run_confidence(self) -> None:
        try:
            from core.agents.self_assessment import assess, to_ui
        except Exception as e:  # noqa: BLE001
            self.conf_lbl.setText(f"置信度模块不可用：{e}")
            return
        src = self.ev_source.currentData() or "unknown"
        ev = [{"source": src} for _ in range(int(self.ev_count.value()))]
        try:
            rep = assess(evidence=ev,
                         freshness_days=float(self.ev_days.value()),
                         disagreement=self.disagree.value() / 100.0,
                         unresolved=int(self.unresolved.value()),
                         sample_size=int(self.sample.value()),
                         oos_decay=self.decay.value() / 100.0)
            d = to_ui(rep)
        except Exception as e:  # noqa: BLE001
            self.conf_lbl.setText(f"计算失败：{type(e).__name__}: {e}")
            return
        self.conf_lbl.setText(f"{d['badge']} · {d['hint']}")
        self.conf_lbl.setStyleSheet(
            f"color:{d['color']};font-size:14px;font-weight:bold;")
        self.conf_bar.setValue(int(d["score"]))
        lines = ["七因子贡献："]
        lines += [f"· {f['name']}：{f['contribution']:.1f} 分"
                  f"（{f['normalized'] * 100:.0f}%）" for f in d["factors"]]
        if d["caveats"]:
            lines.append("")
            lines.append("限制条件：")
            lines += [f"· {c}" for c in d["caveats"]]
        self.caveats.setPlainText("\n".join(lines))

    def _run_redteam(self) -> None:
        try:
            from security.adversarial_compliance import (run_red_team,
                                                         safe_defender,
                                                         guardrail_scorecard)
            rep = run_red_team(safe_defender, rounds=1)
            rows = guardrail_scorecard(rep)
        except Exception as e:  # noqa: BLE001
            log.warning("红队运行失败：%s", e)
            self.conf_lbl.setText(f"红队运行失败：{type(e).__name__}: {e}")
            return
        self.red_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [r["name"], str(r["total"]), str(r["breach"]),
                    ("—" if r["defense_rate"] is None
                     else f"{r['defense_rate'] * 100:.0f}%"),
                    r["status"]]
            for j, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if j == 2 and r["breach"]:
                    item.setForeground(QColor(WARN))
                self.red_table.setItem(i, j, item)
        self.red_table.resizeColumnsToContents()


def _box_style() -> str:
    return (f"QLineEdit,QPlainTextEdit,QTextEdit,QComboBox,QSpinBox,QSlider"
            f"{{background:{BG_CARD};border:1px solid {BORDER};"
            f"border-radius:6px;color:{TEXT_MAIN};padding:4px;}}")


def _btn(primary: bool = False) -> str:
    if primary:
        return (f"QPushButton{{background:{ACCENT};color:#0A0C10;"
                f"border:none;border-radius:6px;padding:6px 14px;font-weight:bold;}}"
                f"QPushButton:hover{{background:{ACCENT}CC;}}")
    return (f"QPushButton{{background:transparent;color:{ACCENT};"
            f"border:1px solid {ACCENT};border-radius:6px;padding:6px 12px;}}"
            f"QPushButton:hover{{background:{ACCENT}22;}}")
