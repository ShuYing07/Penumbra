# -*- coding: utf-8 -*-
"""Token 消耗与成本追踪（SQLite 持久化，支持预算与年度合同承诺）。

- 记录每次调用：model / tokens_in / tokens_out / 单价 / 成本；
- 支持预算检查（单次/月度/年度承诺）；
- 成本单价可配置（每百万 token 元），默认给出常见模型档位。
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path

log = logging.getLogger("stockai.sovereign.cost")

# 默认单价（元 / 百万 token）：{model_prefix: (in, out)}
_DEFAULT_PRICES = {
    "deepseek-chat": (1.0, 2.0),
    "deepseek-reasoner": (2.0, 8.0),
    "qwen": (0.5, 1.5),
    "glm": (0.8, 2.0),
    "gpt-4o": (15.0, 60.0),
    "local": (0.0, 0.0),
}


class CostTracker:
    """成本追踪器。"""

    def __init__(self, db_path: str | Path | None = None,
                 annual_commitment: float = 0.0):
        self._lock = threading.Lock()
        self.annual_commitment = annual_commitment
        db_path = db_path or str(Path.cwd() / "data" / "cost_tracker.db")
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("CREATE TABLE IF NOT EXISTS cost_log("
                           "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                           "ts REAL, model TEXT, tokens_in INTEGER, tokens_out INTEGER,"
                           "cost REAL, note TEXT)")
        self._conn.commit()

    def price_for(self, model: str) -> tuple[float, float]:
        for prefix, p in _DEFAULT_PRICES.items():
            if model and prefix.lower() in model.lower():
                return p
        return (1.0, 2.0)

    def track(self, model: str, tokens_in: int, tokens_out: int,
              note: str = "") -> dict:
        """记录一次调用并计算成本。"""
        pin, pout = self.price_for(model)
        cost = (tokens_in / 1e6) * pin + (tokens_out / 1e6) * pout
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO cost_log(ts,model,tokens_in,tokens_out,cost,note)"
                    " VALUES(?,?,?,?,?,?)",
                    (time.time(), model, int(tokens_in), int(tokens_out),
                     round(cost, 6), note))
        return {"model": model, "tokens_in": tokens_in, "tokens_out": tokens_out,
                "cost": round(cost, 6)}

    def summary(self, since_ts: float = 0.0) -> dict:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(tokens_in),0), COALESCE(SUM(tokens_out),0),"
                " COALESCE(SUM(cost),0), COUNT(*) FROM cost_log WHERE ts>=?",
                (since_ts,)).fetchone()
        tin, tout, cost, n = row
        return {"tokens_in": int(tin), "tokens_out": int(tout),
                "cost": round(cost, 4), "calls": int(n)}

    def budget_check(self, monthly_budget: float = 100.0) -> dict:
        """月度预算检查（自然月窗口）。"""
        month_start = time.mktime(time.localtime(time.time())[:3] + (0, 0, 0, 0, 0, -1))
        s = self.summary(since_ts=month_start)
        return {"month_cost": s["cost"], "budget": monthly_budget,
                "over": s["cost"] > monthly_budget,
                "remaining": round(monthly_budget - s["cost"], 4)}

    def commitment_check(self) -> dict:
        """年度合同承诺检查（累计成本 vs 承诺额）。"""
        s = self.summary()
        return {"year_cost": s["cost"], "commitment": self.annual_commitment,
                "remaining": round(self.annual_commitment - s["cost"], 4),
                "over": self.annual_commitment > 0 and s["cost"] > self.annual_commitment}

    def export(self, path: str | None = None) -> str:
        """导出为 CSV（JSON 兼容导出可转用 summary）。"""
        import csv
        path = path or str(Path.cwd() / "data" / "cost_export.csv")
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts,model,tokens_in,tokens_out,cost,note FROM cost_log "
                "ORDER BY id").fetchall()
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ts", "model", "tokens_in", "tokens_out", "cost", "note"])
            w.writerows(rows)
        return path

    def close(self) -> None:
        """关闭数据库连接（释放文件锁）。"""
        with self._lock:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    import os
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)                       # 立即释放句柄，避免 Windows 文件锁
    ct = CostTracker(db_path=tmp, annual_commitment=1000.0)
    ct.track("deepseek-chat", 100_000, 50_000)      # ~0.2 元
    ct.track("local", 500_000, 200_000)             # 0 元
    s = ct.summary()
    assert s["calls"] == 2 and s["cost"] > 0.1
    bc = ct.budget_check(monthly_budget=0.1)
    assert bc["over"] is True
    cc = ct.commitment_check()
    assert cc["remaining"] > 900
    p = ct.export()
    assert os.path.exists(p)
    ct.close()                        # 关闭连接再删文件
    os.unlink(tmp)
    print(f"PASS cost_tracker 自测 calls={s['calls']} cost={s['cost']} export={p}")
