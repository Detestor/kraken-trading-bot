import os
import requests


def _token() -> str:
    return os.getenv("TELEGRAM_TOKEN", "").strip()


def _chat_id() -> str:
    return os.getenv("TELEGRAM_CHAT_ID", "").strip()


def allowed_chat_id() -> str:
    return _chat_id()


def send_telegram(message: str) -> None:
    token = _token()
    chat_id = _chat_id()
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
            timeout=10,
        )
    except Exception:
        pass


def get_updates(offset: int = 0, timeout: int = 0) -> list:
    token = _token()
    if not token:
        return []
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"offset": offset, "timeout": timeout},
            timeout=15,
        )
        data = r.json()
        if not data.get("ok"):
            return []
        return data.get("result", [])
    except Exception:
        return []
