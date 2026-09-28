# -*- coding: utf-8 -*-
"""国际化数据源适配器：统一接口 + 注册表 + 动态切换。

- base_adapter：DataAdapter 基类（能力声明 + 统一方法 + 健康检查）；
- bloomberg / lseg / wind：企业数据源适配（未配置凭据时健康状态 degraded，
  给出明确配置指引，不崩溃）；
- 注册表：内置 akshare / yfinance 适配器可注册，支持按名称动态切换。
"""
from data_adapters.base_adapter import DataAdapter, Capabilities
from data_adapters.registry import AdapterRegistry, get_registry, switch_source
from data_adapters.bloomberg_adapter import BloombergAdapter
from data_adapters.lseg_adapter import LSEGAdapter
from data_adapters.wind_adapter import WindAdapter

__all__ = [
    "DataAdapter", "Capabilities",
    "AdapterRegistry", "get_registry", "switch_source",
    "BloombergAdapter", "LSEGAdapter", "WindAdapter",
]
