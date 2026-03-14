
from .utils import safe_float
from .profit import break_even_sell
def estimate_equity(balance, pair, last_price):
    base, quote = pair.split("/")
    q = safe_float(balance.get("total", {}).get(quote, 0.0))
    b = safe_float(balance.get("total", {}).get(base, 0.0))
    return round(q + (b * last_price), 4)
def inventory_snapshot(balance, pairs):
    out = {}
    for pair in pairs:
        base, quote = pair.split("/")
        out[quote] = safe_float(balance.get("total", {}).get(quote, 0.0))
        out[base] = safe_float(balance.get("total", {}).get(base, 0.0))
    return out
def choose_pair(ex, pairs):
    best = None
    best_score = -1
    for pair in pairs:
        try:
            t = ex.ticker(pair)
            last = safe_float(t.get("last"), 0.0)
            high = safe_float(t.get("high"), 0.0)
            low = safe_float(t.get("low"), 0.0)
            qv = safe_float(t.get("quoteVolume"), 0.0)
            if last <= 0:
                continue
            score = (abs(high-low) / last) * max(1.0, qv)
            if score > best_score:
                best_score = score
                best = pair
        except Exception:
            pass
    return best
def compute_order_amount(pair, price, order_size_eur, markets):
    min_amount = safe_float(markets[pair]["limits"]["amount"]["min"], 0.0)
    return max(order_size_eur / price, min_amount)
def can_open_new_position(balance, order_size_eur, active_pair):
    eur_free = safe_float(balance.get("free", {}).get("EUR", 0.0))
    return (active_pair is None) and (eur_free >= order_size_eur)
def has_inventory(balance, pair):
    base, _ = pair.split("/")
    return safe_float(balance.get("total", {}).get(base, 0.0)) > 0
def build_buy_price(last_price, entry_discount):
    return last_price * (1 - entry_discount)
def build_target(entry_price, fee_rate, min_profit_buffer, spread_multiplier):
    return break_even_sell(entry_price, fee_rate, min_profit_buffer) * spread_multiplier
