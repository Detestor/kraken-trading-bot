"""
Leviathan v8 — Multi-Pair Scalping Engine
==========================================

Novità rispetto a v7:
  • Multi-pair simultanei: una posizione aperta per pair (es. BTC/EUR + ETH/EUR in parallelo)
  • Stop-loss automatico con ordine limite
  • Trailing stop: segue il prezzo verso l'alto, scatta se scende dal picco
  • Trailing stop e stop-loss convivono per ogni posizione
  • Telegram esteso: /posizioni, /patrimonio, /chiudi PAIR, /chiuditutto, /stats, /config
  • Statistiche: trade totali, profitto, perdite, netto, contatore stop-loss
"""

import os
import sys
import time
import signal

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


# ── Exit handler ─────────────────────────────────────────────────────────────

def make_exit_handler(state_ref: list):
    def handle_exit(signum, frame):
        state = state_ref[0]
        state["bot_status"] = "stopped"
        state["last_event"] = "manual_stop"
        save_state(state)
        send_telegram("🛑 Leviathan v8 chiuso.")
        release_lock()
        sys.exit(0)
    return handle_exit


# ── Helpers patrimonio ───────────────────────────────────────────────────────

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


# ── Logica selezione pair ────────────────────────────────────────────────────

def choose_pairs_to_enter(tickers: dict, pairs: list[str], positions: dict,
                           bal: dict, order_size_eur: float) -> list[str]:
    """
    Ritorna i pair su cui aprire una nuova posizione:
    - non devono avere già una posizione attiva
    - ci deve essere EUR sufficiente
    - ordinati per score (volatilità × volume)
    """
    eur_free   = safe_float(bal.get("free", {}).get("EUR", 0.0))
    candidates = []
    for pair in pairs:
        if pair in positions:
            continue                    # posizione già aperta su questo pair
        if eur_free < order_size_eur:
            break                       # EUR esauriti
        t    = tickers.get(pair, {})
        last = safe_float(t.get("last"), 0.0)
        high = safe_float(t.get("high"), 0.0)
        low  = safe_float(t.get("low"),  0.0)
        qv   = safe_float(t.get("quoteVolume"), 0.0)
        if last <= 0:
            continue
        score = (abs(high - low) / last) * max(1.0, qv)
        candidates.append((score, pair))
        eur_free -= order_size_eur       # riserva EUR per questo pair

    candidates.sort(reverse=True)
    return [p for _, p in candidates]


def compute_amount(pair: str, price: float, order_size_eur: float, markets: dict) -> float:
    min_amount = safe_float(markets[pair]["limits"]["amount"]["min"], 0.0)
    return max(order_size_eur / price, min_amount)


# ── Gestione ordine BUY pendente ─────────────────────────────────────────────

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

    if status == "closed":
        # Filled: aggiorna entry con il prezzo reale di fill
        filled_price = safe_float(order.get("average") or order.get("price"), 0.0)
        if filled_price > 0:
            pos["entry_price"]  = filled_price
            pos["target_price"] = break_even_sell(filled_price, fee_rate, min_profit_buffer)
            pos["stop_price"]   = filled_price * (1 - stop_loss_pct)
            pos["peak_price"]   = filled_price
        pos["status"]        = "open"
        pos["buy_order_id"]  = None
        return pos, f"buy_filled_{pair}"

    elif status in ("canceled", "expired"):
        return None, f"buy_canceled_{pair}"

    elif status == "open":
        age = now_ts() - placed_ts
        if placed_ts > 0 and age > order_ttl:
            try:
                ex.cancel_order(order_id, pair)
                send_telegram(f"⏱ BUY {pair} cancellato (TTL {order_ttl}s scaduto)")
            except Exception:
                pass
            return None, f"buy_ttl_expired_{pair}"

    return pos, "pending_unchanged"


# ── Gestione posizione aperta ─────────────────────────────────────────────────

