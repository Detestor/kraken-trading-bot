import csv, json
from pathlib import Path
RUNTIME_DIR=Path("runtime")
STATE_FILE=RUNTIME_DIR/"state.json"
TRADES_FILE=RUNTIME_DIR/"trades.csv"
DEFAULT_STATE={"bot_status":"starting","paused":False,"tg_offset":0,"hydra_mode":"AUTO","selected_pairs":[],"last_event":None,"last_error":None,"equity_est":None,"eur_free":None,"eur_total":None,"inventory":{},"open_orders_total":0,"stats_trades":0,"stats_realized_pnl_est":0.0}
def ensure_runtime(): RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
def load_state():
    ensure_runtime()
    if not STATE_FILE.exists(): return DEFAULT_STATE.copy()
    try: data=json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception: data={}
    x=DEFAULT_STATE.copy(); x.update(data); return x
def save_state(state):
    ensure_runtime(); STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
def append_trade(row):
    ensure_runtime(); fields=["ts","pair","event","side","price","amount","grid_level","spread_used","note"]; first=not TRADES_FILE.exists()
    with TRADES_FILE.open("a", newline="", encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=fields)
        if first: w.writeheader()
        w.writerow({k:row.get(k) for k in fields})
def get_last_trades(limit=10):
    ensure_runtime()
    if not TRADES_FILE.exists(): return []
    with TRADES_FILE.open("r", encoding="utf-8", newline="") as f: rows=list(csv.DictReader(f))
    return rows[-limit:]
def format_status(state):
    inv=state.get("inventory",{})
    inv_txt="\n".join([f"  {k}: {v}" for k,v in inv.items()]) if inv else "  n/d"
    pairs=", ".join(state.get("selected_pairs",[])) or "n/d"
    return ("🐋 Leviathan v4 Status\n"
            f"- Bot: {state.get('bot_status')}\n"
            f"- Paused: {'sì' if state.get('paused') else 'no'}\n"
            f"- Mode: {state.get('hydra_mode')}\n"
            f"- Selected pairs: {pairs}\n"
            f"- EUR free/total: {state.get('eur_free')} / {state.get('eur_total')}\n"
            f"- Equity stimata: {state.get('equity_est')}\n"
            f"- Open orders total: {state.get('open_orders_total')}\n"
            f"- Trades registrati: {state.get('stats_trades')}\n"
            f"- PnL stimato: {state.get('stats_realized_pnl_est')}\n"
            f"- Ultimo evento: {state.get('last_event')}\n"
            f"- Ultimo errore: {state.get('last_error')}\n"
            f"- Inventory:\n{inv_txt}")
def format_last_trades(rows):
    if not rows: return "🧾 Nessun trade registrato."
    return "🧾 Ultimi trade\n" + "\n".join([f"- {r.get('ts')} | {r.get('pair')} | {r.get('event')} | {r.get('side')} | p={r.get('price')} | a={r.get('amount')} | lvl={r.get('grid_level')}" for r in rows])
