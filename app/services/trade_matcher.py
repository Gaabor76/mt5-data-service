"""
Trade reconstruction from MT5 deals and orders.

MT5 Python API returns numpy structured arrays (named tuples), not dicts.
Fields are accessed as attributes: deal.ticket, deal.position_id, etc.

Deal types:
  DEAL_TYPE_BUY = 0, DEAL_TYPE_SELL = 1, DEAL_TYPE_BALANCE = 2,
  DEAL_TYPE_CREDIT = 3, DEAL_TYPE_CHARGE = 4, DEAL_TYPE_CORRECTION = 5,
  DEAL_TYPE_BONUS = 6, DEAL_TYPE_COMMISSION = 7, DEAL_TYPE_COMMISSION_DAILY = 8,
  DEAL_TYPE_COMMISSION_MONTHLY = 9, DEAL_TYPE_COMMISSION_AGENT_DAILY = 10,
  DEAL_TYPE_COMMISSION_AGENT_MONTHLY = 11, DEAL_TYPE_INTEREST = 12,
  DEAL_TYPE_BUY_CANCELED = 13, DEAL_TYPE_SELL_CANCELED = 14,
  DEAL_TYPE_DIVIDEND = 15, DEAL_TYPE_DIVIDEND_FRANKED = 16, DEAL_TYPE_TAX = 17

Deal entry types:
  DEAL_ENTRY_IN = 0, DEAL_ENTRY_OUT = 1, DEAL_ENTRY_INOUT = 2, DEAL_ENTRY_OUT_BY = 3

Deal reasons:
  DEAL_REASON_CLIENT = 0, DEAL_REASON_MOBILE = 1, DEAL_REASON_WEB = 2,
  DEAL_REASON_EXPERT = 3, DEAL_REASON_SL = 4, DEAL_REASON_TP = 5,
  DEAL_REASON_SO = 6, DEAL_REASON_ROLLOVER = 7, DEAL_REASON_VMARGIN = 8,
  DEAL_REASON_SPLIT = 9
"""

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Non-trade deal types (balance operations)
BALANCE_DEAL_TYPES = {2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 16, 17}

# Entry types
DEAL_ENTRY_IN = 0
DEAL_ENTRY_OUT = 1
DEAL_ENTRY_INOUT = 2
DEAL_ENTRY_OUT_BY = 3

# Deal reasons → human readable entry_type
REASON_MAP = {
    0: "manual",    # CLIENT
    1: "mobile",    # MOBILE
    2: "web",       # WEB
    3: "ea",        # EXPERT
    4: "sl",        # SL
    5: "tp",        # TP
    6: "so",        # STOP OUT
    7: "rollover",  # ROLLOVER
}


def _deal_to_dict(deal) -> dict[str, Any]:
    """Convert MT5 deal (numpy named tuple) to a plain dict."""
    return {
        "ticket": int(deal.ticket),
        "order": int(deal.order),
        "time": datetime.fromtimestamp(deal.time, tz=timezone.utc),
        "time_msc": int(deal.time_msc),
        "type": int(deal.type),
        "entry": int(deal.entry),
        "magic": int(deal.magic),
        "position_id": int(deal.position_id),
        "reason": int(deal.reason),
        "symbol": str(deal.symbol),
        "volume": float(deal.volume),
        "price": float(deal.price),
        "commission": float(deal.commission),
        "swap": float(deal.swap),
        "profit": float(deal.profit),
        "fee": float(deal.fee),
        "comment": str(deal.comment),
        "external_id": str(deal.external_id),
    }


def _order_to_dict(order) -> dict[str, Any]:
    """Convert MT5 order (numpy named tuple) to a plain dict.
    
    Note: MT5 Python API uses 'sl' and 'tp' field names on TradeOrder,
    not 'price_stoploss' / 'price_takeprofit'.
    """
    return {
        "ticket": int(order.ticket),
        "time_setup": datetime.fromtimestamp(order.time_setup, tz=timezone.utc),
        "time_done": datetime.fromtimestamp(order.time_done, tz=timezone.utc),
        "type": int(order.type),
        "state": int(order.state),
        "magic": int(order.magic),
        "position_id": int(order.position_id),
        "symbol": str(order.symbol),
        "volume_initial": float(order.volume_initial),
        "volume_current": float(order.volume_current),
        "price_open": float(order.price_open),
        "price_current": float(order.price_current),
        "price_stoploss": float(order.sl),
        "price_takeprofit": float(order.tp),
        "comment": str(order.comment),
    }


