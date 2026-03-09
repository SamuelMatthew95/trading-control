"""
Market Data Tools - Real-time stock quotes and market data
Extracted from tools.py for market-analysis skill
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)


class GetStockQuote:
    """Get current stock quote with real-time data"""

    def __init__(self):
        self.tool_id = "get_stock_quote"
        self._session = None

    async def _get_session(self):
        """Get aiohttp session"""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def execute(self, symbol: str) -> Dict[str, Any]:
        """Get stock quote"""
        start_time = datetime.now()
        try:
            session = await self._get_session()

            # Try Alpha Vantage API first
            alpha_vantage_key = os.getenv("ALPHA_VANTAGE_API_KEY")
            if alpha_vantage_key:
                result = await self._get_alpha_vantage_quote(
                    session, symbol, alpha_vantage_key
                )
            else:
                # Fallback to Yahoo Finance
                result = await self._get_yahoo_finance_quote(session, symbol)

            return result

        except Exception as e:
            logger.error(f"Error getting stock quote for {symbol}: {e}")
            return {"error": f"Failed to fetch stock quote: {str(e)}"}

    async def _get_alpha_vantage_quote(
        self, session: aiohttp.ClientSession, symbol: str, api_key: str
    ) -> Dict[str, Any]:
        """Get quote from Alpha Vantage API"""
        url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={api_key}"

        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                quote = data.get("Global Quote", {})

                if not quote:
                    return {"error": "No quote data found"}

                return {
                    "symbol": quote.get("01. symbol", symbol.upper()),
                    "price": float(quote.get("05. price", 0)),
                    "change": float(quote.get("09. change", 0)),
                    "change_percent": float(quote.get("10. change_percent", 0)),
                    "volume": int(quote.get("06. volume", 0)),
                    "timestamp": quote.get("07. latest trading day"),
                    "source": "alpha_vantage",
                }
            else:
                return {"error": f"API request failed: {response.status}"}

    async def _get_yahoo_finance_quote(
        self, session: aiohttp.ClientSession, symbol: str
    ) -> Dict[str, Any]:
        """Get quote from Yahoo Finance (unofficial)"""
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                result = data.get("chart", {}).get("result", [{}])[0]

                if not result:
                    return {"error": "No quote data found"}

                meta = result.get("meta", {})
                quote = result.get("indicators", {}).get("quote", [{}])[0]

                return {
                    "symbol": symbol.upper(),
                    "price": (
                        quote.get("close", [0])[-1]
                        if isinstance(quote.get("close", [0]), list)
                        else quote.get("close", 0)
                    ),
                    "change": (
                        quote.get("close", [0])[-1]
                        if isinstance(quote.get("close", [0]), list)
                        else quote.get("close", 0)
                    )
                    - meta.get("previousClose", 0),
                    "change_percent": (
                        (
                            quote.get("close", [0])[-1]
                            if isinstance(quote.get("close", [0]), list)
                            else quote.get("close", 0)
                        )
                        - meta.get("previousClose", 0)
                    )
                    / meta.get("previousClose", 1)
                    * 100,
                    "volume": (
                        result.get("volume", {}).get("volume", [0])[-1]
                        if isinstance(result.get("volume", {}).get("volume", [0]), list)
                        else result.get("volume", {}).get("volume", 0)
                    ),
                    "timestamp": datetime.fromtimestamp(
                        meta.get("regularMarketTime", 0)
                    ).isoformat(),
                    "source": "yahoo_finance",
                }
            else:
                return {"error": f"API request failed: {response.status}"}
