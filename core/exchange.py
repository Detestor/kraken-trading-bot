import os
import ccxt
from dotenv import load_dotenv

load_dotenv()


class Kraken:
    def __init__(self):
        api_key = os.getenv("KRAKEN_API_KEY", "").strip()
        secret  = os.getenv("KRAKEN_API_SECRET", "").strip()
        if not api_key or not secret:
            raise ValueError("Missing KRAKEN_API_KEY / KRAKEN_API_SECRET")
        self.ex = ccxt.kraken({
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
        })

    # ── Mercato ──────────────────────────────────────────────────────────────

    def load_markets(self) -> dict:
        return self.ex.load_markets()

    # FIX #4 — un'unica chiamata per tutti i ticker invece di N chiamate separate
    def fetch_tickers(self, pairs: list[str]) -> dict:
        """
        Restituisce un dict {pair: ticker} con una singola chiamata API.
        Se fetch_tickers non è disponibile, fallback a chiamate singole.
        """
        try:
            return self.ex.fetch_tickers(pairs)
        except Exception:
            result = {}
            for p in pairs:
                try:
                    result[p] = self.ex.fetch_ticker(p)
                except Exception:
                    pass
            return result

    def ticker(self, pair: str) -> dict:
        return self.ex.fetch_ticker(pair)

    def balance(self) -> dict:
        return self.ex.fetch_balance()

    # ── Precision helpers ────────────────────────────────────────────────────

    def amount_precision(self, pair: str, amount: float) -> str:
        return self.ex.amount_to_precision(pair, amount)

    def price_precision(self, pair: str, price: float) -> str:
        return self.ex.price_to_precision(pair, price)

    # ── Ordini ───────────────────────────────────────────────────────────────

    def buy_limit(self, pair: str, price: float, amount: float) -> dict:
        return self.ex.create_limit_buy_order(
            pair,
            self.amount_precision(pair, amount),
            self.price_precision(pair, price),
        )

    def sell_limit(self, pair: str, price: float, amount: float) -> dict:
        return self.ex.create_limit_sell_order(
            pair,
            self.amount_precision(pair, amount),
            self.price_precision(pair, price),
        )

    # FIX #1 — tracking e cancellazione ordini
    def get_order(self, order_id: str, pair: str) -> dict:
        return self.ex.fetch_order(order_id, pair)

    def cancel_order(self, order_id: str, pair: str) -> dict:
        return self.ex.cancel_order(order_id, pair)
