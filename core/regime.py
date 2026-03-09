from __future__ import annotations
import pandas as pd
from .indicators import atr, adx

def detect_regime(df: pd.DataFrame) -> str:
    d = df.copy()
    d = d.assign(
        atr_val=atr(d),
        adx_val=adx(d),
    )
    latest = d.iloc[-1]
    adx_v = float(latest["adx_val"])
    atr_v = float(latest["atr_val"])
    price = float(latest["close"])
    vr = atr_v / price if price else 0.0
    if adx_v > 25:
        return "TREND"
    if adx_v < 20 and vr < 0.01:
        return "RANGE"
    return "CHAOS"
