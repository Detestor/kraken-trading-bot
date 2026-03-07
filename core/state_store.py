

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

RUNTIME_DIR = Path("runtime")
STATE_FILE = RUNTIME_DIR / "state.json"
TRADES_FILE = RUNTIME_DIR / "trades.csv"


DEFAULT_STATE = {
    "bot_status": "starting",
    "symbol": "BTC/EUR",
    "timeframe": "1h",
    "regime": None,
    "last_price": None,
    "eur_free": None,
    "btc_free": None,
    "equity_est": None,
    "in_pos": False,
    "entry_price": None,
    "entry_ts": None,
    "qty_btc": None,
    "eur_spent": None,
    "sl_price": None,
    "tp_price": None,
    "mode": None,
    "last_event": None,
    "last_error": None,
    "last_bar_key": None,
    "tg_offset": 0,
}


def ensure_runtime_dir() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def load_state() -> dict[str, Any]:
    ensure_runtime_dir()
    if not STATE_FILE.exists():
        return DEFAULT_STATE.copy()

    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}

    merged = DEFAULT_STATE.copy()
    merged.update(data)
    return merged


def save_state(state: dict[str, Any]) -> None:
    ensure_runtime_dir()
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def append_trade(row: dict[str, Any]) -> None:
    ensure_runtime_dir()

    fieldnames = [
        "ts",
        "event",
        "symbol",
        "mode",
        "reason",
        "entry_price",
        "exit_price",
        "qty_btc",
        "eur_spent",
        "sl_price",
        "tp_price",
        "pnl_est",
        "equity_est",
    ]

    write_header = not TRADES_FILE.exists()

    with TRADES_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow({k: row.get(k) for k in fieldnames})


def format_status_message(state: dict[str, Any]) -> str:
    def fmt_money(x):
        return "n/d" if x is None else f"{float(x):.2f}"

    def fmt_qty(x):
        return "n/d" if x is None else f"{float(x):.8f}"

    lines = [
        "📊 KrakenBot Status",
        f"- Bot: {state.get('bot_status')}",
        f"- Symbol: {state.get('symbol')}",
        f"- TF: {state.get('timeframe')}",
        f"- Regime: {state.get('regime')}",
        f"- Prezzo: {fmt_money(state.get('last_price'))}",
        f"- EUR: {fmt_money(state.get('eur_free'))}",
        f"- BTC: {fmt_qty(state.get('btc_free'))}",
        f"- Equity stimata: {fmt_money(state.get('equity_est'))}",
        f"- In posizione: {'sì' if state.get('in_pos') else 'no'}",
        f"- Mode: {state.get('mode')}",
        f"- Entry: {fmt_money(state.get('entry_price'))}",
        f"- SL: {fmt_money(state.get('sl_price'))}",
        f"- TP: {fmt_money(state.get('tp_price'))}",
        f"- Qty BTC: {fmt_qty(state.get('qty_btc'))}",
        f"- Spesa EUR: {fmt_money(state.get('eur_spent'))}",
        f"- Ultimo evento: {state.get('last_event')}",
        f"- Ultimo errore: {state.get('last_error')}",
    ]
    return "\\n".join(lines)