# Chart-related API endpoints

import json
from datetime import datetime, timezone
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from config import SUPPORTED_SYMBOLS, SUPPORTED_RESOLUTIONS, timeframe_config
from redis_utils import get_cached_klines, cache_klines, fetch_klines_from_bybit
from logging_config import logger

async def history_endpoint(symbol: str, resolution: str, from_ts: int, to_ts: int):
    try:
        logger.info(f"/history request: symbol={symbol}, resolution={resolution}, from_ts={from_ts}, to_ts={to_ts}")
        # await get_redis_connection()

        if symbol not in SUPPORTED_SYMBOLS:
            return JSONResponse({"s": "error", "errmsg": f"Unsupported symbol: {symbol}"}, status_code=400)

        # Special resolution check for BTCDOM
        if symbol == "BTCDOM":
            if resolution != "1d":
                return JSONResponse({"s": "error", "errmsg": f"Unsupported resolution for BTCDOM: {resolution}. Only 1d is supported."}, status_code=400)
        else:
            if resolution not in timeframe_config.supported_resolutions:
                return JSONResponse({"s": "error", "errmsg": f"Unsupported resolution: {resolution}"}, status_code=400)

        current_time_sec = int(datetime.now(timezone.utc).timestamp())
        from_ts = max(0, from_ts)
        to_ts = max(0, min(to_ts, current_time_sec))
        if from_ts > to_ts:
            logger.warning(f"Adjusted time range invalid: from_ts={from_ts}, to_ts={to_ts}. Returning no data.")
            return JSONResponse({"s": "no_data", "t": [], "o": [], "h": [], "l": [], "c": [], "v": []})

        # Log from_ts and to_ts in human-readable format
        from_dt_str = datetime.fromtimestamp(from_ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        to_dt_str = datetime.fromtimestamp(to_ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        logger.info(f"Time range: from_ts={from_ts} ({from_dt_str}), to_ts={to_ts} ({to_dt_str})")

        logger.info(f"Fetching cached klines for PAXGUSDT with from_ts: {from_ts} and to_ts: {to_ts}")

        # Handle special symbol BTCDOM from CoinGecko
        if symbol == "BTCDOM":
            from redis_utils import fetch_btc_dominance
            klines = await get_cached_klines(symbol, resolution, from_ts, to_ts)

            should_fetch_from_coingecko = False
            if not klines:
                should_fetch_from_coingecko = True
                logger.info("No cached klines found for BTCDOM. Fetching from CoinGecko.")
            else:
                cached_start_ts = klines[0]['time']
                cached_end_ts = klines[-1]['time']
                if cached_start_ts > from_ts or cached_end_ts < to_ts:
                    should_fetch_from_coingecko = True
                    logger.info(f"Cache does not fully cover requested range. Requested: {from_ts}-{to_ts}, Cached: {cached_start_ts}-{cached_end_ts}. Will fetch from CoinGecko to fill gaps.")

            if should_fetch_from_coingecko:
                logger.info(f"Attempting to fetch BTC Dominance for {symbol} {resolution} range {from_ts} to {to_ts}")
                coingecko_klines = await fetch_btc_dominance(symbol, resolution, from_ts, to_ts)
                if coingecko_klines:
                    logger.info(f"Fetched {len(coingecko_klines)} klines from CoinGecko. Caching them.")
                    await cache_klines(symbol, resolution, coingecko_klines)
                    # Re-query cache to get a consolidated, sorted list from the precise range
                    klines = await get_cached_klines(symbol, resolution, from_ts, to_ts)
                elif not klines:
                    logger.info("No data available from CoinGecko and cache is empty for this range.")
                    return JSONResponse({"s": "no_data", "t": [], "o": [], "h": [], "l": [], "c": [], "v": []})
        else:
            # Regular symbol handling from Bybit
            klines = await get_cached_klines(symbol, resolution, from_ts, to_ts)

            should_fetch_from_bybit = False
            if not klines:
                should_fetch_from_bybit = True
                logger.info("No cached klines found. Fetching from Bybit.")
            else:
                cached_start_ts = klines[0]['time']
                cached_end_ts = klines[-1]['time']
                if cached_start_ts > from_ts or cached_end_ts < to_ts:  # Check if cache covers the full requested range
                    should_fetch_from_bybit = True
                    logger.info(f"Cache does not fully cover requested range. Requested: {from_ts}-{to_ts}, Cached: {cached_start_ts}-{cached_end_ts}. Will fetch from Bybit to fill gaps.")

            kline_fetch_start_ts = from_ts  # default values
            kline_fetch_end_ts = to_ts

            logger.info(f"Before Bybit Fetch - From_TS: {from_ts} ({datetime.fromtimestamp(from_ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}), To_TS: {to_ts} ({datetime.fromtimestamp(to_ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')})")
            logger.info(f"Before Bybit Fetch - Clamped from_ts: {kline_fetch_start_ts} ({datetime.fromtimestamp(kline_fetch_start_ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}), to_ts: {kline_fetch_end_ts} ({datetime.fromtimestamp(kline_fetch_end_ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')})")
            logger.info(f"After Lookback Calc - Effective kline fetch range for Bybit: {kline_fetch_start_ts} to {kline_fetch_end_ts}")

            if should_fetch_from_bybit:
                logger.info(f"KLINES: Attempting to fetch from Bybit for PAXGUSDT with from_ts: {from_ts} and to_ts: {to_ts}")
                logger.info(f"Attempting to fetch from Bybit for {symbol} {resolution} range {from_ts} to {to_ts}")
                bybit_klines = fetch_klines_from_bybit(symbol, resolution, from_ts, to_ts)
                if bybit_klines:
                    logger.info(f"Fetched {len(bybit_klines)} klines from Bybit. Caching them.")
                    await cache_klines(symbol, resolution, bybit_klines)
                    # Re-query cache to get a consolidated, sorted list from the precise range
                    klines = await get_cached_klines(symbol, resolution, from_ts, to_ts)
                elif not klines:
                    logger.info(f"BYBIT: No data available from Bybit and cache is empty for this range.")
                    logger.info("No data available from Bybit and cache is empty for this range.")

                    return JSONResponse({"s": "no_data", "t": [], "o": [], "h": [], "l": [], "c": [], "v": []})

        # Final filter and sort, in case cache operations or Bybit fetches returned slightly outside the exact ts range
        klines = [k for k in klines if from_ts <= k['time'] <= to_ts]
        klines.sort(key=lambda x: x['time'])

        # De-duplicate klines: if multiple entries exist for the same timestamp, keep the last one.
        if klines:
            logger.debug(f"Klines before de-duplication for {symbol} {resolution}: {len(klines)} entries.")
            temp_klines_by_ts = {}
            for k_item in klines:  # klines is already sorted by time
                temp_klines_by_ts[k_item['time']] = k_item  # This overwrites, keeping the last seen for a timestamp

            # Convert back to a list and sort by time again to ensure order
            klines = sorted(list(temp_klines_by_ts.values()), key=lambda x: x['time'])
            logger.debug(f"Klines after de-duplication for {symbol} {resolution}: {len(klines)} entries.")

        if not klines:
            logger.info(f"No klines found for {symbol} {resolution} in range {from_ts}-{to_ts} after all checks.")
            return JSONResponse({"s": "no_data", "t": [], "o": [], "h": [], "l": [], "c": [], "v": []})

        response_data = {
            "s": "ok",
            "t": [k["time"] for k in klines], "o": [k["open"] for k in klines],
            "h": [k["high"] for k in klines], "l": [k["low"] for k in klines],
            "c": [k["close"] for k in klines], "v": [k["vol"] for k in klines]
        }

        # Log requested vs. actual timestamp range
        log_msg_parts = [f"Returning {len(klines)} klines for /history request."]
        log_msg_parts.append(f"Requested range: from_ts={from_ts} ({datetime.fromtimestamp(from_ts, timezone.utc)} UTC) to to_ts={to_ts} ({datetime.fromtimestamp(to_ts, timezone.utc)} UTC).")
        if klines:
            actual_min_ts = min(response_data["t"])
            logger.info(f"BYBIT: Fetch Completed with data returned from ({actual_min_ts}) and higher")
            actual_max_ts = max(response_data["t"])
            log_msg_parts.append(f"Actual data range: min_ts={actual_min_ts} ({datetime.fromtimestamp(actual_min_ts, timezone.utc)} UTC) to max_ts={actual_max_ts} ({datetime.fromtimestamp(actual_max_ts, timezone.utc)} UTC).")
        else:
            log_msg_parts.append("Actual data range: No klines returned.")
        logger.info(" ".join(log_msg_parts))
        return JSONResponse(response_data)
    except Exception as e:
        logger.error(f"Error in /history endpoint: {e}", exc_info=True)
        return JSONResponse({"s": "error", "errmsg": str(e)}, status_code=500)

async def initial_chart_config():
    """Returns initial configuration for chart dropdowns."""
    return JSONResponse({
        "symbols": SUPPORTED_SYMBOLS,
        "resolutions": SUPPORTED_RESOLUTIONS,
        "ranges": [
            {"value": "1h", "label": "1h"},
            {"value": "8h", "label": "8h"},
            {"value": "24h", "label": "24h"},
            {"value": "3d", "label": "3d"},
            {"value": "7d", "label": "7d"},
            {"value": "30d", "label": "30d"},
            {"value": "3m", "label": "3M"},  # Approximately 3 * 30 days
            {"value": "6m", "label": "6M"},  # Approximately 6 * 30 days
            {"value": "1y", "label": "1Y"},  # Approximately 365 days
            {"value": "3y", "label": "3Y"},  # Approximately 3 * 365 days
        ]
    })

async def symbols_endpoint(symbol: str):
    if symbol not in SUPPORTED_SYMBOLS:
        return JSONResponse({"s": "error", "errmsg": "Symbol not supported"}, status_code=404)

    # Special handling for BTCDOM
    if symbol == "BTCDOM":
        return JSONResponse({
            "name": symbol, "ticker": symbol, "description": "Bitcoin Dominance",
            "type": "indices", "exchange": "CoinGecko", "session": "24x7", "timezone": "UTC",
            "minmovement": 1, "pricescale": 10000, "has_intraday": False,  # No intraday for dominance
            "supported_resolutions": ["1d"],  # Only daily
            "volume_precision": 2
        })

    return JSONResponse({
        "name": symbol, "ticker": symbol, "description": f"{symbol} Perpetual",
        "type": "crypto", "exchange": "Bybit", "session": "24x7", "timezone": "UTC",
        "minmovement": 1, "pricescale": 100, "has_intraday": True,
        "supported_resolutions": list(timeframe_config.supported_resolutions),
        "volume_precision": 2
    })

async def config_endpoint():
    return JSONResponse({
        "supported_resolutions": list(timeframe_config.supported_resolutions),
        "supports_search": False, "supports_group_request": False,
        "supports_marks": False, "supports_timescale_marks": False
    })

async def symbols_list_endpoint():
    return JSONResponse(list(SUPPORTED_SYMBOLS))
