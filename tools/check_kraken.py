from core.executor import KrakenExecutor
from core.stats import estimate_equity

def main():
    ex = KrakenExecutor()
    bal = ex.balance()
    pairs = ["BTC/EUR", "ETH/EUR", "SOL/EUR", "XRP/EUR", "DOGE/EUR"]
    print("EUR free:", bal.get("free", {}).get("EUR"))
    print("EUR total:", bal.get("total", {}).get("EUR"))
    print("Equity stimata:", estimate_equity(bal, ex, pairs))
    print("Open orders total:", len(ex.open_orders()))

if __name__ == "__main__":
    main()
