# -*- coding: utf-8 -*-
"""报告生成：把分析结果导出为 Markdown / HTML，存到本地知识库。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.config import DISCLAIMER

REPORT_DIR = Path(r"D:\StockAI_Knowledge\reports")


def _sources(analysis_results: dict) -> list[str]:
    src = analysis_results.get("data_sources") or analysis_results.get("sources") or []
    if isinstance(src, str):
        return [src]
    return [str(s) for s in src]


def generate_markdown_report(stock_code: str, analysis_results: dict) -> str:
    name = analysis_results.get("stock_name") or stock_code
    lines = [
        f"# {name}（{stock_code}）分析报告",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 技术指标摘要",
        "",
    ]
    tech = analysis_results.get("indicators") or analysis_results.get("tech") or {}
    if tech:
        lines.append("| 指标 | 数值 |")
        lines.append("|---|---|")
        for k, v in tech.items():
            lines.append(f"| {k} | {v} |")
    else:
        lines.append("- （无技术指标数据）")

    bull = analysis_results.get("bull_points") or analysis_results.get("bull_case") or []
    bear = analysis_results.get("bear_points") or analysis_results.get("bear_case") or []
    if bull or bear:
        lines += ["", "## 多空辩论要点", "", "### 多方论据"]
        lines += [f"- {x}" for x in bull] or ["- （无）"]
        lines += ["", "### 空方论据"]
        lines += [f"- {x}" for x in bear] or ["- （无）"]

    patterns = analysis_results.get("patterns") or []
    if patterns:
        lines += ["", "## 检测到的 K 线形态", ""]
        for p in patterns:
            lines.append(f"- {p.get('pattern_name')}（{p.get('start_date')}~{p.get('end_date')}，"
                         f"置信 {p.get('confidence')}）")

    src = _sources(analysis_results)
    lines += ["", "## 数据来源", ""]
    lines += [f"- {s}" for s in src] or ["- （未记录）"]

    lines += ["", "---", f"**{DISCLAIMER}**"]
    return "\n".join(lines)


def generate_html_report(stock_code: str, analysis_results: dict) -> str:
    md = generate_markdown_report(stock_code, analysis_results)
    body = md.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    import html as _html
    body_html = _html.escape(md)
    # 极简 Markdown→HTML：标题/列表/表格
    out = []
    for line in body_html.splitlines():
        if line.startswith("# "):
            out.append(f"<h2>{line[2:]}</h2>")
        elif line.startswith("## "):
            out.append(f"<h3>{line[3:]}</h3>")
        elif line.startswith("- "):
            out.append(f"<li>{line[2:]}</li>")
        elif line.startswith("> "):
            out.append(f"<blockquote>{line[2:]}</blockquote>")
        elif line.startswith("|"):
            out.append(f"<pre>{line}</pre>")
        elif line.strip():
            out.append(f"<p>{line}</p>")
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{stock_code} 分析报告</title>"
        "<style>body{background:#0D1117;color:#E6EDF3;font-family:sans-serif;"
        "max-width:860px;margin:2rem auto;padding:0 1rem;line-height:1.6}"
        "h2{color:#2F81F7}h3{color:#58A6FF}li{margin:.2rem 0}"
        "blockquote{color:#8b949e;border-left:3px solid #2F81F7;padding-left:.8rem}"
        "pre{white-space:pre-wrap}</style></head><body>"
        + "\n".join(out) + "</body></html>"
    )


def export_report(stock_code: str, analysis_results: dict, fmt: str = "md") -> str:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fmt = (fmt or "md").lower()
    if fmt == "html":
        content = generate_html_report(stock_code, analysis_results)
        path = REPORT_DIR / f"{stock_code}_{ts}.html"
    else:
        content = generate_markdown_report(stock_code, analysis_results)
        path = REPORT_DIR / f"{stock_code}_{ts}.md"
    path.write_text(content, encoding="utf-8")
    return str(path)
