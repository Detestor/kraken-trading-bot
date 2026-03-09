from __future__ import annotations
import pandas as pd

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    d = df.copy()
    up = d["high"].diff()
    down = -d["low"].diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    tr = atr(d, period)
    plus_di = 100 * (plus_dm.rolling(period).mean() / (tr + 1e-9))
    minus_di = 100 * (minus_dm.rolling(period).mean() / (tr + 1e-9))
    dx = (plus_di - minus_di).abs() / ((plus_di + minus_di) + 1e-9) * 100
    return dx.rolling(period).mean()

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    ag = gain.rolling(period).mean()
    al = loss.rolling(period).mean()
    rs = ag / (al + 1e-9)
    return 100 - (100 / (1 + rs))
