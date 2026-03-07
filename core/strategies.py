from __future__ import annotations

import pandas as pd
from .indicators import rsi


def signal_trend(df: pd.DataFrame) -> str | None:
    d = df.copy()
    d = d.assign(
        ema20=d["close"].ewm(span=20).mean(),
        ema50=d["close"].ewm(span=50).mean(),
        ema200=d["close"].ewm(span=200).mean(),
    )

    latest = d.iloc[-1]
    prev = d.iloc[-2]

    if latest["ema50"] > latest["ema200"] and latest["close"] > latest["ema50"]:
        dist = abs(latest["close"] - latest["ema20"]) / latest["close"]
        if dist < 0.003 and latest["close"] > prev["high"]:
            return "BUY"

    return None


def signal_range(df: pd.DataFrame) -> str | None:
    d = df.copy()
    d = d.assign(
        rsi_val=rsi(d["close"], 14),
    )

    if float(d.iloc[-1]["rsi_val"]) < 30:
        return "BUY"

    return None