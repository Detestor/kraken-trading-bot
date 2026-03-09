import os, sys, time, signal
from datetime import datetime, timezone
from rich import print
from core.config import load_config
from core.datafeed import DataFeed
from core.executor import KrakenExecutor
from core.notifier import send_telegram, get_telegram_updates, get_allowed_chat_id
from core.regime import detect_regime
from core.indicators import atr
from core.strategies import signal_fast, signal_scalper
from core.utils import safe_float, backoff_sleep
from core.ai_manager import ai_enabled, ai_recommendation
from core.state_store import load_state, save_state, append_trade, get_last_trades, format_status_message, format_last_trades_message

LOCK_FILE = "bot.lock"
IN_CRITICAL = False
FORCE_CLOSE_REQUEST = False
HYDRA_MODE_OVERRIDE = None

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def pid_exists(pid):
    try:
        os.kill(pid, 0); return True
    except Exception:
        return False

def acquire_lock():
    if os.path.exists(LOCK_FILE):
        try: pid = int(open(LOCK_FILE,"r",encoding="utf-8").read().strip() or "0")
        except Exception: pid = 0
        if pid and pid_exists(pid):
            print("[red]Bot già in esecuzione![/red]"); sys.exit(1)
        else:
            try: os.remove(LOCK_FILE)
            except Exception: pass
    open(LOCK_FILE,"w",encoding="utf-8").write(str(os.getpid()))

def release_lock():
    try:
        if os.path.exists(LOCK_FILE): os.remove(LOCK_FILE)
    except Exception: pass

def handle_exit(signum, frame):
    global IN_CRITICAL
    if IN_CRITICAL:
        send_telegram("⚠️ Tentata chiusura durante operazione: bloccata."); return
    state = load_state()
    state["bot_status"] = "stopped"; state["last_event"] = "manual_stop"; save_state(state)
    send_telegram("🛑 Bot chiuso.")
    release_lock(); sys.exit(0)

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

def bar_key(df):
    cols = list(df.columns)
    if "ts" in cols: return df.iloc[-1]["ts"]
    try: return df.index[-1]
    except Exception: return None

def position_context(bal, open_orders):
    eur_free = safe_float(bal.get("free", {}).get("EUR", 0.0))
    eur_total = safe_float(bal.get("total", {}).get("EUR", eur_free))
    btc_free = safe_float(bal.get("free", {}).get("BTC", 0.0))
    btc_total = safe_float(bal.get("total", {}).get("BTC", btc_free))
    sell_orders = [o for o in open_orders if o.get("side") == "sell"]
    in_pos = (btc_total > 1e-7) or (len(sell_orders) > 0)
    return {"eur_free": eur_free, "eur_total": eur_total, "btc_free": btc_free, "btc_total": btc_total, "sell_orders": sell_orders, "in_pos": in_pos}

def choose_hydra_mode(regime, override):
    if override in ("FAST","SCALPER"):
        return override
    if regime in ("TREND","RANGE"):
        return "SCALPER"
    return "FAST"

def process_telegram_commands(state):
    global FORCE_CLOSE_REQUEST, HYDRA_MODE_OVERRIDE
    allowed_chat_id = get_allowed_chat_id()
    offset = int(state.get("tg_offset", 0))
    updates = get_telegram_updates(offset=offset, timeout=0)
    if not updates: return state
    max_update_id = offset
    for upd in updates:
        update_id = upd.get("update_id", 0)
        if update_id >= max_update_id: max_update_id = update_id + 1
        msg = upd.get("message", {})
        chat = msg.get("chat", {})
        chat_id = str(chat.get("id", ""))
        text = (msg.get("text") or "").strip().lower()
        if not text or chat_id != allowed_chat_id: continue
        if text == "/status":
            send_telegram(format_status_message(state))
        elif text == "/lasttrades":
            send_telegram(format_last_trades_message(get_last_trades(5)))
        elif text == "/closepositionnow":
            FORCE_CLOSE_REQUEST = True
            send_telegram("🧨 Richiesta ricevuta: chiusura posizione appena possibile.")
        elif text == "/mode auto":
            HYDRA_MODE_OVERRIDE = None; send_telegram("🧠 Hydra mode impostato su AUTO.")
        elif text == "/mode fast":
            HYDRA_MODE_OVERRIDE = "FAST"; send_telegram("⚡ Hydra mode impostato su FAST.")
        elif text == "/mode scalper":
            HYDRA_MODE_OVERRIDE = "SCALPER"; send_telegram("🦂 Hydra mode impostato su SCALPER.")
        elif text == "/ping":
            send_telegram("🏓 pong")
        elif text == "/help":
            send_telegram(
                "Comandi disponibili:\n"
                "/status - stato completo del bot\n"
                "/lasttrades - ultimi trade registrati\n"
                "/closepositionnow - chiude la posizione aperta appena possibile\n"
                "/mode auto - Hydra decide\n"
                "/mode fast - usa solo FAST\n"
                "/mode scalper - usa solo SCALPER\n"
                "/ping - test rapido\n"
                "/help - aiuto"
            )
    state["tg_offset"] = max_update_id
    return state

