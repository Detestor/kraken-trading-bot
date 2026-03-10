from .utils import safe_float

def pair_score(ticker):
    last=safe_float(ticker.get("last"),0.0); high=safe_float(ticker.get("high"),0.0); low=safe_float(ticker.get("low"),0.0); quote_vol=safe_float(ticker.get("quoteVolume"),0.0)
    if last<=0: return 0.0
    volatility=abs(high-low)/last
    return volatility*max(1.0, quote_vol)

def select_pairs(executor,pairs,max_pairs=3):
    scored=[]
    for pair in pairs:
        try: scored.append((pair,pair_score(executor.ticker(pair))))
        except Exception: scored.append((pair,0.0))
    scored.sort(key=lambda x:x[1], reverse=True)
    return [p for p,_ in scored[:max_pairs]]
