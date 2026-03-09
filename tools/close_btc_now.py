from core.executor import KrakenExecutor
from core.utils import safe_float
SYMBOL="BTC/EUR"
def main():
    ex=KrakenExecutor(); b=ex.fetch_balance()
    btc_f=safe_float(b.get("free",{}).get("BTC",0.0)); btc_t=safe_float(b.get("total",{}).get("BTC",btc_f))
    eur=safe_float(b.get("free",{}).get("EUR",0.0))
    print("=== CLOSE BTC NOW ===")
    print("BTC free/total:", f"{btc_f:.8f}", "/", f"{btc_t:.8f}")
    print("EUR free:", f"{eur:.2f}")
    try:
        oo=ex.fetch_open_orders(SYMBOL)
        for o in oo:
            if o.get("side")=="sell" and o.get("id"):
                ex.cancel_order(o["id"], SYMBOL)
        print("Ordini SELL aperti cancellati (se presenti).")
    except Exception as e:
        print("Warning cancel:", e)
    if btc_t <= 1e-7:
        print("Niente BTC da chiudere."); return
    b2=ex.fetch_balance()
    btc_use=safe_float(b2.get("free",{}).get("BTC",0.0))
    if btc_use <= 1e-7: btc_use=safe_float(b2.get("total",{}).get("BTC",0.0))
    res=ex.create_market_sell(SYMBOL, btc_use)
    print("SELL MARKET inviato."); print(res)
if __name__=="__main__":
    main()
