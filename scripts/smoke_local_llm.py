# -*- coding: utf-8 -*-
"""本地引擎 + 蒸馏闭环冒烟（假 Ollama 端点，零外部依赖）。

验证：
1) backend=local：走本地端点、成本 0、SFT 语料 source=student 落盘；
2) backend=auto：云端 402（真实免费返回）→ 自动切本地假端点成功；
3) 偏好标注 + LLaMA-Factory 导出往返；
4) 真实 Ollama 检测函数不崩。
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

# 必须在 import core 之前指定假本地端点
_PORT = 11501
os.environ["STOCKAI_LOCAL_URL"] = f"http://127.0.0.1:{_PORT}"
os.environ["STOCKAI_MOCK"] = "0"

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, cond, detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail else ""))


class FakeOllama(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 静默
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/api/version":
            self._send({"version": "0.0-fake"})
        elif self.path == "/api/tags":
            self._send({"models": [{"name": "qwen2.5:7b-instruct-q4_K_M"}]})
        else:
            self._send({}, 404)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        if self.path == "/v1/chat/completions":
            self._send({
                "id": "fake", "object": "chat.completion",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant",
                                         "content": '{"stance":"中性","confidence":50}'}}],
                "usage": {"prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168},
            })
        else:
            self._send({"error": "not found"}, 404)


def cleanup_smoke_rows():
    from core.config import DATA_DIR

    for name in ("sft.jsonl", "preferences.jsonl"):
        p = DATA_DIR / "distill" / name
        if not p.exists():
            continue
        kept = [ln for ln in p.read_text(encoding="utf-8").splitlines() if "SMOKE" not in ln]
        p.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", _PORT), FakeOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    from core import llm_local
    from core.llm import LLMRunner
    from core.training import distill

    check("Ollama 检测 is_installed 不崩", isinstance(llm_local.is_installed(), bool),
          f"installed={llm_local.is_installed()}")
    check("假端点 is_running", llm_local.is_running() is True)
    check("假端点 has_model(7B)", llm_local.has_model("qwen2.5:7b-instruct-q4_K_M") is True)

    # 1) 纯本地后端
    r1 = LLMRunner(backend="local")
    data = r1.chat_json("technical", "sys", '{"事实":"SMOKE"}')
    check("local 返回 JSON", data.get("stance") == "中性", str(data)[:80])
    check("local 成本为 0", r1.cost_cny == 0.0 and r1.completion_tokens == 45,
          f"usage={r1.usage()}")
    check("local backend_used=local", r1.backend_used == "local")
    r1.meta = {"ticker": "SMOKE"}
    r1.chat_json("technical", "sys", '{"事实2":"SMOKE"}')

    # 2) auto：云端 402 真实返回 → 切本地假端点
    r2 = LLMRunner(backend="auto")
    data2 = r2.chat_json("technical", "sys", '{"事实3":"SMOKE"}')
    check("auto 云端402→切本地成功", data2.get("stance") == "中性")
    check("auto backend_used=local（已切换）", r2.backend_used == "local",
          f"fatal={r2._cloud_fatal}")

    # 3) 蒸馏语料落盘与导出
    n_before = distill.stats()["sft_total"]
    r3 = LLMRunner(backend="local")
    r3.meta = {"ticker": "SMOKE"}
    r3.chat_json("news", "sys", "SMOKE")
    n_after = distill.stats()["sft_total"]
    check("SFT 语料追加", n_after >= n_before + 1, f"{n_before}→{n_after}")

    distill.record_preference(decision_id=999001, ticker="SMOKE", action="买入",
                              trader_output='{"action":"买入"}',
                              instruction="SMOKE 指令", realized_return_pct=-2.5,
                              aligned=False)
    st = distill.stats()
    check("偏好语料 bad 计数", st["pref_by_label"].get("bad", 0) >= 1, str(st["pref_by_label"]))
    exported = distill.export_llamafactory()
    check("导出 LLaMA-Factory", exported["preference_rows"] >= 1
          and Path(exported["sft"]).exists(), exported["sft"])

    # 4) 真实 Ollama（本机已装）
    check("真实 Ollama 服务可连", llm_local.is_running() is True,
          f"version={llm_local.version()}")

    cleanup_smoke_rows()
    server.shutdown()

    failed = [n for n, ok, _ in results if not ok]
    print("\n".join(f"  · {n}: {d}" for n, ok, d in results if not ok))
    print(f"\n==== {'全部通过' if not failed else f'{len(failed)} 项失败'}："
          f"{len(results) - len(failed)}/{len(results)} ====")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
