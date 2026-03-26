"""
Leviathan v8 â€” Multi-Pair Scalping Engine
==========================================

NovitÃ  rispetto a v7:
  â€¢ Multi-pair simultanei: una posizione aperta per pair (es. BTC/EUR + ETH/EUR in parallelo)
  â€¢ Stop-loss automatico con ordine limite
  â€¢ Trailing stop: segue il prezzo verso l'alto, scatta se scende dal picco
  â€¢ Trailing stop e stop-loss convivono per ogni posizione
  â€¢ Telegram esteso: /posizioni, /patrimonio, /chiudi PAIR, /chiuditutto, /stats, /config
  â€¢ Statistiche: trade totali, profitto, perdite, netto, contatore stop-loss
"""

import os
import sys
import time
import signal
from datetime import datetime, timezone

from core.config      import load_config
from core.exchange    import Kraken
from core.notifier    import send_telegram, get_updates, allowed_chat_id
from core.position    import (
    new_position, update_trailing,
    should_take_profit, should_trailing_stop, should_stop_loss,
    position_summary,
)
from core.profit      import net_profit_eur, break_even_sell
from core.state_store import load_state, save_state, format_status
from core.utils       import safe_float, backoff_sleep, now_ts

LOCK_FILE = "bot.lock"


# â”€â”€ Lock file â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
            print("Bot giÃ  in esecuzione!")
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


# â”€â”€ Exit handler â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def make_exit_handler(state_ref: list):
    def handle_exit(signum, frame):
        state = state_ref[0]
        state["bot_status"] = "stopped"
        state["last_event"] = "manual_stop"
        save_state(state)
        send_telegram("ðŸ›‘ Leviathan v8 chiuso.")
        release_lock()
        sys.exit(0)
    return handle_exit


# â”€â”€ Helpers patrimonio â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def estimate_total_equity(balance: dict, tickers: dict, pairs: list[str]) -> float:
    """Somma EUR liberi + valore crypto in EUR al prezzo corrente."""
    eur = safe_float(balance.get("total", {}).get("EUR", 0.0))
    for pair in pairs:
        base, _ = pair.split("/")
        qty     = safe_float(balance.get("total", {}).get(base, 0.0))
        if qty <= 0:
            continue
        t    = tickers.get(pair, {})
        last = safe_float(t.get("last"), 0.0)
        eur += qty * last
    return round(eur, 4)


def inventory_snapshot(balance: dict, pairs: list[str]) -> dict:
    out = {}
    for pair in pairs:
        base, quote = pair.split("/")
        out[quote] = safe_float(balance.get("total", {}).get(quote, 0.0))
        out[base]  = safe_float(balance.get("total", {}).get(base, 0.0))
    return out


def detect_unmanaged_positions(balance: dict, tickers: dict, pairs: list[str],
                               positions: dict, min_value_eur: float = 1.0) -> dict:
    """Rileva asset presenti su Kraken ma non tracciati nello state locale."""
    unmanaged = {}
    for pair in pairs:
        if pair in positions:
            continue
        base, _ = pair.split("/")
        qty = safe_float(balance.get("free", {}).get(base, 0.0))
        if qty <= 0:
            continue
        last = safe_float(tickers.get(pair, {}).get("last"), 0.0)
        value_eur = qty * last
        if value_eur < min_value_eur:
            continue
        unmanaged[pair] = {
            "amount": qty,
            "last_price": last,
            "value_eur": round(value_eur, 4),
            "origin": "balance_recovery",
        }
    return unmanaged


def should_skip_pair_for_cooldown(pair: str, state: dict) -> bool:
    cooldowns = state.get("pair_cooldowns") or {}
    until_ts = safe_float(cooldowns.get(pair), 0.0)
    return until_ts > now_ts()


def set_pair_cooldown(state: dict, pair: str, cooldown_seconds: int) -> None:
    if cooldown_seconds <= 0:
        return
    cooldowns = state.get("pair_cooldowns") or {}
    cooldowns[pair] = now_ts() + cooldown_seconds
    state["pair_cooldowns"] = cooldowns


