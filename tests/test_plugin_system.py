# -*- coding: utf-8 -*-
"""模块五：插件化生态测试。"""
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugin_system import PluginBase, PluginContext, PluginManager  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGINS_DIR = os.path.join(ROOT, "plugins")

PASS = 0


def ok(name: str):
    global PASS
    PASS += 1
    print(f"[ok] {name}")


def test_discover_finds_three_plugins():
    mgr = PluginManager(PLUGINS_DIR)
    found = mgr.discover()
    names = {d["name"] for d in found}
    assert {"sentiment_plugin", "backtest_plugin", "export_plugin"} <= names
    for d in found:
        assert d["manifest"] is not None, f"{d['name']} 缺 manifest.json"
    ok("发现 3 个示例插件且 manifest 完整")


def test_load_plugin_and_register_tools():
    mgr = PluginManager(PLUGINS_DIR)
    ctx = PluginContext()
    assert mgr.load("sentiment_plugin", ctx), "sentiment_plugin 应加载成功"
    assert "plugin_sentiment_score" in ctx.tools
    r = ctx.tools["plugin_sentiment_score"]["fn"](text="公司业绩超预期增长，利润大幅提升")
    assert r["label"] == "利好" and r["score"] > 0
    r2 = ctx.tools["plugin_sentiment_score"]["fn"](text="公司爆出财务造假，股价大跌")
    assert r2["label"] == "利空"
    ok("插件加载后工具注册并可调用（情感打分）")


def test_backtest_plugin_deterministic_rules():
    mgr = PluginManager(PLUGINS_DIR)
    ctx = PluginContext()
    assert mgr.load("backtest_plugin", ctx)
    closes = [10, 10.5, 11, 11.5, 12, 12.5, 13, 13.5]
    sig = ctx.tools["plugin_ma_cross_signal"]["fn"](fast=2, slow=4, closes=closes)
    assert sig["signal"] == 1, "上升趋势双均线应为买入信号"
    mom = ctx.tools["plugin_momentum_signal"]["fn"](n=3, closes=closes)
    assert mom["signal"] == 1
    ok("回测插件：确定性规则输出正确")


def test_export_plugin_writes_files():
    mgr = PluginManager(PLUGINS_DIR)
    ctx = PluginContext()
    assert mgr.load("export_plugin", ctx)
    with tempfile.TemporaryDirectory() as td:
        r = ctx.tools["plugin_export_csv"]["fn"](headers=["a", "b"], rows=[[1, 2], [3, 4]],
                                                 out_dir=td)
        assert r["ok"] and os.path.isfile(r["path"])
        with open(r["path"], "r", encoding="utf-8-sig") as f:
            assert f.read().strip().splitlines()[0].startswith("a,b")
    ok("导出插件：CSV 落盘可回读")


def test_permission_grant_filters_undeclared():
    mgr = PluginManager(PLUGINS_DIR)
    perms = mgr.requested_permissions("sentiment_plugin")
    assert perms == ["data_access"]
    r = mgr.grant_permissions("sentiment_plugin", ["data_access", "network"])
    assert r["granted"] == ["data_access"] and r["denied"] == ["network"]
    ok("权限系统：只授予 manifest 声明过的权限")


def test_unload_and_reload():
    mgr = PluginManager(PLUGINS_DIR)
    ctx = PluginContext()
    assert mgr.load("sentiment_plugin", ctx)
    assert mgr.unload("sentiment_plugin")
    assert "sentiment_plugin" not in mgr._instances
    assert mgr.load("sentiment_plugin", ctx), "重新加载应成功"
    ok("插件可卸载并重新加载")


def test_install_zip_and_reject_traversal():
    mgr = PluginManager(PLUGINS_DIR)
    with tempfile.TemporaryDirectory() as td:
        zip_path = os.path.join(td, "demo_plugin.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("demo_plugin/manifest.json",
                        '{"name":"demo_plugin","version":"0.0.1","permissions":["data_access"]}')
            zf.writestr("demo_plugin/plugin.py",
                        "from plugin_system import PluginBase\n"
                        "class Plugin(PluginBase):\n"
                        "    metadata={'name':'demo_plugin','version':'0.0.1',"
                        "'permissions':['data_access'],'author':'t','description':'d'}\n"
                        "    def register_tools(self, ctx):\n"
                        "        ctx.register_tool('demo_ping', lambda: 'pong')\n")
        r = mgr.install_zip(zip_path)
        assert r["ok"] and r["name"] == "demo_plugin"
        assert r["permissions"] == ["data_access"]
        ctx = PluginContext()
        assert mgr.load("demo_plugin", ctx)
        assert "demo_ping" in ctx.tools

        # 路径穿越拒绝
        bad_zip = os.path.join(td, "bad.zip")
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("evil/../../outside.py", "x=1")
        rb = mgr.install_zip(bad_zip)
        assert rb["ok"] is False and "非法路径" in rb.get("error", "")
    ok("zip 安装成功；路径穿越被拒绝")


def test_missing_plugin_py_fails():
    mgr = PluginManager(PLUGINS_DIR)
    assert not mgr.load("not_exists_plugin"), "不存在的插件应加载失败"
    ok("缺失插件加载返回 False（不抛异常）")


def _main():
    test_discover_finds_three_plugins()
    test_load_plugin_and_register_tools()
    test_backtest_plugin_deterministic_rules()
    test_export_plugin_writes_files()
    test_permission_grant_filters_undeclared()
    test_unload_and_reload()
    test_install_zip_and_reject_traversal()
    test_missing_plugin_py_fails()
    print(f"\nALL PASS ({PASS})")


if __name__ == "__main__":
    _main()
