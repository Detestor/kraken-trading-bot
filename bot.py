
import time, yaml
from core.exchange import Kraken
from core.profit import break_even
from core.telegram import send
from core.utils import safe_float

cfg=yaml.safe_load(open("config.yaml"))

pairs=cfg["pairs"]
order_size=cfg["trading"]["order_size_eur"]
fee=cfg["trading"]["fee_rate"]
buffer=cfg["trading"]["min_profit_buffer"]
spread_mult=cfg["trading"]["spread_multiplier"]
sleep=cfg["runtime"]["sleep_seconds"]

ex=Kraken()

inventory={}

send("🐋 Leviathan v6 Anti‑Bleed Engine started")

markets=ex.markets()

while True:

    try:

        bal=ex.balance()

        for pair in pairs:

            ticker=ex.ticker(pair)
            price=safe_float(ticker["last"])

            base,quote=pair.split("/")

            eur=bal["free"].get("EUR",0)

            min_vol=markets[pair]["limits"]["amount"]["min"]

            amount=max(order_size/price, min_vol)

            buy_price=price*(1-0.002)

            if eur>order_size and pair not in inventory:

                ex.buy(pair,buy_price,amount)

                inventory[pair]={
                    "entry":buy_price,
                    "amount":amount
                }

                send(f"BUY {pair} {buy_price}")

            if pair in inventory:

                entry=inventory[pair]["entry"]
                amount=inventory[pair]["amount"]

                target=break_even(entry,fee,buffer)*spread_mult

                if price>=target:

                    ex.sell(pair,price,amount)

                    send(f"SELL {pair} {price} net profit")

                    del inventory[pair]

        time.sleep(sleep)

    except Exception as e:

        send(f"runtime error {e}")
        time.sleep(10)
