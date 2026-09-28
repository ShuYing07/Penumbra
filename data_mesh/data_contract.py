# -*- coding: utf-8 -*-
"""Data Mesh：数据契约（Data Contract）——字段格式、质量要求、SLA 校验。

契约 = {fields:{name:type}, required:[...], quality:{freshness_sec, min_rows},
        sla_seconds}。validate(record) 做类型与必填校验（行级）；
validate_batch(records) 返回通过率与违规明细。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, date

_TYPES = {"str": str, "float": (int, float), "int": int,
          "date": (datetime, date), "datetime": (datetime, date)}


class DataContract:
    def __init__(self, name: str, fields: dict, required: list[str],
                 quality: dict | None = None, sla_seconds: int = 300):
        self.name = name
        self.fields = fields
        self.required = required
        self.quality = quality or {}
        self.sla_seconds = sla_seconds

    def validate(self, record: dict) -> list[str]:
        """行级校验，返回违规列表（空=通过）。"""
        violations = []
        for f in self.required:
            if f not in record or record[f] in (None, ""):
                violations.append(f"缺少必填字段: {f}")
        for f, t in self.fields.items():
            if f in record and record[f] not in (None, ""):
                if not isinstance(record[f], _TYPES.get(t, object)):
                    violations.append(f"字段 {f} 类型应为 {t}")
        return violations

    def validate_batch(self, records: list[dict]) -> dict:
        """批量校验：返回 {pass_rate, total, ok, violations:[{idx, errs}]}。"""
        total = len(records)
        ok = 0
        violations = []
        for i, r in enumerate(records):
            errs = self.validate(r)
            if errs:
                violations.append({"idx": i, "errs": errs})
            else:
                ok += 1
        return {"pass_rate": round(ok / total, 3) if total else 1.0,
                "total": total, "ok": ok, "violations": violations}

    def freshness_ok(self, last_updated: float) -> bool:
        max_sec = self.quality.get("freshness_sec", 300)
        return (time.time() - last_updated) <= max_sec

    def to_dict(self) -> dict:
        return {"name": self.name, "fields": self.fields,
                "required": self.required, "quality": self.quality,
                "sla_seconds": self.sla_seconds}


def from_dict(d: dict) -> "DataContract":
    return DataContract(d["name"], d["fields"], d.get("required", []),
                        d.get("quality"), d.get("sla_seconds", 300))
