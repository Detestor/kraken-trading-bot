from datetime import datetime, timezone

def safe_float(x, default=0.0):
    try: return float(x)
    except Exception: return default

def now_iso(): return datetime.now(timezone.utc).isoformat()

def backoff_sleep(attempt, base=2.0, cap=60.0): return min(cap, base * (2 ** max(0, attempt - 1)))
