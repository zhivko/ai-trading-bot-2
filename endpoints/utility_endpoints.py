# Utility API endpoints

import json
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from config import SUPPORTED_SYMBOLS, DEFAULT_SYMBOL_SETTINGS, REDIS_LAST_SELECTED_SYMBOL_KEY
from redis_utils import get_redis_connection
from logging_config import logger

async def settings_endpoint(request: Request):
    from auth import require_authentication
    global DEFAULT_SYMBOL_SETTINGS
    redis = await get_redis_connection()

    # Require authentication for settings access
    require_authentication(request.session)

    email = request.session.get("email")
    if not email:
        return JSONResponse({"status": "error", "message": "User not authenticated"}, status_code=401)

    symbol = request.query_params.get("symbol")
    settings_key = f"settings:{email}:{symbol}"

    if request.method == 'GET':
        if not symbol:
            logger.warning("GET /settings: Symbol query parameter is missing.")
            return JSONResponse({"status": "error", "message": "Symbol query parameter is required"}, status_code=400)
        # settings_key is already set above

        try:
            settings_json = await redis.get(settings_key)
            if settings_json:
                symbol_settings = json.loads(settings_json)

                # Check for corrupted X-axis timestamps (dates before year 2000)
                if 'xAxisMin' in symbol_settings and 'xAxisMax' in symbol_settings:
                    x_axis_min = symbol_settings['xAxisMin']
                    x_axis_max = symbol_settings['xAxisMax']

                    # Convert to datetime for validation (handle both seconds and milliseconds)
                    import datetime
                    if x_axis_min is not None and x_axis_max is not None:
                        # Use 1e11 (100 billion) as threshold to distinguish seconds from milliseconds
                        # Unix timestamp in seconds (2025): ~1.7e9
                        # Unix timestamp in milliseconds (2025): ~1.7e12
                        if x_axis_min < 1e11:  # Less than 100 billion (reasonable for seconds since 1970)
                            min_timestamp = x_axis_min * 1000  # Convert seconds to milliseconds
                            max_timestamp = x_axis_max * 1000
                        else:
                            min_timestamp = x_axis_min
                            max_timestamp = x_axis_max

                        # Convert timestamps to seconds for datetime conversion
                        min_timestamp_seconds = min_timestamp / 1000
                        max_timestamp_seconds = max_timestamp / 1000

                        # Debug logging for timestamp conversion
                        logger.info(f"DEBUG: Timestamp conversion for {symbol}:")
                        logger.info(f"  Raw x_axis_min: {x_axis_min}, x_axis_max: {x_axis_max}")
                        logger.info(f"  Converted min_timestamp: {min_timestamp}, max_timestamp: {max_timestamp}")
                        logger.info(f"  Timestamp seconds: min={min_timestamp_seconds}, max={max_timestamp_seconds}")

                        data_was_fixed = False
                        try:
                            min_date = datetime.datetime.fromtimestamp(min_timestamp_seconds, tz=datetime.timezone.utc)
                            max_date = datetime.datetime.fromtimestamp(max_timestamp_seconds, tz=datetime.timezone.utc)
                            logger.info(f"  Final dates: min={min_date.isoformat()}, max={max_date.isoformat()}")
                        except (ValueError, OSError, OverflowError) as e:
                            logger.error(f"Failed to convert timestamps to datetime for {symbol}: {e}")
                            logger.error(f"  Problematic values: min_ts={min_timestamp_seconds}, max_ts={max_timestamp_seconds}")
                            logger.error(f"  Raw values: x_axis_min={x_axis_min}, x_axis_max={x_axis_max}")
                            logger.error(f"  Converted values: min_timestamp={min_timestamp}, max_timestamp={max_timestamp}")

                            # Reset to reasonable values: xAxisMax = NOW, xAxisMin = 30 days before NOW
                            now = datetime.datetime.now(datetime.timezone.utc)
                            thirty_days_ago = now - datetime.timedelta(days=30)

                            # Store as seconds (milliseconds / 1000) for consistency with client expectations
                            symbol_settings['xAxisMax'] = int(now.timestamp())
                            symbol_settings['xAxisMin'] = int(thirty_days_ago.timestamp())

                            logger.info(f"✅ FIXED corrupted X-axis data for {symbol} due to conversion error:")
                            logger.info(f"   New xAxisMin: {symbol_settings['xAxisMin']} ({thirty_days_ago.isoformat()})")
                            logger.info(f"   New xAxisMax: {symbol_settings['xAxisMax']} ({now.isoformat()})")

                            # Save the corrected settings back to Redis
                            await redis.set(settings_key, json.dumps(symbol_settings))
                            logger.info(f"Saved corrected X-axis settings to Redis for {symbol}")

                            # Skip further validation since we just fixed the data
                            data_was_fixed = True

                        # Only check for corrupted data if we didn't already fix it due to conversion errors
                        if not data_was_fixed:
                            # Check if dates are before year 2000 (indicating corrupted data)
                            if min_date.year < 2000 or max_date.year < 2000:
                                # Log the corrupted data in human readable format
                                logger.warning(f"🚨 CORRUPTED X-AXIS DATA DETECTED for {symbol}:")
                                logger.warning(f"   xAxisMin: {x_axis_min} ({min_date.isoformat()})")
                                logger.warning(f"   xAxisMax: {x_axis_max} ({max_date.isoformat()})")
                                logger.warning(f"   Min year: {min_date.year}, Max year: {max_date.year}")

                                # Reset to reasonable values: xAxisMax = NOW, xAxisMin = 30 days before NOW
                                now = datetime.datetime.now(datetime.timezone.utc)
                                thirty_days_ago = now - datetime.timedelta(days=30)

                                # Store as seconds (milliseconds / 1000) for consistency with client expectations
                                symbol_settings['xAxisMax'] = int(now.timestamp())
                                symbol_settings['xAxisMin'] = int(thirty_days_ago.timestamp())

                                logger.info(f"✅ FIXED corrupted X-axis data for {symbol}:")
                                logger.info(f"   New xAxisMin: {symbol_settings['xAxisMin']} ({thirty_days_ago.isoformat()})")
                                logger.info(f"   New xAxisMax: {symbol_settings['xAxisMax']} ({now.isoformat()})")

                                # Save the corrected settings back to Redis
                                await redis.set(settings_key, json.dumps(symbol_settings))
                                logger.info(f"Saved corrected X-axis settings to Redis for {symbol}")
                    else:
                        logger.warning(f"X-axis timestamps are None for {symbol}, skipping validation")

                # Ensure activeIndicators key exists for backward compatibility
                if 'activeIndicators' not in symbol_settings:
                    symbol_settings['activeIndicators'] = []
                # Ensure liveDataEnabled key exists for backward compatibility
                if 'liveDataEnabled' not in symbol_settings:
                    symbol_settings['liveDataEnabled'] = DEFAULT_SYMBOL_SETTINGS['liveDataEnabled']
                # Ensure new AI settings keys exist for backward compatibility
                if 'useLocalOllama' not in symbol_settings:
                    symbol_settings['useLocalOllama'] = DEFAULT_SYMBOL_SETTINGS['useLocalOllama']
                if 'localOllamaModelName' not in symbol_settings:
                    symbol_settings['localOllamaModelName'] = DEFAULT_SYMBOL_SETTINGS['localOllamaModelName']
                # Ensure streamDeltaTime key exists
                if 'streamDeltaTime' not in symbol_settings:
                     symbol_settings['streamDeltaTime'] = DEFAULT_SYMBOL_SETTINGS['streamDeltaTime']

                # Ensure showAgentTrades key exists for backward compatibility
                if 'showAgentTrades' not in symbol_settings:
                    symbol_settings['showAgentTrades'] = DEFAULT_SYMBOL_SETTINGS.get('showAgentTrades', False)

                logger.info(f"GET /settings for {symbol}: Retrieved from Redis: {symbol_settings}")
            else:
                logger.info(f"GET /settings for {symbol}: No settings found in Redis, using defaults.")
                symbol_settings = DEFAULT_SYMBOL_SETTINGS.copy()

                # await redis.set(settings_key, json.dumps(symbol_settings))
            return JSONResponse(symbol_settings)
        except Exception as e:
            logger.error(f"Error getting settings for {symbol} from Redis: {e}", exc_info=True)
            return JSONResponse({"status": "error", "message": "Error retrieving settings"}, status_code=500)

    elif request.method == 'POST':
        try:
            data = await request.json()
            if not data:
                # Log the raw body if possible for empty JSON case
                logger.warning("POST /settings: Received empty JSON for settings update")
                return JSONResponse({"status": "error", "message": "Empty JSON"}, status_code=400)

            symbol_to_update = data.get('symbol')
            if not symbol_to_update:
                logger.warning("POST /settings: 'symbol' field missing in request data.")
                return JSONResponse({"status": "error", "message": "'symbol' field is required in payload"}, status_code=400)

            settings_key = f"settings:{email}:{symbol_to_update}"

            # Log the raw data received from the client immediately
            logger.info(f"POST /settings: RAW data received from client for symbol '{symbol_to_update}': {data}")
            client_sent_stream_delta_time = data.get('streamDeltaTime', 'NOT_SENT_BY_CLIENT') # Check what client sent

            # Fetch existing settings or start with defaults
            existing_settings_json = await redis.get(settings_key)
            if existing_settings_json:
                current_symbol_settings = json.loads(existing_settings_json)
                # Ensure activeIndicators key exists
                if 'activeIndicators' not in current_symbol_settings:
                    current_symbol_settings['activeIndicators'] = []
                # Ensure liveDataEnabled key exists
                if 'liveDataEnabled' not in current_symbol_settings:
                    current_symbol_settings['liveDataEnabled'] = DEFAULT_SYMBOL_SETTINGS['liveDataEnabled']
                # Ensure new AI settings keys exist
                if 'useLocalOllama' not in current_symbol_settings:
                    current_symbol_settings['useLocalOllama'] = DEFAULT_SYMBOL_SETTINGS['useLocalOllama']
                if 'localOllamaModelName' not in current_symbol_settings:
                    current_symbol_settings['localOllamaModelName'] = DEFAULT_SYMBOL_SETTINGS['localOllamaModelName']
                if 'streamDeltaTime' not in current_symbol_settings:
                    current_symbol_settings['streamDeltaTime'] = DEFAULT_SYMBOL_SETTINGS['streamDeltaTime']
                # Ensure showAgentTrades key exists
                if 'showAgentTrades' not in current_symbol_settings:
                    current_symbol_settings['showAgentTrades'] = DEFAULT_SYMBOL_SETTINGS.get('showAgentTrades', False)
            else:
                current_symbol_settings = DEFAULT_SYMBOL_SETTINGS.copy()

            # Update settings with new data
            for key, value in data.items():
                    current_symbol_settings[key] = value

            # Log the state of current_symbol_settings *after* updating from client data and *before* saving to Redis
            logger.info(f"POST /settings for {symbol_to_update} and email {email}: current_symbol_settings compiled for Redis save: {current_symbol_settings}")
            # Log what was received vs what is about to be saved for streamDeltaTime
            logger.info(f"POST /settings for {symbol_to_update}: Client sent streamDeltaTime: {client_sent_stream_delta_time}. Value to be saved in Redis for streamDeltaTime: {current_symbol_settings.get('streamDeltaTime')}")

            await redis.set(settings_key, json.dumps(current_symbol_settings))
            logger.info(f"POST /settings for {symbol_to_update} and email {email}: Settings updated in Redis for {symbol_to_update}: {current_symbol_settings}")
            # Store the last selected symbol globally

            return JSONResponse({"status": "success", "settings": current_symbol_settings})

        except json.JSONDecodeError:
            logger.warning("POST /settings: Received invalid JSON for settings update")
            return JSONResponse({"status": "error", "message": "Invalid JSON"}, status_code=400)
        except Exception as e:
            logger.error(f"Error saving settings to Redis: {e}", exc_info=True)

            return JSONResponse({"status": "error", "message": "Error saving settings"}, status_code=500)