def utc_day_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def reset_daily_risk_if_needed(state: dict) -> None:
    day_key = utc_day_key()
    if state.get("daily_day_key") == day_key:
        return
    state["daily_day_key"] = day_key
    state["daily_loss_total"] = 0.0
    state["daily_stop_count"] = 0


def can_open_new_trades(state: dict, equity_est: float, min_equity_to_trade: float,
                        max_daily_loss_eur: float, max_daily_stop_count: int) -> tuple[bool, str]:
    if equity_est > 0 and equity_est < min_equity_to_trade:
        return False, "equity_guard"
    daily_loss = safe_float(state.get("daily_loss_total"), 0.0)
    if max_daily_loss_eur > 0 and daily_loss >= max_daily_loss_eur:
        return False, "daily_loss_guard"
    daily_stops = int(state.get("daily_stop_count", 0))
    if max_daily_stop_count > 0 and daily_stops >= max_daily_stop_count:
        return False, "daily_stop_guard"
    return True, "trading_enabled"


# â”€â”€ Logica selezione pair â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def choose_pairs_to_enter(tickers: dict, pairs: list[str], positions: dict,
                           bal: dict, order_size_eur: float,
                           unmanaged_positions: dict | None = None,
                           state: dict | None = None,
                           max_positions: int | None = None) -> list[str]:
    """
    Ritorna i pair su cui aprire una nuova posizione:
    - non devono avere giÃ  una posizione attiva
    - ci deve essere EUR sufficiente
    - ordinati per score (volatilitÃ  Ã— volume)
    """
    eur_free   = safe_float(bal.get("free", {}).get("EUR", 0.0))
    candidates = []
    unmanaged_positions = unmanaged_positions or {}
    state = state or {}
    max_positions = max_positions if max_positions is not None else len(pairs)
    if len(positions) >= max_positions:
        return []
    for pair in pairs:
        if pair in positions:
            continue                    # posizione giÃ  aperta su questo pair
        if pair in unmanaged_positions:
            continue
        if should_skip_pair_for_cooldown(pair, state):
            continue
        if eur_free < order_size_eur:
            break                       # EUR esauriti
        t    = tickers.get(pair, {})
        last = safe_float(t.get("last"), 0.0)
        high = safe_float(t.get("high"), 0.0)
        low  = safe_float(t.get("low"),  0.0)
        open_price = safe_float(t.get("open"), 0.0)
        vwap = safe_float(t.get("vwap"), 0.0)
        qv   = safe_float(t.get("quoteVolume"), 0.0)
        if last <= 0:
            continue
        # Evita ingressi contro trend intraday debole.
        if open_price > 0 and last < open_price:
            continue
        if vwap > 0 and last < vwap:
            continue
        score = (abs(high - low) / last) * max(1.0, qv)
        candidates.append((score, pair))
        eur_free -= order_size_eur       # riserva EUR per questo pair

    candidates.sort(reverse=True)
    return [p for _, p in candidates]


def compute_amount(pair: str, price: float, order_size_eur: float, markets: dict) -> float:
    min_amount = safe_float(markets[pair]["limits"]["amount"]["min"], 0.0)
    return max(order_size_eur / price, min_amount)


def record_closed_trade(state: dict, pair: str, entry_price: float, sell_price: float,
                        amount: float, fee_rate: float, close_reason: str) -> float:
    """Aggiorna statistiche e invia notifica solo quando la chiusura e' realmente eseguita."""
    profit = net_profit_eur(entry_price, sell_price, amount, fee_rate)
    state["trades_total"] = int(state.get("trades_total", 0)) + 1
    if profit >= 0:
        state["profit_total"] = round(safe_float(state.get("profit_total"), 0.0) + profit, 6)
    else:
        state["loss_total"] = round(safe_float(state.get("loss_total"), 0.0) + profit, 6)
        state["daily_loss_total"] = round(safe_float(state.get("daily_loss_total"), 0.0) + abs(profit), 6)
    if close_reason == "stop_loss":
        state["sl_count"] = int(state.get("sl_count", 0)) + 1
        state["daily_stop_count"] = int(state.get("daily_stop_count", 0)) + 1

    sign = "+" if profit >= 0 else ""
    icon = "ðŸ”´" if close_reason == "stop_loss" else ("ðŸŸ¡" if close_reason == "trailing_stop" else "ðŸŸ¢")
    send_telegram(
        f"{icon} SELL {pair} [{close_reason}]\n"
        f"   @ {sell_price:.8f}\n"
        f"   P&L: {sign}{profit:.4f} EUR\n"
        f"   tot. trades: {state['trades_total']}  "
        f"netto: {(safe_float(state.get('profit_total')) + safe_float(state.get('loss_total'))):.4f} EUR"
    )
    return profit


