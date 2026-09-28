# -*- coding: utf-8 -*-
"""企业版模块一~八 单元测试（不依赖未安装的可选依赖）。"""
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

def _privacy():
    from core.privacy_compliance import (record_consent, consent_history,
                                         export_user_data, delete_user_data)
    record_consent("ent_test", "accept")
    assert any(r["action"] == "accept" for r in consent_history("ent_test"))
    snap = export_user_data("ent_test")
    assert snap["total_rows"] > 0
    dry = delete_user_data("ent_test", dry_run=True)
    assert dry["removed_rows"] >= 0


def _audit():
    from core.audit_logger import log_operation, query_audit, export_csv
    from pathlib import Path
    log_operation("ent_test", "login", "t")
    log_operation("ent_test", "analysis", "SH600519")
    assert len(query_audit(action="analysis")) >= 1
    out = export_csv()
    assert Path(out).exists()


# ---------------------------------------------------------------- 模块二

def _tenant():
    from core.tenant_manager import (tenant_register, tenant_conn,
                                     tenant_set_status, list_tenants)
    t = tenant_register("企业测试", plan="enterprise")
    with tenant_conn(t["tenant_id"]) as c:
        c.execute("INSERT INTO workspace(name, created_at) VALUES('a','2026-09-28')")
    assert len(list_tenants()) >= 1
    tenant_set_status(t["tenant_id"], "disabled")
    try:
        tenant_conn(t["tenant_id"])
        raise AssertionError("禁用租户未被隔离")
    except PermissionError:
        pass
    tenant_set_status(t["tenant_id"], "active")


def _auth():
    import uuid
    from core.auth_service import (register_user, verify_password, create_token,
                                   verify_token, reset_password, has_permission)
    from core.tenant_manager import tenant_register
    t = tenant_register(f"认证测试{uuid.uuid4().hex[:6]}")
    uname = f"ent_{uuid.uuid4().hex[:8]}"
    register_user(t["tenant_id"], uname, "Passw0rd!", role="analyst")
    assert verify_password(uname, "Passw0rd!") is not None
    assert verify_password(uname, "wrong") is None
    u = verify_password(uname, "Passw0rd!")
    tok = create_token(u["user_id"], u["tenant_id"], u["role"])
    assert verify_token(tok)["role"] == "analyst"
    try:
        verify_token(tok + "x")
        raise AssertionError("伪造 token 未被拦截")
    except PermissionError:
        pass
    reset_password(uname, "NewPass1!")
    assert verify_password(uname, "NewPass1!") is not None
    assert has_permission("viewer", "view")
    assert not has_permission("viewer", "export")


# ---------------------------------------------------------------- 模块四

def _collab():
    from core.collaboration import (create_workspace, join_workspace,
                                    add_comment, list_comments,
                                    commit_version, list_versions, rollback_to)
    import uuid
    w = create_workspace(f"企业协作组{uuid.uuid4().hex[:6]}", "u_admin")
    join_workspace(w["id"], "u_analyst")
    add_comment(w["id"], "SH600519", "u_analyst", "MA20 支撑")
    assert len(list_comments(w["id"], "SH600519")) == 1
    commit_version(w["id"], "s:ma", "v1", "u_analyst")
    commit_version(w["id"], "s:ma", "v2", "u_analyst")
    assert len(list_versions(w["id"], "s:ma")) == 2
    r = rollback_to(w["id"], "s:ma", 1, "u_admin")
    assert r["version_no"] == 3


# ---------------------------------------------------------------- 模块五

def _connector():
    import pandas as pd
    from core.data_connector import parse_csv, import_to_cache
    from core.data import cache
    from pathlib import Path
    df = pd.DataFrame({"日期": ["2026-09-01", "2026-09-02"],
                       "开盘": [10, 10.5], "最高": [11, 11.2],
                       "最低": [9.8, 10.2], "收盘": [10.8, 10.9],
                       "成交量": [100, 120]})
    tmp = Path("data/_ent_t.csv")
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    bars = parse_csv(tmp)
    import_to_cache(bars, "ENTIMPORT")
    cached = cache.load_bars("ENTIMPORT")
    assert len(cached) == 2, f"数据完整性失败: {len(cached)}"
    tmp.unlink()
    with cache.get_conn() as c:
        c.execute("DELETE FROM daily_bars WHERE ticker='ENTIMPORT'")


def _market():
    from core.data_marketplace import (list_catalog, subscribe, unsubscribe,
                                       active_sources)
    subscribe("t_ent_test", "tushare")
    assert active_sources("t_ent_test") == ["tushare"]
    unsubscribe("t_ent_test", "tushare")
    assert active_sources("t_ent_test") == []
    assert len(list_catalog()) >= 5


# ---------------------------------------------------------------- 模块六

def _risk():
    import numpy as np
    import pandas as pd
    from core.risk_engine import calculate_var, stress_test, attribution
    np.random.seed(7)
    r = pd.DataFrame({"A": np.random.normal(0, 0.02, 200),
                      "B": np.random.normal(0, 0.03, 200)})
    var = calculate_var(r, confidence=0.95)
    assert 0 < var["var_pct"] < 20
    assert len(stress_test(r)) == 4
    att = attribution(r)
    assert list(att.columns) == ["ticker", "weight", "period_return_pct", "contribution_pct"]


def _compliance_check():
    from core.compliance_checker import (save_rules, check_position,
                                         check_portfolio, load_rules)
    save_rules({"blacklist": ["600xxx"], "position_cap": 0.3, "sector_cap": 0.4})
    assert load_rules()["position_cap"] == 0.3
    assert check_position("600xxx", 0.1)[0]["type"] == "blacklist"
    assert check_position("600519", 0.45)[0]["type"] == "position_cap"
    res = check_portfolio([{"ticker": "A", "weight": 0.6, "sector": "科技"},
                           {"ticker": "B", "weight": 0.4, "sector": "科技"}])
    assert not res["pass"] and any(v["type"] == "sector_cap" for v in res["violations"])


# ---------------------------------------------------------------- 模块八

def _i18n():
    from core.i18n import set_language, t, available_languages
    assert available_languages() == ["zh", "en"]
    set_language("en")
    assert t("btn_search") == "Search"
    set_language("zh")
    assert t("btn_search") == "搜索"


def _docs_exist():
    from pathlib import Path
    for f in ["docs/ENTERPRISE.md", "docs/COMPLIANCE.md", "docs/API.md",
              "docker-compose.yml", "Dockerfile", ".env.docker",
              "deploy/chart/Chart.yaml", "deploy/chart/values.yaml",
              "core/privacy_compliance.py", "core/audit_logger.py",
              "core/tenant_manager.py", "core/auth_service.py",
              "core/collaboration.py", "core/data_connector.py",
              "core/data_marketplace.py", "core/risk_engine.py",
              "core/compliance_checker.py", "api/main.py"]:
        assert Path(f).exists(), f"缺失 {f}"


check("模块一 隐私合规(GDPR)", _privacy)
check("模块一 操作审计", _audit)
check("模块二 多租户隔离", _tenant)
check("模块二 认证与RBAC", _auth)
check("模块四 协作工作流", _collab)
check("模块五 CSV导入缓存", _connector)
check("模块五 数据源市场", _market)
check("模块六 风控引擎", _risk)
check("模块六 合规检查", _compliance_check)
check("模块八 国际化", _i18n)
check("模块七/八 部署与文档文件", _docs_exist)

fails = [r for r in RESULTS if not r[1]]
print(f"\n==== 企业版测试 {len(RESULTS)-len(fails)}/{len(RESULTS)} 通过 ====")
sys.exit(1 if fails else 0)
