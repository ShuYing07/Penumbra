# -*- coding: utf-8 -*-
"""全局配置：路径、.env、模型、代理，以及日志初始化。

设计原则：
- 所有路径基于项目根目录（本文件位于 core/config.py）；
- .env 只存本机敏感信息（API key），不进日志、不进打包；
- 国内源（akshare/sina/DeepSeek）强制直连；境外源（yfinance/google/coingecko）按需走代理；
- 中文 Windows 全程 UTF-8。
"""
from __future__ import annotations

import logging
import os
import sys
from contextlib import contextmanager
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

# 打包后（PyInstaller onedir）：优先把数据目录放 exe 旁边（便携式，可整目录拷贝）；
# 若 exe 目录不可写（如安装在 Program Files），自动回退到用户数据目录 %APPDATA%\ShuyingInsight。
if getattr(sys, "frozen", False):
    _exe_root = Path(sys.executable).resolve().parent
    _probe = _exe_root / "data"
    try:
        _probe.mkdir(parents=True, exist_ok=True)
        _w = _probe / ".w"
        _w.write_text("ok", encoding="utf-8")
        _w.unlink()
        PROJECT_ROOT = _exe_root
    except OSError:
        PROJECT_ROOT = (
            Path(os.environ.get("APPDATA", str(Path.home()))) / "ShuyingInsight")
else:
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
REPORT_DIR = DATA_DIR / "reports"
LOG_DIR = DATA_DIR / "logs"
DB_PATH = DATA_DIR / "stockai.db"
for _d in (DATA_DIR, REPORT_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DISCLAIMER = ("本工具仅用于数据分析和研究学习，不构成任何投资建议。"
              "本工具不提供证券投资咨询业务，未取得中国证监会证券投资咨询业务资格，"
              "不提供任何具体证券品种的分析意见、买卖建议或价格预测。"
              "所有结果均为客观历史数据展示，用户应自行判断并承担投资决策的全部风险。")

# ---------- .env ----------
def _load_dotenv() -> None:
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())

_load_dotenv()

# ---------- LLM ----------
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
# 现役模型（2026-09 核实）：deepseek-flash / deepseek-v4-pro；旧 deepseek-chat 已弃用
FAST_MODEL = os.environ.get("STOCKAI_FAST_MODEL", "deepseek-flash")
THINK_MODEL = os.environ.get("STOCKAI_THINK_MODEL", "deepseek-v4-pro")
TEMPERATURE = float(os.environ.get("STOCKAI_TEMPERATURE", "0.3"))
# STOCKAI_MOCK=1 时使用本地桩响应（不调用 API），用于无余额/离线时跑通管线
LLM_MOCK = os.environ.get("STOCKAI_MOCK", "0") == "1"

# ---------- 本地离线模型（Ollama + Qwen2.5）----------
# 引擎：deepseek(云端) | local(纯本地) | auto(云端失败自动切本地)
LLM_BACKEND = os.environ.get("STOCKAI_LLM_BACKEND", "deepseek").strip().lower()
LOCAL_OLLAMA_URL = os.environ.get("STOCKAI_LOCAL_URL", "http://localhost:11434").rstrip("/")
LOCAL_MODEL = os.environ.get("STOCKAI_LOCAL_MODEL", "qwen2.5:7b-instruct-q4_K_M")
LOCAL_MODEL_SMALL = os.environ.get("STOCKAI_LOCAL_MODEL_SMALL", "qwen2.5:3b-instruct-q4_K_M")

# 本地金融专用模型（可选）：MoziAI 等。Ollama 拉取的模型名。
OLLAMA_MODEL_NAME = os.environ.get("OLLAMA_MODEL_NAME", "moziAI:35b")
# 是否优先本地推理（true=优先本地，false=走 auto/云端）
LOCAL_AI_ENABLED = os.environ.get("LOCAL_AI_ENABLED", "false").strip().lower() == "true"
# llama-cpp-python 直读的 GGUF 模型文件路径（可选，空=不用此后端）
LOCAL_MODEL_PATH = os.environ.get("LOCAL_MODEL_PATH", "").strip()

# DeepSeek 每 1K tokens 人民币单价（2026-09 核实；高峰/空闲）
_PRICE_PER_1K = {
    "deepseek-flash": {"peak": (0.002, 0.008), "offpeak": (0.001, 0.004)},
    "deepseek-v4-pro": {"peak": (0.009, 0.027), "offpeak": (0.0045, 0.0135)},
}

