# -*- coding: utf-8 -*-
"""错误处理与降级工具（模块二）。

设计原则（调研自开源桌面应用惯例，如 qutebrowser / LibreOffice 的降级策略）：
1. 网络失败**永不阻塞**主线程与主界面：日志记录 + 状态栏/横幅提示 + 自动降级；
2. 降级链：网络 → 本地缓存 → 示例数据（贵州茅台 600519），保证新用户首屏可用；
3. 所有提示均非模态，5 秒自动消失，用户可随时手动"重试"。
"""
from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger("stockai.error")

# 降级兜底示例标的（无缓存、无网络时仍能展示完整界面与 K 线）
SAMPLE_TICKER = "SH600519"
SAMPLE_NAME = "贵州茅台"
_BANNER_MS = 5000  # 横幅默认展示时长


def handle_network_error(exception: Exception, context: str = "") -> dict:
    """记录网络异常日志，并返回结构化降级方案。

    返回: {"fallback": "cache"|"sample"|"none", "message": str, "detail": str}
    """
    detail = f"{type(exception).__name__}: {exception}"
    log.warning("网络错误%s: %s", f"（{context}）" if context else "", detail)
    return {
        "fallback": "cache",
        "message": "网络连接失败，已切换到缓存数据",
        "detail": detail,
    }


def show_non_blocking_error(parent, message: str, duration_ms: int = _BANNER_MS) -> None:
    """界面顶部红色横幅，duration_ms 后自动淡出消失（不阻塞，不抢焦点）。

    - parent 须为 QMainWindow / QWidget；
    - 横幅悬浮于窗口顶部居中，鼠标穿透（不挡交互）；
    - 连续调用时旧横幅先移除，避免堆叠。
    """
    if parent is None:
        log.warning("非阻塞横幅：parent 为空，跳过（%s）", message)
        return
    try:
        from PyQt6.QtCore import QTimer, Qt, QPropertyAnimation, QEasingCurve
        from PyQt6.QtGui import QColor
        from PyQt6.QtWidgets import QLabel

        # 移除上一次的横幅
        old = getattr(parent, "_nbe_banner", None)
        if old is not None:
            try:
                old.hide()
                old.deleteLater()
            except Exception:  # noqa: BLE001
                pass
        banner = QLabel(message, parent)
        banner.setStyleSheet(
            "background-color:rgba(211,47,47,0.92); color:#FFFFFF;"
            "border-radius:6px; padding:8px 18px; font-size:13px; font-weight:bold;")
        banner.setWordWrap(True)
        banner.adjustSize()
        w = min(banner.width(), parent.width() - 60)
        banner.setFixedWidth(max(w, 200))
        banner.adjustSize()
        banner.move((parent.width() - banner.width()) // 2, 10)
        banner.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        banner.raise_()
        banner.show()
        parent._nbe_banner = banner  # 保留引用防 GC

        def _fade() -> None:
            try:
                anim = QPropertyAnimation(banner, b"windowOpacity", parent)
                anim.setDuration(400)
                anim.setStartValue(1.0)
                anim.setEndValue(0.0)
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                anim.finished.connect(banner.deleteLater)
                anim.start()
            except Exception:  # noqa: BLE001
                banner.deleteLater()

        QTimer.singleShot(max(duration_ms, 500), _fade)
    except Exception as e:  # noqa: BLE001
        log.warning("非阻塞横幅创建失败：%s", e)


def check_network_and_fallback(ticker: str = SAMPLE_TICKER) -> dict:
    """网络探测 + 自动降级（无 UI 依赖，可在后台线程调用）。

    返回: {"ok": bool, "source": "network"|"cache"|"sample", "message": str, "detail": str}
    - ok=True   网络可用，已拿到真实行情；
    - ok=False  网络失败，按 缓存 → 示例数据 降级。
    """
    from core.data import cache, service

    try:
        df, status = service.get_daily(ticker, use_cache=False)
        if len(df) >= 60:
            source = "network" if str(status).startswith("network") else "cache"
            return {"ok": True, "source": source,
                    "message": "数据源正常", "detail": f"{ticker} 日线 {len(df)} 行 ({status})"}
    except Exception as e:  # noqa: BLE001
        r = handle_network_error(e, f"probe {ticker}")

    cached = cache.load_bars(ticker)
    if len(cached) >= 60:
        return {"ok": False, "source": "cache",
                "message": "网络连接失败，已切换到缓存数据",
                "detail": f"缓存 {len(cached)} 行（{cached.index.min().date()}~{cached.index.max().date()}）"}
    return {"ok": False, "source": "sample",
            "message": f"网络连接失败，已加载示例数据（{SAMPLE_NAME} {SAMPLE_TICKER}）",
            "detail": "无本地缓存，使用内置示例数据"}


def network_status_bar(parent, result: dict, retry: Callable[[], None] | None = None) -> None:
    """把降级方案渲染为状态栏红色提示 + 可选『重试』按钮（非模态）。

    - parent 须为 QMainWindow（有 statusBar）；
    - retry 为回调（如重新探测/刷新市场概览）；点击按钮后自动隐藏。
    """
    if parent is None or parent.statusBar() is None:
        return
    try:
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QLabel, QPushButton

        sb = parent.statusBar()
        # 清除旧状态
        for w in getattr(parent, "_net_widgets", []):
            try:
                sb.removeWidget(w)
                w.deleteLater()
            except Exception:  # noqa: BLE001
                pass
        widgets: list = []
        lab = QLabel("⚠️ " + result.get("message", "网络异常"))
        lab.setStyleSheet("color:#FF5252; font-weight:bold; padding:0 8px;")
        widgets.append(lab)
        sb.addWidget(lab)
        if retry is not None:
            btn = QPushButton("重试")
            btn.setStyleSheet("padding:2px 12px; border-radius:4px;"
                              "border:1px solid #FF5252; color:#FF5252; background:transparent;")

            def _retry() -> None:
                for w in getattr(parent, "_net_widgets", []):
                    try:
                        sb.removeWidget(w)
                        w.deleteLater()
                    except Exception:  # noqa: BLE001
                        pass
                parent._net_widgets = []
                try:
                    retry()
                except Exception as e:  # noqa: BLE001
                    handle_network_error(e, "retry")

            btn.clicked.connect(_retry)
            widgets.append(btn)
            sb.addWidget(btn)
        parent._net_widgets = widgets
        # 点击处常驻，直到重试成功或用户操作；无需自动消失
    except Exception as e:  # noqa: BLE001
        log.warning("状态栏降级提示失败：%s", e)
