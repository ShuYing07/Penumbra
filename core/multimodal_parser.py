# -*- coding: utf-8 -*-
"""多模态金融数据解析（模块一）：财报电话会议音频 / 图表图片 / PDF 财报。

设计原则（对齐 NVIDIA Nemotron Omni / FinVLM 的"统一多模态解析"思路，工程上保持零依赖可运行）：
- 每条路径都有【降级链】：最强后端（本地多模态模型/语音转录）→ LLM 文本分析 → 规则兜底；
- 后端未安装/不可用时【诚实降级】：返回 ok=False + note，绝不假装解析成功；
- 文本形态（.txt/.json/markdown）直接进入分析，便于测试与离线使用。

可复用组件：
- core.model_router.chat / chat_vision：多模态 LLM 后端（OpenAI 兼容，含 ollama 本地视觉）
- 语音转录：faster-whisper（可选，未安装则提示）
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

log = logging.getLogger("stockai.multimodal")

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _read_text_file(path: str) -> str | None:
    """尽力读取文本文件（utf-8 / gbk 兜底）。非文本返回 None。"""
    try:
        b = Path(path).read_bytes()
        for enc in ("utf-8-sig", "utf-8", "gbk"):
            try:
                return b.decode(enc)
            except UnicodeDecodeError:
                continue
    except OSError as e:
        log.warning("multimodal: 读取失败 %s: %s", path, str(e)[:80])
    return None


def _llm(prompt: str, system: str = "") -> str | None:
    from core.model_router import chat
    return chat(prompt, system=system, platform="auto", timeout=60)


def _empty_result(kind: str, note: str) -> dict:
    return {"ok": False, "kind": kind, "note": note, "created_at": time.time()}


# ---------------------------------------------------------------------------
# 1) 财报电话会议：音频 → 转录 → 语气/关键措辞/问答
# ---------------------------------------------------------------------------

def _transcribe_audio(audio_path: str) -> str | None:
    """语音转录：优先 faster-whisper；未安装返回 None（由调用方提示）。"""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        log.warning("multimodal: faster-whisper 未安装，无法转录音频")
        return None
    try:
        model = WhisperModel("small", device="cpu", compute_type="int8")
        segments, _info = model.transcribe(audio_path, language=None)
        return " ".join(s.text.strip() for s in segments if s.text.strip())
    except Exception as e:  # noqa: BLE001
        log.warning("multimodal: 转录失败 %s: %s", audio_path, str(e)[:100])
        return None


_TONE_KEYWORDS = {
    "乐观": ["看好", "增长", "超预期", "强劲", "有信心", "机遇", "乐观", "提升", "改善", "突破"],
    "谨慎": ["谨慎", "承压", "放缓", "挑战", "风险", "不确定", "观望", "下滑", "压力"],
    "中性": ["平稳", "稳定", "正常", "符合预期", "中性", "持平"],
}


def _tone_rules(text: str) -> str:
    hits = {k: sum(1 for w in ws if w in text) for k, ws in _TONE_KEYWORDS.items()}
    best = max(hits, key=hits.get)
    return best if hits[best] else "未知"


def _extract_qa(text: str) -> list[str]:
    """按常见的 "Q:"/"A:" 或 "问："/"答：" 切分问答环节（规则兜底）。"""
    qa = []
    for m in re.finditer(r"(?:^|\n)\s*(?:Q[:：]|问[:：])\s*(.{0,200})", text):
        qa.append(m.group(1).strip())
    return qa[:10]


def parse_earnings_call(audio_path: str) -> dict:
    """解析财报电话会议录音。返回转录文本、语气判断、关键措辞、问答片段。"""
    path = Path(audio_path)
    if not path.exists():
        return _empty_result("earnings_call", f"文件不存在：{audio_path}")

    # 文本形态直读（.txt/.md/.json —— 测试与离线场景）
    if path.suffix.lower() in (".txt", ".md", ".json"):
        text = _read_text_file(str(path))
        if text is None:
            return _empty_result("earnings_call", "文本读取失败")
        transcript, source = text, "text-file"
    else:
        transcript = _transcribe_audio(str(path))
        if transcript is None:
            return _empty_result(
                "earnings_call",
                "未安装语音转录引擎（faster-whisper）或转录失败。"
                "请手动执行：pip install faster-whisper 后重试；"
                "或将会议逐字稿保存为 .txt 上传（程序直接进入分析）。")
        source = "faster-whisper"

    # 语气/关键措辞/问答：LLM 优先，规则兜底
    system = ("你是金融 NLP 专家。从财报电话会议逐字稿中提取："
              "1) 管理层语气（乐观/谨慎/中性）；2) 3-5 条关键措辞（原句+含义）；"
              "3) 问答环节要点。用简洁中文返回。")
    llm_out = _llm(f"逐字稿（节选，共{len(transcript)}字）：\n{transcript[:4000]}", system=system)
    if not llm_out:
        llm_out = (f"（规则模式）语气：{_tone_rules(transcript)}；"
                   f"问答片段 {len(_extract_qa(transcript))} 条")
    return {
        "ok": True,
        "kind": "earnings_call",
        "source": source,
        "transcript": transcript,
        "tone": _tone_rules(transcript),
        "analysis": llm_out,
        "created_at": time.time(),
    }


# ---------------------------------------------------------------------------
# 2) 图表图片：趋势线 / 支撑阻力 / 形态（头肩顶、双底…）
# ---------------------------------------------------------------------------

def parse_chart_image(image_path: str) -> dict:
    """识别图表中的趋势、支撑阻力位与经典形态。视觉 LLM 优先，规则兜底。"""
    path = Path(image_path)
    if not path.exists():
        return _empty_result("chart_image", f"文件不存在：{image_path}")

    # 文本描述形态直读（测试/离线）
    if path.suffix.lower() in (".txt", ".md", ".json"):
        desc = _read_text_file(str(path))
        if desc is None:
            return _empty_result("chart_image", "文本读取失败")
        text, source = desc, "text-file"
    else:
        prompt = ("你是量化图表分析师。分析这张K线/走势图："
                  "1) 当前趋势（上升/下降/震荡）；2) 关键支撑位与阻力位（给出大致价位）；"
                  "3) 是否出现经典形态（头肩顶/头肩底/双顶/双底/三角形/旗形）并说明依据。"
                  "用简洁中文输出。")
        text = _llm_chat_vision(prompt, str(path))
        if text is None:
            return _empty_result(
                "chart_image",
                "无可用视觉模型（未配置 OpenAI 兼容视觉平台 / ollama 未装视觉模型）。"
                "可配置 SILICONFLOW_API_KEY 或安装 ollama 的 llava/qwen2.5vl 后重试；"
                "或将图表描述保存为 .txt 上传。")
        source = "vision-llm"

    # 规则提取形态关键词（供结构化字段展示，不替代视觉判断）
    forms = [k for k in ("头肩顶", "头肩底", "双顶", "双底", "三角形", "旗形", "楔形")
             if k in text]
    trend = ("上升" if re.search(r"上升|上涨|看涨|多头", text)
             else "下降" if re.search(r"下降|下跌|看跌|空头", text) else "震荡/未知")
    support = re.findall(r"支撑(?:位)?[：:]?\s*([\d.]+)", text)
    resistance = re.findall(r"阻力(?:位)?[：:]?\s*([\d.]+)", text)
    return {
        "ok": True,
        "kind": "chart_image",
        "source": source,
        "analysis": text,
        "trend": trend,
        "forms": forms or ["未识别到经典形态"],
        "support_levels": support[:5],
        "resistance_levels": resistance[:5],
        "created_at": time.time(),
    }


def _llm_chat_vision(prompt: str, image_path: str) -> str | None:
    """内部：视觉 LLM，失败即 None。"""
    try:
        from core.model_router import chat_vision
        return chat_vision(prompt, image_path, platform="auto", timeout=90)
    except Exception as e:  # noqa: BLE001
        log.warning("multimodal: 视觉调用异常 %s", str(e)[:80])
        return None


# ---------------------------------------------------------------------------
# 3) PDF 财报：表格 + 图表 + 关键财务数据
# ---------------------------------------------------------------------------

def _pdf_to_text(pdf_path: str) -> tuple[str | None, list[list[str]]]:
    """PDF 文本+表格提取：pdfplumber 优先 → pypdf/PyPDF2 兜底。"""
    tables: list[list[str]] = []
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            parts = []
            for page in pdf.pages[:60]:
                t = page.extract_text() or ""
                parts.append(t)
                for tbl in (page.extract_tables() or []):
                    for row in tbl:
                        tables.append([str(c) if c is not None else "" for c in row])
            return "\n".join(parts), tables
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        log.warning("multimodal: pdfplumber 解析失败 %s", str(e)[:100])
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader
        except ImportError:
            return None, tables
    try:
        reader = PdfReader(pdf_path)
        return "\n".join((p.extract_text() or "") for p in reader.pages[:60]), tables
    except Exception as e:  # noqa: BLE001
        log.warning("multimodal: pypdf 解析失败 %s", str(e)[:100])
        return None, tables


def _extract_key_figures(text: str) -> dict[str, str]:
    """规则提取关键财务数字（LLM 失败时兜底）。"""
    out: dict[str, str] = {}
    pats = {
        "营业收入": r"(?:营业收入|营收|总收入)\s*[=:：]?\s*([\d,，.]+)\s*(亿元|万元|亿)?",
        "净利润": r"(?:净利润|归母净利润|净利)\s*[=:：]?\s*([-+]?[\d,，.]+)\s*(亿元|万元|亿)?",
        "毛利率": r"毛利率\s*[=:：]?\s*([\d.]+)\s*%",
        "净资产收益率": r"(?:ROE|净资产收益率)\s*[=:：]?\s*([\d.]+)\s*%",
        "资产负债率": r"资产负债率\s*[=:：]?\s*([\d.]+)\s*%",
    }
    for k, p in pats.items():
        m = re.search(p, text)
        if m:
            g1 = m.group(1)
            g2 = m.group(2) if len(m.groups()) >= 2 else ""
            suffix = "%" if (g1 and "%" in p and not g2) else ""
            out[k] = f"{g1}{g2}{suffix}".strip()
    return out


def parse_pdf_report(pdf_path: str) -> dict:
    """提取 PDF 财报的文本、表格与关键财务数据。"""
    path = Path(pdf_path)
    if not path.exists():
        return _empty_result("pdf_report", f"文件不存在：{pdf_path}")

    if path.suffix.lower() in (".txt", ".md", ".json"):
        text = _read_text_file(str(path))
        if text is None:
            return _empty_result("pdf_report", "文本读取失败")
        return {
            "ok": True, "kind": "pdf_report", "source": "text-file",
            "text": text, "tables": [], "figures": _extract_key_figures(text),
            "analysis": "（文本直读模式：请结合表格与关键财务数据人工复核）",
            "created_at": time.time(),
        }

    text, tables = _pdf_to_text(str(path))
    if text is None:
        return _empty_result(
            "pdf_report",
            "未安装 PDF 解析库（pdfplumber / pypdf）。请手动执行："
            "pip install pdfplumber 后重试；或将财报文本另存为 .txt 上传。")
    figures = _extract_key_figures(text)
    system = ("你是财务分析专家。基于财报内容给出：1) 业绩亮点；2) 风险点；"
              "3) 关键指标解读。若文本过短请明确说明。简洁中文输出。")
    llm_out = _llm(f"财报文本（节选，共{len(text)}字）：\n{text[:6000]}", system=system)
    return {
        "ok": True, "kind": "pdf_report", "source": "pdf-parser",
        "text": text[:20000], "tables": tables[:50],
        "figures": figures, "analysis": llm_out or "（无可用 LLM：请人工解读）",
        "created_at": time.time(),
    }


# ---------------------------------------------------------------------------
# 统一入口：按扩展名路由
# ---------------------------------------------------------------------------

_KIND_BY_EXT = {
    ".pdf": "pdf_report",
    ".png": "chart_image", ".jpg": "chart_image", ".jpeg": "chart_image",
    ".bmp": "chart_image", ".webp": "chart_image",
    ".mp3": "earnings_call", ".wav": "earnings_call", ".m4a": "earnings_call",
    ".flac": "earnings_call", ".ogg": "earnings_call",
    ".txt": None, ".md": None, ".json": None,  # 文本按文件名关键字路由
}


def parse_multimodal_file(path: str, kind: str | None = None) -> dict:
    """统一入口。kind 未指定时按扩展名/文件名自动判断。"""
    p = Path(path)
    ext = p.suffix.lower()
    if kind:
        fn = {"earnings_call": parse_earnings_call,
              "chart_image": parse_chart_image,
              "pdf_report": parse_pdf_report}.get(kind)
        if not fn:
            return _empty_result(kind or "unknown", f"未知解析类型：{kind}")
        return fn(path)
    auto = _KIND_BY_EXT.get(ext)
    if auto:
        return parse_multimodal_file(path, auto)
    if ext in (".txt", ".md", ".json"):
        name = p.name.lower()
        if "call" in name or "会议" in name or "earnings" in name:
            return parse_earnings_call(path)
        if "pdf" in name or "财报" in name or "report" in name:
            return parse_pdf_report(path)
        return parse_chart_image(path)  # 默认按图表描述处理
    return _empty_result("unknown",
                         f"暂不支持的文件类型：{ext}。支持 PDF/PNG/JPG/MP3/WAV/M4A 及文本。")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        r = parse_multimodal_file(sys.argv[1])
        print(json.dumps({k: v for k, v in r.items()
                          if k not in ("text", "transcript")}, ensure_ascii=False, indent=2))
    else:
        print("用法：python core/multimodal_parser.py <file>")