def handle_open_position(ex: Kraken, pair: str, pos: dict,
                         current_price: float, fee_rate: float,
                         trailing_enabled: bool,
                         state: dict) -> tuple[dict | None, str]:
    """
    Gestisce una posizione OPEN:
    - Aggiorna il trailing stop
    - Controlla take-profit, trailing stop, stop-loss
    - Se scatta una condizione, piazza l'ordine SELL limite e passa a CLOSING
    Ritorna (posizione aggiornata | None se già in closing, evento).
    """
    # Non fare nulla se c'è già un ordine di vendita aperto
    if pos.get("sell_order_id"):
        return pos, "closing_wait"

    # Aggiorna trailing stop
    if trailing_enabled:
        pos = update_trailing(pos, current_price)

    # Determina se e a quale prezzo vendere
    sell_price  = None
    close_reason = None

    if should_trailing_stop(pos, current_price):
        # Vendi al trailing trigger (che è >= target, quindi in profitto)
        sell_price   = pos["trailing_trigger"]
        close_reason = "trailing_stop"

    elif should_take_profit(pos, current_price):
        # Vendi al target fisso
        sell_price   = pos["target_price"]
        close_reason = "take_profit"

    elif should_stop_loss(pos, current_price):
        # Vendi allo stop_price (limite, non market)
        sell_price   = pos["stop_price"]
        close_reason = "stop_loss"

    if sell_price is None:
        return pos, "open_hold"

    # Piazza ordine SELL limite
    amount = safe_float(pos.get("entry_amount"), 0.0)
    try:
        order       = ex.sell_limit(pair, sell_price, amount)
        sell_order_id = order.get("id")
    except Exception as e:
        return pos, f"sell_order_error_{pair}: {e}"

    profit = net_profit_eur(pos["entry_price"], sell_price, amount, fee_rate)

    # Aggiorna statistiche
    state["trades_total"] = int(state.get("trades_total", 0)) + 1
    if profit >= 0:
        state["profit_total"] = round(safe_float(state.get("profit_total"), 0.0) + profit, 6)
    else:
        state["loss_total"] = round(safe_float(state.get("loss_total"), 0.0) + profit, 6)
    if close_reason == "stop_loss":
        state["sl_count"] = int(state.get("sl_count", 0)) + 1

    sign = "+" if profit >= 0 else ""
    icon = "🔴" if close_reason == "stop_loss" else ("🟡" if close_reason == "trailing_stop" else "🔴")
    send_telegram(
        f"{icon} SELL {pair} [{close_reason}]\n"
        f"   @ {sell_price:.8f}\n"
        f"   P&L: {sign}{profit:.4f} EUR\n"
        f"   tot. trades: {state['trades_total']}  "
        f"netto: {(safe_float(state.get('profit_total')) + safe_float(state.get('loss_total'))):.4f} EUR"
    )

    pos["status"]        = "closing"
    pos["sell_order_id"] = sell_order_id
    pos["sell_price"]    = sell_price
    pos["close_reason"]  = close_reason
    return pos, f"sell_placed_{close_reason}_{pair}"


# ── Gestione posizione in chiusura ────────────────────────────────────────────

def handle_closing_position(ex: Kraken, pair: str, pos: dict) -> tuple[dict | None, str]:
    """
    Controlla se l'ordine SELL è stato eseguito.
    Ritorna (None se chiuso/cancellato, evento).
    """
    sell_order_id = pos.get("sell_order_id")
    if not sell_order_id:
        return None, f"closing_no_order_{pair}"

    try:
        order = ex.get_order(sell_order_id, pair)
    except Exception as e:
        return pos, f"get_sell_order_error_{pair}"

    status = order.get("status", "")
    if status == "closed":
        return None, f"sell_filled_{pair}"
    elif status in ("canceled", "expired"):
        # L'ordine SELL è stato cancellato esternamente: torna in OPEN
        pos["status"]        = "open"
        pos["sell_order_id"] = None
        return pos, f"sell_canceled_reopen_{pair}"

    return pos, "closing_wait"


