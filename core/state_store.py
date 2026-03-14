
import json
from pathlib import Path
RUNTIME_DIR = Path("runtime")
STATE_FILE = RUNTIME_DIR / "state.json"
DEFAULT_STATE = {
    "bot_status":"starting",
    "paused":False,
    "tg_offset":0,
    "active_pair":None,
    "entry_price":None,
    "entry_amount":None,
    "target_price":None,
    "last_price":None,
    "eur_free":None,
    "eur_total":None,
    "equity_est":None,
    "inventory":{},
    "last_event":None,
    "last_error":None,
}
def ensure_runtime():
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
def load_state():
    ensure_runtime()
    if not STATE_FILE.exists():
        return DEFAULT_STATE.copy()
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    x = DEFAULT_STATE.copy()
    x.update(data)
    return x
def save_state(state):
    ensure_runtime()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
def format_status(state):
    inv = state.get("inventory", {}) or {}
    inv_txt = "\n".join([f"- {k}: {v}" for k,v in inv.items()]) if inv else "- n/d"
    return (
        "🐋 Leviathan v6.1 Status\n"
        f"- Bot: {state.get('bot_status')}\n"
        f"- Paused: {'sì' if state.get('paused') else 'no'}\n"
        f"- Pair attiva: {state.get('active_pair')}\n"
        f"- Entry: {state.get('entry_price')}\n"
        f"- Qty: {state.get('entry_amount')}\n"
        f"- Target netto: {state.get('target_price')}\n"
        f"- Prezzo ultimo: {state.get('last_price')}\n"
        f"- EUR free/total: {state.get('eur_free')} / {state.get('eur_total')}\n"
        f"- Equity stimata: {state.get('equity_est')}\n"
        f"- Ultimo evento: {state.get('last_event')}\n"
        f"- Ultimo errore: {state.get('last_error')}\n"
        f"- Inventory\n{inv_txt}"
    )
