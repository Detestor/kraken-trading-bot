def break_even_sell(entry_price: float, fee_rate: float, buffer_rate: float) -> float:
    """
    Prezzo minimo di vendita per coprire le fee di buy+sell e il buffer di profitto.
    Formula: entry * (1 + fee_buy + fee_sell + buffer)
    Con fee simmetriche: entry * (1 + 2*fee_rate + buffer_rate)
    """
    return entry_price * (1 + (2 * fee_rate) + buffer_rate)


def net_profit_eur(entry_price: float, sell_price: float, amount: float, fee_rate: float) -> float:
    """Profitto netto in EUR dopo fee di acquisto e vendita."""
    cost     = entry_price * amount * (1 + fee_rate)
    proceeds = sell_price  * amount * (1 - fee_rate)
    return round(proceeds - cost, 6)
