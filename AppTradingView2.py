# AppTradingView2 - Single WS Endpoint Application
# Refactored FastAPI application using a single WebSocket endpoint for all client server communication

import os
import asyncio
import json
import uuid
from datetime import datetime
from urllib.parse import quote_plus

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("Environment variables loaded from .env file")
except ImportError:
    print("⚠️ python-dotenv not installed. Environment variables must be set manually.")
    print("Install with: pip install python-dotenv")

import socket
import uvicorn
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
import tempfile
import io

# Import configuration and utilities
from config import SECRET_KEY, STATIC_DIR, TEMPLATES_DIR, PROJECT_ROOT, SUPPORTED_RANGES, SUPPORTED_RESOLUTIONS, SUPPORTED_SYMBOLS, REDIS_LAST_SELECTED_SYMBOL_KEY
from logging_config import logger
from auth import creds, get_session
from redis_utils import init_redis, get_redis_connection
from background_tasks import fetch_and_publish_klines, fetch_and_aggregate_trades, fill_trade_data_gaps_background_task
from bybit_price_feed import start_bybit_price_feed

# Import background tasks
from background_tasks import monitor_email_alerts

from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
import whisper
import httpx

# Google OAuth imports
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

# Import legacy endpoint handlers for reuse
from endpoints.chart_endpoints import history_endpoint, initial_chart_config
from endpoints.drawing_endpoints import (
    get_drawings_api_endpoint, save_drawing_api_endpoint,
    delete_drawing_api_endpoint, update_drawing_api_endpoint,
    delete_all_drawings_api_endpoint, save_shape_properties_api_endpoint,
    get_shape_properties_api_endpoint
)
from endpoints.ai_endpoints import (
    ai_suggestion_endpoint, get_local_ollama_models_endpoint,
    get_available_indicators_endpoint
)
from endpoints.trading_endpoints import (
    get_agent_trades_endpoint, get_order_history_endpoint,
    get_buy_signals_endpoint
)
from endpoints.utility_endpoints import (
    settings_endpoint, set_last_selected_symbol,
    get_last_selected_symbol, get_live_price
)
from endpoints.indicator_endpoints import indicator_history_endpoint

# Import YouTube endpoints
from endpoints.youtube_endpoints import router as youtube_router

# Import WebSocket helpers
from websocket_handlers import (
    calculate_volume_profile, calculate_trading_sessions,
    fetch_recent_trade_history, stream_klines,
    fetch_MY_recent_trade_history, calculate_indicators_for_data
)
from redis_utils import get_cached_klines
from drawing_manager import save_drawing, delete_drawing, update_drawing, get_drawings, DrawingData, update_drawing_properties


# Lifespan manager for startup and shutdown events
@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    # Clean up old log file BEFORE any logging
    try:
        log_file_path = os.path.join(PROJECT_ROOT, "logs", "trading_view.log")
        if os.path.exists(log_file_path):
            os.remove(log_file_path)
            print("🗑️ Deleted old trading_view.log file")  # Use print instead of logger
    except Exception as e:
        print(f"Could not delete old log file: {e}")  # Use print instead of logger

    logger.info("AppTradingView2 startup...")

    try:
        await init_redis()

        # Store the task in the application state
        logger.info("🔧 STARTING BACKGROUND TASK: Creating fetch_and_publish_klines task...")
        app_instance.state.fetch_klines_task = asyncio.create_task(fetch_and_publish_klines())

        # Start trade aggregator background task
        logger.info("🔧 STARTING BACKGROUND TASK: Creating fetch_and_aggregate_trades task...")
        app_instance.state.trade_aggregator_task = asyncio.create_task(fetch_and_aggregate_trades())

        # Start trade data gap filler background task
        logger.info("🔧 STARTING BACKGROUND TASK: Creating fill_trade_data_gaps_background_task...")
        app_instance.state.trade_gap_filler_task = asyncio.create_task(fill_trade_data_gaps_background_task())

        # Start Bybit price feed task (only if not disabled)
        if os.getenv("DISABLE_BYBIT_PRICE_FEED", "false").lower() != "true":
            logger.info("🔧 STARTING BACKGROUND TASK: Creating Bybit price feed task...")
            app_instance.state.price_feed_task = await start_bybit_price_feed()
        else:
            logger.info("🚫 Bybit price feed disabled via DISABLE_BYBIT_PRICE_FEED environment variable")
            app_instance.state.price_feed_task = None

        # Start email alert monitoring service
        logger.info("🔧 STARTING EMAIL ALERT MONITORING TASK...")
        app_instance.state.email_alert_task = asyncio.create_task(monitor_email_alerts())
        logger.info("✅ EMAIL ALERT MONITORING TASK started")

        # Preload Whisper model for audio transcription
        try:
            logger.info("🔧 PRELOADING WHISPER MODEL: Loading Whisper base model for audio transcription...")
            import torch
            # Force CPU usage and disable CUDA
            original_cuda_check = torch.cuda.is_available
            torch.cuda.is_available = lambda: False
            # Clear any cached models
            if hasattr(whisper, '_models'):
                whisper._models.clear()
            # Load model
            logger.info("Loading Whisper base model...")
            app_instance.state.whisper_model = whisper.load_model("base", device="cpu")
            logger.info("✅ WHISPER MODEL LOADED: Whisper base model successfully loaded and cached")
            # Restore original CUDA check
            torch.cuda.is_available = original_cuda_check
        except Exception as e:
            logger.error(f"❌ FAILED TO LOAD WHISPER MODEL: {e}", exc_info=True)
            app_instance.state.whisper_model = None

    except Exception as e:
        logger.error(f"Failed to initialize components: {e}", exc_info=True)
        app_instance.state.fetch_klines_task = None
        app_instance.state.trade_aggregator_task = None
        app_instance.state.trade_gap_filler_task = None
        app_instance.state.price_feed_task = None
        app_instance.state.email_alert_task = None
        app_instance.state.whisper_model = None
    yield
    logger.info("AppTradingView2 shutdown...")

    # Cleanup tasks (same as original)
    for task_name in ['trade_aggregator_task', 'trade_gap_filler_task', 'fetch_klines_task']:
        task = getattr(app_instance.state, task_name, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.info(f"✅ TASK CANCELLED: {task_name}")

    price_feed_task = getattr(app_instance.state, 'price_feed_task', None)
    if price_feed_task:
        price_feed_task.cancel()
        try:
            await price_feed_task
        except asyncio.CancelledError:
            logger.info("Bybit price feed task successfully cancelled.")

    email_alert_task = getattr(app_instance.state, 'email_alert_task', None)
    if email_alert_task:
        email_alert_task.cancel()
        try:
            await email_alert_task
        except asyncio.CancelledError:
            logger.info("Email alert monitoring task successfully cancelled.")


# Create FastAPI app
app = FastAPI(lifespan=lifespan, title="AppTradingView2", description="Single WebSocket endpoint trading application")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Add rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://crypto.zhivko.eu", "http://192.168.1.52:5000", "http://localhost:5000", "http://127.0.0.1:5000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files and templates
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Cache control middleware
@app.middleware("http")
async def add_no_cache_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    if os.getenv("FASTAPI_DEBUG", "False").lower() == "true" or app.extra.get("debug_mode", False):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "-1"
    return response

# Single unified WebSocket endpoint for all client-server communication
@app.websocket("/ws")
async def unified_websocket_endpoint(websocket: WebSocket):
    """Single WebSocket endpoint handling all client-server communication"""
    await websocket.accept()
    logger.info(f"Unified WebSocket connection established for client")

    client_id = str(uuid.uuid4())

    # Client state for live streaming
    client_state = {
        "current_symbol": None,
        "live_stream_task": None,
        "last_sent_live_price": None,
        "last_sent_timestamp": 0.0,
        "stream_delta_seconds": 1  # Default, will be updated from settings
    }

    async def send_live_update(live_price: float, symbol: str):
        """Send live price update to client if price changed"""
        try:
            current_time = time.time()

            # Check if we should send based on throttling
            if client_state["stream_delta_seconds"] == 0 or (current_time - client_state["last_sent_timestamp"]) >= client_state["stream_delta_seconds"]:

                # Only send if price actually changed
                if live_price != client_state.get("last_sent_live_price"):
                    live_data = {
                        "type": "live",
                        "symbol": symbol,
                        "data": {
                            "live_price": live_price,
                            "time": int(current_time)
                        }
                    }
                    await websocket.send_json(live_data)
                    client_state["last_sent_timestamp"] = current_time
                    client_state["last_sent_live_price"] = live_price
                    # logger.debug(f"📤 Sent live price update for {symbol}: {live_price}")

        except Exception as e:
            if websocket.client_state == WebSocketState.CONNECTED:
                logger.error(f"Error sending live price update for {symbol}: {e}")

    async def start_live_streaming(symbol: str):
        """Start live price streaming for the given symbol"""
        # Cancel existing task if symbol changed
        if client_state["live_stream_task"] is not None:
            if not client_state["live_stream_task"].done():
                client_state["live_stream_task"].cancel()
                try:
                    await client_state["live_stream_task"]
                except asyncio.CancelledError:
                    pass

        client_state["current_symbol"] = symbol

        async def live_stream_worker():
            """Continuously streams live price updates from Redis"""
            logger.info(f"Started live streaming task for {symbol} on client {client_id}")

            # Send initial live price if available
            try:
                redis_conn = await get_redis_connection()
                live_price_key = f"live:{symbol}"
                price_str = await redis_conn.get(live_price_key)
                if price_str:
                    live_price = float(price_str)
                    await send_live_update(live_price, symbol)
                    logger.info(f"Sent initial live price for {symbol}: {live_price}")
            except Exception as e:
                logger.warning(f"Failed to send initial live price for {symbol}: {e}")

            while websocket.client_state == WebSocketState.CONNECTED and client_state["current_symbol"] == symbol:
                try:
                    # Get updated stream delta from settings periodically
                    redis_conn = await get_redis_connection()
                    session = websocket.scope.get('session', {})
                    email = session.get('email')
                    if email:
                        settings_key = f"settings:{email}:{symbol}"
                        settings_json = await redis_conn.get(settings_key)
                        if settings_json:
                            symbol_settings = json.loads(settings_json)
                            new_delta = int(symbol_settings.get('streamDeltaTime', 1))
                            client_state["stream_delta_seconds"] = new_delta

                    # Get live price from Redis
                    live_price_key = f"live:{symbol}"
                    price_str = await redis_conn.get(live_price_key)
                    if price_str:
                        live_price = float(price_str)
                        await send_live_update(live_price, symbol)

                    # Wait before checking again
                    await asyncio.sleep(0.5)

                except Exception as e:
                    logger.error(f"Error in live streaming worker for {symbol}: {e}")
                    break

            logger.info(f"Live streaming task ended for {symbol} on client {client_id}")

        client_state["live_stream_task"] = asyncio.create_task(live_stream_worker())

    try:
        while True:
            try:
                # Receive message from client
                raw_message = await websocket.receive_json()
                logger.debug(f"Message received from client: {raw_message}")
                logger.debug(f"Received WS message: {raw_message.get('type')}")

                # Process the message
                response = await handle_websocket_message(raw_message, websocket)

                # Check if this is a config message that might change the symbol
                message_type = raw_message.get('type')
                if message_type == "config" and raw_message.get('data'):
                    config_symbol = raw_message['data'].get("symbol")
                    if config_symbol and config_symbol != client_state.get("current_symbol"):
                        logger.info(f"Client {client_id} switching to symbol {config_symbol} - starting live streaming")
                        await start_live_streaming(config_symbol)
                elif message_type == "init" and raw_message.get('data'):
                    # Also handle init messages that might specify a symbol
                    init_symbol = raw_message['data'].get('symbol')
                    if init_symbol and init_symbol != client_state.get("current_symbol"):
                        logger.info(f"Client {client_id} initializing with symbol {init_symbol} - starting live streaming")
                        await start_live_streaming(init_symbol)

                # Send response back to client
                if response:
                    await websocket.send_json(response)

            except WebSocketDisconnect:
                logger.info(f"WebSocket client {client_id} disconnected")
                break
            except json.JSONDecodeError:
                logger.warn(f"Invalid JSON received from client {client_id}")
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON format",
                    "request_id": None
                })
            except Exception as e:
                logger.error(f"Error processing WebSocket message for client {client_id}: {e}")
                try:
                    await websocket.send_json({
                        "type": "error",
                        "message": str(e),
                        "request_id": raw_message.get('request_id') if 'raw_message' in locals() else None
                    })
                except Exception:
                    break  # Connection probably closed

    except Exception as e:
        logger.error(f"Fatal error in unified WebSocket endpoint: {e}")
    finally:
        # Clean up live streaming task
        if client_state.get("live_stream_task") is not None:
            client_state["live_stream_task"].cancel()
            try:
                await client_state["live_stream_task"]
            except asyncio.CancelledError:
                pass

        logger.info(f"Cleaned up WebSocket connection for client {client_id}")