# â”€â”€ Gestione ordine BUY pendente â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def handle_pending_buy(ex: Kraken, pair: str, pos: dict, order_ttl: int,
                       fee_rate: float, min_profit_buffer: float,
                       stop_loss_pct: float) -> tuple[dict | None, str]:
    """
    Controlla lo stato dell'ordine BUY pendente.
    Ritorna (posizione aggiornata | None se da rimuovere, evento).
    """
    order_id  = pos.get("buy_order_id")
    placed_ts = safe_float(pos.get("placed_ts"), 0.0)

    try:
        order = ex.get_order(order_id, pair)
    except Exception as e:
        return pos, f"get_order_error_{pair}"

    status = order.get("status", "")
    filled_amount = safe_float(order.get("filled"), 0.0)

    if status == "closed":
        # Filled: aggiorna entry con il prezzo reale di fill
        filled_price = safe_float(order.get("average") or order.get("price"), 0.0)
        if filled_price > 0:
            pos["entry_price"]  = filled_price
            pos["target_price"] = break_even_sell(filled_price, fee_rate, min_profit_buffer)
            pos["stop_price"]   = filled_price * (1 - stop_loss_pct)
            pos["peak_price"]   = filled_price
        if filled_amount > 0:
            pos["entry_amount"] = filled_amount
        pos["status"]        = "open"
        pos["buy_order_id"]  = None
        return pos, f"buy_filled_{pair}"

    elif status in ("canceled", "expired"):
        if filled_amount > 0:
            filled_price = safe_float(order.get("average") or order.get("price"), 0.0)
            if filled_price <= 0:
                return None, f"buy_partial_no_price_{pair}"
            pos["entry_price"] = filled_price
            pos["entry_amount"] = filled_amount
            pos["target_price"] = break_even_sell(filled_price, fee_rate, min_profit_buffer)
            pos["stop_price"] = filled_price * (1 - stop_loss_pct)
            pos["peak_price"] = filled_price
            pos["status"] = "open"
            pos["buy_order_id"] = None
            return pos, f"buy_partial_recovered_{pair}"
        return None, f"buy_canceled_{pair}"

    elif status == "open":
        age = now_ts() - placed_ts
        if placed_ts > 0 and age > order_ttl:
            try:
                ex.cancel_order(order_id, pair)
                send_telegram(f"â± BUY {pair} cancellato (TTL {order_ttl}s scaduto)")
            except Exception:
                pass
            try:
                refreshed = ex.get_order(order_id, pair)
                refreshed_filled = safe_float(refreshed.get("filled"), 0.0)
                if refreshed_filled > 0:
                    filled_price = safe_float(refreshed.get("average") or refreshed.get("price"), 0.0)
                    if filled_price > 0:
                        pos["entry_price"] = filled_price
                        pos["entry_amount"] = refreshed_filled
                        pos["target_price"] = break_even_sell(filled_price, fee_rate, min_profit_buffer)
                        pos["stop_price"] = filled_price * (1 - stop_loss_pct)
                        pos["peak_price"] = filled_price
                        pos["status"] = "open"
                        pos["buy_order_id"] = None
                        return pos, f"buy_partial_ttl_recovered_{pair}"
            except Exception:
                pass
            return None, f"buy_ttl_expired_{pair}"

    return pos, "pending_unchanged"


