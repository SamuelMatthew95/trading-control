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
    symbol = str(data.get(FieldName.SYMBOL) or data.get("asset") or "?")
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
        "notional": notional,
        FieldName.PNL: _float_or_none(data.get(FieldName.PNL)),
        FieldName.PNL_PERCENT: _float_or_none(data.get(FieldName.PNL_PERCENT)),
        "stop_price": stop_price,
        "take_profit_price": take_profit_price,
        FieldName.ORDER_ID: data.get(FieldName.ORDER_ID),
        FieldName.TRACE_ID: data.get(FieldName.TRACE_ID),
        FieldName.FILLED_AT: data.get(FieldName.FILLED_AT) or data.get("executed_at"),
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
    if trade.get("notional") is not None:
        parts.append(f"{notional_label} {_format_money(trade['notional'])}")
    if trade.get(FieldName.PNL) is not None:
        pnl_text = _format_signed_money(trade[FieldName.PNL])
        if trade.get(FieldName.PNL_PERCENT) is not None:
            pnl_text = f"{pnl_text} ({_format_signed_percent(trade[FieldName.PNL_PERCENT])})"
        parts.append(f"Realized PnL {pnl_text}")
    elif side == OrderSide.BUY and trade.get("stop_price") is not None:
        parts.append(
            f"Stop {_format_money(trade['stop_price'])} / "
            f"Target {_format_money(trade['take_profit_price'])}"
        )
    return " | ".join(parts)


def _trade_facts(trade: dict[str, Any]) -> list[dict[str, str]]:
    action = str(trade.get(FieldName.ACTION) or "").upper()
    notional_label = "Proceeds" if action == "SELL" else "Notional"
    facts = [
        {"label": "Symbol", "value": str(trade.get(FieldName.SYMBOL) or "?")},
        {"label": "Qty", "value": _format_qty(trade.get(FieldName.QTY))},
        {"label": "Fill", "value": _format_money(trade.get(FieldName.FILL_PRICE))},
    ]
    if trade.get("notional") is not None:
        facts.append({"label": notional_label, "value": _format_money(trade["notional"])})
    if trade.get(FieldName.PNL) is not None:
        pnl_text = _format_signed_money(trade[FieldName.PNL])
        if trade.get(FieldName.PNL_PERCENT) is not None:
            pnl_text = f"{pnl_text} ({_format_signed_percent(trade[FieldName.PNL_PERCENT])})"
        facts.append(
            {
                "label": "P&L",
                "value": pnl_text,
                "tone": "gain" if float(trade[FieldName.PNL]) >= 0 else "loss",
            }
        )
    if action == "BUY" and trade.get("stop_price") is not None:
        facts.append({"label": "Stop", "value": _format_money(trade["stop_price"])})
    if action == "BUY" and trade.get("take_profit_price") is not None:
        facts.append({"label": "Target", "value": _format_money(trade["take_profit_price"])})
    return facts


def _delivery_payload(trade: dict[str, Any], title: str, message: str) -> dict[str, Any]:
    action = str(trade.get(FieldName.ACTION) or "").upper()
    fields = [{"label": "Action", "value": action}, *_trade_facts(trade)]
    if trade.get(FieldName.ORDER_ID):
        fields.append({"label": "Order", "value": str(trade[FieldName.ORDER_ID])})
    if trade.get(FieldName.TRACE_ID):
        fields.append({"label": "Trace", "value": str(trade[FieldName.TRACE_ID])})

    lines = [f"{field['label']}: {field['value']}" for field in fields]
    return {
        "template": "trade_execution",
        "suggested_channels": ["dashboard", "slack", "email", "telegram"],
        "slack": {
            "text": f"{title} - {message}",
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": title}},
                {"type": "section", "text": {"type": "mrkdwn", "text": message}},
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*{field['label']}:*\n{field['value']}"}
                        for field in fields[:10]
                    ],
                },
            ],
        },
        "email": {
            "subject": title,
            "preview": message,
            "body": "\n".join([message, "", *lines]),
        },
        "telegram": {"text": "\n".join([title, message, *lines])},
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
    badges = [{"label": side.upper(), "tone": side}]
    if severity != "INFO":
        badges.append({"label": severity, "tone": severity.lower()})

    meta = [
        {"label": "Type", "value": notification_type},
        {"label": "Source", "value": stream},
    ]
    if trace_id:
        meta.append({"label": "Trace", "value": trace_id[:8]})

    return {
        "kind": "trade_execution",
        "tone": side,
        "icon": "arrow-down-right" if side == OrderSide.SELL else "arrow-up-right",
        "title": title,
        "subtitle": message,
        "status_label": "open",
        "badges": badges,
        "facts": _trade_facts(trade),
        "meta": meta,
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
        "msg_id": str(uuid.uuid4()),
        "notification_id": notification_id,
        "schema_version": schema_version,
        "source": source,
        "severity": severity,
        "notification_type": notification_type,
        "stream_source": stream,
        "title": title,
        "message": message,
        "summary": message,
        "action": side,
        "symbol": trade[FieldName.SYMBOL],
        "qty": trade[FieldName.QTY],
        "fill_price": trade[FieldName.FILL_PRICE],
        "notional": trade["notional"],
        "pnl": trade[FieldName.PNL],
        "pnl_percent": trade[FieldName.PNL_PERCENT],
        "order_id": trade[FieldName.ORDER_ID],
        "trace_id": trace_id,
        "state": "open",
        "acknowledged": False,
        "display": _display_payload(
            trade=trade,
            title=title,
            message=message,
            severity=severity,
            notification_type=notification_type,
            stream=stream,
        ),
        "delivery": _delivery_payload(trade, title, message),
        "metadata": {
            "observed_msg_id": observed_msg_id,
            "stream": stream,
            "event_type": event_type,
            "trade": trade,
        },
        "timestamp": timestamp,
    }
