# Refactored TradingView Application
# Main FastAPI application that imports and combines all modules

import os
import socket
import asyncio
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
import json
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport.requests import Request as google_requests
from urllib.parse import quote_plus
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

# Import email alert service
from email_alert_service import alert_service

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

        # Start email alert monitoring service
        app_instance.state.email_alert_task = asyncio.create_task(alert_service.monitor_alerts())
        logger.info("Email alert monitoring service started.")
    except Exception as e:
        logger.error(f"Failed to initialize Redis or start background tasks: {e}", exc_info=True)
        app_instance.state.fetch_klines_task = None
        app_instance.state.email_alert_task = None
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

    email_alert_task = getattr(app_instance.state, 'email_alert_task', None)
    if email_alert_task:
        logger.info("Cancelling email alert monitoring task...")
        email_alert_task.cancel()
        try:
            await email_alert_task
            logger.info(f"email_alert_task status: Done={email_alert_task.done()}, Cancelled={email_alert_task.cancelled()}, Exception={email_alert_task.exception()}")
        except asyncio.CancelledError:
            logger.info("Email alert monitoring task successfully cancelled.")
        except Exception as e:
            logger.error(f"Error during email alert monitoring task shutdown: {e}", exc_info=True)

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

    computer_name = os.environ.get('COMPUTERNAME')
    if computer_name == "MAŠINA":
        authenticated = True
        request.session["authenticated"] = True
        request.session["email"] = "vid.zivkovic@gmail.com"
    elif computer_name == "ASUSAMD":
        authenticated = True
        request.session["authenticated"] = True
        request.session["email"] = "klemenzivkovic@gmail.com"
    else:
        # For mobile devices or unknown computers - require proper authentication
        # For now, we'll deny access until proper auth is implemented
        logger.warning(f"Unauthorized access attempt from {client_host} (COMPUTERNAME: {computer_name})")
        authenticated = False
        # Clear any existing session data
        request.session.clear()

    logger.info(f"Chart page request from {client_host}. Current session state: authenticated={request.session.get('authenticated')}, email={request.session.get('email')}")
    if request.session.get('email') is None:
        logger.info(f"No email in session for {client_host}, redirecting to Google OAuth")
        #try:
        #    require_valid_certificate(request)
        #    authenticated = True
        #    request.session["authenticated"] = True
        #    logger.info(f"Client authenticated via certificate. Serving chart page to {client_host}.")
        #    return templates.TemplateResponse("index.html", {"request": request, "authenticated": authenticated}) # type: ignore

        #except HTTPException as cert_exception:
            # Certificate is invalid, initiate Google Auth flow
        #    logger.warning(f"Client certificate missing or invalid. Initiating Google Auth flow for {client_host}. Error: {cert_exception.detail}")

        # Build Google OAuth URL
        google_auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?client_id={creds.GOOGLE_CLIENT_ID}&redirect_uri={quote_plus('https://crypto.zhivko.eu/OAuthCallback')}&response_type=code&scope=openid%20profile%20email&response_mode=query"

        # Redirect to Google for authentication
        return RedirectResponse(google_auth_url, status_code=302)
    else:
        logger.info(f"Email found in session for {client_host}: {request.session.get('email')}")

    response = templates.TemplateResponse("index.html", {"request": request, "authenticated": True}) # type: ignore
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

# Logout endpoint
@app.get("/logout")
async def logout(request: Request):
    """Clear the user session and redirect to home."""
    logger.info(f"Logout request from {request.client.host if request.client else 'Unknown'}. Clearing session.")
    request.session.clear()
    logger.info("Session cleared.")
    return RedirectResponse("/", status_code=302)