# â”€â”€ Gestione posizione aperta â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def handle_open_position(ex: Kraken, pair: str, pos: dict,
                         current_price: float, fee_rate: float,
                         trailing_enabled: bool, break_even_trigger_pct: float,
                         state: dict) -> tuple[dict | None, str]:
    """
    Gestisce una posizione OPEN:
    - Aggiorna il trailing stop
    - Controlla take-profit, trailing stop, stop-loss
    - Stop-loss e trailing eseguono a mercato per evitare ordini limite appesi
    - Il take-profit resta a limite e viene conteggiato solo quando riempito
    """
    if pos.get("sell_order_id"):
        return pos, "closing_wait"

    if trailing_enabled:
        pos = update_trailing(pos, current_price)

    if break_even_trigger_pct > 0:
        trigger_price = pos["entry_price"] * (1 + break_even_trigger_pct)
        if current_price >= trigger_price:
            pos["stop_price"] = max(
                safe_float(pos.get("stop_price"), 0.0),
                break_even_sell(pos["entry_price"], fee_rate, 0.0),
            )

    sell_price = None
    close_reason = None

    if should_trailing_stop(pos, current_price):
        sell_price = safe_float(pos.get("trailing_trigger"), current_price)
        close_reason = "trailing_stop"
    elif should_take_profit(pos, current_price):
        sell_price = pos["target_price"]
        close_reason = "take_profit"
    elif should_stop_loss(pos, current_price):
        sell_price = pos["stop_price"]
        close_reason = "stop_loss"

    if sell_price is None:
        return pos, "open_hold"

    amount = safe_float(pos.get("entry_amount"), 0.0)

    if close_reason in ("stop_loss", "trailing_stop"):
        try:
            ex.sell_market(pair, amount)
        except Exception as e:
            return pos, f"sell_market_error_{pair}: {e}"
        record_closed_trade(
            state, pair, pos["entry_price"], current_price, amount, fee_rate, close_reason
        )
        return None, f"sell_filled_{close_reason}_{pair}"

    try:
        order = ex.sell_limit(pair, sell_price, amount)
        sell_order_id = order.get("id")
    except Exception as e:
        return pos, f"sell_order_error_{pair}: {e}"

    pos["status"] = "closing"
    pos["sell_order_id"] = sell_order_id
    pos["sell_price"] = sell_price
    pos["close_reason"] = close_reason
    return pos, f"sell_placed_{close_reason}_{pair}"


# â”€â”€ Gestione posizione in chiusura â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def handle_closing_position(ex: Kraken, pair: str, pos: dict,
                            fee_rate: float, state: dict) -> tuple[dict | None, str]:
    """
    Controlla se l'ordine SELL limite e' stato eseguito.
    Aggiorna statistiche solo al fill reale.
    """
    sell_order_id = pos.get("sell_order_id")
    if not sell_order_id:
        return None, f"closing_no_order_{pair}"

    try:
        order = ex.get_order(sell_order_id, pair)
    except Exception:
        return pos, f"get_sell_order_error_{pair}"

    status = order.get("status", "")
    if status == "closed":
        avg_sell = safe_float(order.get("average") or order.get("price") or pos.get("sell_price"), 0.0)
        if avg_sell <= 0:
            avg_sell = safe_float(pos.get("sell_price"), 0.0)
        record_closed_trade(
            state,
            pair,
            safe_float(pos.get("entry_price"), 0.0),
            avg_sell,
            safe_float(pos.get("entry_amount"), 0.0),
            fee_rate,
            pos.get("close_reason", "take_profit"),
        )
        return None, f"sell_filled_{pair}"
    elif status in ("canceled", "expired"):
        pos["status"] = "open"
        pos["sell_order_id"] = None
        pos["sell_price"] = None
        pos["close_reason"] = None
        return pos, f"sell_canceled_reopen_{pair}"

    return pos, "closing_wait"


