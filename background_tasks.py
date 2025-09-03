# Background tasks for data fetching and processing

import asyncio
from datetime import datetime, timezone, timedelta
from config import SUPPORTED_SYMBOLS, timeframe_config, TRADING_SYMBOL, TRADING_TIMEFRAME
from redis_utils import (
    get_cached_klines, cache_klines, get_cached_open_interest,
    cache_open_interest, publish_resolution_kline
)
from redis_utils import fetch_klines_from_bybit
from indicators import fetch_open_interest_from_bybit
from logging_config import logger

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
                        end_ts = int(current_time_utc.timestamp())
                        if last_fetch is None:
                            start_ts_map = {"1m": 2*3600, "5m": 24*3600, "1h": 7*24*3600, "1d": 30*24*3600, "1w": 90*24*3600}  # Added 1m
                            start_ts = end_ts - start_ts_map.get(resolution, 30*24*3600)
                        else:
                            start_ts = int(last_fetch.timestamp())

                        if start_ts < end_ts:
                            logger.debug(f"📈 FETCHING: {resolution} klines for {symbol_val} from {datetime.fromtimestamp(start_ts, timezone.utc)} to {datetime.fromtimestamp(end_ts, timezone.utc)}")
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

async def bybit_realtime_feed_listener():
    logger.info("Starting Bybit real-time feed listener task (conceptual - for shared WS to Redis)")
    # This is a placeholder for a shared WebSocket connection that publishes to Redis.
    # The /stream/live/{symbol} endpoint now creates a direct Bybit WS per client.
    # If you want this listener to feed Redis for the old SSE endpoint, implement it here.
    while True:
        await asyncio.sleep(300)
        logger.debug("bybit_realtime_feed_listener (shared conceptual) placeholder is alive")

def get_timeframe_seconds(timeframe: str) -> int:
    multipliers = {"1m": 60, "5m": 300, "1h": 3600, "1d": 86400, "1w": 604800}
    return multipliers.get(timeframe, 3600)