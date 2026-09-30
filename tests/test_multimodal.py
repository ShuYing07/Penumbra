# -*- coding: utf-8 -*-
"""模块一 · 多模态金融数据解析：unit tests。

覆盖：PDF/图表/音频的文本形态直读、降级提示、统一入口路由、规则提取。
真实转录/视觉 LLM 属可选后端，未安装时验证"诚实降级"。
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STOCKAI_MOCK", "1")

import tempfile
from pathlib import Path

from core.multimodal_parser import (
    parse_earnings_call, parse_chart_image, parse_pdf_report,
    parse_multimodal_file, _tone_rules, _extract_key_figures,
)


def _w(path: str, text: str) -> str:
    Path(path).write_text(text, encoding="utf-8")
    return path


def test_earnings_call_text_mode():
    with tempfile.TemporaryDirectory() as d:
        p = _w(os.path.join(d, "call.txt"),
               "Q: 对全年增长的展望？\nA: 我们对下半年保持乐观，营收增长强劲，超出预期。\n"
               "公司称业务承压但整体向好。")
        r = parse_earnings_call(p)
        assert r["ok"] and r["kind"] == "earnings_call"
        assert r["source"] == "text-file"
        assert "Q" in r["transcript"] or "展望" in r["transcript"]
        assert r["tone"] in ("乐观", "谨慎", "中性", "未知")


def test_tone_rules():
    assert _tone_rules("增长强劲 超预期 有信心") == "乐观"
    assert _tone_rules("承压 下滑 风险") == "谨慎"


def test_chart_image_text_mode():
    with tempfile.TemporaryDirectory() as d:
        p = _w(os.path.join(d, "chart.txt"),
               "上升趋势，支撑位320附近，阻力位350附近，疑似双底形态。")
        r = parse_chart_image(p)
        assert r["ok"] and r["kind"] == "chart_image"
        assert r["trend"] == "上升"
        assert "双底" in r["forms"]
        assert "320" in r["support_levels"][0]


def test_pdf_report_text_mode_and_figures():
    with tempfile.TemporaryDirectory() as d:
        p = _w(os.path.join(d, "report.txt"),
               "报告期营业收入 128.5 亿元，净利润 32.4 亿元，毛利率 45.2%，"
               "资产负债率 52.1%。经营稳健。")
        r = parse_pdf_report(p)
        assert r["ok"] and r["kind"] == "pdf_report"
        fig = r["figures"]
        assert "128.5" in fig.get("营业收入", "")
        assert "32.4" in fig.get("净利润", "")
        assert fig.get("毛利率", "").endswith("%")


def test_figure_extraction_regression():
    f = _extract_key_figures("净利润 -8.9 亿元，净资产收益率 12.5%")
    assert "-8.9" in f.get("净利润", "")
    assert "12.5" in f.get("净资产收益率", "")


def test_unified_routing_by_ext():
    with tempfile.TemporaryDirectory() as d:
        p_pdf = _w(os.path.join(d, "a.pdf.txt"), "营收 100 亿")  # 文本直读 pdf
        p_png = _w(os.path.join(d, "b.png.txt"), "下降趋势，阻力位30")
        r = parse_multimodal_file(p_pdf)
        assert r["kind"] == "pdf_report"
        r = parse_multimodal_file(p_png)
        assert r["kind"] == "chart_image"


def test_missing_file_honest_degrade():
    r = parse_multimodal_file("D:/no/such/file.pdf")
    assert not r["ok"] and "不存在" in r["note"]


def test_unknown_ext():
    with tempfile.TemporaryDirectory() as d:
        p = _w(os.path.join(d, "x.xyz"), "data")
        r = parse_multimodal_file(p)
        assert not r["ok"] and "不支持" in r["note"]


def test_audio_without_whisper_honest_degrade():
    # 不存在的真实音频：无 faster-whisper → 诚实降级提示（若已安装则走转录失败路径）
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "call.mp3")
        Path(p).write_bytes(b"\x00\x01\x02")  # 伪音频
        r = parse_earnings_call(p)
        if not r["ok"]:
            assert "faster-whisper" in r["note"] or "转录" in r["note"] or "不存在" in r["note"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"[ok] {fn.__name__}")
    print(f"\nALL PASS ({len(fns)})")
