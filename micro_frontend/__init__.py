# -*- coding: utf-8 -*-
"""微前端架构：Shell 容器 + 独立功能模块 + 统一安全合规层。

参考微前端安全金融架构：每个功能模块（K线/辩论/回测/组合）独立实现统一接口，
由 Shell 协调加载、生命周期与事件；SecurityLayer 统一认证/授权/审计。

与现有 PyQt 主窗口的关系：本模块提供"架构级"接口契约与轻量 Shell，
PyQt 各 tab 可作为模块适配接入（通过 adapter 包装），不改变现有功能。
"""
from micro_frontend.shell import MicroFrontendShell, ModuleContext, EventBus
from micro_frontend.security_layer import SecurityLayer
from micro_frontend.modules import (
    KLineModule, DebateModule, BacktestModule, PortfolioModule,
    list_modules, get_module,
)

__all__ = [
    "MicroFrontendShell", "ModuleContext", "EventBus",
    "SecurityLayer",
    "KLineModule", "DebateModule", "BacktestModule", "PortfolioModule",
    "list_modules", "get_module",
]
