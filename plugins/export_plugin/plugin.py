# -*- coding: utf-8 -*-
"""示例插件：扩展导出格式（HTML / CSV）。"""
import csv
import html
import os
import time

from plugin_system import PluginBase


class Plugin(PluginBase):
    metadata = {
        "name": "export_plugin",
        "version": "0.1.0",
        "author": "疏影雅集",
        "description": "扩展导出格式：将分析报告导出为 HTML / CSV。",
        "permissions": ["file_write"],
    }

    def on_load(self, ctx):
        pass

    def register_tools(self, ctx):
        ctx.register_tool(
            "plugin_export_html",
            self.export_html,
            desc="把标题+正文导出为 HTML 文件，返回保存路径。",
            schema={"title": "str", "body": "str", "out_dir": "str"},
        )
        ctx.register_tool(
            "plugin_export_csv",
            self.export_csv,
            desc="把二维表数据导出为 CSV 文件，返回保存路径。",
            schema={"headers": "list", "rows": "list", "out_dir": "str"},
        )

    def export_html(self, title: str = "报告", body: str = "", out_dir: str = "") -> dict:
        d = out_dir or os.path.join(os.getcwd(), "exports")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"report_{int(time.time())}.html")
        content = (f"<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>"
                   f"<title>{html.escape(title)}</title></head><body>"
                   f"<h1>{html.escape(title)}</h1><div>{html.escape(body)}</div></body></html>")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True, "path": path, "bytes": len(content.encode("utf-8"))}

    def export_csv(self, headers: list | None = None, rows: list | None = None,
                   out_dir: str = "") -> dict:
        d = out_dir or os.path.join(os.getcwd(), "exports")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"data_{int(time.time())}.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            if headers:
                w.writerow(headers)
            for r in rows or []:
                w.writerow(r)
        return {"ok": True, "path": path}
