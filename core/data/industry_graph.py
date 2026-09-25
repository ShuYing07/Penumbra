# -*- coding: utf-8 -*-
"""产业概念图谱：本地 SQLite 缓存 + 东方财富概念板块（HTTP:80 直连）。

为何不用 akshare：本机 TUN/Clash 环境下 push2.eastmoney.com 的 HTTPS:443 持续被断，
而 HTTP:80 正常；akshare 内部写死 https，故这里直接用 requests 走 80 端口。

数据：
- 概念列表  fs=m:90 t:3   字段 f12=板块代码(BKxxxx), f14=概念名
- 成分股    fs=b:BKxxxx   字段 f12=股票代码,       f14=股票名
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from typing import Dict, List

import requests

from core.config import DATA_DIR, domestic_network

log = logging.getLogger("stockai.data.industry")

DB_PATH = os.path.join(DATA_DIR, "concept_graph.db")
CACHE_HOURS = 24
_API = "http://push2.eastmoney.com/api/qt/clist/get"
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _get(fs: str, pz: int = 200) -> List[Dict[str, str]]:
    """分页拉取东财 clist，返回 [{code,name}]。含重试退避（本机网络偶发断连）。"""
    out: List[Dict[str, str]] = []
    pn = 1
    while True:
        params = {
            "pn": pn, "pz": pz, "po": 1, "np": 1,
            "fltt": 2, "invt": 2, "fid": "f3",
            "fs": fs, "fields": "f12,f14",
        }
        diff = None
        for attempt in range(4):
            try:
                with domestic_network():
                    r = requests.get(_API, params=params, headers=_HEADERS, timeout=15)
                data = (r.json().get("data") or {})
                diff = data.get("diff") or []
                break
            except Exception as e:  # noqa: BLE001
                log.warning("东财请求失败(第%d次): %s", attempt + 1, e)
                time.sleep(1.5 * (attempt + 1))
        if diff is None:
            raise ConnectionError(f"东财概念接口多次重试仍失败: {fs}")
        if not diff:
            break
        for it in diff:
            out.append({"code": str(it.get("f12", "")), "name": str(it.get("f14", ""))})
        if len(diff) < pz:
            break
        pn += 1
        time.sleep(0.3)  # 翻页限速
        if pn > 50:
            break
    return out


def _conn() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute(
        """CREATE TABLE IF NOT EXISTS concepts (
               concept_name TEXT, stock_code TEXT, stock_name TEXT, updated_at REAL)"""
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_stock ON concepts(stock_code)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_concept ON concepts(concept_name)")
    return c


def _cache_fresh(c: sqlite3.Connection) -> bool:
    row = c.execute("SELECT MAX(updated_at) FROM concepts").fetchone()
    return bool(row and row[0] and (time.time() - float(row[0])) < CACHE_HOURS * 3600)


def fetch_concept_list() -> List[Dict[str, str]]:
    """全部概念板块 [{code(BKxxxx), name}]。"""
    return _get("m:90 t:3")


def fetch_concept_stocks(bk_code: str) -> List[Dict[str, str]]:
    """某概念成分股。bk_code 如 BK0976。"""
    return _get(f"b:{bk_code}")


def build_full_graph() -> int:
    """全量建立 概念->股票 映射。慢，需后台线程。返回行数。"""
    concepts = fetch_concept_list()
    rows = []
    for i, c in enumerate(concepts):
        try:
            cons = fetch_concept_stocks(c["code"])
            for s in cons:
                rows.append((c["name"], s["code"], s["name"]))
        except Exception as e:  # noqa: BLE001
            log.warning("概念 %s 成分股失败: %s", c["name"], e)
        if i % 50 == 0:
            log.info("概念图谱构建 %d/%d", i, len(concepts))
    c = _conn()
    now = time.time()
    c.execute("DELETE FROM concepts")
    c.executemany(
        "INSERT INTO concepts VALUES(?,?,?,?)",
        [(a, b, n, now) for a, b, n in rows],
    )
    c.commit(); c.close()
    return len(rows)


def get_stocks_by_concept(concept_name: str) -> List[Dict[str, str]]:
    """按概念名查股票。先查库，未命中则实时拉。"""
    c = _conn()
    if _cache_fresh(c):
        rows = c.execute(
            "SELECT stock_code,stock_name FROM concepts WHERE concept_name=?",
            (concept_name,),
        ).fetchall()
        if rows:
            c.close()
            return [{"code": a, "name": b} for a, b in rows]
    c.close()
    # 库内无该概念：需要先找到它的 BK 代码
    bk = None
    for cc in fetch_concept_list():
        if cc["name"] == concept_name:
            bk = cc["code"]; break
    if not bk:
        return []
    out = fetch_concept_stocks(bk)
    cc = _conn(); now = time.time()
    cc.executemany(
        "INSERT INTO concepts VALUES(?,?,?,?)",
        [(concept_name, o["code"], o["name"], now) for o in out],
    )
    cc.commit(); cc.close()
    return out


def get_concepts_by_stock(stock_code: str) -> List[str]:
    """按股票反查概念。依赖全量库。"""
    code = stock_code.strip().upper()
    if code.startswith(("SH", "SZ")):
        code = code[2:]
    c = _conn()
    cnt = c.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
    rows = c.execute(
        "SELECT DISTINCT concept_name FROM concepts WHERE stock_code=?", (code,)
    ).fetchall()
    c.close()
    if cnt == 0:
        return []
    return sorted({r[0] for r in rows})


_graph_lock = threading.Lock()


def build_full_graph_async(on_done=None):
    def _run():
        if not _graph_lock.acquire(blocking=False):
            return
        try:
            n = build_full_graph()
            if on_done: on_done(n)
        except Exception as e:  # noqa: BLE001
            log.error("概念图谱构建失败: %s", e)
            if on_done: on_done(-1)
        finally:
            _graph_lock.release()
    threading.Thread(target=_run, daemon=True).start()
