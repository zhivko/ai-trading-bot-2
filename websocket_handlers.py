# WebSocket handlers for real-time data streaming

import asyncio
import time
import json
import numpy as np
import csv
import os
from typing import Dict, Any, List, AsyncGenerator
import httpx
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from pybit.unified_trading import WebSocket as BybitWS
from config import SUPPORTED_SYMBOLS, DEFAULT_SYMBOL_SETTINGS, AVAILABLE_INDICATORS, SUPPORTED_EXCHANGES, REDIS_LAST_SELECTED_SYMBOL_KEY
from redis_utils import get_redis_connection, publish_live_data_tick, get_cached_klines, get_cached_open_interest, get_stream_key, get_sync_redis_connection
from logging_config import logger
from indicators import _prepare_dataframe, calculate_macd, calculate_rsi, calculate_stoch_rsi, calculate_open_interest, calculate_jma_indicator, calculate_cto_line, get_timeframe_seconds, find_buy_signals
from datetime import datetime, timezone
from drawing_manager import get_drawings


async def fetch_positions_from_trading_service(email: str, symbol: str = None) -> Dict[str, Any]:
    """Fetch current positions from the trading service for authorized users and filter by symbol"""
    if not email:
        logger.warning("No email provided for positions fetch")
        return []

    if email != "klemenzivkovic@gmail.com":
        logger.info(f"Access denied: positions fetch not allowed for email {email}")
        return []

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://localhost:8000/positions")
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    positions = data.get("positions", [])
                    if symbol:
                        # Filter positions by trade symbol (normalize both symbols by removing dashes)
                        # logger.debug(f"DEBUG positions filter: filtering {len(positions)} positions for symbol '{symbol}'")
                        for p in positions:
                            p_symbol = p.get('symbol')
                            if p_symbol:
                                # Normalize by removing dashes for comparison
                                normalized_p_symbol = str(p_symbol).replace('-', '')
                                normalized_symbol = str(symbol).replace('-', '')
                                matches = normalized_p_symbol == normalized_symbol
                            else:
                                matches = False
                            # logger.debug(f"  Position symbol: '{p_symbol}' (normalized: '{normalized_p_symbol}'), matches '{symbol}' (normalized: '{normalized_symbol}'): {matches}")
                        positions = [p for p in positions if p.get('symbol') and str(p.get('symbol')).replace('-', '') == str(symbol).replace('-', '')]
                        # logger.info(f"DEBUG positions filter: after filtering, {len(positions)} positions remain for symbol '{symbol}'")
                    return positions
                else:
                    logger.warning(f"Trading service returned error: {data}")
                    return []
            else:
                logger.error(f"Failed to fetch positions from trading service: HTTP {response.status_code}")
                return []
    except Exception as e:
        logger.error(f"Error fetching positions from trading service: {e}")
        return []