def _detect_session(dt: datetime) -> str:
    """Detect trading session from UTC time."""
    hour = dt.hour
    # Session times in UTC:
    # Asian:    00:00 - 08:00 UTC (Tokyo 09:00 - 17:00 JST)
    # London:   08:00 - 12:00 UTC
    # Overlap:  12:00 - 16:00 UTC (London + NY)
    # New York: 16:00 - 21:00 UTC
    # Off-hours: 21:00 - 00:00 UTC
    if 0 <= hour < 8:
        return "asian"
    elif 8 <= hour < 12:
        return "london"
    elif 12 <= hour < 16:
        return "overlap"
    elif 16 <= hour < 21:
        return "new_york"
    else:
        return "off_hours"


def _calc_pips(symbol: str, direction: str, open_price: float, close_price: float) -> float:
    """
    Calculate pips based on symbol and direction.
    
    For XAUUSD: 1 pip = 0.1 (e.g., 2650.50 → 2651.50 = 10 pips)
    For JPY pairs: 1 pip = 0.01
    For most forex: 1 pip = 0.0001
    """
    # Determine pip size based on symbol
    symbol_upper = symbol.upper()
    if "XAU" in symbol_upper or "GOLD" in symbol_upper:
        pip_size = 0.1
    elif "XAG" in symbol_upper or "SILVER" in symbol_upper:
        pip_size = 0.01
    elif "JPY" in symbol_upper:
        pip_size = 0.01
    elif "BTC" in symbol_upper:
        pip_size = 1.0
    else:
        pip_size = 0.0001

    if direction == "buy":
        pips = (close_price - open_price) / pip_size
    else:
        pips = (open_price - close_price) / pip_size

    return round(pips, 1)


