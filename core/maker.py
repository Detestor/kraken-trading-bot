from .spread import adaptive_spread
from .inventory import split_pair, can_place_buy, can_place_sell, inventory_too_large
from .utils import safe_float, now_iso

class LeviathanMaker:
    def __init__(self, executor, config, append_trade):
        self.ex=executor; self.cfg=config; self.append_trade=append_trade
    def cancel_old_orders(self, pair):
        for o in self.ex.open_orders(pair):
            try: self.ex.cancel(o["id"], pair)
            except Exception: pass
    def place_grid_for_pair(self, pair, balance):
        ticker=self.ex.ticker(pair); last=safe_float(ticker.get("last"),0.0)
        if last<=0: return {"pair":pair,"orders":0,"spread":None,"note":"invalid_price"}
        base,quote=split_pair(pair)
        spread=adaptive_spread(ticker,float(self.cfg["trading"]["base_spread"]),float(self.cfg["trading"]["max_spread"]))
        order_size_quote=float(self.cfg["trading"]["order_size_quote"]); amount_base=order_size_quote/last
        grid_levels=int(self.cfg["trading"]["grid_levels"]); max_inventory_quote=float(self.cfg["risk"]["max_inventory_quote"])
        created=0; sell_only=inventory_too_large(balance,base,last,max_inventory_quote)
        for level in range(1,grid_levels+1):
            s=spread*level; buy_price=last*(1-s); sell_price=last*(1+s)
            if (not sell_only) and can_place_buy(balance,quote,order_size_quote):
                try:
                    self.ex.limit_buy(pair,buy_price,amount_base); created+=1
                    self.append_trade({"ts":now_iso(),"pair":pair,"event":"PLACE","side":"BUY_LIMIT","price":round(buy_price,8),"amount":round(amount_base,12),"grid_level":level,"spread_used":round(s,6),"note":"maker_grid_buy"})
                except Exception: pass
            if can_place_sell(balance,base,amount_base):
                try:
                    self.ex.limit_sell(pair,sell_price,amount_base); created+=1
                    self.append_trade({"ts":now_iso(),"pair":pair,"event":"PLACE","side":"SELL_LIMIT","price":round(sell_price,8),"amount":round(amount_base,12),"grid_level":level,"spread_used":round(s,6),"note":"maker_grid_sell"})
                except Exception: pass
        return {"pair":pair,"orders":created,"spread":round(spread,6),"note":"ok"}
