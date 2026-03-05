from core.executor import KrakenExecutor
from core.utils import safe_float
SYMBOL="BTC/EUR"
def main():
    ex=KrakenExecutor()
    b=ex.fetch_balance()
    btc=safe_float(b.get("free",{}).get("BTC",0.0))
    eur=safe_float(b.get("free",{}).get("EUR",0.0))
    print("=== CLOSE BTC NOW ===")
    print("BTC free:", f"{btc:.8f}")
    print("EUR free:", f"{eur:.2f}")
    try:
        oo=ex.fetch_open_orders(SYMBOL)
        for o in oo:
            if o.get("side")=="sell" and o.get("id"):
                ex.cancel_order(o["id"], SYMBOL)
        print("Ordini SELL aperti cancellati (se presenti).")
    except Exception as e:
        print("Warning cancel:", e)
    if btc<=1e-7:
        print("Niente BTC da chiudere."); return
    res=ex.create_market_sell(SYMBOL, btc)
    print("SELL MARKET inviato."); print(res)
if __name__=="__main__":
    main()
