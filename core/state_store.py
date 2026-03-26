"""
Persistenza stato - Redis se REDIS_URL e' impostato, file locale come fallback.
"""
import json
import os
from pathlib import Path

RUNTIME_DIR = Path("runtime")
STATE_FILE = RUNTIME_DIR / "state.json"

DEFAULT_STATE: dict = {
    "bot_status": "starting",
    "paused": False,
    "tg_offset": 0,
    "positions": {},
    "unmanaged_positions": {},
    "pair_cooldowns": {},
    "daily_day_key": None,
    "daily_loss_total": 0.0,
    "daily_stop_count": 0,
    "eur_free": None,
    "eur_total": None,
    "equity_est": None,
    "inventory": {},
    "last_event": None,
    "last_error": None,
    "trades_total": 0,
    "profit_total": 0.0,
    "loss_total": 0.0,
    "sl_count": 0,
}

REDIS_KEY = "leviathan:state:v8"


def _redis_client():
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        return None
    try:
        import redis  # type: ignore
        return redis.from_url(redis_url, decode_responses=True)
    except Exception:
        return None


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
        if not _save_to_redis(r, state):
            _save_to_file(state)
    else:
        _save_to_file(state)


def format_status(state: dict) -> str:
    positions = state.get("positions") or {}
    unmanaged = state.get("unmanaged_positions") or {}
    n_pos = len(positions)
    n_unmanaged = len(unmanaged)
    profit = safe_float_local(state.get("profit_total"), 0.0)
    loss = safe_float_local(state.get("loss_total"), 0.0)
    trades = state.get("trades_total", 0)
    sl_count = state.get("sl_count", 0)
    net = profit - abs(loss)

    return (
        "Leviathan v8 Status\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Bot:          {state.get('bot_status')}\n"
        f"Paused:       {'si' if state.get('paused') else 'no'}\n"
        f"Posizioni:    {n_pos} aperte\n"
        f"Residui:      {n_unmanaged} non gestite\n"
        f"EUR free/tot: {state.get('eur_free')} / {state.get('eur_total')}\n"
        f"Equity est.:  {state.get('equity_est')}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Trade chiusi: {trades}\n"
        f"Profitto:    +{profit:.4f} EUR\n"
        f"Perdite:      {loss:.4f} EUR\n"
        f"Netto:        {net:+.4f} EUR\n"
        f"Stop-loss:    {sl_count} volte\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Ultimo evento:{state.get('last_event')}\n"
        f"Ultimo errore:{state.get('last_error')}"
    )


def safe_float_local(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default
