# -*- coding: utf-8 -*-
"""微前端功能模块集：K线 / 多空辩论 / 回测 / 组合管理。

每个模块实现统一接口：
  - name: str
  - mount(ctx: ModuleContext, container=None) -> object  # 挂载返回句柄
  - unmount() -> None
  - ping() -> bool

PyQt 主窗口可作为容器接入（container 传入 QWidget/QVBoxLayout）。
"""
from micro_frontend.modules.kline_module import KLineModule
from micro_frontend.modules.debate_module import DebateModule
from micro_frontend.modules.backtest_module import BacktestModule
from micro_frontend.modules.portfolio_module import PortfolioModule

_MODULES = (KLineModule, DebateModule, BacktestModule, PortfolioModule)
_INSTANCES = {m().name: m for m in _MODULES}


def list_modules() -> list[str]:
    return list(_INSTANCES.keys())


def get_module(name: str):
    cls = _INSTANCES.get(name)
    return cls() if cls else None


__all__ = [
    "KLineModule", "DebateModule", "BacktestModule", "PortfolioModule",
    "list_modules", "get_module",
]
