# Utility API endpoints

import json
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from config import SUPPORTED_SYMBOLS, DEFAULT_SYMBOL_SETTINGS, REDIS_LAST_SELECTED_SYMBOL_KEY
from redis_utils import get_redis_connection
from logging_config import logger

async def settings_endpoint(request: Request):
    global DEFAULT_SYMBOL_SETTINGS
    redis = await get_redis_connection()

    email = request.session.get("email")
    symbol = request.query_params.get("symbol")
    settings_key = f"settings:{email}:{symbol}"

    if request.method == 'GET':
        if not symbol:
            logger.warning("GET /settings: Symbol query parameter is missing.")
            return JSONResponse({"status": "error", "message": "Symbol query parameter is required"}, status_code=400)
        symbol = request.query_params.get("symbol")
        settings_key = f"settings:{email}:{symbol}"

        try:
            settings_json = await redis.get(settings_key)
            if settings_json:
                symbol_settings = json.loads(settings_json)
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
            settings_key = f"settings:{email}:{symbol_to_update}"

            if not symbol_to_update:
                logger.warning("POST /settings: 'symbol' field missing in request data.")
                return JSONResponse({"status": "error", "message": "'symbol' field is required in payload"}, status_code=400)

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
            logger.info(f"No last selected symbol found for user {email}.")
            return JSONResponse({"status": "no_data", "message": "No last selected symbol found."}, status_code=404)
    except Exception as e:
        logger.error(f"Error getting last selected symbol: {e}", exc_info=True)

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