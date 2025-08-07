# python -m venv venv
from django.views.decorators.cache import never_cache
import sys
import time # Added for retry delay
import requests
import time
import ntplib
from google.oauth2 import id_token
import google.generativeai as genai
import subprocess
import uvicorn


from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import time
from pathlib import Path
from typing import Any, TypedDict, Union, cast, Optional, AsyncGenerator, Dict, List
import asyncio
import json
import glob
import logging
import os  # For environment variable access
from contextlib import asynccontextmanager # Import asynccontextmanager
import secrets
import traceback
import uuid
from datetime import datetime, timezone
from fastapi.responses import RedirectResponse

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import requests  # Import requests to catch its exceptions
from pybit import exceptions  # Import pybit exceptions

import pandas as pd # type: ignore
import pandas_ta as ta # type: ignore
import numpy as np

from fastapi import FastAPI, Response, Request, WebSocket, WebSocketDisconnect, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates # type: ignore # type: ignore
import httpx # For making requests to Ollama
from redis.asyncio import Redis as AsyncRedis # Renamed for clarity if Redis sync client is also used
from redis.asyncio.client import PubSub
from pybit.unified_trading import HTTP
from sse_starlette.sse import EventSourceResponse
from redis.exceptions import ConnectionError, TimeoutError
from fastapi.middleware.cors import CORSMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware # Import the middleware
from pydantic import BaseModel
from urllib.parse import quote_plus, urlencode


from pybit.unified_trading import WebSocket as BybitWS # Renamed for clarity
from openai import OpenAI, APIError, APIStatusError, APIConnectionError # For DeepSeek
from starlette.websockets import WebSocketState
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware

import socket

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from fastapi.responses import RedirectResponse

from google_auth_oauthlib.flow import Flow

from fastapi import Request
from detectBulishDivergence import detect_bullish_divergence, plot_chart_with_divergence, find_breakout_intersection


SECRET_KEY = "super-secret"  # Replace with a strong, randomly generated key

sys.stdout.reconfigure(encoding="utf-8")


async def get_session(request: Request) -> dict:
    """Dependency to retrieve the session."""
    return request.session

def is_authenticated(session: dict = Depends(get_session)):
    """Check if user is authenticated based on session."""
    return session.get("authenticated", False)

def require_authentication(session: dict = Depends(get_session)):
    """Dependency to require authentication for a route."""
    if not is_authenticated(session):
        raise HTTPException(status_code=403, detail="Not authenticated")




class FlushingFileHandler(logging.FileHandler):
    """A file handler that flushes on every log record."""
    def emit(self, record):
        super().emit(record)
        self.flush()

# Configure logging
log_file_path = Path('trading_view.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
    handlers=[logging.StreamHandler(), FlushingFileHandler(log_file_path, encoding="utf-8")]
)

logger = logging.getLogger(__name__)

# --- Time Synchronization Functionality ---
def sync_time_with_ntp():
    """Synchronizes the system's time with an NTP server."""
    try:
        client = ntplib.NTPClient()
        response = client.request('pool.ntp.org', version=3, timeout=5) # response.tx_time is already in system time
        ntp_time = datetime.fromtimestamp(response.tx_time, tz=timezone.utc)
        offset = response.offset

        # Log the time synchronization details
        logger.info(f"Time synchronized with NTP server. NTP Time: {ntp_time}, Offset: {offset:.4f} seconds")


       # --- Actual System Time Setting ---
        if sys.platform.startswith('linux'):
            # Linux: Use 'date' command. Requires sudo.
            # Format: YYYY-MM-DD HH:MM:SS UTC
            time_str = ntp_time.strftime("%Y-%m-%d %H:%M:%S UTC")
            cmd = ['sudo', 'date', '-s', time_str]
            logger.info(f"Attempting to set system time on Linux: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                logger.info(f"System time successfully set on Linux: {result.stdout.strip()}")
            else:
                logger.error(f"Failed to set system time on Linux. Error: {result.stderr.strip()}")
                return False
        elif sys.platform.startswith('win'):
            # Windows: Use 'w32tm' command. Requires admin privileges.
            # First, configure to sync from manual peer, then force resync.
            max_retries = 3
            retry_delay_seconds = 5
            for attempt in range(max_retries):
                try:
                    logger.info(f"Attempting to set system time on Windows using w32tm (Attempt {attempt + 1}/{max_retries}).")
                    # Configure NTP client to use pool.ntp.org and be reliable
                    # w32tm /config /manualpeerlist:time.windows.com,0x1 /syncfromflags:manual /reliable:yes /update
                    # w32tm /config /update /manualpeerlist:"0.pool.ntp.org,0x8 1.pool.ntp.org,0x8 2.pool.ntp.org,0x8 3.pool.ntp.org,0x8" /syncfromflags:MANUAL


                    config_result = subprocess.run(['w32tm', '/config', '/manualpeerlist:\"0.pool.ntp.org,0x8 1.pool.ntp.org,0x8 2.pool.ntp.org,0x8 3.pool.ntp.org,0x8\"', '/syncfromflags:manual', '/reliable:yes', '/update'], capture_output=True, text=True, check=True)
                    logger.info("w32tm /config command issued on Windows.")
                    if config_result.stdout:
                        logger.info(f"w32tm /config stdout: {config_result.stdout.strip()}")
                    if config_result.stderr:
                        logger.warning(f"w32tm /config stderr: {config_result.stderr.strip()}")

                    # Force resync
                    resync_result = subprocess.run(['w32tm', '/resync', '/force'], capture_output=True, text=True, check=True)
                    logger.info("System time resync command issued on Windows.")
                    if resync_result.stdout:
                        logger.info(f"w32tm /resync stdout: {resync_result.stdout.strip()}")
                    if resync_result.stderr:
                        logger.warning(f"w32tm /resync stderr: {resync_result.stderr.strip()}")

                    # Check if resync was successful based on output
                    if "The command completed successfully." in resync_result.stdout: # or similar success message
                        logger.info("System time resync reported success.")
                        return True
                    else:
                        logger.warning("w32tm /resync did not report success. Retrying...")
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay_seconds)
                        else:
                            logger.error(f"Failed to resync system time after {max_retries} attempts.")
                            return False

                except subprocess.CalledProcessError as e:
                    logger.error(f"Failed to set system time on Windows: {e.output.strip()}")
                    if e.returncode == 2147942405: # 0x80070005 - Access is denied
                        logger.error(f"Failed to set system time on Windows: Access Denied. Please run the script as an Administrator. Error: {e.stderr.strip()}")
                        return False # No point in retrying if it's an access denied error
                    else:
                        logger.error(f"Failed to set system time on Windows. Command: {e.cmd}, Return Code: {e.returncode}, Error: {e.stderr.strip()}")
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay_seconds)
                        else:
                            logger.error(f"Failed to resync system time after {max_retries} attempts due to CalledProcessError.")
                            return False
                except Exception as e:
                    logger.error(f"An unexpected error occurred during time sync attempt: {e}", exc_info=True)
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay_seconds)
                    else:
                        logger.error(f"Failed to resync system time after {max_retries} attempts due to unexpected error.")
                        return False
            return False # All retries failed
        else:
            logger.warning(f"System time setting not implemented for platform: {sys.platform}")


        return True

    except Exception as e:
        logger.error(f"Time synchronization failed: {e}", exc_info=True)
        return False

# Lifespan manager for startup and shutdown events
@asynccontextmanager
async def lifespan(app_instance: FastAPI): # Renamed app to app_instance to avoid conflict
    logger.info("Application startup...")
    try:
        await init_redis()
        # Store the task in the application state so it can be accessed during shutdown
        app_instance.state.fetch_klines_task = asyncio.create_task(fetch_and_publish_klines())
        # Start email alert monitoring
        from email_alert_service import alert_service
        app_instance.state.alert_monitor_task = asyncio.create_task(alert_service.monitor_alerts())
        # The bybit_realtime_feed_listener is conceptual for a shared WS connection.
        # The /stream/live/{symbol} endpoint now creates its own Bybit WS per client.
        # If you intend for bybit_realtime_feed_listener to be a shared connection
        # that feeds into Redis (as it was before the direct WS endpoint change),
        # then you would uncomment its invocation here.
        # asyncio.create_task(bybit_realtime_feed_listener())
        logger.info("Background task (fetch_and_publish_klines) started.")
    except Exception as e:
        logger.error(f"Failed to initialize Redis or start background tasks: {e}", exc_info=True)
        app_instance.state.fetch_klines_task = None # Ensure it's None on failure
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
    
    # Cancel email alert monitoring
    alert_task = getattr(app_instance.state, 'alert_monitor_task', None)
    if alert_task:
        alert_task.cancel()
        try:
            await alert_task
        except asyncio.CancelledError:
            logger.info("Email alert monitoring task cancelled")
    
    if redis_client:
        await redis_client.close()
        logger.info("Redis connection closed.")

