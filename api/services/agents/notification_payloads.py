"""Notification payload builders owned by the API contract."""

from __future__ import annotations

import uuid
from typing import Any

from api.constants import (
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    FieldName,
    OrderSide,
)


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_qty(value: Any) -> str:
    qty = _float_or_none(value)
    if qty is None:
        return "?"
    text = f"{qty:,.8f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _format_money(value: Any) -> str:
    amount = _float_or_none(value)
    if amount is None:
        return "$0.00"
    decimals = 6 if 0 < abs(amount) < 1 else 2
    text = f"${amount:,.{decimals}f}"
    return text.rstrip("0").rstrip(".") if decimals > 2 else text


def _format_signed_money(value: Any) -> str:
    amount = _float_or_none(value)
    if amount is None:
        return "$0.00"
    sign = "+" if amount >= 0 else "-"
    return f"{sign}{_format_money(abs(amount))}"


def _format_signed_percent(value: Any) -> str:
    pct = _float_or_none(value)
    if pct is None:
        return "0.00%"
    sign = "+" if pct >= 0 else "-"
    return f"{sign}{abs(pct):.2f}%"


def build_trade_details(data: dict[str, Any], side: str) -> dict[str, Any]:
    symbol = str(data.get(FieldName.SYMBOL) or data.get(FieldName.ASSET) or "?")
    qty = _float_or_none(data.get(FieldName.QTY) or data.get(FieldName.QUANTITY))
    fill_price = _float_or_none(
        data.get(FieldName.FILL_PRICE)
        or data.get(FieldName.FILLED_PRICE)
        or data.get(FieldName.PRICE)
    )
    notional = round(qty * fill_price, 8) if qty is not None and fill_price is not None else None
    stop_price = None
    take_profit_price = None
    if side == OrderSide.BUY and fill_price is not None:
        stop_price = round(fill_price * (1 - STOP_LOSS_PCT), 8)
        take_profit_price = round(fill_price * (1 + TAKE_PROFIT_PCT), 8)

    return {
        FieldName.ACTION: side,
        FieldName.SIDE: side,
        FieldName.SYMBOL: symbol,
        FieldName.QTY: qty,
        FieldName.PRICE: _float_or_none(data.get(FieldName.PRICE)),
        FieldName.FILL_PRICE: fill_price,
        FieldName.NOTIONAL: notional,
        FieldName.PNL: _float_or_none(data.get(FieldName.PNL)),
        FieldName.PNL_PERCENT: _float_or_none(data.get(FieldName.PNL_PERCENT)),
        FieldName.STOP_PRICE: stop_price,
        FieldName.TAKE_PROFIT_PRICE: take_profit_price,
        FieldName.ORDER_ID: data.get(FieldName.ORDER_ID),
        FieldName.TRACE_ID: data.get(FieldName.TRACE_ID),
        FieldName.FILLED_AT: data.get(FieldName.FILLED_AT) or data.get(FieldName.EXECUTED_AT),
        FieldName.CONFIDENCE: _float_or_none(data.get(FieldName.CONFIDENCE)),
        FieldName.SESSION_ID: data.get(FieldName.SESSION_ID),
    }


def build_trade_title(trade: dict[str, Any]) -> str:
    action = str(trade.get(FieldName.ACTION) or "").upper() or "TRADE"
    symbol = str(trade.get(FieldName.SYMBOL) or "?")
    return f"{action} filled: {symbol}"


def build_trade_notification_type(side: str) -> str:
    return f"trade.{side}_filled" if side in {OrderSide.BUY, OrderSide.SELL} else "trade.fill"


