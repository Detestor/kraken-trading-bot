from __future__ import annotations

def safe_float(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default

def backoff_sleep(attempt: int, base: float = 2.0, cap: float = 60.0) -> float:
    return min(cap, base * (2 ** max(0, attempt - 1)))
