from .indicators import rsi

def signal_fast(df):
    d = df.copy().assign(
        ema9=df["close"].ewm(span=9).mean(),
        ema21=df["close"].ewm(span=21).mean(),
        ema50=df["close"].ewm(span=50).mean(),
        rsi_val=rsi(df["close"], 14),
    )
    latest = d.iloc[-1]; prev = d.iloc[-2]
    if latest["ema9"] > latest["ema21"] > latest["ema50"]:
        if latest["close"] > latest["ema9"]:
            if prev["close"] <= prev["open"] or abs(prev["close"] - latest["ema9"]) / latest["close"] < 0.0025:
                return "BUY", "FAST/TREND"
    if float(latest["rsi_val"]) < 35 and latest["close"] >= latest["ema9"] * 0.995:
        return "BUY", "FAST/RANGE"
    return None, None

def signal_scalper(df):
    d = df.copy().assign(
        ema5=df["close"].ewm(span=5).mean(),
        ema8=df["close"].ewm(span=8).mean(),
        ema13=df["close"].ewm(span=13).mean(),
        rsi_val=rsi(df["close"], 7),
    )
    latest = d.iloc[-1]; prev = d.iloc[-2]
    if latest["ema5"] > latest["ema8"] > latest["ema13"]:
        if latest["close"] > prev["high"] * 0.9995 and float(latest["rsi_val"]) < 68:
            return "BUY", "SCALPER/MOMO"
    if float(latest["rsi_val"]) < 32 and latest["close"] > latest["ema13"] * 0.997:
        return "BUY", "SCALPER/DIP"
    return None, None
