"""
FIX #3 — Persistenza stato robusta su Render.

Strategia a due livelli:
  1. Prova a usare Redis (REDIS_URL nell'env) per persistenza cross-restart.
  2. Fallback su file locale runtime/state.json (funziona in locale e in dev).

In produzione su Render: aggiungi il Redis add-on e imposta REDIS_URL.
"""
import json
import os
from pathlib import Path

RUNTIME_DIR = Path("runtime")
STATE_FILE  = RUNTIME_DIR / "state.json"

DEFAULT_STATE: dict = {
    "bot_status":      "starting",
    "paused":          False,
    "tg_offset":       0,
    # posizione attiva
    "active_pair":     None,
    "active_order_id": None,   # FIX #1 — id ordine BUY aperto
    "order_placed_ts": None,   # FIX #1 — timestamp piazzamento ordine
    "entry_price":     None,
    "entry_amount":    None,
    "target_price":    None,
    # info mercato
    "last_price":      None,
    "eur_free":        None,
    "eur_total":       None,
    "equity_est":      None,
    "inventory":       {},
    # diagnostica
    "last_event":      None,
    "last_error":      None,
    # statistiche sessione
    "trades_total":    0,
    "profit_total":    0.0,
}


# ── Redis helper (opzionale) ─────────────────────────────────────────────────

def _redis_client():
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        return None
    try:
        import redis  # type: ignore
        return redis.from_url(redis_url, decode_responses=True)
    except Exception:
        return None


REDIS_KEY = "leviathan:state"


def _load_from_redis(r) -> dict | None:
    try:
        raw = r.get(REDIS_KEY)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


def _save_to_redis(r, state: dict) -> bool:
    try:
        r.set(REDIS_KEY, json.dumps(state, ensure_ascii=False))
        return True
    except Exception:
        return False


# ── File helper ──────────────────────────────────────────────────────────────

def _ensure_runtime():
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def _load_from_file() -> dict | None:
    _ensure_runtime()
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_to_file(state: dict) -> None:
    _ensure_runtime()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ── API pubblica ─────────────────────────────────────────────────────────────

def load_state() -> dict:
    r = _redis_client()
    data = _load_from_redis(r) if r else _load_from_file()
    state = DEFAULT_STATE.copy()
    if data:
        state.update(data)
    return state


def save_state(state: dict) -> None:
    r = _redis_client()
    if r:
        ok = _save_to_redis(r, state)
        if not ok:
            _save_to_file(state)   # fallback se Redis fallisce
    else:
        _save_to_file(state)


def format_status(state: dict) -> str:
    inv     = state.get("inventory") or {}
    inv_txt = "\n".join(f"  {k}: {v}" for k, v in inv.items()) if inv else "  n/d"
    profit  = state.get("profit_total", 0.0)
    trades  = state.get("trades_total", 0)
    return (
        "🐋 Leviathan v7 Status\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Bot:          {state.get('bot_status')}\n"
        f"Paused:       {'sì' if state.get('paused') else 'no'}\n"
        f"Pair attiva:  {state.get('active_pair')}\n"
        f"Order ID:     {state.get('active_order_id')}\n"
        f"Entry:        {state.get('entry_price')}\n"
        f"Qty:          {state.get('entry_amount')}\n"
        f"Target:       {state.get('target_price')}\n"
        f"Prezzo last:  {state.get('last_price')}\n"
        f"EUR free/tot: {state.get('eur_free')} / {state.get('eur_total')}\n"
        f"Equity est.:  {state.get('equity_est')}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Trade chiusi: {trades}\n"
        f"Profitto tot: {profit:.4f} EUR\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Ultimo evento:{state.get('last_event')}\n"
        f"Ultimo errore:{state.get('last_error')}\n"
        f"Inventory:\n{inv_txt}"
    )