# ---------- 代理 ----------
# 境外源默认走本机 Clash mixed 口；TUN 已开启时代理与直连均可，设置为 0 可关
PROXY_ENABLED = os.environ.get("STOCKAI_PROXY", "1") == "1"
PROXY_URL = os.environ.get("STOCKAI_PROXY_URL", "http://127.0.0.1:7897")

# ---------- 混合推理策略 ----------
# auto（按任务类型）| structured（确定性优先）| retrieval（检索增强优先）
REASONING_STRATEGY = os.environ.get("STOCKAI_REASONING_STRATEGY", "auto").strip().lower()

BEIJING_TZ = timezone(timedelta(hours=8))


def now_cn() -> datetime:
    return datetime.now(BEIJING_TZ)


def is_peak_hours(now: datetime | None = None) -> bool:
    """DeepSeek 高峰时段：北京时间周一至周五 9-12、14-18。"""
    now = now or now_cn()
    if now.weekday() >= 5:
        return False
    hm = now.hour
    return (9 <= hm < 12) or (14 <= hm < 18)


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    # 非 DeepSeek 端点（如通义千问免费额度）不在此计成本，避免按 DeepSeek 单价报假账
    if not model.startswith("deepseek"):
        return 0.0
    table = _PRICE_PER_1K.get(model, _PRICE_PER_1K["deepseek-flash"])
    pin, pout = table["peak" if is_peak_hours() else "offpeak"]
    return round(prompt_tokens * pin + completion_tokens * pout, 6)


# ---------- 代理上下文 ----------
_PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


@contextmanager
def foreign_network():
    """境外数据源上下文：按需注入 HTTP(S)_PROXY。"""
    saved = {k: os.environ.get(k) for k in _PROXY_KEYS}
    try:
        if PROXY_ENABLED:
            os.environ["HTTP_PROXY"] = PROXY_URL
            os.environ["HTTPS_PROXY"] = PROXY_URL
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextmanager
def domestic_network():
    """国内数据源上下文：绕过一切显式代理（TUN 透明接管不受影响）。"""
    saved = {k: os.environ.get(k) for k in _PROXY_KEYS}
    saved_no = os.environ.get("NO_PROXY")
    try:
        for k in _PROXY_KEYS:
            os.environ.pop(k, None)
        os.environ["NO_PROXY"] = "*"
        os.environ["no_proxy"] = "*"
        yield
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
        if saved_no is None:
            os.environ.pop("NO_PROXY", None)
            os.environ.pop("no_proxy", None)
        else:
            os.environ["NO_PROXY"] = saved_no


