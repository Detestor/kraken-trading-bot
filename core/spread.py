from .utils import safe_float

def adaptive_spread(ticker, base_spread, max_spread):
    last=safe_float(ticker.get("last"),0.0); high=safe_float(ticker.get("high"),0.0); low=safe_float(ticker.get("low"),0.0)
    if last<=0: return base_spread
    volatility=abs(high-low)/last
    spread=base_spread+(volatility*0.50)
    if spread>max_spread: spread=max_spread
    if spread<base_spread: spread=base_spread
    return spread
