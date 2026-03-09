import csv, json
from pathlib import Path

RUNTIME_DIR = Path("runtime")
STATE_FILE = RUNTIME_DIR / "state.json"
TRADES_FILE = RUNTIME_DIR / "trades.csv"

DEFAULT_STATE = {
    "bot_status":"starting","symbol":"BTC/EUR","timeframe":"5m","regime":None,"last_price":None,
    "eur_free":None,"eur_total":None,"btc_free":None,"btc_total":None,"equity_est":None,
    "open_sell_orders":0,"in_pos":False,"entry_price":None,"entry_ts":None,"qty_btc":None,
    "eur_spent":None,"sl_price":None,"tp_price":None,"mode":None,"last_event":None,
    "last_error":None,"last_bar_key":None,"tg_offset":0,
}

def ensure_runtime_dir():
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

def load_state():
    ensure_runtime_dir()
    if not STATE_FILE.exists():
        return DEFAULT_STATE.copy()
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    x = DEFAULT_STATE.copy(); x.update(data); return x

def save_state(state):
    ensure_runtime_dir()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def append_trade(row):
    ensure_runtime_dir()
    fields = ["ts","event","symbol","mode","reason","entry_price","exit_price","qty_btc","eur_spent","sl_price","tp_price","pnl_est","equity_est"]
    first = not TRADES_FILE.exists()
    with TRADES_FILE.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if first: w.writeheader()
        w.writerow({k: row.get(k) for k in fields})

def get_last_trades(limit=5):
    ensure_runtime_dir()
    if not TRADES_FILE.exists():
        return []
    with TRADES_FILE.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return rows[-limit:]

def format_status_message(state):
    def fm(x): return "n/d" if x is None else f"{float(x):.2f}"
    def fq(x): return "n/d" if x is None else f"{float(x):.8f}"
    lines = [
        "📊 KrakenBot FAST Status",
        f"- Bot: {state.get('bot_status')}",
        f"- Symbol: {state.get('symbol')}",
        f"- TF: {state.get('timeframe')}",
        f"- Regime: {state.get('regime')}",
        f"- Prezzo: {fm(state.get('last_price'))}",
        f"- EUR free/total: {fm(state.get('eur_free'))} / {fm(state.get('eur_total'))}",
        f"- BTC free/total: {fq(state.get('btc_free'))} / {fq(state.get('btc_total'))}",
        f"- Equity stimata: {fm(state.get('equity_est'))}",
        f"- Open sell orders: {state.get('open_sell_orders')}",
        f"- In posizione: {'sì' if state.get('in_pos') else 'no'}",
        f"- Mode: {state.get('mode')}",
        f"- Entry: {fm(state.get('entry_price'))}",
        f"- SL: {fm(state.get('sl_price'))}",
        f"- TP: {fm(state.get('tp_price'))}",
        f"- Qty BTC: {fq(state.get('qty_btc'))}",
        f"- Spesa EUR: {fm(state.get('eur_spent'))}",
        f"- Ultimo evento: {state.get('last_event')}",
        f"- Ultimo errore: {state.get('last_error')}",
    ]
    return "\n".join(lines)

def format_last_trades_message(rows):
    if not rows:
        return "🧾 Nessun trade registrato."
    lines = ["🧾 Ultimi trade"]
    for r in rows:
        lines.append(f"- {r.get('ts')} | {r.get('event')} | {r.get('mode')} | entry={r.get('entry_price')} | exit={r.get('exit_price')} | pnl={r.get('pnl_est')}")
    return "\n".join(lines)
