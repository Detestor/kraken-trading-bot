from .utils import safe_float
from .profit import break_even_sell


def estimate_equity(balance: dict, pair: str, last_price: float) -> float:
    base, quote = pair.split("/")
    q = safe_float(balance.get("total", {}).get(quote, 0.0))
    b = safe_float(balance.get("total", {}).get(base, 0.0))
    return round(q + (b * last_price), 4)


def inventory_snapshot(balance: dict, pairs: list[str]) -> dict:
    out = {}
    for pair in pairs:
        base, quote = pair.split("/")
        out[quote] = safe_float(balance.get("total", {}).get(quote, 0.0))
        out[base]  = safe_float(balance.get("total", {}).get(base, 0.0))
    return out


# FIX #4 — riceve il dict di tickers già fetched in batch, non fa chiamate singole
def choose_pair(tickers: dict, pairs: list[str]) -> str | None:
    """
    Sceglie il pair con il miglior score:
    score = (volatilità 24h relativa) × volume_quote
    Maggiore volatilità + volume = più chance di fill rapido.
    """
    best       = None
    best_score = -1.0
    for pair in pairs:
        t = tickers.get(pair)
        if not t:
            continue
        last = safe_float(t.get("last"), 0.0)
        high = safe_float(t.get("high"), 0.0)
        low  = safe_float(t.get("low"),  0.0)
        qv   = safe_float(t.get("quoteVolume"), 0.0)
        if last <= 0:
            continue
        score = (abs(high - low) / last) * max(1.0, qv)
        if score > best_score:
            best_score = score
            best       = pair
    return best


def compute_order_amount(pair: str, price: float, order_size_eur: float, markets: dict) -> float:
    min_amount = safe_float(markets[pair]["limits"]["amount"]["min"], 0.0)
    return max(order_size_eur / price, min_amount)


def can_open_new_position(balance: dict, order_size_eur: float, active_order_id) -> bool:
    eur_free = safe_float(balance.get("free", {}).get("EUR", 0.0))
    return (active_order_id is None) and (eur_free >= order_size_eur)


def has_inventory(balance: dict, pair: str) -> bool:
    base, _ = pair.split("/")
    return safe_float(balance.get("total", {}).get(base, 0.0)) > 0


def build_buy_price(last_price: float, entry_discount: float) -> float:
    return last_price * (1 - entry_discount)


def build_target(entry_price: float, fee_rate: float, min_profit_buffer: float, spread_multiplier: float) -> float:
    # FIX #2 — spread_multiplier ora è un moltiplicatore sul buffer, non sul target intero.
    # Con spread_multiplier=1.0 vendi esattamente al break-even + buffer.
    # Con 1.0 < x <= 1.5 aggiungi un ulteriore margine (ma rallenti i fill).
    be = break_even_sell(entry_price, fee_rate, min_profit_buffer)
    extra = (be - entry_price) * (spread_multiplier - 1.0)
    return be + extra
