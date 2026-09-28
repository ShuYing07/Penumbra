# -*- coding: utf-8 -*-
"""实时数据架构升级：轻量事务湖仓 + 流式处理 + Sidecar 行情网关。

- 事务湖仓：以 SQLite 快照表实现 Iceberg 语义（ACID 事务、版本快照、时间旅行），
  统一收纳结构化行情 / 半结构化评级 / 非结构化新闻；pyiceberg 可用时可选启用。
- 流式处理：窗口计算 + 背压 + 批处理；Flink/Spark 为可选适配桩（未装自动降级）。
- Sidecar 网关：定义外部行情进程协议（JSON over stdio/ZeroMQ），Python 侧消费。

原则：所有重型外部依赖（pyiceberg/pyspark/flink/ZeroMQ）均为"可选增强"，
未安装时以内置实现运行并给出明确提示，不阻塞主程序。
"""
from data_pipeline.lakehouse import Lakehouse, LakehouseError
from data_pipeline.stream_processor import StreamProcessor, window_mean, backpressure_guard
from data_pipeline.sidecar_gateway import SidecarGateway, TickMessage

__all__ = [
    "Lakehouse", "LakehouseError",
    "StreamProcessor", "window_mean", "backpressure_guard",
    "SidecarGateway", "TickMessage",
]
