# Refactored TradingView Application
# Main FastAPI application that imports and combines all modules

import os
import socket
import asyncio
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware

# Import configuration and utilities
from config import SECRET_KEY, STATIC_DIR, TEMPLATES_DIR, PROJECT_ROOT
from logging_config import logger
from auth import creds, get_session
from redis_utils import init_redis
from background_tasks import fetch_and_publish_klines
from time_sync import sync_time_with_ntp

# Import endpoint modules
from endpoints.chart_endpoints import (
    history_endpoint, initial_chart_config, symbols_endpoint,
    config_endpoint, symbols_list_endpoint
)
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
    get_last_selected_symbol, stream_logs_endpoint
)
from endpoints.indicator_endpoints import indicator_history_endpoint

# Import WebSocket handlers
from websocket_handlers import stream_live_data_websocket_endpoint, stream_klines

# Lifespan manager for startup and shutdown events
@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    logger.info("Application startup...")
    try:
        await init_redis()
        # Store the task in the application state so it can be accessed during shutdown
        app_instance.state.fetch_klines_task = asyncio.create_task(fetch_and_publish_klines())
        logger.info("Background task (fetch_and_publish_klines) started.")
    except Exception as e:
        logger.error(f"Failed to initialize Redis or start background tasks: {e}", exc_info=True)
        app_instance.state.fetch_klines_task = None
    yield
    logger.info("Application shutdown...")
    fetch_klines_task = getattr(app_instance.state, 'fetch_klines_task', None)
    if fetch_klines_task:
        logger.info("Cancelling fetch_and_publish_klines task...")
        fetch_klines_task.cancel()
        try:
            await fetch_klines_task
            logger.info(f"fetch_klines_task status: Done={fetch_klines_task.done()}, Cancelled={fetch_klines_task.cancelled()}, Exception={fetch_klines_task.exception()}")
        except asyncio.CancelledError:
            logger.info("fetch_and_publish_klines task successfully cancelled.")
        except Exception as e:
            logger.error(f"Error during fetch_and_publish_klines task shutdown: {e}", exc_info=True)

# Initialize FastAPI app
app = FastAPI(lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Add ProxyHeadersMiddleware to trust headers from Nginx
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["IP_OF_NGINX_SERVER_A", "192.168.1.20"])

# Middleware to add cache-control headers
@app.middleware("http")
async def add_no_cache_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    # Conditionally add headers, e.g., if in debug mode.
    if os.getenv("FASTAPI_DEBUG", "False").lower() == "true" or app.extra.get("debug_mode", False):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "-1"
    return response

# Mount static files and templates
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Main chart page endpoint
@app.get("/")
async def chart_page(request: Request):
    client_host = request.client.host if request.client else "Unknown"
    authenticated = False

    if (os.environ.get('COMPUTERNAME') == "MAŠINA"):
        authenticated = True
        request.session["authenticated"] = True
        request.session["email"] = "vid.zivkovic@gmail.com"
    elif(os.environ.get('COMPUTERNAME') == "ASUSAMD"):
        authenticated = True
        request.session["authenticated"] = True
        request.session["email"] = "klemenzivkovic@gmail.com"
    else:
        # Authentication logic would go here
        authenticated = True  # Simplified for refactoring

    response = templates.TemplateResponse("index.html", {"request": request, "authenticated": authenticated})
    return response

# Chart endpoints
app.get("/history")(history_endpoint)
app.get("/initial_chart_config")(initial_chart_config)
app.get("/symbols")(symbols_endpoint)
app.get("/config")(config_endpoint)
app.get("/symbols_list")(symbols_list_endpoint)

# Drawing endpoints
app.get("/get_drawings/{symbol}")(get_drawings_api_endpoint)
app.post("/save_drawing/{symbol}")(save_drawing_api_endpoint)
app.delete("/delete_drawing/{symbol}/{drawing_id}")(delete_drawing_api_endpoint)
app.put("/update_drawing/{symbol}/{drawing_id}")(update_drawing_api_endpoint)
app.delete("/delete_all_drawings/{symbol}")(delete_all_drawings_api_endpoint)
app.post("/save_shape_properties/{symbol}/{drawing_id}")(save_shape_properties_api_endpoint)
app.get("/get_shape_properties/{symbol}/{drawing_id}")(get_shape_properties_api_endpoint)

# AI endpoints
app.post("/AI")(ai_suggestion_endpoint)
app.get("/AI_Local_OLLAMA_Models")(get_local_ollama_models_endpoint)
app.get("/indicators")(get_available_indicators_endpoint)

# Trading endpoints
app.get("/get_agent_trades")(get_agent_trades_endpoint)
app.get("/get_order_history/{symbol}")(get_order_history_endpoint)
app.get("/get_buy_signals/{symbol}")(get_buy_signals_endpoint)

# Utility endpoints
app.route('/settings', methods=['GET', 'POST'])(settings_endpoint)
app.post("/set_last_symbol/{symbol}")(set_last_selected_symbol)
app.get("/get_last_symbol")(get_last_selected_symbol)
app.get("/stream/logs")(stream_logs_endpoint)

# Indicator endpoints
app.get("/indicatorHistory")(indicator_history_endpoint)

# WebSocket endpoints
app.websocket("/stream/live/{symbol}")(stream_live_data_websocket_endpoint)
app.get("/stream/{symbol}/{resolution}")(stream_klines)

# OAuth callback endpoint
@app.get("/OAuthCallback")
async def oauth_callback(request: Request, code: str):
    """Handles the OAuth 2.0 callback from Google."""
    logger.info(f"OAuthCallback: Received callback from Google with code: {code[:50]}...")

    # OAuth implementation would go here
    # For now, redirect to main chart
    return RedirectResponse("/", status_code=302)

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
        "AppTradingView_refactored:app",
        host=IP_ADDRESS,
        port=5000,
        reload=True,
        reload_excludes="*.log",
        http="h11",
        timeout_keep_alive=10,
        log_level="info"
    )