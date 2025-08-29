# WebSocket handlers for real-time data streaming

import asyncio
import time
import json
from typing import Dict, Any
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from pybit.unified_trading import WebSocket as BybitWS
from config import SUPPORTED_SYMBOLS, DEFAULT_SYMBOL_SETTINGS
from redis_utils import get_redis_connection, publish_live_data_tick
from logging_config import logger

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