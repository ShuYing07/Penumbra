# -*- coding: utf-8 -*-
"""企业深化八模块 单元测试（标准库实现，无未装依赖）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RESULTS = []


def check(name, fn):
    try:
        fn()
        RESULTS.append((name, True, ""))
        print(f"PASS {name}")
    except Exception as e:  # noqa: BLE001
        RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        print(f"FAIL {name}: {type(e).__name__}: {e}")


# ---------------------------------------------------------------- 模块一

def _agent_mesh():
    from agent_mesh import agent_registry, agent_identity, policy_engine, observability
    a = agent_registry.register_agent("tech_agent", "1.0", ["analysis", "chart"])
    assert agent_registry.get_agent(a["agent_id"])["name"] == "tech_agent"
    assert any(x["agent_id"] == a["agent_id"] for x in agent_registry.discover("analysis"))
    tok = agent_identity.issue_identity(a["agent_id"], "tech_agent")
    claim = agent_identity.verify_identity(tok)
    assert claim["sub"] == a["agent_id"]
    try:
        agent_identity.verify_identity(tok + "x")
        raise AssertionError("伪造身份未被拦截")
    except PermissionError:
        pass
    policy_engine.allow("tech_agent", "read", "bars")
    policy_engine.enforce("tech_agent", "read", "bars")
    try:
        policy_engine.enforce("tech_agent", "delete", "bars")
        raise AssertionError("未授权动作未被策略拦截")
    except PermissionError:
        pass
    observability.log_comm("a", "b", "query", 12.5)
    assert len(observability.recent_comm(10)) >= 1
    observability.record_decision("d1", "tech_agent", "回测完成", [{"step": "load"}, {"step": "calc"}])
    assert observability.get_decision("d1")["chain"][1]["step"] == "calc"
    agent_registry.unregister(a["agent_id"])


# ---------------------------------------------------------------- 模块二

def _zero_trust():
    from security.zero_trust import (authenticate, authorize, enforce, risk_score,
                                     AuthContext)
    from core.auth_service import (register_user, verify_password, create_token)
    from core.tenant_manager import tenant_register
    import uuid
    t = tenant_register(f"zt_test{uuid.uuid4().hex[:6]}")
    uname = f"zt_{uuid.uuid4().hex[:8]}"
    register_user(t["tenant_id"], uname, "Passw0rd!", role="analyst")
    u = verify_password(uname, "Passw0rd!")
    tok = create_token(u["user_id"], u["tenant_id"], u["role"])
    ident = authenticate(tok)
    assert ident["role"] == "analyst"
    assert authorize(ident, "view", AuthContext(hour=10))
    assert not authorize(ident, "delete", AuthContext(hour=10, ip="1.2.3.4", device="pc"))
    try:
        enforce(ident, "manage", AuthContext(hour=23, ip="1.2.3.4", device="pc"))
        raise AssertionError("异常时段管理动作未被拒绝")
    except PermissionError:
        pass
    assert risk_score("", "") >= 0.8


def _audit_ledger():
    import sqlite3
    import tempfile
    from pathlib import Path
    from security import audit_ledger as al
    # 独立临时库：测试自包含、可重复运行
    tmp = Path(tempfile.mkstemp(suffix=".db")[1])
    old_db = al._DB
    al._DB = tmp
    try:
        r1 = al.append("alice", "login")
        r2 = al.append("alice", "export", "detail=x")
        assert r2["prev_hash"] == r1["hash"]
        ok, n = al.verify()
        assert ok and n == 2
        # 篡改检测：手工改一条记录
        con = sqlite3.connect(tmp)
        con.execute("UPDATE ledger SET detail='tampered' WHERE seq=?", (r2["seq"],))
        con.commit()
        con.close()
        ok, _ = al.verify()
        assert not ok, "篡改未被检测"
        r3 = al.append("alice", "repair")  # 修复链头
        assert r3["seq"] == 3
    finally:
        al._DB = old_db
        try:
            tmp.unlink(missing_ok=True)
        except PermissionError:
            pass  # Windows 偶发句柄延迟释放，临时目录由系统清理


# ---------------------------------------------------------------- 模块三

def _vector_memory():
    from memory import vector_memory as vm
    vm.add_document("doc_moutai", "贵州茅台 白酒龙头 营收增长 毛利率高", {"kind": "analysis"})
    vm.add_document("doc_apple", "Apple AAPL 科技硬件 现金流强劲", {"kind": "analysis"})
    hits = vm.retrieve_similar("白酒 茅台", top_k=3)
    assert hits and hits[0]["text"].find("茅台") >= 0, hits
    assert vm.stats()["docs"] >= 2


def _graph_memory():
    import uuid
    from memory import graph_memory as gm
    tag = uuid.uuid4().hex[:6]
    stock, ind, ev = f"ST{tag}", f"IN{tag}", f"EV{tag}"
    gm.add_entity(stock, "stock", {"name": "测试公司"})
    gm.add_entity(ind, "industry")
    gm.add_entity(ev, "event")
    gm.add_relation(stock, ind, "belongs_to")
    gm.add_relation(ev, ind, "impacted_by")
    gm.add_relation(stock, ev, "affected_by")
    rel = gm.query_entity_relations(stock, depth=2)
    assert any(n["entity"] == ind for n in rel["nodes"])
    paths = gm.chain(stock, ev)
    assert any(p == [stock, ev] for p in paths)


def _hybrid_memory():
    from memory import hybrid_memory as hm
    assert hm.select_strategy("deterministic") == "structured"
    assert hm.select_strategy("conversational") == "retrieval"
    r = hm.search("白酒 茅台", top_k=3)
    assert isinstance(r, list) and len(r) >= 1
    assert hm.stats()["vector"]["docs"] >= 2


# ---------------------------------------------------------------- 模块四

def _reasoner():
    from reasoning import hybrid_reasoner as hr
    assert hr.gate(0.10) is True
    assert hr.gate(0.15) is True   # 边界值拦截
    assert hr.gate(0.50) is False
    r = hr.reason("conversational", "贵州茅台近况")
    assert r["strategy"] in ("retrieval", "structured", "auto")
    assert "gated" in r and "confidence" in r and isinstance(r["gated"], bool)
    g = hr.gated_decision("conversational", "近况")
    assert g["gated"] is False or "数据不足" in g["answer"]


# ---------------------------------------------------------------- 模块五

def _data_mesh():
    from data_mesh import domain_registry, data_catalog, data_contract
    domain_registry.seed()
    domains = domain_registry.list_domains()
    assert len(domains) >= 4
    assert any(d["domain_id"] == "market_data" for d in domains)
    data_catalog.register_product("p_kline", "market_data", "A股日K",
                                  "沪深A股日线", {"ticker": "str", "close": "float"},
                                  updated_at="2026-09-28", quality={"rows": 5000})
    found = data_catalog.search(domain_id="market_data", keyword="K")
    assert any(p["product_id"] == "p_kline" for p in found)
    dc = data_contract.DataContract("行情", {"close": "float", "ticker": "str"},
                                    required=["ticker"], quality={"freshness_sec": 60})
    assert dc.validate({"ticker": "SH600519", "close": 1800.0}) == []
    assert dc.validate({"close": "abc"})  # 缺 ticker + 类型错
    res = dc.validate_batch([{"ticker": "A", "close": 1.0}, {"close": 2.0}])
    assert res["ok"] == 1 and res["total"] == 2


# ---------------------------------------------------------------- 模块六

def _streaming():
    import asyncio
    from streaming.event_bus import EventBus
    from streaming.data_ingestion import DataIngestion
    from streaming.stream_processor import StreamProcessor

    async def main():
        bus = EventBus(max_queue=8)
        sub = bus.subscribe("alert_triggered", maxsize=8)
        ing = DataIngestion(bus, limit=8)
        proc = StreamProcessor(bus)
        # 背压：灌入超过队列上限
        for i in range(20):
            await ing.ingest("sina", "tick", {"ticker": "X", "close": float(i)})
        assert ing.dropped > 0, "背压未生效"
        n = await ing.flush_to_bus()
        assert n > 0
        # 窗口与异动：末值 100 远超均值
        for v in [1, 2, 3, 4, 100]:
            await proc.process("W", {"open": 1, "close": v, "volume": v})
        assert proc.alerts >= 1, "异动未触发"
        got = None
        try:
            got = sub.get_nowait()
        except asyncio.QueueEmpty:
            pass
        assert got is not None and got["type"] == "alert_triggered"
        assert proc.stats()["processed"] == 5

    asyncio.run(main())


# ---------------------------------------------------------------- 模块七

def _web_ui():
    from pathlib import Path
    assert Path("web_ui/static/index.html").exists()
    # fastapi 未装时 create_app 应给出明确错误（而非崩溃）
    import web_ui.app as app
    try:
        app.create_app()
        print("      (fastapi 已安装，跳过导入路径检查)")
    except RuntimeError as e:
        assert "fastapi" in str(e)


# ---------------------------------------------------------------- 模块八

def _compliance_deep():
    from compliance import gdpr, ccpa
    assert "导出" in gdpr.data_subject_rights()["portability"]
    assert "不出售" in ccpa.do_not_sell_declaration()
    ccpa.set_do_not_sell(True)
    assert ccpa.get_do_not_sell() is True
    from pathlib import Path
    for f in ("PRIVACY.md", "TERMS_OF_SERVICE.md", "config.yaml.example"):
        assert Path(f).exists()
    c = Path("PRIVACY.md").read_text(encoding="utf-8")
    assert "CCPA" in c


def _main_window_web_button():
    import pathlib
    c = pathlib.Path(r"D:\StockAIPredictor\app\ui\main_window.py").read_text(encoding="utf-8")
    i18n_c = pathlib.Path(r"D:\StockAIPredictor\i18n\__init__.py").read_text(encoding="utf-8")
    # 按钮文案走 i18n 字典（zh 原文须存在），入口方法存在
    assert "_open_web_ui" in c and "web.btn" in c
    assert "打开 Web 界面" in i18n_c


check("模块一 Agent Mesh(注册/身份/策略/观测)", _agent_mesh)
check("模块二 零信任(认证/授权/风险)", _zero_trust)
check("模块二 哈希链审计(防篡改)", _audit_ledger)
check("模块三 向量记忆(降级检索)", _vector_memory)
check("模块三 图记忆(关系/链路)", _graph_memory)
check("模块三 混合记忆(策略/融合)", _hybrid_memory)
check("模块四 混合推理(策略/门控)", _reasoner)
check("模块五 数据网格(域/目录/契约)", _data_mesh)
check("模块六 流处理(总线/背压/窗口/异动)", _streaming)
check("模块七 Web UI(静态页+导入路径)", _web_ui)
check("模块八 合规深化(GDPR/CCPA/文档)", _compliance_deep)
check("模块七 main_window Web按钮", _main_window_web_button)

fails = [r for r in RESULTS if not r[1]]
print(f"\n==== 企业深化测试 {len(RESULTS)-len(fails)}/{len(RESULTS)} 通过 ====")
sys.exit(1 if fails else 0)
