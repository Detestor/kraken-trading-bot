
from datetime import datetime

def now():
    return datetime.utcnow().isoformat()

def safe_float(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d
