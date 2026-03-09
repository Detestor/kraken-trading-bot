from __future__ import annotations
import ccxt
import pandas as pd

class DataFeed:
    def __init__(self):
        self.ex = ccxt.kraken({"enableRateLimit": True})

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 500) -> pd.DataFrame:
        ohlcv = self.ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
