"""
Leviathan v7 — Anti-Bleed Scalping Engine
==========================================

FIX rispetto a v6.1:
  #1  Order tracking: ogni BUY salva l'order_id e viene verificato ad ogni ciclo.
      Ordini non filled entro order_ttl_seconds vengono cancellati automaticamente.
  #2  Sell usa target_price (limite garantito), non il last price spot.
  #3  Stato persistente: Redis se REDIS_URL è impostato, file locale come fallback.
  #4  Batch ticker: una sola chiamata API per tutti i pair invece di N.
  #5  Statistiche: contatore trade chiusi + profitto cumulato.
"""

import os
import sys
import time
import signal

from core.config      import load_config
from core.exchange    import Kraken
from core.logic       import (
    choose_pair, compute_order_amount, can_open_new_position,
    has_inventory, build_buy_price, build_target,
    estimate_equity, inventory_snapshot,
)
from core.notifier    import send_telegram, get_updates, allowed_chat_id
from core.profit      import net_profit_eur
from core.state_store import load_state, save_state, format_status
from core.utils       import safe_float, backoff_sleep, now_ts

LOCK_FILE = "bot.lock"


# ── Lock file ────────────────────────────────────────────────────────────────

def pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def acquire_lock() -> None:
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


def release_lock() -> None:
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass


# ── Gestione segnali ─────────────────────────────────────────────────────────

def make_exit_handler(state_ref: list):
    def handle_exit(signum, frame):
        state = state_ref[0]
        state["bot_status"] = "stopped"
        state["last_event"] = "manual_stop"
        save_state(state)
        send_telegram("🛑 Leviathan v7 chiuso.")
        release_lock()
        sys.exit(0)
    return handle_exit


# ── Telegram comandi ─────────────────────────────────────────────────────────

def process_telegram(state: dict) -> dict:
    offset  = int(state.get("tg_offset", 0))
    updates = get_updates(offset=offset, timeout=0)
    if not updates:
        return state
    max_update_id = offset
    for upd in updates:
        update_id = upd.get("update_id", 0)
        if update_id >= max_update_id:
            max_update_id = update_id + 1
        msg     = upd.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text    = (msg.get("text") or "").strip().lower()
        if not text or chat_id != allowed_chat_id():
            continue
        if text == "/status":
            send_telegram(format_status(state))
        elif text == "/help":
            send_telegram(
                "Comandi disponibili:\n"
                "/status  — stato e statistiche\n"
                "/pause   — metti in pausa\n"
                "/resume  — riprendi\n"
                "/help    — questo messaggio"
            )
        elif text == "/pause":
            state["paused"] = True
            send_telegram("⏸ Leviathan v7 in pausa.")
        elif text == "/resume":
            state["paused"] = False
            send_telegram("▶️ Leviathan v7 ripreso.")
    state["tg_offset"] = max_update_id
    return state


# ── FIX #1 — gestione ordine BUY aperto ─────────────────────────────────────

def handle_open_buy_order(ex: Kraken, state: dict, order_ttl: int) -> dict:
    """
    Verifica lo stato dell'ordine BUY attivo.
    - Se filled → mantiene la posizione, pulisce l'order_id.
    - Se scaduto (> order_ttl secondi) → cancella l'ordine e resetta.
    - Se canceled dall'esterno → resetta.
    """
    order_id    = state.get("active_order_id")
    active_pair = state.get("active_pair")
    placed_ts   = safe_float(state.get("order_placed_ts"), 0.0)

    if not order_id or not active_pair:
        return state

    try:
        order = ex.get_order(order_id, active_pair)
    except Exception as e:
        state["last_error"] = f"get_order error: {e}"
        return state

    status = order.get("status", "")

    if status == "closed":
        # Ordine eseguito: aggiorna entry_price con il filled price reale
        filled_price = safe_float(order.get("average") or order.get("price"), 0.0)
        if filled_price > 0:
            state["entry_price"] = round(filled_price, 8)
        state["active_order_id"] = None
        state["last_event"]      = f"buy_filled_{active_pair}"

    elif status in ("canceled", "expired"):
        # Ordine cancellato: resetta tutto
        state["active_pair"]     = None
        state["active_order_id"] = None
        state["order_placed_ts"] = None
        state["entry_price"]     = None
        state["entry_amount"]    = None
        state["target_price"]    = None
        state["last_event"]      = f"buy_canceled_{active_pair}"

    elif status == "open":
        # Controlla TTL: se troppo vecchio, cancella
        age = now_ts() - placed_ts
        if placed_ts > 0 and age > order_ttl:
            try:
                ex.cancel_order(order_id, active_pair)
                state["active_pair"]     = None
                state["active_order_id"] = None
                state["order_placed_ts"] = None
                state["entry_price"]     = None
                state["entry_amount"]    = None
                state["target_price"]    = None
                state["last_event"]      = f"buy_ttl_expired_{active_pair}"
                send_telegram(f"⏱ BUY {active_pair} cancellato (TTL {order_ttl}s scaduto)")
            except Exception as e:
                state["last_error"] = f"cancel_order error: {e}"

    return state


# ── Main loop ────────────────────────────────────────────────────────────────

