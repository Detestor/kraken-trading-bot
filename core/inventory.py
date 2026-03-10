from .utils import safe_float

def split_pair(pair): return pair.split("/")
def quote_total(balance,quote): return safe_float(balance.get("total",{}).get(quote,0.0))
def base_total(balance,base): return safe_float(balance.get("total",{}).get(base,0.0))
def base_free(balance,base): return safe_float(balance.get("free",{}).get(base,0.0))
def inventory_snapshot(balance,pairs):
    assets={}
    for pair in pairs:
        base,quote=split_pair(pair)
        assets[quote]=safe_float(balance.get("total",{}).get(quote,0.0))
        assets[base]=safe_float(balance.get("total",{}).get(base,0.0))
    return assets
def can_place_buy(balance,quote,order_size_quote): return quote_total(balance,quote)>=order_size_quote
def can_place_sell(balance,base,amount_base): return base_free(balance,base)>=amount_base
def inventory_too_large(balance,base,pair_price,max_inventory_quote): return base_total(balance,base)*pair_price > max_inventory_quote