async def set_last_selected_symbol(symbol: str, request: Request):
    """
    Sets the last selected symbol for a user. This value is stored in Redis.
    """
    logger.info(f"POST /set_last_symbol/{symbol} request received.")

    if symbol not in SUPPORTED_SYMBOLS:
        logger.warning(f"POST /set_last_symbol: Unsupported symbol: {symbol}")
        return JSONResponse({"status": "error", "message": "Unsupported symbol"}, status_code=400)

    try:
        redis = await get_redis_connection()
        email = request.session.get("email")
        last_selected_symbol_key_per_user = f"user:{email}:{REDIS_LAST_SELECTED_SYMBOL_KEY}"
        await redis.set(last_selected_symbol_key_per_user, symbol)
        logger.info(f"Set last selected symbol for user {email} to {symbol}")
        return JSONResponse({"status": "success", "message": f"Last selected symbol set to {symbol}"})
    except Exception as e:
        logger.error(f"Error setting last selected symbol: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": "Error setting last selected symbol"}, status_code=500)

async def get_last_selected_symbol(request: Request):
    """
    Gets the last selected symbol for a user from Redis.
    Falls back to BTCUSDT if no symbol is found.
    """
    logger.info(f"GET /get_last_symbol request received.")

    try:
        redis = await get_redis_connection()
        email = request.session.get("email")
        last_selected_symbol_key_per_user = f"user:{email}:{REDIS_LAST_SELECTED_SYMBOL_KEY}"
        symbol = await redis.get(last_selected_symbol_key_per_user)
        if symbol:
            logger.info(f"Got last selected symbol for user {email}: {symbol}")
            return JSONResponse({"status": "success", "symbol": symbol})
        else:
            logger.info(f"No last selected symbol found for user {email}. Falling back to BTCUSDT.")
            return JSONResponse({"status": "success", "symbol": "BTCUSDT"})
    except Exception as e:
        logger.error(f"Error getting last selected symbol: {e}. Falling back to BTCUSDT.", exc_info=True)
        return JSONResponse({"status": "success", "symbol": "BTCUSDT"})

async def stream_logs_endpoint(request: Request):
    from logging_config import log_file_path
    import asyncio
    from sse_starlette.sse import EventSourceResponse

    async def log_generator():
        try:
            with open(log_file_path, "r", encoding="utf-8") as f:
                # Go to the end of the file to start streaming new content
                f.seek(0, 2)
                while True:
                    if await request.is_disconnected():
                        logger.info("Log stream client disconnected.")
                        break

                    line = f.readline()
                    if not line:
                        await asyncio.sleep(0.5)  # Wait for new lines
                        continue

                    yield json.dumps(line.strip()) # Yield just the JSON string, EventSourceResponse adds "data: "
        except asyncio.CancelledError:
            logger.info("Log stream generator cancelled.")

    return EventSourceResponse(log_generator())