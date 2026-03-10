import os, ccxt
from dotenv import load_dotenv
load_dotenv()
class KrakenExecutor:
    def __init__(self):
        api_key=os.getenv("KRAKEN_API_KEY","").strip(); secret=os.getenv("KRAKEN_API_SECRET","").strip()
        if not api_key or not secret: raise ValueError("Missing KRAKEN_API_KEY / KRAKEN_API_SECRET")
        self.ex=ccxt.kraken({"apiKey":api_key,"secret":secret,"enableRateLimit":True})
    def balance(self): return self.ex.fetch_balance()
    def ticker(self,pair): return self.ex.fetch_ticker(pair)
    def open_orders(self,pair=None): return self.ex.fetch_open_orders(pair) if pair else self.ex.fetch_open_orders()
    def cancel(self,order_id,pair): return self.ex.cancel_order(order_id,pair)
    def amount_precision(self,pair,amount): return self.ex.amount_to_precision(pair,amount)
    def price_precision(self,pair,price): return self.ex.price_to_precision(pair,price)
    def limit_buy(self,pair,price,amount): return self.ex.create_limit_buy_order(pair,self.amount_precision(pair,amount),self.price_precision(pair,price))
    def limit_sell(self,pair,price,amount): return self.ex.create_limit_sell_order(pair,self.amount_precision(pair,amount),self.price_precision(pair,price))
