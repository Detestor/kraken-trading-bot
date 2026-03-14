
def break_even_sell(entry_price, fee_rate, buffer_rate):
    return entry_price * (1 + (2 * fee_rate) + buffer_rate)
