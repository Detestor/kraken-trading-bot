import os, sys, time, signal
from core.config import load_config
from core.executor import KrakenExecutor
from core.notifier import send_telegram, get_updates, allowed_chat_id
from core.state_store import load_state, save_state, append_trade, get_last_trades, format_status, format_last_trades
from core.pair_selector import select_pairs
from core.inventory import inventory_snapshot
from core.stats import estimate_equity
from core.maker import LeviathanMaker
from core.utils import backoff_sleep

LOCK_FILE = "bot.lock"

def pid_exists(pid):
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False

def acquire_lock():
    if os.path.exists(LOCK_FILE):
        try:
            pid = int(open(LOCK_FILE, "r", encoding="utf-8").read().strip() or "0")
        except Exception:
            pid = 0
        if pid and pid_exists(pid):
            print("Bot già in esecuzione!")
            sys.exit(1)
        else:
            try:
                os.remove(LOCK_FILE)
            except Exception:
                pass
    open(LOCK_FILE, "w", encoding="utf-8").write(str(os.getpid()))

def release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass

def handle_exit(signum, frame):
    state = load_state()
    state["bot_status"] = "stopped"
    state["last_event"] = "manual_stop"
    save_state(state)
    send_telegram("🛑 Leviathan v4 chiuso.")
    release_lock()
    sys.exit(0)

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

def process_telegram(state):
    offset = int(state.get("tg_offset", 0))
    updates = get_updates(offset=offset, timeout=0)
    if not updates:
        return state
    max_update_id = offset
    for upd in updates:
        update_id = upd.get("update_id", 0)
        if update_id >= max_update_id:
            max_update_id = update_id + 1
        msg = upd.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = (msg.get("text") or "").strip().lower()
        if not text or chat_id != allowed_chat_id():
            continue
        if text == "/status":
            send_telegram(format_status(state))
        elif text == "/lasttrades":
            send_telegram(format_last_trades(get_last_trades(10)))
        elif text == "/pause":
            state["paused"] = True
            send_telegram("⏸ Leviathan in pausa.")
        elif text == "/resume":
            state["paused"] = False
            send_telegram("▶️ Leviathan ripreso.")
        elif text == "/pairs":
            send_telegram("Pairs attive: " + ", ".join(state.get("selected_pairs", [])))
        elif text == "/inventory":
            inv = state.get("inventory", {})
            lines = ["📦 Inventory"]
            for k, v in inv.items():
                lines.append(f"- {k}: {v}")
            send_telegram("\n".join(lines))
        elif text == "/help":
            send_telegram("Comandi disponibili:\n/status\n/lasttrades\n/pause\n/resume\n/pairs\n/inventory\n/help")
    state["tg_offset"] = max_update_id
    return state

def main():
    cfg = load_config("config.yaml")
    state = load_state()
    state["bot_status"] = "running"
    save_state(state)
    acquire_lock()
    send_telegram("🐋 Leviathan v4 online.")
    ex = KrakenExecutor()
    maker = LeviathanMaker(ex, cfg, append_trade)
    all_pairs = cfg["pairs"]["all_pairs"]
    max_pairs = int(cfg["pairs"]["max_active_pairs"])
    sleep_seconds = int(cfg["runtime"]["sleep_seconds"])
    attempt = 0

    while True:
        try:
            state = process_telegram(state)
            if state.get("paused"):
                state["bot_status"] = "paused"
                state["last_event"] = "paused"
                save_state(state)
                time.sleep(5)
                continue

            state["bot_status"] = "running"
            selected = select_pairs(ex, all_pairs, max_pairs=max_pairs)
            state["selected_pairs"] = selected
            state["hydra_mode"] = "AUTO"

            bal = ex.balance()
            state["inventory"] = inventory_snapshot(bal, selected)
            try:
                state["eur_free"] = round(float(bal.get("free", {}).get("EUR", 0.0)), 4)
                state["eur_total"] = round(float(bal.get("total", {}).get("EUR", 0.0)), 4)
            except Exception:
                state["eur_free"] = None
                state["eur_total"] = None

            state["equity_est"] = estimate_equity(bal, ex, selected)
            try:
                state["open_orders_total"] = len(ex.open_orders())
            except Exception:
                state["open_orders_total"] = 0

            placed_total = 0
            notes = []
            for pair in selected:
                maker.cancel_old_orders(pair)
                result = maker.place_grid_for_pair(pair, bal)
                placed_total += int(result.get("orders", 0))
                notes.append(f"{pair}:{result.get('orders', 0)}@{result.get('spread')}")

            state["last_event"] = "cycle_ok | placed=" + str(placed_total) + " | " + " ; ".join(notes)
            state["last_error"] = None
            rows = get_last_trades(1000)
            state["stats_trades"] = len(rows)
            state["stats_realized_pnl_est"] = round(float(state.get("stats_realized_pnl_est", 0.0)), 6)
            save_state(state)
            attempt = 0
            time.sleep(sleep_seconds)

        except Exception as e:
            attempt += 1
            wait = backoff_sleep(attempt)
            state["last_error"] = f"{type(e).__name__}: {e}"
            state["last_event"] = "runtime_exception"
            save_state(state)
            send_telegram(f"⚠️ Leviathan runtime: {type(e).__name__}: {e}\nBackoff {wait:.0f}s")
            time.sleep(wait)

if __name__ == "__main__":
    main()
