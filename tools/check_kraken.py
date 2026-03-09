from core.executor import KrakenExecutor
from core.utils import safe_float
SYMBOL = "BTC/EUR"
def main():
    ex = KrakenExecutor()
    t = ex.fetch_ticker(SYMBOL); b = ex.fetch_balance(); oo = ex.fetch_open_orders(SYMBOL)
    last = safe_float(t.get("last")); bid = safe_float(t.get("bid")); ask = safe_float(t.get("ask"))
    eur_f = safe_float(b.get("free", {}).get("EUR", 0.0)); eur_t = safe_float(b.get("total", {}).get("EUR", eur_f))
    btc_f = safe_float(b.get("free", {}).get("BTC", 0.0)); btc_t = safe_float(b.get("total", {}).get("BTC", btc_f))
    print("=== KRAKEN CHECK ==="); print("SYMBOL:", SYMBOL)
    print(f"PRICE last/bid/ask: {last:.2f} / {bid:.2f} / {ask:.2f}")
    print("\n=== BALANCES ===")
    print(f"EUR free/total: {eur_f:.2f} / {eur_t:.2f}")
    print(f"BTC free/total: {btc_f:.8f} / {btc_t:.8f}")
    print(f"Equity stimata: {(eur_t + btc_t * last):.2f}")
    print("\n=== OPEN ORDERS ===")
    if not oo: print("Nessun ordine aperto su BTC/EUR.")
    else:
        for o in oo: print(o)
if __name__ == "__main__":
    main()
