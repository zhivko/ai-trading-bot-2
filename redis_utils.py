# Redis utilities and connection management

import json
from typing import Optional, Dict, Any, List
from redis.asyncio import Redis as AsyncRedis
from redis import Redis as SyncRedis
from config import (
    REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD, REDIS_TIMEOUT,
    REDIS_RETRY_COUNT, REDIS_RETRY_DELAY
)
from logging_config import logger

from config import KlineData, timeframe_config, session, get_timeframe_seconds
from datetime import datetime, timezone

# Global Redis client instances
redis_client: Optional[AsyncRedis] = None
sync_redis_client = None  # Synchronous Redis client for use in threads

async def init_redis():
    """Initialize Redis connections (both async and sync)."""
    global redis_client, sync_redis_client
    try:
        # Initialize async Redis client
        redis_client = AsyncRedis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            decode_responses=True,
            socket_timeout=REDIS_TIMEOUT,
            retry_on_timeout=True  # Enable retrying on socket timeouts
        )
        await redis_client.ping()
        logger.info("Successfully connected to Redis (async)")

        # Initialize sync Redis client
        sync_redis_client = SyncRedis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            decode_responses=True,
            socket_timeout=REDIS_TIMEOUT,
            retry_on_timeout=True
        )
        sync_redis_client.ping()
        logger.info("Successfully connected to Redis (sync)")

        return redis_client
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        logger.error("Run this to start it on wsl2: cmd /c wsl --exec sudo service redis-server start && Exit /B 5")
        redis_client = None
        sync_redis_client = None
        raise

async def get_redis_connection() -> AsyncRedis:
    """Get a Redis connection."""
    global redis_client
    if redis_client is None:
        try:
            redis_client = await init_redis()
        except Exception:
            logger.critical("CRITICAL: Redis connection could not be established in get_redis_connection.")
            logger.critical("Run this to start it on wsl2: cmd /c wsl --exec d && Exit /B 5")
            raise
    if redis_client is None:
        raise Exception("Redis client is None after attempting initialization.")
    return redis_client

def init_sync_redis():
    """Initialize synchronous Redis connection for use in threads."""
    global sync_redis_client
    try:
        sync_redis_client = SyncRedis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            decode_responses=True,
            socket_timeout=REDIS_TIMEOUT,
            retry_on_timeout=True
        )
        sync_redis_client.ping()
        logger.info("Successfully connected to Redis (sync)")
        return sync_redis_client
    except Exception as e:
        logger.error(f"Failed to connect to Redis (sync): {e}")
        sync_redis_client = None
        raise

def get_sync_redis_connection() -> SyncRedis:
    """Get a synchronous Redis connection for use in threads."""
    global sync_redis_client
    if sync_redis_client is None:
        try:
            sync_redis_client = init_sync_redis()
        except Exception:
            logger.critical("CRITICAL: Redis sync connection could not be established.")
            raise
    if sync_redis_client is None:
        raise Exception("Redis sync client is None after attempting initialization.")
    return sync_redis_client

