# -*- coding: utf-8 -*-
"""数据集成（企业版模块五）：CSV/Excel 导入 + 外部数据库连接。

- parse_csv / parse_excel : 自动解析为标准化 OHLCV 表（可接入回测/分析）；
- connect_postgres / connect_mysql : 外部数据库连接（需手动安装驱动；
  psycopg2-binary / pymysql，未安装时给出明确提示）；
- 统一返回 pandas DataFrame，与既有 core/data/service 的数据口径一致。
"""
from __future__ import annotations

import io
import logging
import sqlite3
from pathlib import Path

import pandas as pd

log = logging.getLogger("stockai.connector")

_REQUIRED_COLS = ["date", "open", "high", "low", "close"]
_ALIASES = {"日期": "date", "开盘": "open", "最高": "high",
            "最低": "low", "收盘": "close", "成交量": "volume"}


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """列名中英映射 + 日期排序 + 数值化。"""
    df = df.rename(columns=_ALIASES)
    missing = [c for c in _REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"缺少必需列: {missing}（需要 {_REQUIRED_COLS}）")
    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    if "volume" not in df.columns:
        df["volume"] = 0
    # 与 core/data/service 口径一致：date 作 index
    return df.set_index("date")[["open", "high", "low", "close", "volume"]]


def parse_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    return _normalize(df)


def parse_excel(path: str | Path, sheet: str | int = 0) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=sheet)
    return _normalize(df)


def parse_clipboard_table(text: str) -> pd.DataFrame:
    """解析剪贴板表格文本为标准化 OHLCV。

    自动检测分隔符：制表符（Excel 复制）→ TSV；否则逗号（CSV）；否则连续空白。
    自动判断首行是否为表头（中英表头识别；否则按位置赋列 date/open/high/low/close/volume）。
    空内容 / 无有效数据行 → 抛 ValueError。
    """
    if text is None or not str(text).strip():
        raise ValueError("剪贴板内容为空")
    lines = [ln for ln in str(text).strip().splitlines() if ln.strip()]
    if not lines:
        raise ValueError("剪贴板无有效数据行")
    sample = lines[0]
    if "\t" in sample:
        sep = "\t"
    elif "," in sample and sample.count(",") >= sample.count(" "):
        sep = ","
    else:
        sep = r"\s+"

    _HEADER_NAMES = set(_REQUIRED_COLS) | set(_ALIASES) | {"date", "open"}

    try:
        df = pd.read_csv(io.StringIO(str(text).strip()), sep=sep,
                         engine="python", header=None)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"剪贴板解析失败：{type(e).__name__}: {e}")
    if df.empty:
        raise ValueError("剪贴板解析后无数据")

    # 首行若为表头（含日期/OHLCV 中英列名）→ 作为列名并下移
    first_cells = [str(c).strip().lower() for c in df.iloc[0].tolist()]
    has_header = bool(set(first_cells) & _HEADER_NAMES)
    if has_header:
        df.columns = [str(c).strip() for c in df.iloc[0].tolist()]
        df = df.iloc[1:].reset_index(drop=True)
    else:
        # 无表头：按位置赋列
        ncol = df.shape[1]
        if ncol < 5:
            raise ValueError(f"列数不足：期望≥5（date,open,high,low,close），实际 {ncol}")
        pos = ["date", "open", "high", "low", "close", "volume"]
        df.columns = pos[:ncol]

    return _normalize(df)


def parse_image_ohlcv(image_path: str, extractor=None) -> pd.DataFrame:
    """从行情/表格截图导入 OHLCV。

    extractor(image_path) -> str：视觉模型把图内表格转成 CSV 文本；
    缺省走 core.multimodal_parser.extract_image_table（视觉 LLM 优先，离线返回空）。
    提取出的 CSV 再交给 parse_clipboard_table 标准化为 OHLCV。
    """
    if extractor is None:
        from core.multimodal_parser import extract_image_table
        extractor = extract_image_table
    csv_text = extractor(image_path)
    if not csv_text or not csv_text.strip():
        raise ValueError("图片未解析出表格数据（需含 OHLCV 表格的截图；"
                         "或改用 CSV / 剪贴板导入）")
    return parse_clipboard_table(csv_text)


def import_to_cache(df: pd.DataFrame, ticker: str) -> int:
    """把外部数据导入本地 SQLite 行情缓存（供回测/分析直接使用）。"""
    from core.data import cache

    cache.upsert_bars(ticker, df, source="external")
    return len(df)


# ---------------------------------------------------------------- 外部数据库

def connect_postgres(host: str, port: int, database: str, user: str,
                     password: str) -> object:
    """连接 PostgreSQL（需手动安装 psycopg2-binary）。返回连接对象。"""
    try:
        import psycopg2  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "缺少驱动 psycopg2-binary，请手动安装：pip install psycopg2-binary")
    import psycopg2

    return psycopg2.connect(host=host, port=port, database=database,
                            user=user, password=password)


def connect_mysql(host: str, port: int, database: str, user: str,
                  password: str) -> object:
    """连接 MySQL（需手动安装 pymysql）。返回连接对象。"""
    try:
        import pymysql  # noqa: F401
    except ImportError:
        raise RuntimeError("缺少驱动 pymysql，请手动安装：pip install pymysql")
    import pymysql

    return pymysql.connect(host=host, port=port, database=database,
                           user=user, password=password, charset="utf8mb4")


def query_external(conn: object, sql: str) -> pd.DataFrame:
    """在外部连接上执行只读查询，返回 DataFrame。"""
    cur = conn.cursor()
    try:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        return pd.DataFrame(rows, columns=cols)
    finally:
        cur.close()
