from __future__ import annotations
import os, sys, time, signal
from rich import print
from core.config import load_config
from core.datafeed import DataFeed
from core.executor import KrakenExecutor
from core.notifier import send_telegram
from core.regime import detect_regime
from core.indicators import atr
from core.strategies import signal_trend, signal_range
from core.utils import safe_float, backoff_sleep
from core.ai_manager import ai_enabled, ai_recommendation

LOCK_FILE = "bot.lock"
IN_CRITICAL = False
STATE = {"tp_price": None, "mode": None}

def pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0); return True
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
            try: os.remove(LOCK_FILE)
            except Exception: pass
    open(LOCK_FILE,"w",encoding="utf-8").write(str(os.getpid()))

def release_lock():
    try:
        if os.path.exists(LOCK_FILE): os.remove(LOCK_FILE)
    except Exception:
        pass

def handle_exit(signum, frame):
    global IN_CRITICAL
    if IN_CRITICAL:
        send_telegram("⚠️ Tentata chiusura durante operazione: bloccata.")
        return
    send_telegram("🛑 Bot chiuso.")
    release_lock()
    sys.exit(0)

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

def bar_key(df):
    cols = list(df.columns)
    if "ts" in cols: return df.iloc[-1]["ts"]
    if "timestamp" in cols: return df.iloc[-1]["timestamp"]
    if "datetime" in cols: return df.iloc[-1]["datetime"]
    try: return df.index[-1]
    except Exception: return None

def main():
    cfg = load_config("config.yaml")
    symbol = cfg.get("symbol","BTC/EUR")
    timeframe = cfg.get("timeframe","1h")
    limit = int(cfg.get("ohlcv_limit",500))
    spend_pct = float(cfg.get("spend_pct",0.50))
    min_trade_eur = float(cfg.get("min_trade_eur",6.0))

    A = cfg.get("strategy_A",{})
    B = cfg.get("strategy_B",{})
    A_sl, A_tp = float(A.get("sl_atr",1.5)), float(A.get("tp_atr",3.0))
    B_sl, B_tp = float(B.get("sl_atr",1.0)), float(B.get("tp_atr",1.2))

    acquire_lock()
    send_telegram("🚀 KrakenBotVPS avviato. (SL reale + TP software)")

    feed = DataFeed()
    ex = KrakenExecutor()

    last_k = None
    last_reg = None
    attempt = 0

    print(f"LIVE {symbol} tf={timeframe} | spend_pct={spend_pct:.2f} | min_trade={min_trade_eur:.2f}")

    global IN_CRITICAL
    while True:
        try:
            bal = ex.fetch_balance()
            eur = safe_float(bal.get("free",{}).get("EUR",0.0))
            btc = safe_float(bal.get("free",{}).get("BTC",0.0))
            in_pos = btc > 1e-7

            t = ex.fetch_ticker(symbol)
            last = safe_float(t.get("last",0.0))
            ask = safe_float(t.get("ask", last))

            print(f"status | price={last:.2f} | EUR={eur:.2f} | BTC={btc:.8f}")

            if in_pos and STATE["tp_price"] is not None and last >= float(STATE["tp_price"]):
                IN_CRITICAL = True
                send_telegram(f"🎯 TP software ({STATE['mode']}) — vendo market @ {last:.2f}")
                ex.create_market_sell(symbol, btc)
                STATE["tp_price"] = None
                STATE["mode"] = None
                IN_CRITICAL = False
                time.sleep(10)
                continue

            df = feed.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            k = bar_key(df)
            if k == last_k:
                time.sleep(60); continue
            last_k = k

            reg = detect_regime(df)
            if reg != last_reg:
                send_telegram(f"🧭 Regime: {reg} (tf={timeframe})")
                last_reg = reg

            if in_pos:
                time.sleep(10); continue
            if reg == "CHAOS":
                time.sleep(60); continue

            if reg == "TREND":
                sig = signal_trend(df); sl_m, tp_m, mode = A_sl, A_tp, "A/TREND"
            else:
                sig = signal_range(df); sl_m, tp_m, mode = B_sl, B_tp, "B/RANGE"

            if ai_enabled():
                try:
                    send_telegram(ai_recommendation({"symbol":symbol,"timeframe":timeframe,"regime":reg,"price":last,"signal":sig})[:3500])
                except Exception:
                    pass

            if sig != "BUY":
                time.sleep(60); continue

            eur_spend = min(eur * spend_pct, max(0.0, eur - 0.5))
            if eur_spend < min_trade_eur:
                send_telegram(f"⚠️ Setup {mode} ma EUR insufficienti (free={eur:.2f}).")
                time.sleep(60); continue

            qty = eur_spend / ask
            d2 = df.copy()
            d2["atr"] = atr(d2)
            atr_v = safe_float(d2.iloc[-1]["atr"], 0.0)
            if atr_v <= 0:
                time.sleep(60); continue

            stop_price = ask - (sl_m * atr_v)
            tp_price = ask + (tp_m * atr_v)

            IN_CRITICAL = True
            ex.create_market_buy(symbol, qty)
            send_telegram(f"🟢 BUY {symbol} ({mode})\nSpesa: {eur_spend:.2f}€\nPrezzo: {ask:.2f}")
            time.sleep(3)

            bal2 = ex.fetch_balance()
            btc2 = safe_float(bal2.get("free",{}).get("BTC",0.0))
            if btc2 <= 1e-7:
                send_telegram("⚠️ BUY fatto ma BTC non visibile (attendo).")
                IN_CRITICAL = False
                time.sleep(30); continue

            try:
                ex.create_stop_loss_sell(symbol, btc2, stop_price)
            except Exception as e:
                send_telegram(f"❌ ERRORE SL: {e}\nChiudo per sicurezza.")
                ex.create_market_sell(symbol, btc2)
                IN_CRITICAL = False
                time.sleep(30); continue

            STATE["tp_price"] = tp_price
            STATE["mode"] = mode
            send_telegram(f"🛡 Protezioni {mode}\nSL reale: {stop_price:.2f}\nTP software: {tp_price:.2f}")
            IN_CRITICAL = False

            attempt = 0
            time.sleep(10)

        except Exception as e:
            attempt += 1
            w = backoff_sleep(attempt)
            send_telegram(f"⚠️ Runtime: {type(e).__name__}: {e}\nBackoff {w:.0f}s")
            time.sleep(w)

if __name__ == "__main__":
    main()