# ── Comandi Telegram ─────────────────────────────────────────────────────────

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

        # ── /help ────────────────────────────────────────────────────────────
        if cmd == "/help":
            send_telegram(
                "🐋 Leviathan v8 — Comandi\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "/status       — stato e statistiche\n"
                "/posizioni    — posizioni aperte + P&L\n"
                "/patrimonio   — equity totale\n"
                "/chiudi PAIR  — chiude un pair (es. /chiudi BTC/EUR)\n"
                "/chiuditutto  — chiude tutte le posizioni\n"
                "/stats        — statistiche dettagliate\n"
                "/config       — parametri attivi\n"
                "/pause        — mette in pausa\n"
                "/resume       — riprende\n"
                "/help         — questo messaggio"
            )

        # ── /status ──────────────────────────────────────────────────────────
        elif cmd == "/status":
            send_telegram(format_status(state))

        # ── /pause / /resume ─────────────────────────────────────────────────
        elif cmd == "/pause":
            state["paused"] = True
            send_telegram("⏸ Leviathan v8 in pausa.")

        elif cmd == "/resume":
            state["paused"] = False
            send_telegram("▶️ Leviathan v8 ripreso.")

        # ── /posizioni ───────────────────────────────────────────────────────
        elif cmd == "/posizioni":
            positions = state.get("positions") or {}
            if not positions:
                send_telegram("Nessuna posizione aperta.")
            else:
                lines = [f"📊 Posizioni aperte ({len(positions)})\n━━━━━━━━━━━━━━━━━━━━"]
                for pair, pos in positions.items():
                    t    = tickers.get(pair, {})
                    last = safe_float(t.get("last"), 0.0)
                    fee  = safe_float(cfg["trading"].get("fee_rate"), 0.0016)
                    lines.append(position_summary(pair, pos, last, fee))
                send_telegram("\n".join(lines))

        # ── /patrimonio ──────────────────────────────────────────────────────
        elif cmd == "/patrimonio":
            try:
                bal    = ex.balance()
                equity = estimate_total_equity(bal, tickers, pairs)
                eur_f  = safe_float(bal.get("free",  {}).get("EUR", 0.0))
                eur_t  = safe_float(bal.get("total", {}).get("EUR", 0.0))
                lines  = [
                    "💰 Patrimonio\n━━━━━━━━━━━━━━━━━━━━",
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
                        lines.append(f"{base}: {qty:.8f} ≈ {qty*last:.4f} EUR")
                send_telegram("\n".join(lines))
            except Exception as e:
                send_telegram(f"⚠️ Errore patrimonio: {e}")

        # ── /stats ───────────────────────────────────────────────────────────
        elif cmd == "/stats":
            trades  = int(state.get("trades_total", 0))
            profit  = safe_float(state.get("profit_total"), 0.0)
            loss    = safe_float(state.get("loss_total"),   0.0)
            sl_cnt  = int(state.get("sl_count", 0))
            net     = profit + loss   # loss è già negativo
            avg     = (net / trades) if trades > 0 else 0.0
            send_telegram(
                "📈 Statistiche\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Trade chiusi:   {trades}\n"
                f"Profitto lordo: +{profit:.4f} EUR\n"
                f"Perdite:        {loss:.4f} EUR\n"
                f"Netto:          {net:+.4f} EUR\n"
                f"Medio/trade:    {avg:+.4f} EUR\n"
                f"Stop-loss:      {sl_cnt} volte"
            )

        # ── /config ──────────────────────────────────────────────────────────
        elif cmd == "/config":
            t  = cfg.get("trading", {})
            r  = cfg.get("runtime", {})
            send_telegram(
                "⚙️ Config attiva\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
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

        # ── /chiudi PAIR ─────────────────────────────────────────────────────
        elif cmd.startswith("/chiudi "):
            target_pair = text[len("/chiudi "):].strip().upper()
            if target_pair in (state.get("positions") or {}):
                force_close.append(target_pair)
                send_telegram(f"🔒 Chiusura forzata {target_pair} in corso...")
            else:
                send_telegram(f"Nessuna posizione aperta su {target_pair}.")

        # ── /chiuditutto ─────────────────────────────────────────────────────
        elif cmd == "/chiuditutto":
            positions = state.get("positions") or {}
            if not positions:
                send_telegram("Nessuna posizione da chiudere.")
            else:
                for p in list(positions.keys()):
                    force_close.append(p)
                send_telegram(f"🔒 Chiusura forzata di {len(positions)} posizione/i in corso...")

    state["tg_offset"] = max_update_id
    return state, force_close


def force_close_position(ex: Kraken, pair: str, pos: dict, fee_rate: float, state: dict) -> None:
    """Chiude forzatamente una posizione con ordine limite al prezzo corrente."""
    try:
        t            = ex.ticker(pair)
        current_price = safe_float(t.get("last"), 0.0)
        amount       = safe_float(pos.get("entry_amount"), 0.0)
        # Prima cancella eventuale ordine sell esistente
        if pos.get("sell_order_id"):
            try:
                ex.cancel_order(pos["sell_order_id"], pair)
            except Exception:
                pass
        order  = ex.sell_limit(pair, current_price, amount)
        profit = net_profit_eur(pos["entry_price"], current_price, amount, fee_rate)
        state["trades_total"] = int(state.get("trades_total", 0)) + 1
        if profit >= 0:
            state["profit_total"] = round(safe_float(state.get("profit_total")) + profit, 6)
        else:
            state["loss_total"] = round(safe_float(state.get("loss_total")) + profit, 6)
        sign = "+" if profit >= 0 else ""
        send_telegram(f"🔒 SELL FORZATO {pair} @ {current_price:.8f}\n   P&L: {sign}{profit:.4f} EUR")
    except Exception as e:
        send_telegram(f"⚠️ Errore chiusura forzata {pair}: {e}")


# ── Main loop ────────────────────────────────────────────────────────────────

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
    sleep_seconds      = int(cfg["runtime"]["sleep_seconds"])

    state = load_state()
    state["bot_status"] = "running"
    save_state(state)

    state_ref = [state]
    signal.signal(signal.SIGINT,  make_exit_handler(state_ref))
    signal.signal(signal.SIGTERM, make_exit_handler(state_ref))

    acquire_lock()
    send_telegram(
        f"🐋 Leviathan v8 started\n"
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

            # ── Fetch batch ticker (una sola chiamata) ────────────────────
            tickers = ex.fetch_tickers(pairs)
            bal     = ex.balance()

            state["eur_free"]   = round(safe_float(bal.get("free",  {}).get("EUR", 0.0)), 4)
            state["eur_total"]  = round(safe_float(bal.get("total", {}).get("EUR", 0.0)), 4)
            state["equity_est"] = estimate_total_equity(bal, tickers, pairs)
            state["inventory"]  = inventory_snapshot(bal, pairs)

            # ── Comandi Telegram ──────────────────────────────────────────
            state, force_close_pairs = process_telegram(state, ex, tickers, pairs, cfg)

            if state.get("paused"):
                state["bot_status"] = "paused"
                save_state(state)
                time.sleep(5)
                continue

            state["bot_status"] = "running"
            positions = state.get("positions") or {}

            # ── Chiusura forzata da Telegram ──────────────────────────────
            for pair in force_close_pairs:
                if pair in positions:
                    force_close_position(ex, pair, positions[pair], fee_rate, state)
                    del positions[pair]

            # ── Cicla su tutte le posizioni esistenti ─────────────────────
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
                        ex, pair, pos, last, fee_rate, trailing_enabled, state
                    )
                    if pos is None:
                        to_remove.append(pair)
                    else:
                        positions[pair] = pos
                    state["last_event"] = event

                elif pos["status"] == "closing":
                    pos, event = handle_closing_position(ex, pair, pos)
                    if pos is None:
                        to_remove.append(pair)
                    else:
                        positions[pair] = pos
                    state["last_event"] = event

            for pair in to_remove:
                positions.pop(pair, None)

            # ── Apri nuove posizioni sui pair liberi ──────────────────────
            candidates = choose_pairs_to_enter(tickers, pairs, positions, bal, order_size_eur)

            for pair in candidates:
                t    = tickers.get(pair, {})
                last = safe_float(t.get("last"), 0.0)
                if last <= 0:
                    continue

                eur_free = safe_float(bal.get("free", {}).get("EUR", 0.0))
                # Ri-controlla che ci sia ancora EUR disponibile
                # (potrebbe essere cambiato con più posizioni aperte)
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
                    f"🟢 BUY {pair} @ {buy_price:.8f}\n"
                    f"   qty: {amount:.8f}\n"
                    f"   target: {pos['target_price']:.8f}\n"
                    f"   stop:   {pos['stop_price']:.8f}"
                )

            state["positions"] = positions
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
