
import ccxt, os
from dotenv import load_dotenv

load_dotenv()

class KrakenExecutor:

    def __init__(self):

        self.exchange = ccxt.kraken({
            "apiKey": os.getenv("KRAKEN_API_KEY"),
            "secret": os.getenv("KRAKEN_API_SECRET"),
            "enableRateLimit": True
        })

    def ticker(self, symbol):
        return self.exchange.fetch_ticker(symbol)

    def balance(self):
        return self.exchange.fetch_balance()

    def open_orders(self, symbol):
        return self.exchange.fetch_open_orders(symbol)

    def cancel_order(self, id, symbol):
        return self.exchange.cancel_order(id, symbol)

    def limit_buy(self, symbol, price, amount):
        return self.exchange.create_limit_buy_order(symbol, amount, price)

    def limit_sell(self, symbol, price, amount):
        return self.exchange.create_limit_sell_order(symbol, amount, price)
