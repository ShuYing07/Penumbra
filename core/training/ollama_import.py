# -*- coding: utf-8 -*-
"""训练编排：调 venv_train 跑 LLaMA-Factory → 合并 → ollama create → 切模型。

本模块只做 subprocess 编排（不含 torch），进打包。
训练在独立 venv_train（Python 3.11）执行，不污染主 venv。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from core.config import LOCAL_MODEL, PROJECT_ROOT

log = logging.getLogger("stockai.ollama_import")

VENV_TRAIN_DEFAULT = PROJECT_ROOT / "venv_train"
TRAINING_OUTPUT = PROJECT_ROOT / "data" / "training" / "output"
MERGED_DIR = PROJECT_ROOT / "data" / "training" / "merged"
CONFIGS_DIR = PROJECT_ROOT / "training_configs"


def find_venv_train() -> Path | None:
    """定位 venv_train：.env STOCKAI_VENV_TRAIN 优先，否则默认路径+存在性。"""
    env_path = os.environ.get("STOCKAI_VENV_TRAIN", "").strip()
    if env_path:
        p = Path(env_path)
        return p if p.exists() else None
    return VENV_TRAIN_DEFAULT if VENV_TRAIN_DEFAULT.exists() else None


def _lf_cli(venv: Path) -> Path:
    return venv / "Scripts" / "llamafactory-cli.exe"


def _ollama_exe() -> str | None:
    """定位 ollama 可执行文件：PATH 优先，回退常见 Windows 安装路径。"""
    exe = shutil.which("ollama")
    if exe:
        return exe
    for p in (
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"),
        r"C:\Program Files\Ollama\ollama.exe",
        r"C:\Program Files (x86)\Ollama\ollama.exe",
    ):
        if os.path.isfile(p):
            return p
    return None


def stop_local_model(model: str | None = None) -> tuple[bool, str]:
    """训练前释放 Ollama 驻留模型显存。"""
    exe = _ollama_exe()
    if not exe:
        return False, "未找到 ollama 命令（不在 PATH）"
    target = model or os.environ.get("STOCKAI_LOCAL_MODEL", LOCAL_MODEL)
    try:
        subprocess.run([exe, "stop", target], timeout=30,
                       capture_output=True, text=True)
        return True, f"已释放 {target} 显存"
    except Exception as e:  # noqa: BLE001
        return False, f"stop 失败：{e}"


def run_training(yaml_path: Path, venv: Path,
                 on_line: Callable[[str], None] | None = None,
                 stop_check: Callable[[], bool] | None = None) -> int:
    """流式跑 llamafactory-cli train。返回退出码。"""
    cli = _lf_cli(venv)
    if not cli.exists():
        raise FileNotFoundError(f"llamafactory-cli 不存在：{cli}（先跑 bootstrap_venv_train.ps1）")
    env = os.environ.copy()
    env["HF_ENDPOINT"] = "https://hf-mirror.com"
    cmd = [str(cli), "train", str(yaml_path)]
    log.info("训练启动：%s", " ".join(cmd))
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=str(PROJECT_ROOT), env=env,
        encoding="utf-8", errors="replace", bufsize=1, text=True)
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            if on_line:
                on_line(line)
            log.info("[lf] %s", line)
        if stop_check and stop_check():
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                proc.kill()
            if on_line:
                on_line("[已停止]")
            return -1
    return proc.wait()


def merge_lora(merge_yaml: Path, venv: Path,
               on_line: Callable[[str], None] | None = None) -> tuple[bool, str, Path | None]:
    """合并 LoRA adapter 到 fp16 基座 → MERGED_DIR。"""
    cli = _lf_cli(venv)
    if not cli.exists():
        return False, f"llamafactory-cli 不存在：{cli}", None
    env = os.environ.copy()
    env["HF_ENDPOINT"] = "https://hf-mirror.com"
    env["HF_LOW_CPU_MEM_USAGE"] = "1"
    cmd = [str(cli), "export", str(merge_yaml)]
    log.info("合并启动：%s", " ".join(cmd))
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=str(PROJECT_ROOT), env=env,
        encoding="utf-8", errors="replace", bufsize=1, text=True)
    assert proc.stdout is not None
    for line in proc.stdout:
        if on_line:
            on_line(line.rstrip())
    rc = proc.wait()
    if rc == 0 and MERGED_DIR.exists():
        return True, f"合并完成 → {MERGED_DIR}", MERGED_DIR
    return False, f"合并不成功（退出码 {rc}）", None


def ollama_create(model_name: str, modelfile: Path,
                  on_line: Callable[[str], None] | None = None) -> tuple[bool, str]:
    """用 Modelfile 导入到 Ollama。"""
    exe = _ollama_exe()
    if not exe:
        return False, "未找到 ollama 命令（不在 PATH），请确认 Ollama 已安装"
    if not modelfile.exists():
        return False, f"Modelfile 不存在：{modelfile}"
    cmd = [exe, "create", model_name, "-f", str(modelfile)]
    log.info("ollama create：%s", " ".join(cmd))
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", bufsize=1, text=True)
    assert proc.stdout is not None
    for line in proc.stdout:
        if on_line:
            on_line(line.rstrip())
    rc = proc.wait()
    if rc == 0:
        return True, f"已导入 Ollama：{model_name}"
    return False, f"ollama create 失败（退出码 {rc}）"


def set_local_model(model_name: str, persist: bool = True) -> None:
    """设为本地学生模型：os.environ 即时生效；persist 改写 .env。"""
    os.environ["STOCKAI_LOCAL_MODEL"] = model_name
    if not persist:
        return
    env_file = PROJECT_ROOT / ".env"
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    found = False
    for i, l in enumerate(lines):
        if l.strip().startswith("STOCKAI_LOCAL_MODEL="):
            lines[i] = f"STOCKAI_LOCAL_MODEL={model_name}"
            found = True
            break
    if not found:
        lines.append(f"STOCKAI_LOCAL_MODEL={model_name}")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
