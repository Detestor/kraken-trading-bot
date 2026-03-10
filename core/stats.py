from .utils import safe_float

def estimate_equity(balance, executor, pairs):
    total=0.0; seen=set()
    for pair in pairs:
        base,quote=pair.split("/")
        if quote not in seen:
            total+=safe_float(balance.get("total",{}).get(quote,0.0)); seen.add(quote)
        if base not in seen:
            try: px=safe_float(executor.ticker(pair).get("last"),0.0)
            except Exception: px=0.0
            total+=safe_float(balance.get("total",{}).get(base,0.0))*px; seen.add(base)
    return round(total,4)
