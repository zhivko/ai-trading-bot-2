# Background tasks for data fetching and processing

import asyncio
import json
from datetime import datetime, timezone, timedelta
from config import SUPPORTED_SYMBOLS, timeframe_config, TRADING_SYMBOL, TRADING_TIMEFRAME, SUPPORTED_EXCHANGES, TRADE_AGGREGATION_RESOLUTION
from redis_utils import (
    get_cached_klines, cache_klines, get_cached_open_interest,
    cache_open_interest, publish_resolution_kline, detect_gaps_in_cached_data, fill_data_gaps,
    get_cached_trades, cache_trades, publish_trade_bar, detect_gaps_in_trade_data,
    fill_trade_data_gaps, fetch_trades_from_ccxt, aggregate_trades_to_bars,
    get_redis_connection
)
from redis_utils import fetch_klines_from_bybit
from indicators import fetch_open_interest_from_bybit
from logging_config import logger
from bybit_price_feed import start_bybit_price_feed

async def fetch_and_publish_klines():
    logger.info("🚀 STARTING BACKGROUND TASK: fetch_and_publish_klines")
    last_fetch_times: dict[str, datetime] = {}
    cycle_count = 0

    while True:
        try:
            cycle_count += 1
            current_time_utc = datetime.now(timezone.utc)
            # logger.info(f"🔄 BACKGROUND TASK: Cycle #{cycle_count} started at {current_time_utc}")

            for resolution in timeframe_config.supported_resolutions:
                time_boundary = current_time_utc.replace(second=0, microsecond=0)
                if resolution == "1m":
                    time_boundary = time_boundary.replace(minute=(time_boundary.minute // 1) * 1)  # Ensure 1m aligns
                elif resolution == "5m":
                    time_boundary = time_boundary.replace(minute=(time_boundary.minute // 5) * 5)
                elif resolution == "1h":
                    time_boundary = time_boundary.replace(minute=0)
                elif resolution == "1d":
                    time_boundary = time_boundary.replace(hour=0, minute=0)
                elif resolution == "1w":
                    time_boundary = time_boundary - timedelta(days=time_boundary.weekday())
                    time_boundary = time_boundary.replace(hour=0, minute=0)

                last_fetch = last_fetch_times.get(resolution)
                if last_fetch is None or current_time_utc >= (last_fetch + timedelta(seconds=get_timeframe_seconds(resolution))):
                    # logger.info(f"📊 FETCHING KLINES: {resolution} from {last_fetch or 'beginning'} up to {current_time_utc}")
                    symbols_processed = 0
                    total_klines_fetched = 0

                    for symbol_val in SUPPORTED_SYMBOLS:
                        if symbol_val == "BTCDOM":
                            continue  # BTCDOM fetched from CoinGecko, not Bybit

                        end_ts = int(current_time_utc.timestamp())
                        if last_fetch is None:
                            start_ts_map = {"1m": 2*3600, "5m": 24*3600, "1h": 7*24*3600, "1d": 30*24*3600, "1w": 90*24*3600}  # Added 1m
                            start_ts = end_ts - start_ts_map.get(resolution, 30*24*3600)
                        else:
                            start_ts = int(last_fetch.timestamp())

                        if start_ts < end_ts:
                            # logger.debug(f"📈 FETCHING: {resolution} klines for {symbol_val} from {datetime.fromtimestamp(start_ts, timezone.utc)} to {datetime.fromtimestamp(end_ts, timezone.utc)}")
                            klines = fetch_klines_from_bybit(symbol_val, resolution, start_ts, end_ts)
                            if klines:
                                await cache_klines(symbol_val, resolution, klines)
                                latest_kline = klines[-1]
                                total_klines_fetched += len(klines)
                                symbols_processed += 1

                                if latest_kline['time'] >= int(time_boundary.timestamp()):
                                    await publish_resolution_kline(symbol_val, resolution, latest_kline)
                                    # logger.info(f"📡 PUBLISHED: {resolution} kline for {symbol_val} at {datetime.fromtimestamp(latest_kline['time'], timezone.utc)} (close: {latest_kline['close']})")
                            else:
                                logger.warning(f"❌ NO KLINES: {symbol_val} {resolution} in range {start_ts} to {end_ts}")

                    # logger.info(f"✅ COMPLETED: {resolution} fetch cycle - processed {symbols_processed} symbols, fetched {total_klines_fetched} total klines")
                    last_fetch_times[resolution] = current_time_utc

            # 🔍 GAP DETECTION AND FILLING: Check for and fill data gaps
            logger.info("🔍 STARTING GAP DETECTION: Scanning for data gaps across all symbols and resolutions")

            # Prioritize 1-minute data gaps as they are most critical
            prioritized_resolutions = ["1m"] + [r for r in timeframe_config.supported_resolutions if r != "1m"]
            all_gaps = []

            for resolution in prioritized_resolutions:
                logger.info(f"🔍 Scanning {resolution} data for gaps...")

                # Define time range for gap detection (last 7 days to catch historical gaps)
                current_time_utc = datetime.now(timezone.utc)
                end_ts = int(current_time_utc.timestamp())
                start_ts = end_ts - (7 * 24 * 3600)  # Last 7 days

                for symbol_val in SUPPORTED_SYMBOLS:
                    if symbol_val == "BTCDOM":
                        continue  # BTCDOM data from CoinGecko, no gaps to fill from Bybit

                    try:
                        # Detect gaps in cached data
                        gaps = await detect_gaps_in_cached_data(symbol_val, resolution, start_ts, end_ts)
                        if gaps:
                            all_gaps.extend(gaps)
                            # logger.info(f"📊 Found {len(gaps)} gaps for {symbol_val} {resolution}")
                    except Exception as e:
                        logger.error(f"Error detecting gaps for {symbol_val} {resolution}: {e}")
                        continue

            # Fill all detected gaps
            if all_gaps:
                logger.info(f"🔧 FILLING {len(all_gaps)} DETECTED GAPS")
                await fill_data_gaps(all_gaps)
            else:
                logger.info("✅ No data gaps detected across all symbols and resolutions")

            # logger.info(f"😴 BACKGROUND TASK: Cycle #{cycle_count} kline fetching completed, sleeping for 60 seconds")
            await asyncio.sleep(60)

            # Also fetch and cache Open Interest data
            logger.info("📊 STARTING OPEN INTEREST: Data fetch cycle")
            oi_symbols_processed = 0
            oi_total_entries = 0

            for resolution in timeframe_config.supported_resolutions:
                current_time_utc = datetime.now(timezone.utc)
                end_ts = int(current_time_utc.timestamp())
                # Fetch OI for the last 24 hours to ensure recent data is available
                start_ts = end_ts - (24 * 3600)  # Fetch last 24 hours of OI

                for symbol_val in SUPPORTED_SYMBOLS:
                    if symbol_val == "BTCDOM":
                        continue  # BTCDOM is indices, no OI from Bybit

                    # logger.info(f"📈 FETCHING OI: {symbol_val} {resolution} from {datetime.fromtimestamp(start_ts, timezone.utc)} to {datetime.fromtimestamp(end_ts, timezone.utc)}")
                    oi_data = fetch_open_interest_from_bybit(symbol_val, resolution, start_ts, end_ts)
                    if oi_data:
                        await cache_open_interest(symbol_val, resolution, oi_data)
                        oi_symbols_processed += 1
                        oi_total_entries += len(oi_data)
                        # logger.info(f"💾 CACHED OI: {len(oi_data)} entries for {symbol_val} {resolution}")
                    else:
                        logger.warning(f"❌ NO OI DATA: {symbol_val} {resolution}")

            # logger.info(f"✅ OI COMPLETED: Processed {oi_symbols_processed} symbols, cached {oi_total_entries} total entries")
            # logger.info(f"🎉 BACKGROUND TASK: Cycle #{cycle_count} fully completed")

        except Exception as e:
            logger.error(f"💥 ERROR in fetch_and_publish_klines task cycle #{cycle_count}: {e}", exc_info=True)
            logger.error(f"🔄 RETRYING: Sleeping for 10 seconds before next cycle")
            await asyncio.sleep(10)

async def fetch_and_aggregate_trades():
    """Background task to fetch recent trades from multiple exchanges and aggregate into minute-level bars."""
    logger.info("🚀 STARTING BACKGROUND TASK: fetch_and_aggregate_trades")

    # Redis key for storing last fetch times
    last_fetch_times_key = "last_fetch_times:trade_aggregator"

    # Load persisted last fetch times from Redis
    redis_conn = await get_redis_connection()
    persisted_times_json = await redis_conn.get(last_fetch_times_key)

    if persisted_times_json:
        try:
            persisted_times = json.loads(persisted_times_json)
            last_fetch_times = {}
            for exchange_id, timestamp_str in persisted_times.items():
                last_fetch_times[exchange_id] = datetime.fromtimestamp(float(timestamp_str), timezone.utc)
            logger.info(f"📋 Restored last fetch times from Redis: {len(last_fetch_times)} exchanges")
        except Exception as e:
            logger.warning(f"Failed to load persisted fetch times: {e}, starting fresh")
            last_fetch_times = {}
    else:
        logger.info("📋 No persisted fetch times found, starting fresh")
        last_fetch_times = {}

    cycle_count = 0

    while True:
        try:
            cycle_count += 1
            current_time_utc = datetime.now(timezone.utc)
            logger.info(f"🔄 TRADE AGGREGATOR: Cycle #{cycle_count} started at {current_time_utc}")

            # Process each supported exchange
            total_exchanges_processed = 0
            total_symbols_processed = 0
            total_bars_aggregated = 0

            for exchange_id, exchange_config in SUPPORTED_EXCHANGES.items():
                exchange_name = exchange_config.get('name', exchange_id)
                symbol_mappings = exchange_config.get('symbols', {})

                # Skip exchanges with no symbols configured
                if not symbol_mappings:
                    continue

                total_exchanges_processed += 1
                symbols_in_exchange = 0

                logger.info(f"📊 PROCESSING {exchange_name} ({exchange_id})")

                # Get last fetch time for this exchange
                last_fetch = last_fetch_times.get(exchange_id)

                # Calculate time range for this fetch
                end_ts = int(current_time_utc.timestamp())
                if last_fetch is None:
                    # First time - fetch last 4 hours of trade data
                    start_ts = end_ts - (4 * 3600)
                else:
                    # Subsequent fetches - from last fetch time
                    start_ts = int(last_fetch.timestamp())

                # Only fetch if we have a valid time range
                if start_ts >= end_ts:
                    logger.debug(f"⚠️ Skipping {exchange_id}: invalid time range {start_ts} to {end_ts}")
                    continue

                # Process each symbol supported by this exchange
                for internal_symbol, exchange_symbol in symbol_mappings.items():
                    # Only process symbols that are in our SUPPORTED_SYMBOLS list
                    if internal_symbol not in SUPPORTED_SYMBOLS:
                        continue

                    symbols_in_exchange += 1

                    try:
                        start_dt = datetime.fromtimestamp(start_ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
                        end_dt = datetime.fromtimestamp(end_ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
                        logger.debug(f"📈 FETCHING TRADES: {internal_symbol} ({exchange_symbol}) on {exchange_name} from {start_dt} to {end_dt}")

                        # Fetch recent trades from this exchange
                        trade_bars = await fetch_trades_from_ccxt(exchange_id, internal_symbol, start_ts, end_ts)

                        if trade_bars:
                            # Cache the aggregated trade bars
                            await cache_trades(internal_symbol, exchange_id, trade_bars)

                            # Publish latest bar if it's recent enough (within last 2 minutes)
                            current_ts = int(current_time_utc.timestamp())
                            for bar in trade_bars:
                                if current_ts - bar['time'] <= 120:  # Within last 2 minutes
                                    await publish_trade_bar(internal_symbol, exchange_id, bar)
                                    total_bars_aggregated += 1
                                    # logger.debug(f"📡 PUBLISHED trade bar for {internal_symbol} on {exchange_id} at {bar['time']}")

                            logger.debug(f"✅ CACHED {len(trade_bars)} trade bars for {internal_symbol} on {exchange_name}")
                        else:
                            logger.debug(f"⚠️ No trade bars received for {internal_symbol} on {exchange_name}")

                    except Exception as e:
                        logger.error(f"❌ Error processing {internal_symbol} on {exchange_id}: {e}")
                        continue

                total_symbols_processed += symbols_in_exchange
                # logger.info(f"📊 COMPLETED {exchange_name}: processed {symbols_in_exchange} symbols")

            # Gap detection and filling for trade data
            logger.info("🔍 STARTING TRADE DATA GAP DETECTION: Scanning for gaps across all exchanges and symbols")

            all_trade_gaps = []
            current_time_utc = datetime.now(timezone.utc)
            end_ts = int(current_time_utc.timestamp())
            # Check for gaps in the last 24 hours
            start_ts = end_ts - (24 * 3600)

            for exchange_id, exchange_config in SUPPORTED_EXCHANGES.items():
                symbol_mappings = exchange_config.get('symbols', {})

                for internal_symbol in symbol_mappings.keys():
                    if internal_symbol not in SUPPORTED_SYMBOLS:
                        continue

                    try:
                        # Detect gaps in cached trade data
                        gaps = await detect_gaps_in_trade_data(internal_symbol, exchange_id, start_ts, end_ts)
                        if gaps:
                            all_trade_gaps.extend(gaps)
                            logger.debug(f"📊 Found {len(gaps)} trade gaps for {internal_symbol} on {exchange_id}")
                    except Exception as e:
                        logger.error(f"Error detecting trade gaps for {exchange_id}:{internal_symbol}: {e}")
                        continue

            # Fill all detected trade data gaps
            if all_trade_gaps:
                logger.info(f"🔧 FILLING {len(all_trade_gaps)} TRADE DATA GAPS")
                await fill_trade_data_gaps(all_trade_gaps)
            else:
                logger.info("✅ No trade data gaps detected across all exchanges and symbols")

            # Update last fetch time for each exchange and persist to Redis
            updated_times = {}
            for exchange_id in SUPPORTED_EXCHANGES.keys():
                last_fetch_times[exchange_id] = current_time_utc
                updated_times[exchange_id] = str(current_time_utc.timestamp())

            # Persist the updated fetch times to Redis
            try:
                await redis_conn.set(last_fetch_times_key, json.dumps(updated_times))
                logger.debug(f"💾 Persisted last fetch times to Redis: {len(updated_times)} exchanges")
            except Exception as e:
                logger.warning(f"Failed to persist last fetch times to Redis: {e}")

            logger.info(f"✅ TRADE AGGREGATOR COMPLETED: Cycle #{cycle_count} - processed {total_exchanges_processed} exchanges, {total_symbols_processed} symbols, aggregated {total_bars_aggregated} recent bars")
            logger.info("😴 TRADE AGGREGATOR: Sleeping for 60 seconds")

            await asyncio.sleep(60)

        except Exception as e:
            logger.error(f"💥 ERROR in fetch_and_aggregate_trades task cycle #{cycle_count}: {e}", exc_info=True)
            logger.error("🔄 RETRYING: Sleeping for 10 seconds before next cycle")
            await asyncio.sleep(10)

async def bybit_realtime_feed_listener():
    logger.info("Starting Bybit real-time feed listener task (conceptual - for shared WS to Redis)")
    # This is a placeholder for a shared WebSocket connection that publishes to Redis.
    # The /stream/live/{symbol} endpoint now creates a direct Bybit WS per client.
    # If you want this listener to feed Redis for the old SSE endpoint, implement it here.
    while True:
        await asyncio.sleep(300)
        logger.debug("bybit_realtime_feed_listener (shared conceptual) placeholder is alive")

def get_timeframe_seconds(timeframe: str) -> int:
    multipliers = {"1m": 60, "5m": 300, "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800}
    return multipliers.get(timeframe, 3600)
