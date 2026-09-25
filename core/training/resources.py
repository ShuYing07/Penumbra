# -*- coding: utf-8 -*-
"""教学资源获取与解析（蒸馏数据来源）。

设计：
- 资源源注册表（REGISTRY）：每个源声明 URL/类型/许可证/语言/主题/网络上下文；
- 获取：按源声明的 network 走 foreign_network()/domestic_network()（复用 config 代理切换）；
- 解析：PDF→pdfplumber、HTML→trafilatura（fallback bs4）、Markdown→直读；
  pdfplumber/trafilatura 为可选依赖，缺失时友好降级（不进打包）；
- 产物：data/training/corpus_raw/{source_id}.txt（纯文本），供打包 exe 直接消费。

纪律：只收显式开放许可（CC-BY/BY-SA/Public Domain/官方投教公开材料），
不碰盗版书；权重不分发，仅本地训练。详见 training_configs/LICENSE_MANIFEST.md。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from core.config import DATA_DIR, foreign_network, domestic_network

log = logging.getLogger("stockai.resources")

CORPUS_DIR = DATA_DIR / "training" / "corpus_raw"


@dataclass(frozen=True)
class ResourceSource:
    id: str                 # 稳定标识，如 investopedia_what_is_stock
    name: str               # 显示名
    url: str                # 规范 URL
    kind: str               # "pdf" | "html" | "markdown"
    license: str            # "CC-BY-SA-4.0" | "Public Domain" | "Educational Use" | ...
    language: str           # "zh" | "en"
    topics: tuple[str, ...] = ()   # ("technical","macro","risk",...)
    network: str = "foreign"       # "foreign" | "domestic" → 决定走哪个网络上下文


REGISTRY: dict[str, ResourceSource] = {}


def register(src: ResourceSource) -> None:
    REGISTRY[src.id] = src


def list_sources() -> list[ResourceSource]:
    return list(REGISTRY.values())


def get(source_id: str) -> ResourceSource | None:
    return REGISTRY.get(source_id)


# ---------- 内置源（许可证人工核实，可扩展：在本文件末尾或调用方追加 register） ----------
_SOURCES = [
    # 维基百科（CC-BY-SA，稳定可下载，不反爬）
    ResourceSource("wiki_stock_zh", "维基百科 - 股票",
        "https://zh.wikipedia.org/wiki/股票",
        "html", "CC-BY-SA", "zh", ("fundamental",), "foreign"),
    ResourceSource("wiki_ta_zh", "维基百科 - 技术分析",
        "https://zh.wikipedia.org/wiki/技术分析",
        "html", "CC-BY-SA", "zh", ("technical",), "foreign"),
    ResourceSource("wiki_macro_zh", "维基百科 - 宏观经济学",
        "https://zh.wikipedia.org/wiki/宏观经济学",
        "html", "CC-BY-SA", "zh", ("macro",), "foreign"),
    ResourceSource("wiki_stock_en", "Wikipedia - Stock",
        "https://en.wikipedia.org/wiki/Stock",
        "html", "CC-BY-SA", "en", ("fundamental",), "foreign"),
    ResourceSource("wiki_ta_en", "Wikipedia - Technical analysis",
        "https://en.wikipedia.org/wiki/Technical_analysis",
        "html", "CC-BY-SA", "en", ("technical",), "foreign"),
    ResourceSource("wiki_macd_en", "Wikipedia - MACD",
        "https://en.wikipedia.org/wiki/MACD",
        "html", "CC-BY-SA", "en", ("technical",), "foreign"),
    ResourceSource("wiki_rsi_en", "Wikipedia - RSI",
        "https://en.wikipedia.org/wiki/Relative_strength_index",
        "html", "CC-BY-SA", "en", ("technical",), "foreign"),
    ResourceSource("wiki_risk_en", "Wikipedia - Risk management",
        "https://en.wikipedia.org/wiki/Risk_management",
        "html", "CC-BY-SA", "en", ("risk",), "foreign"),
    ResourceSource("imf_glossary", "IMF - 金融词汇表",
        "https://www.imf.org/external/pubs/ft/terms.htm",
        "html", "Educational Use", "en", ("macro", "fundamental"), "foreign"),
    ResourceSource("ecb_edu", "ECB - 货币政策教育",
        "https://www.ecb.europa.eu/ecb/educational/html/index.en.html",
        "html", "Educational Use", "en", ("macro",), "foreign"),
    ResourceSource("bis_investor", "BIS - 投资者教育",
        "https://www.bis.org/publ/educational.htm",
        "html", "Educational Use", "en", ("macro", "risk"), "foreign"),
    ResourceSource("csrc_risk_edu", "证监会 - 风险警示投教",
        "https://www.csrc.gov.cn/pub/newsite/tzzjy/tzzcs/tzfxsj/",
        "html", "Educational Use", "zh", ("risk",), "domestic"),
    ResourceSource("csc_sse_edu", "上交所 - 投资者教育",
        "https://edu.sse.com.cn/col/col5413/index.html",
        "html", "Educational Use", "zh", ("fundamental", "risk"), "domestic"),
]
for _s in _SOURCES:
    register(_s)


# ---------- 获取 ----------
def fetch(source_id: str, dest_dir: Path = CORPUS_DIR,
          progress_cb: Callable[[int, str], None] | None = None) -> tuple[bool, str, Path | None]:
    """下载原始文件到 dest_dir/{source_id}.{ext}。返回 (ok, msg, path)。"""
    src = get(source_id)
    if src is None:
        return False, f"未知资源源：{source_id}", None
    import requests

    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = "pdf" if src.kind == "pdf" else ("md" if src.kind == "markdown" else "html")
    out = dest_dir / f"{source_id}.{ext}"

    ctx = foreign_network if src.network == "foreign" else domestic_network
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        if progress_cb:
            progress_cb(0, f"下载 {src.name} …")
        with ctx():
            r = requests.get(src.url, headers=headers, timeout=30, stream=True)
            r.raise_for_status()
            n = 0
            with out.open("wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
                    n += len(chunk)
        if progress_cb:
            progress_cb(100, f"下载完成 {n} 字节")
        return True, f"下载成功（{n} 字节）", out
    except Exception as e:  # noqa: BLE001
        msg = f"下载失败 {src.name}: {type(e).__name__}: {e}"
        log.warning(msg)
        if progress_cb:
            progress_cb(-1, msg)
        return False, msg, None


# ---------- 解析 ----------
def parse_pdf(path: Path) -> str:
    try:
        import pdfplumber  # 可选依赖，缺失给清晰提示
    except ImportError as e:
        raise RuntimeError("PDF 解析需 pdfplumber，请在主 venv 执行：pip install pdfplumber") from e
    out: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            if t.strip():
                out.append(t)
    return "\n\n".join(out)


def parse_html(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    try:
        import trafilatura  # 可选，正文提取更好
        text = trafilatura.extract(raw, include_comments=False, include_tables=False) or ""
        if text.strip():
            return text
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        log.debug("trafilatura 解析失败，回退 bs4：%s", e)
    return _html_to_text_bs4(raw)


def _html_to_text_bs4(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()
    text = soup.get_text("\n")
    # 压缩连续空行
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return text


def parse_markdown(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    # 剥 YAML frontmatter
    m = re.match(r"^---\n.*?\n---\n", text, re.DOTALL)
    if m:
        text = text[m.end():]
    return text.strip()


def parse(path: Path, kind: str) -> str:
    if kind == "pdf":
        return parse_pdf(path)
    if kind == "html":
        return parse_html(path)
    if kind == "markdown":
        return parse_markdown(path)
    raise ValueError(f"不支持的类型：{kind}")


def fetch_and_parse(source_id: str, corpus_dir: Path = CORPUS_DIR,
                    progress_cb: Callable[[int, str], None] | None = None
                    ) -> tuple[bool, str, str]:
    """取+解析→ corpus_dir/{source_id}.txt（纯文本）。返回 (ok, msg, text)。"""
    src = get(source_id)
    if src is None:
        return False, f"未知资源源：{source_id}", ""
    ok, msg, raw_path = fetch(source_id, corpus_dir, progress_cb)
    if not ok:
        return False, msg, ""
    try:
        text = parse(raw_path, src.kind)
    except Exception as e:  # noqa: BLE001
        return False, f"解析失败 {src.name}: {type(e).__name__}: {e}", ""
    if not text.strip():
        return False, f"解析为空 {src.name}（可能为扫描版 PDF 或页面结构变化）", ""
    txt_path = corpus_dir / f"{source_id}.txt"
    txt_path.write_text(text, encoding="utf-8")
    # 清理原始文件
    try:
        raw_path.unlink()
    except Exception:  # noqa: BLE001
        pass
    if progress_cb:
        progress_cb(100, f"解析完成 {len(text)} 字符")
    return True, f"取解析成功（{len(text)} 字符）", text


def corpus_files(corpus_dir: Path = CORPUS_DIR) -> list[Path]:
    """列出已就绪的纯文本语料。"""
    if not corpus_dir.exists():
        return []
    return sorted(corpus_dir.glob("*.txt"))


def corpus_stats(corpus_dir: Path = CORPUS_DIR) -> dict:
    files = corpus_files(corpus_dir)
    total_chars = sum(f.stat().st_size for f in files)
    return {"files": len(files), "chars": total_chars,
            "ids": [f.stem for f in files]}
