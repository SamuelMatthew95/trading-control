"""Stream-lag consumer-health classification.

Regression for the false ``no_active_consumers`` warning that fired on the
empty/dormant ``orders`` stream (never written in the live pipeline).
"""

from api.constants import STREAM_MARKET_TICKS, STREAM_ORDERS, STREAM_SIGNALS
from api.mcp.read_tools import STREAMS_REQUIRING_ACTIVE_CONSUMERS, _flags_missing_consumer


def test_empty_required_stream_does_not_warn():
    # orders is a required-consumer stream but is never written — an empty
    # stream has nothing to consume, so a missing consumer is not a fault.
    assert STREAM_ORDERS in STREAMS_REQUIRING_ACTIVE_CONSUMERS
    assert _flags_missing_consumer(STREAM_ORDERS, 0) is False


def test_required_stream_with_backlog_warns():
    # A required stream that actually holds messages but has no consumer is a
    # genuine warning — this signal must be preserved.
    assert _flags_missing_consumer(STREAM_SIGNALS, 12) is True


def test_required_stream_when_empty_does_not_warn():
    assert _flags_missing_consumer(STREAM_SIGNALS, 0) is False


def test_non_required_stream_never_warns():
    assert STREAM_MARKET_TICKS not in STREAMS_REQUIRING_ACTIVE_CONSUMERS
    assert _flags_missing_consumer(STREAM_MARKET_TICKS, 999) is False
