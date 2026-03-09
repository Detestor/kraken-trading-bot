import ccxt, pandas as pd
class DataFeed:
    def __init__(self):
        self.ex = ccxt.kraken({"enableRateLimit": True})
    def fetch_ohlcv(self, symbol, timeframe="5m", limit=500):
        ohlcv = self.ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","volume"])
