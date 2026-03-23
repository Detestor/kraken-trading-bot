"""
Modulo che gestisce il ciclo di vita di una singola posizione:
  PENDING  → ordine BUY aperto, non ancora filled
  OPEN     → BUY filled, in attesa di raggiungere target o stop
  CLOSING  → ordine SELL/STOP aperto
  CLOSED   → posizione chiusa (rimossa dal dict positions)

Struttura dati di una posizione (dentro state["positions"][pair]):
{
    "status":          "pending" | "open" | "closing",
    "buy_order_id":    str | None,
    "sell_order_id":   str | None,
    "placed_ts":       float,        # timestamp piazzamento BUY
    "entry_price":     float,        # prezzo fill reale (aggiornato da pending → open)
    "entry_amount":    float,
    "target_price":    float,        # target take-profit (fisso al fill)
    "stop_price":      float,        # prezzo stop-loss limite
    "peak_price":      float,        # massimo raggiunto (per trailing stop)
    "trailing_trigger":float | None, # prezzo a cui scatta il trailing stop
}
"""

from .utils import safe_float, now_ts
from .profit import net_profit_eur, break_even_sell


def new_position(pair: str, buy_order_id: str, buy_price: float, amount: float,
                 fee_rate: float, min_profit_buffer: float,
                 stop_loss_pct: float, trailing_distance_pct: float) -> dict:
    target = break_even_sell(buy_price, fee_rate, min_profit_buffer)
    stop   = buy_price * (1 - stop_loss_pct)
    return {
        "status":           "pending",
        "buy_order_id":     buy_order_id,
        "sell_order_id":    None,
        "placed_ts":        now_ts(),
        "entry_price":      buy_price,   # sarà aggiornato al fill price reale
        "entry_amount":     amount,
        "target_price":     target,
        "stop_price":       stop,
        "peak_price":       buy_price,
        "trailing_trigger": None,
        "trailing_distance_pct": trailing_distance_pct,
    }


def update_trailing(pos: dict, current_price: float) -> dict:
    """
    Aggiorna il peak e il trigger del trailing stop.
    Il trailing trigger è: peak * (1 - trailing_distance_pct)
    """
    if current_price > pos["peak_price"]:
        pos["peak_price"]      = current_price
        dist                   = pos.get("trailing_distance_pct", 0.003)
        pos["trailing_trigger"] = pos["peak_price"] * (1 - dist)
    return pos


def should_take_profit(pos: dict, current_price: float) -> bool:
    """Take-profit fisso: prezzo >= target."""
    return current_price >= pos["target_price"]


def should_trailing_stop(pos: dict, current_price: float) -> bool:
    """
    Trailing stop: scatta solo se:
    1. Il prezzo ha superato almeno una volta il target (peak > target)
    2. Il prezzo è sceso sotto il trailing trigger
    """
    trigger = pos.get("trailing_trigger")
    if trigger is None:
        return False
    peak_above_target = pos["peak_price"] >= pos["target_price"]
    return peak_above_target and (current_price <= trigger)


def should_stop_loss(pos: dict, current_price: float) -> bool:
    """Stop-loss fisso: prezzo <= stop_price."""
    return current_price <= pos["stop_price"]


def position_pnl(pos: dict, current_price: float, fee_rate: float) -> float:
    """P&L non realizzato in EUR."""
    return net_profit_eur(
        pos["entry_price"], current_price, pos["entry_amount"], fee_rate
    )


def position_summary(pair: str, pos: dict, current_price: float, fee_rate: float) -> str:
    pnl    = position_pnl(pos, current_price, fee_rate)
    status = pos["status"]
    sign   = "+" if pnl >= 0 else ""
    return (
        f"📌 {pair} [{status}]\n"
        f"   Entry:   {pos['entry_price']:.8f}\n"
        f"   Qty:     {pos['entry_amount']:.8f}\n"
        f"   Target:  {pos['target_price']:.8f}\n"
        f"   Stop:    {pos['stop_price']:.8f}\n"
        f"   Peak:    {pos['peak_price']:.8f}\n"
        f"   Last:    {current_price:.8f}\n"
        f"   P&L:     {sign}{pnl:.4f} EUR"
    )