def calculate_volume_profile(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calculate volume profile from trade history data.
    Works with both individual trade data and k-line data formats.
    Returns volume profile data with aggregated trade volumes by price level.
    Uses 20 bins across the price range for optimal visualization.
    """
    if not trades or len(trades) == 0:
        logger.warning("No trades available for volume profile calculation")
        return {"volume_profile": []}

    logger.debug(f"Processing {len(trades)} trades/klines for volume profile")

    # Calculate price range for 20 bins
    prices = []
    for trade in trades:
        if 'open' in trade:
            # K-line format
            price = trade.get('vwap', trade.get('close', 0))
        else:
            # Individual trade format
            price = trade.get('price', 0)

        if isinstance(price, (int, float)) and price > 0:
            prices.append(float(price))

    if not prices:
        logger.warning("No valid prices found for volume profile calculation")
        return {"volume_profile": []}

    price_min = min(prices)
    price_max = max(prices)
    price_range = price_max - price_min

    # Calculate bin size for 20 bins (minimum bin size of 0.01 to avoid division by zero)
    bin_size = max(price_range / 20, 0.01)

    logger.debug(f"Volume profile: price range [{price_min:.2f}, {price_max:.2f}], bin_size: {bin_size:.4f} (20 bins)")

    # Group trades by price level for volume profile
    volume_map = {}

    for trade in trades:
        try:
            # Handle both individual trade format and k-line format
            # Individual trade format: price, quantity/size, side, timestamp
            # K-line format: time, open, high, low, close, vwap, volume, count, buyer_count, seller_count

            # Check if this is k-line data (has 'open' field) or individual trade data
            if 'open' in trade:
                # K-line format: use VWAP as the representative price level
                price = trade.get('vwap', trade.get('close', 0))
                # For volume profile, use total volume for this time period
                quantity = trade.get('vol', trade.get('volume', 0))
                timestamp = trade.get('time', 0)

                # Fix: Always create both buy and sell trades from k-line data
                # Split volume 50/50 for buy and sell when buyer_count/seller_count not available
                # This ensures both buy and sell bars appear even when data is limited

                buy_volume = quantity * 0.5  # 50% buy
                sell_volume = quantity * 0.5  # 50% sell

                # Create artificial trades representing buy and sell activity
                # Always create both buy and sell entries to show both bars
                if buy_volume > 0:
                    trade_data = {
                        "price": float(price),
                        "quantity": float(buy_volume),
                        "side": "BUY",
                        "timestamp": int(timestamp)
                    }
                    _add_trade_to_volume_map(trade_data, volume_map, bin_size)
                if sell_volume > 0:
                    trade_data = {
                        "price": float(price),
                        "quantity": float(sell_volume),
                        "side": "SELL",
                        "timestamp": int(timestamp)
                    }
                    _add_trade_to_volume_map(trade_data, volume_map, bin_size)
            else:
                # Individual trade format
                price = trade.get('price', 0)
                quantity = trade.get('quantity', trade.get('size', 0))
                side = trade.get('side', 'BUY').upper()
                timestamp = trade.get('timestamp', 0)

                if not isinstance(price, (int, float)) or not isinstance(quantity, (int, float)):
                    continue

                trade_data = {
                    "price": float(price),
                    "quantity": float(quantity),
                    "side": side,
                    "timestamp": int(timestamp)
                }
                _add_trade_to_volume_map(trade_data, volume_map, bin_size)

        except Exception as e:
            logger.error(f"Error processing trade for volume profile: {e}")
            continue

    # Sort price levels and create volume profile data
    price_levels = sorted(volume_map.keys())

    volume_profile = []
    for price in price_levels:
        vol_data = volume_map[price]
        volume_profile.append({
            "price": price,
            "totalVolume": vol_data["totalVolume"],
            "buyVolume": vol_data["buyVolume"],
            "sellVolume": vol_data["sellVolume"],
            "trades": vol_data["trades"]
        })

    logger.info(f"Calculated volume profile with {len(volume_profile)} price levels from {len(trades)} trades")

    return {
        "volume_profile": volume_profile,
        "total_trades": len(trades),
        "price_levels": len(volume_profile)
    }


async def calculate_trading_sessions(symbol: str, from_ts: int = None, to_ts: int = None) -> List[Dict[str, Any]]:
    """
    Generate standardized trading sessions based on GMT time zones for crypto trading.
    Returns predefined sessions: Asian, European, American, and Weekend sessions.
    Sessions are filtered and clipped to the requested time range.
    """
    try:
        logger.info(f"Generating GMT-based trading sessions for {symbol} from {from_ts} to {to_ts}")

        # Default to last 7 days if no time range provided
        if from_ts is None:
            from_ts = int(time.time()) - (7 * 24 * 60 * 60)  # 7 days ago
        if to_ts is None:
            to_ts = int(time.time())

        sessions = []

        # Generate sessions for the entire requested time range
        # We'll create multiple days worth of sessions and then filter/intersect with the requested range

        # Calculate the start and end dates (in UTC)
        start_date = time.gmtime(from_ts)
        end_date = time.gmtime(to_ts)

        # Get the range in days
        days_range = int((to_ts - from_ts) / (24 * 60 * 60)) + 2  # Add buffer

        # Generate sessions for each day in the range
        for day_offset in range(days_range):
            session_day = from_ts + (day_offset * 24 * 60 * 60)
            session_date = time.gmtime(session_day)
            weekday = session_date.tm_wday  # 0=Monday, 6=Sunday

            # Helper function to create GMT timestamp for a given hour on the session day
            def create_gmt_timestamp(hour: int) -> int:
                return int(time.mktime(time.struct_time((
                    session_date.tm_year, session_date.tm_mon, session_date.tm_mday,
                    hour, 0, 0,  # hour, minute, second
                    session_date.tm_wday, session_date.tm_yday, session_date.tm_isdst
                ))))

            # 1. ASIAN SESSION: 23:00 GMT to 08:00 GMT (next day)
            asian_start = create_gmt_timestamp(23)  # 23:00 GMT today
            asian_end = create_gmt_timestamp(8) + (24 * 60 * 60)  # 08:00 GMT next day

            if weekday < 5:  # Monday to Friday only
                sessions.append({
                    "symbol": symbol,
                    "start_time": asian_start,
                    "end_time": asian_end,
                    "type": "market_session",
                    "activity_type": "asian",
                    "session_name": "Asian Session",
                    "description": "Asian trading hours (Tokyo/Singapore markets)",
                    "volatility": "moderate",
                    "characteristics": "moderate activity, lower volatility",
                    "gmt_range": "23:00 - 08:00 GMT",
                    "local_description": "late evening to early morning in Western time zones"
                })

            # 2. EUROPEAN SESSION: 08:00 GMT to 17:00 GMT
            european_start = create_gmt_timestamp(8)
            european_end = create_gmt_timestamp(17)

            if weekday < 5:  # Monday to Friday only
                sessions.append({
                    "symbol": symbol,
                    "start_time": european_start,
                    "end_time": european_end,
                    "type": "market_session",
                    "activity_type": "european",
                    "session_name": "European Session",
                    "description": "European trading hours (London/Frankfurt markets)",
                    "volatility": "high",
                    "characteristics": "high activity and liquidity",
                    "gmt_range": "08:00 - 17:00 GMT",
                    "local_description": "European financial center opening hours"
                })

            # 3. AMERICAN SESSION: 13:00 GMT to 22:00 GMT
            american_start = create_gmt_timestamp(13)
            american_end = create_gmt_timestamp(22)

            if weekday < 5:  # Monday to Friday only
                sessions.append({
                    "symbol": symbol,
                    "start_time": american_start,
                    "end_time": american_end,
                    "type": "market_session",
                    "activity_type": "american",
                    "session_name": "American Session",
                    "description": "American trading hours (New York market)",
                    "volatility": "very_high",
                    "characteristics": "high liquidity and volatility",
                    "gmt_range": "13:00 - 22:00 GMT",
                    "local_description": "North American financial center trading hours"
                })

            # 4. WEEKEND SESSION: Friday 23:00 GMT to Sunday 22:00 GMT
            if weekday == 4:  # Friday
                weekend_start = create_gmt_timestamp(23)  # Friday 23:00 GMT
                weekend_end = create_gmt_timestamp(22) + (2 * 24 * 60 * 60)  # Sunday 22:00 GMT

                sessions.append({
                    "symbol": symbol,
                    "start_time": weekend_start,
                    "end_time": weekend_end,
                    "type": "market_session",
                    "activity_type": "weekend",
                    "session_name": "Weekend Session",
                    "description": "Weekend trading (reduced institutional participation)",
                    "volatility": "high",
                    "characteristics": "reduced liquidity, increased volatility",
                    "gmt_range": "Fri 23:00 - Sun 22:00 GMT",
                    "local_description": "24/7 crypto markets with lower volume"
                })

        # Filter sessions to the requested time range (without clipping)
        filtered_sessions = []
        for session in sessions:
            session_start = session['start_time']
            session_end = session['end_time']

            # Check if session overlaps with requested time range
            if session_start <= to_ts and session_end >= from_ts:
                # Include the full session without clipping
                filtered_session = session.copy()
                filtered_session['duration_minutes'] = int((session_end - session_start) / 60)

                filtered_sessions.append(filtered_session)

                logger.debug(f"Added {session['activity_type']} session: {time.strftime('%Y-%m-%d %H:%M GMT', time.gmtime(session_start))} to {time.strftime('%Y-%m-%d %H:%M GMT', time.gmtime(session_end))}")

        logger.info(f"Generated {len(filtered_sessions)} GMT-based trading sessions within time range")

        # Sort sessions chronologically
        filtered_sessions.sort(key=lambda x: x['start_time'])

        return filtered_sessions

    except Exception as e:
        logger.error(f"Error generating GMT-based trading sessions for {symbol}: {e}")
        return []


def _add_trade_to_volume_map(trade_data: Dict[str, Any], volume_map: Dict[float, Dict[str, Any]], bin_size: float = 5.0) -> None:
    """Helper function to add a trade to the volume map using binned prices."""
    price = trade_data['price']
    quantity = trade_data['quantity']
    side = trade_data.get('side', 'BUY').upper()
    timestamp = trade_data.get('timestamp', 0)

    # Group prices into bins dynamically based on calculated bin_size
    price_key = round((float(price) // bin_size) * bin_size, 2)

    if price_key not in volume_map:
        volume_map[price_key] = {
            "totalVolume": 0,
            "buyVolume": 0,
            "sellVolume": 0,
            "trades": []
        }

    vol_data = volume_map[price_key]
    vol_data["totalVolume"] += float(quantity)
    if side == 'BUY':
        vol_data["buyVolume"] += float(quantity)
    else:
        vol_data["sellVolume"] += float(quantity)

    # Store trade details (only one trade record per actual trade)
    vol_data["trades"].append({
        "price": float(price),
        "volume": float(quantity),
        "side": side,
        "timestamp": int(timestamp)
    })


async def fetch_MY_recent_trade_history(symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Fetch recent trade history from the trading service for websocket delivery.
    Returns trade data in the same format as the source service.
    """
    try:
        # Convert symbol format for trading service (BTCUSDT -> BTC-USDT)
        logger.info(f"Fetching trade history for websocket: {symbol}, limit: {limit}")

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "http://localhost:8000/trade-history",
                params={'symbol': symbol, 'limit': limit}
            )

            if response.status_code == 200:
                data = response.json()
                logger.info(f"Trading service returned trade history: {len(data.get('trade_history', []))} trades")

                # The trading service returns data in Bybit format
                # Transform to the format expected by combinedData.js
                transformed_trades = []
                for trade in data.get('trade_history', []):
                    try:
                        # Convert timestamp from string to milliseconds if needed
                        timestamp = trade.get('createdAt', 0)
                        timestamp_ms = 0  # Default fallback

                        if isinstance(timestamp, str):
                            # Try to parse ISO string
                            try:
                                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                                timestamp_ms = int(dt.timestamp() * 1000)
                            except ValueError:
                                logger.warning(f"Failed to parse timestamp string: {timestamp}")
                                timestamp_ms = 0
                        elif isinstance(timestamp, (int, float)):
                            # Determine if timestamp is in milliseconds or seconds
                            if timestamp > 10000000000:  # > 10 billion, likely milliseconds
                                timestamp_ms = int(timestamp)
                            else:  # In seconds, convert to milliseconds
                                timestamp_ms = int(timestamp * 1000)
                        else:
                            logger.warning(f"Invalid timestamp type for trade: {type(timestamp)}, value: {timestamp}")
                            timestamp_ms = 0

                        # Validate timestamp is within reasonable crypto trading range (2021-2035)
                        if timestamp_ms > 0:
                            timestamp_seconds = timestamp_ms // 1000
                            min_valid_ts = 1609459200  # 2021-01-01
                            max_valid_ts = 2050000000  # 2035-01-01
                            if not (min_valid_ts <= timestamp_seconds <= max_valid_ts):
                                logger.warning(f"Trade has invalid timestamp: {timestamp_seconds} seconds (should be between {min_valid_ts} and {max_valid_ts}). Using current time.")
                                timestamp_ms = int(time.time() * 1000)  # Use current time as fallback

                        # Transform to the format expected by tradeHistory.js
                        zulu_timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat().replace('+00:00', 'Z')
                        transformed_trade = {
                            "timestamp": zulu_timestamp,  # Zulu timestamp
                            "price": float(trade.get('price', 0)),
                            "quantity": float(trade.get('size', 0)),  # Total quantity of the trade
                            "side": trade.get('side', 'BUY').upper(),
                            "size": float(trade.get('size', 0))  # Alias for quantity
                        }
                        transformed_trades.append(transformed_trade)
                    except Exception as trade_e:
                        logger.warning(f"Failed to transform trade data: {trade_e}")
                        continue

                logger.info(f"Successfully transformed {len(transformed_trades)} trades for websocket delivery")
                return transformed_trades
            else:
                logger.warning(f"Trading service returned {response.status_code} for trade history: {response.text}")
                return []

    except Exception as e:
        logger.error(f"Error fetching trade history for websocket: {e}")
        return []