# â”€â”€ Comandi Telegram â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def process_telegram(state: dict, ex: Kraken, tickers: dict,
                     pairs: list[str], cfg: dict) -> tuple[dict, list[str]]:
    """
    Processa i comandi Telegram. Ritorna (state aggiornato, lista pair da chiudere forzatamente).
    """
    offset       = int(state.get("tg_offset", 0))
    updates      = get_updates(offset=offset, timeout=0)
    force_close  = []   # pair da chiudere su richiesta dell'utente

    if not updates:
        return state, force_close

    max_update_id = offset
    for upd in updates:
        update_id = upd.get("update_id", 0)
        if update_id >= max_update_id:
            max_update_id = update_id + 1

        msg     = upd.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text    = (msg.get("text") or "").strip()
        cmd     = text.lower()

        if not cmd or chat_id != allowed_chat_id():
            continue

        # â”€â”€ /help â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if cmd == "/help":
            send_telegram(
                "ðŸ‹ Leviathan v8 â€” Comandi\n"
                "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
                "/status       â€” stato e statistiche\n"
                "/posizioni    â€” posizioni aperte + P&L\n"
                "/patrimonio   â€” equity totale\n"
                "/chiudi PAIR  â€” chiude un pair (es. /chiudi BTC/EUR)\n"
                "/chiuditutto  â€” chiude tutte le posizioni\n"
                "/stats        â€” statistiche dettagliate\n"
                "/config       â€” parametri attivi\n"
                "/pause        â€” mette in pausa\n"
                "/resume       â€” riprende\n"
                "/help         â€” questo messaggio"
            )

        # â”€â”€ /status â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        elif cmd == "/status":
            send_telegram(format_status(state))

        # â”€â”€ /pause / /resume â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        elif cmd == "/pause":
            state["paused"] = True
            send_telegram("â¸ Leviathan v8 in pausa.")

        elif cmd == "/resume":
            state["paused"] = False
            send_telegram("â–¶ï¸ Leviathan v8 ripreso.")

        # â”€â”€ /posizioni â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        elif cmd == "/posizioni":
            positions = state.get("positions") or {}
            unmanaged = state.get("unmanaged_positions") or {}
            if not positions and not unmanaged:
                send_telegram("Nessuna posizione aperta.")
            else:
                lines = [f"ðŸ“Š Posizioni aperte ({len(positions)})\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”"]
                for pair, pos in positions.items():
                    t    = tickers.get(pair, {})
                    last = safe_float(t.get("last"), 0.0)
                    fee  = safe_float(cfg["trading"].get("fee_rate"), 0.0016)
                    lines.append(position_summary(pair, pos, last, fee))
                for pair, pos in unmanaged.items():
                    lines.append(
                        f"RECOVERY {pair} [unmanaged]\n"
                        f"   Qty:     {safe_float(pos.get('amount'), 0.0):.8f}\n"
                        f"   Last:    {safe_float(pos.get('last_price'), 0.0):.8f}\n"
                        f"   Valore:  {safe_float(pos.get('value_eur'), 0.0):.4f} EUR\n"
                        "   Nota:    residuo su Kraken non tracciato dal bot"
                    )
                send_telegram("\n".join(lines))

        # â”€â”€ /patrimonio â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        elif cmd == "/patrimonio":
            try:
                bal    = ex.balance()
                equity = estimate_total_equity(bal, tickers, pairs)
                eur_f  = safe_float(bal.get("free",  {}).get("EUR", 0.0))
                eur_t  = safe_float(bal.get("total", {}).get("EUR", 0.0))
                lines  = [
                    "ðŸ’° Patrimonio\nâ”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”",
                    f"EUR liberi:  {eur_f:.4f}",
                    f"EUR totali:  {eur_t:.4f}",
                    f"Equity tot.: {equity:.4f} EUR",
                ]
                for pair in pairs:
                    base, _ = pair.split("/")
                    qty     = safe_float(bal.get("total", {}).get(base, 0.0))
                    if qty > 0:
                        t    = tickers.get(pair, {})
                        last = safe_float(t.get("last"), 0.0)
                        lines.append(f"{base}: {qty:.8f} â‰ˆ {qty*last:.4f} EUR")
                send_telegram("\n".join(lines))
            except Exception as e:
                send_telegram(f"âš ï¸ Errore patrimonio: {e}")

        # â”€â”€ /stats â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        elif cmd == "/stats":
            trades  = int(state.get("trades_total", 0))
            profit  = safe_float(state.get("profit_total"), 0.0)
            loss    = safe_float(state.get("loss_total"),   0.0)
            sl_cnt  = int(state.get("sl_count", 0))
            net     = profit + loss   # loss Ã¨ giÃ  negativo
            avg     = (net / trades) if trades > 0 else 0.0
            send_telegram(
                "ðŸ“ˆ Statistiche\n"
                f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
                f"Trade chiusi:   {trades}\n"
                f"Profitto lordo: +{profit:.4f} EUR\n"
                f"Perdite:        {loss:.4f} EUR\n"
                f"Netto:          {net:+.4f} EUR\n"
                f"Medio/trade:    {avg:+.4f} EUR\n"
                f"Stop-loss:      {sl_cnt} volte"
            )

        # â”€â”€ /config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        elif cmd == "/config":
            t  = cfg.get("trading", {})
            r  = cfg.get("runtime", {})
            send_telegram(
                "âš™ï¸ Config attiva\n"
                f"â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n"
                f"Pair:           {', '.join(cfg.get('pairs', []))}\n"
                f"order_size_eur: {t.get('order_size_eur')}\n"
                f"fee_rate:       {t.get('fee_rate')}\n"
                f"min_profit_buf: {t.get('min_profit_buffer')}\n"
                f"entry_discount: {t.get('entry_discount')}\n"
                f"order_ttl:      {t.get('order_ttl_seconds')}s\n"
                f"stop_loss_pct:  {t.get('stop_loss_pct')}\n"
                f"trailing:       {'on' if t.get('trailing_enabled') else 'off'}\n"
                f"trailing_dist:  {t.get('trailing_distance_pct')}\n"
                f"sleep_seconds:  {r.get('sleep_seconds')}"
            )

        # â”€â”€ /chiudi PAIR â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        elif cmd.startswith("/chiudi "):
            target_pair = text[len("/chiudi "):].strip().upper()
            if target_pair in (state.get("positions") or {}):
                force_close.append(target_pair)
                send_telegram(f"ðŸ”’ Chiusura forzata {target_pair} in corso...")
            elif target_pair in (state.get("unmanaged_positions") or {}):
                force_close.append(target_pair)
                send_telegram(f"Chiusura recovery {target_pair} in corso...")
            else:
                send_telegram(f"Nessuna posizione aperta su {target_pair}.")

        # â”€â”€ /chiuditutto â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        elif cmd == "/chiuditutto":
            positions = state.get("positions") or {}
            unmanaged = state.get("unmanaged_positions") or {}
            if not positions and not unmanaged:
                send_telegram("Nessuna posizione da chiudere.")
            else:
                for p in list(positions.keys()):
                    force_close.append(p)
                for p in list(unmanaged.keys()):
                    if p not in force_close:
                        force_close.append(p)
                send_telegram(f"ðŸ”’ Chiusura forzata di {len(positions)} posizione/i in corso...")

    state["tg_offset"] = max_update_id
    return state, force_close


