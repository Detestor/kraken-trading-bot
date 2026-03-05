from __future__ import annotations
import pandas as pd
from .indicators import atr, adx

def detect_regime(df: pd.DataFrame) -> str:
    d = df.copy()
    d["atr"] = atr(d)
    d["adx"] = adx(d)
    latest = d.iloc[-1]
    adx_v = float(latest["adx"])
    atr_v = float(latest["atr"])
    price = float(latest["close"])
    vr = atr_v / price if price else 0.0
    if adx_v > 25:
        return "TREND"
    if adx_v < 20 and vr < 0.01:
        return "RANGE"
    return "CHAOS"