# Initialize app with lifespan manager
# This is the single point of FastAPI app initialization
app = FastAPI(lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Add ProxyHeadersMiddleware to trust headers from Nginx
# Replace "IP_OF_NGINX_SERVER_A" with the actual IP address of your Nginx server (Server A)
# If Nginx is on the same machine and proxying to 127.0.0.1, you might use "127.0.0.1"
# If Nginx is on a different machine, use its IP as seen by Server B.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["IP_OF_NGINX_SERVER_A", "192.168.1.20"]) # Add Nginx IP here

# Middleware to add cache-control headers, similar to @app.after_request
@app.middleware("http")
async def add_no_cache_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    # Conditionally add headers, e.g., if in debug mode.
    # You can set the FASTAPI_DEBUG environment variable to "true" when running in debug.
    # Uvicorn's reload=True implies a development/debug environment.
    if os.getenv("FASTAPI_DEBUG", "False").lower() == "true" or app.extra.get("debug_mode", False):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "-1"
    return response

def require_valid_certificate(request: Request):
    """
    Dependency function to enforce client certificate validation on a specific route.
    To be used with `Depends()` in a route decorator.
    It checks for headers set by a reverse proxy (e.g., Nginx) performing mTLS.
    """
    client_verify_status = request.headers.get("X-SSL-Client-Verify")

    # Case 1: A valid certificate was presented and verified by the proxy.
    if client_verify_status == "SUCCESS":
        client_subject_dn = request.headers.get("X-SSL-Client-S-DN")
        client_full_cert_pem = request.headers.get("X-SSL-Client-Cert")


        if not client_full_cert_pem:
            logger.warning(f"mTLS SUCCESS but 'X-SSL-Client-Cert' header missing. Subject: {client_subject_dn}")
            raise HTTPException(status_code=403, detail="Client certificate PEM not provided by proxy.")

        try:
            cert = x509.load_pem_x509_certificate(client_full_cert_pem.encode('utf-8'))
            if str(cert.subject) not in creds.TRUSTED_CLIENT_CERT_SUBJECTS:
                logger.warning(f"Unauthorized client certificate subject: {cert.subject}")
                raise HTTPException(status_code=403, detail="Client certificate not authorized.")
            logger.info(f"Client authenticated and authorized via mTLS. Subject: {cert.subject}")
            return True # Indicate success
        except Exception as e:
            logger.error(f"Error processing client certificate: {e}. Subject: {client_subject_dn}", exc_info=True)
            raise HTTPException(status_code=403, detail="Invalid or unprocessable client certificate.")

    # Case 2: An invalid certificate was presented.
    elif client_verify_status and "FAILED" in client_verify_status:
        client_subject_dn = request.headers.get("X-SSL-Client-S-DN", "N/A")
        logger.warning(f"Client certificate verification FAILED by proxy. Subject: {client_subject_dn}, Status: {client_verify_status}")
        raise HTTPException(status_code=403, detail="Client certificate verification failed.")

    # Case 3: No certificate was presented.
    else:
        logger.warning(f"Client certificate not present.")
        raise HTTPException(status_code=403, detail="Client certificate not present.")

def require_valid_google_session(request: Request):
    """Dependency to check for a valid Google account session."""
    # Implement session check (e.g., check for a session cookie)
    # If session is invalid, raise HTTPException(status_code=403, detail="Invalid Google session")
    # Replace this with your actual session validation logic
    return True  # Placeholder: Always returns True, needs actual session logic


# Mount static files and templates


# This must happen after `app` is defined and before routes that might use templates.
static_files_path = Path("static") # Define path for clarity
static_files_path.mkdir(exist_ok=True) # Ensure static directory exists
app.mount("/static", StaticFiles(directory=static_files_path), name="static")
templates = Jinja2Templates(directory="templates")


# Default settings structure for a symbol when not found in Redis
DEFAULT_SYMBOL_SETTINGS = { # Default settings for a new symbol
    'resolution': '1d',   # Default resolution
    'range': '30d',       # Default time range dropdown value
    'xAxisMin': None,
    'xAxisMax': None,
    'yAxisMin': None,
    'yAxisMax': None,
    'activeIndicators': [], 
    'liveDataEnabled': True,
    'streamDeltaTime': 1,         # New default for live stream update interval (seconds)
    'useLocalOllama': False,
    'localOllamaModelName': None, # New default
    'showAgentTrades': False      # New default for showing agent trades
}

# Redis connection settings
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_PASSWORD = None
REDIS_TIMEOUT = 10 # Increased socket timeout
REDIS_RETRY_COUNT = 3
REDIS_RETRY_DELAY = 1


# Define TRADING_SYMBOL and TRADING_TIMEFRAME before they are used in Redis key prefixes
TRADING_SYMBOL = "BTCUSDT" # Symbol to trade for background tasks and AI defaults
TRADING_TIMEFRAME = "5m" # Timeframe for background tasks and AI defaults

REDIS_LAST_SELECTED_SYMBOL_KEY = "global_settings:last_selected_symbol"


# Constants - Define these before they are used by TimeframeConfig
SUPPORTED_SYMBOLS = ["BTCUSDT", "XMRUSDT", "ETHUSDT", "SOLUSDT", "SUIUSDT", "PAXGUSDT", "BNBUSDT", "ADAUSDT"]
SUPPORTED_RESOLUTIONS = ["1m", "5m", "1h", "1d", "1w"]
SUPPORTED_RANGES = [
    {"value": "1h", "label": "1h"},
    {"value": "8h", "label": "8h"},
    {"value": "24h", "label": "24h"},
    {"value": "3d", "label": "3d"},
    {"value": "7d", "label": "7d"},
    {"value": "30d", "label": "30d"},
    {"value": "3m", "label": "3M"}, # Approximately 3 * 30 days
    {"value": "6m", "label": "6M"}, # Approximately 6 * 30 days
    {"value": "1y", "label": "1Y"}, # Approximately 365 days
    {"value": "3y", "label": "3Y"}, # Approximately 3 * 365 days
]

REDIS_OPEN_INTEREST_KEY_PREFIX = f"zset:open_interest:{TRADING_SYMBOL}:{TRADING_TIMEFRAME}" # Dedicated key for Open Interest data

def get_sorted_set_oi_key(symbol: str, resolution: str) -> str:
    return f"zset:open_interest:{symbol}:{resolution}"

def fetch_open_interest_from_bybit(symbol: str, interval: str, start_ts: int, end_ts: int) -> list[Dict[str, Any]]:
    """Fetches Open Interest data from Bybit."""
    #logger.info(f"Fetching Open Interest for {symbol} {interval} from {datetime.fromtimestamp(start_ts, timezone.utc)} to {datetime.fromtimestamp(end_ts, timezone.utc)}")
    all_oi_data: list[Dict[str, Any]] = []
    current_start = start_ts
    
    # Bybit's get_open_interest intervalTime parameter has specific values.
    # We assume TRADING_TIMEFRAME (e.g., "5m") maps to a valid intervalTime like "5min".
    # This mapping needs to be consistent with what Bybit's API expects for `intervalTime`.
    oi_interval_map = {"1m": "5min", "5m": "5min", "1h": "1h", "1d": "1d", "1w": "1d"} # "1w" might need "1d" OI
    bybit_oi_interval = oi_interval_map.get(interval, "5min") # Default to 5min if not found

    # Convert interval string to seconds for calculation (e.g., "5min" -> 300 seconds)
    oi_interval_seconds_map = {"5min": 300, "15min": 900, "30min": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
    interval_seconds = oi_interval_seconds_map.get(bybit_oi_interval)
    if not interval_seconds:
        logger.error(f"Unsupported Open Interest interval for calculation: {bybit_oi_interval}")
        return []

    while current_start < end_ts:
        # Bybit get_open_interest limit is 200 per request
        batch_end = min(current_start + (200 * interval_seconds) - 1, end_ts)
        logger.debug(f"  Fetching OI batch: {datetime.fromtimestamp(current_start, timezone.utc)} to {datetime.fromtimestamp(batch_end, timezone.utc)}")
        try:
            response = session.get_open_interest(
                category="linear", # Assuming linear perpetuals
                symbol=symbol,
                intervalTime=bybit_oi_interval, # Use the string interval like "5min"
                start=current_start * 1000, # Bybit expects milliseconds
                end=batch_end * 1000,       # Bybit expects milliseconds
                limit=200
            )
        except Exception as e:
            logger.error(f"Bybit API request for Open Interest failed: {e}")
            break

        if response.get("retCode") != 0:
            logger.error(f"Bybit API error for Open Interest: {response.get('retMsg', 'Unknown error')}")
            break

        list_data = response.get("result", {}).get("list", [])
        if not list_data:
            logger.info("  No more Open Interest data available from Bybit for this range.")
            break
        
        # Data is usually newest first, reverse to get chronological order
        batch_oi = []
        for item in reversed(list_data):
            batch_oi.append({
                "time": int(item["timestamp"]) // 1000, # Convert ms to seconds
                "open_interest": float(item["openInterest"])
            })
        all_oi_data.extend(batch_oi)
        
        if not batch_oi or len(list_data) < 200: # No more data or last page
            break
        
        # Next query starts after the last fetched item's timestamp
        last_fetched_ts_in_batch = batch_oi[-1]["time"]
        current_start = last_fetched_ts_in_batch + interval_seconds
        
    all_oi_data.sort(key=lambda x: x["time"]) # Ensure chronological order
    #logger.info(f"Total Open Interest data fetched from Bybit: {len(all_oi_data)}")
    return all_oi_data

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
                await pipe.zadd(sorted_set_key, {data_str: timestamp}) # type: ignore
            await pipe.execute()
        # Trim the sorted set to keep a manageable number of recent entries.
        max_sorted_set_entries = 5000 # Same as klines
        await redis.zremrangebyrank(sorted_set_key, 0, -(max_sorted_set_entries + 1)) # type: ignore
        #logger.info(f"Successfully cached {len(oi_data)} Open Interest entries for {symbol} {resolution}")
    except Exception as e:
        logger.error(f"Error caching Open Interest data: {e}", exc_info=True)

def calculate_open_interest(df_input: pd.DataFrame) -> Dict[str, Any]:
    df = df_input.copy()
    original_time_index = df.index.to_series()
    oi_col = 'open_interest' # This column should already exist from _prepare_dataframe
    if oi_col not in df.columns:
        logger.warning(f"Open Interest column '{oi_col}' not found in DataFrame. Cannot calculate.")
        return {"t": [], "open_interest": []}
    return _extract_results(df, [oi_col], original_time_index)


# Ensure Bybit resolution map covers all supported resolutions
BYBIT_RESOLUTION_MAP = {
    "1m": "1", "5m": "5", "1h": "60", "1d": "D", "1w": "W"
}

# Initialize Redis client (using AsyncRedis for consistency)
redis_client: Optional[AsyncRedis] = None

async def init_redis():
    """Initialize Redis connection."""
    global redis_client
    try:
        redis_client = AsyncRedis (
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            decode_responses=True,
            socket_timeout=REDIS_TIMEOUT,
            retry_on_timeout=True # Enable retrying on socket timeouts
        )
        await redis_client.ping()
        logger.info("Successfully connected to Redis")
        return redis_client
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        logger.error("Run this to start it on wsl2: cmd /c wsl --exec sudo service redis-server start && Exit /B 5")
        redis_client = None
        raise

async def get_redis_connection() -> AsyncRedis:
    """Get a Redis connection."""
    global redis_client
    if redis_client is None:
        try:
            redis_client = await init_redis()
        except Exception: 
            logger.critical("CRITICAL: Redis connection could not be established in get_redis_connection.")
            logger.critical("Run this to start it on wsl2: cmd /c wsl --exec sudo service redis-server start && Exit /B 5")
            
            raise 
    if redis_client is None: 
        raise Exception("Redis client is None after attempting initialization.")
    return redis_client


@dataclass(frozen=True)
class BybitCredentials:
    api_key: str
    api_secret: str
    TRUSTED_CLIENT_CERT_SUBJECTS: List[str]
    GOOGLE_CLIENT_ID: str
    DEEPSEEK_API_KEY: str
    GEMINI_API_KEY: str
    SMTP_SERVER: str
    SMTP_PORT: int
    gmailEmail: str
    gmailPwd: str
    GOOGLE_CLIENT_SECRET: str

    @classmethod
    def from_file(cls, path: Path) -> "BybitCredentials":
        if not path.is_file():
            logger.warning(f"Credentials file not found at {path}. Using placeholder credentials.")
            return cls(
                api_key="YOUR_BYBIT_API_KEY",
                api_secret="YOUR_BYBIT_API_SECRET",
                TRUSTED_CLIENT_CERT_SUBJECTS=[],
                GOOGLE_CLIENT_ID="",
                DEEPSEEK_API_KEY="",
                GEMINI_API_KEY="",
                SMTP_SERVER="",
                SMTP_PORT=0,
                gmailEmail="",
                gmailPwd="",
                GOOGLE_CLIENT_SECRET=""
            )
        
        creds_text = path.read_text(encoding="utf-8")
        try:
            creds_json = json.loads(creds_text)
            return cls(
                api_key=creds_json["kljuc"], 
                api_secret=creds_json["geslo"], 
                TRUSTED_CLIENT_CERT_SUBJECTS=creds_json.get("TRUSTED_CLIENT_CERT_SUBJECTS", []), 
                DEEPSEEK_API_KEY=creds_json.get("DEEPSEEK_API_KEY"), 
                GEMINI_API_KEY=creds_json.get("GEMINI_API_KEY"),
                GOOGLE_CLIENT_ID=creds_json.get("GOOGLE_CLIENT_ID"),
                GOOGLE_CLIENT_SECRET=creds_json.get("GOOGLE_CLIENT_SECRET"),
                SMTP_SERVER=creds_json.get("SMTP_SERVER"),
                SMTP_PORT=creds_json.get("SMTP_PORT", 0),
                gmailEmail=creds_json.get("gmailEmail"),
                gmailPwd=creds_json.get("gmailPwd")
                )
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Error reading credentials file {path}: {e}. Using placeholder credentials.")
            return cls(
                api_key="YOUR_BYBIT_API_KEY",
                api_secret="YOUR_BYBIT_API_SECRET",
                TRUSTED_CLIENT_CERT_SUBJECTS=[],
                GOOGLE_CLIENT_ID="",
                DEEPSEEK_API_KEY="",
                GEMINI_API_KEY="",
                SMTP_SERVER="",
                SMTP_PORT=0,
                gmailEmail="",
                gmailPwd="",
                GOOGLE_CLIENT_SECRET=""
            )


class KlineData(TypedDict):
    time: int
    open: float
    high: float
    low: float
    close: float
    vol: float

class DrawingData(BaseModel):
    symbol: str
    type: str
    start_time: int
    end_time: int
    start_price: float
    end_price: float
    subplot_name: str # Identifies the main plot or subplot (e.g., "BTCUSDT" or "BTCUSDT-MACD")
    resolution: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None # New field for additional properties

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

@dataclass(frozen=True)
class TimeframeConfig:
    # Use the global SUPPORTED_RESOLUTIONS, converted to a tuple
    supported_resolutions: tuple[str, ...] = field(default_factory=lambda: tuple(SUPPORTED_RESOLUTIONS))
    # Use the global BYBIT_RESOLUTION_MAP
    resolution_map: dict[str, str] = field(default_factory=lambda: BYBIT_RESOLUTION_MAP)

creds = BybitCredentials.from_file(Path("c:/git/VidWebServer/authcreds.json"))
timeframe_config = TimeframeConfig()
data_dir = Path("data")
data_dir.mkdir(exist_ok=True)


for symbol_val_init in SUPPORTED_SYMBOLS: # Renamed to avoid conflict
    symbol_dir = data_dir / symbol_val_init
    symbol_dir.mkdir(exist_ok=True)

session = HTTP(
    api_key=creds.api_key,
    api_secret=creds.api_secret,
    testnet=False,
    recv_window=20000,
    max_retries=1 # Set max_retries to 0 to disable retries
)

# Configure Gemini API key globally
genai.configure(api_key=creds.GEMINI_API_KEY)

def get_redis_key(symbol: str, resolution: str, timestamp: int) -> str:
    timeframe_seconds = get_timeframe_seconds(resolution)
    aligned_ts = (timestamp // timeframe_seconds) * timeframe_seconds
    return f"kline:{symbol}:{resolution}:{aligned_ts}"

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

async def get_cached_klines(symbol: str, resolution: str, start_ts: int, end_ts: int) -> list[KlineData]:
    try:
        redis = await get_redis_connection()
        sorted_set_key = get_sorted_set_key(symbol, resolution)
        logger.info(f"Querying sorted set '{sorted_set_key}' for range [{start_ts}, {end_ts}]")

        klines_data_redis = await redis.zrangebyscore( # Renamed klines_data to klines_data_redis
            sorted_set_key,
            min=start_ts,
            max=end_ts,
            withscores=False # type: ignore
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
                    logger.info(f"All members in '{sorted_set_key}' (first 5 shown if many):")
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
                cached_data.append(parsed_data) # type: ignore
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON: {e}. Raw data: {data_item}")
                continue
        
        logger.info(f"Found {len(cached_data)} cached klines for {symbol} {resolution} between {start_ts} and {end_ts}")
        return cached_data
    except Exception as e:
        logger.error(f"Error in get_cached_klines: {e}", exc_info=True)
        return []

async def cache_klines(symbol: str, resolution: str, klines: list[KlineData]) -> None:
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
        unique_klines_for_caching: Dict[int, KlineData] = {}
        for k in klines:
            unique_klines_for_caching[k['time']] = k 
        
        # Now, get the list of unique kline objects to process.
        # Sorting by time is good practice, though the Redis operations for each timestamp are independent.
        klines_to_process = sorted(list(unique_klines_for_caching.values()), key=lambda x: x['time'])

        pipeline_batch_size = 500  # Execute pipeline every N klines
        sorted_set_key = get_sorted_set_key(symbol, resolution)
        async with redis.pipeline() as pipe:
            for kline in klines_to_process: # Iterate over the de-duplicated and sorted klines
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
                await pipe.zadd(sorted_set_key, {data_str: timestamp}) # type: ignore

                # Execute in batches
                if len(pipe) >= pipeline_batch_size * 3: # Each kline adds 3 commands (setex, zremrangebyscore, zadd)
                    await pipe.execute()
            await pipe.execute() # Execute any remaining commands in the pipeline
        
        # Trim the sorted set to keep a manageable number of recent klines.
        max_sorted_set_entries = 5000 # Adjust as needed based on typical query ranges and resolutions
        await redis.zremrangebyrank(sorted_set_key, 0, -(max_sorted_set_entries + 1)) # type: ignore
        #logger.info(f"Successfully cached {len(klines_to_process)} unique klines for {symbol} {resolution}")
    except Exception as e:
        logger.error(f"Error caching data: {e}", exc_info=True)

def get_timeframe_seconds(timeframe: str) -> int:
    multipliers = {"1m": 60, "5m": 300, "1h": 3600, "1d": 86400, "1w": 604800} # Added 1m
    return multipliers.get(timeframe, 3600) 

def format_kline_data(bar: list[Any]) -> KlineData:
    return {
        "time": int(bar[0]) // 1000,
        "open": float(bar[1]),
        "high": float(bar[2]),
        "low": float(bar[3]),
        "close": float(bar[4]),
        "vol": float(bar[5])
    }

def fetch_klines_from_bybit(symbol: str, resolution: str, start_ts: int, end_ts: int) -> list[KlineData]:
    #logger.info(f"Fetching klines for {symbol} {resolution} from {datetime.fromtimestamp(start_ts, timezone.utc)} to {datetime.fromtimestamp(end_ts, timezone.utc)}")
    all_klines: list[KlineData] = []
    current_start = start_ts
    timeframe_seconds = get_timeframe_seconds(resolution)
    
    while current_start < end_ts:
        batch_end = min(current_start + (1000 * timeframe_seconds) -1 , end_ts) 
        #logger.debug(f"Fetching batch: {datetime.fromtimestamp(current_start, timezone.utc)} to {datetime.fromtimestamp(batch_end, timezone.utc)}")
        try:
            response = session.get_kline(
                category="linear", symbol=symbol,
                interval=timeframe_config.resolution_map[resolution],
                start=current_start * 1000, end=batch_end * 1000, limit=1000
            )
        except Exception as e:
            logger.error(f"Bybit API request failed: {e}")
            break 
        
        if response.get("retCode") != 0:
            logger.error(f"Error fetching data from Bybit: {response.get('retMsg', 'Unknown error')}")
            break
        
        bars = response.get("result", {}).get("list", [])
        if not bars:
            logger.info("No more data available from Bybit for this range.")
            break
        
        batch_klines = [format_kline_data(bar) for bar in reversed(bars)]
        all_klines.extend(batch_klines)
        
        if not batch_klines: 
            logger.warning("Batch klines became empty after formatting, stopping fetch.")
            break

        last_fetched_ts = batch_klines[-1]["time"]
        if len(bars) < 1000 or last_fetched_ts >= batch_end:
            break 
        current_start = last_fetched_ts + timeframe_seconds 
    
    all_klines.sort(key=lambda x: x["time"])
    #logger.info(f"Total klines fetched from Bybit: {len(all_klines)}")
    return all_klines

def get_stream_key(symbol: str, resolution: str) -> str:
    return f"stream:kline:{symbol}:{resolution}"

def get_sorted_set_key(symbol: str, resolution: str) -> str:
    return f"zset:kline:{symbol}:{resolution}"

async def stream_klines(symbol: str, resolution: str, request: Request) -> EventSourceResponse:
    async def event_generator() -> AsyncGenerator[Dict[str, str], None]:
        try:
            redis = await get_redis_connection()
            stream_key = get_stream_key(symbol, resolution)
            group_name = f"tradingview:{symbol}:{resolution}"
            consumer_id = f"consumer:{uuid.uuid4()}"
            try:
                await redis.xgroup_create(stream_key, group_name, id='0', mkstream=True) # type: ignore
            except Exception as e:
                if "BUSYGROUP" not in str(e): raise
            
            last_id = '0-0' 
            while True:
                if await request.is_disconnected():
                    logger.info(f"Client disconnected from SSE stream {symbol}/{resolution}. Stopping generator.")
                    break
                try:
                    messages = await redis.xreadgroup( # type: ignore
                        group_name, consumer_id, {stream_key: ">"}, count=10, block=5000 # 5 second block
                    )
                    if messages:
                        for _stream_name, message_list in messages:
                            for message_id, message_data_dict in message_list:
                                try:
                                    kline_json_str = message_data_dict.get('data')
                                    if kline_json_str:
                                        yield {"event": "message", "data": kline_json_str} 
                                        await redis.xack(stream_key, group_name, message_id) # type: ignore
                                    else:
                                        logger.warning(f"Message {message_id} has no 'data' field: {message_data_dict}")
                                except Exception as e:
                                    logger.error(f"Error processing message {message_id}: {e}", exc_info=True)
                                    continue
                    # No need for asyncio.TimeoutError explicitly here if xreadgroup block handles it by returning empty
                except Exception as e: # Catch other errors like Redis connection issues
                    logger.error(f"Error in SSE event generator loop for {symbol}/{resolution}: {e}", exc_info=True)
                    await asyncio.sleep(1) # Wait a bit before retrying on general errors
        except Exception as e:
            logger.error(f"Fatal error in SSE event generator setup for {symbol}/{resolution}: {e}", exc_info=True)
            try:
                yield {"event": "error", "data": json.dumps({"error": str(e)})}
            except Exception: # If yielding error also fails (e.g. client disconnected)
                pass
        finally:
            logger.info(f"SSE event generator for {symbol}/{resolution} finished.")
    return EventSourceResponse(event_generator())

async def publish_resolution_kline(symbol: str, resolution: str, kline_data: dict) -> None:
    try:
        redis = await get_redis_connection()
        stream_key = get_stream_key(symbol, resolution)
        sorted_set_key = get_sorted_set_key(symbol, resolution)
        kline_json_str = json.dumps(kline_data)

        await redis.xadd(stream_key, {"data": kline_json_str}, maxlen=1000) # type: ignore
        await redis.zadd(sorted_set_key, {kline_json_str: kline_data["time"]}) # type: ignore
        await redis.zremrangebyrank(sorted_set_key, 0, -1001) # type: ignore
    except Exception as e:
        logger.error(f"Error publishing resolution kline to Redis: {e}", exc_info=True)

async def publish_live_data_tick(symbol: str, live_data: dict) -> None:
    try:
        redis = await get_redis_connection()
        live_stream_key = f"live:tick:{symbol}"
        await redis.xadd(live_stream_key, {"data": json.dumps(live_data)}, maxlen=2000) # type: ignore
    except Exception as e:
        logger.error(f"Error publishing live tick data to Redis: {e}", exc_info=True)

@never_cache
@app.get("/")
async def chart_page(request: Request):
    client_host = request.client.host if request.client else "Unknown"
    authenticated = False  # Default to False
    if (os.environ['COMPUTERNAME'] == "MAŠINA"):
        authenticated = True
        request.session["authenticated"] = True
        request.session["email"] = "vid.zivkovic@gmail.com"
    elif(os.environ['COMPUTERNAME'] == "ASUSAMD"):
        authenticated = True
        request.session["authenticated"] = True
        request.session["email"] = "klemenzivkovic@gmail.com"
    else:
        if request.session.get('email') is None:
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

    response = templates.TemplateResponse("index.html", {"request": request, "authenticated": True}) # type: ignore
    return response
    
    
@app.get("/initial_chart_config")
async def initial_chart_config():
    """Returns initial configuration for chart dropdowns."""
    return JSONResponse({
        "symbols": SUPPORTED_SYMBOLS,
        "resolutions": SUPPORTED_RESOLUTIONS,
        "ranges": SUPPORTED_RANGES
    })

@app.get("/history")
async def history(symbol: str, resolution: str, from_ts: int, to_ts: int):
    try:
        logger.info(f"/history request: symbol={symbol}, resolution={resolution}, from_ts={from_ts}, to_ts={to_ts}")
        await get_redis_connection() 

        if symbol not in SUPPORTED_SYMBOLS:
            return JSONResponse({"s": "error", "errmsg": f"Unsupported symbol: {symbol}"}, status_code=400)
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

        klines = await get_cached_klines(symbol, resolution, from_ts, to_ts)
        
        should_fetch_from_bybit = False
        if not klines:
            should_fetch_from_bybit = True
            logger.info("No cached klines found. Fetching from Bybit.")
        else:
            cached_start_ts = klines[0]['time']
            cached_end_ts = klines[-1]['time']
            if cached_start_ts > from_ts or cached_end_ts < to_ts: # Check if cache covers the full requested range
                should_fetch_from_bybit = True
                logger.info(f"Cache does not fully cover requested range. Requested: {from_ts}-{to_ts}, Cached: {cached_start_ts}-{cached_end_ts}. Will fetch from Bybit to fill gaps.")

        kline_fetch_start_ts = from_ts # default values
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
            temp_klines_by_ts: Dict[int, KlineData] = {}
            for k_item in klines: # klines is already sorted by time
                temp_klines_by_ts[k_item['time']] = k_item # This overwrites, keeping the last seen for a timestamp
            
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

@app.route('/settings', methods=['GET', 'POST'])
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


    return f"drawings:{request.session.get('email')}:{symbol}"


def get_drawings_redis_key(symbol: str, request: Request) -> str:
    email = request.session.get("email")
    return f"drawings:{email}:{symbol}"

async def save_drawing(drawing_data: Dict[str, Any], request: Request) -> str:

    redis = await get_redis_connection()
    symbol = drawing_data["symbol"]
    if symbol not in SUPPORTED_SYMBOLS: raise ValueError(f"Unsupported symbol: {symbol}")
    key = get_drawings_redis_key(symbol, request)
    drawings_data_str = await redis.get(get_drawings_redis_key(symbol, request))
    drawings = json.loads(drawings_data_str) if drawings_data_str else []
    drawing_with_id = {**drawing_data, "id": str(uuid.uuid4())}
    drawings.append(drawing_with_id)
    await redis.set(key, json.dumps(drawings))

    return drawing_with_id["id"]

async def get_drawings(symbol: str, request: Request) -> List[Dict[str, Any]]:
    redis = await get_redis_connection()
    key = get_drawings_redis_key(symbol, request)

    drawings_data_str = await redis.get(key)
    return json.loads(drawings_data_str) if drawings_data_str else []
async def delete_drawing(symbol: str, drawing_id: str, request: Request) -> bool:
    redis = await get_redis_connection()
    key = get_drawings_redis_key(symbol, request)
    drawings_data_str = await redis.get(key)
    if not drawings_data_str: return False
    drawings = json.loads(drawings_data_str)
    original_len = len(drawings)
    drawings = [d for d in drawings if d.get("id") != drawing_id]
    if len(drawings) == original_len: return False 
    await redis.set(key, json.dumps(drawings))
    return True

async def update_drawing(symbol: str, drawing_id: str, drawing_data: DrawingData, request: Request) -> bool:
    redis = await get_redis_connection()
    key = get_drawings_redis_key(symbol, request)
    drawings_data_str = await redis.get(key)
    if not drawings_data_str: return False
    drawings = json.loads(drawings_data_str)
    found = False
    for i, drawing_item in enumerate(drawings): # Renamed drawing to drawing_item
        if drawing_item.get("id") == drawing_id:
            updated_drawing_dict = drawing_data.to_dict()
            updated_drawing_dict['id'] = drawing_id 
            drawings[i] = updated_drawing_dict
            found = True

            break
    if not found:
        logger.info(f"Drawing {drawing_id} not found.")
        return False

    
    await redis.set(key, json.dumps(drawings))
    logger.info(f"Drawing {drawing_id} updated.")

    return True

@never_cache
@app.post("/save_shape_properties/{symbol}/{drawing_id}")
async def save_shape_properties_api_endpoint(symbol: str, drawing_id: str, properties: Dict[str, Any], request: Request): 
    logger.info(f"POST /save_shape_properties/{symbol}/{drawing_id} request received with properties: {properties}")
    if symbol not in SUPPORTED_SYMBOLS:
        return JSONResponse({"status": "error", "message": f"Unsupported symbol: {symbol}"}, status_code=400)

    # Fetch the existing drawing to merge properties
    existing_drawings = await get_drawings(symbol, request)
    existing_drawing = next((d for d in existing_drawings if d.get("id") == drawing_id), None)
    
    if not existing_drawing:
        logger.warning(f"Shape {drawing_id} not found for symbol {symbol}.")
        return JSONResponse({"status": "error", "message": "Shape not found"}, status_code=404)
    
    # Create a DrawingData object from the existing drawing, then update properties
    try:
        drawing_data_instance = DrawingData(
            symbol=existing_drawing['symbol'],
            type=existing_drawing['type'],
            start_time=existing_drawing['start_time'],
            end_time=existing_drawing['end_time'],
            start_price=existing_drawing['start_price'],
            end_price=existing_drawing['end_price'],
            subplot_name=existing_drawing['subplot_name'],
            resolution=existing_drawing.get('resolution'),
            properties=existing_drawing.get('properties', {}) # Start with existing properties
        )
        # Merge new properties with existing ones
        if drawing_data_instance.properties is None:
            drawing_data_instance.properties = {}

        if properties:        
          drawing_data_instance.properties.update(properties) # type: ignore
        
    except KeyError as e:
        logger.error(f"Missing key in existing drawing data for {drawing_id}: {e}")
        return JSONResponse({"status": "error", "message": f"Malformed existing drawing data: {e}"}, status_code=500)
    except Exception as e:
        logger.error(f"Error creating DrawingData instance from existing data: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": f"Internal server error: {e}"}, status_code=500)
    
    updated = await update_drawing(symbol, drawing_id, drawing_data_instance, request)
    if not updated:
        return JSONResponse({"status": "error", "message": "Failed to update shape properties"}, status_code=500)
    
    logger.info(f"Shape {drawing_id} properties updated successfully.")
    return JSONResponse({"status": "success", "message": "Shape properties updated successfully"})

@never_cache
@app.get("/get_shape_properties/{symbol}/{drawing_id}")
async def get_shape_properties_api_endpoint(symbol: str, drawing_id: str, request: Request):
    logger.info(f"GET /get_shape_properties/{symbol}/{drawing_id} request received")
    
    # Validate that the symbol is supported
    if symbol not in SUPPORTED_SYMBOLS:
        return JSONResponse({"status": "error", "message": f"Unsupported symbol: {symbol}"}, status_code=400)

    # Retrieve all drawings for the symbol from Redis
    email = request.session.get("email")
    drawings_key = f"drawings:{email}:{symbol}"
    drawings_data_str = await redis_client.get(drawings_key)

    if not drawings_data_str:
        raise HTTPException(status_code=404, detail="No drawings found for this symbol")

    drawings = json.loads(drawings_data_str)

    # Find the specific drawing by ID
    drawing = next((d for d in drawings if d.get("id") == drawing_id), None)

    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    # Extract the properties from the found drawing
    properties = drawing.get("properties")

    if not properties:
        logger.info(f"No properties found for drawing {drawing_id}, returning empty dict")
        return JSONResponse(content={"status": "success", "properties": {}})

    return JSONResponse(content={"status": "success", "properties": properties})


@app.get("/symbols_list")
async def symbols_list_endpoint(): return JSONResponse(list(SUPPORTED_SYMBOLS))

@app.get("/config")
async def config_endpoint():
    return JSONResponse({
        "supported_resolutions": list(timeframe_config.supported_resolutions),
        "supports_search": False, "supports_group_request": False,
        "supports_marks": False, "supports_timescale_marks": False
    })

@app.get("/symbols")
async def symbols_endpoint(symbol: str):
    if symbol not in SUPPORTED_SYMBOLS:
        return JSONResponse({"s": "error", "errmsg": "Symbol not supported"}, status_code=404)
    return JSONResponse({
        "name": symbol, "ticker": symbol, "description": f"{symbol} Perpetual",
        "type": "crypto", "exchange": "Bybit", "session": "24x7", "timezone": "UTC",
        "minmovement": 1, "pricescale": 100, "has_intraday": True,
        "supported_resolutions": list(timeframe_config.supported_resolutions),
        "volume_precision": 2
    })

@app.get("/get_drawings/{symbol}")
async def get_drawings_api_endpoint(symbol: str, request: Request):
    if symbol not in SUPPORTED_SYMBOLS:
        return JSONResponse({"status": "error", "message": f"Unsupported symbol: {symbol}"}, status_code=400)    
    drawings = await get_drawings(symbol, request)
    return JSONResponse({"status": "success", "drawings": drawings})

@app.post("/save_drawing/{symbol}")
async def save_drawing_api_endpoint(symbol: str, drawing_data: DrawingData, request: Request): 
    if symbol not in SUPPORTED_SYMBOLS:
        return JSONResponse({"status": "error", "message": f"Unsupported symbol: {symbol}"}, status_code=400)
    drawing_dict = drawing_data.to_dict()
    drawing_dict['symbol'] = symbol # Ensure symbol from path is used
    drawing_id = await save_drawing(drawing_dict, request) 
    return JSONResponse({"status": "success", "id": drawing_id})

@app.delete("/delete_drawing/{symbol}/{drawing_id}")
async def delete_drawing_api_endpoint(symbol: str, drawing_id: str, request: Request): 
    if symbol not in SUPPORTED_SYMBOLS:
        return JSONResponse({"status": "error", "message": f"Unsupported symbol: {symbol}"}, status_code=400)
    deleted = await delete_drawing(symbol, drawing_id, request)
    if not deleted:
        return JSONResponse({"status": "error", "message": "Drawing not found"}, status_code=404)
    return JSONResponse({"status": "success"})

@app.put("/update_drawing/{symbol}/{drawing_id}")
async def update_drawing_api_endpoint(symbol: str, drawing_id: str, drawing_data: DrawingData, request: Request): 
    if symbol not in SUPPORTED_SYMBOLS:
        return JSONResponse({"status": "error", "message": f"Unsupported symbol: {symbol}"}, status_code=400)
    drawing_data.symbol = symbol # Ensure symbol from path is used in the Pydantic model
    updated = await update_drawing(symbol, drawing_id, drawing_data, request)
    if not updated:
        return JSONResponse({"status": "error", "message": "Drawing not found"}, status_code=404)
    return JSONResponse({"status": "success"})

@app.delete("/delete_all_drawings/{symbol}")
async def delete_all_drawings_api_endpoint(symbol: str, request: Request):
    logger.info(f"DELETE /delete_all_drawings/{symbol} request received.")
    if symbol not in SUPPORTED_SYMBOLS:
        logger.warning(f"DELETE /delete_all_drawings: Unsupported symbol: {symbol}")
        return JSONResponse({"status": "error", "message": f"Unsupported symbol: {symbol}"}, status_code=400)
    try:
        redis = await get_redis_connection()
        key = get_drawings_redis_key(symbol, request)
        deleted_count = await redis.delete(key) # delete returns the number of keys deleted
        logger.info(f"DELETE /delete_all_drawings/{symbol}: Deleted {deleted_count} Redis key(s).")
        return JSONResponse({"status": "success", "deleted_count": deleted_count})
    except Exception as e:
        logger.error(f"Error deleting all drawings for {symbol} from Redis: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": "Error deleting drawings"}, status_code=500)

# Define the list of available indicators
AVAILABLE_INDICATORS = [
    {"id": "macd", "name": "MACD", "params": {"short_period": 12, "long_period": 26, "signal_period": 9}},
    {"id": "rsi", "name": "RSI", "params": {"period": 14}},
    {"id": "stochrsi_9_3", "name": "Stochastic RSI (9,3)", "params": {"rsi_period": 9, "stoch_period": 9, "k_period": 3, "d_period": 3}},
    {"id": "stochrsi_14_3", "name": "Stochastic RSI (14,3)", "params": {"rsi_period": 14, "stoch_period": 14, "k_period": 3, "d_period": 3}},
    {"id": "stochrsi_40_4", "name": "Stochastic RSI (40,4)", "params": {"rsi_period": 40, "stoch_period": 40, "k_period": 4, "d_period": 4}},
    {"id": "stochrsi_60_10", "name": "Stochastic RSI (60,10)", "params": {"rsi_period": 60, "stoch_period": 60, "k_period": 10, "d_period": 10}},
    {"id": "stochrsi_14_3", "name": "Stochastic RSI (14,3)", "params": {"rsi_period": 14, "stoch_period": 14, "k_period": 3, "d_period": 3}}, # Default for TradingAgent2
    {"id": "open_interest", "name": "Open Interest", "params": {}}, # New: Open Interest
    {"id": "jma", "name": "Jurik MA", "params": {"length": 7, "phase": 50, "power": 2}} # Add JMA
]

@app.get("/indicators")
async def get_available_indicators():
    """Returns the list of available technical indicators."""
    return JSONResponse(AVAILABLE_INDICATORS)


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
            id_info = id_token.verify_token(id_token_jwt, google_requests.Request(), GOOGLE_CLIENT_ID)
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

        request.session["authenticated"] = True
        request.session["email"] = user_email  # Store the user's email in the session
        logger.info(f"Login user in by google account. Session variable set: session[\"authenticated\"] = True, session[\"email\"] = {user_email}")


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




# --- Indicator Calculation Helper Functions ---
def _prepare_dataframe(klines: List[KlineData], open_interest_data: List[Dict[str, Any]]) -> Optional[pd.DataFrame]:
    if not klines:
        return None
    
    # De-duplicate klines by time before DataFrame creation
    unique_klines_map: Dict[int, KlineData] = {}
    for k in klines:
        unique_klines_map[k['time']] = k
        klines_deduplicated = sorted(list(unique_klines_map.values()), key=lambda x: x['time']) # This list is now guaranteed unique by time
    
    df_klines = pd.DataFrame(klines_deduplicated) # Use the de-duplicated list
    df_klines['time'] = pd.to_datetime(df_klines['time'], unit='s')
    df_klines = df_klines.set_index('time')
    # Ensure correct column names for pandas_ta
    df_klines.rename(columns={'vol': 'volume'}, inplace=True)
    # pandas_ta expects lowercase column names for ohlcv
    df_klines.columns = [col.lower() for col in df_klines.columns]

    # Process Open Interest data
    df_oi = pd.DataFrame()
    if open_interest_data:
        # De-duplicate OI data by time before DataFrame creation
        unique_oi_map: Dict[int, Dict[str, Any]] = {}
        for oi_entry in open_interest_data:
            unique_oi_map[oi_entry['time']] = oi_entry
        oi_data_deduplicated = sorted(list(unique_oi_map.values()), key=lambda x: x['time']) # This list is now guaranteed unique by time

        df_oi = pd.DataFrame(oi_data_deduplicated) # Use the de-duplicated list
        if 'time' in df_oi.columns:
            df_oi['time'] = pd.to_datetime(df_oi['time'], unit='s')
            df_oi = df_oi.set_index('time')
            df_oi.rename(columns={'open_interest': 'open_interest'}, inplace=True)

    # Merge klines and Open Interest data
    if not df_oi.empty:
        df_merged = pd.merge(df_klines, df_oi[['open_interest']], left_index=True, right_index=True, how='left')
        df_merged['open_interest'] = df_merged['open_interest'].ffill().bfill().fillna(0)
        return df_merged
    else:
        df_klines['open_interest'] = 0.0
        return df_klines

def _extract_results(df: pd.DataFrame, columns: List[str], original_time_index: pd.Series) -> Dict[str, Any]:
    """Extracts specified columns and aligns with original time index, handling NaNs by omission."""
    data_dict: Dict[str, Any] = {"t": []}
    
    # Create a temporary DataFrame with only the required columns and the original time index
    temp_df = df[columns].copy()
    temp_df['original_time'] = original_time_index # Add original timestamps for alignment
    
    # Drop rows where ALL specified indicator columns are NaN
    # This keeps rows if at least one indicator value is present
    temp_df.dropna(subset=columns, how='all', inplace=True)

    data_dict["t"] = (temp_df['original_time'].astype('int64') // 10**9).tolist() # Convert ns to s
    for col in columns:
        # Ensure the key in data_dict is simplified (e.g., 'macd' instead of 'MACD_12_26_9')
        simple_col_name = col.lower() # Start with the full lowercase name
        if "macdh" in col.lower(): simple_col_name = "histogram"
        elif "macds" in col.lower(): simple_col_name = "signal"
        elif "mac" in col.lower() and "macdh" not in col.lower() and "macds" not in col.lower(): simple_col_name = "macd" # Ensure 'macd' is prioritized
        elif "stochrsik" in col.lower(): simple_col_name = "stoch_k"
        elif "stochrsid" in col.lower(): simple_col_name = "stoch_d"
        elif "rsi" in col.lower() and "stoch" not in col.lower() : simple_col_name = "rsi"
        elif "open_interest" in col.lower(): simple_col_name = "open_interest"

        elif "jma_up" in col.lower(): simple_col_name = "jma_up"

        elif "jma_down" in col.lower(): simple_col_name = "jma_down"
        elif "jma" in col.lower() and "jma_up" not in col.lower() and "jma_down" not in col.lower(): simple_col_name = "jma" # Add JMA
        
        # Convert NaN to None for JSON compatibility
        raw_values = temp_df[col].tolist()
        processed_values = [None if pd.isna(val) else val for val in raw_values]
        data_dict[simple_col_name] = processed_values
    return data_dict

def calculate_macd(df_input: pd.DataFrame, short_period: int, long_period: int, signal_period: int) -> Dict[str, Any]:
    df = df_input.copy()
    original_time_index = df.index.to_series() # Keep original timestamps before any drops
    df.ta.macd(fast=short_period, slow=long_period, signal=signal_period, append=True)
    macd_col = f'MACD_{short_period}_{long_period}_{signal_period}'
    signal_col = f'MACDs_{short_period}_{long_period}_{signal_period}'
    hist_col = f'MACDh_{short_period}_{long_period}_{signal_period}'

    # Check if columns were actually created by pandas_ta
    if not all(col in df.columns for col in [macd_col, signal_col, hist_col]):
        logger.warning(f"MACD columns not found in DataFrame. Expected: {macd_col}, {signal_col}, {hist_col}. "
                       f"This might be due to insufficient data for the indicator periods. Available columns: {df.columns.tolist()}")
        return {"t": [], "macd": [], "signal": [], "histogram": []} # Return empty data structure
    return _extract_results(df, [macd_col, signal_col, hist_col], original_time_index)

def calculate_rsi(df_input: pd.DataFrame, period: int) -> Dict[str, Any]:
    df = df_input.copy()
    original_time_index = df.index.to_series()
    df.ta.rsi(length=period, append=True)
    rsi_col = f'RSI_{period}'

    # Check if column was actually created by pandas_ta
    if rsi_col not in df.columns:
        logger.warning(f"RSI column '{rsi_col}' not found in DataFrame after calculation. "
                       f"This might be due to insufficient data for the indicator period. Available columns: {df.columns.tolist()}")
        return {"t": [], "rsi": []} # Return empty data structure
    return _extract_results(df, [rsi_col], original_time_index)

def calculate_stoch_rsi(df_input: pd.DataFrame, rsi_period: int, stoch_period: int, k_period: int, d_period: int) -> Dict[str, Any]:
    df = df_input.copy()
    original_time_index = df.index.to_series()
    # pandas-ta uses rsi_length, roc_length (for stoch_period), k, d
    df.ta.stochrsi(rsi_length=rsi_period, length=stoch_period, k=k_period, d=d_period, append=True)
    k_col = f'STOCHRSIk_{rsi_period}_{stoch_period}_{k_period}_{d_period}'
    d_col = f'STOCHRSId_{rsi_period}_{stoch_period}_{k_period}_{d_period}'

    # Check if columns were actually created by pandas_ta
    if k_col not in df.columns or d_col not in df.columns:
        logger.warning(f"Stochastic RSI columns '{k_col}' or '{d_col}' not found in DataFrame after calculation. "
                       f"This might be due to insufficient data for the indicator periods. "
                       f"Available columns: {df.columns.tolist()}")
        return {"t": [], "stoch_k": [], "stoch_d": []} # Return empty data structure

    return _extract_results(df, [k_col, d_col], original_time_index)

def calculate_jma_indicator(df_input: pd.DataFrame, length: int = 7, phase: int = 50, power: int = 2) -> Dict[str, Any]:
    """Calculates the Jurik Moving Average (JMA) using the jurikIndicator.py module."""
    try:
        import jurikIndicator  # Import here to avoid circular dependency issues
        if not hasattr(jurikIndicator, 'calculate_jma'):

            logger.error("jurikIndicator.py does not have the 'calculate_jma' function.")
            return {"t": [], "jma": []}
        df = df_input.copy()
        original_time_index = df.index.to_series()
        jma_series = jurikIndicator.calculate_jma(df['close'], length, phase, power)
        df['jma'] = jma_series
        if 'jma' not in df.columns:
            return {"t": [], "jma": [], "jma_up":[], "jma_down":[]}

        df['jma_up'] = np.where(df['jma'] > df['jma'].shift(1), df['jma'], np.nan)
        df['jma_down'] = np.where(df['jma'] < df['jma'].shift(1), df['jma'], np.nan)

        return _extract_results(df, ['jma', 'jma_up', 'jma_down'], original_time_index)
    except ImportError:
        logger.error("Could not import jurikIndicator.py module.")
        return {"t": [], "jma": []}

# --- End Indicator Calculation ---


@app.get("/indicatorHistory")
async def indicator_history( # Refactor to pass indicator config as dict
    symbol: str, 
    resolution: str, 
    from_ts: int, 
    to_ts: int, 
    indicator_id: str, 
    simulation: Optional[bool] = False # Add simulation flag
):
    return await get_indicator_history(symbol, resolution, from_ts, to_ts, indicator_id, simulation)

async def get_indicator_history(
    symbol: str,
    resolution: str,
    from_ts: int,
    to_ts: int,
    indicator_id: str,
    simulation: Optional[bool] = False
):
    return await _get_indicator_history_implementation(symbol, resolution, from_ts, to_ts, indicator_id, simulation)

async def _get_indicator_history_implementation(
    symbol: str,
    resolution: str,
    from_ts: int,
    to_ts: int,
    indicator_id: str,
    simulation: Optional[bool] = False
):
    """
    Internal implementation for indicator history, refactored to handle JMA and other indicators.
    This version receives the indicator configuration details as a dictionary, improving flexibility.
    """
    
    # Split indicator_id to handle multiple indicators
    requested_indicator_ids = [id_str.strip() for id_str in indicator_id.split(',') if id_str.strip()]

    return await _calculate_and_return_indicators(symbol, resolution, from_ts, to_ts, requested_indicator_ids, simulation, indicator_id)

async def _calculate_and_return_indicators(symbol: str, resolution: str, from_ts: int, to_ts: int, requested_indicator_ids: List[str], simulation: Optional[bool] = False, indicator_id: Optional[str] = None):
    """
    Core logic to fetch klines, calculate indicators (including JMA), and return the results.
    """

    # indicator_id is now expected to be a comma-separated string of IDs
    logger.info(f"/indicatorHistory request: symbol={symbol}, resolution={resolution}, from_ts={from_ts}, to_ts={to_ts}, requested_ids={requested_indicator_ids}, simulation={simulation}")

    # Log from_ts and to_ts in human-readable format
    from_dt_str = datetime.fromtimestamp(from_ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    to_dt_str = datetime.fromtimestamp(to_ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    logger.info(f"Time range: from_ts={from_ts} ({from_dt_str}), to_ts={to_ts} ({to_dt_str})")

    if symbol not in SUPPORTED_SYMBOLS:
        return JSONResponse({"s": "error", "errmsg": f"Unsupported symbol: {symbol}"}, status_code=400)
    if resolution not in timeframe_config.supported_resolutions:
        return JSONResponse({"s": "error", "errmsg": f"Unsupported resolution: {resolution}"}, status_code=400)

    if not requested_indicator_ids:


        # Log from_ts and to_ts in human-readable format
        from_dt_str = datetime.fromtimestamp(from_ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        to_dt_str = datetime.fromtimestamp(to_ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        logger.info(f"Time range: from_ts={from_ts} ({from_dt_str}), to_ts={to_ts} ({to_dt_str})")

    # Validate all requested indicator IDs
    for req_id in requested_indicator_ids:
        if not next((item for item in AVAILABLE_INDICATORS if item["id"] == req_id), None):
            print(req_id)
            return JSONResponse({"s": "error", "errmsg": f"Unsupported indicator ID found: {req_id}"}, status_code=400)

    # Unconditionally calculate lookback needed for accurate indicator calculation
    max_lookback_periods = 0
    for req_id in requested_indicator_ids:
        config = next((item for item in AVAILABLE_INDICATORS if item["id"] == req_id), None)
        if config:
            current_indicator_lookback = 0
            if config["id"] == "macd":
                current_indicator_lookback = config["params"]["long_period"] + config["params"]["signal_period"]
            elif config["id"] == "rsi":
                current_indicator_lookback = config["params"]["period"]
            elif config["id"] == "open_interest":
                current_indicator_lookback = 0 # No specific lookback for OI itself
            elif config["id"].startswith("stochrsi"):
                current_indicator_lookback = config["params"]["rsi_period"] + config["params"]["stoch_period"] + config["params"]["d_period"]
            elif config["id"] == "jma":
                current_indicator_lookback = config["params"]["length"]  # JMA Length
            if current_indicator_lookback > max_lookback_periods:
                max_lookback_periods = current_indicator_lookback
    
    buffer_candles = 1
    min_overall_candles = 1
    lookback_candles_needed = max(max_lookback_periods + buffer_candles, min_overall_candles)
    timeframe_secs = get_timeframe_seconds(resolution)

    # Determine the kline fetch window based on lookback and original request's to_ts
    # The data for calculation must extend up to the original 'to_ts'.
    # The start of this data window needs to be early enough to satisfy 'lookback_candles_needed'
    # for the indicators to be valid at the original 'from_ts' (for non-simulation) or the target candle (for simulation).
    kline_fetch_start_ts = from_ts - (lookback_candles_needed * timeframe_secs)
    kline_fetch_end_ts = to_ts # This is the original 'to_ts' from the request

    logger.info(f"Mode (sim={simulation}): Original request from_ts={from_ts}, to_ts={to_ts}. Max lookback: {max_lookback_periods}, Candles needed: {lookback_candles_needed}. Effective kline fetch range for calculation: {kline_fetch_start_ts} to {kline_fetch_end_ts}")

    current_time_sec = int(datetime.now(timezone.utc).timestamp())
    # Clamp the fetch window
    final_fetch_from_ts = max(0, kline_fetch_start_ts)
    final_fetch_to_ts = max(0, min(kline_fetch_end_ts, current_time_sec if not simulation else kline_fetch_end_ts))

    if final_fetch_from_ts >= final_fetch_to_ts:
         logger.warning(f"Invalid effective time range after lookback adjustment and clamping: {final_fetch_from_ts} >= {final_fetch_to_ts}")
         return JSONResponse({"s": "no_data", "errmsg": "Invalid time range"})

    # Fetch klines and Open Interest (base data for indicators) using the final clamped fetch window
    klines = await get_cached_klines(symbol, resolution, final_fetch_from_ts, final_fetch_to_ts)
    if not klines or klines[0]['time'] > final_fetch_from_ts or klines[-1]['time'] < final_fetch_to_ts :
        bybit_klines = fetch_klines_from_bybit(symbol, resolution, final_fetch_from_ts, final_fetch_to_ts)
        if bybit_klines:
            await cache_klines(symbol, resolution, bybit_klines)
            klines = await get_cached_klines(symbol, resolution, final_fetch_from_ts, final_fetch_to_ts)
    
    # Filter klines to the exact final fetch window (should be redundant if cache/bybit fetch is precise)
    
    oi_data = await get_cached_open_interest(symbol, resolution, final_fetch_from_ts, final_fetch_to_ts)
    if not oi_data or oi_data[0]['time'] > final_fetch_from_ts or oi_data[-1]['time'] < final_fetch_to_ts:
        bybit_oi_data = fetch_open_interest_from_bybit(symbol, resolution, final_fetch_from_ts, final_fetch_to_ts)
        if bybit_oi_data:
            await cache_open_interest(symbol, resolution, bybit_oi_data)
            oi_data = await get_cached_open_interest(symbol, resolution, final_fetch_from_ts, final_fetch_to_ts)

    # Filter klines to the exact final fetch window (should be redundant if cache/bybit fetch is precise)
    # And filter OI data
    oi_data = [oi for oi in oi_data if final_fetch_from_ts <= oi['time'] <= final_fetch_to_ts]
    oi_data.sort(key=lambda x: x['time'])
        
    klines = [k for k in klines if final_fetch_from_ts <= k['time'] <= final_fetch_to_ts]    
    klines.sort(key=lambda x: x['time'])
    
    if not klines:
        logger.warning(f"No klines found for symbol {symbol} resolution {resolution} in effective fetch range {final_fetch_from_ts} to {final_fetch_to_ts} after fetching and filtering.")
        all_indicator_results_empty: Dict[str, Dict[str, Any]] = {}
        for current_indicator_id_str_empty in requested_indicator_ids:
            errmsg = f"No base kline data for calc range for {current_indicator_id_str_empty}"
            if simulation:
                errmsg += f" (sim target: {from_ts})" # Original from_ts is the sim target
            all_indicator_results_empty[current_indicator_id_str_empty] = {"s": "no_data", "errmsg": errmsg}
        return JSONResponse({"s": "ok", "data": all_indicator_results_empty})
        
    df_ohlcv = _prepare_dataframe(klines, oi_data)
    if df_ohlcv is None or df_ohlcv.empty:
        all_indicator_results_empty_df: Dict[str, Dict[str, Any]] = {}
        for current_indicator_id_str_empty_df in requested_indicator_ids:
             all_indicator_results_empty_df[current_indicator_id_str_empty_df] = {"s": "no_data", "errmsg": f"Failed to prepare DataFrame for {current_indicator_id_str_empty_df}"}
        logger.warning(f"DataFrame preparation failed for {symbol} {resolution} in effective fetch range {final_fetch_from_ts} to {final_fetch_to_ts}. Kline count: {len(klines)}, OI count: {len(oi_data)}")
        return JSONResponse({"s": "ok", "data": all_indicator_results_empty_df})

    logger.info(f"Prepared DataFrame for {symbol} {resolution} with {len(df_ohlcv)} rows for calculation range {final_fetch_from_ts} to {final_fetch_to_ts}.")

    all_indicator_results: Dict[str, Dict[str, Any]] = {}
    for current_indicator_id_str in requested_indicator_ids:
        indicator_config = next((item for item in AVAILABLE_INDICATORS if item["id"] == current_indicator_id_str), None)
        if not indicator_config: 
            all_indicator_results[current_indicator_id_str] = {"s": "error", "errmsg": f"Config not found for {current_indicator_id_str}"}
            continue

        try:
            indicator_data_full_calc_range: Optional[Dict[str, Any]] = None 
            params = indicator_config["params"]
            calc_id = indicator_config["id"]

            if calc_id == "macd": indicator_data_full_calc_range = calculate_macd(df_ohlcv.copy(), **params)
            elif calc_id == "rsi": indicator_data_full_calc_range = calculate_rsi(df_ohlcv.copy(), **params)
            elif calc_id.startswith("stochrsi"): indicator_data_full_calc_range = calculate_stoch_rsi(df_ohlcv.copy(), **params)
            elif calc_id == "open_interest": indicator_data_full_calc_range = calculate_open_interest(df_ohlcv.copy())
            elif calc_id == "jma": indicator_data_full_calc_range = calculate_jma_indicator(df_ohlcv.copy(), **params) # Add JMA
            elif calc_id == "rsi_sma_3":  # New: Handle rsi_sma_3 calculation
                # We'll compute RSI for the entire range if it wasn't already part of the request:
                if "rsi" not in requested_indicator_ids:
                    # Re-use calculate_rsi, but for the full range; avoids re-calculation later
                    rsi_data = calculate_rsi(df_ohlcv.copy(), period=14)
                    # To ensure alignment with our core calculations, re-attach to df_ohlcv
                    df_ohlcv['rsi'] = rsi_data['rsi']
                else:  # If RSI was requested, we can assume it's already been calculated
                    rsi_data = calculate_rsi(df_ohlcv.copy(), period=14) # Ensure you are using a standard RSI period 
                indicator_data_full_calc_range = calculate_rsi_sma(df_ohlcv.copy(), 3, rsi_data.get("rsi"))
            else: # Existing logic for unrecognized indicator
                all_indicator_results[current_indicator_id_str] = {"s": "error", "errmsg": f"Calc logic not implemented for {calc_id}"}
                continue
            
            final_processed_data: Optional[Dict[str, Any]] = None

            if indicator_data_full_calc_range and indicator_data_full_calc_range.get("t"):
                if simulation:
                    temp_signal_data = {}
                    original_t_series = indicator_data_full_calc_range.get("t", [])
                    
                    if calc_id == "macd":
                        signal_values = indicator_data_full_calc_range.get("signal")
                        temp_signal_data = {"t": original_t_series, "signal": signal_values} if signal_values is not None else {"t": [], "signal": []}
                    elif calc_id == "rsi":
                        rsi_values = indicator_data_full_calc_range.get("rsi")
                        temp_signal_data = {"t": original_t_series, "rsi": rsi_values} if rsi_values is not None else {"t": [], "rsi": []}
                    elif calc_id.startswith("stochrsi"):
                        stoch_d_values = indicator_data_full_calc_range.get("stoch_d")
                        temp_signal_data = {"t": original_t_series, "stoch_d": stoch_d_values} if stoch_d_values is not None else {"t": [], "stoch_d": []}
                    elif calc_id == "open_interest":
                        oi_values = indicator_data_full_calc_range.get("open_interest")
                        temp_signal_data = {"t": original_t_series, "open_interest": oi_values} if oi_values is not None else {"t": [], "open_interest": []}                        
                    else: 
                        temp_signal_data = indicator_data_full_calc_range # Should not happen if calc_id is valid

                    if temp_signal_data.get("t") and len(temp_signal_data["t"]) > 0 and \
                       any(val_list for key, val_list in temp_signal_data.items() if key != "t" and val_list is not None and len(val_list) > 0):
                        temp_signal_data["s"] = "ok"
                    else:
                        temp_signal_data = {"s": "no_data", "errmsg": f"No signal line data for {current_indicator_id_str} after filtering for simulation", "t": []}

                    original_status_str = temp_signal_data.get("s", "error")
                    original_errmsg_str = temp_signal_data.get("errmsg")
                    filtered_t_sim = []
                    data_series_keys = [key for key in temp_signal_data if key not in ["t", "s", "errmsg"]]
                    filtered_values_dict_sim: Dict[str, List[Any]] = {key: [] for key in data_series_keys}
                    found_target_candle_sim = False

                    for i, t_val_sim in enumerate(temp_signal_data.get("t", [])):
                        if t_val_sim == from_ts: # Original from_ts is the target for simulation
                            filtered_t_sim.append(t_val_sim)
                            for data_key in data_series_keys:
                                if data_key in temp_signal_data and i < len(temp_signal_data[data_key]):
                                    filtered_values_dict_sim[data_key].append(temp_signal_data[data_key][i])
                                else: 
                                    filtered_values_dict_sim[data_key].append(None)
                            found_target_candle_sim = True
                            break 
                    
                    if found_target_candle_sim and filtered_t_sim:
                        final_processed_data = {"t": filtered_t_sim, "s": original_status_str}
                        if original_errmsg_str: final_processed_data["errmsg"] = original_errmsg_str
                        for data_key in data_series_keys: final_processed_data[data_key] = filtered_values_dict_sim[data_key]
                    else:
                        logger.warning(f"Simulation: Target candle ts {from_ts} not found for {current_indicator_id_str}.")
                        final_processed_data = {"s": "no_data", "errmsg": f"Target candle {from_ts} not found for {current_indicator_id_str}", "t": []}
                
                else: # Not simulation - filter to original requested range [from_ts, to_ts]
                    original_status_str = "ok" # Assume 'ok' if calculation succeeded and data is present
                    original_errmsg_str = None # No error message by default for non-simulation success
                    
                    # If _extract_results put an 's' key, respect it, otherwise assume 'ok'
                    if "s" in indicator_data_full_calc_range:
                        original_status_str = indicator_data_full_calc_range["s"]
                        original_errmsg_str = indicator_data_full_calc_range.get("errmsg")

                    filtered_t_range = []
                    data_series_keys_range = [key for key in indicator_data_full_calc_range if key not in ["t", "s", "errmsg"]]
                    filtered_values_dict_range: Dict[str, List[Any]] = {key: [] for key in data_series_keys_range}
                    data_found_in_range = False

                    for i, t_val_range in enumerate(indicator_data_full_calc_range.get("t", [])):
                        if from_ts <= t_val_range <= to_ts: # Original request range
                            filtered_t_range.append(t_val_range)
                            for data_key in data_series_keys_range:
                                if data_key in indicator_data_full_calc_range and i < len(indicator_data_full_calc_range[data_key]):
                                    filtered_values_dict_range[data_key].append(indicator_data_full_calc_range[data_key][i])
                                else:
                                    filtered_values_dict_range[data_key].append(None)
                            data_found_in_range = True
                    
                    if data_found_in_range and filtered_t_range:
                        final_processed_data = {"t": filtered_t_range, "s": original_status_str}
                        if original_errmsg_str: final_processed_data["errmsg"] = original_errmsg_str
                        for data_key in data_series_keys_range: final_processed_data[data_key] = filtered_values_dict_range[data_key]
                    else:
                        logger.warning(f"Non-Simulation: No data found in range {from_ts}-{to_ts} for {current_indicator_id_str} after calculation and filtering.")
                        final_processed_data = {"s": "no_data", "errmsg": f"No data in range {from_ts}-{to_ts} for {current_indicator_id_str}", "t": []}
            else: 
                final_processed_data = {"s": "no_data", "errmsg": f"Initial calculation for {current_indicator_id_str} yielded no data", "t": []}

            if final_processed_data and final_processed_data.get("t") and len(final_processed_data["t"]) > 0 and final_processed_data.get("s") == "ok":
                status_to_set = final_processed_data.get("s", "error") 
                errmsg_to_set = final_processed_data.get("errmsg")
                payload_data = {k: v for k, v in final_processed_data.items() if k not in ["s", "errmsg"]}
                
                result_entry = {"s": status_to_set, **payload_data}
                if errmsg_to_set: result_entry["errmsg"] = errmsg_to_set
                all_indicator_results[current_indicator_id_str] = result_entry
            else:
                logger.warning(f"Indicator data for {current_indicator_id_str} (target_ts: {from_ts if simulation else f'{from_ts}-{to_ts}'}) resulted in no valid data points after all processing.")
                all_indicator_results[current_indicator_id_str] = {
                    "s": final_processed_data.get("s") if final_processed_data else "no_data", 
                    "errmsg": final_processed_data.get("errmsg") if final_processed_data else f"No data for {current_indicator_id_str} after processing"
                }

        except Exception as e:
            logger.error(f"Error processing indicator {current_indicator_id_str}: {e}", exc_info=True)
            all_indicator_results[current_indicator_id_str] = {"s": "error", "errmsg": f"Error processing indicator {current_indicator_id_str}: {str(e)}"}

    return JSONResponse({"s": "ok", "data": all_indicator_results})

def calculate_rsi_sma(df_input: pd.DataFrame, sma_period: int, rsi_values: List[float]) -> Dict[str, Any]:
    df = df_input.copy()
    original_time_index = df.index.to_series() # Store original index

    if len(rsi_values) < len(df.index):  # RSI values are shorter, pad with NaNs
        padding = [np.nan] * (len(df.index) - len(rsi_values))
        aligned_rsi_values = rsi_values + padding
        logger.warning(f"calculate_rsi_sma: Padding rsi_values (from {len(rsi_values)} to {len(aligned_rsi_values)}) with NaNs to match DataFrame index.")
    elif len(rsi_values) > len(df.index):  # RSI values are longer, truncate
        aligned_rsi_values = rsi_values[:len(df.index)]
        logger.warning(f"calculate_rsi_sma: Truncating rsi_values (from {len(rsi_values)} to {len(aligned_rsi_values)}) to match DataFrame index.")
    else:
        aligned_rsi_values = rsi_values  # Lengths already mat
        
    # Now, assign to the DataFrame
    df['rsi'] = aligned_rsi_values
    logger.info(f"calculate_rsi_sma: Assigned RSI column of length {len(df['rsi'])} (index length: {len(df.index)}) to DataFrame.")

    df[f'RSI_SMA_{sma_period}'] = df['rsi'].rolling(window=sma_period).mean()
    return _extract_results(df, [f'RSI_SMA_{sma_period}'], original_time_index)


def format_indicator_data_for_llm_as_dict(indicator_id: str, indicator_config_details: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Formats indicator data into a dictionary structure suitable for JSON embedding.
    data is like {'t': [...], 'value1': [...], 'value2': [...], 's': 'ok'}
    indicator_config_details is from AVAILABLE_INDICATORS
    """
    
    if not data or not data.get('t') or data.get('s') != 'ok':
        return {
            "indicator_name": indicator_config_details['name'],
            "params": indicator_config_details['params'],
            "status": "no_data",
            "error_message": "No valid data available for the selected range.",
            "values": []
        }
        
    # Determine column names from data keys, excluding 't', 's', 'errmsg'
    value_keys = [k for k in data.keys() if k not in ['t', 's', 'errmsg']]

    # Map internal keys to more readable names
    column_names_map = {
        "macd": "MACD", "signal": "Signal", "histogram": "Histogram",
        "rsi": "RSI",
        "open_interest": "OpenInterest",
        "jma": "JMA", # Add JMA
        "stoch_k": "StochK", "stoch_d": "StochD"
    }

    timestamps = data['t']
    values_by_key = {key: data[key] for key in value_keys}

    formatted_values = []
    for i, ts in enumerate(timestamps):
        dt_object = datetime.fromtimestamp(ts, timezone.utc)
        record: Dict[str, Any] = {"timestamp": dt_object.strftime('%Y-%m-%d %H:%M:%S')}
        for current_key in value_keys:
            value = values_by_key[current_key][i] if i < len(values_by_key[current_key]) else None # Use None for N/A
            record[column_names_map.get(current_key, current_key.capitalize())] = value
        formatted_values.append(record)

    return {
        "indicator_name": indicator_config_details['name'],
        "params": indicator_config_details['params'],
        "status": "ok",
        "values": formatted_values
    }

# --- AI Suggestion Endpoint ---
class AIRequest(BaseModel):
    image_data: str # Base64 encoded image string (without data:image/png;base64, prefix)
    question: str

# OLLAMA_API_URL = "http://localhost:11434/api/chat" # Old Ollama URL
#AI_MODEL_NAME = "granite3.2-vision" # Or your specific multimodal model if Gemma isn't directly handling images

# This AI_MODEL_NAME was likely for local Ollama.
# For the DeepSeek API, we'll use DEEPSEEK_API_MODEL_NAME defined below.
# AI_MODEL_NAME = "deepseek-r1:7b" # Example Ollama model name

# --- DeepSeek API Configuration ---
DEEPSEEK_API_KEY = creds.DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_API_MODEL_NAME = "deepseek-reasoner" # "deepseek-chat" or "deepseek-coder" or "deepseek-reasoner"

deepseek_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL, timeout=120.0) # Increased timeout
# --- End DeepSeek API Configuration ---

# --- Local Ollama Configuration (using OpenAI client) ---
LOCAL_OLLAMA_BASE_URL = "http://localhost:11434/v1" # Standard OpenAI-compatible endpoint for Ollama
LOCAL_OLLAMA_MODEL_NAME = "llama3" # Default local Ollama model if not specified by user
# No API key is typically needed for local Ollama with OpenAI client if Ollama doesn't require it.
local_ollama_client = OpenAI(base_url=LOCAL_OLLAMA_BASE_URL, api_key="ollama", timeout=120.0) # api_key can be anything non-empty
# --- End Local Ollama Configuration ---

# gemma3:12b
# llama3.2-vision:11b
# robinji/finance
# granite3.2-vision

#AI_MODEL_NAME = "sam860/deepseek-r1-0528-qwen3:8b" # Or your specific multimodal model if Gemma isn't directly handling images

# --- AI Suggestion Endpoint ---
class IndicatorConfigRequest(BaseModel):
    id: str
    # Params are fixed in AVAILABLE_INDICATORS, client only needs to send id

class AIRequest(BaseModel):
    symbol: str
    resolution: str
    xAxisMin: int  # timestamp
    xAxisMax: int  # timestamp
    activeIndicatorIds: List[str] # List of indicator IDs like "macd", "rsi"
    question: str
    use_local_ollama: bool = False
    local_ollama_model_name: Optional[str] = None
    use_gemini: bool = False # New field for Gemini

AI_SYSTEM_PROMPT_INSTRUCTIONS = """
You are an expert trading agent specializing in cryptocurrency analysis. Your primary function is to analyze textual market data (kline/candlestick and technical indicators) to suggest BUY, SELL, or HOLD actions.

You will be provided with the following textual data for a specific cryptocurrency pair and timeframe:
1.  **Open Interest**: The total number of outstanding derivative contracts. Rising OI can confirm a trend, while falling OI can signal a weakening trend.
2.  **Symbol**: The cryptocurrency pair (e.g., BTCUSDT).
3.  **Timeframe**: The chart timeframe (e.g., 1m, 5m, 1h, 1d).
4.  **Data Range (UTC)**: The start and end UTC timestamps for the provided data.

--- START KLINE DATA ---
--- END KLINE DATA ---

--- START INDICATOR DATA: INDICATOR_NAME (Indicator Full Name, Params: ...) ---
--- END INDICATOR DATA: INDICATOR_NAME ---

The market data will be provided as a JSON object embedded within this prompt, under the "--- MARKET DATA JSON ---" heading.
The JSON object will have the following structure:
{
  "kline_data": [
   {"date": "YYYY-MM-DD HH:MM:SS", "close": 0.0},
    // ... more kline data points, each with date and close price
  ],
  "indicator_data": [ // This is now a list of indicator objects
    {
      "indicator_name": "MACD",
      "params": {"short_period": 12, "long_period": 26, "signal_period": 9},
      "status": "ok" | "no_data",
      "error_message": "Optional error message if status is no_data",
      "values": [
        {"timestamp": "YYYY-MM-DD HH:MM:SS", "MACD": 0.0, "Signal": 0.0, "Histogram": 0.0},
        // ... more macd values
      ]
    },
    // ... more indicator objects if active
  ]
}

The latest data is at the end of the Kline and Indicator lists.

To generate your JSON response:
- The "price" field MUST be the 'Close' value from the LAST entry in the "--- START KLINE DATA ---" section.
- The "date" field MUST be the 'date' from the LAST entry in the "--- START KLINE DATA ---" section, formatted as YYYY-MM-DD HH:MM:SS.
- Your "trend_description" MUST be based on patterns observed in the "kline_data" array. To identify a trend, look for a series of at least 3-5 consecutive candles showing:
    - Uptrend: Higher highs and higher lows. Note the approximate start time and price.
    - Downtrend: Lower highs and lower lows. Note the approximate start time and price.
    - Consolidation/Sideways: Price trading within a relatively narrow range without clear higher highs/lows or lower highs/lows. Note the approximate range.
- Your "breakout_point_description" MUST reference specific price levels and timestamps from the "kline_data" array if a breakout is identified.
    - For an uptrend, a break might be a candle closing significantly below the recent series of higher lows, or forming a distinct lower high followed by a lower low.
    - For a downtrend, a break might be a candle closing significantly above the recent series of lower highs, or forming a distinct higher low followed by a higher high.
    - If no clear breakout is observed from kline data, state that clearly.
- Your "explanation" for "action" MUST reference specific values and timestamps from the "kline_data" array and relevant indicator objects in the "indicator_data" array. For example, if you mention MACD, state the MACD values and timestamp from its "values" array. If you mention RSI, state the RSI value and timestamp. Do not invent values; use only what is provided in the JSON.

Decision Logic to suggest trade:
Condition 1: Identify a price trend from the "kline_data" as described above.
Condition 2: Identify if the price is showing signs of breaking the current trend from the "kline_data" as described above (e.g., for an uptrend, forming a lower high then lower low; for a downtrend, forming a higher low then higher high).

Monitor the slowest Stochastic RSI (if provided, e.g., Stochastic RSI 60,10). When this indicator starts rising from an oversold condition (<20), it's a positive sign for a potential BUY. When it falls from an overbought condition (>80), it's a negative sign for a potential SELL.
Confirm with MACD (if provided): A BUY signal is strengthened when the MACD line crosses above the Signal line, ideally after price shows signs of breaking a downtrend and the slowest StochRSI is rising. A SELL signal is strengthened by a MACD line crossing below the Signal line after signs of breaking an uptrend and slowest StochRSI is falling.
RSI (if provided): RSI below 30-40 can indicate oversold (potential buy opportunity in an uptrend or reversal), and above 60-70 can indicate overbought (potential sell opportunity in a downtrend or reversal).

Decision Logic to suggest opening LONG position - BUY:
Price shows signs of breaking a prior downtrend or is in an established uptrend and rallying.
Stochastic RSI (slowest available, e.g., 60,10, or if not, then 40,4, etc.) is rising from an oversold area.
RSI (if available) is ideally below 40 or rising from oversold.
MACD (if available) shows a bullish cross (MACD line > Signal line) or is already in bullish territory and rising.
Faster Stochastic RSIs (if available) may show a 'W' pattern rising from oversold.

Decision Logic to suggest opening SHORT position - SELL:
Price shows signs of breaking a prior uptrend or is in an established downtrend.
Stochastic RSI (slowest available) is falling from an overbought area.
RSI (if available) is ideally above 60 or falling from overbought.
MACD (if available) shows a bearish cross (MACD line < Signal line) or is already in bearish territory and falling.
Faster Stochastic RSIs (if available) may show an 'M' pattern falling from overbought.

Decision Logic for HOLD:
If neither strong BUY nor strong SELL conditions are met, or if the market data indicates consolidation without clear directional momentum (e.g., price moving sideways, indicators neutral).
"""

AI_OUTPUTFORMAT_INSTRUCTIONS ="""
Output Format:
Your response MUST be in the following JSON format. Do not include any explanatory text outside of this JSON structure.
{
"price": "current/latest closing price from Kline Data",
"date": "current/latest timestamp from Kline Data (YYYY-MM-DD HH:MM:SS)",
"trend_description": "A brief description of the observed price trend (e.g., 'Uptrend since YYYY-MM-DD HH:MM:SS', 'Downtrend, recently broke support at X', 'Consolidating between P1 and P2').",
"breakout_point_description": "Description of any observed trend breakout or breakdown point relevant to the decision (e.g., 'Price broke above resistance at YYYY-MM-DD HH:MM:SS at price P', 'No clear breakout observed').",
"action": "BUY" | "SELL" | "HOLD",
"explanation": "A concise explanation for your decision, referencing specific kline patterns or indicator signals from the provided textual data. Mention specific values or conditions if possible (e.g., 'MACD bullish cross at YYYY-MM-DD HH:MM:SS, RSI at 35 and rising')."
}
"""


MAX_DATA_POINTS_FOR_LLM = 100 # Max data points (candles/indicator values) to send to LLM

@app.post("/AI")
async def get_ai_suggestion(request_data: AIRequest):
    logger.info(f"Received /AI request: Symbol={request_data.symbol}, Res={request_data.resolution}, "
                f"Range=[{request_data.xAxisMin}, {request_data.xAxisMax}], "
                f"Indicators={request_data.activeIndicatorIds}, "
                f"LocalModel={request_data.local_ollama_model_name if request_data.use_local_ollama else 'N/A'}, "
                f"UseLocalOllama: {request_data.use_local_ollama}")
    
    # Determine api_source early for logging and error handling
    if request_data.use_local_ollama:
        api_source = "Local Ollama"
    else:
        api_source = "Gemini"
            
    current_time_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    
    # 1. Determine kline fetch window (considering lookback for indicators)
    max_lookback_periods = 0
    for ind_id in request_data.activeIndicatorIds:
        config = next((item for item in AVAILABLE_INDICATORS if item["id"] == ind_id), None)
        if config:
            current_indicator_lookback = 0
            if config["id"] == "macd": current_indicator_lookback = config["params"]["long_period"] + config["params"]["signal_period"]
            elif config["id"] == "rsi": current_indicator_lookback = config["params"]["period"]
            elif config["id"].startswith("stochrsi"): current_indicator_lookback = config["params"]["rsi_period"] + config["params"]["stoch_period"] + config["params"]["d_period"]
            if current_indicator_lookback > max_lookback_periods: max_lookback_periods = current_indicator_lookback
            elif config["id"] == "open_interest":
                current_indicator_lookback = 0 # No specific lookback for OI itself
    
    buffer_candles = 30
    min_overall_candles = 50
    lookback_candles_needed = max(max_lookback_periods + buffer_candles, min_overall_candles)
    timeframe_secs = get_timeframe_seconds(request_data.resolution)

    kline_fetch_start_ts = request_data.xAxisMin - (lookback_candles_needed * timeframe_secs)
    kline_fetch_end_ts = request_data.xAxisMax
    
    # Clamp fetch window
    current_time_sec_utc = int(datetime.now(timezone.utc).timestamp())
    final_fetch_from_ts = max(0, kline_fetch_start_ts)
    final_fetch_to_ts = max(0, min(kline_fetch_end_ts, current_time_sec_utc))

    if final_fetch_from_ts >= final_fetch_to_ts:
        logger.warning(f"AI: Invalid effective time range for kline fetch: {final_fetch_from_ts} >= {final_fetch_to_ts}")
        return JSONResponse({"error": "Invalid time range for fetching data."}, status_code=400)

    # 2. Fetch klines and Open Interest for calculation
    klines_for_calc = await get_cached_klines(request_data.symbol, request_data.resolution, final_fetch_from_ts, final_fetch_to_ts)
    if not klines_for_calc or klines_for_calc[0]['time'] > final_fetch_from_ts or klines_for_calc[-1]['time'] < final_fetch_to_ts:
        bybit_klines = fetch_klines_from_bybit(request_data.symbol, request_data.resolution, final_fetch_from_ts, final_fetch_to_ts)
        if bybit_klines:
            await cache_klines(request_data.symbol, request_data.resolution, bybit_klines)
            klines_for_calc = await get_cached_klines(request_data.symbol, request_data.resolution, final_fetch_from_ts, final_fetch_to_ts)
    
        oi_data_for_calc = await get_cached_open_interest(request_data.symbol, request_data.resolution, final_fetch_from_ts, final_fetch_to_ts)

    if not oi_data_for_calc or oi_data_for_calc[0]['time'] > final_fetch_from_ts or oi_data_for_calc[-1]['time'] < final_fetch_to_ts:
        bybit_oi_data = fetch_open_interest_from_bybit(request_data.symbol, request_data.resolution, final_fetch_from_ts, final_fetch_to_ts)
        if bybit_oi_data:
            await cache_open_interest(request_data.symbol, request_data.resolution, bybit_oi_data)
            oi_data_for_calc = await get_cached_open_interest(request_data.symbol, request_data.resolution, final_fetch_from_ts, final_fetch_to_ts)

    # Filter klines and OI to the exact final fetch window
    klines_for_calc = [k for k in klines_for_calc if final_fetch_from_ts <= k['time'] <= final_fetch_to_ts]
    klines_for_calc.sort(key=lambda x: x['time'])

    if not klines_for_calc:
        logger.warning(f"AI: No kline data found for {request_data.symbol} {request_data.resolution} in range {final_fetch_from_ts}-{final_fetch_to_ts}")
        return JSONResponse({"error": "No kline data available for analysis."}, status_code=404)

    # 3. Prepare DataFrame
    oi_data_for_calc = [oi for oi in oi_data_for_calc if final_fetch_from_ts <= oi['time'] <= final_fetch_to_ts]
    oi_data_for_calc.sort(key=lambda x: x['time'])
    if not klines_for_calc: # OI data without klines is not useful for the AI prompt as constructed
        logger.warning(f"AI: No kline data found for {request_data.symbol} {request_data.resolution} in range {final_fetch_from_ts}-{final_fetch_to_ts}")
        return JSONResponse({"error": "No kline data available for analysis."}, status_code=404)

    # 3. Prepare DataFrame (merge klines and OI)
    df_ohlcv = _prepare_dataframe(klines_for_calc, oi_data_for_calc)
        
    
    if df_ohlcv is None or df_ohlcv.empty:
        logger.warning(f"AI: DataFrame preparation failed for {request_data.symbol} {request_data.resolution}.")
        return JSONResponse({"error": "Failed to prepare data for analysis."}, status_code=500)

    # 4. Calculate all requested indicators using the full df_ohlcv
    calculated_indicators_data_full_range: Dict[str, Dict[str, Any]] = {}
    for ind_id_str in request_data.activeIndicatorIds:
        indicator_config = next((item for item in AVAILABLE_INDICATORS if item["id"] == ind_id_str), None)
        if indicator_config:
            params = indicator_config["params"]
            calc_id = indicator_config["id"]
            temp_data: Optional[Dict[str, Any]] = None
            if calc_id == "macd": temp_data = calculate_macd(df_ohlcv.copy(), **params)
            elif calc_id == "rsi": temp_data = calculate_rsi(df_ohlcv.copy(), **params)
            elif calc_id.startswith("stochrsi"): temp_data = calculate_stoch_rsi(df_ohlcv.copy(), **params)
            elif calc_id == "open_interest": temp_data = calculate_open_interest(df_ohlcv.copy())
            
            if temp_data and temp_data.get("t"): # Ensure 't' exists for filtering
                calculated_indicators_data_full_range[ind_id_str] = temp_data
            else:
                logger.warning(f"AI: Calculation for indicator {ind_id_str} yielded no data or no timestamps.")
                calculated_indicators_data_full_range[ind_id_str] = {"t": [], "s": "no_data", "errmsg": f"No data from {ind_id_str} calc"}

    # 5. Filter klines and indicators to the visible range (xAxisMin, xAxisMax)
    visible_klines = [k for k in klines_for_calc if request_data.xAxisMin <= k['time'] <= request_data.xAxisMax]
    visible_klines.sort(key=lambda x: x['time']) # Ensure sorted

    # Truncate visible klines if they exceed the limit
    klines_to_send_for_json_payload = visible_klines[-MAX_DATA_POINTS_FOR_LLM:] if len(visible_klines) > MAX_DATA_POINTS_FOR_LLM else visible_klines
    if len(visible_klines) > MAX_DATA_POINTS_FOR_LLM:
        logger.info(f"AI: Truncating visible klines from {len(visible_klines)} to {len(klines_to_send_for_json_payload)} for LLM.")


    visible_indicators_data: Dict[str, Dict[str, Any]] = {}
    for ind_id, ind_data_full in calculated_indicators_data_full_range.items():
        if not ind_data_full or not ind_data_full.get("t"):
            visible_indicators_data[ind_id] = {"t": [], "s": "no_data", "errmsg": f"No initial data for {ind_id}"}
            continue

        filtered_t: List[int] = []
        # Initialize lists for all potential data series in the indicator
        data_series_keys = [key for key in ind_data_full if key not in ["t", "s", "errmsg"]]
        filtered_values_dict: Dict[str, List[Any]] = {key: [] for key in data_series_keys}
        
        data_found_in_visible_range = False
        for i, ts_val in enumerate(ind_data_full["t"]):
            if request_data.xAxisMin <= ts_val <= request_data.xAxisMax:
                filtered_t.append(ts_val)
                for data_key in data_series_keys:
                    if data_key in ind_data_full and i < len(ind_data_full[data_key]):
                        filtered_values_dict[data_key].append(ind_data_full[data_key][i])
                    else: # Should not happen if data is consistent
                        filtered_values_dict[data_key].append(None) 
                data_found_in_visible_range = True
        
        if data_found_in_visible_range and filtered_t:
            # Truncate indicator data if necessary
            if len(filtered_t) > MAX_DATA_POINTS_FOR_LLM:
                logger.info(f"AI: Truncating indicator {ind_id} data from {len(filtered_t)} to {MAX_DATA_POINTS_FOR_LLM} points for LLM.")
                truncated_indicator_t = filtered_t[-MAX_DATA_POINTS_FOR_LLM:]
                truncated_indicator_values = {}
                for key, values_list in filtered_values_dict.items():
                    if isinstance(values_list, list) and len(values_list) == len(filtered_t):
                        truncated_indicator_values[key] = values_list[-MAX_DATA_POINTS_FOR_LLM:]
                    else: # Should not happen if data is consistent
                        truncated_indicator_values[key] = values_list 
                visible_indicators_data[ind_id] = {"t": truncated_indicator_t, "s": "ok", **truncated_indicator_values}
            else:
                visible_indicators_data[ind_id] = {"t": filtered_t, "s": "ok", "maxTime":final_fetch_to_ts, "maxLookBack" : lookback_candles_needed, **filtered_values_dict}
        else:
            visible_indicators_data[ind_id] = {"t": [], "s": "no_data", "errmsg": f"No data for {ind_id} in visible range"}

    # 6. Format data for LLM
    # Prepare Kline data for JSON
    kline_data_for_json = []
    if not klines_to_send_for_json_payload: # Check the (potentially truncated) list
        logger.info("No visible klines to send to AI.")
    else:
        logger.info(f"AI: Preparing {len(klines_to_send_for_json_payload)} klines for JSON payload.")
        for k in klines_to_send_for_json_payload:
            dt_object = datetime.fromtimestamp(k['time'], timezone.utc)
            kline_data_for_json.append({ # Changed to only include date and close
                    "date": dt_object.strftime('%Y-%m-%d %H:%M:%S'), # Renamed from timestamp to date
                    "close": k['close']
                })
           
    indicator_data_for_json_list = []
    
    
    if not request_data.activeIndicatorIds:
        logger.info("No active indicators to send to AI.")
    else:
        for ind_id in request_data.activeIndicatorIds:
            indicator_config_details = next((item for item in AVAILABLE_INDICATORS if item["id"] == ind_id), None)
            if indicator_config_details:
                data_to_format = visible_indicators_data.get(ind_id, {"t": [], "s": "no_data", "errmsg": f"Data for {ind_id} not found post-filter"})
                # format_indicator_data_for_llm_as_dict no longer needs max_points as data is pre-truncated
                indicator_dict = format_indicator_data_for_llm_as_dict(ind_id, indicator_config_details, data_to_format) 
                indicator_data_for_json_list.append(indicator_dict)                
            else:
                indicator_data_for_json_list.append({
                    "indicator_name": ind_id, "status": "error", "error_message": "Configuration not found."
                })
                
    start_dt_str = datetime.fromtimestamp(request_data.xAxisMin, timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        
    # Determine end_dt_str from the latest kline in klines_for_calc, which represents the true end of data fetched from Redis
    if klines_for_calc:
        end_dt_str = datetime.fromtimestamp(klines_for_calc[-1]['time'], timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    else: # Fallback if klines_for_calc is somehow empty (should be caught earlier)
        end_dt_str = datetime.fromtimestamp(request_data.xAxisMax, timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


    market_data_json_payload = {
        "kline_data": kline_data_for_json,
        "indicator_data": indicator_data_for_json_list
    }
    market_data_json_str = json.dumps(market_data_json_payload, indent=2)
    
    # --- Construct System and User Prompts for DeepSeek ---
    system_prompt_content = f"{AI_SYSTEM_PROMPT_INSTRUCTIONS}\n\n{AI_OUTPUTFORMAT_INSTRUCTIONS}"

    user_prompt_content = "--- Market Data ---\n"
    user_prompt_content += f"Symbol: {request_data.symbol}\n"
    user_prompt_content += f"Timeframe: {request_data.resolution}\n"
    user_prompt_content += f"Data Range (UTC): {start_dt_str} to {end_dt_str}\n\n"
    user_prompt_content += "--- MARKET DATA JSON ---\n" + market_data_json_str + "\n--- END MARKET DATA JSON ---\n\n"
    user_prompt_content += "--- End Market Data ---\n\n"
    #user_prompt_content += f"User Question: {request_data.question}"

    # --- DUMP PROMPT TO FILE ---
    try:
        temp_dir = Path("./") # Changed from c:/temp to current directory for broader compatibility
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        prompt_filename = "ai_prompt_deepseek.txt"
        if request_data.use_local_ollama:
            prompt_filename = "ai_prompt_local_ollama.txt"
        elif request_data.use_gemini:
            prompt_filename = "ai_prompt_gemini.txt"

        prompt_file_path = temp_dir / prompt_filename
        
        prompt_content_to_dump = f"--- SYSTEM PROMPT ---\n{system_prompt_content}\n\n--- USER PROMPT ---\n{user_prompt_content}"
        prompt_file_path.write_text(prompt_content_to_dump, encoding='utf-8')
        logger.info(f"AI prompt ({api_source}) successfully dumped to {prompt_file_path}")
    except Exception as e:
        logger.error(f"Error dumping AI prompt ({api_source}) to file: {e}", exc_info=True)
    # --- END DUMP PROMPT ---

    messages_for_ai = [
        {"role": "system", "content": system_prompt_content},
        {"role": "user", "content": user_prompt_content}
    ]

    logger.info(f"AI: Sending request to {api_source} with model {request_data.local_ollama_model_name or LOCAL_OLLAMA_MODEL_NAME if request_data.use_local_ollama else DEEPSEEK_API_MODEL_NAME}.")
    try:
        if request_data.use_local_ollama:
            selected_local_model = request_data.local_ollama_model_name or LOCAL_OLLAMA_MODEL_NAME
            logger.info(f"Using Local Ollama model for streaming: {selected_local_model}")
            generator = ollama_response_generator(
                selected_local_model, messages_for_ai, local_ollama_client, request_data
            )
            return StreamingResponse(generator, media_type="application/x-ndjson")
        else:
            selected_gemini_model = "models/gemini-2.5-flash-lite-preview-06-17" # Or "gemini-pro"
            logger.info(f"Using Gemini model: {selected_gemini_model}")
            
            # Gemini uses a 'system_instruction' for the system prompt, separate from the message history.
            model = genai.GenerativeModel(
                model_name=selected_gemini_model,
                system_instruction=system_prompt_content
            )
            gemini_response = await asyncio.to_thread(
                model.generate_content,
                user_prompt_content,  # Pass just the user prompt string
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    response_mime_type="application/json" # Explicitly ask for JSON output
                )
            )
            ai_message_content_str = gemini_response.text
            logger.info(f"Gemini raw response text: {ai_message_content_str[:500]}...")            
            
        if not ai_message_content_str:
            logger.error(f"{api_source} API response content is empty.")
            return JSONResponse({"error": f"AI model ({api_source}) returned empty content."}, status_code=500)

        # Try to parse the JSON content from the AI
        try:
                # The AI should return a JSON string, so we parse it.
                ai_suggestion_json = json.loads(ai_message_content_str)
                # Ensure the date is current if the AI didn't set it, or standardize format
                if "date" not in ai_suggestion_json or not ai_suggestion_json["date"]:
                    if visible_klines and kline_data_for_json: # Ensure kline_data_for_json is not empty
                        ai_suggestion_json["date"] = kline_data_for_json[-1]["timestamp"]
                    elif visible_klines: # Fallback if kline_data_for_json was empty but visible_klines was not
                         ai_suggestion_json["date"] = datetime.fromtimestamp(visible_klines[-1]['time'], timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        ai_suggestion_json["date"] = current_time_str 
                logger.info(f"AI Suggestion ({api_source}): {ai_suggestion_json}")
                return JSONResponse(ai_suggestion_json)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse AI suggestion JSON from {api_source}: {ai_message_content_str}")
            # Return the raw string if it's not valid JSON, but wrap it in your expected structure
            return JSONResponse({
                "action": "ERROR",
                "date": current_time_str,
                "explanation": f"AI model returned non-JSON content: {ai_message_content_str}"
            })

    except APIStatusError as e: # Handles HTTP status errors from DeepSeek API
        logger.error(f"{api_source} API error (status {e.status_code}): {e.response.text if e.response else 'No response body'}")
        error_details = e.response.text if e.response else 'No response body'
        return JSONResponse({"error": f"AI API error ({api_source}): {e.status_code}", "details": error_details}, status_code=e.status_code)
    except APIConnectionError as e: # Handles connection errors
        logger.error(f"Failed to connect to {api_source} API: {e}")
        return JSONResponse({"error": f"Could not connect to AI service ({api_source})."}, status_code=503)
    except APIError as e: # Catch-all for other API errors from the openai library
        logger.error(f"{api_source} API returned an error: {e}")
        return JSONResponse({"error": f"AI API error ({api_source}): {str(e)}"}, status_code=500) # Generic 500 or more specific if possible
    except Exception as e:
        logger.error(f"Unexpected error in /AI endpoint with {api_source}: {e}", exc_info=True)
        return JSONResponse({"error": "An unexpected error occurred processing the AI request."}, status_code=500)

# --- Helper for Ollama Streaming ---
async def ollama_response_generator(
    model_name: str, 
    messages_list: list, 
    client: OpenAI, 
    request_data_for_log: AIRequest # For logging context
):
    queue = asyncio.Queue()
    # Get the event loop of the context where this async generator is running
    main_event_loop = asyncio.get_running_loop()

    def ollama_thread_worker():
        try:
            logger.info(f"Ollama stream worker started for model {model_name}. Symbol: {request_data_for_log.symbol}, Res: {request_data_for_log.resolution}")
            stream = client.chat.completions.create(
                model=model_name,
                messages=messages_list,
                stream=True
            )
            for chunk_count, chunk in enumerate(stream):
                if chunk.choices[0].delta and chunk.choices[0].delta.content:
                    response_payload = {"response": chunk.choices[0].delta.content}
                    # logger.debug(f"Ollama stream chunk {chunk_count} for {model_name}: {response_payload['response'][:50]}...")
                    main_event_loop.call_soon_threadsafe(queue.put_nowait, json.dumps(response_payload) + "\n")
                elif chunk.choices[0].finish_reason:
                    logger.info(f"Ollama stream finished for model {model_name}. Reason: {chunk.choices[0].finish_reason}")
            
            main_event_loop.call_soon_threadsafe(queue.put_nowait, None) # Signal end of stream
            logger.info(f"Ollama stream worker finished successfully for model {model_name}. Symbol: {request_data_for_log.symbol}")
        except (APIConnectionError, APIStatusError, APIError) as api_e: # Catch specific OpenAI client errors
            logger.error(f"Ollama stream worker: API-related error for model {model_name}: {api_e}", exc_info=True)
            error_response = {"error": f"Ollama API error: {type(api_e).__name__}", "details": str(api_e)}
            main_event_loop.call_soon_threadsafe(queue.put_nowait, json.dumps(error_response) + "\n")
            main_event_loop.call_soon_threadsafe(queue.put_nowait, None)
        except Exception as e:
            logger.error(f"Ollama stream worker: Unexpected error for model {model_name}: {e}", exc_info=True)
            error_response = {"error": "Unexpected error streaming from Ollama", "details": str(e)}
            main_event_loop.call_soon_threadsafe(queue.put_nowait, json.dumps(error_response) + "\n")
            main_event_loop.call_soon_threadsafe(queue.put_nowait, None)

    asyncio.create_task(asyncio.to_thread(ollama_thread_worker))

    while True:
        item = await queue.get()
        if item is None:
            break
        yield item

@app.get("/AI_Local_OLLAMA_Models")
async def get_local_ollama_models():
    try:
        logger.info("Fetching local Ollama models list...")
        models_response = await asyncio.to_thread(local_ollama_client.models.list)
        # The response object might be a Pydantic model, access its 'data' attribute
        # which should be a list of model objects.
        models_list = [model.id for model in models_response.data if hasattr(model, 'id')]
        logger.info(f"Successfully fetched {len(models_list)} local Ollama models: {models_list}")
        return JSONResponse({"models": models_list})
    except APIConnectionError as e:
        logger.error(f"Failed to connect to local Ollama to get models: {e}")
        return JSONResponse({"error": "Could not connect to local Ollama service."}, status_code=503)
    except Exception as e:
        logger.error(f"Error fetching local Ollama models: {e}", exc_info=True)
        return JSONResponse({"error": f"An unexpected error occurred: {str(e)}"}, status_code=500)




async def fetch_and_publish_klines():
    logger.info("Starting fetch_and_publish_klines background task")
    last_fetch_times: dict[str, datetime] = {}
    while True:
        try:
            current_time_utc = datetime.now(timezone.utc)
            for resolution in timeframe_config.supported_resolutions:
                time_boundary = current_time_utc.replace(second=0, microsecond=0)
                if resolution == "1m": time_boundary = time_boundary.replace(minute=(time_boundary.minute // 1) * 1) # Ensure 1m aligns
                elif resolution == "5m": time_boundary = time_boundary.replace(minute=(time_boundary.minute // 5) * 5)
                elif resolution == "1h": time_boundary = time_boundary.replace(minute=0)
                elif resolution == "1d": time_boundary = time_boundary.replace(hour=0, minute=0)
                elif resolution == "1w": 
                    time_boundary = time_boundary - timedelta(days=time_boundary.weekday())
                    time_boundary = time_boundary.replace(hour=0, minute=0)

                last_fetch = last_fetch_times.get(resolution)
                if last_fetch is None or current_time_utc >= (last_fetch + timedelta(seconds=get_timeframe_seconds(resolution))):
                    #logger.info(f"Fetching klines for {resolution} from {last_fetch or 'beginning'} up to {current_time_utc}")
                    for symbol_val in SUPPORTED_SYMBOLS: 
                        end_ts = int(current_time_utc.timestamp())
                        if last_fetch is None: 
                            start_ts_map = {"1m": 2*3600, "5m": 24*3600, "1h": 7*24*3600, "1d": 30*24*3600, "1w": 90*24*3600} # Added 1m
                            start_ts = end_ts - start_ts_map.get(resolution, 30*24*3600)
                        else:
                            start_ts = int(last_fetch.timestamp()) 
                        
                        if start_ts < end_ts:
                            klines = fetch_klines_from_bybit(symbol_val, resolution, start_ts, end_ts)
                            if klines:
                                await cache_klines(symbol_val, resolution, klines)
                                latest_kline = klines[-1]
                                if latest_kline['time'] >= int(time_boundary.timestamp()):
                                    await publish_resolution_kline(symbol_val, resolution, latest_kline)
                                    #logger.info(f"Published {resolution} kline for {symbol_val} at {datetime.fromtimestamp(latest_kline['time'], timezone.utc)}")
                    last_fetch_times[resolution] = current_time_utc 
            await asyncio.sleep(60)
            # Also fetch and cache Open Interest data
            for resolution in timeframe_config.supported_resolutions:
                current_time_utc = datetime.now(timezone.utc)
                end_ts = int(current_time_utc.timestamp())
                # Fetch OI for the last 24 hours to ensure recent data is available
                start_ts = end_ts - (24 * 3600) # Fetch last 24 hours of OI
                for symbol_val in SUPPORTED_SYMBOLS:
                    oi_data = fetch_open_interest_from_bybit(symbol_val, resolution, start_ts, end_ts)
                    if oi_data:
                        await cache_open_interest(symbol_val, resolution, oi_data)            
        except Exception as e:
            logger.error(f"Error in fetch_and_publish_klines task: {e}", exc_info=True)
            await asyncio.sleep(10) 

async def bybit_realtime_feed_listener():
    logger.info("Starting Bybit real-time feed listener task (conceptual - for shared WS to Redis)")
    # This is a placeholder for a shared WebSocket connection that publishes to Redis.
    # The /stream/live/{symbol} endpoint now creates a direct Bybit WS per client.
    # If you want this listener to feed Redis for the old SSE endpoint, implement it here.
    while True:
        await asyncio.sleep(300) 
        logger.debug("bybit_realtime_feed_listener (shared conceptual) placeholder is alive")

@app.get("/stream/{symbol}/{resolution}")
async def stream_resolution_api_endpoint(symbol: str, resolution: str, request: Request): 
    return await stream_klines(symbol, resolution, request)

@app.websocket("/stream/live/{symbol}")
async def stream_live_data_websocket_endpoint(websocket: WebSocket, symbol: str):
    await websocket.accept()
    logger.info(f"WebSocket connection accepted for live data: {symbol}")

    # --- Client-specific state for throttling ---
    client_stream_state = {
        "last_sent_timestamp": 0.0,
        "stream_delta_seconds": 1, # Default, will be updated from settings
        "last_settings_check_timestamp": 0.0, # For periodically re-checking settings
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
            retrieved_delta_time = symbol_settings.get('streamDeltaTime', 0) # Get value before int conversion for logging
            logger.info(f"Live stream for {symbol}: Retrieved 'streamDeltaTime' from symbol_settings: {retrieved_delta_time} (type: {type(retrieved_delta_time)})")
            client_stream_state["stream_delta_seconds"] = int(retrieved_delta_time)
            logger.info(f"Live stream for {symbol}: Using stream_delta_seconds = {client_stream_state['stream_delta_seconds']}")
        else:
            logger.warning(f"Live stream for {symbol}: No settings_json found in Redis for key '{settings_key}'. Defaulting stream_delta_seconds to 0.")
        client_stream_state["last_settings_check_timestamp"] = time.time() # Initialize after first load attempt
    except Exception as e:
        logger.error(f"Error fetching or processing streamDeltaTime settings for {symbol}: {e}. Defaulting stream_delta_seconds to 0.", exc_info=True)

    # --- End client-specific state ---
    client_stream_state["last_settings_check_timestamp"] = time.time() # Initialize even on error

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
        logger.debug(f"Bybit Handler for {symbol}: Using stream_delta_seconds = {client_stream_state['stream_delta_seconds']}") # Log current delta
        if "topic" in message and "data" in message:
            topic_str = message["topic"] # topic is already a string
            # No need to split topic_str if we are only checking the full topic string
            # Check if the topic is for tickers and matches the requested symbol
            if topic_str == f"tickers.{symbol}": # Direct comparison
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
                            message_timestamp_ms = time.time() * 1000 # Fallback to current time in ms

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
    bybit_ws_client.subscribe(topic=topics, callback=bybit_message_handler,symbol=symbols)
    
    # Start the settings update listener task (ensure 'settings_update_listener' is defined before this line)
    redis_for_pubsub = await get_redis_connection() # Get a connection for PubSub
    ps_client = redis_for_pubsub.pubsub()

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
                bybit_ws_client.exit() # This is a synchronous call
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
                    logger.error(f"RuntimeError during FastAPI WebSocket close for {symbol}: {e_rt}", exc_info=True) # Log other RuntimeErrors
            except Exception as e_close: # Catch any other unexpected errors during close
                logger.error(f"Unexpected error closing FastAPI WebSocket for {symbol}: {e_close}", exc_info=True)
        else:
            logger.info(f"FastAPI WebSocket for {symbol} client_state was already DISCONNECTED in finally block.")
        
        logger.info(f"Cleanup finished for WebSocket and Bybit connection for live data: {symbol}")


@app.get("/get_agent_trades")
async def get_trades_from_csv(
    symbol: str, 
    from_ts: int = Query(..., description="Start timestamp (Unix seconds)"), 
    to_ts: int = Query(..., description="End timestamp (Unix seconds)")
):
    """
    Retrieves trade records from episode CSV files generated by gemini_RL.py.
    """
    # The symbol is not in the CSV, but we accept it for API consistency.
    logger.info(f"GET /get_agent_trades request for symbol={symbol} from {from_ts} to {to_ts}")

    try:
        # Find all episode CSV files in the current directory
        episode_files = glob.glob("episode_*.csv")
        if not episode_files:
            logger.warning("No episode CSV files found for /get_agent_trades.")
            return JSONResponse(content={"status": "no_data", "trades": [], "message": "No trade data files found."}, status_code=404)

        # Sort to find the latest episode file (e.g., episode_0025.csv > episode_0024.csv)
        episode_files.sort()
        latest_episode_file = episode_files[-1]
        logger.info(f"Reading latest agent trades from: {latest_episode_file}")

        all_trades_df_list = []
        try:
            # Read only the latest file
            df = pd.read_csv(latest_episode_file, low_memory=False)
            all_trades_df_list.append(df)
        except pd.errors.EmptyDataError:
            logger.warning(f"Latest episode file is empty: {latest_episode_file}")
            # This will result in an empty list, which is handled below
        except Exception as e:
            logger.error(f"Error reading latest episode file {latest_episode_file}: {e}")
            # This will also result in an empty list

        if not all_trades_df_list:
            logger.warning("All found episode CSV files were empty or unreadable.")
            return JSONResponse(content={"status": "no_data", "trades": [], "message": "Trade data files are empty or unreadable."}, status_code=404)

        combined_df = pd.concat(all_trades_df_list, ignore_index=True)
        
        if 'timestamp' not in combined_df.columns or 'action' not in combined_df.columns:
            logger.error("Required 'timestamp' or 'action' column not found in combined CSV data.")
            return JSONResponse(content={"status": "error", "message": "Required columns missing in data files."}, status_code=500)

        combined_df['timestamp'] = pd.to_numeric(combined_df['timestamp'], errors='coerce')
        combined_df.dropna(subset=['timestamp'], inplace=True)
        
        trade_actions = ['buy', 'sell', 'close_long', 'close_short']
        trades_df = combined_df[combined_df['action'].isin(trade_actions)].copy()
        trades_df = trades_df[(trades_df['timestamp'] >= from_ts) & (trades_df['timestamp'] <= to_ts)]
        trades_df.sort_values(by='timestamp', inplace=True)
        # Replace NaN with None for JSON compatibility before converting to dict
        trades_df_cleaned = trades_df.replace({np.nan: None})
        trades_list = trades_df_cleaned.to_dict(orient='records')
        logger.info(f"Found {len(trades_list)} trades for {symbol} in the specified time range.")
        logger.debug(f"Trades data (first 5 shown if many): {trades_list[:5] if len(trades_list) > 5 else trades_list}")
        
        return JSONResponse(content={"status": "success", "trades": trades_list})
    except Exception as e:
        logger.error(f"Error in /get_trades endpoint: {e}", exc_info=True)
        return JSONResponse(content={"status": "error", "message": "An unexpected error occurred while fetching trades."}, status_code=500)


@app.get("/get_order_history/{symbol}")
async def get_order_history_endpoint(symbol: str, request: Request, cert_check: bool = Depends(require_valid_certificate)):
    """
    Fetches and returns the current open positions for a given symbol from Bybit.
    This endpoint is protected and requires a valid client certificate.
    """
    logger.info(f"GET /get_order_history/{symbol} request received.")
    if symbol not in SUPPORTED_SYMBOLS:
        logger.warning(f"GET /get_order_history: Unsupported symbol: {symbol}")
        return JSONResponse({"status": "error", "message": f"Unsupported symbol: {symbol}"}, status_code=400)
    
    email = request.session.get("email")
    if not email:
        logger.warning("GET /get_order_history: Email not found in session.")
        return JSONResponse({"status": "error", "message": "Email not found in session"}, status_code=400)

    try:
        
        redis = await get_redis_connection()
        # Define a key prefix for storing order history in Redis, unique per email and symbol
        order_history_key_prefix = f"order_history:{email}:{symbol}"

        # Fetch existing order history from Redis
        existing_order_history = []
        redis_keys = await redis.keys(f"{order_history_key_prefix}:*")
        if redis_keys:
            stored_orders = await redis.mget(*redis_keys)
            if stored_orders:
                existing_order_history = [json.loads(order) for order in stored_orders]

        # Create a set of existing order IDs to efficiently check for duplicates
        existing_order_ids = {order['orderId'] for order in existing_order_history}

        # Retrieve recent order history from Bybit API
        res = session.get_order_history(
            category="linear",
            symbol=symbol,
            limit=200  # Adjust limit as needed
        )

        if res.get("retCode") != 0:
            error_message = res.get('retMsg', 'Unknown Bybit API error')
            logger.error(f"Bybit API error fetching order history for {symbol}: {error_message}")
            return JSONResponse({"status": "error", "message": error_message}, status_code=500)

        new_orders = res.get("result", {}).get("list", [])
        
        if res.get("retCode") == 0:
            orderHistory = res.get("result", {}).get("list", [])
            orders_to_persist = []
            for h in orderHistory:
                # Filter out already persisted order ID's and combine with history from Bybit
                orders_to_persist = [order for order in new_orders if order.get('orderId') not in existing_order_ids]

            persisted_count = 0
            async with redis.pipeline() as pipe:
                for order in orders_to_persist:
                    # Create a unique key for each order
                    order_id = order.get('orderId')
                    if order_id:
                        order_key = f"{order_history_key_prefix}:{order_id}"
                        order_json = json.dumps(order)
                        # Set the order data in Redis with an expiration time (e.g., 30 days)
                        await pipe.setex(order_key, 30 * 24 * 3600, order_json) # type: ignore # Persist each trade history 30 days
                        persisted_count += 1
                    else:
                        logger.warning("Order ID wasn't found")

                await pipe.execute()

            if persisted_count > 0:
                logger.info(f"Persisted {persisted_count} new orders from Bybit API to Redis for {email} and symbol {symbol}")

            # Fetch all order history from Redis after persisting new ones
            all_order_history = []
            redis_keys = await redis.keys(f"{order_history_key_prefix}:*")

            if redis_keys:
                stored_orders = await redis.mget(*redis_keys)
                if stored_orders:
                    all_order_history = [json.loads(order) for order in stored_orders]

            logger.info(f"Returning {len(all_order_history)} order history records from Redis for {email} and symbol {symbol}")
            return JSONResponse({"status": "success", "order history": all_order_history})

        else:
            # Check for Bybit API errors that might indicate time synchronization issues
            # retCode 10002 is a direct timestamp/recv_window error
            if res.get("retCode") == 10002: 
                logger.warning("Received timestamp error from Bybit. Attempting time synchronization with NTP...")
                if sync_time_with_ntp():
                    # Retry the request after time synchronization
                    return await get_order_history_endpoint(symbol)
                else:
                    logger.error("Time synchronization failed. Cannot retry Bybit API request.")
            
            error_message = res.get('retMsg', 'Unknown Bybit API error')
            logger.error(f"Bybit API error fetching open trades for {symbol}: {error_message}")
            return JSONResponse({"status": "error", "message": error_message}, status_code=500)







    except exceptions.FailedRequestError as e:
        # Catch FailedRequestError (e.g., HTTP 400 Bad Request) and check if it's a potential timestamp issue
        if e.status_code == 400:
            logger.warning(f"Received FailedRequestError (status 400) from Bybit for {symbol}. This might be a timestamp issue. Attempting time synchronization with NTP...")
            if sync_time_with_ntp():
                # Retry the request after time synchronization
                return await get_order_history_endpoint(symbol)
            else:
                logger.error("Time synchronization failed. Cannot retry Bybit API request.")
        
        # If not the specific 400 error, or if time sync failed, re-raise the original error
        logger.error(f"Pybit API request failed for {symbol}: {e}", exc_info=True) # Log the original error
        return JSONResponse({"status": "error", "message": f"Bybit API request failed: {e.status_code} - {e.message}"}, status_code=500) # Return generic error
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Network connection error to Bybit API for {symbol}: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": "Network connection error to Bybit API. Check internet or API endpoint."}, status_code=503)
    except requests.exceptions.Timeout as e:
        logger.error(f"Timeout connecting to Bybit API for {symbol}: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": "Timeout connecting to Bybit API. Try again later."}, status_code=504)
    except requests.exceptions.RequestException as e: # Catch-all for other requests-related errors
        logger.error(f"General requests error for Bybit API for {symbol}: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": f"An HTTP request error occurred with Bybit API: {e}"}, status_code=500)
    except Exception as e:
        logger.error(f"Error fetching open trades for {symbol}: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": "An unexpected error occurred"}, status_code=500)



def find_buy_signals(df: pd.DataFrame) -> list:
    """
    Finds buy signals based on "buy the dip in a downtrend" logic, with relaxed conditions
    allowing key events to occur within a 10-bar window.
    
    Key events (conditions that may not happen on the same bar):
    - RSI_SMA_3 crosses above RSI_SMA_5
    - RSI_SMA_3 crosses above RSI_SMA_10
    - RSI_SMA_3 crosses above RSI_SMA_20
    - StochRSI K crosses above D
    """
    logger.info("Starting find_buy_signals with enhanced logging for diagnosis")
    signals = []
    
    # Reset index for easy access
    df = df.reset_index()
    
    # Define the date range for focused logging (e.g., April 5th to April 7th)
    target_date_start = pd.to_datetime("2025-04-05", utc=True)
    target_date_end = pd.to_datetime("2025-04-07", utc=True)
    logger.info(f"Enhanced logging for date range: {target_date_start} to {target_date_end}")

    # Define key event flags (crossovers)
    df['cross_3_5'] = ((df['RSI_SMA_3'] > df['RSI_SMA_5']) & 
                       (df['RSI_SMA_3'].shift(1) <= df['RSI_SMA_5'].shift(1))).fillna(False)
    df['cross_3_10'] = ((df['RSI_SMA_3'] > df['RSI_SMA_10']) & 
                        (df['RSI_SMA_3'].shift(1) <= df['RSI_SMA_10'].shift(1))).fillna(False)
    df['cross_3_20'] = ((df['RSI_SMA_3'] > df['RSI_SMA_20']) & 
                        (df['RSI_SMA_3'].shift(1) <= df['RSI_SMA_20'].shift(1))).fillna(False)
    df['stoch_cross'] = ((df['STOCHRSIk_60_60_10_10'] > df['STOCHRSId_60_60_10_10']) & 
                         (df['STOCHRSIk_60_60_10_10'].shift(1) <= df['STOCHRSId_60_60_10_10'].shift(1))).fillna(False)
    
    # Define state flags
    df['downtrend'] = ((df['EMA_21'] < df['EMA_50']) & 
                       (df['EMA_50'] < df['EMA_200']) & 
                       (df['close'] < df['EMA_200'])).fillna(False)
    df['oversold'] = ((df['RSI_14'] < 30) & 
                      (df['STOCHRSIk_60_60_10_10'] < 20)).fillna(False)
    
    # Required events for the relaxed condition
    required_events = ['cross_3_5', 'cross_3_10', 'cross_3_20', 'stoch_cross']
    
    # Log counts of each condition across the entire dataset
    logger.info(f"Total bars in DataFrame: {len(df)}")
    logger.info(f"cross_3_5 occurrences: {df['cross_3_5'].sum()}")
    logger.info(f"cross_3_10 occurrences: {df['cross_3_10'].sum()}")
    logger.info(f"cross_3_20 occurrences: {df['cross_3_20'].sum()}")
    logger.info(f"stoch_cross occurrences: {df['stoch_cross'].sum()}")
    logger.info(f"downtrend occurrences: {df['downtrend'].sum()}")
    logger.info(f"oversold occurrences: {df['oversold'].sum()}")

    # Save DataFrame with all indicators and conditions to CSV for inspection
    debug_csv_filename = f"buy_signals_debug_df_{df['time'].iloc[0].strftime('%Y%m%d')}_to_{df['time'].iloc[-1].strftime('%Y%m%d')}.csv"
    df.to_csv(debug_csv_filename, index=False)
    logger.info(f"Saved DataFrame with indicators and conditions to: {debug_csv_filename}")

    for i in range(0, len(df)):
        # Ensure current_time is timezone-aware (UTC) for comparison
        current_time = df['time'].iloc[i].tz_localize('UTC')
        # Check if the current bar is within the target date range for detailed logging
        is_target_date = target_date_start <= current_time <= target_date_end
        
        # Current window: max 10 bars ending at i
        win_start = max(0, i - 9)
        window = df.iloc[win_start : i + 1]
        
        # Check if all required events have occurred at least once in the window
        has_all_events = all(window[event].any() for event in required_events)
        
        # Check states in the window
        has_downtrend = window['downtrend'].any()
        has_oversold = window['oversold'].any()
        
        # Log details for bars around April 6th
        if is_target_date:
            logger.info(f"Bar {i} at {current_time}:")
            logger.info(f"  RSI_SMA_3={df['RSI_SMA_3'].iloc[i]:.2f}, RSI_SMA_5={df['RSI_SMA_5'].iloc[i]:.2f}, "
                        f"RSI_SMA_10={df['RSI_SMA_10'].iloc[i]:.2f}, RSI_SMA_20={df['RSI_SMA_20'].iloc[i]:.2f}")
            logger.info(f"  STOCHRSIk={df['STOCHRSIk_60_60_10_10'].iloc[i]:.2f}, "
                        f"STOCHRSId={df['STOCHRSId_60_60_10_10'].iloc[i]:.2f}")
            logger.info(f"  EMA_21={df['EMA_21'].iloc[i]:.2f}, EMA_50={df['EMA_50'].iloc[i]:.2f}, "
                        f"EMA_200={df['EMA_200'].iloc[i]:.2f}, close={df['close'].iloc[i]:.2f}")
            logger.info(f"  Conditions: cross_3_5={df['cross_3_5'].iloc[i]}, "
                        f"cross_3_10={df['cross_3_10'].iloc[i]}, "
                        f"cross_3_20={df['cross_3_20'].iloc[i]}, "
                        f"stoch_cross={df['stoch_cross'].iloc[i]}")
            logger.info(f"  States: downtrend={df['downtrend'].iloc[i]}, oversold={df['oversold'].iloc[i]}")
            logger.info(f"  Window ({len(window)} bars): has_all_events={has_all_events}, "
                        f"has_downtrend={has_downtrend}, has_oversold={has_oversold}")
            logger.info(f"  Window event counts: cross_3_5={window['cross_3_5'].sum()}, "
                        f"cross_3_10={window['cross_3_10'].sum()}, "
                        f"cross_3_20={window['cross_3_20'].sum()}, "
                        f"stoch_cross={window['stoch_cross'].sum()}")

        if has_all_events and has_downtrend and has_oversold:
            # Check previous window (up to i-1, max 10 bars)
            prev_start = max(0, i - 10)
            prev_window = df.iloc[prev_start : i]
            
            # If no previous bars, consider it as not having all
            if len(prev_window) == 0:
                had_all_prev = False
            else:
                had_all_prev = all(prev_window[event].any() for event in required_events)
            
            # Signal if this is the first bar where all events are covered in the window
            if not had_all_prev:
                timestamp = int(df['time'].iloc[i].timestamp())
                signals.append({
                    'timestamp': timestamp,
                    'price': df['close'].iloc[i],
                    'type': 'buy'
                })
                if is_target_date:
                    logger.info(f"BUY SIGNAL DETECTED at {current_time}: timestamp={timestamp}, "
                                f"price={df['close'].iloc[i]:.2f}")
    
    logger.info(f"Total buy signals detected: {len(signals)}")
    return signals

# --- Indicator Calculation Helper Functions ---
def find_buy_signals_orig(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Analyzes a DataFrame with technical indicators to find specific buy signals
    based on a downtrend followed by an oversold reversal.
    Returns a list of dictionaries, each representing a detected signal.
    """
    logger.info("--- Running Buy Signal Detection with Downtrend Logic ---")
    signals = []

    # --- Define Signal Conditions ---
    RSI_LOW_ZONE_LEVEL = 30 # RSI is in a low zone, not necessarily just crossed up.
    STORSI_OVERSOLD_LEVEL = 20 # StochRSI oversold level
    CONDITION_LOOKBACK_WINDOW = 10 # How many candles to look back for dip/low RSI conditions.

    # --- Prepare required column names ---
    # pandas-ta generates uppercase column names by default
    required_cols = ['close', 'RSI_14', 'STOCHRSIk_60_60_10_10', 'STOCHRSId_60_60_10_10', 'EMA_50']

    
    # Check if all required columns exist in the DataFrame
    if not all(col in df.columns for col in required_cols):
        missing_cols = [col for col in required_cols if col not in df.columns]
        logger.error(f"Missing one or more required columns for signal detection:  {missing_cols}")
        return []

    df_signal = df.copy()

    # --- Implement the Logic using Vectorized Operations ---

    # Context Condition 1: Price is in a dip (below a key moving average).
    cond_price_below_ma = df_signal['close'] < df_signal['EMA_50']
    # Context Condition 2: RSI is in a low zone (e.g., below 40), indicating it's not overbought.
    cond_rsi_is_low = df_signal['RSI_14'] < RSI_LOW_ZONE_LEVEL

    # Condition 3: The key STOCHRSI_60_10 shows a bullish crossover from the oversold zone.
    # OR, more generally, is rising from a low level.
    k_line = df_signal['STOCHRSIk_60_60_10_10']
    d_line = df_signal['STOCHRSId_60_60_10_10']
    cond_storsi_crossover = (k_line.shift(1) < d_line.shift(1)) & (k_line > d_line) & (k_line.shift(1) < STORSI_OVERSOLD_LEVEL)

    # For a signal to be valid, the crossover must happen while the context conditions
    # (dip and low RSI) are either true on the same candle or were true recently.
    # A rolling max on a boolean series is equivalent to a rolling 'any'.
    dip_in_window = cond_price_below_ma.rolling(window=CONDITION_LOOKBACK_WINDOW, min_periods=1).max().astype(bool)
    rsi_low_in_window = cond_rsi_is_low.rolling(window=CONDITION_LOOKBACK_WINDOW, min_periods=1).max().astype(bool)


    # --- DEBUGGING: Log counts for each condition ---
    logger.info(f"Condition 1 (Price below EMA50): {cond_price_below_ma.sum()} points")
    logger.info(f"Condition 2 (RSI is low < {RSI_LOW_ZONE_LEVEL}): {cond_rsi_is_low.sum()} points")
    logger.info(f"Condition 3 (StochRSI Crossover from < {STORSI_OVERSOLD_LEVEL}): {cond_storsi_crossover.sum()} points")
    logger.info(f"Context Check: Price was below EMA50 within last {CONDITION_LOOKBACK_WINDOW} candles: {dip_in_window.sum()} points")
    logger.info(f"Context Check: RSI was low within last {CONDITION_LOOKBACK_WINDOW} candles: {rsi_low_in_window.sum()} points")

    # Combine all conditions to identify buy signals
    buy_signals_df = df_signal[cond_storsi_crossover & dip_in_window & rsi_low_in_window]

    logger.info(f"Total points satisfying ALL conditions: {len(buy_signals_df)}")
    if not buy_signals_df.empty:
        logger.info(f"Found {len(buy_signals_df)} potential BUY signals in the provided data range.")
        for timestamp, row in buy_signals_df.iterrows():
            signal_time_ts = int(timestamp.timestamp())
            signals.append({
                "timestamp": signal_time_ts,
                "price": row['close'],
                "rsi": row['RSI_14'],
                "stoch_rsi_k": row['STOCHRSIk_60_60_10_10']
            })
    else:
        logger.info("No buy signals matching the specified criteria were found in the data.")
    
    return signals

@app.get("/get_buy_signals/{symbol}")
async def get_buy_signals_endpoint(symbol: str, resolution: str, from_ts: int, to_ts: int):
    """
    Analyzes historical data for a symbol to find moments that match the
    "buy the dip in a downtrend" criteria.
    """
    # Convert timestamps to human-readable format for logging
    from_dt_str = datetime.fromtimestamp(from_ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    to_dt_str = datetime.fromtimestamp(to_ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    logger.info(f"GET /get_buy_signals/{symbol} request: res={resolution}, from={from_dt_str}, to={to_dt_str}")
    # Validation
    if symbol not in SUPPORTED_SYMBOLS or resolution not in timeframe_config.supported_resolutions:
        raise HTTPException(status_code=400, detail="Unsupported symbol or resolution")

    # Calculate lookback needed for indicators (EMA 200 is the longest)
    lookback_periods = 200 + 50  # 200 for EMA, 50 as a buffer
    timeframe_secs = get_timeframe_seconds(resolution)
    fetch_start_ts = from_ts - (lookback_periods * timeframe_secs)

    signals= []

    try:
        # Fetch klines with lookback
        klines_for_calc = await get_cached_klines(symbol, resolution, fetch_start_ts, to_ts)
        # Check if cache is missing data at the start
        if not klines_for_calc or klines_for_calc[0]['time'] > fetch_start_ts:
            logger.info(f"Cache miss or insufficient lookback for {symbol}. Fetching from Bybit.")
            bybit_klines = fetch_klines_from_bybit(symbol, resolution, fetch_start_ts, to_ts)
            if bybit_klines:
                await cache_klines(symbol, resolution, bybit_klines)
                # Re-query from cache to get a consolidated list
                klines_for_calc = await get_cached_klines(symbol, resolution, fetch_start_ts, to_ts)

        if not klines_for_calc:
            return JSONResponse({"status": "error", "message": "Not enough historical data to perform analysis."}, status_code=404)

        # Prepare DataFrame
        df = pd.DataFrame(klines_for_calc)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('time', inplace=True)
        df.rename(columns={'vol': 'volume'}, inplace=True)
        # pandas_ta needs lowercase ohlcv
        df.columns = [col.lower() for col in df.columns]

        # Add all necessary indicators for the signal logic
        df.ta.ema(length=21, append=True)
        df.ta.ema(length=50, append=True)
        df.ta.ema(length=200, append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.stochrsi(rsi_length=60, length=60, k=10, d=10, append=True)

        # Calculate SMAs for RSI
        df[f'RSI_SMA_5'] = df['RSI_14'].rolling(window=5).mean()
        df[f'RSI_SMA_10'] = df['RSI_14'].rolling(window=10).mean()
        df[f'RSI_SMA_3'] = df['RSI_14'].rolling(window=3).mean()
        df[f'RSI_SMA_3'] = df['RSI_14'].rolling(window=3).mean()
        df[f'RSI_SMA_3'] = df['RSI_14'].rolling(window=3).mean()
        df[f'RSI_SMA_20'] = df['RSI_14'].rolling(window=20).mean()


        # Drop rows with NaNs that result from indicator calculations
        df.dropna(subset=[f'EMA_200', 'RSI_14', 'STOCHRSIk_60_60_10_10', 'STOCHRSId_60_60_10_10'], inplace=True)
        
        if df.empty:
            logger.warning(f"DataFrame for {symbol} became empty after indicator calculation and dropna.")
            return JSONResponse({"status": "error", "message": "Not enough data to calculate all indicators for the requested range."}, status_code=500)
            
        # Find all signals in the calculated (extended) range
        significant_divergence = detect_bullish_divergence(
            df,
            price_col="high",
            rsi_col="RSI_14",
            rsi_oversold_level=40
        )
        
        if significant_divergence:
            intersection_point = find_breakout_intersection(df, significant_divergence[0])
            
            # Print the final result to the console
            if intersection_point:
                print("\n--- BREAKOUT ANALYSIS COMPLETE ---")
                print(f"  > Trendline Breakout Date: {intersection_point['date'].strftime('%Y-%m-%d')}")
                print(f"  > Breakout Price Level:    ${intersection_point['price']:.2f}")
                print("----------------------------------\n")
            
                signal_time_ts = int(intersection_point['date'].timestamp())  # Convert to timestamp
                signals.append({
                    "timestamp": signal_time_ts,
                    "price": intersection_point['price']  # Use the price directly
                })           
            
            # Plot the chart with the breakout point marked
            # plot_chart_with_divergence(df, significant_divergence, symbol, intersection=intersection_point)
            
            return JSONResponse({"status": "success", "signals": signals})
        else:
            logger.info(f"No bullish divergence signals found for {symbol}.")
            # Fallback to original buy signal logic if no divergence is found
            pass # No changes needed; code will continue to original logic below
        
    except Exception as e:
        logger.error(f"Error in /get_buy_signals endpoint for {symbol}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred during signal analysis.")


@app.get("/stream/logs")
async def stream_logs(request: Request):
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
from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from typing import Dict, List, Any
import json
import uuid


@app.post("/set_last_symbol/{symbol}")
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


@app.get("/get_last_symbol")
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



if __name__ == "__main__":
    if require_valid_certificate:
        res = session.get_account_info()
        logger.info(f"Account info:")
        logger.info(res.get("result"))

        unifiedMarginStatus = res.get("result")["unifiedMarginStatus"]    
        account_type = {
            1: "classic account",

            3: "uta1.0",
            4: "uta1.0 (pro version)",
            5: "uta2.0",
            6: "uta2.0 (pro version)"
        }.get(unifiedMarginStatus, "Unknown account type")
        logger.info(f"Account Type: {account_type}")

    # You can set an extra attribute on the app instance if you want to pass the debug state
    # This is one way to make the "debug" status available to the middleware.
    # However, relying on an environment variable like FASTAPI_DEBUG is often cleaner.
    is_debug_mode = True # Assume debug if running directly like this with reload=True
    app.extra["debug_mode"] = is_debug_mode
    # For the environment variable approach, you'd set FASTAPI_DEBUG=true in your shell before running.

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    IP_ADDRESS = s.getsockname()[0]
    logger.info(f'Local address: {IP_ADDRESS}')
    s.close()    

    uvicorn.run("AppTradingView:app", host=IP_ADDRESS, port=5000, reload=False)
