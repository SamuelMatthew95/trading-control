"""Offline backtest harness for the trading-control signal logic.

Why this exists
---------------
The live system is event-driven and only ever learns *after* it has already
traded (and lost). There was no way to ask "would this rule have made money?"
before risking capital — every strategy change shipped blind. This package
answers that question offline::

    prices -> classify_signal() -> simulated fills -> trade_scorer metrics

It deliberately REUSES the production decision
(``api.services.signal_generator.classify_signal``) and the production scoring
(``api.services.agents.trade_scorer``) so the backtest and the live system can
never silently diverge — if you change the signal, the backtest measures the
real thing.

It lives outside ``api/`` on purpose: this is research tooling, not
request-path code, so it is exempt from the FieldName/guardrail ceremony that
governs the live service.

Use it via the API (``GET /backtest/compare``) or directly in Python::

    from backtest import run_backtest
    from backtest.data import synthetic_prices

    result = run_backtest(synthetic_prices(n=1000))
"""

from backtest.engine import BacktestResult, run_backtest

__all__ = ["BacktestResult", "run_backtest"]