async def analyze_trade_data_coverage(exchange_name: str, symbol: str, from_ts: int, to_ts: int, cached_trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze cached trade data for gaps and coverage issues.
    Returns a dictionary with gap analysis results.
    """
    if not cached_trades or len(cached_trades) == 0:
        return {
            'has_gaps': True,
            'gap_info': 'No cached data available',
            'coverage_percentage': 0.0,
            'gaps_count': 0
        }

    try:
        # Sort trades by timestamp for gap analysis
        sorted_trades = sorted(cached_trades, key=lambda x: x.get('timestamp', 0))

        # Find earliest and latest trade timestamps
        earliest_trade_ts = sorted_trades[0].get('timestamp', 0)
        latest_trade_ts = sorted_trades[-1].get('timestamp', 0)

        # Calculate expected coverage (we expect 1-minute aggregated trades)
        expected_interval_seconds = 60  # 1 minute
        total_expected_intervals = (to_ts - from_ts) // expected_interval_seconds

        # Check for significant gaps within the cached data range
        gaps = []
        significant_gaps_count = 0

        for i in range(1, len(sorted_trades)):
            current_trade_ts = sorted_trades[i].get('timestamp', 0)
            previous_trade_ts = sorted_trades[i-1].get('timestamp', 0)

            gap_seconds = current_trade_ts - previous_trade_ts
            if gap_seconds > expected_interval_seconds * 2:  # More than 2 minutes gap
                gaps.append({
                    'from_ts': previous_trade_ts,
                    'to_ts': current_trade_ts,
                    'gap_seconds': gap_seconds,
                    'missing_intervals': int(gap_seconds / expected_interval_seconds) - 1
                })
                significant_gaps_count += 1

        # Check if we have data covering the requested time range
        requested_range_seconds = to_ts - from_ts
        cached_range_seconds = latest_trade_ts - earliest_trade_ts
        coverage_percentage = min(100.0, (cached_range_seconds / requested_range_seconds) * 100.0) if requested_range_seconds > 0 else 0.0

        # Check for gaps at the beginning or end of requested range
        has_start_gap = earliest_trade_ts > from_ts + 300  # More than 5 minutes from start
        has_end_gap = to_ts > latest_trade_ts + 300  # More than 5 minutes before end

        has_gaps = significant_gaps_count > 0 or has_start_gap or has_end_gap

        gap_info = []
        if has_start_gap:
            gap_info.append(f"Start gap: {int((earliest_trade_ts - from_ts) / 60)} minutes")
        if has_end_gap:
            gap_info.append(f"End gap: {int((to_ts - latest_trade_ts) / 60)} minutes")
        if significant_gaps_count > 0:
            gap_info.append(f"{significant_gaps_count} internal gaps")

        return {
            'has_gaps': has_gaps,
            'gap_info': ', '.join(gap_info) if gap_info else 'No significant gaps',
            'coverage_percentage': coverage_percentage,
            'gaps_count': significant_gaps_count + (1 if has_start_gap else 0) + (1 if has_end_gap else 0),
            'earliest_trade': earliest_trade_ts,
            'latest_trade': latest_trade_ts,
            'requested_from': from_ts,
            'requested_to': to_ts
        }

    except Exception as e:
        logger.error(f"Error analyzing trade data coverage for {exchange_name}:{symbol}: {e}")
        return {
            'has_gaps': True,
            'gap_info': f'Analysis error: {str(e)}',
            'coverage_percentage': 0.0,
            'gaps_count': 0
        }


async def fetch_recent_trade_history(symbol: str, from_ts: int = None, to_ts: int = None) -> List[Dict[str, Any]]:
    """
    Fetch trade history from all supported exchanges within date range.
    Returns trade data ordered by timestamp.
    """
    try:
        from redis_utils import get_individual_trades
        from config import SUPPORTED_EXCHANGES

        logger.info(f"Fetching trade history from all exchanges for {symbol}, from_ts: {from_ts}, to_ts: {to_ts}")

        # Default to last 24 hours if no time range provided
        if from_ts is None:
            from_ts = int(time.time()) - (24 * 60 * 60)
        if to_ts is None:
            to_ts = int(time.time())

        all_trades = []

        # Log the requested time range for debugging
        from_dt = datetime.fromtimestamp(from_ts, timezone.utc)
        to_dt = datetime.fromtimestamp(to_ts, timezone.utc)
        logger.info(f"Trade history request: {symbol} from {from_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} to {to_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")

        # Fetch from all supported exchanges that have this symbol
        for exchange_id, exchange_config in SUPPORTED_EXCHANGES.items():
            exchange_name = exchange_config.get('name', exchange_id)
            if symbol in exchange_config.get('symbols', {}):
                try:
                    logger.debug(f"Fetching trades for {symbol} from {exchange_name}")
                    exchange_trades = await get_individual_trades(exchange_name, symbol, from_ts, to_ts)
                    logger.debug(f"Retrieved {len(exchange_trades) if exchange_trades else 0} cached trades for {symbol} from {exchange_name}")

                    # Process cached trades
                    cached_trade_count = 0
                    if exchange_trades and len(exchange_trades) > 0:
                        # Log some sample trades for debugging
                        logger.info(f"Sample trades from {exchange_name}: {min(3, len(exchange_trades))} of {len(exchange_trades)} total")
                        for i, sample_trade in enumerate(exchange_trades[:3]):
                            trade_time = datetime.fromtimestamp(sample_trade.get('timestamp', 0), timezone.utc)
                            logger.info(f"  Trade {i+1}: {sample_trade.get('price', 0)} @ {trade_time.strftime('%Y-%m-%d %H:%M:%S')}")

                        # Transform cached trades to the expected format
                        for trade in exchange_trades:
                            try:
                                # Convert timestamp to milliseconds (detect format)
                                timestamp = trade.get('timestamp', 0)
                                # Ensure timestamp is numeric
                                if isinstance(timestamp, str):
                                    timestamp = int(float(timestamp))  # Handle string timestamps
                                if timestamp > 1e12:  # Already in milliseconds
                                    timestamp_ms = int(timestamp)
                                else:  # In seconds, convert to milliseconds
                                    timestamp_ms = int(timestamp * 1000)

                                # Validate timestamp in seconds for filtering
                                timestamp_seconds = timestamp_ms // 1000
                                min_valid_ts = 1609459200  # 2021-01-01
                                max_valid_ts = 2050000000  # 2035-01-01
                                if not (min_valid_ts <= timestamp_seconds <= max_valid_ts):
                                    logger.warning(f"Skipping trade from {exchange_name} with invalid timestamp: {timestamp_seconds} seconds ({timestamp_ms} ms)")
                                    continue

                                zulu_timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat().replace('+00:00', 'Z')
                                transformed_trade = {
                                    "timestamp": zulu_timestamp,
                                    "price": float(trade.get('price', 0)),
                                    "quantity": float(trade.get('amount', trade.get('size', 0))),
                                    "side": trade.get('side', 'BUY').upper(),
                                    "size": float(trade.get('amount', trade.get('size', 0)))
                                }
                                all_trades.append(transformed_trade)
                                cached_trade_count += 1
                            except Exception as trade_e:
                                logger.warning(f"Failed to transform cached trade from {exchange_name}: {trade_e}")
                                continue

                        logger.debug(f"Added {cached_trade_count} cached transformed trades from {exchange_name}")
                except Exception as e:
                    logger.warning(f"Failed to fetch trades from {exchange_name}: {e}")
                    continue
            else:
                logger.debug(f"Symbol {symbol} not supported on {exchange_name}")

        # Sort all trades by timestamp
        if all_trades:
            all_trades.sort(key=lambda x: x['timestamp'])
            logger.info(f"Successfully fetched and sorted {len(all_trades)} trades from all exchanges for {symbol}")
        else:
            logger.warning(f"No trades found in cached or fresh data for {symbol} in the requested time range. This may indicate data gaps that require background fetching.")

        return all_trades

    except Exception as e:
        logger.error(f"Error fetching trade history from exchanges: {e}")
        return []


async def stream_klines(symbol: str, resolution: str, request):
    from redis_utils import get_redis_connection, get_stream_key
    from redis.asyncio.client import PubSub
    from sse_starlette.sse import EventSourceResponse
    from datetime import datetime, timezone
    import uuid

    async def event_generator() -> AsyncGenerator[Dict[str, str], None]:
        try:
            redis = await get_redis_connection()
            stream_key = get_stream_key(symbol, resolution)
            group_name = f"tradingview:{symbol}:{resolution}"
            consumer_id = f"consumer:{uuid.uuid4()}"
            try:
                await redis.xgroup_create(stream_key, group_name, id='0', mkstream=True)
            except Exception as e:
                if "BUSYGROUP" not in str(e):
                    raise

            last_id = '0-0'
            while True:
                if await request.is_disconnected():
                    logger.info(f"Client disconnected from SSE stream {symbol}/{resolution}. Stopping generator.")
                    break
                try:
                    messages = await redis.xreadgroup(
                        group_name, consumer_id, {stream_key: ">"}, count=10, block=5000  # 5 second block
                    )
                    if messages:
                        for _stream_name, message_list in messages:
                            for message_id, message_data_dict in message_list:
                                try:
                                    kline_json_str = message_data_dict.get('data')
                                    if kline_json_str:
                                        yield {"event": "message", "data": kline_json_str}
                                        await redis.xack(stream_key, group_name, message_id)
                                    else:
                                        logger.warning(f"Message {message_id} has no 'data' field: {message_data_dict}")
                                except Exception as e:
                                    logger.error(f"Error processing message {message_id}: {e}", exc_info=True)
                                    continue
                    # No need for asyncio.TimeoutError explicitly here if xreadgroup block handles it by returning empty
                except Exception as e:  # Catch other errors like Redis connection issues
                    logger.error(f"Error in SSE event generator loop for {symbol}/{resolution}: {e}", exc_info=True)
                    await asyncio.sleep(1)  # Wait a bit before retrying on general errors
        except Exception as e:
            logger.error(f"Fatal error in SSE event generator setup for {symbol}/{resolution}: {e}", exc_info=True)
            try:
                yield {"event": "error", "data": json.dumps({"error": str(e)})}
            except Exception:  # If yielding error also fails (e.g. client disconnected)
                pass
        finally:
            logger.info(f"SSE event generator for {symbol}/{resolution} finished.")
    return EventSourceResponse(event_generator())


async def stream_live_data_websocket_endpoint(websocket: WebSocket, symbol: str):
    # SECURITY FIX: Validate symbol BEFORE accepting WebSocket connection
    # This prevents accepting connections for invalid/malicious symbols
    if symbol not in SUPPORTED_SYMBOLS:
        logger.warning(f"SECURITY: Unsupported symbol '{symbol}' requested for live data WebSocket - rejecting before accept")
        await websocket.close(code=1008, reason="Unsupported symbol")
        return

    # Accept the WebSocket connection only for valid symbols
    await websocket.accept()
    logger.info(f"WebSocket connection accepted for live data: {symbol}")

    # --- Client-specific state for throttling ---
    client_stream_state = {
        "last_sent_timestamp": 0.0,
        "stream_delta_seconds": 1,  # Default, will be updated from settings
        "last_settings_check_timestamp": 0.0,  # For periodically re-checking settings
        "settings_check_interval_seconds": 3,  # How often to check settings (e.g., every 3 seconds)
        "last_sent_live_price": None,  # Track last sent live price to avoid duplicate sends
        "last_positions_update": 0.0,  # Track last positions update
        "positions_update_interval": 10,  # Update positions every 10 seconds
        "cached_positions": []  # Cache positions data
    }

    try:
        redis_conn = await get_redis_connection()
        settings_key = f"settings:{symbol}"
        logger.info(f"Live stream for {symbol}: Attempting to GET settings from Redis key: '{settings_key}'")
        settings_json = await redis_conn.get(settings_key)
        if settings_json:
            logger.info(f"Live stream for {symbol}: Found settings_json in Redis: {settings_json}")
            symbol_settings = json.loads(settings_json)
            retrieved_delta_time = symbol_settings.get('streamDeltaTime', 0)  # Get value before int conversion for logging
            logger.info(f"Live stream for {symbol}: Retrieved 'streamDeltaTime' from symbol_settings: {retrieved_delta_time} (type: {type(retrieved_delta_time)})")
            client_stream_state["stream_delta_seconds"] = int(retrieved_delta_time)
            logger.info(f"Live stream for {symbol}: Using stream_delta_seconds = {client_stream_state['stream_delta_seconds']}")
        else:
            logger.warning(f"Live stream for {symbol}: No settings_json found in Redis for key '{settings_key}'. Defaulting stream_delta_seconds to 0.")
            client_stream_state["stream_delta_seconds"] = 0
        client_stream_state["last_settings_check_timestamp"] = time.time()  # Initialize after first load attempt
    except Exception as e:
        logger.error(f"Error fetching or processing streamDeltaTime settings for {symbol}: {e}. Defaulting stream_delta_seconds to 0.", exc_info=True)
        client_stream_state["stream_delta_seconds"] = 0

    # --- End client-specific state ---
    client_stream_state["last_settings_check_timestamp"] = time.time()  # Initialize even on error

    # Get the current asyncio event loop
    loop = asyncio.get_running_loop()

    bybit_ws_client = BybitWS(
        testnet=False,
        channel_type="linear"
    )

    async def send_to_client(data_to_send: Dict[str, Any]):
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json(data_to_send)
        except WebSocketDisconnect:
            logger.info(f"Client (live stream {symbol}) disconnected while trying to send data.")
        except Exception as e:
            error_str = str(e)
            if "Cannot call \"send\" once a close message has been sent" in error_str:
                logger.debug(f"WebSocket send failed - close message already sent for {symbol}")
            elif "Cannot call \"send\" after WebSocket has been closed" in error_str:
                logger.debug(f"WebSocket send failed - connection already closed for {symbol}")
            elif "closed connection before send could complete" in error_str:
                logger.debug(f"WebSocket send failed - connection closed before completion for {symbol}")
            elif "Data should not be empty" in error_str:
                logger.debug(f"WebSocket send failed - empty buffer for {symbol}")
            else:
                logger.error(f"Unexpected RuntimeError sending data to client (live stream {symbol}): {e}")

    def bybit_message_handler(message: Dict[str, Any]):
        # This callback will run in a thread managed by pybit's WebSocket client.
        # To send data over FastAPI's WebSocket (which is async),
        # we need to schedule it on the event loop.
        logger.debug(f"Bybit Handler for {symbol}: Using stream_delta_seconds = {client_stream_state['stream_delta_seconds']}")  # Log current delta
        if "topic" in message and "data" in message:
            topic_str = message["topic"]  # topic is already a string
            # No need to split topic_str if we are only checking the full topic string
            # Check if the topic is for tickers and matches the requested symbol
            if topic_str == f"tickers.{symbol}":  # Direct comparison
                ticker_data = message["data"]
                # The ticker data structure might vary slightly based on Bybit's API version for V5 tickers.
                # Common fields include lastPrice, bid1Price, ask1Price.
                # We'll primarily use lastPrice.
                if "lastPrice" in ticker_data:
                    try:
                        # Timestamp 'ts' is at the same level as 'topic', 'type', 'data'
                        message_timestamp_ms = message.get("ts")
                        if message_timestamp_ms is None:
                            logger.warning(f"Timestamp 'ts' not found in Bybit ticker message for {symbol}. Using current server time. Message: {message}")
                            message_timestamp_ms = time.time() * 1000  # Fallback to current time in ms

                        current_server_timestamp_sec = time.time()
                        should_send = False
                        if client_stream_state["stream_delta_seconds"] == 0:
                            should_send = True
                        elif (current_server_timestamp_sec - client_stream_state["last_sent_timestamp"]) >= client_stream_state["stream_delta_seconds"]:
                            should_send = True

                        if should_send:
                            # Get live price from Redis using synchronous connection
                            live_price = None
                            try:
                                sync_redis = get_sync_redis_connection()
                                live_price_key = f"live:{symbol}"
                                price_str = sync_redis.get(live_price_key)
                                # logger.debug(f"Redis get result for key '{live_price_key}': {price_str}")
                                if price_str:
                                    live_price = float(price_str)
                                    # logger.info(f"✅ Retrieved live price from Redis for {symbol}: {live_price}")
                                else:
                                    logger.warning(f"⚠️ No live price found in Redis for {symbol} (key: {live_price_key})")
                            except Exception as e:
                                logger.error(f"❌ Failed to get live price from Redis for {symbol}: {e}", exc_info=True)

                            # Only send update if live price has changed or is the first price
                            should_send_price_update = (
                                live_price is not None and
                                live_price != client_stream_state["last_sent_live_price"]
                            )

                            if should_send_price_update:
                                live_data = {
                                    "symbol": ticker_data.get("symbol", symbol),
                                    "time": int(message_timestamp_ms) // 1000,
                                    "price": float(ticker_data["lastPrice"]),
                                    "vol": float(ticker_data.get("volume24h", 0)),
                                    "live_price": live_price  # Add live price from Redis
                                }
                                asyncio.run_coroutine_threadsafe(
                                    send_to_client(live_data),
                                    loop
                                )
                                client_stream_state["last_sent_timestamp"] = current_server_timestamp_sec
                                client_stream_state["last_sent_live_price"] = live_price
                                # logger.debug(f"📤 Sent live price update for {symbol}: {live_price} (changed from {client_stream_state['last_sent_live_price']})")
                    except Exception as e:
                        logger.error(f"Error processing or scheduling send for Bybit ticker data for {symbol}: {e} - Data: {ticker_data}")

    # Pass the handler to the subscribe method
    topics = 'tickers.{symbol}'
    symbols = [f'{symbol}']
    logger.info(f"Subscribing Bybit WebSocket to:  ")
    bybit_ws_client.subscribe(topic=topics, callback=bybit_message_handler, symbol=symbols)

    # Store reference to client for proper cleanup
    websocket_client_ref = bybit_ws_client

    try:
        # The pybit client is handling messages in its own thread and calling bybit_message_handler.
        # This loop is just to keep the FastAPI WebSocket connection open
        # and to allow for graceful exit when the client disconnects.
        while websocket.client_state == WebSocketState.CONNECTED:
            current_loop_time = time.time()
            # Periodically re-check settings from Redis
            if (current_loop_time - client_stream_state["last_settings_check_timestamp"]) >= client_stream_state["settings_check_interval_seconds"]:
                try:
                    redis_conn_check = await get_redis_connection()
                    settings_key_check = f"settings:{symbol}"
                    settings_json_check = await redis_conn_check.get(settings_key_check)
                    if settings_json_check:
                        symbol_settings_check = json.loads(settings_json_check)
                        # Default to current state's delta if key is missing, to avoid reverting to 0 if Redis temporarily has no setting
                        new_delta = int(symbol_settings_check.get('streamDeltaTime', client_stream_state["stream_delta_seconds"]))
                        if new_delta != client_stream_state["stream_delta_seconds"]:
                            logger.info(f"Live stream for {symbol}: Polled settings changed. Updating stream_delta_seconds from {client_stream_state['stream_delta_seconds']} to {new_delta}")
                            client_stream_state["stream_delta_seconds"] = new_delta
                    client_stream_state["last_settings_check_timestamp"] = current_loop_time
                except Exception as e_settings_check:
                    logger.error(f"Error re-checking settings for {symbol} in WebSocket loop: {e_settings_check}", exc_info=True)
                    # Still update timestamp to avoid rapid retries on persistent error
                    client_stream_state["last_settings_check_timestamp"] = current_loop_time
            await asyncio.sleep(0.1)  # Keep alive and allow other tasks to run

    except WebSocketDisconnect:
        logger.info(f"Client disconnected from live stream for {symbol} (WebSocketDisconnect received).")
    except asyncio.CancelledError:
        logger.info(f"Live stream task for {symbol} was cancelled.")
        # Important to re-raise CancelledError so Uvicorn/FastAPI can handle task cancellation properly.
        # The 'finally' block will still execute for cleanup.
        raise
    except Exception as e:
        logger.error(f"Error in live data WebSocket for {symbol}: {e}", exc_info=True)
    finally:
        logger.info(f"Initiating cleanup for WebSocket and Bybit connection for live data: {symbol}")

        # Attempt to gracefully close the Bybit WebSocket connection
        # The pybit WebSocket client runs in its own thread. exit() signals it to stop.
        if 'bybit_ws_client' in locals() and hasattr(bybit_ws_client, 'exit') and callable(bybit_ws_client.exit):
            try:
                logger.info(f"Attempting to call bybit_ws_client.exit() for {symbol}")
                bybit_ws_client.exit()  # This is a synchronous call
                logger.info(f"Called bybit_ws_client.exit() for {symbol}")
            except Exception as e_bybit_exit:
                logger.error(f"Error calling bybit_ws_client.exit() for {symbol}: {e_bybit_exit}")
        else:
            logger.warning(f"bybit_ws_client for {symbol} not defined or does not have a callable 'exit' method at cleanup.")

        # Attempt to close the FastAPI WebSocket connection
        if websocket.client_state != WebSocketState.DISCONNECTED:
            logger.info(f"FastAPI WebSocket for {symbol} client_state is {websocket.client_state}, attempting close.")
            try:
                await websocket.close()
                logger.info(f"FastAPI WebSocket for {symbol} successfully closed in finally block.")
            except RuntimeError as e_rt:
                if "Cannot call \"send\" once a close message has been sent" in str(e_rt) or \
                   "Cannot call \"send\" after WebSocket has been closed" in str(e_rt):
                    logger.warning(f"FastAPI WebSocket for {symbol} was already closing/closed when finally tried to close: {e_rt}")
                else:
                    logger.error(f"RuntimeError during FastAPI WebSocket close for {symbol}: {e_rt}", exc_info=True)  # Log other RuntimeErrors
            except Exception as e_close:  # Catch any other unexpected errors during close
                logger.error(f"Unexpected error closing FastAPI WebSocket for {symbol}: {e_close}", exc_info=True)
        else:
            logger.info(f"FastAPI WebSocket for {symbol} client_state was already DISCONNECTED in finally block.")

        logger.info(f"Cleanup finished for WebSocket and Bybit connection for live data: {symbol}")


async def calculate_indicators_for_data(klines: List[Dict], indicators: List[str]) -> Dict[str, Any]:
    """
    Calculate indicators for the given klines data.
    """
    logger.debug(f"calculate_indicators_for_data: {len(klines) if klines else 0} klines, {len(indicators) if indicators else 0} indicators")
    if not klines or not indicators:
        logger.debug("Early return - no klines or no indicators")
        return {}

    # Prepare DataFrame from klines data (OI data not needed for most indicators)
    df = _prepare_dataframe(klines, None)
    if df is None or df.empty:
        logger.warning(f"Failed to prepare DataFrame from {len(klines)} klines")
        return {}

    indicators_data = {}

    for indicator_id in indicators:
        logger.info(f"🔍 INDICATOR DEBUG: Processing indicator {indicator_id}")
        config = next((item for item in AVAILABLE_INDICATORS if item["id"] == indicator_id), None)
        if not config:
            logger.warning(f"Unknown indicator {indicator_id} requested for active_symbol")
            continue

        try:
            params = config["params"]
            calc_id = config["id"]
            logger.info(f"🔍 INDICATOR DEBUG: Indicator {indicator_id} config: calc_id={calc_id}, params={params}")

            if calc_id == "macd":
                # logger.info(f"🔍 INDICATOR DEBUG: Calling calculate_macd for {indicator_id}")
                result = calculate_macd(df.copy(), **params)
                # logger.info(f"🔍 INDICATOR DEBUG: MACD result type: {type(result)}, is None: {result is None}")
            elif calc_id == "rsi":
                # logger.info(f"🔍 INDICATOR DEBUG: Calling calculate_rsi for {indicator_id}")
                result = calculate_rsi(df.copy(), **params)
                # logger.info(f"🔍 INDICATOR DEBUG: RSI result type: {type(result)}, is None: {result is None}")
            elif calc_id.startswith("stochrsi"):
                # logger.info(f"🔍 INDICATOR DEBUG: Calling calculate_stoch_rsi for {indicator_id}")
                # Filter out lookback_period from params as it's only used for data retrieval
                stoch_params = {k: v for k, v in params.items() if k != "lookback_period"}
                result = calculate_stoch_rsi(df.copy(), **stoch_params)
                # logger.info(f"🔍 INDICATOR DEBUG: STOCHRSI result type: {type(result)}, is None: {result is None}")
            elif calc_id == "open_interest":
                # logger.info(f"🔍 INDICATOR DEBUG: Calling calculate_open_interest for {indicator_id}")
                result = calculate_open_interest(df.copy())
                # logger.info(f"🔍 INDICATOR DEBUG: OI result type: {type(result)}, is None: {result is None}")
            elif calc_id == "jma":
                # logger.info(f"🔍 INDICATOR DEBUG: Calling calculate_jma_indicator for {indicator_id}")
                result = calculate_jma_indicator(df.copy(), **params)
                # logger.info(f"🔍 INDICATOR DEBUG: JMA result type: {type(result)}, is None: {result is None}")
            elif calc_id == "cto_line":
                # logger.info(f"🔍 INDICATOR DEBUG: Calling calculate_cto_line for {indicator_id}")
                result = calculate_cto_line(df.copy(), **params)
                # logger.info(f"🔍 INDICATOR DEBUG: CTO Line result type: {type(result)}, is None: {result is None}")
            else:
                # logger.warning(f"Unsupported indicator calculation {calc_id}")
                continue

            # logger.info(f"🔍 INDICATOR DEBUG: Indicator {indicator_id} calculation result: {result is not None}")
            if result:
                # logger.info(f"🔍 INDICATOR DEBUG: Indicator {indicator_id} result keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}")
                if "t" in result:
                    #logger.info(f"🔍 INDICATOR DEBUG: Indicator {indicator_id} has 't' key with {len(result['t'])} timestamps")
                    indicators_data[indicator_id] = result
                    # logger.info(f"🔍 INDICATOR DEBUG: Successfully added {indicator_id} to indicators_data")
            else:
                logger.warning(f"Indicator {indicator_id} calculation returned None")

        except Exception as e:
            logger.error(f"Error calculating indicator {indicator_id}: {e}", exc_info=True)
            import traceback
            logger.error(f"📋 INDICATOR ERROR TRACEBACK:\n{traceback.format_exc()}")

    return indicators_data


async def stream_combined_data_websocket_endpoint(websocket: WebSocket, symbol: str):
    """Combined WebSocket endpoint that streams historical OHLC data with indicators and live data from Redis."""

    # SECURITY FIX: Validate symbol BEFORE accepting WebSocket connection
    # This prevents accepting connections for invalid/malicious symbols like ".ENV"
    if symbol not in SUPPORTED_SYMBOLS:
        logger.warning(f"SECURITY: Unsupported symbol '{symbol}' requested for combined data WebSocket - rejecting before accept")
        await websocket.close(code=1008, reason="Unsupported symbol")
        return

    # Accept the WebSocket connection only for valid symbols
    await websocket.accept()
    logger.info(f"WebSocket connection accepted for combined data: {symbol}")

    # Client state
    client_state = {
        "indicators": [],  # List of indicator IDs the client wants
        "resolution": "1h",  # Default resolution
        "from_ts": None,  # Historical data start timestamp
        "to_ts": None,  # Historical data end timestamp
        "historical_sent": False,  # Whether historical data has been sent
        "live_mode": False,  # Whether we're in live streaming mode
        "last_sent_timestamp": 0.0,
        "stream_delta_seconds": 1,  # Default, will be updated from settings (0 for no throttle)
        "last_settings_check_timestamp": 0.0,  # For periodically re-checking settings
        "settings_check_interval_seconds": 3,  # How often to check settings (e.g., every 3 seconds)
        "last_positions_update": 0.0,
        "positions_update_interval": 10,
        "cached_positions": []
    }

    # Initialize active_symbol with URL path symbol (will be updated from message if provided)
    active_symbol = symbol
    last_active_symbol = None  # Track for live streaming symbol changes

    # Register client in Redis for smart notifications
    client_id = f"client:{id(websocket)}"
    notification_stream_key = f"notify:{client_id}"
    try:
        redis = await get_redis_connection()

        # Ensure all values are properly converted to strings
        symbol_val = str(active_symbol) if active_symbol is not None else ""
        resolution_val = str(client_state["resolution"]) if client_state["resolution"] is not None else "1h"
        from_ts_val = str(client_state["from_ts"]) if client_state["from_ts"] is not None else "0"
        to_ts_val = str(client_state["to_ts"]) if client_state["to_ts"] is not None else "0"
        last_update_val = str(time.time())

        logger.debug(f"DEBUG Redis registration: symbol={symbol_val} (type: {type(active_symbol)}), resolution={resolution_val} (type: {type(client_state['resolution'])}), from_ts={from_ts_val} (type: {type(client_state['from_ts'])}), to_ts={to_ts_val} (type: {type(client_state['to_ts'])})")

        # Use individual key-value pairs instead of dictionary
        await redis.hset(client_id, "symbol", symbol_val)
        await redis.hset(client_id, "resolution", resolution_val)
        await redis.hset(client_id, "from_ts", from_ts_val)
        await redis.hset(client_id, "to_ts", to_ts_val)
        await redis.hset(client_id, "last_update", last_update_val)

        # Set TTL for client data (24 hours)
        await redis.expire(client_id, 86400)
        logger.info(f"Registered client {client_id} for smart notifications")
    except Exception as e:
        logger.error(f"Failed to register client {client_id} in Redis: {e}")
        logger.error(f"Redis registration values: symbol={active_symbol} (type: {type(active_symbol)}), resolution={client_state.get('resolution')} (type: {type(client_state.get('resolution'))}), from_ts={client_state.get('from_ts')} (type: {type(client_state.get('from_ts'))}), to_ts={client_state.get('to_ts')} (type: {type(client_state.get('to_ts'))})")

    async def send_to_client(data_to_send: Dict[str, Any]):
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json(data_to_send)
        except WebSocketDisconnect:
            logger.info(f"Client (combined data {active_symbol}) disconnected while trying to send data.")
        except Exception as e:
            error_str = str(e)
            if "Cannot call \"send\" once a close message has been sent" in error_str:
                logger.debug(f"WebSocket send failed - close message already sent for {active_symbol}")
            elif "Cannot call \"send\" after WebSocket has been closed" in error_str:
                logger.debug(f"WebSocket send failed - connection already closed for {active_symbol}")
            elif "closed connection before send could complete" in error_str:
                logger.debug(f"WebSocket send failed - connection closed before completion for {active_symbol}")
            elif "Data should not be empty" in error_str:
                logger.debug(f"WebSocket send failed - empty buffer for {active_symbol}")
            elif "[Errno 22] Invalid argument" in error_str:
                logger.error(f"Socket error sending data to client (combined data {active_symbol}): {e}", exc_info=True)
            else:
                logger.error(f"Unexpected error sending data to client (combined data {active_symbol}): {e}", exc_info=True)

    # Start notification listener task
    async def listen_for_notifications():
        """Listen for smart notifications from Redis and forward to client."""
        try:
            redis = await get_redis_connection()
            group_name = f"notify:{client_id}"
            consumer_id = f"consumer:{id(websocket)}"

            # Create consumer group if it doesn't exist
            try:
                await redis.xgroup_create(notification_stream_key, group_name, id='0', mkstream=True)
            except Exception as e:
                if "BUSYGROUP" not in str(e):
                    logger.error(f"Failed to create notification consumer group for {client_id}: {e}")
                    return

            logger.info(f"Started notification listener for client {client_id}")

            while websocket.client_state == WebSocketState.CONNECTED:
                try:
                    current_time = time.time()

                    # Periodically send positions updates (independent of price ticks)
                    if current_time - client_state.get("last_positions_update", 0) >= client_state.get("positions_update_interval", 10):
                        try:
                            # Get user email for positions fetching
                            email = None
                            if hasattr(websocket, 'scope') and 'session' in websocket.scope:
                                email = websocket.scope['session'].get('email')
                            positions = await fetch_positions_from_trading_service(email, active_symbol)
                            client_state["cached_positions"] = positions
                            client_state["last_positions_update"] = current_time

                            # Only send positions update if there are actual positions
                            if positions and len(positions) > 0:
                                positions_message = {
                                    "type": "positions_update",
                                    "symbol": active_symbol,  # Include symbol for context
                                    "positions": positions,
                                    "timestamp": int(current_time)
                                }
                                await send_to_client(positions_message)
                                logger.debug(f"📊 Sent positions update with {len(positions)} positions")
                        except Exception as pos_e:
                            logger.warning(f"Failed to update and send positions: {pos_e}")

                    # Read notifications with 1 second timeout
                    messages = await redis.xreadgroup(
                        group_name, consumer_id, {notification_stream_key: ">"}, count=10, block=1000
                    )

                    if messages:
                        for _stream_name, message_list in messages:
                            for message_id, message_data_dict in message_list:
                                try:
                                    notification_json = message_data_dict.get('data')
                                    if notification_json:
                                        notification = json.loads(notification_json)

                                        # Forward notification to client
                                        await send_to_client(notification)
                                        logger.debug(f"Forwarded notification to client {client_id}: {notification.get('type')}")

                                        # Acknowledge the message
                                        await redis.xack(notification_stream_key, group_name, message_id)

                                except Exception as e:
                                    logger.error(f"Error processing notification {message_id} for {client_id}: {e}")
                                    continue

                    await asyncio.sleep(0.1)

                except Exception as e:
                    logger.error(f"Error in notification listener loop for {client_id}: {e}")
                    await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Error in notification listener for {client_id}: {e}")

    # Start the notification listener task
    notification_task = asyncio.create_task(listen_for_notifications())

    async def send_historical_data() -> bool:
        """Send historical OHLC data with indicators. Returns True if data was sent successfully."""
        try:
            logger.info(f"Sending historical data for {active_symbol} with indicators: {client_state['indicators']}")
            logger.info(f"Time range: from_ts={client_state['from_ts']}, to_ts={client_state['to_ts']}, resolution={client_state['resolution']}")

            # Get historical klines from Redis
            try:
                logger.debug(f"Requesting klines for {active_symbol}: from_ts={client_state['from_ts']}, to_ts={client_state['to_ts']}")
                klines = await get_cached_klines(active_symbol, client_state["resolution"], client_state["from_ts"], client_state["to_ts"])
                logger.info(f"✅ Retrieved {len(klines) if klines else 0} klines from Redis for {active_symbol}")
            except Exception as e:
                logger.error(f"❌ Failed to get cached klines from Redis for {active_symbol}: {e}", exc_info=True)
                return False

            if not klines or len(klines) == 0:
                logger.warning(f"⚠️ No historical data available for {active_symbol}. Sending empty historical message.")
                # Send empty historical data message to indicate completion
                try:
                    await send_to_client({
                        "type": "historical",
                        "symbol": active_symbol,
                        "data": []
                    })
                    logger.info(f"✅ Sent empty historical data for {active_symbol} (no data available)")
                    return True
                except Exception as e:
                    logger.error(f"Failed to send empty historical data: {e}")
                    return False

            # Calculate indicators
            try:
                logger.info(f"Calculating indicators for {active_symbol}: {client_state['indicators']}")
                indicators_data = await calculate_indicators_for_data(klines, client_state["indicators"])
                logger.info(f"📊 Indicators calculated: {list(indicators_data.keys()) if indicators_data else 'none'}")
            except Exception as e:
                logger.error(f"Failed to calculate indicators for {active_symbol}: {e}", exc_info=True)
                indicators_data = {}

            # Prepare and send combined data
            combined_data = []
            for kline in klines:
                data_point = {
                    "time": kline["time"],
                    "ohlc": {
                        "open": kline["open"],
                        "high": kline["high"],
                        "low": kline["low"],
                        "close": kline["close"],
                        "volume": kline["vol"]
                    },
                    "indicators": {}
                }

                # Add indicator values for this timestamp
                for indicator_id, indicator_values in indicators_data.items():
                    if "t" in indicator_values:
                        # Find the index for this timestamp
                        if kline["time"] in indicator_values["t"]:
                            idx = indicator_values["t"].index(kline["time"])
                            temp_indicator = {}
                            for key, values in indicator_values.items():
                                if key != "t" and idx < len(values):
                                    temp_indicator[key] = values[idx]

                            if temp_indicator:
                                data_point["indicators"][indicator_id] = temp_indicator

                combined_data.append(data_point)

            # Send data in batches
            data_sent = False
            batch_size = 100
            for i in range(0, len(combined_data), batch_size):
                batch = combined_data[i:i + batch_size]
                try:
                    await send_to_client({
                        "type": "historical",
                        "symbol": active_symbol,
                        "data": batch
                    })
                    data_sent = True
                except Exception as e:
                    logger.error(f"Failed to send historical data batch: {e}")
                    break

                await asyncio.sleep(0.01)  # Small delay to prevent overwhelming client

            if data_sent:
                logger.info(f"✅ Sent {len(combined_data)} historical data points for {active_symbol}")

                # Send drawings after historical data
                try:
                    # Get user email for drawing access control
                    email = None
                    if hasattr(websocket, 'scope') and 'session' in websocket.scope:
                        email = websocket.scope['session'].get('email')

                    drawings = await get_drawings(active_symbol, None, client_state["resolution"], email)

            # Send drawings message
                    await send_to_client({
                        "type": "drawings",
                        "symbol": active_symbol,
                        "resolution": client_state["resolution"],
                        "drawings": drawings,
                        "timestamp": int(time.time())
                    })
                    # logger.info(f"✅ Sent {len(drawings)} drawings for {active_symbol}")

                    # Send trading session data based on active positions and recent activity
                    # Only send if time range is less than 1 week (7 days) to avoid performance issues with large charts
                    try:
                        if client_state["from_ts"] and client_state["to_ts"]:
                            time_range_duration_seconds = client_state["to_ts"] - client_state["from_ts"]
                            time_range_duration_days = time_range_duration_seconds / (24 * 60 * 60)

                            if time_range_duration_days < 7:  # Less than 1 week
                                trading_sessions = await calculate_trading_sessions(active_symbol, client_state["from_ts"], client_state["to_ts"])
                                if trading_sessions and len(trading_sessions) > 0:
                                    await send_to_client({
                                        "type": "trading_sessions",
                                        "symbol": active_symbol,
                                        "data": trading_sessions,  # Frontend expects message.data
                                        "timestamp": int(time.time())
                                    })
                                    logger.info(f"✅ Sent {len(trading_sessions)} trading sessions for {active_symbol} (time range: {time_range_duration_days:.1f} days)")
                            else:
                                logger.info(f"📊 Time range too large ({time_range_duration_days:.1f} days), skipping trading sessions to avoid performance issues with large charts")
                    except Exception as session_e:
                        logger.warning(f"Failed to send trading sessions: {session_e}")

                    # Calculate and send volume profile for rectangle drawings within the time range
                    try:
                        client_from_ts = client_state.get("from_ts")
                        client_to_ts = client_state.get("to_ts")
                        logger.debug(f"DEBUG Volume Profile: client_from_ts={client_from_ts}, client_to_ts={client_to_ts}")
                        logger.debug(f"DEBUG Volume Profile: Total drawings received: {len(drawings)}")

                        # Debug: show all drawing types
                        drawing_types = {}
                        for d in drawings:
                            d_type = d.get("type", "unknown")
                            if d_type not in drawing_types:
                                drawing_types[d_type] = 0
                            drawing_types[d_type] += 1
                        logger.debug(f"DEBUG Volume Profile: Drawing types count: {drawing_types}")

                        # Debug: show rectangle drawings and their time info
                        rectangle_drawings_raw = [d for d in drawings if d.get("type") == "rect"]
                        logger.debug(f"DEBUG Volume Profile: Found {len(rectangle_drawings_raw)} rectangle drawings total")

                        for i, rect in enumerate(rectangle_drawings_raw):
                            rect_id = rect.get("id", f"rect_{i}")
                            start_time = rect.get("start_time", 0)
                            end_time = rect.get("end_time", 0)
                            logger.debug(f"DEBUG Volume Profile: Rectangle {rect_id}: start_time={start_time}, end_time={end_time}")

                        if client_from_ts and client_to_ts:
                            rectangle_drawings = [
                                d for d in drawings
                                if d.get("type") == "rect" and
                                   d.get("start_time", 0) <= client_to_ts and
                                   d.get("end_time", 0) >= client_from_ts
                            ]
                            logger.info(f"Found {len(rectangle_drawings)} rectangle drawings within time range for volume profile")

                            # Debug: show why rectangles were filtered out
                            for i, rect in enumerate(rectangle_drawings_raw):
                                rect_id = rect.get("id", f"rect_{i}")
                                start_time = rect.get("start_time", 0)
                                end_time = rect.get("end_time", 0)

                                in_range = (start_time >= client_from_ts and end_time <= client_to_ts)
                                logger.debug(f"DEBUG Volume Profile: Rectangle {rect_id} time filter check:")
                                logger.debug(f"  - start_time={start_time} >= client_from_ts={client_from_ts}? {start_time >= client_from_ts}")
                                logger.debug(f"  - end_time={end_time} <= client_to_ts={client_to_ts}? {end_time <= client_to_ts}")
                                logger.debug(f"  - PASS time filter? {in_range}")
                        else:
                            logger.warning(f"DEBUG Volume Profile: Skipping rectangle filtering - client_from_ts or client_to_ts is None")

                        # Process rectangle drawings that passed the time filter
                        for rect_drawing in rectangle_drawings:
                            drawing_id = rect_drawing.get("id")
                            start_time = rect_drawing.get("start_time")
                            end_time = rect_drawing.get("end_time")
                            start_price = rect_drawing.get("start_price")
                            end_price = rect_drawing.get("end_price")

                            if not all([start_time, end_time, start_price is not None, end_price is not None]):
                                logger.warning(f"Incomplete rectangle data for drawing {drawing_id}")
                                continue

                            price_min = min(float(start_price), float(end_price))
                            price_max = max(float(start_price), float(end_price))

                            # Fetch klines for this rectangle's time range
                            rect_klines = await get_cached_klines(active_symbol, client_state["resolution"], start_time, end_time)
                            logger.debug(f"Fetched {len(rect_klines)} klines for rectangle {drawing_id} time range")

                            if not rect_klines:
                                logger.warning(f"No klines available for rectangle {drawing_id}")
                                continue

                            # Filter klines that intersect with the rectangle's price range
                            filtered_klines = [
                                k for k in rect_klines
                                if k.get('high', 0) >= price_min and k.get('low', 0) <= price_max
                            ]
                            logger.debug(f"Filtered to {len(filtered_klines)} klines within price range [{price_min}, {price_max}] for rectangle {drawing_id}")

                            if not filtered_klines:
                                logger.warning(f"No klines within price range for rectangle {drawing_id}")
                                continue

                            # Calculate volume profile for the filtered data
                            volume_profile_data = calculate_volume_profile(filtered_klines)
                            logger.info(f"Calculated volume profile for rectangle {drawing_id} with {len(volume_profile_data.get('volume_profile', []))} price levels")

                            # Send volume profile data for this rectangle
                            await send_to_client({
                                "type": "volume_profile",
                                "symbol": active_symbol,
                                "rectangle_id": drawing_id,
                                "rectangle": {
                                    "start_time": start_time,
                                    "end_time": end_time,
                                    "start_price": start_price,
                                    "end_price": end_price
                                },
                                "data": volume_profile_data,
                                "timestamp": int(time.time())
                            })
                            logger.debug(f"Sent volume profile for rectangle {drawing_id}")

                    except Exception as e:
                        logger.error(f"Failed to process volume profile for rectangles: {e}", exc_info=True)
                except Exception as e:
                    logger.warning(f"Failed to send drawings for {active_symbol}: {e}")

                return True
            else:
                logger.error(f"Failed to send any historical data for {active_symbol}")
                return False

        except Exception as e:
            logger.error(f"Error sending historical data for {active_symbol}: {e}", exc_info=True)
            return False

    # Task for streaming live data concurrently with message handling
    live_stream_task = None

    def start_live_streaming():
        """Start live data streaming task when live_mode is enabled."""
        async def live_stream_worker():
            """Streams live price updates from Redis."""
            while websocket.client_state == WebSocketState.CONNECTED and client_state.get("live_mode", False):
                try:
                    current_time = time.time()
                    should_send = False

                    # Check if enough time has passed since last send
                    if (current_time - client_state["last_sent_timestamp"]) >= client_state["stream_delta_seconds"]:
                        should_send = True

                    # Update settings periodically
                    if (current_time - client_state["last_settings_check_timestamp"]) >= client_state["settings_check_interval_seconds"]:
                        try:
                            redis_conn = await get_redis_connection()
                            settings_key = f"settings:{active_symbol}"
                            settings_json = await redis_conn.get(settings_key)
                            if settings_json:
                                symbol_settings = json.loads(settings_json)
                                new_delta = int(symbol_settings.get('streamDeltaTime', client_state["stream_delta_seconds"]))
                                if new_delta != client_state["stream_delta_seconds"]:
                                    logger.info(f"Live stream for {active_symbol}: Settings changed. Updating stream_delta_seconds from {client_state['stream_delta_seconds']} to {new_delta}")
                                    client_state["stream_delta_seconds"] = new_delta
                            client_state["last_settings_check_timestamp"] = current_time
                        except Exception as e_settings_check:
                            logger.error(f"Error re-checking settings in live mode for {active_symbol}: {e_settings_check}")

                    if should_send:
                        # Get live price from Redis and check if it has actually changed
                        try:
                            sync_redis = get_sync_redis_connection()
                            live_price_key = f"live:{active_symbol}"
                            price_str = sync_redis.get(live_price_key)
                            if price_str:
                                live_price = float(price_str)

                                # Only send update if live price has changed or is the first price
                                should_send_price_update = (
                                    live_price != client_state.get("last_sent_live_price")
                                )

                                if should_send_price_update or client_state.get("last_sent_live_price") is None:
                                    live_data = {
                                        "type": "live",
                                        "symbol": active_symbol,
                                        "data": {
                                            "live_price": live_price,
                                            "time": int(current_time)
                                        }
                                    }
                                    await send_to_client(live_data)
                                    client_state["last_sent_timestamp"] = current_time
                                    client_state["last_sent_live_price"] = live_price
                                    # logger.debug(f"📤 Sent live price update for {active_symbol}: {live_price} (changed from {client_state.get('last_sent_live_price')})")
                        except Exception as e:
                            logger.error(f"Failed to get live price from Redis for {active_symbol}: {e}")

                    await asyncio.sleep(0.5)  # Check more frequently than old 0.1 to avoid overloading

                except Exception as e:
                    logger.error(f"Error in live data stream worker: {e}")
                    break

        nonlocal live_stream_task
        if live_stream_task is None or live_stream_task.done():
            live_stream_task = asyncio.create_task(live_stream_worker())
            logger.info(f"Started live streaming task for {active_symbol}")

    # Message handling loop
    try:
        while websocket.client_state == WebSocketState.CONNECTED:
            try:
                # Try to receive message from client with timeout
                message = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)

                message_type = message.get("type")
                logger.info(f"Received WebSocket message: {message_type}")

                if message_type == "ping":
                    # Handle ping messages to keep connection alive
                    await websocket.send_json({"type": "pong"})
                    continue


                elif message_type == "history":
                    # Handle history request from client
                    symbol = message.get("data", {}).get("symbol", active_symbol)
                    email = message.get("data", {}).get("email")
                    min_value_percentage = message.get("data", {}).get("minValuePercentage", 0)

                    logger.info(f"Processing history request for symbol {symbol}, email {email}, minValuePercentage {min_value_percentage}")

                    try:
                        # Get current time range from client state
                        from_ts = client_state.get("from_ts")
                        to_ts = client_state.get("to_ts")
                        resolution = client_state.get("resolution", "1h")
                        indicators = client_state.get("active_indicators", [])

                        if not from_ts or not to_ts:
                            logger.warning("No time range specified for history request")
                            continue

                        # Fetch historical klines
                        klines = await get_cached_klines(symbol, resolution, from_ts, to_ts)
                        logger.info(f"Fetched {len(klines) if klines else 0} klines for history")

                        # Calculate indicators
                        indicators_data = await calculate_indicators_for_data(klines, indicators)
                        logger.info(f"Calculated indicators: {list(indicators_data.keys()) if indicators_data else 'none'}")

                        # Fetch and filter trades based on min value percentage
                        trades = await fetch_recent_trade_history(symbol, from_ts, to_ts)
                        if trades and len(trades) > 0 and min_value_percentage > 0:
                            # Calculate max trade value for filtering
                            trade_values = [trade['price'] * trade['quantity'] for trade in trades if 'price' in trade and 'quantity' in trade]
                            if trade_values:
                                max_trade_value = max(trade_values)
                                min_volume = min_value_percentage * max_trade_value
                                trades = [trade for trade in trades if (trade.get('price', 0) * trade.get('quantity', 0)) >= min_volume]
                                logger.info(f"Filtered trades: {len(trades)} remain after filtering with {min_value_percentage*100}% min value")

                        # Prepare combined data
                        combined_data = []
                        if klines:
                            for kline in klines:
                                data_point = {
                                    "time": kline["time"],
                                    "ohlc": {
                                        "open": kline["open"],
                                        "high": kline["high"],
                                        "low": kline["low"],
                                        "close": kline["close"],
                                        "volume": kline["vol"]
                                    },
                                    "indicators": {}
                                }

                                # Add indicator values for this timestamp
                                for indicator_id, indicator_values in indicators_data.items():
                                    if "t" in indicator_values and kline["time"] in indicator_values["t"]:
                                        idx = indicator_values["t"].index(kline["time"])
                                        temp_indicator = {}
                                        for key, values in indicator_values.items():
                                            if key != "t" and idx < len(values):
                                                temp_indicator[key] = values[idx]
                                        if temp_indicator:
                                            data_point["indicators"][indicator_id] = temp_indicator

                                combined_data.append(data_point)

                        # Send history_success message
                        await send_to_client({
                            "type": "history_success",
                            "symbol": symbol,
                            "email": email,
                            "data": {
                                "ohlcv": combined_data,
                                "trades": trades or [],
                                "indicators": list(indicators_data.keys())
                            },
                            "timestamp": int(time.time())
                        })
                        logger.info(f"Sent history_success with {len(combined_data)} OHLCV points and {len(trades) if trades else 0} trades")

                    except Exception as e:
                        logger.error(f"Failed to process history request: {e}")
                        continue


            except asyncio.TimeoutError:
                # No message within timeout, just continue
                continue

            except Exception as e:
                logger.error(f"Error handling WebSocket message: {e}")
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_json({"type": "error", "message": str(e)})
                break

    except WebSocketDisconnect:
        logger.info(f"Client disconnected from combined data stream for {active_symbol}")
    except Exception as e:
        logger.error(f"Error in combined WebSocket endpoint: {e}")
    finally:
        # Cleanup notification task
        if 'notification_task' in locals():
            notification_task.cancel()
            try:
                await notification_task
            except asyncio.CancelledError:
                pass

        # Clean up Redis client registration
        try:
            redis_conn = await get_redis_connection()
            await redis_conn.delete(client_id)
            logger.info(f"Cleaned up client registration {client_id}")
        except Exception as e:
            logger.error(f"Error cleaning up client registration: {e}")