def main():
    global IN_CRITICAL, FORCE_CLOSE_REQUEST
    cfg = load_config("config.yaml"); state = load_state()
    symbol = cfg.get("symbol","BTC/EUR"); timeframe = cfg.get("timeframe","1m"); limit = int(cfg.get("ohlcv_limit",500))
    spend_pct = float(cfg.get("spend_pct",0.50)); min_trade_eur = float(cfg.get("min_trade_eur",6.0))
    fast_cfg = cfg.get("fast", {}); scalper_cfg = cfg.get("scalper", {})
    fast_sl, fast_tp = float(fast_cfg.get("sl_atr",0.7)), float(fast_cfg.get("tp_atr",1.1))
    scalper_sl, scalper_tp = float(scalper_cfg.get("sl_atr",0.35)), float(scalper_cfg.get("tp_atr",0.55))

    state["symbol"] = symbol; state["timeframe"] = timeframe; state["bot_status"] = "running"; save_state(state)
    acquire_lock(); send_telegram("🚀 KrakenBot Hydra avviato. (1m, FAST + SCALPER + /closepositionnow)")
    feed = DataFeed(); ex = KrakenExecutor()
    last_k = state.get("last_bar_key"); last_reg = state.get("regime"); attempt = 0
    print(f"LIVE HYDRA {symbol} tf={timeframe} | spend_pct={spend_pct:.2f} | min_trade={min_trade_eur:.2f}")

    while True:
        try:
            state = process_telegram_commands(state)
            bal = ex.fetch_balance(); open_orders = ex.fetch_open_orders(symbol)
            ctx = position_context(bal, open_orders)
            eur_free = ctx["eur_free"]; eur_total = ctx["eur_total"]; btc_free = ctx["btc_free"]; btc_total = ctx["btc_total"]
            in_pos = ctx["in_pos"]; sell_orders = ctx["sell_orders"]

            t = ex.fetch_ticker(symbol); last = safe_float(t.get("last",0.0)); ask = safe_float(t.get("ask",last))
            equity_est = eur_total + btc_total * last
            state["eur_free"] = eur_free; state["eur_total"] = eur_total; state["btc_free"] = btc_free; state["btc_total"] = btc_total
            state["open_sell_orders"] = len(sell_orders); state["last_price"] = last; state["equity_est"] = equity_est; state["bot_status"] = "running"; state["in_pos"] = in_pos

            print(f"status | price={last:.2f} | EUR free/total={eur_free:.2f}/{eur_total:.2f} | BTC free/total={btc_free:.8f}/{btc_total:.8f} | open_sells={len(sell_orders)}")

            if FORCE_CLOSE_REQUEST and in_pos:
                IN_CRITICAL = True
                for o in sell_orders:
                    if o.get("id"):
                        try: ex.cancel_order(o["id"], symbol)
                        except Exception: pass
                bal_fc = ex.fetch_balance()
                btc_fc = safe_float(bal_fc.get("free", {}).get("BTC", 0.0))
                if btc_fc <= 1e-7: btc_fc = safe_float(bal_fc.get("total", {}).get("BTC", 0.0))
                if btc_fc > 1e-7:
                    ex.create_market_sell(symbol, btc_fc)
                    pnl_est = None
                    try: pnl_est = ((last - float(state.get("entry_price") or 0)) * float(state.get("qty_btc") or 0))
                    except Exception: pass
                    append_trade({"ts": now_iso(), "event": "EXIT", "symbol": symbol, "mode": state.get("mode"), "reason": "FORCE_CLOSE_TELEGRAM", "entry_price": state.get("entry_price"), "exit_price": last, "qty_btc": state.get("qty_btc"), "eur_spent": state.get("eur_spent"), "sl_price": state.get("sl_price"), "tp_price": state.get("tp_price"), "pnl_est": pnl_est, "equity_est": equity_est})
                    send_telegram(f"🔴 Chiusura forzata eseguita. PnL stimato: {pnl_est if pnl_est is not None else 'n/d'}")
                FORCE_CLOSE_REQUEST = False
                state["entry_price"] = None; state["entry_ts"] = None; state["qty_btc"] = None; state["eur_spent"] = None; state["sl_price"] = None; state["tp_price"] = None; state["mode"] = None; state["last_event"] = "force_close_done"
                IN_CRITICAL = False; save_state(state); time.sleep(5); continue

            if state.get("entry_price") is not None and (not in_pos):
                pnl_est = ((last - float(state.get("entry_price") or 0)) * float(state.get("qty_btc") or 0))
                append_trade({"ts": now_iso(), "event": "EXIT", "symbol": symbol, "mode": state.get("mode"), "reason": "POSITION_CLOSED_DETECTED", "entry_price": state.get("entry_price"), "exit_price": last, "qty_btc": state.get("qty_btc"), "eur_spent": state.get("eur_spent"), "sl_price": state.get("sl_price"), "tp_price": state.get("tp_price"), "pnl_est": pnl_est, "equity_est": equity_est})
                send_telegram(f"ℹ️ Posizione chiusa rilevata. PnL stimato: {pnl_est:.2f}€")
                state["entry_price"] = None; state["entry_ts"] = None; state["qty_btc"] = None; state["eur_spent"] = None; state["sl_price"] = None; state["tp_price"] = None; state["mode"] = None; state["last_event"] = "position_closed_detected"

            if in_pos and state.get("tp_price") is not None and btc_free > 1e-7 and last >= float(state["tp_price"]):
                IN_CRITICAL = True
                send_telegram(f"🎯 TP software ({state.get('mode')}) — vendo market @ {last:.2f}")
                ex.create_market_sell(symbol, btc_free)
                pnl_est = ((last - float(state.get("entry_price") or 0)) * float(state.get("qty_btc") or 0))
                append_trade({"ts": now_iso(), "event": "EXIT", "symbol": symbol, "mode": state.get("mode"), "reason": "TP_SOFTWARE", "entry_price": state.get("entry_price"), "exit_price": last, "qty_btc": state.get("qty_btc"), "eur_spent": state.get("eur_spent"), "sl_price": state.get("sl_price"), "tp_price": state.get("tp_price"), "pnl_est": pnl_est, "equity_est": equity_est})
                state["entry_price"] = None; state["entry_ts"] = None; state["qty_btc"] = None; state["eur_spent"] = None; state["sl_price"] = None; state["tp_price"] = None; state["mode"] = None; state["last_event"] = "tp_software_exit"
                send_telegram(f"💰 Uscita TP software. PnL stimato: {pnl_est:.2f}€")
                IN_CRITICAL = False; save_state(state); time.sleep(5); continue

            df = feed.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            k = bar_key(df)
            if k == last_k:
                save_state(state); time.sleep(8); continue
            last_k = k; state["last_bar_key"] = str(k)

            reg = detect_regime(df); state["regime"] = reg
            if reg != last_reg:
                send_telegram(f"🧭 Regime: {reg} (tf={timeframe})"); last_reg = reg

            hydra_mode = choose_hydra_mode(reg, HYDRA_MODE_OVERRIDE)
            state["hydra_mode"] = hydra_mode

            if in_pos:
                state["last_event"] = "position_monitored"; save_state(state); time.sleep(5); continue
            if reg == "CHAOS":
                state["last_event"] = "chaos_skip"; save_state(state); time.sleep(8); continue

            if hydra_mode == "FAST":
                sig, mode = signal_fast(df); sl_m, tp_m = fast_sl, fast_tp
            else:
                sig, mode = signal_scalper(df); sl_m, tp_m = scalper_sl, scalper_tp

            if ai_enabled():
                try: send_telegram(ai_recommendation({"symbol":symbol,"timeframe":timeframe,"regime":reg,"price":last,"signal":sig,"mode":hydra_mode})[:3500])
                except Exception: pass

            if sig != "BUY":
                state["last_event"] = f"no_setup_{hydra_mode}"; save_state(state); time.sleep(8); continue

            eur_spend = min(eur_free * spend_pct, max(0.0, eur_free - 0.5))
            if eur_spend < min_trade_eur:
                state["last_event"] = "insufficient_funds"; save_state(state); send_telegram(f"⚠️ Setup {mode} ma EUR insufficienti (free={eur_free:.2f})."); time.sleep(8); continue

            qty = eur_spend / ask
            d2 = df.copy(); d2["atr_val"] = atr(d2)
            atr_v = safe_float(d2.iloc[-1]["atr_val"], 0.0)
            if atr_v <= 0:
                state["last_event"] = "invalid_atr"; save_state(state); time.sleep(8); continue

            stop_price = ask - (sl_m * atr_v)
            tp_price = ask + (tp_m * atr_v)

            IN_CRITICAL = True
            ex.create_market_buy(symbol, qty)
            send_telegram(f"🟢 BUY {symbol} ({mode})\nSpesa: {eur_spend:.2f}€\nPrezzo: {ask:.2f}")
            time.sleep(2)

            bal2 = ex.fetch_balance()
            btc2 = safe_float(bal2.get("free", {}).get("BTC", 0.0))
            total_btc2 = safe_float(bal2.get("total", {}).get("BTC", btc2))
            if total_btc2 <= 1e-7:
                state["last_event"] = "buy_no_btc_visible"; save_state(state); send_telegram("⚠️ BUY fatto ma BTC non visibile (attendo)."); IN_CRITICAL = False; time.sleep(8); continue

            try:
                ex.create_stop_loss_sell(symbol, total_btc2, stop_price)
            except Exception as e:
                state["last_error"] = f"SL_ERROR: {e}"; state["last_event"] = "sl_error_forced_close"; save_state(state)
                send_telegram(f"❌ ERRORE SL: {e}\nChiudo per sicurezza.")
                ex.create_market_sell(symbol, total_btc2)
                IN_CRITICAL = False; time.sleep(8); continue

            state["in_pos"] = True; state["entry_price"] = ask; state["entry_ts"] = now_iso(); state["qty_btc"] = total_btc2; state["eur_spent"] = eur_spend; state["sl_price"] = stop_price; state["tp_price"] = tp_price; state["mode"] = mode; state["last_event"] = "entry_opened"; state["last_error"] = None
            append_trade({"ts": now_iso(), "event": "ENTRY", "symbol": symbol, "mode": mode, "reason": "BUY_SIGNAL", "entry_price": ask, "exit_price": None, "qty_btc": total_btc2, "eur_spent": eur_spend, "sl_price": stop_price, "tp_price": tp_price, "pnl_est": None, "equity_est": equity_est})
            send_telegram(f"🛡 Protezioni {mode}\nSL reale: {stop_price:.2f}\nTP software: {tp_price:.2f}")
            IN_CRITICAL = False; attempt = 0; save_state(state); time.sleep(5)

        except Exception as e:
            attempt += 1; w = backoff_sleep(attempt)
            state["last_error"] = f"{type(e).__name__}: {e}"; state["last_event"] = "runtime_exception"; state["bot_status"] = "warning"; save_state(state)
            send_telegram(f"⚠️ Runtime: {type(e).__name__}: {e}\nBackoff {w:.0f}s")
            time.sleep(w)

if __name__ == "__main__":
    main()