def force_close_position(ex: Kraken, pair: str, pos: dict, fee_rate: float, state: dict) -> None:
    """Chiude forzatamente una posizione a mercato."""
    try:
        t = ex.ticker(pair)
        current_price = safe_float(t.get("last"), 0.0)
        amount = safe_float(pos.get("entry_amount"), 0.0)
        if pos.get("sell_order_id"):
            try:
                ex.cancel_order(pos["sell_order_id"], pair)
            except Exception:
                pass
        ex.sell_market(pair, amount)
        record_closed_trade(
            state,
            pair,
            safe_float(pos.get("entry_price"), 0.0),
            current_price,
            amount,
            fee_rate,
            "forced_close",
        )
    except Exception as e:
        send_telegram(f"Errore chiusura forzata {pair}: {e}")


# â”€â”€ Main loop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def force_close_unmanaged_inventory(ex: Kraken, pair: str, amount: float, state: dict) -> None:
    """Liquida a mercato un residuo presente su Kraken ma non tracciato dal bot."""
    try:
        if amount <= 0:
            raise ValueError("amount <= 0")
        t = ex.ticker(pair)
        current_price = safe_float(t.get("last"), 0.0)
        ex.sell_market(pair, amount)
        send_telegram(
            f"RECOVERY SELL {pair} @ market\n"
            f"   qty: {amount:.8f}\n"
            f"   stima: {amount * current_price:.4f} EUR"
        )
        state["last_event"] = f"recovery_sell_{pair}"
        state["last_error"] = None
    except Exception as e:
        state["last_error"] = f"recovery_sell_error_{pair}: {e}"
        send_telegram(f"Errore chiusura recovery {pair}: {e}")


