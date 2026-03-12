
import os
import ccxt
from dotenv import load_dotenv
load_dotenv()

class Kraken:

    def __init__(self):
        self.ex = ccxt.kraken({
            "apiKey": os.getenv("KRAKEN_API_KEY"),
            "secret": os.getenv("KRAKEN_API_SECRET"),
            "enableRateLimit": True
        })

    def ticker(self,pair):
        return self.ex.fetch_ticker(pair)

    def balance(self):
        return self.ex.fetch_balance()

    def open_orders(self,pair=None):
        if pair:
            return self.ex.fetch_open_orders(pair)
        return self.ex.fetch_open_orders()

    def buy(self,pair,price,amount):
        return self.ex.create_limit_buy_order(pair,amount,price)

    def sell(self,pair,price,amount):
        return self.ex.create_limit_sell_order(pair,amount,price)

    def cancel(self,id,pair):
        return self.ex.cancel_order(id,pair)