def build_execution_message(data: dict[str, Any]) -> str:
    side = str(data.get(FieldName.SIDE) or data.get(FieldName.ACTION) or "").strip().lower()
    trade = build_trade_details(data, side)
    action = side.upper() or "TRADE"
    symbol = str(trade.get(FieldName.SYMBOL) or "?")
    notional_label = "Proceeds" if side == OrderSide.SELL else "Notional"

    parts = [f"{action} {symbol} filled"]
    if trade.get(FieldName.FILL_PRICE) is not None:
        parts.append(f"Fill {_format_money(trade[FieldName.FILL_PRICE])}")
    if trade.get(FieldName.QTY) is not None:
        parts.append(f"Qty {_format_qty(trade[FieldName.QTY])}")
    if trade.get(FieldName.NOTIONAL) is not None:
        parts.append(f"{notional_label} {_format_money(trade[FieldName.NOTIONAL])}")
    if trade.get(FieldName.PNL) is not None:
        pnl_text = _format_signed_money(trade[FieldName.PNL])
        if trade.get(FieldName.PNL_PERCENT) is not None:
            pnl_text = f"{pnl_text} ({_format_signed_percent(trade[FieldName.PNL_PERCENT])})"
        parts.append(f"Realized PnL {pnl_text}")
    elif side == OrderSide.BUY and trade.get(FieldName.STOP_PRICE) is not None:
        parts.append(
            f"Stop {_format_money(trade[FieldName.STOP_PRICE])} / "
            f"Target {_format_money(trade[FieldName.TAKE_PROFIT_PRICE])}"
        )
    return " | ".join(parts)


def _trade_facts(trade: dict[str, Any]) -> list[dict[str, str]]:
    action = str(trade.get(FieldName.ACTION) or "").upper()
    notional_label = "Proceeds" if action == "SELL" else "Notional"
    facts = [
        {FieldName.LABEL: "Symbol", FieldName.VALUE: str(trade.get(FieldName.SYMBOL) or "?")},
        {FieldName.LABEL: "Qty", FieldName.VALUE: _format_qty(trade.get(FieldName.QTY))},
        {FieldName.LABEL: "Fill", FieldName.VALUE: _format_money(trade.get(FieldName.FILL_PRICE))},
    ]
    if trade.get(FieldName.NOTIONAL) is not None:
        facts.append(
            {
                FieldName.LABEL: notional_label,
                FieldName.VALUE: _format_money(trade[FieldName.NOTIONAL]),
            }
        )
    if trade.get(FieldName.PNL) is not None:
        pnl_text = _format_signed_money(trade[FieldName.PNL])
        if trade.get(FieldName.PNL_PERCENT) is not None:
            pnl_text = f"{pnl_text} ({_format_signed_percent(trade[FieldName.PNL_PERCENT])})"
        facts.append(
            {
                FieldName.LABEL: "P&L",
                FieldName.VALUE: pnl_text,
                FieldName.TONE: "gain" if float(trade[FieldName.PNL]) >= 0 else "loss",
            }
        )
    if action == "BUY" and trade.get(FieldName.STOP_PRICE) is not None:
        facts.append(
            {FieldName.LABEL: "Stop", FieldName.VALUE: _format_money(trade[FieldName.STOP_PRICE])}
        )
    if action == "BUY" and trade.get(FieldName.TAKE_PROFIT_PRICE) is not None:
        facts.append(
            {
                FieldName.LABEL: "Target",
                FieldName.VALUE: _format_money(trade[FieldName.TAKE_PROFIT_PRICE]),
            }
        )
    return facts


def _delivery_payload(trade: dict[str, Any], title: str, message: str) -> dict[str, Any]:
    action = str(trade.get(FieldName.ACTION) or "").upper()
    fields = [{FieldName.LABEL: "Action", FieldName.VALUE: action}, *_trade_facts(trade)]
    if trade.get(FieldName.ORDER_ID):
        fields.append({FieldName.LABEL: "Order", FieldName.VALUE: str(trade[FieldName.ORDER_ID])})
    if trade.get(FieldName.TRACE_ID):
        fields.append({FieldName.LABEL: "Trace", FieldName.VALUE: str(trade[FieldName.TRACE_ID])})

    lines = [f"{field[FieldName.LABEL]}: {field[FieldName.VALUE]}" for field in fields]
    return {
        FieldName.TEMPLATE: "trade_execution",
        FieldName.SUGGESTED_CHANNELS: ["dashboard", "slack", "email", "telegram"],
        FieldName.SLACK: {
            FieldName.TEXT: f"{title} - {message}",
            FieldName.BLOCKS: [
                {"type": "header", FieldName.TEXT: {"type": "plain_text", FieldName.TEXT: title}},
                {"type": "section", FieldName.TEXT: {"type": "mrkdwn", FieldName.TEXT: message}},
                {
                    "type": "section",
                    FieldName.FIELDS: [
                        {
                            "type": "mrkdwn",
                            FieldName.TEXT: f"*{field[FieldName.LABEL]}:*\n{field[FieldName.VALUE]}",
                        }
                        for field in fields[:10]
                    ],
                },
            ],
        },
        FieldName.EMAIL: {
            FieldName.SUBJECT: title,
            FieldName.PREVIEW: message,
            "body": "\n".join([message, "", *lines]),
        },
        FieldName.TELEGRAM: {FieldName.TEXT: "\n".join([title, message, *lines])},
    }