def auto_close_unmanaged_positions(ex: Kraken, unmanaged_positions: dict, state: dict) -> dict:
    """Liquida automaticamente i residui per evitare che restino fuori controllo."""
    remaining = dict(unmanaged_positions)
    for pair, info in list(unmanaged_positions.items()):
        amount = safe_float(info.get("amount"), 0.0)
        if amount <= 0:
            remaining.pop(pair, None)
            continue
        force_close_unmanaged_inventory(ex, pair, amount, state)
        remaining.pop(pair, None)
    return remaining


def main():
    cfg = load_config("config.yaml")

    pairs              = cfg["pairs"]
    order_size_eur     = float(cfg["trading"]["order_size_eur"])
    fee_rate           = float(cfg["trading"]["fee_rate"])
    min_profit_buffer  = float(cfg["trading"]["min_profit_buffer"])
    entry_discount     = float(cfg["trading"]["entry_discount"])
    order_ttl          = int(cfg["trading"]["order_ttl_seconds"])
    stop_loss_pct      = float(cfg["trading"]["stop_loss_pct"])
    trailing_enabled   = bool(cfg["trading"].get("trailing_enabled", True))
    trailing_dist      = float(cfg["trading"].get("trailing_distance_pct", 0.003))
    break_even_trigger = float(cfg["trading"].get("break_even_trigger_pct", 0.003))
    stoploss_cooldown  = int(cfg["trading"].get("stoploss_cooldown_seconds", 1800))
    max_positions      = int(cfg["trading"].get("max_simultaneous_positions", 1))
    auto_close_unmanaged = bool(cfg["trading"].get("auto_close_unmanaged", True))
    max_daily_loss_eur = float(cfg["trading"].get("max_daily_loss_eur", 0.5))
    max_daily_stop_count = int(cfg["trading"].get("max_daily_stop_count", 2))
    min_equity_to_trade = float(cfg["trading"].get("min_equity_to_trade", 15.0))
    sleep_seconds      = int(cfg["runtime"]["sleep_seconds"])

    state = load_state()
    state["bot_status"] = "running"
    save_state(state)

    state_ref = [state]
    signal.signal(signal.SIGINT,  make_exit_handler(state_ref))
    signal.signal(signal.SIGTERM, make_exit_handler(state_ref))

    acquire_lock()
    send_telegram(
        f"ðŸ‹ Leviathan v8 started\n"
        f"Pair: {', '.join(pairs)}\n"
        f"Trailing: {'on' if trailing_enabled else 'off'} | "
        f"Stop-loss: {stop_loss_pct*100:.1f}%"
    )

    ex      = Kraken()
    markets = ex.load_markets()
    attempt = 0

    while True:
        try:
            state_ref[0] = state
            reset_daily_risk_if_needed(state)

            # â”€â”€ Fetch batch ticker (una sola chiamata) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            tickers = ex.fetch_tickers(pairs)
            bal     = ex.balance()

            state["eur_free"]   = round(safe_float(bal.get("free",  {}).get("EUR", 0.0)), 4)
            state["eur_total"]  = round(safe_float(bal.get("total", {}).get("EUR", 0.0)), 4)
            state["equity_est"] = estimate_total_equity(bal, tickers, pairs)
            state["inventory"]  = inventory_snapshot(bal, pairs)
            state["unmanaged_positions"] = detect_unmanaged_positions(
                bal, tickers, pairs, state.get("positions") or {}
            )

            # â”€â”€ Comandi Telegram â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            state, force_close_pairs = process_telegram(state, ex, tickers, pairs, cfg)

            if state.get("paused"):
                state["bot_status"] = "paused"
                save_state(state)
                time.sleep(5)
                continue

            state["bot_status"] = "running"
            positions = state.get("positions") or {}
            unmanaged_positions = state.get("unmanaged_positions") or {}

            if auto_close_unmanaged and unmanaged_positions:
                unmanaged_positions = auto_close_unmanaged_positions(ex, unmanaged_positions, state)

            # â”€â”€ Chiusura forzata da Telegram â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            for pair in force_close_pairs:
                if pair in positions:
                    force_close_position(ex, pair, positions[pair], fee_rate, state)
                    del positions[pair]
                elif pair in unmanaged_positions:
                    amount = safe_float(unmanaged_positions[pair].get("amount"), 0.0)
                    force_close_unmanaged_inventory(ex, pair, amount, state)
                    unmanaged_positions.pop(pair, None)

            # â”€â”€ Cicla su tutte le posizioni esistenti â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            to_remove = []
            for pair, pos in list(positions.items()):
                t    = tickers.get(pair, {})
                last = safe_float(t.get("last"), 0.0)

                if pos["status"] == "pending":
                    pos, event = handle_pending_buy(
                        ex, pair, pos, order_ttl,
                        fee_rate, min_profit_buffer, stop_loss_pct
                    )
                    if pos is None:
                        to_remove.append(pair)
                    else:
                        positions[pair] = pos
                    state["last_event"] = event

                elif pos["status"] == "open":
                    pos, event = handle_open_position(
                        ex, pair, pos, last, fee_rate, trailing_enabled, break_even_trigger, state
                    )
                    if pos is None:
                        if "stop_loss" in event:
                            set_pair_cooldown(state, pair, stoploss_cooldown)
                        to_remove.append(pair)
                    else:
                        positions[pair] = pos
                    state["last_event"] = event

                elif pos["status"] == "closing":
                    pos, event = handle_closing_position(ex, pair, pos, fee_rate, state)
                    if pos is None:
                        to_remove.append(pair)
                    else:
                        positions[pair] = pos
                    state["last_event"] = event

            for pair in to_remove:
                positions.pop(pair, None)

            # â”€â”€ Apri nuove posizioni sui pair liberi â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            can_trade, trade_guard_reason = can_open_new_trades(
                state,
                safe_float(state.get("equity_est"), 0.0),
                min_equity_to_trade,
                max_daily_loss_eur,
                max_daily_stop_count,
            )
            if can_trade:
                candidates = choose_pairs_to_enter(
                    tickers, pairs, positions, bal, order_size_eur, unmanaged_positions, state, max_positions
                )
            else:
                candidates = []
                state["last_event"] = trade_guard_reason

            for pair in candidates:
                t    = tickers.get(pair, {})
                last = safe_float(t.get("last"), 0.0)
                if last <= 0:
                    continue

                eur_free = safe_float(bal.get("free", {}).get("EUR", 0.0))
                # Ri-controlla che ci sia ancora EUR disponibile
                # (potrebbe essere cambiato con piÃ¹ posizioni aperte)
                if eur_free < order_size_eur:
                    break

                amount    = compute_amount(pair, last, order_size_eur, markets)
                buy_price = last * (1 - entry_discount)
                est_cost  = amount * buy_price

                if est_cost > eur_free:
                    continue

                try:
                    order = ex.buy_limit(pair, buy_price, amount)
                except Exception as e:
                    state["last_error"] = f"buy_order_error_{pair}: {e}"
                    continue

                pos = new_position(
                    pair, order.get("id"), buy_price, amount,
                    fee_rate, min_profit_buffer,
                    stop_loss_pct, trailing_dist
                )
                positions[pair] = pos
                state["last_event"] = f"buy_placed_{pair}"
                state["last_error"] = None
                send_telegram(
                    f"ðŸŸ¢ BUY {pair} @ {buy_price:.8f}\n"
                    f"   qty: {amount:.8f}\n"
                    f"   target: {pos['target_price']:.8f}\n"
                    f"   stop:   {pos['stop_price']:.8f}"
                )

            state["positions"] = positions
            state["unmanaged_positions"] = unmanaged_positions
            save_state(state)
            attempt = 0
            time.sleep(sleep_seconds)

        except Exception as e:
            attempt += 1
            wait = backoff_sleep(attempt)
            state["last_error"] = f"{type(e).__name__}: {e}"
            state["last_event"] = "runtime_exception"
            save_state(state)
            send_telegram(f"âš ï¸ runtime error {type(e).__name__}: {e}")
            time.sleep(wait)


if __name__ == "__main__":
    main()

