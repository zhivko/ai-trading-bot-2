# WebSocket handlers for real-time data streaming

import asyncio
import time
import json
from typing import Dict, Any, List
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from pybit.unified_trading import WebSocket as BybitWS
from config import SUPPORTED_SYMBOLS, DEFAULT_SYMBOL_SETTINGS, AVAILABLE_INDICATORS
from redis_utils import get_redis_connection, publish_live_data_tick, get_cached_klines, get_cached_open_interest, get_stream_key
from logging_config import logger
from indicators import _prepare_dataframe, calculate_macd, calculate_rsi, calculate_stoch_rsi, calculate_open_interest, calculate_jma_indicator, get_timeframe_seconds
from datetime import datetime, timezone

async def stream_live_data_websocket_endpoint(websocket: WebSocket, symbol: str):
    await websocket.accept()
    logger.info(f"WebSocket connection accepted for live data: {symbol}")

    # --- Client-specific state for throttling ---
    client_stream_state = {
        "last_sent_timestamp": 0.0,
        "stream_delta_seconds": 1,  # Default, will be updated from settings
        "last_settings_check_timestamp": 0.0,  # For periodically re-checking settings
        "settings_check_interval_seconds": 3  # How often to check settings (e.g., every 3 seconds)
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
        client_stream_state["last_settings_check_timestamp"] = time.time()  # Initialize after first load attempt
    except Exception as e:
        logger.error(f"Error fetching or processing streamDeltaTime settings for {symbol}: {e}. Defaulting stream_delta_seconds to 0.", exc_info=True)

    # --- End client-specific state ---
    client_stream_state["last_settings_check_timestamp"] = time.time()  # Initialize even on error

    # Get the current asyncio event loop
    loop = asyncio.get_running_loop()

    if symbol not in SUPPORTED_SYMBOLS:
        logger.warning(f"Unsupported symbol requested for live stream: {symbol}")
        await websocket.close(code=1008, reason="Unsupported symbol")
        return

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
            if "Cannot call \"send\" once a close message has been sent" in str(e):
                pass
            elif "Cannot call \"send\" after WebSocket has been closed" in str(e):
                pass
            elif "closed connection before send could complete." in str(e):
                pass
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
                            live_data = {
                                "symbol": ticker_data.get("symbol", symbol),
                                "time": int(message_timestamp_ms) // 1000,
                                "price": float(ticker_data["lastPrice"]),
                                "vol": float(ticker_data.get("volume24h", 0)),
                            }
                            loop.call_soon_threadsafe(asyncio.create_task, send_to_client(live_data))
                            client_stream_state["last_sent_timestamp"] = current_server_timestamp_sec
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


async def stream_combined_data_websocket_endpoint(websocket: WebSocket, symbol: str):
    """Combined WebSocket endpoint that streams historical OHLC data with indicators and live data from Redis."""
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
    }

    # Validate URL path symbol
    if symbol not in SUPPORTED_SYMBOLS:
        logger.warning(f"Unsupported symbol requested for combined data: {symbol}")
        await websocket.close(code=1008, reason="Unsupported symbol")
        return

    # Initialize active_symbol with URL path symbol (will be updated from message if provided)
    active_symbol = symbol

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
            elif "[Errno 22] Invalid argument" in error_str:
                logger.error(f"Socket error sending data to client (combined data {active_symbol}): {e}", exc_info=True)
            else:
                logger.error(f"Unexpected error sending data to client (combined data {active_symbol}): {e}", exc_info=True)

    async def send_historical_data():
        """Send historical OHLC data with indicators."""
        try:
            logger.info(f"Sending historical data for {active_symbol} with indicators: {client_state['indicators']}")
            logger.info(f"Time range: from_ts={client_state['from_ts']}, to_ts={client_state['to_ts']}, resolution={client_state['resolution']}")

            # Get historical klines from Redis with error handling
            try:
                logger.info(f"🔍 REDIS QUERY: Requesting klines for {active_symbol}, resolution={client_state['resolution']}, from_ts={client_state['from_ts']}, to_ts={client_state['to_ts']}")
                klines = await get_cached_klines(active_symbol, client_state["resolution"], client_state["from_ts"], client_state["to_ts"])
                logger.info(f"✅ REDIS SUCCESS: Retrieved {len(klines) if klines else 0} klines from Redis for {active_symbol}")
            except Exception as e:
                logger.error(f"❌ REDIS FAILURE: Failed to get cached klines from Redis for {active_symbol}: {e}", exc_info=True)
                logger.error(f"📊 REDIS CONTEXT: symbol={active_symbol}, resolution={client_state['resolution']}, from_ts={client_state['from_ts']}, to_ts={client_state['to_ts']}")
                return

            # If no klines found in cache, try to fetch from Bybit as fallback
            if not klines or len(klines) == 0:
                logger.warning(f"⚠️ No historical klines found in Redis cache for {active_symbol}")
                logger.info(f"🔄 FALLBACK: Attempting to fetch data from Bybit API for {active_symbol}")

                try:
                    # Import the Bybit fetch function
                    from redis_utils import fetch_klines_from_bybit, cache_klines

                    # Fetch data from Bybit
                    logger.info(f"📡 FETCHING FROM BYBIT: {active_symbol} {client_state['resolution']} from {client_state['from_ts']} to {client_state['to_ts']}")
                    fetched_klines = fetch_klines_from_bybit(active_symbol, client_state["resolution"], client_state["from_ts"], client_state["to_ts"])

                    if fetched_klines and len(fetched_klines) > 0:
                        logger.info(f"✅ BYBIT SUCCESS: Fetched {len(fetched_klines)} klines from Bybit for {active_symbol}")

                        # Cache the fetched data
                        await cache_klines(active_symbol, client_state["resolution"], fetched_klines)
                        logger.info(f"💾 CACHED: Stored {len(fetched_klines)} klines in Redis for {active_symbol}")

                        # Use the fetched data
                        klines = fetched_klines
                    else:
                        logger.warning(f"❌ BYBIT FAILURE: No data fetched from Bybit for {active_symbol}")
                        return

                except Exception as e:
                    logger.error(f"❌ BYBIT FETCH ERROR: Failed to fetch data from Bybit for {active_symbol}: {e}", exc_info=True)
                    return
            else:
                logger.info(f"✅ CACHE HIT: Found {len(klines)} klines in Redis cache for {active_symbol}")

            # Calculate indicators with error handling
            try:
                logger.info(f"🔍 SERVER DEBUG: About to calculate indicators for {active_symbol}")
                logger.info(f"🔍 SERVER DEBUG: Indicators requested: {client_state['indicators']}")
                logger.info(f"🔍 SERVER DEBUG: Klines count: {len(klines)}")
                indicators_data = await calculate_indicators_for_data(klines, client_state["indicators"])
                logger.info(f"🔍 SERVER DEBUG: Indicators calculation completed for {active_symbol}")
                logger.info(f"🔍 SERVER DEBUG: Indicators data keys: {list(indicators_data.keys()) if indicators_data else 'None'}")
            except Exception as e:
                logger.error(f"Failed to calculate indicators for {active_symbol}: {e}", exc_info=True)
                logger.error(f"📊 INDICATOR CALCULATION FAILURE CONTEXT:")
                logger.error(f"  Symbol: {active_symbol}")
                logger.error(f"  Indicators requested: {client_state['indicators']}")
                logger.error(f"  Klines count: {len(klines) if klines else 0}")
                logger.error(f"  Resolution: {client_state['resolution']}")
                logger.error(f"  Time range: {client_state['from_ts']} to {client_state['to_ts']}")
                indicators_data = {}

            # Prepare combined data
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
                        try:
                            idx = indicator_values["t"].index(kline["time"])
                            data_point["indicators"][indicator_id] = {}
                            for key, values in indicator_values.items():
                                if key != "t" and idx < len(values):
                                    data_point["indicators"][indicator_id][key] = values[idx]
                        except (ValueError, IndexError):
                            pass

                combined_data.append(data_point)

            # Send historical data in batches
            batch_size = 100
            total_batches = (len(combined_data) + batch_size - 1) // batch_size
            logger.info(f"Sending {len(combined_data)} historical data points in {total_batches} batches for {active_symbol}")

            # Log sample of data being sent to verify timestamps
            if combined_data:
                first_point = combined_data[0]
                last_point = combined_data[-1]
                logger.info(f"📤 SAMPLE DATA POINTS TO CLIENT:")
                logger.info(f"  First point: time={first_point['time']} ({datetime.fromtimestamp(first_point['time'], timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')})")
                logger.info(f"  Last point: time={last_point['time']} ({datetime.fromtimestamp(last_point['time'], timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')})")
                logger.info(f"  Time range in data: {first_point['time']} to {last_point['time']} (seconds)")

            for i in range(0, len(combined_data), batch_size):
                batch = combined_data[i:i + batch_size]
                batch_num = i // batch_size + 1
                logger.info(f"Sending batch {batch_num}/{total_batches} with {len(batch)} data points")

                try:
                    await send_to_client({
                        "type": "historical",
                        "symbol": active_symbol,
                        "data": batch
                    })
                    logger.info(f"Successfully sent batch {batch_num}/{total_batches}")
                except Exception as e:
                    logger.error(f"Failed to send batch {batch_num}/{total_batches}: {e}")
                    break

                await asyncio.sleep(0.01)  # Small delay to prevent overwhelming client

            logger.info(f"Completed sending {len(combined_data)} historical data points for {active_symbol}")
            client_state["historical_sent"] = True

        except Exception as e:
            logger.error(f"Error sending historical data for {active_symbol}: {e}", exc_info=True)

    async def stream_live_data():
        """Stream live data from Redis streams with indicators."""
        try:
            # Get Redis connection with error handling
            try:
                redis = await get_redis_connection()
            except Exception as e:
                logger.error(f"Failed to establish Redis connection for live streaming {active_symbol}: {e}", exc_info=True)
                return

            stream_key = get_stream_key(active_symbol, client_state["resolution"])
            group_name = f"combined:{active_symbol}:{client_state['resolution']}"
            consumer_id = f"consumer:{id(websocket)}"

            # Create consumer group if it doesn't exist
            try:
                await redis.xgroup_create(stream_key, group_name, id='0', mkstream=True)
            except Exception as e:
                if "BUSYGROUP" not in str(e):
                    logger.error(f"Failed to create Redis consumer group for {active_symbol}: {e}", exc_info=True)
                    return

            logger.info(f"Starting live stream for {active_symbol} from Redis stream: {stream_key}")

            while client_state["live_mode"] and websocket.client_state == WebSocketState.CONNECTED:
                try:
                    # Read from Redis stream with error handling
                    try:
                        messages = await redis.xreadgroup(
                            group_name, consumer_id, {stream_key: ">"}, count=10, block=5000
                        )
                    except Exception as e:
                        logger.error(f"Failed to read from Redis stream for {active_symbol}: {e}", exc_info=True)
                        await asyncio.sleep(1)
                        continue

                    if messages:
                        for _stream_name, message_list in messages:
                            for message_id, message_data_dict in message_list:
                                try:
                                    kline_json_str = message_data_dict.get('data')
                                    if kline_json_str:
                                        try:
                                            kline_data = json.loads(kline_json_str)
                                        except json.JSONDecodeError as e:
                                            logger.error(f"Invalid JSON in Redis message {message_id} for {active_symbol}: {e}")
                                            continue

                                        # For live data, we need recent klines to calculate indicators
                                        # Get last 200 klines for indicator calculation
                                        current_time = int(time.time())
                                        lookback_start = current_time - (200 * get_timeframe_seconds(client_state["resolution"]))

                                        try:
                                            recent_klines = await get_cached_klines(active_symbol, client_state["resolution"], lookback_start, current_time)
                                        except Exception as e:
                                            logger.error(f"Failed to get recent klines for indicators {active_symbol}: {e}", exc_info=True)
                                            recent_klines = None

                                        if recent_klines:
                                            # Add the current live kline if not already in the list
                                            if not any(k["time"] == kline_data["time"] for k in recent_klines):
                                                recent_klines.append(kline_data)
                                                recent_klines.sort(key=lambda x: x["time"])

                                            # Calculate indicators for recent data
                                            try:
                                                indicators_data = await calculate_indicators_for_data(recent_klines, client_state["indicators"])
                                            except Exception as e:
                                                logger.error(f"Failed to calculate indicators for live data {active_symbol}: {e}", exc_info=True)
                                                indicators_data = {}

                                            # Get indicator values for the current kline
                                            current_indicators = {}
                                            for indicator_id, indicator_values in indicators_data.items():
                                                if "t" in indicator_values:
                                                    try:
                                                        idx = indicator_values["t"].index(kline_data["time"])
                                                        current_indicators[indicator_id] = {}
                                                        for key, values in indicator_values.items():
                                                            if key != "t" and idx < len(values):
                                                                current_indicators[indicator_id][key] = values[idx]
                                                    except (ValueError, IndexError):
                                                        pass
                                        else:
                                            current_indicators = {}

                                        # Create live data point with indicators
                                        live_data_point = {
                                            "time": kline_data["time"],
                                            "ohlc": {
                                                "open": kline_data["open"],
                                                "high": kline_data["high"],
                                                "low": kline_data["low"],
                                                "close": kline_data["close"],
                                                "volume": kline_data["vol"]
                                            },
                                            "indicators": current_indicators
                                        }

                                        try:
                                            await send_to_client({
                                                "type": "live",
                                                "symbol": active_symbol,
                                                "data": live_data_point
                                            })
                                        except Exception as e:
                                            logger.error(f"Failed to send live data to client for {active_symbol}: {e}")
                                            continue

                                        # Acknowledge the message
                                        try:
                                            await redis.xack(stream_key, group_name, message_id)
                                        except Exception as e:
                                            logger.error(f"Failed to acknowledge Redis message {message_id} for {active_symbol}: {e}")

                                except Exception as e:
                                    logger.error(f"Error processing live message {message_id} for {active_symbol}: {e}", exc_info=True)
                                    continue

                    await asyncio.sleep(0.1)

                except Exception as e:
                    logger.error(f"Error in live streaming loop for {active_symbol}: {e}", exc_info=True)
                    await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Error in live streaming setup for {active_symbol}: {e}", exc_info=True)

    async def calculate_indicators_for_data(klines: List[Dict], indicators: List[str]) -> Dict[str, Any]:
        """Calculate indicators for the given klines data."""
        logger.info(f"🔍 SERVER DEBUG: calculate_indicators_for_data called with {len(klines) if klines else 0} klines and indicators: {indicators}")
        if not klines or not indicators:
            logger.info(f"🔍 SERVER DEBUG: Early return - no klines or no indicators")
            return {}

        # Prepare DataFrame with error handling
        try:
            # Try to get Open Interest data from cache first
            oi_data = await get_cached_open_interest(active_symbol, client_state["resolution"], client_state["from_ts"], client_state["to_ts"])

            # If no OI data in cache, try to fetch from Bybit as fallback
            if not oi_data or len(oi_data) == 0:
                logger.info(f"🔄 OI FALLBACK: No Open Interest data in cache for {active_symbol}, attempting to fetch from Bybit")
                try:
                    from indicators import fetch_open_interest_from_bybit
                    from redis_utils import cache_open_interest

                    oi_fetched = fetch_open_interest_from_bybit(active_symbol, client_state["resolution"], client_state["from_ts"], client_state["to_ts"])
                    if oi_fetched and len(oi_fetched) > 0:
                        await cache_open_interest(active_symbol, client_state["resolution"], oi_fetched)
                        logger.info(f"💾 OI CACHED: Stored {len(oi_fetched)} Open Interest entries for {active_symbol}")
                        oi_data = oi_fetched
                    else:
                        logger.info(f"ℹ️ OI INFO: No Open Interest data available from Bybit for {active_symbol}")
                except Exception as e:
                    logger.warning(f"⚠️ OI FETCH WARNING: Failed to fetch Open Interest data for {active_symbol}: {e}")

            df = _prepare_dataframe(klines, oi_data)
            if df is None or df.empty:
                logger.warning(f"Failed to prepare DataFrame for indicators calculation for {active_symbol}")
                return {}
        except Exception as e:
            logger.error(f"Error preparing DataFrame for indicators for {active_symbol}: {e}", exc_info=True)
            return {}

        indicators_data = {}

        for indicator_id in indicators:
            logger.info(f"🔍 SERVER DEBUG: Processing indicator {indicator_id}")
            config = next((item for item in AVAILABLE_INDICATORS if item["id"] == indicator_id), None)
            if not config:
                logger.warning(f"Unknown indicator {indicator_id} requested for {active_symbol}")
                continue

            try:
                params = config["params"]
                calc_id = config["id"]
                logger.info(f"🔍 SERVER DEBUG: Indicator {indicator_id} config: calc_id={calc_id}, params={params}")

                if calc_id == "macd":
                    logger.info(f"🔍 SERVER DEBUG: Calling calculate_macd for {indicator_id}")
                    result = calculate_macd(df.copy(), **params)
                elif calc_id == "rsi":
                    logger.info(f"🔍 SERVER DEBUG: Calling calculate_rsi for {indicator_id}")
                    result = calculate_rsi(df.copy(), **params)
                elif calc_id.startswith("stochrsi"):
                    logger.info(f"🔍 SERVER DEBUG: Calling calculate_stoch_rsi for {indicator_id}")
                    result = calculate_stoch_rsi(df.copy(), **params)
                elif calc_id == "open_interest":
                    logger.info(f"🔍 SERVER DEBUG: Calling calculate_open_interest for {indicator_id}")
                    result = calculate_open_interest(df.copy())
                elif calc_id == "jma":
                    logger.info(f"🔍 SERVER DEBUG: Calling calculate_jma_indicator for {indicator_id}")
                    result = calculate_jma_indicator(df.copy(), **params)
                else:
                    logger.warning(f"Unsupported indicator calculation {calc_id} for {active_symbol}")
                    continue

                logger.info(f"🔍 SERVER DEBUG: Indicator {indicator_id} calculation result: {result is not None}")
                if result:
                    logger.info(f"🔍 SERVER DEBUG: Indicator {indicator_id} result keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}")
                    if "t" in result:
                        logger.info(f"🔍 SERVER DEBUG: Indicator {indicator_id} has 't' key with {len(result['t'])} timestamps")
                        indicators_data[indicator_id] = result
                        logger.info(f"🔍 SERVER DEBUG: Added indicator {indicator_id} to indicators_data")
                    else:
                        logger.warning(f"Indicator {indicator_id} calculation result missing 't' key for {active_symbol}")
                else:
                    logger.warning(f"Indicator {indicator_id} calculation returned None for {active_symbol}")

            except Exception as e:
                logger.error(f"Error calculating indicator {indicator_id} for {active_symbol}: {e}", exc_info=True)

        return indicators_data

    try:
        while websocket.client_state == WebSocketState.CONNECTED:
            try:
                # Receive client messages with error handling
                try:
                    message = await asyncio.wait_for(websocket.receive_json(), timeout=1.0)
                except asyncio.TimeoutError:
                    # No message received, continue with keep-alive
                    pass
                except Exception as e:
                    logger.error(f"Failed to receive WebSocket message for {symbol}: {e}", exc_info=True)
                    # Check if this is a WebSocketDisconnect with service restart code
                    if isinstance(e, WebSocketDisconnect) and e.code == 1012:
                        logger.warning(f"🚨 CRITICAL: WebSocket disconnect with service restart code (1012) detected for {symbol}")
                        logger.info(f"📋 CONTEXT: Last processed indicators: {client_state.get('indicators', [])}")
                        logger.info(f"📋 CONTEXT: Active symbol: {active_symbol}, Resolution: {client_state.get('resolution', 'unknown')}")
                    continue
                else:
                    # Validate message structure
                    if not isinstance(message, dict):
                        logger.error(f"Invalid message format for {symbol}: expected dict, got {type(message)}")
                        continue

                    message_type = message.get("type")
                    if not message_type:
                        logger.error(f"Missing 'type' field in WebSocket message for {symbol}")
                        continue

                    if message_type == "config":
                        # Update client configuration
                        old_from_ts = client_state["from_ts"]
                        old_to_ts = client_state["to_ts"]

                        # Get symbol from message (with URL path as fallback)
                        message_symbol = message.get("symbol")
                        active_symbol = message_symbol if message_symbol else symbol

                        # Validate symbol consistency
                        if message_symbol and message_symbol != symbol:
                            logger.warning(f"Symbol mismatch: URL path={symbol}, message={message_symbol}. Using message symbol.")
                            active_symbol = message_symbol

                        # Log the raw message for debugging timestamp issues
                        logger.info(f"📨 RAW MESSAGE RECEIVED for {active_symbol}: {json.dumps(message, indent=2)}")

                        # TIMESTAMP DEBUG: Log received timestamps with unit analysis
                        received_from_ts = message.get("from_ts")
                        received_to_ts = message.get("to_ts")
                        logger.info(f"[TIMESTAMP DEBUG] websocket_handlers.py - Received timestamps:")
                        logger.info(f"  from_ts: {received_from_ts} (type: {type(received_from_ts)})")
                        logger.info(f"  to_ts: {received_to_ts} (type: {type(received_to_ts)})")

                        # Check if timestamps are ISO strings or numeric
                        if received_from_ts and received_to_ts:
                            if isinstance(received_from_ts, str) and isinstance(received_to_ts, str):
                                logger.info(f"[TIMESTAMP DEBUG] Timestamps are ISO strings (correct format)")
                                # Convert ISO strings to Unix timestamps (seconds)
                                try:
                                    from_datetime = datetime.fromisoformat(received_from_ts.replace('Z', '+00:00'))
                                    to_datetime = datetime.fromisoformat(received_to_ts.replace('Z', '+00:00'))
                                    converted_from = int(from_datetime.timestamp())
                                    converted_to = int(to_datetime.timestamp())
                                    logger.info(f"[TIMESTAMP CONVERSION] ISO strings -> Unix seconds:")
                                    logger.info(f"  {received_from_ts} -> {converted_from} ({from_datetime.strftime('%Y-%m-%d %H:%M:%S UTC')})")
                                    logger.info(f"  {received_to_ts} -> {converted_to} ({to_datetime.strftime('%Y-%m-%d %H:%M:%S UTC')})")
                                except Exception as e:
                                    logger.error(f"Failed to parse ISO timestamp strings: {e}")
                                    converted_from = received_from_ts
                                    converted_to = received_to_ts
                            elif received_from_ts > 1e10:  # Likely milliseconds (10 digits or more)
                                logger.warning(f"[TIMESTAMP DEBUG] from_ts {received_from_ts} appears to be in MILLISECONDS (should be seconds)")
                                logger.info(f"  Converting to seconds: {received_from_ts // 1000}")
                                # Log the actual conversion
                                converted_from = received_from_ts // 1000
                                converted_to = received_to_ts // 1000
                                logger.info(f"[TIMESTAMP CONVERSION] Client milliseconds -> Server seconds:")
                                logger.info(f"  {received_from_ts} -> {converted_from} ({datetime.fromtimestamp(converted_from, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')})")
                                logger.info(f"  {received_to_ts} -> {converted_to} ({datetime.fromtimestamp(converted_to, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')})")
                            elif received_from_ts > 1e8:  # Likely seconds (8-9 digits)
                                logger.info(f"[TIMESTAMP DEBUG] from_ts {received_from_ts} appears to be in SECONDS (correct)")
                                converted_from = received_from_ts
                                converted_to = received_to_ts
                            else:
                                logger.warning(f"[TIMESTAMP DEBUG] from_ts {received_from_ts} appears to be invalid")
                                converted_from = received_from_ts
                                converted_to = received_to_ts

                        # Validate and set configuration with error handling
                        try:
                            client_state["indicators"] = message.get("indicators", [])
                            client_state["resolution"] = message.get("resolution", "1h")

                            # Use the converted timestamps from above
                            client_state["from_ts"] = converted_from if 'converted_from' in locals() else message.get("from_ts")
                            client_state["to_ts"] = converted_to if 'converted_to' in locals() else message.get("to_ts", int(time.time()))

                            logger.info(f"[TIMESTAMP FIX] Final timestamps set:")
                            logger.info(f"  from_ts: {client_state['from_ts']} (type: {type(client_state['from_ts'])})")
                            logger.info(f"  to_ts: {client_state['to_ts']} (type: {type(client_state['to_ts'])})")

                            # Validate timestamps
                            if client_state["from_ts"] is not None and not isinstance(client_state["from_ts"], (int, float)):
                                logger.error(f"Invalid from_ts type for {active_symbol}: {type(client_state['from_ts'])}, expected int/float")
                                continue
                            if client_state["to_ts"] is not None and not isinstance(client_state["to_ts"], (int, float)):
                                logger.error(f"Invalid to_ts type for {active_symbol}: {type(client_state['to_ts'])}, expected int/float")
                                continue

                            logger.info(f"Client config updated for {active_symbol}: indicators={client_state['indicators']}, resolution={client_state['resolution']}")
                            logger.info(f"📊 MESSAGE FIELD VALUES for {active_symbol}:")
                            logger.info(f"  symbol: {message_symbol} (fallback: {symbol})")
                            logger.info(f"  from_ts: {message.get('from_ts')} (type: {type(message.get('from_ts'))})")
                            logger.info(f"  to_ts: {message.get('to_ts')} (type: {type(message.get('to_ts'))})")
                            logger.info(f"  indicators: {message.get('indicators')} (type: {type(message.get('indicators'))})")
                            logger.info(f"  resolution: {message.get('resolution')} (type: {type(message.get('resolution'))})")

                            # Check if this is a new time range request (panning/zooming)
                            time_range_changed = (old_from_ts != client_state["from_ts"] or
                                                old_to_ts != client_state["to_ts"])

                            logger.info(f"📊 SERVER TIME RANGE ANALYSIS for {active_symbol}:")
                            logger.info(f"  Old range: from_ts={old_from_ts}, to_ts={old_to_ts}")
                            logger.info(f"  New range: from_ts={client_state['from_ts']}, to_ts={client_state['to_ts']}")
                            logger.info(f"  Time range changed: {time_range_changed}")
                            logger.info(f"  Historical sent: {client_state['historical_sent']}")
                            logger.info(f"  Has timestamps: from_ts={bool(client_state['from_ts'])}, to_ts={bool(client_state['to_ts'])}")

                            # Log human-readable dates for comparison
                            if client_state['from_ts'] and client_state['to_ts']:
                                try:
                                    # Timestamps should now be in seconds after conversion above
                                    from_ts_seconds = client_state['from_ts']
                                    to_ts_seconds = client_state['to_ts']

                                    from_date = datetime.fromtimestamp(from_ts_seconds, timezone.utc)
                                    to_date = datetime.fromtimestamp(to_ts_seconds, timezone.utc)
                                    range_seconds = client_state['to_ts'] - client_state['from_ts']
                                    range_hours = range_seconds / 3600  # Convert seconds to hours (not milliseconds)

                                    # Also show local time for the user's timezone
                                    local_tz = datetime.now().astimezone().tzinfo
                                    from_date_local = datetime.fromtimestamp(from_ts_seconds, local_tz)
                                    to_date_local = datetime.fromtimestamp(to_ts_seconds, local_tz)

                                    logger.info(f"  📅 SERVER RECEIVED RANGE (UTC):")
                                    logger.info(f"    From: {from_date.strftime('%Y-%m-%d %H:%M:%S')} UTC ({client_state['from_ts']})")
                                    logger.info(f"    To: {to_date.strftime('%Y-%m-%d %H:%M:%S')} UTC ({client_state['to_ts']})")
                                    logger.info(f"    Range: {range_seconds} seconds ({range_hours:.1f} hours)")

                                    logger.info(f"  📅 SERVER RECEIVED RANGE (Local Time):")
                                    logger.info(f"    From: {from_date_local.strftime('%Y-%m-%d %H:%M:%S')} {from_date_local.tzname()}")
                                    logger.info(f"    To: {to_date_local.strftime('%Y-%m-%d %H:%M:%S')} {to_date_local.tzname()}")

                                    # TIMEZONE DEBUGGING: Compare with user's expected chart view state
                                    logger.info(f"  🌍 TIMEZONE ANALYSIS:")
                                    logger.info(f"    Server timezone: {datetime.now().astimezone().tzinfo} (UTC{datetime.now().astimezone().utcoffset().total_seconds() / 3600:+.1f})")
                                    logger.info(f"    User timezone (from logs): Europe/Ljubljana (UTC+2)")
                                    logger.info(f"    Timezone difference: {2 - (datetime.now().astimezone().utcoffset().total_seconds() / 3600):.1f} hours")

                                    # Log what will be sent to client (timestamps in seconds)
                                    logger.info(f"  📤 DATA TO BE SENT TO CLIENT:")
                                    logger.info(f"    Timestamps will be sent as seconds (not milliseconds)")
                                    logger.info(f"    Client will receive: from_ts={client_state['from_ts']}, to_ts={client_state['to_ts']}")
                                    logger.info(f"    Client local time equivalent: {from_date_local.strftime('%Y-%m-%d %H:%M:%S')} to {to_date_local.strftime('%Y-%m-%d %H:%M:%S')}")

                                    # Check if this matches the user's Chart View State
                                    user_chart_min = "30/08/2025, 10:31:39"
                                    user_chart_max = "04/09/2025, 01:58:37"
                                    logger.info(f"  📊 USER'S CHART VIEW STATE:")
                                    logger.info(f"    X-Axis Min: {user_chart_min}")
                                    logger.info(f"    X-Axis Max: {user_chart_max}")
                                    logger.info(f"    Expected local time range: 2025-08-30 10:31 to 2025-09-04 01:58")
                                    logger.info(f"    Server received UTC equivalent: {from_date.strftime('%Y-%m-%d %H:%M')} to {to_date.strftime('%Y-%m-%d %H:%M')}")

                                except (ValueError, OSError) as e:
                                    logger.warning(f"Failed to convert timestamps to datetime for {active_symbol}: {e}")

                            # Send historical data if:
                            # 1. Time range changed (new pan/zoom request), OR
                            # 2. Historical data hasn't been sent yet
                            should_send_historical = (time_range_changed or not client_state["historical_sent"]) and client_state["from_ts"] and client_state["to_ts"]

                            logger.info(f"Should send historical data: {should_send_historical}")

                            if should_send_historical:
                                logger.info(f"Sending historical data for {active_symbol} - time range changed: {time_range_changed}, historical_sent: {client_state['historical_sent']}")
                                await send_historical_data()
                            else:
                                logger.info(f"NOT sending historical data for {active_symbol} - conditions not met")

                                # Switch to live mode after sending historical data
                                client_state["live_mode"] = True

                                # Start live streaming task
                                live_task = asyncio.create_task(stream_live_data())

                        except Exception as e:
                            logger.error(f"Error processing config message for {active_symbol}: {e}", exc_info=True)
                            continue

                    elif message_type == "start_live":
                        # Client requests to start live streaming
                        try:
                            client_state["live_mode"] = True
                            if not client_state["historical_sent"]:
                                await send_historical_data()

                            # Start live streaming if not already started
                            if "live_task" not in locals() or live_task.done():
                                live_task = asyncio.create_task(stream_live_data())

                            logger.info(f"Started live streaming for {symbol}")
                        except Exception as e:
                            logger.error(f"Error processing start_live message for {symbol}: {e}", exc_info=True)
                            continue

                    else:
                        logger.warning(f"Unknown message type '{message_type}' received for {active_symbol}")

            except Exception as e:
                logger.error(f"Error in WebSocket message processing loop for {active_symbol}: {e}", exc_info=True)

            await asyncio.sleep(0.1)

    except WebSocketDisconnect as e:
        logger.info(f"Client disconnected from combined data stream for {active_symbol} with code: {e.code}, reason: {e.reason}")
        if e.code == 1012:
            logger.warning(f"⚠️ SERVICE RESTART DETECTED: Client sent close code 1012 for {active_symbol} - server may be restarting")
            # Add diagnostic info
            import psutil
            import os
            try:
                process = psutil.Process(os.getpid())
                memory_mb = process.memory_info().rss / 1024 / 1024
                logger.info(f"📊 SERVER DIAGNOSTICS: Memory usage: {memory_mb:.2f} MB, CPU: {process.cpu_percent()}%")
            except Exception as diag_e:
                logger.error(f"Failed to get server diagnostics: {diag_e}")
    except Exception as e:
        logger.error(f"Error in combined data WebSocket for {active_symbol}: {e}", exc_info=True)
    finally:
        # Cancel live streaming task if it exists
        if "live_task" in locals() and not live_task.done():
            live_task.cancel()
            try:
                await live_task
            except asyncio.CancelledError:
                pass

        if websocket.client_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close()
            except Exception as e:
                logger.error(f"Error closing WebSocket for {active_symbol}: {e}")