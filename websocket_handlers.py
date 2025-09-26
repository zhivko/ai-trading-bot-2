# WebSocket handlers for real-time data streaming

import asyncio
import time
import json
import numpy as np
import csv
import os
from typing import Dict, Any, List
import httpx
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from pybit.unified_trading import WebSocket as BybitWS
from config import SUPPORTED_SYMBOLS, DEFAULT_SYMBOL_SETTINGS, AVAILABLE_INDICATORS
from redis_utils import get_redis_connection, publish_live_data_tick, get_cached_klines, get_cached_open_interest, get_stream_key, get_sync_redis_connection
from logging_config import logger
from indicators import _prepare_dataframe, calculate_macd, calculate_rsi, calculate_stoch_rsi, calculate_open_interest, calculate_jma_indicator, calculate_cto_line, get_timeframe_seconds, find_buy_signals
from datetime import datetime, timezone
from drawing_manager import get_drawings


async def fetch_positions_from_trading_service() -> Dict[str, Any]:
    """Fetch current positions from the trading service"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://localhost:8000/positions")
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    return data.get("positions", [])
                else:
                    logger.warning(f"Trading service returned error: {data}")
                    return []
            else:
                logger.error(f"Failed to fetch positions from trading service: HTTP {response.status_code}")
                return []
    except Exception as e:
        logger.error(f"Error fetching positions from trading service: {e}")
        return []


async def stream_live_data_websocket_endpoint(websocket: WebSocket, symbol: str):
    # SECURITY FIX: Validate symbol BEFORE accepting WebSocket connection
    # This prevents accepting connections for invalid/malicious symbols
    if symbol not in SUPPORTED_SYMBOLS:
        logger.warning(f"SECURITY: Unsupported symbol '{symbol}' requested for live data WebSocket - rejecting before accept")
        # Don't accept the connection for invalid symbols
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
        client_stream_state["last_settings_check_timestamp"] = time.time()  # Initialize after first load attempt
    except Exception as e:
        logger.error(f"Error fetching or processing streamDeltaTime settings for {symbol}: {e}. Defaulting stream_delta_seconds to 0.", exc_info=True)

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
                                logger.debug(f"Redis get result for key '{live_price_key}': {price_str}")
                                if price_str:
                                    live_price = float(price_str)
                                    logger.info(f"✅ Retrieved live price from Redis for {symbol}: {live_price}")
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
                                logger.debug(f"📤 Sent live price update for {symbol}: {live_price} (changed from {client_stream_state['last_sent_live_price']})")
                            else:
                                logger.debug(f"⏭️ Skipped sending duplicate live price for {symbol}: {live_price} (same as last sent)")
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
            # Periodically send positions updates (independent of price ticks)
            if current_loop_time - client_stream_state.get("last_positions_update", 0) >= client_stream_state.get("positions_update_interval", 10):
                try:
                    positions = await fetch_positions_from_trading_service()
                    client_stream_state["cached_positions"] = positions
                    client_stream_state["last_positions_update"] = current_loop_time

                    # Send positions update as separate WebSocket message type
                    positions_message = {
                        "type": "positions_update",
                        "symbol": symbol,  # Include symbol for context
                        "positions": positions,
                        "timestamp": int(current_loop_time)
                    }
                    await send_to_client(positions_message)
                    logger.debug(f"📊 Live WebSocket sent positions update with {len(positions)} positions")
                except Exception as pos_e:
                    logger.warning(f"Failed to update and send positions: {pos_e}")

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


async def stream_live_data_websocket_endpoint(websocket: WebSocket, symbol: str):
    # SECURITY FIX: Validate symbol BEFORE accepting WebSocket connection
    # This prevents accepting connections for invalid/malicious symbols
    if symbol not in SUPPORTED_SYMBOLS:
        logger.warning(f"SECURITY: Unsupported symbol '{symbol}' requested for live data WebSocket - rejecting before accept")
        # Don't accept the connection for invalid symbols
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
        client_stream_state["last_settings_check_timestamp"] = time.time()  # Initialize after first load attempt
    except Exception as e:
        logger.error(f"Error fetching or processing streamDeltaTime settings for {symbol}: {e}. Defaulting stream_delta_seconds to 0.", exc_info=True)

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
                                logger.debug(f"Redis get result for key '{live_price_key}': {price_str}")
                                if price_str:
                                    live_price = float(price_str)
                                    logger.info(f"✅ Retrieved live price from Redis for {symbol}: {live_price}")
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
                                logger.debug(f"📤 Sent live price update for {symbol}: {live_price} (changed from {client_stream_state['last_sent_live_price']})")
                            else:
                                logger.debug(f"⏭️ Skipped sending duplicate live price for {symbol}: {live_price} (same as last sent)")
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



async def stream_combined_data_websocket_endpoint(websocket: WebSocket, symbol: str):
    """Combined WebSocket endpoint that streams historical OHLC data with indicators and live data from Redis."""

    # SECURITY FIX: Validate symbol BEFORE accepting WebSocket connection
    # This prevents accepting connections for invalid/malicious symbols like ".ENV"
    if symbol not in SUPPORTED_SYMBOLS:
        logger.warning(f"SECURITY: Unsupported symbol '{symbol}' requested for combined data WebSocket - rejecting before accept")
        # Don't accept the connection for invalid symbols
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
                            positions = await fetch_positions_from_trading_service()
                            client_state["cached_positions"] = positions
                            client_state["last_positions_update"] = current_time

                            # Send positions update as separate WebSocket message type
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

    async def generate_csv_from_combined_data(symbol: str, indicators: List[str], combined_data: List[Dict], from_ts: int, to_ts: int):
        """Generate CSV file with the exact same data structure sent to client."""
        import os  # Local import for scoping

        if not combined_data:
            logger.info(f"No data to export to CSV for {symbol}")
            return

        # Create filename with symbol, indicators, and timestamp range for easy identification
        indicators_str = "_".join(indicators) if indicators else "no_indicators"
        timestamp = int(time.time())
        csv_filename = f"data/{symbol}_{indicators_str}_{from_ts}_{to_ts}_{timestamp}.csv"

        logger.info(f"📊 GENERATING CSV: {csv_filename}")

        try:
            # Build fieldnames dynamically based on ALL indicators present in data
            fieldnames = ["timestamp", "iso_timestamp", "open", "high", "low", "close", "volume"]
            indicator_columns = set()  # Use set to avoid duplicates

            # Analyze ALL data points to determine available indicators
            # Don't just look at first point - some indicators may only have data later
            if combined_data:
                for data_point in combined_data:
                    if data_point.get("indicators"):
                        for indicator_id, indicator_data in data_point["indicators"].items():
                            if isinstance(indicator_data, dict):
                                for key in indicator_data.keys():
                                    if key != "t":  # timestamps array is not a data column
                                        indicator_columns.add(f"{indicator_id}_{key}")

            # Add unique indicator columns to fieldnames
            fieldnames.extend(sorted(indicator_columns))

            logger.debug(f"CSV fieldnames generated: {fieldnames}")

            with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()

                # Write data rows
                for data_point in combined_data:
                    # Convert Unix timestamp to human-readable ISO format
                    try:
                        iso_timestamp = datetime.fromtimestamp(data_point["time"], timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                    except (ValueError, OSError) as e:
                        logger.warning(f"Failed to convert timestamp {data_point['time']} to ISO format: {e}")
                        iso_timestamp = ""  # Blank if conversion fails

                    row = {
                        "timestamp": data_point["time"],
                        "iso_timestamp": iso_timestamp,
                        "open": data_point["ohlc"]["open"],
                        "high": data_point["ohlc"]["high"],
                        "low": data_point["ohlc"]["low"],
                        "close": data_point["ohlc"]["close"],
                        "volume": data_point["ohlc"]["volume"]
                    }

                    # Add indicator values for this timestamp
                    if data_point.get("indicators"):
                        for indicator_id, indicator_data in data_point["indicators"].items():
                            if isinstance(indicator_data, dict):
                                for key, value in indicator_data.items():
                                    if key != "t":  # Skip timestamps array
                                        row[f"{indicator_id}_{key}"] = value if value is not None else ""  # Use empty string instead of null

                    writer.writerow(row)

            # Log CSV generation summary
            file_size_kb = os.path.getsize(csv_filename) / 1024
            logger.info(f"✅ CSV GENERATED: {csv_filename}")
            logger.info(f"   Size: {file_size_kb:.1f} KB, Rows: {len(combined_data)}")
            logger.info(f"   Columns: {len(fieldnames)} ({', '.join(fieldnames[:6])}{'...' if len(fieldnames) > 6 else ''})")
            logger.info(f"   Time range: {from_ts} to {to_ts} (UTC)")

        except Exception as e:
            logger.error(f"❌ FAILED TO GENERATE CSV {csv_filename}: {e}", exc_info=True)

    async def send_historical_data():
        """Send historical OHLC data with indicators."""
        try:
            logger.info(f"Sending historical data for {active_symbol} with indicators: {client_state['indicators']}")
            logger.info(f"Time range: from_ts={client_state['from_ts']}, to_ts={client_state['to_ts']}, resolution={client_state['resolution']}")

            # Load and send existing shapes/drawings for this symbol
            async def send_existing_shapes():
                """Send existing drawings/shapes for the current symbol to the client."""
                try:
                    # Try to get user email from WebSocket scope if available
                    user_email = None
                    if hasattr(websocket, 'scope') and 'session' in websocket.scope:
                        user_email = websocket.scope['session'].get('email')
                        logger.info(f"WebSocket session email found: {user_email}")
                    else:
                        logger.info("No WebSocket session found, using anonymous access")

                    # Get drawings for this symbol and resolution
                    logger.info(f"Looking for drawings: symbol={active_symbol}, resolution={client_state.get('resolution')}, email={user_email}")

                    # Log the Redis key that will be used
                    from redis_utils import get_drawings_redis_key
                    redis_key = get_drawings_redis_key(active_symbol, None, user_email)
                    logger.info(f"Redis key for drawings: {redis_key}")

                    drawings = await get_drawings(
                        active_symbol,
                        resolution=client_state.get('resolution'),
                        email=user_email
                    )

                    if drawings and len(drawings) > 0:
                        logger.info(f"Sending {len(drawings)} existing drawings for {active_symbol}")
                        drawing_message = {
                            "type": "drawings",
                            "symbol": active_symbol,
                            "data": drawings
                        }
                        # logger.info(f"Sending drawing ({len(drawings)}) message: {drawing_message}")
                        await send_to_client(drawing_message)
                        # logger.info(f"Successfully sent drawings message to client")
                    else:
                        logger.info(f"No existing drawings found for {active_symbol} (email: {user_email}, resolution: {client_state.get('resolution')})")

                except Exception as e:
                    logger.error(f"Error sending existing shapes for {active_symbol}: {e}", exc_info=True)
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")

            await send_existing_shapes()

            # Calculate the TOTAL historical data needed for ZERO null values in the requested range
            # Each indicator needs enough historical data to produce valid values for the ENTIRE requested range
            max_lookback_periods = 0
            indicator_lookbacks = {}

            for indicator_id in client_state["indicators"]:
                config = next((item for item in AVAILABLE_INDICATORS if item["id"] == indicator_id), None)
                if config:
                    current_indicator_lookback = 0
                    if config["id"] == "macd":
                        # MACD calculation: MACD = EMA(close, fast) - EMA(close, slow), Signal = EMA(MACD, signal)
                        # EMA needs ~3x period for stabilization, plus signal period
                        short_period = config["params"]["short_period"]
                        long_period = config["params"]["long_period"]
                        signal_period = config["params"]["signal_period"]
                        ema_warmup = max(short_period, long_period) * 3  # EMA stabilization
                        current_indicator_lookback = ema_warmup + signal_period + 50  # Extra buffer
                    elif config["id"] == "rsi":
                        # RSI calculation: RSI = 100 - (100 / (1 + RS)), RS = EMA(gains, period) / EMA(losses, period)
                        # Needs period * 3 for EMA stabilization + some buffer
                        period = config["params"]["period"]
                        current_indicator_lookback = period * 3 + 50
                    elif config["id"] == "open_interest":
                        current_indicator_lookback = 0  # OI is direct data, no calculation lookback
                    elif config["id"].startswith("stochrsi"):
                        # StochRSI: Precise lookback calculation based on algorithm requirements
                        rsi_period = config["params"]["rsi_period"]
                        stoch_period = config["params"]["stoch_period"]
                        k_period = config["params"]["k_period"]
                        d_period = config["params"]["d_period"]

                        # RSI calculation: EMA(gains, period) / EMA(losses, period)
                        # Each EMA needs ~3*period for proper stabilization
                        rsi_warmup = rsi_period * 3

                        # Stochastic applied to RSI: StOCH[stoch_period](RSI[last K])
                        # For stable Stochastic output, need enough RSI values for reliable %K calculation
                        # %K = Current RSI - Min(RSI[stoch_period]) / Max(RSI[stoch_period]) - Min(RSI[stoch_period])
                        # So we need: rsi_warmup + stoch_period + smoothing periods (k_period + d_period)
                        stoch_warmup = stoch_period + k_period + d_period

                        # Minimal additional buffer for edge cases and stabilization
                        minimal_buffer = max(20, rsi_period)  # At least 20 periods or one RSI cycle

                        current_indicator_lookback = rsi_warmup + stoch_warmup + minimal_buffer
                    elif config["id"] == "jma":
                        # JMA (Jurik Moving Average): Complex adaptive algorithm
                        # Needs length * 4 for proper initialization + phase adaptation
                        length = config["params"]["length"]
                        current_indicator_lookback = length * 4 + 100

                    indicator_lookbacks[indicator_id] = current_indicator_lookback
                    if current_indicator_lookback > max_lookback_periods:
                        max_lookback_periods = current_indicator_lookback

            logger.info(f"🔍 WEBSOCKET LOOKBACK CALCULATION: Max lookback needed: {max_lookback_periods} periods for ZERO null values")
            logger.info(f"🔍 WEBSOCKET INDICATOR LOOKBACKS: {indicator_lookbacks}")

            # Calculate timeframe seconds
            timeframe_secs = get_timeframe_seconds(client_state["resolution"])

            # CRITICAL FIX: Ensure we fetch ENOUGH historical data for the indicators to have valid values
            # MACD and RSI need substantial lookback for proper calculation
            macd_max_lookback = 0
            rsi_max_lookback = 0

            # Calculate actual minimum data requirements for MACD and RSI
            for indicator_id in client_state["indicators"]:
                config = next((item for item in AVAILABLE_INDICATORS if item["id"] == indicator_id), None)
                if config:
                    if config["id"] == "macd":
                        short = config["params"]["short_period"]
                        long = config["params"]["long_period"]
                        signal = config["params"]["signal_period"]
                        # MACD needs at least short + long + signal periods, plus substantial buffer
                        macd_lookback = max(short, long) * 4 + signal + 50  # 4x periods + signal + buffer
                        macd_max_lookback = max(macd_max_lookback, macd_lookback)
                    elif config["id"] == "rsi":
                        period = config["params"]["period"]
                        # RSI needs at least period * 3 for proper stabilization + 14 for SMA + buffer
                        rsi_lookback = period * 4 + 100  # 4x period + buffer
                        rsi_max_lookback = max(rsi_max_lookback, rsi_lookback)

            # Use the maximum lookback across all required indicators
            base_minimum = 150  # Always fetch at least 150 candles for basic calculations
            actual_lookback_needed = max(max_lookback_periods, macd_max_lookback, rsi_max_lookback, base_minimum)

            logger.info("🔍 WEBSOCKET CALCULATION REQUIREMENTS:")
            logger.info(f"  Max StochRSI lookback: {max_lookback_periods} periods")
            logger.info(f"  Max MACD lookback: {macd_max_lookback} periods")
            logger.info(f"  Max RSI lookback: {rsi_max_lookback} periods")
            logger.info(f"  Final dataset size needed: {actual_lookback_needed} periods")

            lookback_candles_needed = actual_lookback_needed

            kline_fetch_start_ts = client_state["from_ts"] - (lookback_candles_needed * timeframe_secs)
            kline_fetch_end_ts = client_state["to_ts"]  # This is the original 'to_ts' from the request

            logger.info(f"🔍 WEBSOCKET DATA FETCH: Will fetch from {kline_fetch_start_ts} to {kline_fetch_end_ts}")
            logger.info(f"🔍 WEBSOCKET DATA FETCH: This provides {lookback_candles_needed} candles before requested range for indicator calculation")

            # Get historical klines from Redis with enlarged range for indicator calculation
            try:
                logger.debug(f"Requesting enlarged klines for {active_symbol}: fetch range {kline_fetch_start_ts} to {kline_fetch_end_ts}")
                klines = await get_cached_klines(active_symbol, client_state["resolution"], kline_fetch_start_ts, kline_fetch_end_ts)
                logger.info(f"✅ REDIS SUCCESS: Retrieved {len(klines) if klines else 0} klines from Redis for {active_symbol} (enlarged range)")
            except Exception as e:
                logger.error(f"❌ REDIS FAILURE: Failed to get cached klines from Redis for {active_symbol}: {e}", exc_info=True)
                logger.error(f"📊 REDIS CONTEXT: symbol={active_symbol}, resolution={client_state['resolution']}, fetch_from={kline_fetch_start_ts}, fetch_to={kline_fetch_end_ts}")
                return

            # Check if we have data for the FULL requested range
            # If not, we need to fetch missing data from Bybit (for non-BTCDOM symbols)
            requested_range_start = client_state["from_ts"]
            requested_range_end = client_state["to_ts"]
            available_data_start = min([k['time'] for k in klines]) if klines else float('inf')
            available_data_end = max([k['time'] for k in klines]) if klines else 0

            data_gap_at_start = requested_range_start < available_data_start
            data_gap_at_end = requested_range_end > available_data_end

            if data_gap_at_start or data_gap_at_end:
                logger.warning(f"⚠️ DATA RANGE GAP DETECTED: Requested {requested_range_start} to {requested_range_end}, Available {available_data_start} to {available_data_end}")
                logger.info(f"🔄 FETCHING MISSING DATA: gap_at_start={data_gap_at_start}, gap_at_end={data_gap_at_end}")

                try:
                    # For BTCDOM, fetch from CoinMarketCap
                    if active_symbol == "BTCDOM":
                        from redis_utils import fetch_btc_dominance, cache_klines

                        gap_start = requested_range_start if data_gap_at_start else available_data_start
                        gap_end = requested_range_end if data_gap_at_end else available_data_end

                        gap_start -= 86400 * 7  # 7 day buffer for CoinGecko
                        gap_end += 86400 * 7

                        logger.info(f"📡 FETCHING BTC DOMINANCE GAP DATA from CoinGecko: {datetime.fromtimestamp(gap_start, timezone.utc)} to {datetime.fromtimestamp(gap_end, timezone.utc)}")

                        fetched_klines = await fetch_btc_dominance(active_symbol, client_state["resolution"], gap_start, gap_end)

                        if fetched_klines and len(fetched_klines) > 0:
                            logger.info(f"✅ COINGECKO GAP SUCCESS: Fetched {len(fetched_klines)} additional klines for {active_symbol}")
                            await cache_klines(active_symbol, client_state["resolution"], fetched_klines)
                            full_klines = await get_cached_klines(active_symbol, client_state["resolution"], kline_fetch_start_ts, kline_fetch_end_ts)
                            if full_klines:
                                klines = full_klines
                                logger.info(f"✅ COMPLETE DATASET: Now have {len(klines)} klines after gap filling")
                            else:
                                merged_klines = klines + fetched_klines
                                klines = sorted(merged_klines, key=lambda x: x['time'])
                                seen = set()
                                unique_klines = []
                                for k in klines:
                                    if k['time'] not in seen:
                                        seen.add(k['time'])
                                        unique_klines.append(k)
                                klines = unique_klines
                                logger.info(f"✅ MANUAL MERGE: Now have {len(klines)} unique klines after gap filling")
                        else:
                            logger.warning(f"❌ COINGECKO GAP FAILURE: Could not fill data gap for {active_symbol}")
                    else:
                        from redis_utils import fetch_klines_from_bybit, cache_klines

                        # For gaps, fetch the missing period plus some buffer
                        gap_start = requested_range_start if data_gap_at_start else available_data_start
                        gap_end = requested_range_end if data_gap_at_end else available_data_end

                        # Add buffer around the gap
                        gap_start -= timeframe_secs * 24  # 1 day buffer before
                        gap_end += timeframe_secs * 24    # 1 day buffer after

                        logger.info(f"📡 FETCHING GAP DATA: {datetime.fromtimestamp(gap_start, timezone.utc)} to {datetime.fromtimestamp(gap_end, timezone.utc)}")

                        fetched_klines = fetch_klines_from_bybit(active_symbol, client_state["resolution"], gap_start, gap_end)

                        if fetched_klines and len(fetched_klines) > 0:
                            logger.info(f"✅ BYBIT GAP SUCCESS: Fetched {len(fetched_klines)} additional klines for {active_symbol}")

                            # Cache the gap data
                            await cache_klines(active_symbol, client_state["resolution"], fetched_klines)
                            logger.info(f"💾 GAP CACHED: Stored {len(fetched_klines)} gap klines in Redis for {active_symbol}")

                            # Re-fetch from cache to get complete dataset
                            full_klines = await get_cached_klines(active_symbol, client_state["resolution"], kline_fetch_start_ts, kline_fetch_end_ts)
                            if full_klines:
                                klines = full_klines
                                logger.info(f"✅ COMPLETE DATASET: Now have {len(klines)} klines after gap filling")
                            else:
                                # Merge with existing klines if re-fetch fails
                                logger.warning("Re-fetch failed, merging manually")
                                merged_klines = klines + fetched_klines
                                klines = sorted(merged_klines, key=lambda x: x['time'])
                                # Remove duplicates
                                seen = set()
                                unique_klines = []
                                for k in klines:
                                    if k['time'] not in seen:
                                        seen.add(k['time'])
                                        unique_klines.append(k)
                                klines = unique_klines
                                logger.info(f"✅ MANUAL MERGE: Now have {len(klines)} unique klines after gap filling")

                        else:
                            logger.warning(f"❌ BYBIT GAP FAILURE: Could not fill data gap for {active_symbol} - will proceed with available data")

                except Exception as e:
                    logger.error(f"❌ GAP FETCH ERROR: Failed to fetch gap data for {active_symbol}: {e}", exc_info=True)
                    logger.info("Proceeding with available cached data...")

            # If STILL no klines found at all, try to fetch the full range from Bybit as last resort
            if not klines or len(klines) == 0:
                logger.warning(f"⚠️ NO HISTORICAL DATA AT ALL: No historical klines found for {active_symbol}")
                logger.info(f"🔄 LAST RESORT: Attempting full range fetch from Bybit API for {active_symbol}")

                try:
                    # Import the Bybit fetch function
                    from redis_utils import fetch_klines_from_bybit, cache_klines

                    # Fetch data from Bybit - use the ORIGINAL requested range, not the expanded fetch range
                    logger.info(f"📡 LAST RESORT FETCH: {active_symbol} {client_state['resolution']} from {client_state['from_ts']} to {client_state['to_ts']}")
                    fetched_klines = fetch_klines_from_bybit(active_symbol, client_state["resolution"], client_state["from_ts"], client_state["to_ts"])

                    if fetched_klines and len(fetched_klines) > 0:
                        logger.info(f"✅ BYBIT LAST RESORT SUCCESS: Fetched {len(fetched_klines)} klines from Bybit for {active_symbol}")

                        # Cache the fetched data
                        await cache_klines(active_symbol, client_state["resolution"], fetched_klines)
                        logger.info(f"💾 CACHED: Stored {len(fetched_klines)} klines in Redis for {active_symbol}")

                        # Use the fetched data
                        klines = fetched_klines
                    else:
                        logger.warning(f"❌ BYBIT LAST RESORT FAILURE: No data available for {active_symbol}")
                        return

                except Exception as e:
                    logger.error(f"❌ BYBIT LAST RESORT FETCH ERROR: Failed to fetch data from Bybit for {active_symbol}: {e}", exc_info=True)
                    return
            else:
                logger.info(f"✅ CACHE HIT: Found {len(klines)} klines in Redis cache for {active_symbol}")

            # Calculate indicators with error handling
            try:
                logger.info(f"Calculating indicators for {active_symbol}: {len(client_state['indicators'])} indicators, {len(klines)} klines")
                indicators_data = await calculate_indicators_for_data(klines, client_state["indicators"])
                logger.info(f"📊 INDICATORS CALCULATION RESULTS: {list(indicators_data.keys()) if indicators_data else 'NONE'}")
                logger.debug(f"Indicators calculation completed: {len(indicators_data) if indicators_data else 0} results")
            except Exception as e:
                logger.error(f"Failed to calculate indicators for {active_symbol}: {e}", exc_info=True)
                logger.error(f"📊 INDICATOR CALCULATION FAILURE CONTEXT:")
                logger.error(f"  Symbol: {active_symbol}")
                logger.error(f"  Indicators requested: {client_state['indicators']}")
                logger.error(f"  Klines count: {len(klines) if klines else 0}")
                logger.error(f"  Resolution: {client_state['resolution']}")
                logger.error(f"  Time range: {client_state['from_ts']} to {client_state['to_ts']}")
                indicators_data = {}

            # Calculate buy signals if we have the required indicators (RSI and StochRSI)
            buy_signals = []
            if indicators_data and any(ind.startswith('rsi') for ind in client_state["indicators"]) and any(ind.startswith('stochrsi') for ind in client_state["indicators"]):
                try:
                    logger.info(f"Calculating buy signals for {active_symbol} historical data")
                    # Recreate df for buy signals calculation since we need the DataFrame
                    # Try to get Open Interest data from cache first
                    '''
                    oi_data = await get_cached_open_interest(active_symbol, client_state["resolution"], client_state["from_ts"], client_state["to_ts"])

                    # If no OI data in cache, try to fetch from Bybit as fallback (except for BTCDOM)
                    if active_symbol != "BTCDOM" and (not oi_data or len(oi_data) == 0):
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
                    '''
                    
                    df_for_signals = _prepare_dataframe(klines, None)
                    if df_for_signals is not None and not df_for_signals.empty:
                        # Add calculated indicator values back to the DataFrame for buy signals calculation
                        # Map indicator result keys back to DataFrame column names
                        for indicator_id, indicator_result in indicators_data.items():
                            if indicator_id == 'rsi' and 'rsi' in indicator_result:
                                # RSI values - need to align with DataFrame timestamps
                                rsi_values = indicator_result['rsi']
                                rsi_sma14_values = indicator_result.get('rsi_sma14', [])
                                timestamps = indicator_result['t']
                                # Create mappings from timestamp to values
                                rsi_map = dict(zip(timestamps, rsi_values))
                                rsi_sma14_map = dict(zip(timestamps, rsi_sma14_values))
                                # Add RSI columns to DataFrame
                                df_for_signals['RSI_14'] = df_for_signals.index.map(lambda ts: rsi_map.get(ts.timestamp(), np.nan))
                                df_for_signals['RSI_14_sma14'] = df_for_signals.index.map(lambda ts: rsi_sma14_map.get(ts.timestamp(), np.nan))

                            elif indicator_id.startswith('stochrsi') and 'stoch_k' in indicator_result and 'stoch_d' in indicator_result:
                                # StochRSI values - need to align with DataFrame timestamps
                                stoch_k_values = indicator_result['stoch_k']
                                stoch_d_values = indicator_result['stoch_d']
                                timestamps = indicator_result['t']
                                # Create mappings from timestamp to values
                                stoch_k_map = dict(zip(timestamps, stoch_k_values))
                                stoch_d_map = dict(zip(timestamps, stoch_d_values))

                                # Map indicator_id to the correct column names that find_buy_signals expects
                                # indicator_id format: 'stochrsi_X_Y' where X is rsi_period, Y is stoch_period
                                if indicator_id == 'stochrsi_9_3':
                                    df_for_signals['STOCHRSIk_9_9_3_3'] = df_for_signals.index.map(lambda ts: stoch_k_map.get(ts.timestamp(), np.nan))
                                    df_for_signals['STOCHRSId_9_9_3_3'] = df_for_signals.index.map(lambda ts: stoch_d_map.get(ts.timestamp(), np.nan))
                                elif indicator_id == 'stochrsi_14_3':
                                    df_for_signals['STOCHRSIk_14_14_3_3'] = df_for_signals.index.map(lambda ts: stoch_k_map.get(ts.timestamp(), np.nan))
                                    df_for_signals['STOCHRSId_14_14_3_3'] = df_for_signals.index.map(lambda ts: stoch_d_map.get(ts.timestamp(), np.nan))
                                elif indicator_id == 'stochrsi_40_4':
                                    df_for_signals['STOCHRSIk_40_40_4_4'] = df_for_signals.index.map(lambda ts: stoch_k_map.get(ts.timestamp(), np.nan))
                                    df_for_signals['STOCHRSId_40_40_4_4'] = df_for_signals.index.map(lambda ts: stoch_d_map.get(ts.timestamp(), np.nan))
                                elif indicator_id == 'stochrsi_60_10':
                                    df_for_signals['STOCHRSIk_10_60_10_10'] = df_for_signals.index.map(lambda ts: stoch_k_map.get(ts.timestamp(), np.nan))
                                    df_for_signals['STOCHRSId_10_60_10_10'] = df_for_signals.index.map(lambda ts: stoch_d_map.get(ts.timestamp(), np.nan))

                                buy_signals = find_buy_signals(df_for_signals)
                                logger.info(f"Found {len(buy_signals)} buy signals for {active_symbol}")
                    else:
                        logger.warning(f"Could not prepare DataFrame for buy signals calculation for {active_symbol}")
                        buy_signals = []
                except Exception as e:
                    logger.error(f"Error calculating buy signals for {active_symbol}: {e}", exc_info=True)
                    buy_signals = []

            # 🔍 VALIDATION: Log availability but DON'T FILTER - return ALL requested data
            # Count how many data points have ALL indicators available in the requested range
            valid_data_range_count = 0

            # Get all klines in the requested range (ALL of them, not just the valid ones)
            all_requested_klines = [kline for kline in klines if client_state['from_ts'] <= kline['time'] <= client_state['to_ts']]
            requested_range_count = len(all_requested_klines)
            logger.info(f"🔍 WEBSOCKET DATA PREPARATION: Requested range {client_state['from_ts']} to {client_state['to_ts']} = {requested_range_count} candles")

            if requested_range_count == 0:
                logger.warning(f"⚠️ NO DATA IN REQUESTED RANGE: No klines found between {client_state['from_ts']} and {client_state['to_ts']}")
                return

            # Calculate how many indicators are fully available in the requested range
            fully_available_indicators = 0
            for indicator_id, indicator_values in indicators_data.items():
                if "t" in indicator_values and indicator_values["t"]:
                    # Count how many points in the requested range have this indicator available (non-null)
                    requested_range_for_indicator = [ts for ts in indicator_values["t"] if client_state['from_ts'] <= ts <= client_state['to_ts']]
                    requested_range_valid_count = len(requested_range_for_indicator)

                    if requested_range_valid_count > 0:
                        # Check the percentage of valid values
                        null_count = 0
                        for ts in requested_range_for_indicator:
                            idx = indicator_values["t"].index(ts)
                            for key, values in indicator_values.items():
                                if key != "t" and idx < len(values) and values[idx] is None:
                                    null_count += 1
                                    break  # Count each timestamp once even if multiple values are null

                        valid_percentage = ((requested_range_valid_count - null_count) / requested_range_valid_count) * 100
                        logger.info(f"🔍 WEBSOCKET AVAILABILITY: {indicator_id} - {requested_range_valid_count - null_count}/{requested_range_valid_count} valid points ({valid_percentage:.1f}%)")

                        if null_count == 0:
                            fully_available_indicators += 1
                    else:
                        logger.warning(f"⚠️ WEBSOCKET AVAILABILITY: {indicator_id} has no data points in requested range")

            logger.info(f"🔍 WEBSOCKET RESULT: {fully_available_indicators}/{len(indicators_data)} indicators are fully available in requested range")
            logger.info("✅ SENDING ALL REQUESTED DATA: Even if some early indicators are null - this is normal chart behavior")

            # Send ALL requested klines (within the requested range), regardless of indicator validity
            combined_data = []
            requested_klines_dict = {k['time']: k for k in all_requested_klines}  # For faster lookup

            # Prepare combined data - include ALL data points in requested range
            logger.info(f"🔍 WEBSOCKET BUILDING DATA: Processing {len(all_requested_klines)} data points in requested range")

            # Create timestamp mapping for faster lookups
            timestamp_map = {}
            for indicator_id, indicator_values in indicators_data.items():
                if "t" in indicator_values:
                    indicator_timestamps = indicator_values["t"]
                    timestamp_map[indicator_id] = dict(zip(indicator_timestamps, range(len(indicator_timestamps))))

            for kline in all_requested_klines:
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

                # Add indicator values for this timestamp - send all OHLC data and populate indicators
                for indicator_id, indicator_values in indicators_data.items():
                    if "t" in indicator_values:
                        # Use pre-built timestamp map for faster lookup
                        if indicator_id in timestamp_map and kline["time"] in timestamp_map[indicator_id]:
                            idx = timestamp_map[indicator_id][kline["time"]]
                            # Verify index is valid for this indicator (check the first available key)
                            first_key = next((k for k in indicator_values.keys() if k != "t"), None)
                            if first_key and idx < len(indicator_values.get(first_key, [])):
                                # Always create indicator object, populating with available values
                                temp_indicator = {}
                                for key, values in indicator_values.items():
                                    if key != "t" and idx < len(values):
                                        value = values[idx]
                                        # Use None for missing values instead of excluding them
                                        temp_indicator[key] = value

                                # Only add indicator if it has the expected data structure and at least timestamps
                                if temp_indicator:
                                    data_point["indicators"][indicator_id] = temp_indicator

                # Always include all candles (both OHLC data and any valid indicators they have)
                combined_data.append(data_point)

            # 📊 GENERATE CSV FILE WITH COMPLETE DATA STRUCTURE
            # await generate_csv_from_combined_data(active_symbol, client_state["indicators"], combined_data, client_state["from_ts"], client_state["to_ts"])

            # Get YouTube videos in the requested time range
            try:
                # Fetch YouTube videos from Redis for the requested time period
                redis_conn = await get_redis_connection()

                # Get all YouTube video IDs and their publish timestamps
                youtube_videos = []
                video_ids = await redis_conn.zrangebyscore(
                    "youtube_videos",
                    min=client_state["from_ts"],
                    max=client_state["to_ts"]
                )

                for video_id in video_ids:  # Return all videos in the requested time range
                    video_key = f"youtube_video:{video_id.decode('utf-8') if isinstance(video_id, bytes) else video_id}"
                    video_data_json = await redis_conn.get(video_key)
                    if video_data_json:
                        try:
                            video_data = json.loads(video_data_json)
                            # Convert published_at to timestamp for filtering
                            published_dt = datetime.fromisoformat(video_data['published_at'].replace('Z', '+00:00'))
                            published_ts = published_dt.timestamp()

                            # Only include videos within the requested range
                            if client_state["from_ts"] <= published_ts <= client_state["to_ts"]:
                                youtube_videos.append(video_data)
                                logger.debug(f"Including YouTube video: {video_data.get('title', 'Unknown')[:50]}...")
                        except (json.JSONDecodeError, KeyError, ValueError) as e:
                            logger.warning(f"Error parsing YouTube video data for {video_id}: {e}")
                            continue

                logger.info(f"🎥 Found {len(youtube_videos)} YouTube videos in requested time range ({client_state['from_ts']} to {client_state['to_ts']})")

                # Send historical data in batches
                batch_size = 100
                total_batches = (len(combined_data) + batch_size - 1) // batch_size
                # logger.info(f"Sending {len(combined_data)} historical data points in {total_batches} batches for {active_symbol}")

                # Log sample of data being sent to verify timestamps
                if combined_data:
                    first_point = combined_data[0]
                    last_point = combined_data[-1]
                    # logger.info(f"📤 SAMPLE DATA POINTS TO CLIENT:")
                    # logger.info(f"  First point: time={first_point['time']} ({datetime.fromtimestamp(first_point['time'], timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')})")
                    # logger.info(f"  Last point: time={last_point['time']} ({datetime.fromtimestamp(last_point['time'], timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')})")
                    # logger.info(f"  Time range in data: {first_point['time']} to {last_point['time']} (seconds)")

                for i in range(0, len(combined_data), batch_size):
                    batch = combined_data[i:i + batch_size]
                    batch_num = i // batch_size + 1
                    # logger.info(f"Sending batch {batch_num}/{total_batches} with {len(batch)} data points")

                    try:
                        await send_to_client({
                            "type": "historical",
                            "symbol": active_symbol,
                            "data": batch
                        })
                        # logger.info(f"Successfully sent batch {batch_num}/{total_batches}")
                    except Exception as e:
                        logger.error(f"Failed to send batch {batch_num}/{total_batches}: {e}")
                        break

                    await asyncio.sleep(0.01)  # Small delay to prevent overwhelming client

                # Send YouTube videos if any were found
                if youtube_videos:
                    logger.info(f"🎥 Sending {len(youtube_videos)} YouTube videos to client for {active_symbol}")

                    # Send YouTube videos in batches to avoid overwhelming client
                    video_batch_size = 5  # Smaller batches for videos
                    for i in range(0, len(youtube_videos), video_batch_size):
                        video_batch = youtube_videos[i:i + video_batch_size]

                        try:
                            await send_to_client({
                                "type": "youtube_videos",
                                "symbol": active_symbol,
                                "videos": video_batch,
                                "batch_index": i // video_batch_size,
                                "total_batches": (len(youtube_videos) + video_batch_size - 1) // video_batch_size
                            })
                            logger.debug(f"📤 Sent batch {i // video_batch_size + 1} of YouTube videos ({len(video_batch)} videos)")
                        except Exception as e:
                            logger.error(f"Failed to send YouTube video batch {i // video_batch_size + 1}: {e}")
                            break

                        await asyncio.sleep(0.05)  # Slightly longer delay for video data

            except Exception as e:
                logger.error(f"Error fetching YouTube videos for {active_symbol}: {e}")
                # Continue without YouTube videos if there's an error

            # Send buy signals if any were found
            if buy_signals:
                logger.info(f"Sending {len(buy_signals)} buy signals for {active_symbol}")
                try:
                    await send_to_client({
                        "type": "buy_signals",
                        "symbol": active_symbol,
                        "data": buy_signals
                    })
                    logger.info(f"Successfully sent {len(buy_signals)} buy signals for {active_symbol}")
                except Exception as e:
                    logger.error(f"Failed to send buy signals for {active_symbol}: {e}")

            # logger.info(f"Completed sending {len(combined_data)} historical data points for {active_symbol}")
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

            # Track last live price update time for periodic updates
            last_live_price_update = 0
            live_price_update_interval = 5  # Send live price update every 5 seconds

            while client_state["live_mode"] and websocket.client_state == WebSocketState.CONNECTED:
                try:
                    current_time = time.time()

                    # Send periodic live price updates (every 5 seconds) for all resolutions
                    if current_time - last_live_price_update >= live_price_update_interval:
                        try:
                            sync_redis = get_sync_redis_connection()
                            live_price_key = f"live:{active_symbol}"
                            price_str = sync_redis.get(live_price_key)

                            if price_str:
                                live_price = float(price_str)
                                # logger.debug(f"✅ Combined WebSocket - Periodic live price update for {active_symbol}: {live_price}")

                                # Send live price update
                                await send_to_client({
                                    "type": "live_price",
                                    "symbol": active_symbol,
                                    "price": live_price,
                                    "timestamp": int(current_time)
                                })

                                last_live_price_update = current_time
                            else:
                                logger.debug(f"⚠️ Combined WebSocket - No live price available for periodic update {active_symbol}")
                        except Exception as e:
                            logger.debug(f"Failed to send periodic live price update for {active_symbol}: {e}")

                    # Read from Redis stream with error handling
                    try:
                        messages = await redis.xreadgroup(
                            group_name, consumer_id, {stream_key: ">"}, count=10, block=1000  # Reduced block time
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

                                        # Get live price from Redis using synchronous connection
                                        live_price = None
                                        try:
                                            sync_redis = get_sync_redis_connection()
                                            live_price_key = f"live:{active_symbol}"
                                            price_str = sync_redis.get(live_price_key)
                                            #logger.debug(f"Combined WebSocket - Redis get result for key '{live_price_key}': {price_str}")
                                            if price_str:
                                                live_price = float(price_str)
                                                # logger.info(f"✅ Combined WebSocket - Retrieved live price from Redis for {active_symbol}: {live_price}")
                                            else:
                                                logger.warning(f"⚠️ Combined WebSocket - No live price found in Redis for {active_symbol} (key: {live_price_key})")
                                        except Exception as e:
                                            logger.error(f"❌ Combined WebSocket - Failed to get live price from Redis for {active_symbol}: {e}", exc_info=True)

                                        # Create live data point with indicators and live price
                                        live_data_point = {
                                            "time": kline_data["time"],
                                            "ohlc": {
                                                "open": kline_data["open"],
                                                "high": kline_data["high"],
                                                "low": kline_data["low"],
                                                "close": kline_data["close"],
                                                "volume": kline_data["vol"]
                                            },
                                            "indicators": current_indicators,
                                            "live_price": live_price  # Add live price from Redis
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
                logger.warning(f"Unknown indicator {indicator_id} requested for {active_symbol}")
                continue

            try:
                params = config["params"]
                calc_id = config["id"]
                logger.info(f"🔍 INDICATOR DEBUG: Indicator {indicator_id} config: calc_id={calc_id}, params={params}")

                if calc_id == "macd":
                    logger.info(f"🔍 INDICATOR DEBUG: Calling calculate_macd for {indicator_id}")
                    result = calculate_macd(df.copy(), **params)
                    logger.info(f"🔍 INDICATOR DEBUG: MACD result type: {type(result)}, is None: {result is None}")
                elif calc_id == "rsi":
                    logger.info(f"🔍 INDICATOR DEBUG: Calling calculate_rsi for {indicator_id}")
                    result = calculate_rsi(df.copy(), **params)
                    logger.info(f"🔍 INDICATOR DEBUG: RSI result type: {type(result)}, is None: {result is None}")
                elif calc_id.startswith("stochrsi"):
                    logger.info(f"🔍 INDICATOR DEBUG: Calling calculate_stoch_rsi for {indicator_id}")
                    # Filter out lookback_period from params as it's only used for data retrieval
                    stoch_params = {k: v for k, v in params.items() if k != "lookback_period"}
                    result = calculate_stoch_rsi(df.copy(), **stoch_params)
                    logger.info(f"🔍 INDICATOR DEBUG: STOCHRSI result type: {type(result)}, is None: {result is None}")
                elif calc_id == "open_interest":
                    logger.info(f"🔍 INDICATOR DEBUG: Calling calculate_open_interest for {indicator_id}")
                    result = calculate_open_interest(df.copy())
                    logger.info(f"🔍 INDICATOR DEBUG: OI result type: {type(result)}, is None: {result is None}")
                elif calc_id == "jma":
                    logger.info(f"🔍 INDICATOR DEBUG: Calling calculate_jma_indicator for {indicator_id}")
                    result = calculate_jma_indicator(df.copy(), **params)
                    logger.info(f"🔍 INDICATOR DEBUG: JMA result type: {type(result)}, is None: {result is None}")
                elif calc_id == "cto_line":
                    logger.info(f"🔍 INDICATOR DEBUG: Calling calculate_cto_line for {indicator_id}")
                    result = calculate_cto_line(df.copy(), **params)
                    logger.info(f"🔍 INDICATOR DEBUG: CTO Line result type: {type(result)}, is None: {result is None}")
                else:
                    logger.warning(f"Unsupported indicator calculation {calc_id} for {active_symbol}")
                    continue

                logger.info(f"🔍 INDICATOR DEBUG: Indicator {indicator_id} calculation result: {result is not None}")
                if result:
                    logger.info(f"🔍 INDICATOR DEBUG: Indicator {indicator_id} result keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}")
                    if "t" in result:
                        logger.info(f"🔍 INDICATOR DEBUG: Indicator {indicator_id} has 't' key with {len(result['t'])} timestamps")
                        indicators_data[indicator_id] = result
                        logger.info(f"🔍 INDICATOR DEBUG: Successfully added {indicator_id} to indicators_data")
                    else:
                        logger.warning(f"Indicator {indicator_id} calculation result missing 't' key for {active_symbol}")
                else:
                    logger.warning(f"Indicator {indicator_id} calculation returned None for {active_symbol}")

            except Exception as e:
                logger.error(f"Error calculating indicator {indicator_id} for {active_symbol}: {e}", exc_info=True)
                import traceback
                logger.error(f"📋 INDICATOR ERROR TRACEBACK:\n{traceback.format_exc()}")

        # 🔍 VALIDATION: Check non-null values for requested time range (WebSocket historical data)
        if df is not None and len(df) > 0:
            logger.info(f"🔍 WEBSOCKET VALIDATION: Checking {len(indicators_data)} indicators for WebSocket historical data")

            validation_results = {}
            total_indicators = len(indicators_data)
            valid_indicators = 0

            for indicator_name, result in indicators_data.items():
                if not isinstance(result, dict) or not result.get('t'):
                    logger.warning(f"⚠️ WEBSOCKET VALIDATION SKIPPED: {indicator_name} - Invalid result format")
                    validation_results[indicator_name] = False
                    continue

                timestamps = result.get('t', [])
                indicator_keys = [k for k in result.keys() if k not in ['t', 's', 'errmsg']]

                # Filter to requested time range only
                requested_range_indices = [i for i, ts in enumerate(timestamps) if client_state["from_ts"] <= ts <= client_state["to_ts"]]
                requested_range_count = len(requested_range_indices)

                if requested_range_count == 0:
                    logger.warning(f"⚠️ WEBSOCKET VALIDATION SKIPPED: {indicator_name} - No data in requested range {client_state['from_ts']} to {client_state['to_ts']}")
                    validation_results[indicator_name] = False
                    continue

                logger.debug(f"🔍 WEBSOCKET VALIDATION: {indicator_name} - Checking {len(indicator_keys)} data series for {requested_range_count} points in range {client_state['from_ts']} to {client_state['to_ts']}")

                is_valid = True
                total_nulls_in_requested_range = 0

                for key in indicator_keys:
                    data_series = result.get(key, [])
                    if not data_series or len(data_series) != len(timestamps):
                        logger.error(f"❌ WEBSOCKET VALIDATION FAILED: {indicator_name} - {key} data length mismatch")
                        is_valid = False
                        continue

                    # Count nulls ONLY in the requested chart range (what user actually sees)
                    nulls_in_requested_range = sum(1 for i in requested_range_indices if data_series[i] is None)
                    total_nulls_in_requested_range += nulls_in_requested_range

                    if nulls_in_requested_range > 0:
                        # For stochrsi indicators, show how many data points are actually needed
                        if indicator_name.startswith('stochrsi'):
                            config = next((item for item in AVAILABLE_INDICATORS if item["id"] == indicator_name), None)
                            if config:
                                rsi_period = config["params"]["rsi_period"]
                                stoch_period = config["params"]["stoch_period"]
                                k_period = config["params"]["k_period"]
                                d_period = config["params"]["d_period"]
                                # Calculate the actual lookback needed (same as above)
                                rsi_warmup = rsi_period * 3
                                stoch_warmup = stoch_period + k_period + d_period
                                min_data_needed = rsi_warmup + stoch_warmup + 50
                                logger.error(f"❌ WEBSOCKET VALIDATION FAILED: {indicator_name} - {key} has {nulls_in_requested_range} nulls in REQUESTED chart range!")
                                logger.error(f"   Requested chart range: {requested_range_count} points have {nulls_in_requested_range} nulls")
                                logger.error(f"   Indicator needs minimum {min_data_needed} data points (RSI warmup: {rsi_warmup}, Stoch warmup: {stoch_warmup}, buffer: 50)")
                                logger.error(f"   Current data window is insufficient for this indicator length")
                            else:
                                logger.error(f"❌ WEBSOCKET VALIDATION FAILED: {indicator_name} - {key} has {nulls_in_requested_range} nulls in REQUESTED chart range!")
                        else:
                            logger.error(f"❌ WEBSOCKET VALIDATION FAILED: {indicator_name} - {key} has {nulls_in_requested_range} nulls in REQUESTED chart range!")
                        is_valid = False
                    else:
                        logger.debug(f"✅ WEBSOCKET VALIDATION: {indicator_name} - {key} has 0 nulls in {requested_range_count} requested points")

                # Log summary for this indicator
                if total_nulls_in_requested_range > 0:
                    logger.error(f"❌ WEBSOCKET VALIDATION FAILED: {indicator_name} - Total nulls in requested chart range: {total_nulls_in_requested_range}/{requested_range_count}")
                else:
                    logger.info(f"✅ WEBSOCKET VALIDATION PASSED: {indicator_name} - All {requested_range_count} points in requested range are non-null")

                validation_results[indicator_name] = is_valid
                if is_valid:
                    valid_indicators += 1

            # Log validation summary
            failed_count = total_indicators - valid_indicators

            logger.info(f"🔍 WEBSOCKET VALIDATION RESULTS: {valid_indicators}/{total_indicators} indicators valid for requested range, {failed_count} failed")

            if failed_count > 0:
                logger.error(f"🚨 CRITICAL WEBSOCKET ISSUE: {failed_count}/{total_indicators} indicators have null values in WebSocket historical data!")
                logger.error("This will cause frontend chart display problems in WebSocket streaming.")
                logger.error(f"WebSocket requested range: {client_state['from_ts']} to {client_state['to_ts']}")
            else:
                logger.info(f"✅ WEBSOCKET SUCCESS: All {total_indicators} indicators have complete data for WebSocket historical range {client_state['from_ts']} to {client_state['to_ts']}")
        else:
            logger.warning("⚠️ WEBSOCKET VALIDATION SKIPPED: No DataFrame available for validation")

        return indicators_data

    try:
        while websocket.client_state == WebSocketState.CONNECTED:
            try:
                # Additional safety check before receiving messages
                if websocket.client_state != WebSocketState.CONNECTED:
                    logger.info(f"WebSocket state changed to {websocket.client_state} for {active_symbol}, breaking message loop")
                    break

                # Receive client messages with error handling
                try:
                    message = await asyncio.wait_for(websocket.receive_json(), timeout=1.0)
                except asyncio.TimeoutError:
                    # No message received, continue with keep-alive
                    pass
                except RuntimeError as e:
                    if "WebSocket is not connected" in str(e) or "Need to call \"accept\" first" in str(e):
                        logger.warning(f"WebSocket connection lost for {active_symbol}: {e}")
                        break
                    else:
                        logger.error(f"RuntimeError receiving WebSocket message for {active_symbol}: {e}", exc_info=True)
                        continue
                except Exception as e:
                    logger.error(f"Failed to receive WebSocket message for {active_symbol}: {e}", exc_info=True)
                    # Check if this is a WebSocketDisconnect with service restart code
                    if isinstance(e, WebSocketDisconnect) and e.code == 1012:
                        logger.warning(f"🚨 CRITICAL: WebSocket disconnect with service restart code (1012) detected for {active_symbol}")
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

                        # Parse timestamps for human-readable logging
                        try:
                            if isinstance(received_from_ts, str) and received_from_ts.endswith('Z'):
                                # ISO string with Z suffix
                                parsed_from = datetime.fromisoformat(received_from_ts.replace('Z', '+00:00'))
                                logger.info(f"  from_ts parsed: {parsed_from.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                            elif isinstance(received_from_ts, (int, float)):
                                # Unix timestamp
                                parsed_from = datetime.fromtimestamp(received_from_ts, timezone.utc)
                                logger.info(f"  from_ts parsed: {parsed_from.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                            else:
                                logger.info(f"  from_ts format: Unable to parse")
                        except Exception as e:
                            logger.warning(f"Failed to parse from_ts for logging: {e}")

                        try:
                            if isinstance(received_to_ts, str) and received_to_ts.endswith('Z'):
                                # ISO string with Z suffix
                                parsed_to = datetime.fromisoformat(received_to_ts.replace('Z', '+00:00'))
                                logger.info(f"  to_ts parsed: {parsed_to.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                            elif isinstance(received_to_ts, (int, float)):
                                # Unix timestamp
                                parsed_to = datetime.fromtimestamp(received_to_ts, timezone.utc)
                                logger.info(f"  to_ts parsed: {parsed_to.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                            else:
                                logger.info(f"  to_ts format: Unable to parse")
                        except Exception as e:
                            logger.warning(f"Failed to parse to_ts for logging: {e}")

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

                            # Update client state in Redis for smart notifications
                            try:
                                redis = await get_redis_connection()

                                # Debug all values before Redis operation
                                logger.debug(f"DEBUG Redis update: active_symbol={active_symbol} (type: {type(active_symbol)})")
                                logger.debug(f"DEBUG Redis update: resolution={client_state.get('resolution')} (type: {type(client_state.get('resolution'))})")
                                logger.debug(f"DEBUG Redis update: from_ts={client_state.get('from_ts')} (type: {type(client_state.get('from_ts'))})")
                                logger.debug(f"DEBUG Redis update: to_ts={client_state.get('to_ts')} (type: {type(client_state.get('to_ts'))})")

                                # Ensure all values are properly converted to strings
                                symbol_str = str(active_symbol) if active_symbol is not None else ""
                                resolution_str = str(client_state["resolution"]) if client_state["resolution"] is not None else "1h"

                                from_ts_val = client_state["from_ts"]
                                to_ts_val = client_state["to_ts"]

                                # Convert timestamps to string safely, handling different types
                                if isinstance(from_ts_val, (int, float)):
                                    from_ts_str = str(int(from_ts_val))
                                elif isinstance(from_ts_val, str):
                                    from_ts_str = from_ts_val
                                else:
                                    from_ts_str = "0"

                                if isinstance(to_ts_val, (int, float)):
                                    to_ts_str = str(int(to_ts_val))
                                elif isinstance(to_ts_val, str):
                                    to_ts_str = to_ts_val
                                else:
                                    to_ts_str = "0"

                                logger.debug(f"DEBUG Redis final values: symbol='{symbol_str}', resolution='{resolution_str}', from_ts='{from_ts_str}', to_ts='{to_ts_str}'")

                                # Use individual key-value pairs instead of dictionary
                                await redis.hset(client_id, "symbol", symbol_str)
                                await redis.hset(client_id, "resolution", resolution_str)
                                await redis.hset(client_id, "from_ts", from_ts_str)
                                await redis.hset(client_id, "to_ts", to_ts_str)
                                await redis.hset(client_id, "last_update", str(time.time()))
                                logger.debug(f"Updated client state in Redis for {client_id}")
                            except Exception as e:
                                logger.error(f"Failed to update client state in Redis for {client_id}: {e}")
                                logger.error(f"Redis update failed with values: symbol={active_symbol} (type: {type(active_symbol)}), resolution={client_state.get('resolution')} (type: {type(client_state.get('resolution'))}), from_ts={client_state.get('from_ts')} (type: {type(client_state.get('from_ts'))}), to_ts={client_state.get('to_ts')} (type: {type(client_state.get('to_ts'))})")

                            # Check if this is a new time range request (panning/zooming) or resolution change
                            old_resolution = message.get("old_resolution")
                            resolution_changed = old_resolution is not None and old_resolution != client_state["resolution"]
                            time_range_changed = (old_from_ts != client_state["from_ts"] or
                                                old_to_ts != client_state["to_ts"])

                            logger.info(f"📊 SERVER TIME RANGE ANALYSIS for {active_symbol}:")
                            logger.info(f"  Old range: from_ts={old_from_ts}, to_ts={old_to_ts}")
                            logger.info(f"  New range: from_ts={client_state['from_ts']}, to_ts={client_state['to_ts']}")
                            logger.info(f"  Time range changed: {time_range_changed}")
                            logger.info(f"  Resolution changed: {resolution_changed} (from {old_resolution} to {client_state['resolution']})")
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
                                # 2. Resolution changed (different data needed), OR
                                # 3. Historical data hasn't been sent yet
                                should_send_historical = (time_range_changed or resolution_changed or not client_state["historical_sent"]) and client_state["from_ts"] and client_state["to_ts"]

                                # logger.info(f"Should send historical data: {should_send_historical}")

                                if should_send_historical:
                                    # logger.info(f"Sending historical data for {active_symbol} - time range changed: {time_range_changed}, historical_sent: {client_state['historical_sent']}")
                                    await send_historical_data()

                                # Always activate live mode regardless of historical data status
                                if not client_state["live_mode"] or resolution_changed or time_range_changed:
                                    client_state["live_mode"] = True
                                    # logger.info(f"✅ LIVE MODE ACTIVATED for {active_symbol} (always active)")

                                    # Restart live streaming task if symbol changed or it doesn't exist/isn't running
                                    if not 'live_task' in locals() or live_task.done():
                                        live_task = asyncio.create_task(stream_live_data())
                                    elif active_symbol != last_active_symbol:
                                        # Cancel current live task and restart for new symbol
                                        live_task.cancel()
                                        try:
                                            await live_task
                                        except asyncio.CancelledError:
                                            pass
                                        live_task = asyncio.create_task(stream_live_data())

                                # Track the last active symbol for comparison
                                last_active_symbol = active_symbol

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

        # Cancel notification task if it exists
        if "notification_task" in locals() and not notification_task.done():
            notification_task.cancel()
            try:
                await notification_task
            except asyncio.CancelledError:
                pass

        # Clean up client data from Redis
        try:
            redis = await get_redis_connection()
            await redis.delete(client_id)
            await redis.delete(notification_stream_key)
            logger.info(f"Cleaned up client data for {client_id}")
        except Exception as e:
            logger.error(f"Failed to clean up client data for {client_id}: {e}")

        if websocket.client_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close()
            except Exception as e:
                logger.error(f"Error closing WebSocket for {active_symbol}: {e}")