@app.get("/OAuthCallback")
async def oauth_callback(request: Request, code: str):
    """
    Handles the OAuth 2.0 callback from Google.
    This is where Google redirects the user after they authenticate.
    """
    logger.info(f"OAuthCallback: Received callback from Google with code: {code[:50]}...") # Truncate code for logging

    GOOGLE_CLIENT_ID = creds.GOOGLE_CLIENT_ID
    GOOGLE_CLIENT_SECRET = creds.GOOGLE_CLIENT_SECRET

    try:
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
            raise HTTPException(status_code=500, detail="Client ID or secret not found in client_secret.json")



        if not client_id or not client_secret:
            logger.error(f"Client ID or secret not found in {client_secrets_file}")
            raise HTTPException(status_code=500, detail="Client ID or secret not found in client_secret.json")

        # 1. Configure the OAuth 2.0 flow
        flow = Flow.from_client_secrets_file(
            client_secrets_file=client_secrets_file,  # Replace with the path to your client_secret.json file
            scopes = scopes,
            redirect_uri='https://crypto.zhivko.eu/OAuthCallback')
        
        # 2. Exchange the authorization code for credentials
        flow.fetch_token(code=code)
        credentials = flow.credentials

        # 3. Verify the ID token
        id_token_jwt = credentials.id_token

        if id_token_jwt is None:
            raise ValueError("ID token is missing in the credentials.")

        try:
            id_info = id_token.verify_token(id_token_jwt, google_requests(), GOOGLE_CLIENT_ID)
        except ValueError as e:
           logger.error(f"OAuthCallback: Invalid ID token: {e}")
           raise HTTPException(status_code=400, detail=f"Invalid ID token: {e}")

        # 4. Check the token's claims
        if id_info['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
            raise ValueError("Wrong issuer.")

        # print(id_info)
        # return RedirectResponse("/", status_code=302) # Redirect to the main chart
        user_id = id_info['sub'] # The unique user ID
        user_email = id_info['email']
        logger.info(f"OAuthCallback: Successfully verified Google ID token for user {user_id} (email: {user_email})")

        logger.info(f"OAuthCallback: Before setting session - authenticated={request.session.get('authenticated')}, email={request.session.get('email')}")
        request.session["authenticated"] = True
        request.session["email"] = user_email  # Store the user's email in the session
        logger.info(f"Login user in by google account. Session variable set: session[\"authenticated\"] = True, session[\"email\"] = {user_email}")
        logger.info(f"OAuthCallback: After setting session - authenticated={request.session.get('authenticated')}, email={request.session.get('email')}")


        # 2. [Placeholder] Create or update user in your database
        # You would typically check if the user_id exists, if not, create a new user.
        # For now, just log the user information.
        logger.info(f"OAuthCallback: [Placeholder] Creating or updating user in database for user_id: {user_id}, email: {user_email}")

        # 3. [Placeholder] Establish a session for the user
        # This is a placeholder.  In a real app, you'd set a cookie or use some other session management.
        logger.info(f"OAuthCallback: [Placeholder] Establishing session for user_id: {user_id} and email: {user_email}")

        return RedirectResponse("/", status_code=302) # Redirect to the main chart

    except Exception as e:
        logger.error(f"OAuthCallback: Error processing Google login: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to process Google login: {e}")


# Symbol-specific chart page endpoint (must be last to avoid conflicts with API routes)
@app.get("/{symbol}")
async def symbol_chart_page(symbol: str, request: Request):
    """Handle requests to /symbol pages and serve the main chart page."""
    # Skip if this is an API route or static file
    if symbol in ["static", "history", "initial_chart_config", "symbols", "config", "symbols_list",
                  "get_drawings", "save_drawing", "delete_drawing", "update_drawing", "delete_all_drawings",
                  "save_shape_properties", "get_shape_properties", "AI", "AI_Local_OLLAMA_Models", "indicators",
                  "get_agent_trades", "get_order_history", "get_buy_signals", "settings", "set_last_symbol",
                  "get_last_symbol", "stream", "indicatorHistory", "OAuthCallback"]:
        raise HTTPException(status_code=404, detail="Not found")

    client_host = request.client.host if request.client else "Unknown"


    authenticated = False
    '''
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

    logger.info(f"Symbol page request: {symbol} from {client_host}")
    '''

    logger.info(f"Symbol chart page request for {symbol} from {client_host}. Current session state: authenticated={request.session.get('authenticated')}, email={request.session.get('email')}")
    if request.session.get('email') is None:
        logger.info(f"No email in session for {symbol} request from {client_host}, redirecting to Google OAuth")
        #try:
        #    require_valid_certificate(request)
        #    authenticated = True
        #    request.session["authenticated"] = True
        #    logger.info(f"Client authenticated via certificate. Serving chart page to {client_host}.")
        #    return templates.TemplateResponse("index.html", {"request": request, "authenticated": authenticated}) # type: ignore

        #except HTTPException as cert_exception:
            # Certificate is invalid, initiate Google Auth flow
        #    logger.warning(f"Client certificate missing or invalid. Initiating Google Auth flow for {client_host}. Error: {cert_exception.detail}")

        # Build Google OAuth URL
        google_auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?client_id={creds.GOOGLE_CLIENT_ID}&redirect_uri={quote_plus('https://crypto.zhivko.eu/OAuthCallback')}&response_type=code&scope=openid%20profile%20email&response_mode=query"

        # Redirect to Google for authentication
        return RedirectResponse(google_auth_url, status_code=302)
    else:
        logger.info(f"Email found in session for {symbol} request from {client_host}: {request.session.get('email')}")

    # Set the symbol in session for the frontend to use
    request.session["requested_symbol"] = symbol
    response = templates.TemplateResponse("index.html", {"request": request, "authenticated": authenticated})
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
        "AppTradingView:app",
        host=IP_ADDRESS,
        port=5000,
        reload=True,
        reload_excludes="*.log",
        http="h11",
        timeout_keep_alive=10,
        log_level="info"
    )