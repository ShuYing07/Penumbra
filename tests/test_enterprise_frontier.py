# -*- coding: utf-8 -*-
"""前沿架构八模块（HERMES / Swarm / 湖仓 / 微前端 / SAFE / 合规监控 / 数据适配器）回归测试。

以函数形式提供断言；本文件可独立运行（python tests/test_enterprise_frontier.py）。
全部为离线/降级路径，不依赖外部网络与 API Key。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _demo_bars(n: int = 60, base: float = 100.0) -> list[dict]:
    import math
    return [{"open": base + i, "high": base + i + 1, "low": base + i - 1,
             "close": base + i + math.sin(i / 5), "volume": 1000 + i * 10}
            for i in range(n)]


def test_hermes_hierarchical() -> bool:
    from hermes.hierarchical_agents import run_analysis
    h = run_analysis("SH600519", {
        "bars": lambda t: _demo_bars(),
        "news": lambda t: [{"title": "公司发布第三季度财报 营收增长符合预期"}],
    })
    assert not h["gated"] and "HERMES" in h["report"]
    assert h["consensus"]["consensus"] > 0
    # 数据不足 → 拒绝结论（合规门控）
    h2 = run_analysis("SH600519", {"bars": lambda t: [], "news": lambda t: []})
    assert h2["gated"] and "数据不足" in h2["report"]
    return True


def test_dynamic_kg() -> bool:
    from hermes.dynamic_kg import DynamicKG, financial_ner
    kg = DynamicKG()
    kg.add_entity("SH600519", "stock", {"name": "贵州茅台"})
    kg.add_entity("IND:白酒", "industry")
    kg.add_relation("SH600519", "IND:白酒", "belongs_to", weight=1.0)
    rels = kg.query_entity_relations("SH600519", depth=1)
    assert any(n["entity"] == "IND:白酒" for n in rels["nodes"])
    assert financial_ner("贵州茅台发布财报")
    return True


def test_valuation_swarm() -> bool:
    from valuation_swarm.swarm_agents import SwarmEstimator, TASKS
    facts = {"close": 100.0, "eps": 5.0, "growth_pct": 8.0, "discount_rate": 0.10,
             "pe_ttm": 20.0, "peer_pe": 22.0, "momentum": 0.12, "sentiment": 0.3}
    sw = SwarmEstimator()
    out = sw.estimate("SH600519", facts)
    assert set(out["task_results"]) == set(TASKS)
    for t in TASKS:
        assert len(out["task_results"][t]["agents"]) == 3
    return True


def test_debate_alignment() -> bool:
    from valuation_swarm.swarm_agents import SwarmEstimator
    from valuation_swarm.debate_alignment import DebateAlignment
    facts = {"close": 100.0, "eps": 5.0, "growth_pct": 8.0, "discount_rate": 0.10,
             "pe_ttm": 20.0, "peer_pe": 22.0, "momentum": 0.12, "sentiment": 0.3}
    sw = SwarmEstimator()
    da = DebateAlignment()
    out = sw.run_with_alignment("SH600519", facts, alignment=da)
    assert out["converged"]["value"] is not None
    assert out["converged"]["rounds"] >= 1
    assert "LLM Swarm 估值" in out["report"]
    return True


def test_lakehouse() -> bool:
    from data_pipeline.lakehouse import Lakehouse
    lh = Lakehouse()
    v1 = lh.put("market_data", {"close": 100.0})
    v2 = lh.put("market_data", {"close": 110.0})
    assert v2 == v1 + 1
    assert lh.read_latest("market_data").payload[0]["close"] == 110.0
    assert lh.read_version("market_data", v1).payload[0]["close"] == 100.0
    assert len(lh.list_snapshots("market_data")) >= 2
    lh.close()
    return True


def test_stream_processor() -> bool:
    from data_pipeline.stream_processor import StreamProcessor, window_mean
    sp = StreamProcessor(window_size=5)
    for v in (100, 101, 100, 102, 2000):  # 2000 相对窗口均值 280.4 偏差 6.1σ → 告警
        r = sp.process("SH600519", {"close": v, "volume": v})
        assert r["alert"] in (True, False)
    assert sp.stats()["alerts"] >= 1
    assert window_mean([1, 2, 3], 3)[-1] == 2.0
    return True


def test_sidecar_gateway() -> bool:
    from data_pipeline.sidecar_gateway import SidecarGateway, TickMessage
    g = SidecarGateway()
    t = TickMessage(ticker="SH600519", px=1500.0, ts=1.0)
    g.push(t)
    got = g.drain()
    assert got and got[0].ticker == "SH600519" and got[0].px == 1500.0
    assert TickMessage.from_json(got[0].to_json()).px == 1500.0
    return True


def test_micro_frontend() -> bool:
    from micro_frontend.shell import MicroFrontendShell
    from micro_frontend.modules import list_modules, get_module
    assert set(list_modules()) == {"kline", "debate", "backtest", "portfolio"}
    shell = MicroFrontendShell()
    for name in list_modules():
        shell.register(get_module(name))
    assert shell.mount_all() == 4
    assert shell.ping("kline") is True
    assert len(shell.list_modules()) == 4
    return True


def test_security_layer() -> bool:
    from micro_frontend.security_layer import SecurityLayer
    sl = SecurityLayer("analyst")
    assert sl.authorize("analyze", hour=10)
    assert not sl.authorize("manage", hour=23)      # 时段拒绝
    assert SecurityLayer("viewer").authorize("backtest", hour=10) is False
    return True


def test_private_deployment() -> bool:
    from sovereign_agent.private_deployment import PrivateDeployment, DeploymentMode
    d = PrivateDeployment(DeploymentMode.LOCAL)
    assert not d.allow_egress({"portfolio": {}})
    d.set_mode(DeploymentMode.HYBRID)
    assert d.allow_egress({"query": "分析"})
    d.set_mode(DeploymentMode.LOCAL)
    r = d.run_agent("analyst", None, {"external_llm": True})
    assert not r["ok"] and "local" in r["reason"]
    return True


def test_model_registry() -> bool:
    from sovereign_agent.model_registry import ModelRegistry
    reg = ModelRegistry()
    reg.register_openai_compatible("deepseek", "https://api.deepseek.com/v1",
                                   "deepseek-chat")
    assert reg.resolve("deepseek") is None       # openai 无 key → None
    reg.register_local("qwen", "models/__no_such_model_dir__")
    assert reg.resolve("qwen") is None           # 目录不存在 → None
    reg.register_ollama("qwen-ollama", "qwen3:7b")
    assert reg.resolve("qwen-ollama") is not None
    return True


def test_cost_tracker() -> bool:
    from sovereign_agent.cost_tracker import CostTracker
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)                        # 立即释放句柄，避免 Windows 文件锁
    ct = CostTracker(db_path=tmp, annual_commitment=1000.0)
    ct.track("deepseek-chat", 100_000, 50_000)
    assert ct.budget_check(monthly_budget=0.1)["over"] is True
    assert ct.commitment_check()["remaining"] > 900
    ct.close()
    os.unlink(tmp)
    return True


def test_rule_engine() -> bool:
    from compliance.rule_engine import RuleEngine
    eng = RuleEngine()
    assert eng.is_blocked(eng.check({"text": "必涨稳赚", "position": 0.5}))
    assert not eng.is_blocked(eng.check({"text": "历史回测示例"}))
    return True


def test_continuous_monitor() -> bool:
    from compliance.continuous_monitor import ContinuousMonitor
    m = ContinuousMonitor()
    r = m.monitor("必涨", ticker="SH600519")
    assert r["blocked"] is True and r["sanitized"].startswith("[已触发合规拦截")
    assert m.pending_reviews()
    return True


def test_data_adapters() -> bool:
    from data_adapters.registry import register_builtin_adapters, get_registry
    register_builtin_adapters()
    reg = get_registry()
    assert reg.active() is not None
    assert len(reg.list()) >= 2
    from data_adapters.bloomberg_adapter import BloombergAdapter
    hb = BloombergAdapter().health_check()
    assert hb["degraded"] is True            # 未配置 → degraded 而非崩溃
    from data_adapters.wind_adapter import WindAdapter
    hw = WindAdapter().health_check()
    assert "degraded" in hw                  # WindPy 未装 → degraded
    return True


def test_config_example_clean() -> bool:
    with open("config.yaml.example", encoding="utf-8") as f:
        lines = f.read().splitlines()
    top = [ln.split(":", 1)[0].strip() for ln in lines
           if ln and not ln.startswith((" ", "#")) and ":" in ln]
    dup = {k for k in top if top.count(k) > 1}
    assert not dup, f"config.yaml.example 顶层重复键: {dup}"
    return True


def run_all() -> dict:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    results = {}
    for fn in tests:
        try:
            results[fn.__name__] = bool(fn())
        except Exception as e:  # noqa: BLE001
            results[fn.__name__] = f"{type(e).__name__}: {e}"
    return results


if __name__ == "__main__":
    res = run_all()
    for name, ok in res.items():
        print(f"{'PASS' if ok is True else 'FAIL'}  {name}  {'' if ok is True else ok}")
    failed = {k: v for k, v in res.items() if v is not True}
    print(f"\n汇总：通过 {len(res) - len(failed)}/{len(res)}，失败 {len(failed)}")
    if failed:
        raise SystemExit(1)
