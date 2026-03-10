
from executor import KrakenExecutor
from config import BASE_SPREAD, ORDER_SIZE_EUR

class MarketMaker:

    def __init__(self):
        self.ex = KrakenExecutor()

    def run_pair(self, pair):

        ticker = self.ex.ticker(pair)
        price = ticker["last"]

        buy_price = price * (1 - BASE_SPREAD/2)
        sell_price = price * (1 + BASE_SPREAD/2)

        amount = ORDER_SIZE_EUR / price

        print(pair, "price", price)
        print(" placing buy", buy_price)
        print(" placing sell", sell_price)

        try:
            self.ex.limit_buy(pair, buy_price, amount)
            self.ex.limit_sell(pair, sell_price, amount)
        except Exception as e:
            print("order error", e)