def main():
    cfg = load_config("config.yaml")
    pairs              = cfg["pairs"]
    order_size_eur     = float(cfg["trading"]["order_size_eur"])
    fee_rate           = float(cfg["trading"]["fee_rate"])
    min_profit_buffer  = float(cfg["trading"]["min_profit_buffer"])
    spread_multiplier  = float(cfg["trading"]["spread_multiplier"])
    entry_discount     = float(cfg["trading"]["entry_discount"])
    order_ttl          = int(cfg["trading"]["order_ttl_seconds"])
    sleep_seconds      = int(cfg["runtime"]["sleep_seconds"])

    state = load_state()
    state["bot_status"] = "running"
    save_state(state)

    # Permette all'exit handler di mutare lo stato corrente
    state_ref = [state]
    signal.signal(signal.SIGINT,  make_exit_handler(state_ref))
    signal.signal(signal.SIGTERM, make_exit_handler(state_ref))

    acquire_lock()
    send_telegram("🐋 Leviathan v7 Anti-Bleed Engine started")

    ex      = Kraken()
    markets = ex.load_markets()
    attempt = 0

    while True:
        try:
            # Sincronizza state_ref con la variabile locale
            state_ref[0] = state

            # ── Telegram ──────────────────────────────────────────────────
            state = process_telegram(state)
            if state.get("paused"):
                state["bot_status"] = "paused"
                state["last_event"] = "paused"
                save_state(state)
                time.sleep(5)
                continue

            state["bot_status"] = "running"

            # ── FIX #1: gestisci ordine BUY aperto prima di tutto ─────────
            state = handle_open_buy_order(ex, state, order_ttl)

            # ── FIX #4: batch ticker in una sola chiamata ─────────────────
            tickers = ex.fetch_tickers(pairs)

            # Scegli il pair migliore
            pair = choose_pair(tickers, pairs)
            if not pair:
                state["last_event"] = "no_pair_selected"
                save_state(state)
                time.sleep(sleep_seconds)
                continue

            ticker = tickers.get(pair, {})
            last   = safe_float(ticker.get("last"), 0.0)
            bal    = ex.balance()

            state["inventory"] = inventory_snapshot(bal, pairs)
            state["eur_free"]  = round(safe_float(bal.get("free",  {}).get("EUR", 0.0)), 4)
            state["eur_total"] = round(safe_float(bal.get("total", {}).get("EUR", 0.0)), 4)
            state["last_price"]  = round(last, 8)
            state["equity_est"]  = estimate_equity(bal, pair, last)

            # Se c'è già una posizione attiva, usa quel pair per il prezzo
            managed_pair = state["active_pair"] if state.get("active_pair") else pair
            if managed_pair != pair:
                managed_ticker = tickers.get(managed_pair) or ex.ticker(managed_pair)
                last           = safe_float(managed_ticker.get("last"), 0.0)
                state["last_price"] = round(last, 8)
                state["equity_est"] = estimate_equity(bal, managed_pair, last)

            # ── Apri nuova posizione ──────────────────────────────────────
            # Condizione: nessun ordine attivo (FIX #1 usa active_order_id)
            if can_open_new_position(bal, order_size_eur, state.get("active_order_id")):
                amount    = compute_order_amount(managed_pair, last, order_size_eur, markets)
                buy_price = build_buy_price(last, entry_discount)
                est_cost  = amount * buy_price
                eur_free  = safe_float(bal.get("free", {}).get("EUR", 0.0))

                if est_cost <= eur_free:
                    order = ex.buy_limit(managed_pair, buy_price, amount)
                    # FIX #1 — salva order_id e timestamp
                    state["active_pair"]     = managed_pair
                    state["active_order_id"] = order.get("id")
                    state["order_placed_ts"] = now_ts()
                    state["entry_price"]     = round(buy_price, 8)
                    state["entry_amount"]    = round(amount, 12)
                    # FIX #2 — target calcolato sull'entry_price, usato come limite nel sell
                    state["target_price"]    = round(
                        build_target(buy_price, fee_rate, min_profit_buffer, spread_multiplier), 8
                    )
                    state["last_event"]  = f"buy_placed_{managed_pair}"
                    state["last_error"]  = None
                    send_telegram(
                        f"🟢 BUY {managed_pair} @ {buy_price:.8f}\n"
                        f"   qty: {amount:.8f}\n"
                        f"   target: {state['target_price']:.8f}"
                    )
                else:
                    state["last_event"] = "skip_buy_insufficient_eur"

            # ── Chiudi posizione se il BUY è filled e prezzo >= target ────
            # active_order_id è None solo se il buy è stato filled (vedi handle_open_buy_order)
            if (
                state.get("active_pair")
                and state.get("active_order_id") is None
                and state.get("target_price")
            ):
                active_pair  = state["active_pair"]
                active_last  = last if active_pair == managed_pair else safe_float(
                    (tickers.get(active_pair) or ex.ticker(active_pair)).get("last"), 0.0
                )
                target       = safe_float(state.get("target_price"), 0.0)
                entry_price  = safe_float(state.get("entry_price"), 0.0)
                amount       = safe_float(state.get("entry_amount"), 0.0)

                if active_last >= target and has_inventory(bal, active_pair):
                    # FIX #2 — vendi a target_price (limite), non al prezzo spot
                    ex.sell_limit(active_pair, target, amount)
                    # FIX #5 — statistiche
                    profit = net_profit_eur(entry_price, target, amount, fee_rate)
                    state["trades_total"]  = int(state.get("trades_total", 0)) + 1
                    state["profit_total"]  = round(
                        safe_float(state.get("profit_total"), 0.0) + profit, 6
                    )
                    send_telegram(
                        f"🔴 SELL {active_pair} @ {target:.8f}\n"
                        f"   profitto netto: {profit:.4f} EUR\n"
                        f"   tot. trades: {state['trades_total']}  "
                        f"tot. profitto: {state['profit_total']:.4f} EUR"
                    )
                    state["last_event"]      = f"sell_placed_{active_pair}"
                    state["active_pair"]     = None
                    state["active_order_id"] = None
                    state["order_placed_ts"] = None
                    state["entry_price"]     = None
                    state["entry_amount"]    = None
                    state["target_price"]    = None

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