def reconstruct_trades(
    raw_deals,
    raw_orders,
    raw_positions=None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Reconstruct trades from MT5 deals and orders.

    Args:
        raw_deals: Result of mt5.history_deals_get() — numpy structured array
        raw_orders: Result of mt5.history_orders_get() — numpy structured array
        raw_positions: Result of mt5.positions_get() — numpy structured array (open positions)

    Returns:
        (trades, balance_operations, open_positions)
    """
    # Convert numpy arrays to dicts
    deals = [_deal_to_dict(d) for d in raw_deals] if raw_deals is not None else []
    orders = [_order_to_dict(o) for o in raw_orders] if raw_orders is not None else []

    # Build order lookup by ticket for SL/TP
    order_lookup: dict[int, dict] = {}
    for o in orders:
        order_lookup[o["ticket"]] = o

    # Separate balance operations from trade deals
    trade_deals = []
    balance_ops = []

    for deal in deals:
        if deal["type"] in BALANCE_DEAL_TYPES:
            balance_ops.append({
                "ticket": deal["ticket"],
                "type": deal["type"],
                "time": deal["time"].isoformat(),
                "amount": deal["profit"],
                "comment": deal["comment"],
                "symbol": deal["symbol"],
            })
        else:
            trade_deals.append(deal)

    # Group trade deals by position_id
    positions: dict[int, dict] = {}
    for deal in trade_deals:
        pid = deal["position_id"]
        if pid == 0:
            # Deals without position_id (rare, log and skip)
            logger.warning(f"Deal {deal['ticket']} has position_id=0, skipping")
            continue

        if pid not in positions:
            positions[pid] = {"entries": [], "exits": []}

        if deal["entry"] == DEAL_ENTRY_IN:
            positions[pid]["entries"].append(deal)
        elif deal["entry"] in (DEAL_ENTRY_OUT, DEAL_ENTRY_OUT_BY):
            positions[pid]["exits"].append(deal)
        elif deal["entry"] == DEAL_ENTRY_INOUT:
            # INOUT = close existing + open new in opposite direction
            # Treat as exit for this position
            positions[pid]["exits"].append(deal)

    # Reconstruct trades
    trades = []
    errors = []

    for pid, data in positions.items():
        entries = data["entries"]
        exits = data["exits"]

        if not entries:
            logger.warning(f"Position {pid}: no entry deal found, skipping")
            continue

        # Use first entry deal (multiple entries for the same position_id
        # shouldn't happen in standard mode, but handle gracefully)
        entry = entries[0]
        if len(entries) > 1:
            logger.info(f"Position {pid}: {len(entries)} entry deals, using first")

        # Lookup order for SL/TP
        order = order_lookup.get(entry["order"])
        sl = order["price_stoploss"] if order else 0.0
        tp = order["price_takeprofit"] if order else 0.0

        # Direction
        direction = "buy" if entry["type"] == 0 else "sell"

        # Entry reason → entry_type
        entry_type = REASON_MAP.get(entry["reason"], "manual")

        if not exits:
            # No exit = still open (will be in open_positions list)
            continue

        # Total entry volume for commission/swap proportional split
        total_exit_volume = sum(e["volume"] for e in exits)

        for exit_deal in exits:
            # Proportional share of this partial close
            volume_ratio = exit_deal["volume"] / total_exit_volume if total_exit_volume > 0 else 1.0

            # Duration
            duration_seconds = (exit_deal["time"] - entry["time"]).total_seconds()

            # Pips
            pips = _calc_pips(entry["symbol"], direction, entry["price"], exit_deal["price"])

            # Commission: entry commission proportionally + full exit commission
            # (MT5 typically charges commission on entry, sometimes split entry/exit)
            entry_commission_share = entry["commission"] * volume_ratio
            total_commission = entry_commission_share + exit_deal["commission"]

            # Swap: typically accumulated on the exit deal
            total_swap = (entry["swap"] * volume_ratio) + exit_deal["swap"]

            # Fee
            total_fee = (entry["fee"] * volume_ratio) + exit_deal["fee"]

            # R:R calculation (if SL/TP available)
            risk_reward = None
            if sl > 0 and tp > 0:
                risk = abs(entry["price"] - sl)
                reward = abs(tp - entry["price"])
                if risk > 0:
                    risk_reward = round(reward / risk, 2)

            # Exit reason
            exit_reason = REASON_MAP.get(exit_deal["reason"], "manual")

            trade = {
                # Identifiers
                "deal_ticket": exit_deal["ticket"],     # Unique per partial close
                "order_ticket": entry["order"],          # Shared across entry/exit
                "position_id": pid,

                # Trade data
                "symbol": entry["symbol"],
                "direction": direction,
                "volume": exit_deal["volume"],
                "open_price": entry["price"],
                "close_price": exit_deal["price"],
                "open_time": entry["time"].isoformat(),
                "close_time": exit_deal["time"].isoformat(),
                "duration_seconds": duration_seconds,

                # Financials
                "commission": round(total_commission, 2),
                "swap": round(total_swap, 2),
                "profit": exit_deal["profit"],
                "fee": round(total_fee, 2),
                "pips": pips,
                "risk_reward": risk_reward,

                # SL/TP from order
                "stop_loss": sl,
                "take_profit": tp,

                # Strategy/EA metadata
                "magic_number": entry["magic"],
                "deal_comment": entry["comment"],
                "deal_reason": entry["reason"],
                "entry_type": entry_type,
                "exit_reason": exit_reason,
                "external_id": entry["external_id"],

                # Session
                "session": _detect_session(entry["time"]),

                # Status
                "status": "closed",
            }
            trades.append(trade)

    # Process open positions from mt5.positions_get()
    open_pos_list = []
    if raw_positions is not None:
        for pos in raw_positions:
            open_pos_list.append({
                "ticket": int(pos.ticket),
                "symbol": str(pos.symbol),
                "direction": "buy" if int(pos.type) == 0 else "sell",
                "volume": float(pos.volume),
                "open_price": float(pos.price_open),
                "current_price": float(pos.price_current),
                "open_time": datetime.fromtimestamp(pos.time, tz=timezone.utc).isoformat(),
                "stop_loss": float(pos.sl),
                "take_profit": float(pos.tp),
                "swap": float(pos.swap),
                "profit": float(pos.profit),
                "magic_number": int(pos.magic),
                "comment": str(pos.comment),
            })

    logger.info(
        f"Reconstructed {len(trades)} trades, "
        f"{len(balance_ops)} balance ops, "
        f"{len(open_pos_list)} open positions "
        f"from {len(deals)} deals"
    )

    return trades, balance_ops, open_pos_list
