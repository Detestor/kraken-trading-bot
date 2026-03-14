
import os, sys, time, signal
from core.config import load_config
from core.exchange import Kraken
from core.logic import choose_pair, compute_order_amount, can_open_new_position, has_inventory, build_buy_price, build_target, estimate_equity, inventory_snapshot
from core.notifier import send_telegram, get_updates, allowed_chat_id
from core.state_store import load_state, save_state, format_status
from core.utils import safe_float, backoff_sleep

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
    send_telegram("🛑 Leviathan v6.1 chiuso.")
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
        elif text == "/help":
            send_telegram("Comandi disponibili:\n/status\n/pause\n/resume\n/help")
        elif text == "/pause":
            state["paused"] = True
            send_telegram("⏸ Leviathan v6.1 in pausa.")
        elif text == "/resume":
            state["paused"] = False
            send_telegram("▶️ Leviathan v6.1 ripreso.")
    state["tg_offset"] = max_update_id
    return state

def main():
    cfg = load_config("config.yaml")
    pairs = cfg["pairs"]
    order_size_eur = float(cfg["trading"]["order_size_eur"])
    fee_rate = float(cfg["trading"]["fee_rate"])
    min_profit_buffer = float(cfg["trading"]["min_profit_buffer"])
    spread_multiplier = float(cfg["trading"]["spread_multiplier"])
    entry_discount = float(cfg["trading"]["entry_discount"])
    sleep_seconds = int(cfg["runtime"]["sleep_seconds"])

    state = load_state()
    state["bot_status"] = "running"
    save_state(state)

    acquire_lock()
    send_telegram("🐋 Leviathan v6.1 Anti-Bleed Engine started")

    ex = Kraken()
    markets = ex.load_markets()
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
            pair = choose_pair(ex, pairs)
            if not pair:
                state["last_event"] = "no_pair_selected"
                save_state(state)
                time.sleep(sleep_seconds)
                continue

            ticker = ex.ticker(pair)
            last = safe_float(ticker.get("last"), 0.0)
            bal = ex.balance()

            state["inventory"] = inventory_snapshot(bal, pairs)
            state["eur_free"] = round(safe_float(bal.get("free", {}).get("EUR", 0.0)), 4)
            state["eur_total"] = round(safe_float(bal.get("total", {}).get("EUR", 0.0)), 4)
            state["last_price"] = round(last, 8)
            state["equity_est"] = estimate_equity(bal, pair, last)

            managed_pair = state["active_pair"] if state.get("active_pair") else pair

            if managed_pair != pair:
                ticker = ex.ticker(managed_pair)
                last = safe_float(ticker.get("last"), 0.0)
                state["last_price"] = round(last, 8)
                state["equity_est"] = estimate_equity(bal, managed_pair, last)

            if can_open_new_position(bal, order_size_eur, state.get("active_pair")):
                amount = compute_order_amount(managed_pair, last, order_size_eur, markets)
                buy_price = build_buy_price(last, entry_discount)
                estimated_cost = amount * buy_price
                eur_free = safe_float(bal.get("free", {}).get("EUR", 0.0))
                if estimated_cost <= eur_free:
                    ex.buy_limit(managed_pair, buy_price, amount)
                    state["active_pair"] = managed_pair
                    state["entry_price"] = round(buy_price, 8)
                    state["entry_amount"] = round(amount, 12)
                    state["target_price"] = round(build_target(buy_price, fee_rate, min_profit_buffer, spread_multiplier), 8)
                    state["last_event"] = f"buy_placed_{managed_pair}"
                    state["last_error"] = None
                    send_telegram(f"🟢 BUY {managed_pair} @ {buy_price:.8f}")
                else:
                    state["last_event"] = "skip_buy_insufficient_eur"

            if state.get("active_pair"):
                active_pair = state["active_pair"]
                active_last = last if active_pair == managed_pair else safe_float(ex.ticker(active_pair).get("last"), 0.0)
                target = safe_float(state.get("target_price"), 0.0)
                amount = safe_float(state.get("entry_amount"), 0.0)
                if active_last >= target and has_inventory(bal, active_pair):
                    ex.sell_limit(active_pair, active_last, amount)
                    send_telegram(f"🔴 SELL {active_pair} @ {active_last:.8f} netto")
                    state["last_event"] = f"sell_placed_{active_pair}"
                    state["active_pair"] = None
                    state["entry_price"] = None
                    state["entry_amount"] = None
                    state["target_price"] = None

            save_state(state)
            attempt = 0
            time.sleep(sleep_seconds)

        except Exception as e:
            attempt += 1
            wait = backoff_sleep(attempt)
            state["last_error"] = f"{type(e).__name__}: {e}"
            state["last_event"] = "runtime_exception"
            save_state(state)
            send_telegram(f"⚠️ runtime error {type(e).__name__}: {e}")
            time.sleep(wait)

if __name__ == "__main__":
    main()