# ---------- 日志 ----------
def setup_logging() -> logging.Logger:
    logger = logging.getLogger("stockai")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    fh = logging.FileHandler(LOG_DIR / f"app_{now_cn():%Y%m%d}.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    if sys.stdout is not None:  # windowed 打包模式下 stdout 为 None，只留文件日志
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
    return logger


def ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


# ---------- 交易时段（盯盘用；粗略周一~五，不判断节假日）----------
def _nth_weekday(year: int, month: int, n: int, weekday: int) -> date:
    """该月第 n 个 weekday（0=周一..6=周日）。"""
    d = date(year, month, 1)
    days_ahead = (weekday - d.weekday()) % 7
    return d + timedelta(days=days_ahead + 7 * (n - 1))


def is_us_dst(now: datetime | None = None) -> bool:
    """美国夏令时（3 月第二周日 ~ 11 月第一周日），日期粒度。"""
    now = now or now_cn()
    y = now.year
    start = _nth_weekday(y, 3, 2, 6)   # 3 月第二周日
    end = _nth_weekday(y, 11, 1, 6)    # 11 月第一周日
    return start <= now.date() < end


def is_market_open(market: str, now: datetime | None = None) -> bool:
    """是否处于该市场交易时段（北京时间；粗略周一~五，不判断节假日）。

    - CN：周一~五 9:30-11:30 / 13:00-15:00
    - HK：周一~五 9:30-12:00 / 13:00-16:00（港股本地时间=北京时间）
    - US：周一~五；夏令时北京 21:30~次日 04:00，冬令时 22:30~次日 05:00
    - JP/KR/TW：本地 UTC+9/+9/+8，已折算为北京时间（见 MARKET_META）
    - CRYPTO：恒 True；其他（GLOBAL/UNKNOWN）：False
    """
    now = now or now_cn()
    wd = now.weekday()            # 0=周一..6=周日
    hm = now.hour * 60 + now.minute
    if market == "CRYPTO":
        return True
    if market == "CN":
        if wd >= 5:
            return False
        return (570 <= hm < 690) or (780 <= hm < 900)   # 9:30-11:30 / 13:00-15:00
    if market == "HK":
        if wd >= 5:
            return False
        return (570 <= hm < 720) or (780 <= hm < 960)   # 9:30-12:00 / 13:00-16:00
    if market == "US":
        dst = is_us_dst(now)
        open_min = 1290 if dst else 1350     # 21:30 / 22:30
        close_min = 240 if dst else 300      # 04:00 / 05:00
        if hm >= open_min:
            return wd < 5                     # 晚间段：当日须工作日
        if hm < close_min:
            return (wd - 1) % 7 < 5           # 凌晨段：前一日须工作日
        return False
    if market in ("JP", "KR", "TW"):
        # 本地交易时段已折算为北京时间（MARKET_META 内 sip 字段）
        sess = MARKET_META[market]["sessions_bj"]
        if wd >= 5:
            return False
        return any(a <= hm < b for a, b in sess)
    return False


# ---------------------------------------------------------------------------
# 市场注册表（任务书B·模块二：日股/韩股数据源支持评估）
# 时区与交易时段统一折算为北京时间（hm = 时*60+分），便于 is_market_open 单一口径。
# 数据来源：JP/KR/TW/HK/US/GLOBAL 均走 yfinance 全球源（免费、覆盖最广）；
# 若后续需更高频/更深历史，可在此登记付费备源（如 JPX、KRX、TWSE 官方）。
# ---------------------------------------------------------------------------
MARKET_META: dict[str, dict] = {
    "CN": {"name_zh": "A股", "name_en": "China A", "currency": "CNY",
           "tz": "Asia/Shanghai", "code_fmt": "SH600519 / SZ000001",
           "sessions_bj": [(570, 690), (780, 900)]},
    "HK": {"name_zh": "港股", "name_en": "Hong Kong", "currency": "HKD",
           "tz": "Asia/Hong_Kong", "code_fmt": "0700.HK / 00700.HK",
           "sessions_bj": [(570, 720), (780, 960)]},
    "US": {"name_zh": "美股", "name_en": "US", "currency": "USD",
           "tz": "America/New_York", "code_fmt": "AAPL / MSFT",
           "sessions_bj": [(1290, 1440), (0, 300)]},
    "JP": {"name_zh": "日股", "name_en": "Japan (TSE)", "currency": "JPY",
           "tz": "Asia/Tokyo", "code_fmt": "7203.T（丰田）/ 6758.T（索尼）",
           # 东京 09:00-11:30 / 12:30-15:00 JST = 北京 08:00-10:30 / 11:30-14:00
           "sessions_bj": [(480, 630), (690, 840)]},
    "KR": {"name_zh": "韩股", "name_en": "Korea (KRX)", "currency": "KRW",
           "tz": "Asia/Seoul", "code_fmt": "005930.KS（三星）/ 000660.KS（海力士）",
           # 首尔 09:00-15:30 KST = 北京 08:00-14:30（连续交易，无午休）
           "sessions_bj": [(480, 870)]},
    "TW": {"name_zh": "台股", "name_en": "Taiwan (TWSE)", "currency": "TWD",
           "tz": "Asia/Taipei", "code_fmt": "2330.TW（台积电）",
           # 台北 09:00-13:30 = 北京 09:00-13:30（UTC+8 同）
           "sessions_bj": [(540, 810)]},
    "GLOBAL": {"name_zh": "全球(其它)", "name_en": "Global", "currency": "USD",
               "tz": "UTC", "code_fmt": "<code>.<EXCH>",
               "sessions_bj": []},
    "CRYPTO": {"name_zh": "加密货币", "name_en": "Crypto", "currency": "USD",
               "tz": "UTC", "code_fmt": "BTC-USD / ETH-USD",
               "sessions_bj": [(0, 1440)]},
}


def market_meta(market: str) -> dict:
    """取市场元信息（无则回退 GLOBAL）。"""
    return MARKET_META.get(market, MARKET_META["GLOBAL"])



def refresh_interval(market: str, now: datetime | None = None) -> int:
    """盯盘刷新间隔（秒）：盘中 60，盘外/非交易日 300；加密恒 60。"""
    if market == "CRYPTO":
        return 60
    return 60 if is_market_open(market, now) else 300