def _display_payload(
    *,
    trade: dict[str, Any],
    title: str,
    message: str,
    severity: str,
    notification_type: str,
    stream: str,
) -> dict[str, Any]:
    side = str(trade.get(FieldName.ACTION) or "").lower()
    trace_id = str(trade.get(FieldName.TRACE_ID) or "")
    badges = [{FieldName.LABEL: side.upper(), FieldName.TONE: side}]
    if severity != "INFO":
        badges.append({FieldName.LABEL: severity, FieldName.TONE: severity.lower()})

    meta = [
        {FieldName.LABEL: "Type", FieldName.VALUE: notification_type},
        {FieldName.LABEL: "Source", FieldName.VALUE: stream},
    ]
    if trace_id:
        meta.append({FieldName.LABEL: "Trace", FieldName.VALUE: trace_id[:8]})

    return {
        FieldName.KIND: "trade_execution",
        FieldName.TONE: side,
        FieldName.ICON: "arrow-down-right" if side == OrderSide.SELL else "arrow-up-right",
        "title": title,
        FieldName.SUBTITLE: message,
        FieldName.STATUS_LABEL: "open",
        FieldName.BADGES: badges,
        FieldName.FACTS: _trade_facts(trade),
        FieldName.META: meta,
    }


def build_trade_notification(
    *,
    data: dict[str, Any],
    side: str,
    stream: str,
    event_type: str,
    observed_msg_id: str,
    severity: str,
    timestamp: str,
    schema_version: str,
    source: str,
) -> dict[str, Any]:
    trade = build_trade_details(data, side)
    title = build_trade_title(trade)
    message = build_execution_message(data)
    trace_id = str(trade.get(FieldName.TRACE_ID) or "") or None
    notification_type = build_trade_notification_type(side)
    notification_id = f"trade:{side}:{trade[FieldName.SYMBOL]}:{trace_id or observed_msg_id}"

    return {
        FieldName.MSG_ID: str(uuid.uuid4()),
        FieldName.NOTIFICATION_ID: notification_id,
        FieldName.SCHEMA_VERSION: schema_version,
        FieldName.SOURCE: source,
        FieldName.SEVERITY: severity,
        FieldName.NOTIFICATION_TYPE: notification_type,
        FieldName.STREAM_SOURCE: stream,
        FieldName.TITLE: title,
        FieldName.MESSAGE: message,
        FieldName.SUMMARY: message,
        FieldName.ACTION: side,
        FieldName.SYMBOL: trade[FieldName.SYMBOL],
        FieldName.QTY: trade[FieldName.QTY],
        FieldName.FILL_PRICE: trade[FieldName.FILL_PRICE],
        FieldName.NOTIONAL: trade[FieldName.NOTIONAL],
        FieldName.PNL: trade[FieldName.PNL],
        FieldName.PNL_PERCENT: trade[FieldName.PNL_PERCENT],
        FieldName.ORDER_ID: trade[FieldName.ORDER_ID],
        FieldName.TRACE_ID: trace_id,
        FieldName.STATE: "open",
        FieldName.ACKNOWLEDGED: False,
        FieldName.DISPLAY: _display_payload(
            trade=trade,
            title=title,
            message=message,
            severity=severity,
            notification_type=notification_type,
            stream=stream,
        ),
        FieldName.DELIVERY: _delivery_payload(trade, title, message),
        FieldName.METADATA: {
            FieldName.OBSERVED_MSG_ID: observed_msg_id,
            FieldName.STREAM: stream,
            FieldName.EVENT_TYPE: event_type,
            FieldName.TRADE: trade,
        },
        FieldName.TIMESTAMP: timestamp,
    }
