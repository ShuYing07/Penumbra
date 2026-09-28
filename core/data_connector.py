# -*- coding: utf-8 -*-
"""数据集成（企业版模块五）：CSV/Excel 导入 + 外部数据库连接。

- parse_csv / parse_excel : 自动解析为标准化 OHLCV 表（可接入回测/分析）；
- connect_postgres / connect_mysql : 外部数据库连接（需手动安装驱动；
  psycopg2-binary / pymysql，未安装时给出明确提示）；
- 统一返回 pandas DataFrame，与既有 core/data/service 的数据口径一致。
"""
from __future__ import annotations

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
