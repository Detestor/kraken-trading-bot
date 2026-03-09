from .indicators import rsi
def signal_trend_fast(df):
    d = df.copy()
    d = d.assign(
        ema9=d["close"].ewm(span=9).mean(),
        ema21=d["close"].ewm(span=21).mean(),
        ema50=d["close"].ewm(span=50).mean(),
    )
    latest = d.iloc[-1]; prev = d.iloc[-2]
    if latest["ema9"] > latest["ema21"] > latest["ema50"]:
        if latest["close"] > latest["ema9"]:
            if prev["close"] <= prev["open"] or abs(prev["close"] - latest["ema9"]) / latest["close"] < 0.0025:
                return "BUY"
    return None

def signal_range_fast(df):
    d = df.copy()
    d = d.assign(rsi_val=rsi(d["close"], 14), ema9=d["close"].ewm(span=9).mean())
    latest = d.iloc[-1]
    if float(latest["rsi_val"]) < 35 and latest["close"] >= latest["ema9"] * 0.995:
        return "BUY"
    return None
