# -*- coding: utf-8 -*-
"""多渠道推送适配器（模块二 · 参考 daily_stock_analysis）。

统一推送接口，支持：企业微信机器人、飞书 Webhook、Telegram Bot、
Discord Webhook、Slack Webhook、SMTP 邮件。全部为「配置缺失即降级」：
- payload 构造为纯函数（可单测）；
- 网络/凭证缺失时返回 {ok: False, reason}，绝不让推送失败阻塞主流程。

配置读取：config.yaml `push` 段；也可直接传 dict（测试用）。
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from email.header import Header
from typing import Any, Dict, List, Optional
from urllib import request

log = logging.getLogger("stockai.core.push")

# 纯函数：各渠道 payload 构造（便于单测 + 审计留痕）
def build_wecom_payload(content: str, title: str = "") -> dict:
    return {"msgtype": "text", "text": {"content": f"{title}\n{content}" if title else content}}


def build_feishu_payload(content: str, title: str = "") -> dict:
    return {"msg_type": "text",
            "content": {"text": f"{title}\n{content}" if title else content}}


def build_telegram_payload(content: str, chat_id: str, title: str = "") -> dict:
    return {"chat_id": chat_id, "text": f"{title}\n{content}" if title else content}


def build_discord_payload(content: str, title: str = "") -> dict:
    return {"content": f"**{title}**\n{content}" if title else content}


def build_slack_payload(content: str, title: str = "") -> dict:
    return {"text": f"*{title}*\n{content}" if title else content}


def build_mail_text(content: str, title: str) -> str:
    return f"{title}\n\n{content}"


def _post(url: str, payload: dict, timeout: float = 10.0) -> Dict[str, object]:
    import json
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=data,
                          headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "ignore")[:200]
            return {"ok": resp.status < 400, "status": resp.status, "body": body}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": str(e)}


def send_webhook(url: str, payload: dict, timeout: float = 10.0) -> Dict[str, object]:
    """通用 Webhook 发送（企微/飞书/Telegram/Discord/Slack 共用）。"""
    if not url:
        return {"ok": False, "reason": "未配置 webhook URL"}
    return _post(url, payload, timeout)


def send_mail(content: str, *, subject: str, to_addrs: List[str],
              smtp_host: str, smtp_port: int = 465, username: str = "",
              password: str = "", from_addr: str = "",
              timeout: float = 15.0) -> Dict[str, object]:
    """SMTP 邮件推送（默认 SSL 465；可传 25/587 走 starttls）。"""
    if not (to_addrs and smtp_host):
        return {"ok": False, "reason": "未配置收件人/ SMTP 服务器"}
    try:
        msg = MIMEText(content, "plain", "utf-8")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = from_addr or username or "stockai"
        msg["To"] = ",".join(to_addrs)
        context = ssl.create_default_context()
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout,
                                      context=context)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=timeout)
            server.starttls(context=context)
        if username:
            server.login(username, password)
        server.sendmail(from_addr or username, to_addrs, msg.as_string())
        server.quit()
        return {"ok": True, "sent_to": len(to_addrs)}
    except Exception as e:  # noqa: BLE001
        log.warning("邮件推送失败：%s", e)
        return {"ok": False, "reason": str(e)}


def push(content: str, title: str = "", cfg: Optional[dict] = None,
         channel: str = "auto") -> List[Dict[str, object]]:
    """统一推送入口。

    cfg 结构（config.yaml push 段）：
      {wecom: {webhook}, feishu: {webhook}, telegram: {bot_token, chat_id},
       discord: {webhook}, slack: {webhook},
       mail: {smtp_host, smtp_port, username, password, from_addr, to: [..]}}
    channel: auto（全部已配置渠道）/ 指定渠道名。
    返回每个渠道的发送结果列表。
    """
    cfg = cfg or {}
    results: List[Dict[str, object]] = []
    wanted = [channel] if channel != "auto" else \
        ["wecom", "feishu", "telegram", "discord", "slack", "mail"]
    for name in wanted:
        spec = cfg.get(name)
        if not spec:
            results.append({"channel": name, "ok": False,
                            "reason": "未配置"})
            continue
        if name == "wecom":
            r = send_webhook(spec.get("webhook", ""),
                             build_wecom_payload(content, title))
        elif name == "feishu":
            r = send_webhook(spec.get("webhook", ""),
                             build_feishu_payload(content, title))
        elif name == "telegram":
            url = (f"https://api.telegram.org/bot{spec.get('bot_token', '')}"
                   f"/sendMessage")
            r = send_webhook(url, build_telegram_payload(
                content, spec.get("chat_id", ""), title))
        elif name == "discord":
            r = send_webhook(spec.get("webhook", ""),
                             build_discord_payload(content, title))
        elif name == "slack":
            r = send_webhook(spec.get("webhook", ""),
                             build_slack_payload(content, title))
        elif name == "mail":
            r = send_mail(build_mail_text(content, title),
                          subject=title or "疏影·知微推送",
                          to_addrs=spec.get("to") or [],
                          smtp_host=spec.get("smtp_host", ""),
                          smtp_port=int(spec.get("smtp_port", 465)),
                          username=spec.get("username", ""),
                          password=spec.get("password", ""),
                          from_addr=spec.get("from_addr", ""))
        else:
            r = {"ok": False, "reason": f"未知渠道 {name}"}
        results.append({"channel": name, **r})
    return results


if __name__ == "__main__":
    # 自检：payload 构造 + 未配置降级（不联网）
    assert build_wecom_payload("x")["msgtype"] == "text"
    assert build_feishu_payload("x")["msg_type"] == "text"
    assert build_telegram_payload("x", "123")["chat_id"] == "123"
    assert "**t**" in build_discord_payload("x", "t")["content"]
    assert "*t*" in build_slack_payload("x", "t")["text"]
    results = push("测试简报", cfg={})   # 全部未配置 → 全降级
    assert all(r["ok"] is False for r in results)
    assert len(results) == 6
    print("channels self-check ok")
