from .indicators import atr, adx
def detect_regime(df):
    d = df.copy().assign(atr_val=atr(df), adx_val=adx(df))
    x = d.iloc[-1]
    adx_v = float(x["adx_val"]); atr_v = float(x["atr_val"]); price = float(x["close"])
    vr = atr_v / price if price else 0.0
    if adx_v > 22:
        return "TREND"
    if adx_v < 18 and vr < 0.008:
        return "RANGE"
    return "CHAOS"
