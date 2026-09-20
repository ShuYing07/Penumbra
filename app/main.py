# -*- coding: utf-8 -*-
"""StockAIPredictor 桌面入口（PyQt6）。

运行：venv\\Scripts\\python.exe -m app.main
打包自检：StockAIPredictor.exe --selftest（offscreen 构建窗口 + mock 跑通全管线，
结果写 data/selftest.log，退出码 0=通过）
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _fix_akshare_data() -> None:
    """确保PyInstaller打包后akshare的calendar.json在正确位置。"""
    try:
        import akshare
        ak_dir = Path(akshare.__file__).parent
        fold = ak_dir / "file_fold"
        cal = fold / "calendar.json"
        if cal.exists():
            return
        fold.mkdir(parents=True, exist_ok=True)
        candidates = []
        if hasattr(sys, '_MEIPASS'):
            candidates.append(Path(sys._MEIPASS) / "akshare" / "file_fold" / "calendar.json")
        exe_dir = Path(sys.executable).parent
        candidates.append(exe_dir / "_internal" / "akshare" / "file_fold" / "calendar.json")
        for src in candidates:
            if src and src.exists():
                import shutil
                shutil.copy2(src, cal)
                break
    except Exception:
        pass

_fix_akshare_data()


def _selftest() -> int:
    """打包冒烟：不依赖控制台（windowed 下 print 安全 no-op），结果落 data/selftest.log。"""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ.setdefault("STOCKAI_MOCK", "1")
    import socket

    socket.setdefaulttimeout(30)  # 兜底：akshare 部分请求无超时
    lines: list[str] = []

    def log(msg: str) -> None:
        lines.append(msg)
        print(msg, flush=True)

    try:
        from PyQt6.QtWidgets import QApplication

        from core.config import DATA_DIR, setup_logging

        setup_logging()
        from app.ui.main_window import MainWindow

        app = QApplication([])
        win = MainWindow()
        win.show()
        log(f"PASS 窗口构建（{win.centralWidget().count()} 标签）")

        done: dict = {}
        win.analysis_tab.analysis_finished.connect(lambda r: done.update(r))
        win.analysis_tab.input.setText("SH600519")
        win.analysis_tab.mock_box.setChecked(True)
        win.analysis_tab._start()
        deadline = time.time() + 300
        while time.time() < deadline and "state" not in done:
            app.processEvents()
            time.sleep(0.05)
        assert "state" in done, "mock 分析超时未完成"
        final = done["state"]["final"]
        log(f"PASS 全管线：{final.get('action')} 仓位{final.get('position_pct')}%")

        assert win.history_tab.table.rowCount() >= 1, "决策记录为空"
        log("PASS 决策记录联动")
        # K线在分析完成信号里触发后台加载，给事件循环留时间
        kdeadline = time.time() + 120
        while time.time() < kdeadline and win.chart_tab._bars is None:
            app.processEvents()
            time.sleep(0.05)
        assert win.chart_tab._bars is not None, "K线未联动"
        log("PASS K线联动")

        # watchlist 冒烟：建表 + 加一只无效标的 + scan_all 错误隔离不抛
        from core.watchlist import init as _wl_init, store as _wl_store, engine as _wl_eng
        _wl_init()
        _wl_store.remove("TESTWATCH")
        _wl_store.add("TESTWATCH", "UNKNOWN", "RSI大于70")
        _rows = _wl_eng.scan_all()
        assert len(_rows) >= 1, "watchlist scan 未返回行"
        log(f"PASS watchlist 错误隔离（{len(_rows)} 行不抛）")
        _wl_store.remove("TESTWATCH")

        # 信号回放冒烟：mock 历史回放 2 点 + 评估，且不污染真实 decisions
        from core.data.cache import get_conn
        from core.data import service as _svc
        from core.llm import LLMRunner as _Runner
        from core.replay import engine as _rp_eng, store as _rp_store
        _rp_store.init()
        _bars, _ = _svc.get_daily("SH600519")
        _pts = _rp_eng.pick_dates(_bars, step_bars=120)[:2]
        assert len(_pts) == 2, f"回放选点不足: {_pts}"
        with get_conn() as _conn:
            _before = _conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        _bid = "SELFTEST"   # 固定批次：重复跑幂等覆盖，不膨胀
        _rr = _Runner(mock=True)
        for _d in _pts:
            _f = _rp_eng.run_one("SH600519", _d, _rr)
            _rp_store.save_signal(_bid, "SH600519", "CN", "mock(规则桩)", _d, _f)
        _n = _rp_eng.evaluate_batch(_bid, _bars)
        assert _n == 2, f"回放评估数异常: {_n}"
        with get_conn() as _conn:
            _after = _conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        assert _before == _after, "回放污染了 decisions 表"
        log(f"PASS 信号回放（{len(_pts)}点评估{_n}，decisions不污染）")

        # 参数寻优冒烟：1 组合网格（IS/OOS 各一次回测），校验结论结构
        from core.optimize import grid as _opt_grid
        from core.quant.backtest import BacktestConfig as _BC
        _spec = {"fast": [5], "slow": [20]}
        _o = _opt_grid.optimize(_bars, "CN", "ma_cross", _spec,
                                _BC(ticker="SH600519", market="CN"),
                                objective="sharpe", split=0.6)
        assert _o["n_combos"] == 1 and _o["best"]["params"] == {"fast": 5, "slow": 20}
        assert "rating" in _o["plateau"] and 0 <= _o["walk_forward"]["oos_percentile"] <= 1
        log("PASS 参数寻优（网格+平原+walk-forward 结构完整）")

        (DATA_DIR / "selftest.log").write_text("\n".join(lines), encoding="utf-8")
        return 0
    except Exception as e:  # noqa: BLE001
        log(f"FAIL {type(e).__name__}: {e}")
        try:
            from core.config import DATA_DIR

            (DATA_DIR / "selftest.log").write_text("\n".join(lines), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return 1


def _nettest() -> int:
    """网络自检：逐源直连测试，打印耗时与结果（排障用）。"""
    import socket
    import time

    socket.setdefaulttimeout(20)
    from core.config import setup_logging

    setup_logging()
    results: list[str] = []

    def run(name, fn):
        t0 = time.time()
        try:
            r = fn()
            line = f"OK   {name}: {r}（{time.time() - t0:.1f}s）"
        except Exception as e:  # noqa: BLE001
            line = f"FAIL {name}: {type(e).__name__}: {e}（{time.time() - t0:.1f}s）"
        print(line, flush=True)
        results.append(line)

    import requests

    run("新浪日线HTTP", lambda: requests.get("https://finance.sina.com.cn", timeout=15).status_code)
    run("百度HTTP", lambda: requests.get("https://www.baidu.com", timeout=15).status_code)
    from core.data.akshare_source import fetch_daily_cn

    run("akshare新浪日线", lambda: f"{len(fetch_daily_cn('SH600519'))}行")

    from core.config import DATA_DIR

    (DATA_DIR / "nettest.log").write_text("\n".join(results), encoding="utf-8")
    return 0 if all(r.startswith("OK") for r in results) else 1


def _localping() -> int:
    """本地引擎自检：Ollama 安装/服务/模型 + 一次真实本地推理（结果落 data/localping.log）。"""
    import time

    from core.config import DATA_DIR, LOCAL_MODEL, setup_logging

    setup_logging()
    lines: list[str] = []

    def log(msg: str) -> None:
        lines.append(msg)
        print(msg, flush=True)

    try:
        from core import llm_local
        from core.llm import LLMRunner

        log(f"Ollama 已安装：{llm_local.find_executable()}")
        if not llm_local.ensure_started():
            log("FAIL Ollama 服务未运行且无法拉起（请从开始菜单启动 Ollama）")
            raise RuntimeError("ollama service down")
        log(f"Ollama 服务：{llm_local.version()}")
        models = llm_local.list_models()
        log(f"已装模型：{models}")
        if not (llm_local.has_model(LOCAL_MODEL) or models):
            log(f"FAIL 未找到本地模型 {LOCAL_MODEL}，请先在界面『本地模型…』中下载")
            raise RuntimeError("no model")
        model = LOCAL_MODEL if llm_local.has_model(LOCAL_MODEL) else models[0]
        log(f"使用模型：{model}，发起一次真实推理…")
        runner = LLMRunner(backend="local", local_model=model)
        t0 = time.time()
        data = runner.chat_json(
            "technical", "你是技术分析师，只输出JSON。",
            "事实：收盘10元，MA20=10.1，MACD金叉。输出 {stance,confidence,view,key_points,risks}")
        dt = time.time() - t0
        log(f"PASS 本地推理 {dt:.1f}s：{str(data)[:200]}")
        log(f"usage：{runner.usage()}")
        (DATA_DIR / "localping.log").write_text("\n".join(lines), encoding="utf-8")
        return 0
    except Exception as e:  # noqa: BLE001
        log(f"FAIL {type(e).__name__}: {e}")
        try:
            (DATA_DIR / "localping.log").write_text("\n".join(lines), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return 1


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()
    if "--nettest" in sys.argv:
        return _nettest()
    if "--localping" in sys.argv:
        return _localping()

    import socket

    socket.setdefaulttimeout(30)  # 兜底：akshare 部分请求无超时，冻结环境曾因此挂死
    from core.config import setup_logging

    setup_logging()
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    app.setApplicationName("StockAIPredictor")
    # 应用级图标：任务栏/所有窗口统一 logo
    import os as _os
    from PyQt6.QtGui import QIcon as _QIcon

    def _find_ico() -> str:
        candidates = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(_os.path.join(meipass, "assets", "app.ico"))
        proj_root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        candidates.append(_os.path.join(proj_root, "assets", "app.ico"))
        for c in candidates:
            if _os.path.exists(c):
                return c
        return ""

    _ico = _find_ico()
    if _ico:
        app.setWindowIcon(_QIcon(_ico))
    try:
        from app.ui.theme import apply_dark_theme
        apply_dark_theme(app)
    except Exception:
        pass

    from app.ui.main_window import MainWindow

    _show_disclaimer_if_first()
    _show_api_key_if_first()
    win = MainWindow()
    win.show()
    _show_welcome_if_first()
    return app.exec()


def _show_welcome_if_first() -> None:
    """首次启动显示 3 页新手引导；看完后不再弹。"""
    from PyQt6.QtCore import QSettings, Qt
    from PyQt6.QtWidgets import (QDialog, QLabel, QPushButton, QStackedWidget,
                                 QVBoxLayout)

    settings = QSettings("StockAI", "StockAIPredictor")
    if settings.value("welcome_shown", False, type=bool):
        return

    pages = [
        "👋 欢迎使用 疏影 · 知微\n\n它可以帮你快速了解一只股票的"
        "行情、技术指标与近期新闻（纯数据展示，不替你做决定）。",
        "📊 怎么用？\n\n在中间输入框输入股票代码（如 600519 / AAPL），回车，"
        "右侧会自动画出它的K线，中间用大白话客观描述技术指标。",
        "⚠️ 请注意\n\n所有分析仅供研究学习，不构成投资建议，也不提供买卖时机。"
        "投资有风险，决策请自行判断。",
    ]
    dlg = QDialog()
    dlg.setWindowTitle("新手引导")
    lay = QVBoxLayout(dlg)
    stack = QStackedWidget()
    for p in pages:
        lab = QLabel(p)
        lab.setWordWrap(True)
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stack.addWidget(lab)
    lay.addWidget(stack)
    btn = QPushButton("下一步")

    def advance() -> None:
        i = stack.currentIndex()
        if i < stack.count() - 1:
            stack.setCurrentIndex(i + 1)
            btn.setText("开始使用" if i == stack.count() - 2 else "下一步")
        else:
            settings.setValue("welcome_shown", True)
            dlg.accept()

    btn.clicked.connect(advance)
    lay.addWidget(btn)
    dlg.exec()


def _show_disclaimer_if_first() -> None:
    """首次启动弹出免责声明确认；用户点'我已阅读并理解'后不再弹。"""
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QMessageBox

    settings = QSettings("StockAI", "StockAIPredictor")
    if settings.value("disclaimer_accepted", False, type=bool):
        return
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("免责声明")
    box.setText("疏影 · 知微 免责声明")
    box.setInformativeText(
        "本工具仅用于数据分析和研究学习，不构成任何投资建议。\n\n"
        "本工具不提供证券投资咨询业务，未取得中国证监会证券投资咨询业务资格，"
        "不提供任何具体证券品种的分析意见、买卖建议或价格走势预测。\n\n"
        "所有输出均为客观历史数据展示与统计，不保证数据准确性与完整性。"
        "用户应自行判断并承担投资决策的全部风险，开发者不对任何投资损失承担责任。\n\n"
        "点击「我已阅读并理解」表示你已充分知晓上述风险。"
    )
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.button(QMessageBox.StandardButton.Yes).setText("我已阅读并理解")
    box.button(QMessageBox.StandardButton.No).setText("退出")
    if box.exec() == QMessageBox.StandardButton.Yes:
        settings.setValue("disclaimer_accepted", True)
    else:
        raise SystemExit(0)


def _show_api_key_if_first() -> None:
    """首次启动引导：可选配置云端API，也可跳过直接用本地模型。
    一旦用户做过选择（保存Key或跳过），后续不再弹窗。"""
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import (QDialog, QLabel, QLineEdit, QPushButton,
                                 QVBoxLayout, QHBoxLayout)
    from config_manager import ensure_configured, save_deepseek_key

    settings = QSettings("StockAI", "StockAIPredictor")
    # 用户已做过选择（保存过Key或主动跳过），不再弹窗
    if settings.value("api_choice_done", False, type=bool):
        return
    ok, _ = ensure_configured()
    if ok:
        # .env里已有Key，说明用户之前配过，标记为已完成
        settings.setValue("api_choice_done", True)
        return

    dlg = QDialog()
    dlg.setWindowTitle("欢迎使用 疏影·知微")
    dlg.setMinimumWidth(560)
    lay = QVBoxLayout(dlg)
    lay.addWidget(QLabel(
        "欢迎使用！\n\n"
        "你有两种方式开始：\n\n"
        "【方式一：云端API】（推荐，质量最高）\n"
        "粘贴任意OpenAI兼容接口的Key（DeepSeek/通义千问/智谱/硅基流动等），\n"
        "去对应平台申请免费额度即可。Key只存你本机，不上传。\n\n"
        "【方式二：本地模型】（完全离线、零成本）\n"
        "如果你已安装Ollama，可直接跳过此步，用本地模型分析。\n\n"
        "（之后可在 帮助→API设置 中随时修改）"
    ))
    inp = QLineEdit()
    inp.setPlaceholderText("粘贴你的 API Key（sk-...），或留空跳过")
    lay.addWidget(inp)

    row = QHBoxLayout()
    btn_save = QPushButton("保存并开始")
    btn_save.setStyleSheet("background-color:#2F81F7; color:white; padding:6px 16px;")
    row.addWidget(btn_save)
    btn_skip = QPushButton("跳过，先用本地模型")
    btn_skip.setStyleSheet("padding:6px 16px;")
    row.addWidget(btn_skip)
    lay.addLayout(row)

    def _save() -> None:
        k = inp.text().strip()
        if k:
            save_deepseek_key(k)
        settings.setValue("api_choice_done", True)
        dlg.accept()

    def _skip() -> None:
        settings.setValue("api_choice_done", True)
        dlg.accept()

    btn_save.clicked.connect(_save)
    btn_skip.clicked.connect(_skip)
    inp.returnPressed.connect(_save)
    dlg.exec()


if __name__ == "__main__":
    raise SystemExit(main())

