"""
Simple data manager for testing
"""

from typing import Any, Dict, Optional


class MarketData:
    """Simple market data for testing"""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.price = 0.0


class DataManager:
    """Simple data manager for testing"""

    def __init__(self) -> None:
        self.data_cache = {}

    async def start(self) -> None:
        """Start data manager"""
        pass

    async def stop(self) -> None:
        """Stop data manager"""
        pass

    async def get_symbol_data(self, symbol: str) -> Optional[MarketData]:
        """Get data for a symbol"""
        if symbol not in self.data_cache:
            self.data_cache[symbol] = MarketData(symbol)
        return self.data_cache.get(symbol)

    async def get_data_freshness(self) -> int:
        """Get data freshness in milliseconds"""
        return 5000  # Mock value
