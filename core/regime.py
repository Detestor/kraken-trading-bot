from .indicators import atr, adx
def detect_regime(df):
    d = df.copy()
    d = d.assign(atr_val=atr(d), adx_val=adx(d))
    x = d.iloc[-1]
    adx_v = float(x["adx_val"]); atr_v = float(x["atr_val"]); price = float(x["close"])
    vr = atr_v / price if price else 0.0
    if adx_v > 22:
        return "TREND"
    if adx_v < 18 and vr < 0.008:
        return "RANGE"
    return "CHAOS"
