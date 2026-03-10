
import time
from maker import MarketMaker
from config import PAIRS, SLEEP_SECONDS

maker = MarketMaker()

print("KrakenBot Leviathan started")

while True:

    for pair in PAIRS:

        try:
            maker.run_pair(pair)
        except Exception as e:
            print("pair error", pair, e)

    time.sleep(SLEEP_SECONDS)
