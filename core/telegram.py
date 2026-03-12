
import os, requests

TOKEN=os.getenv("TELEGRAM_TOKEN")
CHAT=os.getenv("TELEGRAM_CHAT_ID")

def send(msg):
    if not TOKEN or not CHAT:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id":CHAT,"text":msg},
            timeout=10
        )
    except Exception:
        pass
