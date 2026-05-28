"""CLI entrypoint for the backtest harness.

    python -m backtest --symbol BTC/USD --bars 1000 --vol 0.8

Runs the current production signal logic over historical (Alpaca) or synthetic
price data and prints the realized performance. Real data is used when Alpaca
credentials are available; otherwise it falls back to a seeded random walk and
says so explicitly.
"""

from __future__ import annotations

import argparse

from backtest.data import alpaca_prices, synthetic_prices
from backtest.engine import run_backtest


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m backtest",
        description="Backtest the trading-control signal over price history.",
    )
    parser.add_argument("--symbol", default="BTC/USD", help="symbol to backtest")
    parser.add_argument("--bars", type=int, default=1000, help="number of bars")
    parser.add_argument(
        "--source",
        choices=["auto", "synthetic", "alpaca"],
        default="auto",
        help="data source (auto = real if Alpaca creds present, else synthetic)",
    )
    parser.add_argument("--vol", type=float, default=0.8, help="synthetic per-bar volatility, %%")
    parser.add_argument("--drift", type=float, default=0.0, help="synthetic per-bar drift, %%")
    parser.add_argument("--seed", type=int, default=0, help="random seed (deterministic runs)")
    args = parser.parse_args()

    prices: list[float] = []
    source_used = "synthetic"
    if args.source in ("auto", "alpaca"):
        prices = alpaca_prices(args.symbol, bars=args.bars)
        if prices:
            source_used = "alpaca"
        elif args.source == "alpaca":
            print("No Alpaca data (missing credentials or fetch failed). Aborting.")
            return
    if not prices:
        prices = synthetic_prices(
            n=args.bars, vol_pct=args.vol, drift_pct=args.drift, seed=args.seed
        )

    result = run_backtest(prices, symbol=args.symbol, slippage_seed=args.seed)

    detail = f"  (vol={args.vol}% drift={args.drift}%)" if source_used == "synthetic" else ""
    print(f"\nData source: {source_used}{detail}")
    print(result.summary())
    if source_used == "synthetic" and args.drift == 0.0:
        print(
            "\nNote: synthetic data has NO built-in edge (drift=0). Any loss here is the\n"
            "signal's own behavior plus slippage cost — not bad luck."
        )


if __name__ == "__main__":
    main()