def get_redis_key(symbol: str, resolution: str, timestamp: int) -> str:
    from config import TRADING_TIMEFRAME
    multipliers = {"1m": 60, "5m": 300, "1h": 3600, "1d": 86400, "1w": 604800}
    timeframe_seconds = multipliers.get(resolution, 3600)
    aligned_ts = (timestamp // timeframe_seconds) * timeframe_seconds
    return f"kline:{symbol}:{resolution}:{aligned_ts}"

def get_sorted_set_key(symbol: str, resolution: str) -> str:
    return f"zset:kline:{symbol}:{resolution}"

def get_stream_key(symbol: str, resolution: str) -> str:
    return f"stream:kline:{symbol}:{resolution}"

def get_sorted_set_oi_key(symbol: str, resolution: str) -> str:
    return f"zset:open_interest:{symbol}:{resolution}"

def get_drawings_redis_key(symbol: str, request=None, email=None) -> str:
    if email:
        return f"drawings:{email}:{symbol}"
    elif request:
        from auth import get_session
        email = request.session.get("email")
        return f"drawings:{email}:{symbol}"
    else:
        # Fallback for cases where neither request nor email is provided
        return f"drawings:anonymous:{symbol}"

async def get_oldest_cached_timestamp(symbol: str, resolution: str) -> Optional[int]:
    try:
        redis = await get_redis_connection()
        pattern = f"kline:{symbol}:{resolution}:*"
        timestamps = []
        async for key in redis.scan_iter(match=pattern):
            parts = key.split(":")
            if len(parts) == 4:
                try:
                    timestamps.append(int(parts[3]))
                except ValueError:
                    continue
        return min(timestamps) if timestamps else None
    except Exception as e:
        logger.error(f"Error finding oldest cached timestamp: {e}")
        return None

async def get_cached_klines(symbol: str, resolution: str, start_ts: int, end_ts: int) -> list[Dict[str, Any]]:
    from config import KlineData
    try:
        redis = await get_redis_connection()
        sorted_set_key = get_sorted_set_key(symbol, resolution)
        logger.info(f"Querying sorted set '{sorted_set_key}' for range [{start_ts}, {end_ts}]")

        # TIMESTAMP DEBUG: Analyze query timestamps
        logger.info(f"[TIMESTAMP DEBUG] redis_utils.py - get_cached_klines query:")
        logger.info(f"  start_ts: {start_ts} (type: {type(start_ts)})")
        logger.info(f"  end_ts: {end_ts} (type: {type(end_ts)})")

        if start_ts and end_ts:
            if start_ts > 1e10:  # Likely milliseconds
                logger.warning(f"[TIMESTAMP DEBUG] start_ts {start_ts} appears to be in MILLISECONDS (should be seconds for Redis)")
                logger.info(f"  Converting to seconds: {start_ts // 1000}")
            elif start_ts > 1e8:  # Likely seconds
                logger.info(f"[TIMESTAMP DEBUG] start_ts {start_ts} appears to be in SECONDS (correct for Redis)")
            else:
                logger.warning(f"[TIMESTAMP DEBUG] start_ts {start_ts} appears to be invalid")

        # Check Redis data sample
        logger.info(f"[TIMESTAMP DEBUG] Checking Redis data sample for comparison...")

        klines_data_redis = await redis.zrangebyscore(
            sorted_set_key,
            min=start_ts,
            max=end_ts,
            withscores=False
        )
        if not klines_data_redis:
            logger.warning(f"No data returned from zrangebyscore for key '{sorted_set_key}' with range [{start_ts}, {end_ts}]. Checking if key exists and has members...")
            key_exists = await redis.exists(sorted_set_key)
            cardinality = await redis.zcard(sorted_set_key) if key_exists else 0
            logger.info(f"Key '{sorted_set_key}': Exists? {key_exists}, Cardinality: {cardinality}")
            if key_exists and cardinality > 0:
                logger.info(f"Fetching all members from '{sorted_set_key}' to inspect scores, as zrangebyscore returned empty for range [{start_ts}, {end_ts}].")
                all_members_with_scores = await redis.zrange(sorted_set_key, 0, -1, withscores=True)
                if all_members_with_scores:
                    logger.info("All members in '{sorted_set_key}' (first 5 shown if many):")
                    for i, (member, score) in enumerate(all_members_with_scores[:5]):
                        logger.info(f"  Member: {str(member)[:100]}..., Score: {score} (datetime: {datetime.fromtimestamp(int(score), timezone.utc) if isinstance(score, (int, float)) else 'N/A'})")
                    if len(all_members_with_scores) > 5: logger.info(f"  ... and {len(all_members_with_scores) - 5} more members.")
                else:
                    logger.warning(f"'{sorted_set_key}' exists with cardinality {cardinality}, but zrange returned no members. This is unexpected.")
        cached_data = []
        for data_item in klines_data_redis:
            try:
                if isinstance(data_item, bytes):
                    data_str = data_item.decode('utf-8')
                elif isinstance(data_item, str):
                    data_str = data_item
                else:
                    logger.error(f"Unexpected data type in Redis: {type(data_item)}. Skipping.")
                    continue
                parsed_data = json.loads(data_str)
                cached_data.append(parsed_data)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON: {e}. Raw data: {data_item}")
                continue

        logger.info(f"Found {len(cached_data)} cached klines for {symbol} {resolution} between {start_ts} and {end_ts}")

        # DATA GAP ANALYSIS: Check for gaps in the data
        if cached_data:
            logger.info(f"🔍 DATA GAP ANALYSIS for {symbol} {resolution}:")
            logger.info(f"  Expected data points based on time range: ~{int((end_ts - start_ts) / get_timeframe_seconds(resolution))}")
            logger.info(f"  Actual data points retrieved: {len(cached_data)}")

            # Check for timestamp gaps
            timestamps = [item['time'] for item in cached_data]
            timestamps.sort()

            expected_interval = get_timeframe_seconds(resolution)
            gaps = []
            consecutive_missing = 0

            for i in range(1, len(timestamps)):
                gap = timestamps[i] - timestamps[i-1]
                if gap > expected_interval:
                    missing_points = int(gap / expected_interval) - 1
                    gaps.append({
                        'from': timestamps[i-1],
                        'to': timestamps[i],
                        'gap_seconds': gap,
                        'missing_points': missing_points
                    })
                    consecutive_missing += missing_points

            if gaps:
                logger.warning(f"🚨 DATA GAPS DETECTED: {len(gaps)} gaps found, {consecutive_missing} total missing data points")
                for gap in gaps[:5]:  # Show first 5 gaps
                    logger.warning(f"  Gap: {datetime.fromtimestamp(gap['from'], timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} to {datetime.fromtimestamp(gap['to'], timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} ({gap['missing_points']} missing points)")
                if len(gaps) > 5:
                    logger.warning(f"  ... and {len(gaps) - 5} more gaps")
            else:
                logger.info(f"✅ No data gaps detected - data appears continuous")

            # Check data quality
            null_values = sum(1 for item in cached_data if not all(item.get(field) for field in ['time', 'open', 'high', 'low', 'close', 'vol']))
            if null_values > 0:
                logger.warning(f"🚨 DATA QUALITY ISSUE: {null_values} records have null/empty OHLC values")

        return cached_data
    except Exception as e:
        logger.error(f"Error in get_cached_klines: {e}", exc_info=True)
        return []

async def cache_klines(symbol: str, resolution: str, klines: list[Dict[str, Any]]) -> None:
    from config import KlineData
    try:
        redis = await get_redis_connection()
        expiration = {
            "1m": 60 * 60 * 2,    # Shorter cache for 1m
            "5m": 60 * 60 * 24,
            "1h": 60 * 60 * 24 * 7,
            "1d": 60 * 60 * 24 * 30,
            "1w": 60 * 60 * 24 * 90
        }

        # De-duplicate the input klines list: for each timestamp, keep only the last encountered kline object.
        # This ensures that if the input `klines` list itself has multiple variations for the same timestamp,
        # we only consider one (the last one) for caching.
        unique_klines_for_caching: Dict[int, Dict[str, Any]] = {}
        for k in klines:
            unique_klines_for_caching[k['time']] = k

        # Now, get the list of unique kline objects to process.
        # Sorting by time is good practice, though the Redis operations for each timestamp are independent.
        klines_to_process = sorted(list(unique_klines_for_caching.values()), key=lambda x: x['time'])

        pipeline_batch_size = 500  # Execute pipeline every N klines
        sorted_set_key = get_sorted_set_key(symbol, resolution)
        async with redis.pipeline() as pipe:
            for kline in klines_to_process:
                timestamp = kline["time"]
                data_str = json.dumps(kline)

                # Update/set the individual kline key (e.g., kline:BTCUSDT:5m:1234567890)
                # This key stores the JSON string for a single kline at its exact timestamp.
                individual_key = get_redis_key(symbol, resolution, timestamp)
                await pipe.setex(individual_key, expiration.get(resolution, 60 * 60 * 24), data_str)

                # For the sorted set (e.g., zset:kline:BTCUSDT:5m), ensure uniqueness per timestamp score.
                # 1. Remove any existing members that have this exact timestamp as their score.
                await pipe.zremrangebyscore(sorted_set_key, timestamp, timestamp)
                # 2. Add the current (and now unique for this timestamp) kline data.
                await pipe.zadd(sorted_set_key, {data_str: timestamp})

                # Execute in batches
                if len(pipe) >= pipeline_batch_size * 3:  # Each kline adds 3 commands (setex, zremrangebyscore, zadd)
                    await pipe.execute()
            await pipe.execute()  # Execute any remaining commands in the pipeline

        # Trim the sorted set to keep a manageable number of recent klines.
        max_sorted_set_entries = 5000  # Adjust as needed based on typical query ranges and resolutions
        await redis.zremrangebyrank(sorted_set_key, 0, -(max_sorted_set_entries + 1))
        #logger.info(f"Successfully cached {len(klines_to_process)} unique klines for {symbol} {resolution}")
    except Exception as e:
        logger.error(f"Error caching data: {e}", exc_info=True)

async def get_cached_open_interest(symbol: str, resolution: str, start_ts: int, end_ts: int) -> list[Dict[str, Any]]:
    try:
        redis = await get_redis_connection()
        sorted_set_key = get_sorted_set_oi_key(symbol, resolution)
        oi_data_redis = await redis.zrangebyscore(sorted_set_key, min=start_ts, max=end_ts, withscores=False)
        cached_data = [json.loads(item) for item in oi_data_redis]
        logger.info(f"Found {len(cached_data)} cached Open Interest entries for {symbol} {resolution} between {start_ts} and {end_ts}")
        return cached_data
    except Exception as e:
        logger.error(f"Error in get_cached_open_interest: {e}", exc_info=True)
        return []

async def cache_open_interest(symbol: str, resolution: str, oi_data: list[Dict[str, Any]]) -> None:
    try:
        redis = await get_redis_connection()
        sorted_set_key = get_sorted_set_oi_key(symbol, resolution)
        async with redis.pipeline() as pipe:
            for oi_entry in oi_data:
                timestamp = oi_entry["time"]
                data_str = json.dumps(oi_entry)
                await pipe.zadd(sorted_set_key, {data_str: timestamp})
            await pipe.execute()
        # Trim the sorted set to keep a manageable number of recent entries.
        max_sorted_set_entries = 5000  # Same as klines
        await redis.zremrangebyrank(sorted_set_key, 0, -(max_sorted_set_entries + 1))
        #logger.info(f"Successfully cached {len(oi_data)} Open Interest entries for {symbol} {resolution}")
    except Exception as e:
        logger.error(f"Error caching Open Interest data: {e}", exc_info=True)

async def publish_resolution_kline(symbol: str, resolution: str, kline_data: dict) -> None:
    try:
        redis = await get_redis_connection()
        stream_key = get_stream_key(symbol, resolution)
        sorted_set_key = get_sorted_set_key(symbol, resolution)
        kline_json_str = json.dumps(kline_data)

        await redis.xadd(stream_key, {"data": kline_json_str}, maxlen=1000)
        await redis.zadd(sorted_set_key, {kline_json_str: kline_data["time"]})
        await redis.zremrangebyrank(sorted_set_key, 0, -1001)
    except Exception as e:
        logger.error(f"Error publishing resolution kline to Redis: {e}", exc_info=True)

async def publish_live_data_tick(symbol: str, live_data: dict) -> None:
    try:
        redis = await get_redis_connection()
        live_stream_key = f"live:tick:{symbol}"
        await redis.xadd(live_stream_key, {"data": json.dumps(live_data)}, maxlen=2000)
    except Exception as e:
        logger.error(f"Error publishing live tick data to Redis: {e}", exc_info=True)

def fetch_klines_from_bybit(symbol: str, resolution: str, start_ts: int, end_ts: int) -> list[Dict[str, Any]]:
    """Fetches klines from Bybit API."""

    #logger.info(f"Fetching klines for {symbol} {resolution} from {datetime.fromtimestamp(start_ts, timezone.utc)} to {datetime.fromtimestamp(end_ts, timezone.utc)}")
    all_klines: list[KlineData] = []
    current_start = start_ts
    timeframe_seconds = get_timeframe_seconds(resolution)
    batch_count = 0
    total_bars_received = 0

    while current_start < end_ts:
        batch_count += 1
        batch_end = min(current_start + (1000 * timeframe_seconds) -1 , end_ts)
        logger.debug(f"Fetching batch #{batch_count} for {symbol} {resolution}: {datetime.fromtimestamp(current_start, timezone.utc)} to {datetime.fromtimestamp(batch_end, timezone.utc)}")

        try:
            response = session.get_kline(
                category="linear", symbol=symbol,
                interval=timeframe_config.resolution_map[resolution],
                start=current_start * 1000, end=batch_end * 1000, limit=1000
            )
        except Exception as e:
            logger.error(f"Bybit API request failed for {symbol} {resolution} batch #{batch_count}: {e}")
            break

        if response.get("retCode") != 0:
            logger.error(f"Bybit API error for {symbol} {resolution} batch #{batch_count}: {response.get('retMsg', 'Unknown error')} (retCode: {response.get('retCode')})")
            break

        bars = response.get("result", {}).get("list", [])
        if not bars:
            logger.info(f"No more data available from Bybit for {symbol} {resolution} at batch #{batch_count}")
            break

        logger.debug(f"Received {len(bars)} bars from Bybit for {symbol} {resolution} batch #{batch_count}")
        total_bars_received += len(bars)

        batch_klines = [format_kline_data(bar) for bar in reversed(bars)]
        all_klines.extend(batch_klines)

        if not batch_klines:
            logger.warning(f"Batch klines became empty after formatting for {symbol} {resolution} batch #{batch_count}, stopping fetch")
            break

        last_fetched_ts = batch_klines[-1]["time"]
        logger.debug(f"Processed batch #{batch_count} for {symbol} {resolution}: {len(batch_klines)} klines, last timestamp: {datetime.fromtimestamp(last_fetched_ts, timezone.utc)}")

        if len(bars) < 1000 or last_fetched_ts >= batch_end:
            logger.debug(f"Stopping batch fetch for {symbol} {resolution}: received {len(bars)} bars (less than 1000) or reached batch end")
            break
        current_start = last_fetched_ts + timeframe_seconds

    all_klines.sort(key=lambda x: x["time"])
    #logger.info(f"Completed Bybit fetch for {symbol} {resolution}: {batch_count} batches, {total_bars_received} total bars received, {len(all_klines)} klines processed")
    return all_klines

def format_kline_data(bar: list[Any]) -> Dict[str, Any]:
    """Formats raw Bybit kline data into standardized format."""
    return {
        "time": int(bar[0]) // 1000,
        "open": float(bar[1]),
        "high": float(bar[2]),
        "low": float(bar[3]),
        "close": float(bar[4]),
        "vol": float(bar[5])
    }