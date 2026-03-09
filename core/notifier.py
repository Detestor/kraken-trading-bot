from __future__ import annotations
import os
import requests

def _token() -> str:
    return os.getenv("TELEGRAM_TOKEN", "").strip()

def _chat_id() -> str:
    return os.getenv("TELEGRAM_CHAT_ID", "").strip()

def send_telegram(message: str) -> None:
    token = _token()
    chat_id = _chat_id()
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "disable_web_page_preview": True}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception:
        pass

def get_telegram_updates(offset: int = 0, timeout: int = 0) -> list[dict]:
    token = _token()
    if not token:
        return []
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {"offset": offset, "timeout": timeout}
    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if not data.get("ok"):
            return []
        return data.get("result", [])
    except Exception:
        return []

def get_allowed_chat_id() -> str:
    return _chat_id()
