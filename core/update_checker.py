# -*- coding: utf-8 -*-
"""自动更新检查（模块六）。

- 后台线程请求 GitHub Releases API（标准库 urllib，5 秒超时，静默失败）。
- 仅提示、绝不自动下载/替换；发现新版本时通过回调通知 UI。
- 启动时自动调用一次；用户也可在「帮助 → 检查更新」手动触发（已有）。
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

log = logging.getLogger("stockai.update")


def check_updates_async(on_result: Optional[Callable[[dict], None]] = None,
                        on_error: Optional[Callable[[str], None]] = None) -> None:
    """后台异步检查更新。on_result(res) / on_error(err) 在后台线程回调。"""
    def _work() -> None:
        try:
            from config_manager import check_update
            res = check_update(timeout=5.0)
            if on_result:
                on_result(res)
        except Exception as e:  # noqa: BLE001
            log.debug("更新检查失败: %s", e)
            if on_error:
                on_error(f"{type(e).__name__}: {e}")

    threading.Thread(target=_work, daemon=True, name="update-checker").start()


if __name__ == "__main__":
    import time

    def _res(res):
        print("更新检查结果:", res.get("has_update"), res.get("latest"))

    check_updates_async(on_result=_res)
    time.sleep(7)
    print("done")
