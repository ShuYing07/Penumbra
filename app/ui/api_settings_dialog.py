# -*- coding: utf-8 -*-
"""多渠道API设置对话框：支持多个AI厂商，类似Cline的API配置。"""
from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QTabWidget,
                             QVBoxLayout, QWidget)

ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env"

# 支持的厂商预设
PRESETS = {
    "DeepSeek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "key_var": "DEEPSEEK_API_KEY",
        "apply_var": "DEEPSEEK_BASE_URL",
        "apply_value": "https://api.deepseek.com",
    },
    "通义千问(阿里百炼)": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-max",
        "key_var": "DASHSCOPE_API_KEY",
        "apply_var": "DEEPSEEK_BASE_URL",
        "apply_value": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    "智谱GLM": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "key_var": "GLM_API_KEY",
        "apply_var": "DEEPSEEK_BASE_URL",
        "apply_value": "https://open.bigmodel.cn/api/paas/v4",
    },
    "硅基流动": {
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "deepseek-ai/DeepSeek-V3",
        "key_var": "SILICONFLOW_API_KEY",
        "apply_var": "DEEPSEEK_BASE_URL",
        "apply_value": "https://api.siliconflow.cn/v1",
    },
    "Groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "key_var": "GROQ_API_KEY",
        "apply_var": "DEEPSEEK_BASE_URL",
        "apply_value": "https://api.groq.com/openai/v1",
    },
    "OpenRouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "deepseek/deepseek-chat",
        "key_var": "OPENROUTER_API_KEY",
        "apply_var": "DEEPSEEK_BASE_URL",
        "apply_value": "https://openrouter.ai/api/v1",
    },
    "自定义": {
        "base_url": "",
        "model": "",
        "key_var": "DEEPSEEK_API_KEY",
        "apply_var": "DEEPSEEK_BASE_URL",
        "apply_value": "",
    },
}


def _read_env() -> dict[str, str]:
    out = {}
    if not ENV_PATH.exists():
        return out
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def _write_env(values: dict[str, str]) -> None:
    """合并写入.env（保留未列出的行）。"""
    existing = {}
    lines = []
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, _, v = stripped.partition("=")
                existing[k.strip()] = v.strip()
            lines.append(line)
    # 更新
    for k, v in values.items():
        existing[k] = v
    # 重写
    new_lines = []
    seen = set()
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _, _ = stripped.partition("=")
            k = k.strip()
            if k in existing:
                new_lines.append(f"{k}={existing[k]}")
                seen.add(k)
                continue
        new_lines.append(line)
    for k, v in existing.items():
        if k not in seen:
            new_lines.append(f"{k}={v}")
    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


class APISettingsDialog(QDialog):
    """多渠道API设置：选择厂商→填Key→设为当前使用。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("API 设置")
        self.setMinimumWidth(600)
        self._build_ui()
        self._load_current()

    def _build_ui(self):
        lay = QVBoxLayout(self)

        lay.addWidget(QLabel(
            "选择AI渠道，填入Key，点「设为当前」即可切换。\n"
            "所有Key只保存在本机.env文件，不上传。"))

        # 厂商选择
        form = QFormLayout()
        self.cb_provider = QComboBox()
        for name in PRESETS:
            self.cb_provider.addItem(name)
        self.cb_provider.currentTextChanged.connect(self._on_provider_changed)
        form.addRow("AI厂商：", self.cb_provider)

        self.ed_base_url = QLineEdit()
        self.ed_base_url.setPlaceholderText("https://api.example.com/v1")
        form.addRow("Base URL：", self.ed_base_url)

        self.ed_model = QLineEdit()
        self.ed_model.setPlaceholderText("模型名称")
        form.addRow("模型：", self.ed_model)

        self.ed_key = QLineEdit()
        self.ed_key.setPlaceholderText("粘贴你的 API Key")
        self.ed_key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("API Key：", self.ed_key)

        lay.addLayout(form)

        # 按钮
        row = QHBoxLayout()
        btn_apply = QPushButton("设为当前使用")
        btn_apply.setStyleSheet("background-color:#2F81F7; color:white; padding:6px 16px;")
        btn_apply.clicked.connect(self._apply)
        row.addWidget(btn_apply)

        btn_save = QPushButton("仅保存Key")
        btn_save.setStyleSheet("padding:6px 16px;")
        btn_save.clicked.connect(self._save_only)
        row.addWidget(btn_save)

        btn_local = QPushButton("使用本地模型")
        btn_local.setStyleSheet("padding:6px 16px;")
        btn_local.clicked.connect(self._use_local)
        row.addWidget(btn_local)
        lay.addLayout(row)

        self.lbl_status = QLabel("")
        lay.addWidget(self.lbl_status)

    def _on_provider_changed(self, name: str):
        p = PRESETS.get(name, {})
        self.ed_base_url.setText(p.get("base_url", ""))
        self.ed_model.setText(p.get("model", ""))

    def _load_current(self):
        env = _read_env()
        current_url = env.get("DEEPSEEK_BASE_URL", "")
        # 匹配当前用的是哪个厂商
        for name, p in PRESETS.items():
            if p.get("base_url") and p["base_url"] in current_url:
                self.cb_provider.setCurrentText(name)
                self.ed_key.setText(env.get(p["key_var"], ""))
                return
        # 没匹配到，显示自定义
        self.cb_provider.setCurrentText("自定义")
        self.ed_base_url.setText(current_url)
        self.ed_key.setText(env.get("DEEPSEEK_API_KEY", ""))

    def _apply(self):
        name = self.cb_provider.currentText()
        p = PRESETS.get(name, {})
        key = self.ed_key.text().strip()
        base_url = self.ed_base_url.text().strip()
        model = self.ed_model.text().strip()

        if not key:
            self.lbl_status.setText("⚠️ 请填写API Key")
            return

        values = {"DEEPSEEK_API_KEY": key}
        if base_url:
            values["DEEPSEEK_BASE_URL"] = base_url
        if model:
            values["FAST_MODEL"] = model
        # 同时存到对应厂商的变量
        key_var = p.get("key_var", "DEEPSEEK_API_KEY")
        if key_var != "DEEPSEEK_API_KEY":
            values[key_var] = key
        _write_env(values)
        self.lbl_status.setText(f"✅ 已切换到 {name}（重启程序后生效）")

    def _save_only(self):
        name = self.cb_provider.currentText()
        p = PRESETS.get(name, {})
        key = self.ed_key.text().strip()
        if not key:
            self.lbl_status.setText("⚠️ 请填写API Key")
            return
        key_var = p.get("key_var", "DEEPSEEK_API_KEY")
        _write_env({key_var: key})
        self.lbl_status.setText(f"✅ 已保存 {name} 的Key（未切换当前渠道）")

    def _use_local(self):
        _write_env({"LLM_BACKEND": "local"})
        self.lbl_status.setText("✅ 已切换为本地模型（重启后生效，无需API Key）")
