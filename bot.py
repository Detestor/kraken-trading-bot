from __future__ import annotations

import os
import sys
import time
import signal
from datetime import datetime, timezone

from rich import print

from core.config import load_config
from core.datafeed import DataFeed
from core.executor import KrakenExecutor
from core.notifier import send_telegram, get_telegram_updates, get_allowed_chat_id
from core.regime import detect_regime
from core.indicators import atr
from core.strategies import signal_trend, signal_range
from core.utils import safe_float, backoff_sleep
from core.ai_manager import ai_enabled, ai_recommendation
from core.state_store import load_state, save_state, append_trade, format_status_message


LOCK_FILE = "bot.lock"
IN_CRITICAL = False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def pid_exists(pid: int) -> bool:
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
            print("[red]Bot già in esecuzione![/red]")
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
    global IN_CRITICAL
    if IN_CRITICAL:
        send_telegram("⚠️ Tentata chiusura durante operazione: bloccata.")
        return

    state = load_state()
    state["bot_status"] = "stopped"
    state["last_event"] = "manual_stop"
    save_state(state)

    send_telegram("🛑 Bot chiuso.")
    release_lock()
    sys.exit(0)


signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)


def bar_key(df):
    cols = list(df.columns)
    if "ts" in cols:
        return df.iloc[-1]["ts"]
    if "timestamp" in cols:
        return df.iloc[-1]["timestamp"]
    if "datetime" in cols:
        return df.iloc[-1]["datetime"]
    try:
        return df.index[-1]
    except Exception:
        return None


def process_telegram_commands(state: dict):
    allowed_chat_id = get_allowed_chat_id()
    offset = int(state.get("tg_offset", 0))

    updates = get_telegram_updates(offset=offset, timeout=0)
    if not updates:
        return state

    max_update_id = offset

    for upd in updates:
        update_id = upd.get("update_id", 0)
        if update_id >= max_update_id:
            max_update_id = update_id + 1

        msg = upd.get("message", {})
        chat = msg.get("chat", {})
        chat_id = str(chat.get("id", ""))
        text = (msg.get("text") or "").strip().lower()

        if not text or chat_id != allowed_chat_id:
            continue

        if text == "/status":
            send_telegram(format_status_message(state))

        elif text == "/ping":
            send_telegram("🏓 pong")

        elif text == "/help":
            send_telegram(
                "Comandi disponibili:\\n"
                "/status - stato completo del bot\\n"
                "/ping - test rapido\\n"
                "/help - aiuto"
            )

    state["tg_offset"] = max_update_id
    return state


