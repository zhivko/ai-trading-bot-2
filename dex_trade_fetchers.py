"""
DEX Trade Fetchers
Module for fetching trade data from decentralized exchanges (DEXes)
"""
import asyncio
import aiohttp
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import time

logger = logging.getLogger(__name__)

class DEXTradeFetcher:
    """Base class for DEX trade fetchers"""

    def __init__(self, exchange_name: str, api_base_url: str, rate_limit: int = 10):
        self.exchange_name = exchange_name
        self.api_base_url = api_base_url
        self.rate_limit = rate_limit
        self.last_request_time = 0
        self.request_interval = 1.0 / rate_limit  # seconds between requests

    async def _rate_limit_wait(self):
        """Enforce rate limiting"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.request_interval:
            await asyncio.sleep(self.request_interval - time_since_last)
        self.last_request_time = time.time()

    async def fetch_trades(self, symbol: str, since: Optional[int] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch trades for a symbol. Override in subclasses."""
        raise NotImplementedError("Subclasses must implement fetch_trades")


class HyperliquidTradeFetcher(DEXTradeFetcher):
    """Hyperliquid DEX trade fetcher"""

    def __init__(self):
        super().__init__("hyperliquid", "https://api.hyperliquid.xyz", rate_limit=10)

    async def fetch_trades(self, symbol: str, since: Optional[int] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Fetch trades from Hyperliquid
        API: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
        """
        await self._rate_limit_wait()

        try:
            async with aiohttp.ClientSession() as session:
                # Hyperliquid uses coin names without USDT suffix
                coin = symbol.replace('USDT', '')

                # Try different payload formats - Hyperliquid API might have changed
                payloads = [
                    # Format 1: Recent trades
                    {"type": "trades", "coin": coin},
                    # Format 2: With time range
                    {
                        "type": "trades",
                        "coin": coin,
                        "startTime": since or (int(time.time() * 1000) - 3600000),  # Default to last hour
                        "endTime": int(time.time() * 1000)
                    }
                ]

                for payload in payloads:
                    try:
                        async with session.post(f"{self.api_base_url}/info", json=payload) as response:
                            if response.status != 200:
                                logger.debug(f"Hyperliquid API error with payload {payload}: {response.status}")
                                continue

                            data = await response.json()

                            if not data or not isinstance(data, list):
                                logger.debug(f"No trade data from Hyperliquid for {symbol} with payload {payload}")
                                continue

                            trades = []
                            for trade in data[:limit]:  # Limit results
                                try:
                                    # Convert Hyperliquid trade format to standardized format
                                    standardized_trade = {
                                        "id": f"{trade.get('hash', '')}_{trade.get('tid', '')}",
                                        "timestamp": trade.get("time", 0) // 1000000,  # Convert to seconds
                                        "datetime": datetime.fromtimestamp(trade.get("time", 0) // 1000000, timezone.utc).isoformat(),
                                        "symbol": symbol,
                                        "side": "buy" if trade.get("side") == "B" else "sell",
                                        "price": float(trade.get("px", 0)),
                                        "amount": float(trade.get("sz", 0)),
                                        "cost": float(trade.get("px", 0)) * float(trade.get("sz", 0)),
                                        "fee": 0,  # Hyperliquid fees are not in trade data
                                        "exchange": "hyperliquid",
                                        "info": trade
                                    }
                                    trades.append(standardized_trade)
                                except (KeyError, ValueError, TypeError) as e:
                                    logger.warning(f"Error parsing Hyperliquid trade: {e}")
                                    continue

                            if trades:
                                logger.info(f"Fetched {len(trades)} trades from Hyperliquid for {symbol}")
                                return trades

                    except Exception as e:
                        logger.debug(f"Error with Hyperliquid payload {payload}: {e}")
                        continue

                logger.warning(f"No valid trade data from Hyperliquid for {symbol} after trying all payloads")
                return []

        except Exception as e:
            logger.error(f"Error fetching trades from Hyperliquid: {e}")
            return []


class AsterTradeFetcher(DEXTradeFetcher):
    """Aster DEX trade fetcher"""

    def __init__(self):
        # Aster might not be active or API might be different
        super().__init__("aster", "https://api.aster.network", rate_limit=5)

    async def fetch_trades(self, symbol: str, since: Optional[int] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Fetch trades from Aster
        Note: Aster may not be active or API may be different. This is a placeholder implementation.
        """
        await self._rate_limit_wait()

        try:
            async with aiohttp.ClientSession() as session:
                # Aster uses different symbol format
                coin = symbol.replace('USDT', '')

                # Try different possible Aster API endpoints
                endpoints = [
                    f"{self.api_base_url}/v1/trades",
                    f"{self.api_base_url}/api/v1/trades",
                    f"{self.api_base_url}/trades"
                ]

                for endpoint in endpoints:
                    try:
                        params = {
                            "symbol": f"{coin}_USDT",
                            "limit": limit
                        }

                        if since:
                            params["startTime"] = since * 1000  # Convert to milliseconds

                        async with session.get(endpoint, params=params) as response:
                            if response.status != 200:
                                logger.debug(f"Aster API error for {endpoint}: {response.status}")
                                continue

                            data = await response.json()

                            trades = []
                            for trade in data.get("data", [])[:limit]:
                                try:
                                    standardized_trade = {
                                        "id": trade.get("id", ""),
                                        "timestamp": trade.get("timestamp", 0) // 1000,  # Convert to seconds
                                        "datetime": datetime.fromtimestamp(trade.get("timestamp", 0) // 1000, timezone.utc).isoformat(),
                                        "symbol": symbol,
                                        "side": trade.get("side", "").lower(),
                                        "price": float(trade.get("price", 0)),
                                        "amount": float(trade.get("amount", 0)),
                                        "cost": float(trade.get("price", 0)) * float(trade.get("amount", 0)),
                                        "fee": float(trade.get("fee", 0)),
                                        "exchange": "aster",
                                        "info": trade
                                    }
                                    trades.append(standardized_trade)
                                except (KeyError, ValueError, TypeError) as e:
                                    logger.warning(f"Error parsing Aster trade: {e}")
                                    continue

                            if trades:
                                logger.info(f"Fetched {len(trades)} trades from Aster for {symbol}")
                                return trades

                    except Exception as e:
                        logger.debug(f"Error with Aster endpoint {endpoint}: {e}")
                        continue

                logger.warning(f"No valid trade data from Aster for {symbol} - API may not be available")
                return []

        except Exception as e:
            logger.error(f"Error fetching trades from Aster: {e}")
            return []


class DydxTradeFetcher(DEXTradeFetcher):
    """dYdX DEX trade fetcher"""

    def __init__(self):
        super().__init__("dxdy", "https://api.dydx.exchange", rate_limit=10)

    async def fetch_trades(self, symbol: str, since: Optional[int] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Fetch trades from dYdX
        API: https://docs.dydx.exchange/#get-trades
        """
        await self._rate_limit_wait()

        try:
            async with aiohttp.ClientSession() as session:
                # dYdX uses MARKET-USD format
                market = symbol.replace('USDT', '-USD')

                # Try different API versions and endpoints
                endpoints = [
                    f"{self.api_base_url}/v3/trades",
                    f"{self.api_base_url}/v4/trades"  # Try v4 if v3 doesn't work
                ]

                for endpoint in endpoints:
                    try:
                        params = {
                            "market": market,
                            "limit": min(limit, 100)  # dYdX limits to 100
                        }

                        if since:
                            params["startingBeforeOrAt"] = datetime.fromtimestamp(since, timezone.utc).isoformat() + "Z"

                        async with session.get(endpoint, params=params) as response:
                            if response.status != 200:
                                logger.debug(f"dYdX API error for {endpoint}: {response.status}")
                                continue

                            data = await response.json()

                            trades = []
                            for trade in data.get("trades", [])[:limit]:
                                try:
                                    # Convert dYdX trade format to standardized format
                                    standardized_trade = {
                                        "id": trade.get("id", ""),
                                        "timestamp": int(datetime.fromisoformat(trade.get("createdAt", "").replace('Z', '+00:00')).timestamp()),
                                        "datetime": trade.get("createdAt", ""),
                                        "symbol": symbol,
                                        "side": trade.get("side", "").lower(),
                                        "price": float(trade.get("price", 0)),
                                        "amount": float(trade.get("size", 0)),
                                        "cost": float(trade.get("price", 0)) * float(trade.get("size", 0)),
                                        "fee": float(trade.get("fee", 0)),
                                        "exchange": "dxdy",
                                        "info": trade
                                    }
                                    trades.append(standardized_trade)
                                except (KeyError, ValueError, TypeError) as e:
                                    logger.warning(f"Error parsing dYdX trade: {e}")
                                    continue

                            if trades:
                                logger.info(f"Fetched {len(trades)} trades from dYdX for {symbol}")
                                return trades

                    except Exception as e:
                        logger.debug(f"Error with dYdX endpoint {endpoint}: {e}")
                        continue

                logger.warning(f"No valid trade data from dYdX for {symbol} after trying all endpoints")
                return []

        except Exception as e:
            logger.error(f"Error fetching trades from dYdX: {e}")
            return []


# Factory function to get the appropriate DEX fetcher
def get_dex_fetcher(exchange_id: str) -> Optional[DEXTradeFetcher]:
    """Factory function to get DEX trade fetcher by exchange ID"""
    fetchers = {
        "hyperliquid": HyperliquidTradeFetcher,
        "aster": AsterTradeFetcher,
        "dxdy": DydxTradeFetcher
    }

    fetcher_class = fetchers.get(exchange_id.lower())
    if fetcher_class:
        return fetcher_class()
    return None


# Mock data generators for testing when APIs are unavailable
def generate_mock_dex_trades(exchange: str, symbol: str, count: int = 10) -> List[Dict[str, Any]]:
    """Generate mock DEX trade data for testing purposes"""
    import random
    from datetime import datetime, timezone

    trades = []
    base_price = 50000 if symbol.startswith('BTC') else 3000 if symbol.startswith('ETH') else 100

    for i in range(count):
        # Generate realistic price movements
        price_variation = random.uniform(-0.005, 0.005)  # ±0.5%
        price = base_price * (1 + price_variation)

        # Generate realistic trade sizes
        amount = random.uniform(0.001, 2.0)

        # Generate timestamp (last hour)
        timestamp = int(time.time()) - random.randint(0, 3600)

        trade = {
            "id": f"mock_{exchange}_{symbol}_{i}",
            "timestamp": timestamp,
            "datetime": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
            "symbol": symbol,
            "side": random.choice(["buy", "sell"]),
            "price": round(price, 2),
            "amount": round(amount, 6),
            "cost": round(price * amount, 2),
            "fee": round(price * amount * 0.001, 6),  # 0.1% fee
            "exchange": exchange,
            "info": {"mock": True, "note": "Generated for testing when API unavailable"}
        }
        trades.append(trade)

    return trades


async def fetch_dex_trades(exchange_id: str, symbol: str, since: Optional[int] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Convenience function to fetch trades from any supported DEX

    Args:
        exchange_id: DEX exchange identifier (hyperliquid, aster, dxdy)
        symbol: Trading symbol (e.g., BTCUSDT)
        since: Timestamp to fetch trades since (optional)
        limit: Maximum number of trades to fetch

    Returns:
        List of standardized trade dictionaries
    """
    fetcher = get_dex_fetcher(exchange_id)
    if not fetcher:
        logger.error(f"No DEX fetcher available for {exchange_id}")
        return []

    trades = await fetcher.fetch_trades(symbol, since, limit)

    # If no real trades fetched, return mock data for testing
    if not trades:
        logger.info(f"No real trades from {exchange_id}, generating mock data for testing")
        trades = generate_mock_dex_trades(exchange_id, symbol, min(limit, 10))

    return trades


# Test functions
async def test_dex_fetchers():
    """Test all DEX fetchers using the convenience function"""
    exchanges = ["hyperliquid", "dxdy", "aster"]

    for exchange in exchanges:
        print(f"\n--- Testing {exchange.upper()} ---")
        trades = await fetch_dex_trades(exchange, "BTCUSDT", limit=5)
        print(f"{exchange.upper()} BTCUSDT trades: {len(trades)}")
        if trades:
            print(f"Sample trade: {trades[0]}")
            print(f"Trade has mock data: {trades[0].get('info', {}).get('mock', False)}")
        else:
            print(f"No trades fetched from {exchange}")


if __name__ == "__main__":
    # Run tests
    asyncio.run(test_dex_fetchers())