async def handle_websocket_message(message: dict, websocket: WebSocket) -> dict:
    """
    Handle incoming WebSocket messages and route them to appropriate handlers.
    Returns a response message dict that will be sent back to the client.
    """
    message_type = message.get('type')
    action = message.get('action')
    request_id = message.get('request_id')

    logger.info(f"WS message:\n" + str(message))

    try:
        # Handle ping messages
        if message_type == "ping":
            return {
                "type": "pong",
                "request_id": request_id,
                "timestamp": int(datetime.now().timestamp() * 1000)
            }

        # Handle request messages
        if message_type == "request":
            return await handle_request_action(action, message.get('data', {}), websocket, request_id)

        # Handle initialization messages
        if message_type == "init":
            return await handle_init_message(message.get('data', {}), websocket, request_id)

        elif message_type == "history":
            return await handle_history_message(message.get('data', {}), websocket, request_id)

        elif message_type == "trade_history":
            return await handle_trade_history_message(message.get('data', {}), websocket, request_id)

        elif message_type in ["config"]:
            return await handle_config_message(message.get('data', {}), websocket, request_id)

        elif message_type == "shape":
            return await handle_shape_message(message.get('data', {}), websocket, request_id, message.get('action'))

        elif message_type == "get_volume_profile":
            return await handle_get_volume_profile_direct(message, websocket, request_id)

        # Handle unknown message types
        logger.warn(f"Unknown WS message type: {message_type}")
        return {
            "type": "error",
            "message": f"Unknown message type: {message_type}",
            "request_id": request_id
        }

    except Exception as e:
        logger.error(f"Error handling WS message: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_config_message(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle initialization/config message - get data from WebSocket session"""
    session = websocket.scope.get('session', {})

    # Get authentication info from session or config data
    authenticated = session.get('authenticated', False)
    email = data.get('email') or session.get('email')

    active_symbol = data.get("symbol", "BTCUSDT")
    logger.info(f"🔧 Processing config message for symbol {active_symbol}")

    # Parse data from request
    indicators = data.get("active_indicators", [])
    resolution = data.get("resolution", "1h")
    min_value_percentage = data.get("minValuePercentage", 0)

    # Convert timestamp values from xAxisMin/xAxisMax (milliseconds) to seconds
    from_ts_val = data.get("xAxisMin")
    to_ts_val = data.get("xAxisMax")
    logger.debug(f"Raw timestamps: xAxisMin={from_ts_val}, xAxisMax={to_ts_val}")

    # Convert to human readable format for logging
    try:
        if from_ts_val is not None:
            from_ts_readable = datetime.fromtimestamp(from_ts_val / 1000 if from_ts_val > 1e12 else from_ts_val).strftime('%Y-%m-%d %H:%M:%S UTC')
        else:
            from_ts_readable = "None"
        if to_ts_val is not None:
            to_ts_readable = datetime.fromtimestamp(to_ts_val / 1000 if to_ts_val > 1e12 else to_ts_val).strftime('%Y-%m-%d %H:%M:%S UTC')
        else:
            to_ts_readable = "None"
        logger.info(f"Human readable timestamps: xAxisMin={from_ts_readable}, xAxisMax={to_ts_readable}")
    except Exception as e:
        logger.warning(f"Error converting timestamps to readable format: {e}")

    # Convert from_ts
    from_ts = None
    if isinstance(from_ts_val, (int, float)):
        # xAxisMin/xAxisMax are in milliseconds, convert to seconds
        if from_ts_val > 1e12:  # > 1 trillion, likely milliseconds
            from_ts = int(from_ts_val / 1000)
        else:
            from_ts = int(from_ts_val)

    # Convert to_ts
    to_ts = None
    if isinstance(to_ts_val, (int, float)):
        # xAxisMax is in milliseconds, convert to seconds
        if to_ts_val > 1e12:  # > 1 trillion, likely milliseconds
            to_ts = int(to_ts_val / 1000)
        else:
            to_ts = int(to_ts_val)

    logger.info(f"Client initialization: indicators={indicators}, resolution={resolution}, from_ts={from_ts}, to_ts={to_ts}")

    # Update config timestamps if provided in the message
    if from_ts is not None:
        config_from_ts = from_ts
    if to_ts is not None:
        config_to_ts = to_ts

    # Load settings from Redis for stream delta
    stream_delta_seconds = 1  # Default
    try:
        if email:
            redis_conn = await get_redis_connection()
            settings_key = f"settings:{email}:{active_symbol}"
            settings_json = await redis_conn.get(settings_key)
            logger.info(f"DEBUG CONFIG: Redis settings key '{settings_key}' - data exists: {settings_json is not None}")
            if settings_json:
                symbol_settings = json.loads(settings_json)
                stream_delta_seconds = int(symbol_settings.get('streamDeltaTime', 1))
                logger.info(f"Updated stream delta from settings: {stream_delta_seconds} seconds")
    except Exception as e:
        logger.error(f"Error loading settings for {active_symbol}: {e}")

    # Get the last selected symbol from Redis for config.symbol
    config_symbol = active_symbol  # Default fallback
    config_trade_value_filter = 0  # Default
    config_from_ts = None
    config_to_ts = None
    config_active_indicators = []
    try:
        redis_conn = await get_redis_connection()
        if email:
            last_selected_symbol_key = f"user:{email}:{REDIS_LAST_SELECTED_SYMBOL_KEY}"
            last_symbol = await redis_conn.get(last_selected_symbol_key)
            if last_symbol and last_symbol in SUPPORTED_SYMBOLS:
                config_symbol = last_symbol
                logger.debug(f"Using last selected symbol from Redis: {config_symbol}")
            else:
                logger.debug(f"No last selected symbol found in Redis, using URL symbol: {active_symbol}")

            # Also get config values from Redis settings
            settings_key = f"settings:{email}:{config_symbol}"
            settings_json = await redis_conn.get(settings_key)
            if settings_json:
                symbol_settings = json.loads(settings_json)
                config_trade_value_filter = symbol_settings.get('minValueFilter', 0)
                config_indicators = symbol_settings.get('active_indicators', [])

                # Convert axis timestamps from milliseconds to seconds if needed
                x_axis_min = symbol_settings.get('xAxisMin')
                x_axis_max = symbol_settings.get('xAxisMax')

                if x_axis_min is not None:
                    # Convert to seconds if stored as milliseconds
                    if x_axis_min > 1e12:  # > 1 trillion, likely milliseconds
                        config_from_ts = int(x_axis_min / 1000)
                    else:
                        config_from_ts = int(x_axis_min)

                if x_axis_max is not None:
                    # Convert to seconds if stored as milliseconds
                    if x_axis_max > 1e12:  # > 1 trillion, likely milliseconds
                        config_to_ts = int(x_axis_max / 1000)
                    else:
                        config_to_ts = int(x_axis_max)

                logger.debug(f"Config from Redis - trade_value_filter: {config_trade_value_filter}, from_ts: {config_from_ts}, to_ts: {config_to_ts}, indicators: {config_indicators}")

    except Exception as redis_e:
        logger.warning(f"Error fetching config data from Redis: {redis_e}, using defaults")

    # Save the updated settings to Redis
    try:
        if email:
            redis_conn = await get_redis_connection()
            settings_key = f"settings:{email}:{active_symbol}"

            # Prepare settings data from the config message
            settings_data = {
                'resolution': data.get('resolution', '1h'),
                'range': data.get('range'),
                'xAxisMin': data.get('xAxisMin'),
                'xAxisMax': data.get('xAxisMax'),
                'yAxisMin': data.get('yAxisMin'),
                'yAxisMax': data.get('yAxisMax'),
                'replayFrom': data.get('replayFrom', ''),
                'replayTo': data.get('replayTo', ''),
                'replaySpeed': data.get('replaySpeed', '1'),
                'useLocalOllama': data.get('useLocalOllama', False),
                'localOllamaModelName': data.get('localOllamaModelName', ''),
                'active_indicators': data.get('active_indicators', []),
                'liveDataEnabled': data.get('liveDataEnabled', True),
                'showAgentTrades': data.get('showAgentTrades', False),
                'streamDeltaTime': data.get('streamDeltaTime', 0),
                'last_selected_symbol': data.get('last_selected_symbol', active_symbol),
                'minValueFilter': data.get('minValueFilter', 0)
            }

            settings_json = json.dumps(settings_data)
            await redis_conn.set(settings_key, settings_json)
            logger.info(f"Saved settings for {email}:{active_symbol} from config message")
    except Exception as e:
        logger.error(f"Error saving settings from config message: {e}")

    # Fetch historical data like in history_success
    klines = await get_cached_klines(config_symbol, resolution, config_from_ts, config_to_ts)
    logger.info(f"Fetched {len(klines) if klines else 0} klines for config")

    # Calculate indicators
    indicators_data = await calculate_indicators_for_data(klines, config_indicators)
    logger.info(f"Calculated indicators for config: {list(indicators_data.keys()) if indicators_data else 'none'}")

    # Fetch trades
    trades = await fetch_recent_trade_history(config_symbol, config_from_ts, config_to_ts)
    logger.info(f"CONFIG: Fetched {len(trades) if trades else 0} trades for symbol {config_symbol}, from_ts={config_from_ts}, to_ts={config_to_ts}")

    if trades and len(trades) > 0:
        logger.info(f"HISTORY: First trade sample: {json.dumps(trades[0])}")
    if trades and len(trades) > 0 and min_value_percentage > 0:
        # Calculate max trade value for filtering
        trade_values = [trade['price'] * trade['amount'] for trade in trades if 'price' in trade and 'amount' in trade]
        if trade_values:
            max_trade_value = max(trade_values)
            min_value = min_value_percentage * max_trade_value
            trades = [trade for trade in trades if (trade.get('price', 0) * trade.get('amount', 0)) >= min_value]
            logger.info(f"HISTORY: Filtered trades: {len(trades)} remain after filtering with {min_value_percentage*100}% min value")

    # Fetch drawings
    drawings = await get_drawings(config_symbol, None, resolution, email)
    logger.info(f"Fetched {len(drawings) if drawings else 0} drawings for config")

    # Calculate volume profile for rectangle drawings if we have a time range
    if drawings and config_from_ts is not None and config_to_ts is not None:
        logger.info(f"Processing {len(drawings)} drawings for volume profile calculation in config")
        for drawing in drawings:
            drawing_id = drawing.get('id')
            drawing_type = drawing.get('type')
            logger.info(f"Processing drawing {drawing_id}, type: {drawing_type}")
            if drawing_type == 'rect':
                start_time_val = drawing.get('start_time')
                end_time_val = drawing.get('end_time')
                start_price = drawing.get('start_price')
                end_price = drawing.get('end_price')
                logger.info(f"Rectangle {drawing_id}: start_time={start_time_val}, end_time={end_time_val}, start_price={start_price}, end_price={end_price}")
                if all([start_time_val, end_time_val, start_price is not None, end_price is not None]):
                    # Convert timestamps from milliseconds to seconds if needed
                    if start_time_val > 1e12:  # > 1 trillion, likely milliseconds
                        start_time = int(start_time_val / 1000)
                        logger.info(f"Converted start_time from ms to s: {start_time}")
                    else:
                        start_time = int(start_time_val)
                    if end_time_val > 1e12:  # > 1 trillion, likely milliseconds
                        end_time = int(end_time_val / 1000)
                        logger.info(f"Converted end_time from ms to s: {end_time}")
                    else:
                        end_time = int(end_time_val)

                    logger.info(f"Rectangle {drawing_id} time range: {start_time} to {end_time}")

                    price_min = min(float(start_price), float(end_price))
                    price_max = max(float(start_price), float(end_price))
                    logger.info(f"Rectangle {drawing_id} price range: {price_min} to {price_max}")

                    # Only calculate volume profile if rectangle time range intersects with config time range
                    intersects = start_time <= config_to_ts and end_time >= config_from_ts
                    logger.info(f"Rectangle {drawing_id} intersects with config range ({config_from_ts} to {config_to_ts}): {intersects}")
                    if intersects:
                        # Fetch klines for rectangle time range
                        rect_klines = await get_cached_klines(config_symbol, resolution, start_time, end_time)
                        logger.info(f"Fetched {len(rect_klines) if rect_klines else 0} klines for rectangle {drawing_id}")
                        if rect_klines:
                            # Filter klines within price range
                            filtered_klines = [
                                k for k in rect_klines
                                if k.get('high', 0) >= price_min and k.get('low', 0) <= price_max
                            ]
                            logger.info(f"Filtered to {len(filtered_klines)} klines within price range for rectangle {drawing_id}")
                            if filtered_klines:
                                volume_profile_data = calculate_volume_profile(filtered_klines)
                                drawing['volume_profile'] = volume_profile_data
                                logger.info(f"Added volume profile to rectangle {drawing_id} with {len(volume_profile_data.get('volume_profile', []))} levels")
                            else:
                                logger.info(f"No klines in price range for rectangle {drawing_id}")
                        else:
                            logger.info(f"No klines for rectangle {drawing_id} time range")
                else:
                    logger.info(f"Incomplete rectangle data for drawing {drawing_id}")
            else:
                logger.info(f"Skipping non-rectangle drawing {drawing_id}, type: {drawing_type}")

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

    # Return configuration success response
    return {
        "type": "config_success",
        "symbol": config_symbol,
        "email": email,
        "data": {
            "ohlcv": combined_data,
            "trades": (trades or [])[:10000],
            "active_indicators": list(indicators_data.keys()),
            "drawings": drawings or []
        },
        "timestamp": int(time.time()),
        "request_id": request_id
    }
    

async def handle_init_message(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle initialization/setup messages - includes settings delivery"""
    try:
        # Get session data from WebSocket
        session = websocket.scope.get('session', {})

        # Use init data from request (not storing in session since we're stateless)
        symbol = data.get('symbol', 'BTCUSDT')
        indicators = data.get('indicators', [])
        from_ts = data.get('from_ts')
        to_ts = data.get('to_ts')

        logger.info(f"Client initialized: symbol={symbol}, authenticated={bool(session.get('email'))}")

        # Load user config from Redis
        config_data = {}
        last_selected_symbol = symbol  # Default fallback
        try:
            redis = await get_redis_connection()
            email = session.get('email')
            if email:
                # Get last selected symbol from global user key
                last_selected_symbol_key = f"user:{email}:{REDIS_LAST_SELECTED_SYMBOL_KEY}"
                last_symbol = await redis.get(last_selected_symbol_key)
                if last_symbol and last_symbol in SUPPORTED_SYMBOLS:
                    last_selected_symbol = last_symbol
                    logger.debug(f"Using last selected symbol from Redis: {last_selected_symbol}")
                else:
                    logger.debug(f"No last selected symbol found in Redis, using init symbol: {symbol}")

                # Load symbol-specific config
                if symbol:
                    config_key = f"settings:{email}:{symbol}"
                    config_json = await redis.get(config_key)
                    if config_json:
                        config_data = json.loads(config_json)
                        logger.debug(f"Loaded config for {email}:{symbol} from Redis: {config_data}")
                    else:
                        logger.info(f"No config found in Redis for {email}:{symbol}, using empty config")
                        config_data = {}
        except Exception as config_error:
            logger.error(f"Error loading config for {session.get('email')}:{symbol}: {config_error}")
            config_data = {}

        # Extract config values from config_data or use defaults
        config_from_ts = config_data.get('xAxisMin') if config_data else None
        config_to_ts = config_data.get('xAxisMax') if config_data else None
        config_trade_value_filter = config_data.get('minValueFilter', 0) if config_data else 0
        config_indicators = config_data.get('active_indicators', []) if config_data else []

        # Convert timestamps from milliseconds to seconds if needed
        if config_from_ts is not None and config_from_ts > 1e12:  # > 1 trillion, likely milliseconds
            config_from_ts = int(config_from_ts / 1000)
        if config_to_ts is not None and config_to_ts > 1e12:  # > 1 trillion, likely milliseconds
            config_to_ts = int(config_to_ts / 1000)

        # Build the complete config object with all required fields and defaults
        config_obj = {
            "symbol": symbol,
            "resolution": config_data.get('resolution', '1h'), 
            "range": config_data.get('range', '24h'),
            "xAxisMin": config_data.get('xAxisMin'),
            "xAxisMax": config_data.get('xAxisMax'),
            "yAxisMin": config_data.get('yAxisMin'),
            "yAxisMax": config_data.get('yAxisMax'),
            "replayFrom": config_data.get('replayFrom', ''),
            "replayTo": config_data.get('replayTo', ''),
            "replaySpeed": config_data.get('replaySpeed', '1'),
            "useLocalOllama": config_data.get('useLocalOllama', False),
            "localOllamaModelName": config_data.get('localOllamaModelName', ''),
            "active_indicators": config_data.get('active_indicators', []),
            "liveDataEnabled": config_data.get('liveDataEnabled', True),
            "showAgentTrades": config_data.get('showAgentTrades', False),
            "streamDeltaTime": config_data.get('streamDeltaTime', 0),
            "last_selected_symbol": last_selected_symbol,
            "minValueFilter": config_data.get('minValueFilter', 0),
            "email": session.get('email')
        }

        return {
            "type": "init_success",
            "data": {
                "authenticated": bool(session.get('email')),
                "config": config_obj,
                "symbols": SUPPORTED_SYMBOLS
            },
            "request_id": request_id
        }

    except Exception as e:
        logger.error(f"Error handling init message: {e}")
        return {
            "type": "error",
            "message": f"Initialization failed: {str(e)}",
            "request_id": request_id
        }


async def handle_request_action(action: str, data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Route request actions to appropriate handlers"""
    session = websocket.scope.get('session', {})


    # Drawing actions
    if action == "get_drawings":
        return await handle_get_drawings(data, websocket, request_id)
    elif action == "save_drawing":
        return await handle_save_drawing(data, websocket, request_id)
    elif action == "update_drawing":
        return await handle_update_drawing(data, websocket, request_id)
    elif action == "delete_drawing":
        return await handle_delete_drawing(data, websocket, request_id)
    elif action == "delete_all_drawings":
        return await handle_delete_all_drawings(data, websocket, request_id)

    # AI actions
    elif action == "ai_suggestion":
        return await handle_ai_suggestion(data, websocket, request_id)
    elif action == "get_local_ollama_models":
        return await handle_get_local_ollama_models(data, websocket, request_id)
    elif action == "get_available_indicators":
        return await handle_get_available_indicators(data, websocket, request_id)

    # Trading actions
    elif action == "get_agent_trades":
        return await handle_get_agent_trades(data, websocket, request_id)
    elif action == "get_order_history":
        return await handle_get_order_history(data, websocket, request_id)
    elif action == "get_buy_signals":
        return await handle_get_buy_signals(data, websocket, request_id)

    # Utility actions
    elif action == "get_settings":
        return await handle_get_settings(data, websocket, request_id)
    elif action == "set_settings":
        return await handle_set_settings(data, websocket, request_id)
    elif action == "set_last_symbol":
        return await handle_set_last_symbol(data, websocket, request_id)
    elif action == "get_last_symbol":
        return await handle_get_last_symbol(data, websocket, request_id)
    elif action == "get_live_price":
        return await handle_get_live_price(data, websocket, request_id)

    # Data actions
    elif action == "get_history":
        return await handle_get_history(data, websocket, request_id)
    elif action == "get_initial_chart_config":
        return await handle_get_initial_chart_config(data, websocket, request_id)
    elif action == "get_symbols":
        return await handle_get_symbols(data, websocket, request_id)
    elif action == "get_symbols_list":
        return await handle_get_symbols_list(data, websocket, request_id)
    elif action == "get_trade_history":
        return await handle_get_trade_history(data, websocket, request_id)

    # Volume profile and analysis
    elif action == "get_volume_profile":
        return await handle_get_volume_profile(data, websocket, request_id)
    elif action == "get_trading_sessions":
        return await handle_get_trading_sessions(data, websocket, request_id)

    # Auth and user actions
    elif action == "authenticate":
        return await handle_authenticate(data, websocket, request_id)

    else:
        logger.warn(f"Unknown WS request action: {action}")
        return {
            "type": "error",
            "message": f"Unknown action: {action}",
            "request_id": request_id
        }


# Handler functions for each action type

async def handle_get_drawings(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle get_drawings request"""
    try:
        # Get email from WebSocket session
        session = websocket.scope.get('session', {})
        email = session.get('email')

        symbol = data.get('symbol', 'BTCUSDT')  # Default fallback
        resolution = data.get('resolution', '1h')  # Default fallback

        drawings = await get_drawings(symbol, None, resolution, email)

        return {
            "type": "response",
            "action": "get_drawings",
            "success": True,
            "data": {"drawings": drawings},
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_get_drawings: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_save_drawing(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle save_drawing request"""
    session = websocket.scope.get('session', {})

    try:
        # Reuse existing endpoint logic
        from fastapi import Request as FastAPIRequest
        fake_request = FastAPIRequest(scope={"type": "http", "session": {}})

        # Call the existing endpoint logic
        result = await save_drawing_api_endpoint(
            symbol=data.get('symbol'),
            drawing_data=data,
            request=fake_request
        )

        return {
            "type": "response",
            "action": "save_drawing",
            "success": result.status_code == 200,
            "data": result.body.decode('utf-8') if hasattr(result, 'body') else str(result),
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_save_drawing: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_update_drawing(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle update_drawing request"""
    session = websocket.scope.get('session', {})

    try:
        from fastapi import Request as FastAPIRequest
        fake_request = FastAPIRequest(scope={"type": "http", "session": {}})

        result = await update_drawing_api_endpoint(
            symbol=data.get('symbol'),
            drawing_id=str(data.get('drawing_id')),
            drawing_data=data,
            request=fake_request
        )

        return {
            "type": "response",
            "action": "update_drawing",
            "success": result.status_code == 200,
            "data": result.body.decode('utf-8') if hasattr(result, 'body') else str(result),
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_update_drawing: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_delete_drawing(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle delete_drawing request"""
    session = websocket.scope.get('session', {})

    try:
        from fastapi import Request as FastAPIRequest
        fake_request = FastAPIRequest(scope={"type": "http", "session": {}})

        result = await delete_drawing_api_endpoint(
            symbol=data.get('symbol'),
            drawing_id=str(data.get('drawing_id')),
            request=fake_request
        )

        return {
            "type": "response",
            "action": "delete_drawing",
            "success": result.status_code == 200,
            "data": result.body.decode('utf-8') if hasattr(result, 'body') else str(result),
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_delete_drawing: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_delete_all_drawings(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle delete_all_drawings request"""
    session = websocket.scope.get('session', {})

    try:
        from fastapi import Request as FastAPIRequest
        fake_request = FastAPIRequest(scope={"type": "http", "session": {}})

        result = await delete_all_drawings_api_endpoint(
            symbol=data.get('symbol'),
            request=fake_request
        )

        return {
            "type": "response",
            "action": "delete_all_drawings",
            "success": result.status_code == 200,
            "data": result.body.decode('utf-8') if hasattr(result, 'body') else str(result),
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_delete_all_drawings: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_ai_suggestion(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle AI suggestion request"""
    session = websocket.scope.get('session', {})

    try:
        from fastapi import Request as FastAPIRequest
        fake_request = FastAPIRequest(scope={"type": "http", "session": {}})

        result = await ai_suggestion_endpoint(
            ai_request=data,
            request=fake_request
        )

        return {
            "type": "response",
            "action": "ai_suggestion",
            "success": result.status_code == 200,
            "data": result.body.decode('utf-8') if hasattr(result, 'body') else str(result),
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_ai_suggestion: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_get_local_ollama_models(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle get_local_ollama_models request"""
    session = websocket.scope.get('session', {})

    try:
        from fastapi import Request as FastAPIRequest
        fake_request = FastAPIRequest(scope={"type": "http", "session": {}})

        result = await get_local_ollama_models_endpoint(request=fake_request)

        return {
            "type": "response",
            "action": "get_local_ollama_models",
            "success": result.status_code == 200,
            "data": result.body.decode('utf-8') if hasattr(result, 'body') else str(result),
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_get_local_ollama_models: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_get_available_indicators(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle get_available_indicators request"""
    session = websocket.scope.get('session', {})

    try:
        from fastapi import Request as FastAPIRequest
        fake_request = FastAPIRequest(scope={"type": "http", "session": {}})

        result = await get_available_indicators_endpoint(request=fake_request)

        return {
            "type": "response",
            "action": "get_available_indicators",
            "success": result.status_code == 200,
            "data": result.body.decode('utf-8') if hasattr(result, 'body') else str(result),
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_get_available_indicators: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_get_agent_trades(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle get_agent_trades request"""
    session = websocket.scope.get('session', {})

    try:
        from fastapi import Request as FastAPIRequest
        fake_request = FastAPIRequest(scope={"type": "http", "session": {}})

        result = await get_agent_trades_endpoint(request=fake_request)

        return {
            "type": "response",
            "action": "get_agent_trades",
            "success": result.status_code == 200,
            "data": result.body.decode('utf-8') if hasattr(result, 'body') else str(result),
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_get_agent_trades: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_get_order_history(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle get_order_history request"""
    session = websocket.scope.get('session', {})

    try:
        from fastapi import Request as FastAPIRequest
        fake_request = FastAPIRequest(scope={"type": "http", "session": {}})

        result = await get_order_history_endpoint(
            symbol=data.get('symbol'),
            request=fake_request
        )

        return {
            "type": "response",
            "action": "get_order_history",
            "success": result.status_code == 200,
            "data": result.body.decode('utf-8') if hasattr(result, 'body') else str(result),
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_get_order_history: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_get_buy_signals(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle get_buy_signals request"""
    session = websocket.scope.get('session', {})

    try:
        from fastapi import Request as FastAPIRequest
        fake_request = FastAPIRequest(scope={"type": "http", "session": {}})

        result = await get_buy_signals_endpoint(
            symbol=data.get('symbol'),
            request=fake_request
        )

        return {
            "type": "response",
            "action": "get_buy_signals",
            "success": result.status_code == 200,
            "data": result.body.decode('utf-8') if hasattr(result, 'body') else str(result),
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_get_buy_signals: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_get_settings(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle get_settings request - load directly from Redis"""
    session = websocket.scope.get('session', {})

    try:
        symbol = data.get('symbol', session.get('symbol'))
        email = session.get('email')

        if not email:
            return {
                "type": "error",
                "message": "Not authenticated",
                "request_id": request_id
            }

        # Load settings directly from Redis
        redis_conn = await get_redis_connection()
        settings_key = f"settings:{email}:{symbol}"
        settings_json = await redis_conn.get(settings_key)

        if settings_json:
            settings_data = json.loads(settings_json)
            logger.info(f"Retrieved settings for {email}:{symbol} from Redis")
        else:
            # Return defaults if no settings found
            settings_data = {
                "active_indicators": session.get('active_indicators', []),
                "resolution": session.get('resolution', "1h"),
                "from_ts": session.get('from_ts'),
                "to_ts": session.get('to_ts'),
                "xAxisMin": None,
                "xAxisMax": None,
                "yAxisMin": None,
                "yAxisMax": None,
                "streamDeltaTime": 0
            }
            logger.info(f"No settings found for {email}:{symbol}, using defaults")

        return {
            "type": "response",
            "action": "get_settings",
            "success": True,
            "data": settings_data,
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_get_settings: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_set_settings(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle set_settings request - save directly to Redis"""
    session = websocket.scope.get('session', {})
    logger.info(f"DRAWING: {json.dumps(data, indent=2)}")
    logger.info(f"DRAWING: {json.dumps(data, indent=2)}")

    try:
        symbol = data.get('symbol', session.get('symbol'))
        email = session.get('email')

        if not email:
            return {
                "type": "error",
                "message": "Not authenticated",
                "request_id": request_id
            }

        # Extract settings data from the request
        settings_data = {
            k: v for k, v in data.items() if k not in ['symbol', 'request_id']
        }

        # Ensure required fields are set
        if 'last_selected_symbol' not in settings_data:
            settings_data['last_selected_symbol'] = symbol

        # Save settings directly to Redis
        redis_conn = await get_redis_connection()
        settings_key = f"settings:{email}:{symbol}"
        settings_json = json.dumps(settings_data)
        await redis_conn.set(settings_key, settings_json)

        logger.info(f"Saved settings for {email}:{symbol} to Redis: {list(settings_data.keys())}")

        return {
            "type": "response",
            "action": "set_settings",
            "success": True,
            "data": settings_data,
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_set_settings: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_set_last_symbol(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle set_last_symbol request"""
    session = websocket.scope.get('session', {})

    try:
        from fastapi import Request as FastAPIRequest
        fake_request = FastAPIRequest(scope={"type": "http", "session": {}})

        result = await set_last_selected_symbol(
            symbol=data.get('symbol'),
            request=fake_request
        )

        return {
            "type": "response",
            "action": "set_last_symbol",
            "success": result.status_code == 200,
            "data": result.body.decode('utf-8') if hasattr(result, 'body') else str(result),
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_set_last_symbol: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_get_last_symbol(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle get_last_symbol request"""
    session = websocket.scope.get('session', {})

    try:
        from fastapi import Request as FastAPIRequest
        fake_request = FastAPIRequest(scope={"type": "http", "session": {}})

        result = await get_last_selected_symbol(request=fake_request)

        return {
            "type": "response",
            "action": "get_last_symbol",
            "success": result.status_code == 200,
            "data": result.body.decode('utf-8') if hasattr(result, 'body') else str(result),
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_get_last_symbol: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_get_live_price(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle get_live_price request"""
    session = websocket.scope.get('session', {})

    try:
        from fastapi import Request as FastAPIRequest
        fake_request = FastAPIRequest(scope={"type": "http", "session": {}})

        result = await get_live_price(request=fake_request)

        return {
            "type": "response",
            "action": "get_live_price",
            "success": result.status_code == 200,
            "data": result.body.decode('utf-8') if hasattr(result, 'body') else str(result),
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_get_live_price: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_get_history(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle get_history request"""
    session = websocket.scope.get('session', {})

    try:
        from fastapi import Request as FastAPIRequest
        fake_request = FastAPIRequest(scope={"type": "http", "session": {}})

        result = await history_endpoint(
            symbol=data.get('symbol'),
            resolution=data.get('resolution'),
            from_ts=data.get('from_ts'),
            to_ts=data.get('to_ts'),
            request=fake_request
        )

        return {
            "type": "response",
            "action": "get_history",
            "success": result.status_code == 200,
            "data": result.body.decode('utf-8') if hasattr(result, 'body') else str(result),
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_get_history: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_get_initial_chart_config(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle get_initial_chart_config request"""
    session = websocket.scope.get('session', {})

    try:
        from fastapi import Request as FastAPIRequest
        fake_request = FastAPIRequest(scope={"type": "http", "session": {}})

        result = await initial_chart_config(symbol=data.get('symbol'), request=fake_request)

        return {
            "type": "response",
            "action": "get_initial_chart_config",
            "success": result.status_code == 200,
            "data": result.body.decode('utf-8') if hasattr(result, 'body') else str(result),
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_get_initial_chart_config: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_get_symbols(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle get_symbols request"""
    session = websocket.scope.get('session', {})

    try:
        from endpoints.chart_endpoints import symbols_endpoint
        from fastapi import Request as FastAPIRequest
        fake_request = FastAPIRequest(scope={"type": "http", "session": {}})

        result = await symbols_endpoint(request=fake_request)

        return {
            "type": "response",
            "action": "get_symbols",
            "success": result.status_code == 200,
            "data": result.body.decode('utf-8') if hasattr(result, 'body') else str(result),
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_get_symbols: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_get_symbols_list(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle get_symbols_list request"""
    session = websocket.scope.get('session', {})

    try:
        from endpoints.chart_endpoints import symbols_list_endpoint
        from fastapi import Request as FastAPIRequest
        fake_request = FastAPIRequest(scope={"type": "http", "session": {}})

        result = await symbols_list_endpoint(request=fake_request)

        return {
            "type": "response",
            "action": "get_symbols_list",
            "success": result.status_code == 200,
            "data": result.body.decode('utf-8') if hasattr(result, 'body') else str(result),
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_get_symbols_list: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_get_trade_history(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle get_trade_history request"""
    session = websocket.scope.get('session', {})

    try:
        from fastapi import Request as FastAPIRequest
        fake_request = FastAPIRequest(scope={"type": "http", "session": {}})

        # Use indicator_history_endpoint for now - may need to adjust
        result = await indicator_history_endpoint(
            symbol=data.get('symbol'),
            resolution=data.get('resolution'),
            from_ts=data.get('from_ts'),
            to_ts=data.get('to_ts'),
            request=fake_request
        )

        return {
            "type": "response",
            "action": "get_trade_history",
            "success": result.status_code == 200,
            "data": result.body.decode('utf-8') if hasattr(result, 'body') else str(result),
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_get_trade_history: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_get_volume_profile(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle get_volume_profile request"""
    session = websocket.scope.get('session', {})

    try:
        # Implement volume profile calculation
        klines = await get_cached_klines(
            symbol=data.get('symbol', session.get('symbol')),
            resolution=data.get('resolution', session.get('resolution')),
            from_ts=data.get('from_ts'),
            to_ts=data.get('to_ts')
        )

        if klines:
            volume_data = calculate_volume_profile(klines)
            return {
                "type": "response",
                "action": "get_volume_profile",
                "success": True,
                "data": volume_data,
                "request_id": request_id
            }
        else:
            return {
                "type": "response",
                "action": "get_volume_profile",
                "success": False,
                "data": {"error": "No klines data available"},
                "request_id": request_id
            }
    except Exception as e:
        logger.error(f"Error in handle_get_volume_profile: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_get_trading_sessions(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle get_trading_sessions request"""
    session = websocket.scope.get('session', {})

    try:
        sessions = await calculate_trading_sessions(
            symbol=data.get('symbol', session.get('symbol')),
            from_ts=data.get('from_ts'),
            to_ts=data.get('to_ts')
        )

        return {
            "type": "response",
            "action": "get_trading_sessions",
            "success": True,
            "data": {"sessions": sessions},
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_get_trading_sessions: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_history_message(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle history request from client"""
    session = websocket.scope.get('session', {})

    try:
        # Get parameters from message data
        symbol = data.get("symbol", "BTCUSDT")
        email = data.get("email") or session.get('email')
        min_value_percentage = data.get("minValuePercentage", 0)
        from_ts = data.get("from_ts")
        to_ts = data.get("to_ts")
        resolution = data.get("resolution", "1h")
        indicators = data.get("active_indicators", [])

        logger.info(f"Processing history request for symbol {symbol}, email {email}, minValuePercentage {min_value_percentage}, from_ts={from_ts}, to_ts={to_ts}")

        if not from_ts or not to_ts:
            return {
                "type": "error",
                "message": "No time range specified for history request",
                "request_id": request_id
            }

        # Fetch historical klines
        klines = await get_cached_klines(symbol, resolution, from_ts, to_ts)
        logger.info(f"Fetched {len(klines) if klines else 0} klines for history")

        # Calculate indicators
        indicators_data = await calculate_indicators_for_data(klines, indicators)
        logger.info(f"Calculated indicators: {list(indicators_data.keys()) if indicators_data else 'none'}")

        # Fetch and filter trades based on min value percentage
        trades = await fetch_recent_trade_history(symbol, from_ts, to_ts)
        logger.info(f"HISTORY: Fetched {len(trades) if trades else 0} trades for symbol {symbol}, from_ts={from_ts}, to_ts={to_ts}")

        if trades:
            trades = sorted(trades, key=lambda trade: trade.get('price', 0) * trade.get('quantity', 0), reverse=True)
            logger.info(f"TRADE_HISTORY: Sorted and limited trades to {len(trades)}")

        if trades and len(trades) > 0:
            logger.info(f"HISTORY: First trade sample: {json.dumps(trades[0])}")
        if trades and len(trades) > 0 and min_value_percentage > 0:
            # Calculate max trade value for filtering
            trade_values = [trade['price'] * trade['amount'] for trade in trades if 'price' in trade and 'amount' in trade]
            if trade_values:
                max_trade_value = max(trade_values)
                min_value = min_value_percentage * max_trade_value
                trades = [trade for trade in trades if (trade.get('price', 0) * trade.get('amount', 0)) >= min_value]
                logger.info(f"HISTORY: Filtered trades: {len(trades)} remain after filtering with {min_value_percentage*100}% min value")

        # Fetch drawings
        drawings = await get_drawings(symbol, None, resolution, email)
        logger.info(f"Fetched {len(drawings) if drawings else 0} drawings for history")

        # Calculate volume profile for rectangle drawings
        if drawings:
            logger.info(f"Processing {len(drawings)} drawings for volume profile calculation")
            for drawing in drawings:
                drawing_id = drawing.get('id')
                drawing_type = drawing.get('type')
                logger.info(f"Processing drawing {drawing_id}, type: {drawing_type}")
                if drawing_type == 'rect':
                    start_time_val = drawing.get('start_time')
                    end_time_val = drawing.get('end_time')
                    start_price = drawing.get('start_price')
                    end_price = drawing.get('end_price')
                    logger.info(f"Rectangle {drawing_id}: start_time={start_time_val}, end_time={end_time_val}, start_price={start_price}, end_price={end_price}")
                    if all([start_time_val, end_time_val, start_price is not None, end_price is not None]):
                        # Convert timestamps from milliseconds to seconds if needed
                        if start_time_val > 1e12:  # > 1 trillion, likely milliseconds
                            start_time = int(start_time_val / 1000)
                            logger.info(f"Converted start_time from ms to s: {start_time}")
                        else:
                            start_time = int(start_time_val)
                        if end_time_val > 1e12:  # > 1 trillion, likely milliseconds
                            end_time = int(end_time_val / 1000)
                            logger.info(f"Converted end_time from ms to s: {end_time}")
                        else:
                            end_time = int(end_time_val)

                        logger.info(f"Rectangle {drawing_id} time range: {start_time} to {end_time}")

                        price_min = min(float(start_price), float(end_price))
                        price_max = max(float(start_price), float(end_price))
                        logger.info(f"Rectangle {drawing_id} price range: {price_min} to {price_max}")

                        # Only calculate volume profile if rectangle time range intersects with history time range
                        intersects = start_time <= to_ts and end_time >= from_ts
                        logger.info(f"Rectangle {drawing_id} intersects with history range ({from_ts} to {to_ts}): {intersects}")
                        if intersects:
                            # Fetch klines for rectangle time range
                            rect_klines = await get_cached_klines(symbol, resolution, start_time, end_time)
                            logger.info(f"Fetched {len(rect_klines) if rect_klines else 0} klines for rectangle {drawing_id}")
                            if rect_klines:
                                # Filter klines within price range
                                filtered_klines = [
                                    k for k in rect_klines
                                    if k.get('high', 0) >= price_min and k.get('low', 0) <= price_max
                                ]
                                logger.info(f"Filtered to {len(filtered_klines)} klines within price range for rectangle {drawing_id}")
                                if filtered_klines:
                                    volume_profile_data = calculate_volume_profile(filtered_klines)
                                    drawing['volume_profile'] = volume_profile_data
                                    logger.info(f"Added volume profile to rectangle {drawing_id} with {len(volume_profile_data.get('volume_profile', []))} levels")
                                else:
                                    logger.info(f"No klines in price range for rectangle {drawing_id}")
                            else:
                                logger.info(f"No klines for rectangle {drawing_id} time range")
                    else:
                        logger.info(f"Incomplete rectangle data for drawing {drawing_id}")
                else:
                    logger.info(f"Skipping non-rectangle drawing {drawing_id}, type: {drawing_type}")

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

        # Debug: output drawings JSON
        # logger.info(f"HISTORY DRAWINGS: {json.dumps(drawings or [], default=str)}")

        # Return history_success message
        return {
            "type": "history_success",
            "symbol": symbol,
            "email": email,
            "data": {
                "ohlcv": combined_data,
                "trades": (trades or [])[:10000],
                "active_indicators": list(indicators_data.keys()),
                "drawings": drawings or []
            },
            "timestamp": int(time.time()),
            "request_id": request_id
        }

    except Exception as e:
        logger.error(f"Error in handle_history_message: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_trade_history_message(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle trade_history request from client (for filtering)"""
    session = websocket.scope.get('session', {})

    try:
        # Get parameters from message data
        symbol = data.get("symbol", "BTCUSDT")
        email = data.get("email") or session.get('email')
        value_filter = data.get("minValuePercentage", 0)
        from_ts = data.get("from_ts")
        to_ts = data.get("to_ts")

        logger.info(f"Processing trade_history request for symbol {symbol}, email {email}, valueFilter {value_filter}")

        if not from_ts or not to_ts:
            return {
                "type": "error",
                "message": "No time range specified for trade_history request",
                "request_id": request_id
            }

        # Fetch trades (without filtering)
        trades = await fetch_recent_trade_history(symbol, from_ts, to_ts)
        logger.info(f"TRADE_HISTORY: Fetched {len(trades) if trades else 0} trades for symbol {symbol}, from_ts={from_ts}, to_ts={to_ts}, value_filter={value_filter}")

        if trades and len(trades) > 0:
            logger.info(f"HISTORY: First trade sample: {json.dumps(trades[0])}")
        if trades and len(trades) > 0 and value_filter > 0:
            # Calculate max trade value for filtering
            trade_values = [trade['price'] * trade['amount'] for trade in trades if 'price' in trade and 'amount' in trade]
            if trade_values:
                max_trade_value = max(trade_values)
                min_value = value_filter * max_trade_value
                trades = [trade for trade in trades if (trade.get('price', 0) * trade.get('amount', 0)) >= min_value]
                logger.info(f"HISTORY: Filtered trades: {len(trades)} remain after filtering with {value_filter*100}% min value")

        # Return trade_history_success message
        return {
            "type": "trade_history_success",
            "symbol": symbol,
            "email": email,
            "data": {
                "trades": (trades or [])[:10000]
            },
            "timestamp": int(time.time()),
            "request_id": request_id
        }

    except Exception as e:
        logger.error(f"Error in handle_trade_history_message: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_shape_message(data: dict, websocket: WebSocket, request_id: str, action: str = None) -> dict:
    """Handle shape save/update/delete message from client"""
    session = websocket.scope.get('session', {})

    try:
        # Get email from WebSocket session
        email = session.get('email')
        if not email:
            return {
                "type": "error",
                "message": "Not authenticated",
                "request_id": request_id
            }

        symbol = data.get('symbol', 'BTCUSDT')

        logger.info(f"Processing shape message for {symbol}:{email}")

        # Create a fake request object for compatibility with existing functions
        from fastapi import Request as FastAPIRequest
        fake_request = FastAPIRequest(scope={"type": "http", "session": {"email": email}})

        # Check the action type - use parameter if provided, otherwise get from data
        if not action:
            action = data.get('action')
        if not action:
            return {
                "type": "error",
                "message": "Action is required for shape message",
                "request_id": request_id
            }

        if action == 'delete':
            # Handle delete operation
            drawing_id = data.get('drawing_id')
            if not drawing_id:
                return {
                    "type": "error",
                    "message": "Drawing ID is required for delete operation",
                    "request_id": request_id
                }

            logger.info(f"Deleting drawing {drawing_id} for {symbol}:{email}")
            success = await delete_drawing(symbol, drawing_id, fake_request, email)

            # Delete is considered successful even if drawing doesn't exist (idempotent operation)
            return {
                "type": "shape_success",
                "symbol": symbol,
                "email": email,
                "data": {"success": True, "id": drawing_id},
                "timestamp": int(time.time()),
                "request_id": request_id
            }

        elif action == 'save' or action == 'update':
            # Handle save/update operations
            resolution = data.get('resolution', '1h')

            # Prepare drawing data from the shape message
            drawing_data = {
                'symbol': symbol,
                'type': data.get('type'),  # Include type from client data
                'start_time': data.get('start_time'),
                'end_time': data.get('end_time'),
                'start_price': data.get('start_price'),
                'end_price': data.get('end_price'),
                'subplot_name': data.get('subplot_name', symbol),
                'resolution': resolution,
                'properties': data.get('properties')
            }

            # Check if this is an update (has drawing_id) or new save
            drawing_id = data.get('drawing_id')
            if drawing_id:
                # Update existing drawing
                logger.info(f"Updating drawing {drawing_id} for {symbol}:{email}")
                # Remove drawing_id from drawing_data for update
                update_data = {k: v for k, v in drawing_data.items() if k != 'drawing_id'}
                success = await update_drawing(symbol, drawing_id, DrawingData(**update_data), fake_request, email)
                result = {"success": success, "id": drawing_id}
            else:
                # Save new drawing
                logger.info(f"Saving new drawing for {symbol}:{email}")
                drawing_id = await save_drawing(drawing_data, fake_request)
                result = {"success": True, "id": drawing_id}

            if result and result.get('success'):
                return {
                    "type": "shape_success",
                    "symbol": symbol,
                    "email": email,
                    "data": result,
                    "timestamp": int(time.time()),
                    "request_id": request_id
                }
            else:
                return {
                    "type": "error",
                    "message": "Failed to save/update shape",
                    "request_id": request_id
                }

        elif action == 'get_properties':
            # Handle get properties operation
            drawing_id = data.get('drawing_id')
            if not drawing_id:
                return {
                    "type": "error",
                    "message": "Drawing ID is required for get_properties operation",
                    "request_id": request_id
                }

            logger.info(f"Getting properties for drawing {drawing_id} for {symbol}:{email}")

            # Get drawing data to retrieve properties
            drawings = await get_drawings(symbol, None, None, email)
            drawing = next((d for d in drawings if d.get('id') == drawing_id), None)
            if not drawing:
                return {
                    "type": "error",
                    "message": f"Drawing {drawing_id} not found",
                    "request_id": request_id
                }

            properties = drawing.get('properties', {})

            return {
                "type": "shape_properties_response",
                "symbol": symbol,
                "email": email,
                "data": {
                    "id": drawing_id,
                    "type": drawing.get('type'),  # Include 
                    "properties": properties
                },
                "timestamp": int(time.time()),
                "request_id": request_id
            }

        elif action == 'save_properties':
            # Handle save properties operation
            drawing_id = data.get('drawing_id')
            properties = data.get('properties', {})

            if not drawing_id:
                logger.error("Drawing ID is required for save_properties operation")
                return {
                    "type": "error",
                    "message": "Drawing ID is required for save_properties operation",
                    "request_id": request_id
                }

            logger.info(f"📝 SAVE_PROPERTIES: Attempting to save properties for drawing {drawing_id} for {symbol}:{email}")
            logger.info(f"📝 SAVE_PROPERTIES: Properties to save: {properties}")

            # Update drawing properties using existing function
            success = await update_drawing_properties(symbol, drawing_id, properties, email)
            logger.info(f"📝 SAVE_PROPERTIES: Update result - success: {success}")

            if success:
                logger.info(f"✅ SAVE_PROPERTIES: Successfully saved properties for drawing {drawing_id}")
                return {
                    "type": "shape_properties_success",
                    "symbol": symbol,
                    "email": email,
                    "id": drawing_id,
                    "data": {"success": True, "id": drawing_id},
                    "timestamp": int(time.time()),
                    "request_id": request_id
                }
            else:
                logger.error(f"❌ SAVE_PROPERTIES: Failed to save properties for drawing {drawing_id}")
                return {
                    "type": "error",
                    "message": "Failed to save shape properties",
                    "request_id": request_id
                }

        else:
            return {
                "type": "error",
                "message": f"Unknown shape action: {action}",
                "request_id": request_id
            }

    except Exception as e:
        logger.error(f"Error in handle_shape_message: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_get_volume_profile_direct(message: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle direct get_volume_profile message from client"""
    session = websocket.scope.get('session', {})

    try:
        # Handle volume profile calculation request from client
        rectangle_id = message.get("rectangle_id")
        rectangle_symbol = message.get("symbol", "BTCUSDT")
        resolution = message.get("resolution", "1h")

        logger.info(f"Processing get_volume_profile request for rectangle {rectangle_id}, symbol {rectangle_symbol}")

        # Get rectangle data from database
        email = session.get('email')
        if not email:
            return {
                "type": "error",
                "message": "Not authenticated",
                "request_id": request_id
            }

        # Get drawing data for the rectangle
        rectangle_drawings = await get_drawings(rectangle_symbol, rectangle_id, resolution, email)

        if not rectangle_drawings or len(rectangle_drawings) == 0:
            return {
                "type": "error",
                "message": f"No rectangle data found for id {rectangle_id}",
                "request_id": request_id
            }

        rect_drawing = rectangle_drawings[0]  # Should be only one
        start_time = rect_drawing.get("start_time")
        end_time = rect_drawing.get("end_time")
        start_price = rect_drawing.get("start_price")
        end_price = rect_drawing.get("end_price")

        if not all([start_time, end_time, start_price is not None, end_price is not None]):
            return {
                "type": "error",
                "message": f"Incomplete rectangle data for drawing {rectangle_id}",
                "request_id": request_id
            }

        price_min = min(float(start_price), float(end_price))
        price_max = max(float(start_price), float(end_price))

        # Fetch klines for this rectangle's time range
        rect_klines = await get_cached_klines(rectangle_symbol, resolution, start_time, end_time)
        logger.debug(f"Fetched {len(rect_klines)} klines for rectangle {rectangle_id} time range")

        if not rect_klines:
            return {
                "type": "error",
                "message": f"No klines available for rectangle {rectangle_id}",
                "request_id": request_id
            }

        # Filter klines that intersect with the rectangle's price range
        filtered_klines = [
            k for k in rect_klines
            if k.get('high', 0) >= price_min and k.get('low', 0) <= price_max
        ]
        logger.debug(f"Filtered to {len(filtered_klines)} klines within price range [{price_min}, {price_max}] for rectangle {rectangle_id}")

        if not filtered_klines:
            return {
                "type": "error",
                "message": f"No klines within price range for rectangle {rectangle_id}",
                "request_id": request_id
            }

        # Calculate volume profile for the filtered data
        volume_profile_data = calculate_volume_profile(filtered_klines)
        logger.info(f"Calculated volume profile for rectangle {rectangle_id} with {len(volume_profile_data.get('volume_profile', []))} price levels")

        # Return volume profile data for this rectangle
        return {
            "type": "volume_profile",
            "symbol": rectangle_symbol,
            "rectangle_id": rectangle_id,
            "rectangle": {
                "start_time": start_time,
                "end_time": end_time,
                "start_price": start_price,
                "end_price": end_price
            },
            "data": volume_profile_data,
            "timestamp": int(time.time()),
            "request_id": request_id
        }

    except Exception as e:
        logger.error(f"Failed to process get_volume_profile request for rectangle {rectangle_id}: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


async def handle_authenticate(data: dict, websocket: WebSocket, request_id: str) -> dict:
    """Handle authentication request"""
    session = websocket.scope.get('session', {})

    try:
        # Basic authentication check
        email = data.get('email')
        authenticated = session.get('authenticated', False)

        return {
            "type": "response",
            "action": "authenticate",
            "success": authenticated,
            "data": {
                "authenticated": authenticated,
                "email": session.get('email')
            },
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Error in handle_authenticate: {e}")
        return {
            "type": "error",
            "message": str(e),
            "request_id": request_id
        }


# Legacy HTTP endpoints (for backward compatibility during transition)

@app.get("/")
@limiter.limit("30/minute")
async def chart_page(request: Request):
    """Legacy HTTP endpoint for main chart page - redirects to use WebSocket"""
    # Same logic as original AppTradingView.py
    client_host = request.client.host if request.client else "Unknown"
    authenticated = False

    logger.info(f"Legacy chart page request from {client_host}. Current session state: authenticated={request.session.get('authenticated')}, email={request.session.get('email')}")

    # Check authentication
    is_local_test = client_host == "192.168.1.52"
    if request.session.get('email') is None:
        if is_local_test:
            request.session["authenticated"] = True
            request.session["email"] = "test@example.com"
            authenticated = True
        else:
            # Redirect to Google OAuth
            # Use local IP for redirect URI when running on local network
            if client_host == "192.168.1.52":
                redirect_uri = 'http://192.168.1.52:5000/OAuthCallback'
            else:
                redirect_uri = 'https://crypto.zhivko.eu/OAuthCallback'
            google_auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?client_id={creds.GOOGLE_CLIENT_ID}&redirect_uri={quote_plus(redirect_uri)}&response_type=code&scope=openid%20profile%20email&response_mode=query"
            return RedirectResponse(google_auth_url, status_code=302)
    else:
        # Check for last selected symbol and redirect if found
        try:
            from endpoints.utility_endpoints import get_last_selected_symbol
            last_symbol_response = await get_last_selected_symbol(request)
            if last_symbol_response.status_code == 200:
                import json
                response_data = json.loads(last_symbol_response.body.decode('utf-8'))
                if response_data.get('status') == 'success' and response_data.get('symbol'):
                    last_symbol = response_data['symbol']
                    logger.info(f"Redirecting user {request.session.get('email')} to last selected symbol: {last_symbol}")
                    return RedirectResponse(f"/{last_symbol}", status_code=302)
        except Exception as e:
            logger.error(f"Error checking last selected symbol for redirect: {e}")

    response = templates.TemplateResponse("index.html", {
        "request": request,
        "authenticated": authenticated,
        "supported_resolutions": SUPPORTED_RESOLUTIONS,
        "supported_ranges": SUPPORTED_RANGES,
        "supported_symbols": SUPPORTED_SYMBOLS
    })
    return response






@app.get("/logout")
async def logout(request: Request):
    """Clear the user session and redirect to home."""
    logger.info(f"Logout request from {request.client.host if request.client else 'Unknown'}. Clearing session.")
    request.session.clear()
    logger.info("Session cleared.")
    return RedirectResponse("/", status_code=302)


@app.get("/health/background-tasks")
async def background_tasks_health():
    """Health check for background tasks - same as original"""
    fetch_task = getattr(app.state, 'fetch_klines_task', None)
    trade_aggregator_task = getattr(app.state, 'trade_aggregator_task', None)
    trade_gap_filler_task = getattr(app.state, 'trade_gap_filler_task', None)
    email_task = getattr(app.state, 'email_alert_task', None)
    price_feed_task = getattr(app.state, 'price_feed_task', None)
    youtube_monitor_task = getattr(app.state, 'youtube_monitor_task', None)

    health_status = {
        "timestamp": datetime.now().isoformat(),
        "background_tasks": {
            "fetch_klines_task": {
                "exists": fetch_task is not None,
                "running": fetch_task is not None and not fetch_task.done(),
                "done": fetch_task.done() if fetch_task else None,
                "cancelled": fetch_task.cancelled() if fetch_task else None,
                "exception": str(fetch_task.exception()) if fetch_task and fetch_task.exception() else None
            },
            "trade_aggregator_task": {
                "exists": trade_aggregator_task is not None,
                "running": trade_aggregator_task is not None and not trade_aggregator_task.done(),
                "done": trade_aggregator_task.done() if trade_aggregator_task else None,
                "cancelled": trade_aggregator_task.cancelled() if trade_aggregator_task else None,
                "exception": str(trade_aggregator_task.exception()) if trade_aggregator_task and trade_aggregator_task.exception() else None
            },
            "trade_gap_filler_task": {
                "exists": trade_gap_filler_task is not None,
                "running": trade_gap_filler_task is not None and not trade_gap_filler_task.done(),
                "done": trade_gap_filler_task.done() if trade_gap_filler_task else None,
                "cancelled": trade_gap_filler_task.cancelled() if trade_gap_filler_task else None,
                "exception": str(trade_gap_filler_task.exception()) if trade_gap_filler_task and trade_gap_filler_task.exception() else None
            },
            "price_feed_task": {
                "exists": price_feed_task is not None,
                "running": price_feed_task is not None and not price_feed_task.done(),
                "done": price_feed_task.done() if price_feed_task else None,
                "cancelled": price_feed_task.cancelled() if price_feed_task else None,
                "exception": str(price_feed_task.exception()) if price_feed_task and price_feed_task.exception() else None
            },
            "email_alert_task": {
                "exists": email_task is not None,
                "running": email_task is not None and not email_task.done(),
                "done": email_task.done() if email_task else None,
                "cancelled": email_task.cancelled() if email_task else None,
                "exception": str(email_task.exception()) if email_task and email_task.exception() else None
            },
            "youtube_monitor_task": {
                "exists": youtube_monitor_task is not None,
                "running": youtube_monitor_task is not None and not youtube_monitor_task.done(),
                "done": youtube_monitor_task.done() if youtube_monitor_task else None,
                "cancelled": youtube_monitor_task.cancelled() if youtube_monitor_task else None,
                "exception": str(youtube_monitor_task.exception()) if youtube_monitor_task and youtube_monitor_task.exception() else None
            }
        }
    }

    logger.info(f"📊 BACKGROUND TASK HEALTH CHECK: {health_status}")
    return health_status


@app.get("/OAuthCallback")
async def oauth_callback(request: Request, code: str):
    """
    Handles the OAuth 2.0 callback from Google.
    This is where Google redirects the user after they authenticate.
    """
    logger.info(f"OAuthCallback: Received callback from Google with code: {code[:50]}...") # Truncate code for logging

    # Determine redirect URI based on client host (same logic as in chart_page)
    client_host = request.client.host if request.client else "Unknown"
    if client_host == "192.168.1.52":
        redirect_uri = 'http://192.168.1.52:5000/OAuthCallback'
    else:
        redirect_uri = 'https://crypto.zhivko.eu/OAuthCallback'

    try:
        # Run the synchronous OAuth operations in a thread to avoid blocking the ASGI event loop
        user_email = await asyncio.to_thread(process_google_oauth, code, redirect_uri)

        logger.info(f"OAuthCallback: Before setting session - authenticated={request.session.get('authenticated')}, email={request.session.get('email')}")
        request.session["authenticated"] = True
        request.session["email"] = user_email  # Store the user's email in the session
        logger.info(f"Login user in by google account. Session variable set: session[\"authenticated\"] = True, session[\"email\"] = {user_email}")
        logger.info(f"OAuthCallback: After setting session - authenticated={request.session.get('authenticated')}, email={request.session.get('email')}")

        # 2. [Placeholder] Create or update user in your database
        # You would typically check if the user_id exists, if not, create a new user.
        # For now, just log the user information.
        logger.info(f"OAuthCallback: [Placeholder] Creating or updating user in database for email: {user_email}")

        # 3. [Placeholder] Establish a session for the user
        # This is a placeholder.  In a real app, you'd set a cookie or use some other session management.
        logger.info(f"OAuthCallback: [Placeholder] Establishing session for email: {user_email}")

        return RedirectResponse("/", status_code=302) # Redirect to the main chart

    except Exception as e:
        logger.error(f"OAuthCallback: Error processing Google login: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to process Google login: {e}")


def process_google_oauth(code: str, redirect_uri: str) -> str:
    """
    Synchronous function to handle Google OAuth flow.
    This runs in a thread to avoid blocking the ASGI event loop.
    """
    GOOGLE_CLIENT_ID = creds.GOOGLE_CLIENT_ID
    GOOGLE_CLIENT_SECRET = creds.GOOGLE_CLIENT_SECRET

    client_secrets_file = 'c:/git/VidWebServer/client_secret_655872926127-9fihq5a2rdsiakqltvmt6urj7saanhhd.apps.googleusercontent.com.json'

    # Load client secrets from file
    with open(client_secrets_file, 'r') as f:
        client_config = json.load(f)

    web_config = client_config.get('web', {})
    scopes = client_config.get('web', {}).get('scopes')
    if not scopes:
        logger.warning(f"No scopes found in client_secret.json at {client_secrets_file}. Check file structure.")
        scopes = ['https://www.googleapis.com/auth/userinfo.email','openid','https://www.googleapis.com/auth/userinfo.profile'] # Use default scopes if not found in file
    client_id = web_config.get('client_id')
    client_secret = web_config.get('client_secret')
    if not client_id or not client_secret:
        logger.error(f"Client ID or secret not found in {client_secrets_file}")
        raise ValueError("Client ID or secret not found in client_secret.json")

    flow = Flow.from_client_secrets_file(
        client_secrets_file=client_secrets_file,  # Replace with the path to your client_secret.json file
        scopes=scopes,
        redirect_uri=redirect_uri)

    # 2. Exchange the authorization code for credentials
    flow.fetch_token(code=code)
    credentials = flow.credentials

    # 3. Verify the ID token
    id_token_jwt = credentials.id_token

    if id_token_jwt is None:
        raise ValueError("ID token is missing in the credentials.")

    try:
        request = google_requests.Request()
        id_info = id_token.verify_oauth2_token(id_token_jwt, request, GOOGLE_CLIENT_ID)
    except ValueError as e:
        logger.error(f"OAuthCallback: Invalid ID token: {e}")
        raise ValueError(f"Invalid ID token: {e}")

    # 4. Check the token's claims
    if id_info['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
        raise ValueError("Wrong issuer.")

    user_id = id_info['sub'] # The unique user ID
    user_email = id_info['email']
    logger.info(f"OAuthCallback: Successfully verified Google ID token for user {user_id} (email: {user_email})")

    return user_email
@app.get("/{symbol}")
@limiter.limit("1000/minute")
async def symbol_chart_page(symbol: str, request: Request):
    """Legacy HTTP endpoint for symbol-specific chart page"""
    # Same logic as original
    client_host = request.client.host if request.client else "Unknown"

    logger.info(f"Legacy symbol chart page request for {symbol} from {client_host}. Current session state: authenticated={request.session.get('authenticated')}, email={request.session.get('email')}")

    # Skip if API route
    if symbol in ["static", "ws", "health", "logout", "OAuthCallback"]:
        raise HTTPException(status_code=404, detail="Not found")

    # Authentication logic (same as original)
    authenticated = False
    is_local_test = client_host == "192.168.1.52"

    if request.session.get('email') is None:
        if is_local_test:
            request.session["authenticated"] = True
            request.session["email"] = "test@example.com"
            authenticated = True
        else:
            # Use local IP for redirect URI when running on local network
            if client_host == "192.168.1.52":
                redirect_uri = 'http://192.168.1.52:5000/OAuthCallback'
            else:
                redirect_uri = 'https://crypto.zhivko.eu/OAuthCallback'
            google_auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?client_id={creds.GOOGLE_CLIENT_ID}&redirect_uri={quote_plus(redirect_uri)}&response_type=code&scope=openid%20profile%20email&response_mode=query"
            logger.info(f"User not authenticated. Redirecting to Google OAuth: {google_auth_url}")
            return RedirectResponse(google_auth_url, status_code=302)
    else:
        authenticated = True
        
        if symbol in SUPPORTED_SYMBOLS:
            # Persist last selected symbol per user in Redis
            try:
                email = request.session.get("email")
                if email:
                    redis_conn = await get_redis_connection()
                    last_selected_symbol_key = f"user:{email}:{REDIS_LAST_SELECTED_SYMBOL_KEY}"
                    await redis_conn.set(last_selected_symbol_key, symbol.upper())
                    logger.debug(f"Persisted last selected symbol '{symbol.upper()}' for user {email}")
            except Exception as e:
                logger.error(f"Error persisting last selected symbol for {symbol}: {e}")


    # Render template
    response = templates.TemplateResponse("index.html", {
        "request": request,
        "authenticated": authenticated,
        "symbol": symbol.upper(),
        "supported_resolutions": SUPPORTED_RESOLUTIONS,
        "supported_ranges": SUPPORTED_RANGES,
        "supported_symbols": SUPPORTED_SYMBOLS
    })
    return response


if __name__ == "__main__":
    # Configure Gemini API key globally
    try:
        import google.generativeai as genai
        genai.configure(api_key=creds.GEMINI_API_KEY)
    except ImportError:
        logger.warning("Google Generative AI not available. AI features will be limited.")

    # Get local IP address
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    IP_ADDRESS = s.getsockname()[0]
    s.close()

    logger.info(f'Local address: {IP_ADDRESS}')

    # Set debug mode
    is_debug_mode = True
    app.extra["debug_mode"] = is_debug_mode

    uvicorn.run(
        "AppTradingView2:app",
        host=IP_ADDRESS,
        port=5000,
        reload=True,
        reload_excludes="*.log",
        http="h11",
        timeout_keep_alive=10,
        log_level="info",
        timeout_graceful_shutdown=1
    )


if __name__ == "__main__":
    # Configure Gemini API key globally
    try:
        import google.generativeai as genai
        genai.configure(api_key=creds.GEMINI_API_KEY)
    except ImportError:
        logger.warning("Google Generative AI not available. AI features will be limited.")

    # Get local IP address
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    IP_ADDRESS = s.getsockname()[0]
    s.close()

    logger.info(f'Local address: {IP_ADDRESS}')

    # Set debug mode
    is_debug_mode = True
    app.extra["debug_mode"] = is_debug_mode

    uvicorn.run(
        "AppTradingView2:app",
        host=IP_ADDRESS,
        port=5000,
        reload=False,
        reload_excludes="*.log",
        http="h11",
        timeout_keep_alive=10,
        log_level="info",
        timeout_graceful_shutdown=1
    )
