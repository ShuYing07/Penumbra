# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import os, glob

# 只打包 data 里的静态索引 json（all_stocks.json / a_stocks.json）。
# 严禁打包 data/*.db —— 它们是运行时生成的个人数据
# （自选股/分析历史/模拟盘持仓/向量记忆/账号），随安装包分发会泄漏隐私。
datas = [('assets', 'assets')]
for jf in glob.glob('data/*.json'):
    datas.append((jf, 'data'))
# Web 混合模式静态页（FastAPI 需在打包后也能找到）
datas.append(('web_ui/static', 'web_ui/static'))

binaries = []
hiddenimports = []
tmp_ret = collect_all('akshare')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('py_mini_racer')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# 企业深化八模块：显式收集，确保打包后全部可用（Web/REST 需 fastapi/uvicorn）
hiddenimports += [
    'agent_mesh.agent_registry', 'agent_mesh.agent_identity',
    'agent_mesh.policy_engine', 'agent_mesh.observability',
    'security.zero_trust', 'security.audit_ledger',
    'memory.vector_memory', 'memory.graph_memory', 'memory.hybrid_memory',
    'reasoning.hybrid_reasoner',
    'data_mesh.domain_registry', 'data_mesh.data_catalog',
    'data_mesh.data_contract',
    'streaming.event_bus', 'streaming.data_ingestion',
    'streaming.stream_processor',
    'compliance.gdpr', 'compliance.ccpa',
    'web_ui.app', 'web_ui.__init__',
    'api.main',
    # 前沿架构八模块（HERMES / Swarm / 湖仓 / 微前端 / SAFE / 合规监控 / 数据适配器）
    'hermes.hierarchical_agents', 'hermes.dynamic_kg', 'hermes.adversarial_validator',
    'valuation_swarm.swarm_agents', 'valuation_swarm.debate_alignment',
    'data_pipeline.lakehouse', 'data_pipeline.stream_processor',
    'data_pipeline.sidecar_gateway',
    'micro_frontend.shell', 'micro_frontend.security_layer',
    'micro_frontend.modules.kline_module', 'micro_frontend.modules.debate_module',
    'micro_frontend.modules.backtest_module', 'micro_frontend.modules.portfolio_module',
    'sovereign_agent.private_deployment', 'sovereign_agent.model_registry',
    'sovereign_agent.cost_tracker',
    'compliance.rule_engine', 'compliance.continuous_monitor',
    'data_adapters.base_adapter', 'data_adapters.registry',
    'data_adapters.akshare_adapter', 'data_adapters.yfinance_adapter',
    'data_adapters.bloomberg_adapter', 'data_adapters.lseg_adapter',
    'data_adapters.wind_adapter',
    'app.ui.valuation_tab', 'app.ui.compliance_monitor_tab',
]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='疏影知微',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX 压缩会破坏 py_mini_racer(V8) DLL，导致 selftest 崩溃；禁用以保证稳定
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    # V8( py_mini_racer/mini_racer.dll ) 被 UPX 压缩后初始化崩溃
    # (IsConfigurablePoolInitialized 失败)，必须排除 UPX。
    upx_exclude=['mini_racer', '*mini_racer*'],
    name='疏影知微',
)
