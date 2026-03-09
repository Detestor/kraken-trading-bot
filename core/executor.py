import os, ccxt
from dotenv import load_dotenv

class KrakenExecutor:
    def __init__(self):
        load_dotenv()
        api_key = os.getenv("KRAKEN_API_KEY","").strip()
        secret = os.getenv("KRAKEN_API_SECRET","").strip()
        if not api_key or not secret:
            raise ValueError("Missing KRAKEN_API_KEY / KRAKEN_API_SECRET env vars")
        self.ex = ccxt.kraken({"apiKey": api_key, "secret": secret, "enableRateLimit": True})

    def fetch_balance(self):
        return self.ex.fetch_balance()
    def fetch_ticker(self, symbol):
        return self.ex.fetch_ticker(symbol)
    def fetch_open_orders(self, symbol):
        return self.ex.fetch_open_orders(symbol)
    def cancel_order(self, order_id, symbol):
        return self.ex.cancel_order(order_id, symbol)
    def p(self, symbol, price):
        return self.ex.price_to_precision(symbol, price)
    def a(self, symbol, amount):
        return self.ex.amount_to_precision(symbol, amount)
    def create_market_buy(self, symbol, amount_base):
        return self.ex.create_order(symbol, "market", "buy", self.a(symbol, amount_base))
    def create_market_sell(self, symbol, amount_base):
        return self.ex.create_order(symbol, "market", "sell", self.a(symbol, amount_base))
    def create_stop_loss_sell(self, symbol, amount_base, stop_price):
        amt = self.a(symbol, amount_base)
        trigger = float(stop_price)
        limit_exec = trigger * 0.999
        trigger_s = self.p(symbol, trigger)
        limit_s = self.p(symbol, limit_exec)
        params = {"trading_agreement":"agree", "price": trigger_s, "price2": limit_s}
        return self.ex.create_order(symbol, "stop-loss-limit", "sell", amt, trigger_s, params=params)