def main():
    global IN_CRITICAL

    cfg = load_config("config.yaml")
    state = load_state()

    symbol = cfg.get("symbol", "BTC/EUR")
    timeframe = cfg.get("timeframe", "1h")
    limit = int(cfg.get("ohlcv_limit", 500))
    spend_pct = float(cfg.get("spend_pct", 0.50))
    min_trade_eur = float(cfg.get("min_trade_eur", 6.0))

    A = cfg.get("strategy_A", {})
    B = cfg.get("strategy_B", {})
    A_sl, A_tp = float(A.get("sl_atr", 1.5)), float(A.get("tp_atr", 3.0))
    B_sl, B_tp = float(B.get("sl_atr", 1.0)), float(B.get("tp_atr", 1.2))

    state["symbol"] = symbol
    state["timeframe"] = timeframe
    state["bot_status"] = "running"
    save_state(state)

    acquire_lock()
    send_telegram("🚀 KrakenBotVPS avviato. (SL reale + TP software)")

    feed = DataFeed()
    ex = KrakenExecutor()

    last_k = state.get("last_bar_key")
    last_reg = state.get("regime")
    attempt = 0

    print(f"LIVE {symbol} tf={timeframe} | spend_pct={spend_pct:.2f} | min_trade={min_trade_eur:.2f}")

    while True:
        try:
            # comandi telegram
            state = process_telegram_commands(state)

            bal = ex.fetch_balance()
            eur = safe_float(bal.get("free", {}).get("EUR", 0.0))
            btc = safe_float(bal.get("free", {}).get("BTC", 0.0))
            in_pos = btc > 1e-7

            t = ex.fetch_ticker(symbol)
            last = safe_float(t.get("last", 0.0))
            ask = safe_float(t.get("ask", last))

            equity_est = eur + btc * last

            state["eur_free"] = eur
            state["btc_free"] = btc
            state["last_price"] = last
            state["equity_est"] = equity_est
            state["bot_status"] = "running"

            print(f"status | price={last:.2f} | EUR={eur:.2f} | BTC={btc:.8f}")

            # rilevazione uscita esterna / stop loss eseguito
            if state.get("in_pos") and not in_pos:
                append_trade({
                    "ts": now_iso(),
                    "event": "EXIT",
                    "symbol": symbol,
                    "mode": state.get("mode"),
                    "reason": "POSITION_CLOSED_EXTERNALLY_OR_SL",
                    "entry_price": state.get("entry_price"),
                    "exit_price": last,
                    "qty_btc": state.get("qty_btc"),
                    "eur_spent": state.get("eur_spent"),
                    "sl_price": state.get("sl_price"),
                    "tp_price": state.get("tp_price"),
                    "pnl_est": ((last - float(state.get("entry_price") or 0)) * float(state.get("qty_btc") or 0)),
                    "equity_est": equity_est,
                })

                state["in_pos"] = False
                state["entry_price"] = None
                state["entry_ts"] = None
                state["qty_btc"] = None
                state["eur_spent"] = None
                state["sl_price"] = None
                state["tp_price"] = None
                state["mode"] = None
                state["last_event"] = "position_closed_detected"
                send_telegram("ℹ️ Posizione chiusa rilevata (stop/manuale/esterna).")

            # TP software
            if in_pos and state.get("tp_price") is not None and last >= float(state["tp_price"]):
                IN_CRITICAL = True
                send_telegram(f"🎯 TP software ({state.get('mode')}) — vendo market @ {last:.2f}")
                ex.create_market_sell(symbol, btc)

                append_trade({
                    "ts": now_iso(),
                    "event": "EXIT",
                    "symbol": symbol,
                    "mode": state.get("mode"),
                    "reason": "TP_SOFTWARE",
                    "entry_price": state.get("entry_price"),
                    "exit_price": last,
                    "qty_btc": state.get("qty_btc"),
                    "eur_spent": state.get("eur_spent"),
                    "sl_price": state.get("sl_price"),
                    "tp_price": state.get("tp_price"),
                    "pnl_est": ((last - float(state.get("entry_price") or 0)) * float(state.get("qty_btc") or 0)),
                    "equity_est": equity_est,
                })

                state["in_pos"] = False
                state["entry_price"] = None
                state["entry_ts"] = None
                state["qty_btc"] = None
                state["eur_spent"] = None
                state["sl_price"] = None
                state["tp_price"] = None
                state["mode"] = None
                state["last_event"] = "tp_software_exit"

                IN_CRITICAL = False
                save_state(state)
                time.sleep(10)
                continue

            df = feed.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            k = bar_key(df)
            if k == last_k:
                save_state(state)
                time.sleep(60)
                continue

            last_k = k
            state["last_bar_key"] = str(k)

            reg = detect_regime(df)
            state["regime"] = reg

            if reg != last_reg:
                send_telegram(f"🧭 Regime: {reg} (tf={timeframe})")
                last_reg = reg

            if in_pos:
                save_state(state)
                time.sleep(10)
                continue

            if reg == "CHAOS":
                state["last_event"] = "chaos_skip"
                save_state(state)
                time.sleep(60)
                continue

            if reg == "TREND":
                sig = signal_trend(df)
                sl_m, tp_m, mode = A_sl, A_tp, "A/TREND"
            else:
                sig = signal_range(df)
                sl_m, tp_m, mode = B_sl, B_tp, "B/RANGE"

            if ai_enabled():
                try:
                    send_telegram(
                        ai_recommendation({
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "regime": reg,
                            "price": last,
                            "signal": sig,
                        })[:3500]
                    )
                except Exception:
                    pass

            if sig != "BUY":
                state["last_event"] = f"no_setup_{mode}"
                save_state(state)
                time.sleep(60)
                continue

            eur_spend = min(eur * spend_pct, max(0.0, eur - 0.5))
            if eur_spend < min_trade_eur:
                state["last_event"] = "insufficient_funds"
                save_state(state)
                send_telegram(f"⚠️ Setup {mode} ma EUR insufficienti (free={eur:.2f}).")
                time.sleep(60)
                continue

            qty = eur_spend / ask

            d2 = df.copy()
            d2["atr"] = atr(d2)
            atr_v = safe_float(d2.iloc[-1]["atr"], 0.0)
            if atr_v <= 0:
                state["last_event"] = "invalid_atr"
                save_state(state)
                time.sleep(60)
                continue

            stop_price = ask - (sl_m * atr_v)
            tp_price = ask + (tp_m * atr_v)

            IN_CRITICAL = True
            ex.create_market_buy(symbol, qty)
            send_telegram(f"🟢 BUY {symbol} ({mode})\\nSpesa: {eur_spend:.2f}€\\nPrezzo: {ask:.2f}")

            time.sleep(3)

            bal2 = ex.fetch_balance()
            btc2 = safe_float(bal2.get("free", {}).get("BTC", 0.0))
            if btc2 <= 1e-7:
                state["last_event"] = "buy_no_btc_visible"
                save_state(state)
                send_telegram("⚠️ BUY fatto ma BTC non visibile (attendo).")
                IN_CRITICAL = False
                time.sleep(30)
                continue

            try:
                ex.create_stop_loss_sell(symbol, btc2, stop_price)
            except Exception as e:
                state["last_error"] = f"SL_ERROR: {e}"
                state["last_event"] = "sl_error_forced_close"
                save_state(state)
                send_telegram(f"❌ ERRORE SL: {e}\\nChiudo per sicurezza.")
                ex.create_market_sell(symbol, btc2)
                IN_CRITICAL = False
                time.sleep(30)
                continue

            state["in_pos"] = True
            state["entry_price"] = ask
            state["entry_ts"] = now_iso()
            state["qty_btc"] = btc2
            state["eur_spent"] = eur_spend
            state["sl_price"] = stop_price
            state["tp_price"] = tp_price
            state["mode"] = mode
            state["last_event"] = "entry_opened"
            state["last_error"] = None

            append_trade({
                "ts": now_iso(),
                "event": "ENTRY",
                "symbol": symbol,
                "mode": mode,
                "reason": "BUY_SIGNAL",
                "entry_price": ask,
                "exit_price": None,
                "qty_btc": btc2,
                "eur_spent": eur_spend,
                "sl_price": stop_price,
                "tp_price": tp_price,
                "pnl_est": None,
                "equity_est": equity_est,
            })

            send_telegram(
                f"🛡 Protezioni {mode}\\n"
                f"SL reale: {stop_price:.2f}\\n"
                f"TP software: {tp_price:.2f}"
            )

            IN_CRITICAL = False
            attempt = 0
            save_state(state)
            time.sleep(10)

        except Exception as e:
            attempt += 1
            w = backoff_sleep(attempt)
            state["last_error"] = f"{type(e).__name__}: {e}"
            state["last_event"] = "runtime_exception"
            state["bot_status"] = "warning"
            save_state(state)
            send_telegram(f"⚠️ Runtime: {type(e).__name__}: {e}\\nBackoff {w:.0f}s")
            time.sleep(w)


if __name__ == "__main__":
    main()