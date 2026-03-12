
import time,yaml
from core.exchange import Kraken
from core.profit import break_even_sell
from core.telegram import send

cfg=yaml.safe_load(open("config.yaml"))

pairs=cfg["pairs"]
order_size=cfg["trading"]["order_size_eur"]
fee=cfg["trading"]["fee_rate"]
buffer=cfg["trading"]["min_profit_buffer"]
sleep=cfg["runtime"]["sleep_seconds"]

ex=Kraken()
inventory={}

send("Leviathan v5 started")

while True:

    try:

        bal=ex.balance()

        for pair in pairs:

            ticker=ex.ticker(pair)
            price=ticker["last"]

            base,quote=pair.split("/")

            eur=bal["free"].get("EUR",0)

            amount=order_size/price

            if eur>order_size:

                buy_price=price*0.998

                ex.buy(pair,buy_price,amount)

                inventory[pair]={
                    "entry":buy_price,
                    "amount":amount
                }

                send(f"BUY {pair} {buy_price}")

            if pair in inventory:

                entry=inventory[pair]["entry"]
                amount=inventory[pair]["amount"]

                target=break_even_sell(entry,fee,buffer)

                if price>target:

                    ex.sell(pair,price,amount)

                    send(f"SELL {pair} {price} profit")

                    del inventory[pair]

        time.sleep(sleep)

    except Exception as e:

        send(f"runtime error {e}")
        time.sleep(10)
