import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import pandas as pd
import datetime
import time
import random
from tqdm import tqdm # Import tqdm
import os # Import os for file operations
import uuid # For generating unique trade IDs
import json # For serializing/deserializing data in Redis
import redis # For Redis interaction
import traceback # For detailed error logging

# Use ta library for indicators
from ta import add_all_ta_features
from ta.volatility import AverageTrueRange
import pandas_ta as ta # Use pandas_ta for consistency with AppTradingView

# Use pybit for fetching data if needed for backfill
from pybit.unified_trading import HTTP as BybitHTTPClient

# Set device to GPU if available, otherwise CPU
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Using device: {device}")

# Hyperparameters
LEARNING_RATE = 0.001
GAMMA = 0.99
EPSILON_START = 1.0
EPSILON_END = 0.01
EPSILON_DECAY = 0.999  # Slower decay for more exploration
BATCH_SIZE = 64  # Increased batch size
MEMORY_CAPACITY = 100000
NUM_EPISODES = 500  # Increased number of episodes
UPDATE_FREQUENCY = 500  # Less frequent target network updates for stability
# Risk management parameters
STOP_LOSS_PERCENT = 0.05  # 5% stop loss
TAKE_PROFIT_PERCENT = 0.15 # Lowered take profit to 10%
POSITION_SIZE_PERCENT = 0.05  # 5% of networth for position sizing (kept for now)
UNREALIZED_PNL_REWARD_SCALE = 0.1 # Scaling factor for unrealized PnL reward shaping

# --- Configuration (Copied/Adapted from TradingAgent2.py) ---
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_OHLCV_KEY_PREFIX = f"agent:zset:kline:BTCUSDT:5m" # Use the same key as AppTradingView.py
REDIS_OPEN_INTEREST_KEY_PREFIX = f"agent:zset:open_interest:BTCUSDT:5m" # Dedicated key for Open Interest data
MIN_RECORDS_FOR_TRAINING = 100000 # Desired number of records
TRADING_SYMBOL = "BTCUSDT" # Symbol to trade
TRADING_TIMEFRAME = "5m" # Timeframe for data
BYBIT_API_KEY_AGENT = os.getenv("BYBIT_API_KEY_AGENT", "YOUR_BYBIT_API_KEY_HERE")
BYBIT_API_SECRET_AGENT = os.getenv("BYBIT_API_SECRET_AGENT", "YOUR_BYBIT_SECRET_HERE")
LOG_FILE = "gemini_RL_log.txt" # Separate log file for this agent
# --- End Configuration ---

# --- Helper Functions (Copied/Adapted from TradingAgent2.py) ---
def log_message(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_message = f"[{timestamp}] {message}"
    print(full_message)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(full_message + "\n")

def get_redis_connection():
    try:
        # decode_responses=False because data is JSON strings, we'll decode after fetching
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=False)
        r.ping()
        log_message(f"Successfully connected to Redis ({REDIS_HOST}:{REDIS_PORT}, DB {REDIS_DB}).")
        return r
    except redis.exceptions.ConnectionError as e:
        log_message(f"CRITICAL: Could not connect to Redis: {e}")
        return None

bybit_session_agent = None

def get_bybit_session_agent():
    global bybit_session_agent
    if bybit_session_agent is None:
        if BYBIT_API_KEY_AGENT == "YOUR_BYBIT_API_KEY_HERE" or BYBIT_API_SECRET_AGENT == "YOUR_BYBIT_SECRET_HERE":
            log_message("WARNING: Bybit API key/secret not configured. Backfilling from Bybit will fail if needed.")
            # Allow to proceed if Redis already has enough data, but fetching will fail.
        bybit_session_agent = BybitHTTPClient(
            api_key=BYBIT_API_KEY_AGENT,
            api_secret=BYBIT_API_SECRET_AGENT,
            testnet=False # Assuming mainnet
        )
    return bybit_session_agent

def get_timeframe_seconds_agent(timeframe: str) -> int:
    multipliers = {"1m": 60, "5m": 300, "1h": 3600, "1d": 86400, "1w": 604800}
    return multipliers.get(timeframe, 300) # Default to 5m if not found

def format_kline_data_agent(bar: list) -> dict:
    """Formats a single kline bar from Bybit API response."""
    return {
        "time": int(bar[0]) // 1000, # Bybit timestamp is in ms
        "open": float(bar[1]),
        "high": float(bar[2]),
        "low": float(bar[3]),
        "close": float(bar[4]),
        "volume": float(bar[5]) # Bybit calls it 'volume'
        # 'turnover' is bar[6], not typically used as 'volume' by TA libraries
    }

def fetch_klines_from_bybit_agent(symbol: str, resolution: str, start_ts: int, end_ts: int) -> list:
    """Fetches klines from Bybit for the agent's backfilling purposes."""
    session = get_bybit_session_agent()
    if not session:
        log_message("ERROR: Bybit session not available for fetching klines.")
        return []

    log_message(f"Fetching klines from Bybit for {symbol} {resolution} from {datetime.datetime.fromtimestamp(start_ts, tz=datetime.timezone.utc)} to {datetime.datetime.fromtimestamp(end_ts, tz=datetime.timezone.utc)}")
    all_klines: list = []
    current_start = start_ts
    timeframe_seconds = get_timeframe_seconds_agent(resolution)
    bybit_resolution_map = {"1m": "1", "5m": "5", "1h": "60", "1d": "D", "1w": "W"}

    while current_start < end_ts:
        # Bybit limit is 1000 candles per request.
        # Calculate batch_end to not exceed 1000 candles or the overall end_ts.
        batch_end = min(current_start + (1000 * timeframe_seconds) - 1, end_ts)
        log_message(f"  Fetching Bybit batch: {datetime.datetime.fromtimestamp(current_start, tz=datetime.timezone.utc)} to {datetime.datetime.fromtimestamp(batch_end, tz=datetime.timezone.utc)}")
        try:
            response = session.get_kline(
                category="linear", # Or "spot" if you trade spot
                symbol=symbol,
                interval=bybit_resolution_map.get(resolution, "5"), # Default to 5 min if resolution string is weird
                start=current_start * 1000, # Bybit expects milliseconds
                end=batch_end * 1000,       # Bybit expects milliseconds
                limit=1000
            )
        except Exception as e:
            log_message(f"ERROR: Bybit API request failed: {e}")
            break

        if response.get("retCode") != 0:
            log_message(f"ERROR: Bybit API error: {response.get('retMsg', 'Unknown error')}")
            break

        bars = response.get("result", {}).get("list", [])
        if not bars:
            log_message("  No more data available from Bybit for this range.")
            break

        # Bybit returns data in reverse chronological order (newest first)
        batch_klines = [format_kline_data_agent(bar) for bar in reversed(bars)]
        all_klines.extend(batch_klines)

        if not batch_klines or len(bars) < 1000: # No more data or last page
            break

        # Next query starts after the last fetched kline's timestamp
        last_fetched_ts_in_batch = batch_klines[-1]["time"]
        current_start = last_fetched_ts_in_batch + timeframe_seconds

    all_klines.sort(key=lambda x: x["time"]) # Ensure chronological order
    log_message(f"Total klines fetched from Bybit: {len(all_klines)}")
    return all_klines

def cache_klines_agent(redis_conn, symbol: str, resolution: str, klines: list, redis_key_prefix=REDIS_OHLCV_KEY_PREFIX):
    """Caches klines into Redis sorted set for the agent."""
    import json # Explicitly import json within the function
    if not redis_conn or not klines: return
    log_message(f"Caching {len(klines)} klines to Redis key '{redis_key_prefix}'...")
    pipeline_batch_size = 500  # Number of ZADD commands per batch
    klines_processed_count = 0
    pipe = redis_conn.pipeline()
    try:
        for i, kline_data in enumerate(klines):
            timestamp = kline_data["time"]
            # The 'volume' key should already be correct from format_kline_data_agent
            data_str = json.dumps(kline_data)
            pipe.zadd(redis_key_prefix, {data_str: timestamp})
            klines_processed_count += 1

            if (i + 1) % pipeline_batch_size == 0:
                pipe.execute()
                log_message(f"Executed batch of {pipeline_batch_size} ZADD commands for {symbol} {resolution}.")
        if len(pipe.command_stack) > 0: # Execute any remaining commands
            pipe.execute()
        log_message(f"Successfully cached {klines_processed_count} klines for {symbol} {resolution}.")
    except Exception as e:
        log_message(f"ERROR during kline caching for {symbol} {resolution}: {e}")

def fetch_open_interest_from_bybit_agent(symbol: str, interval: str, start_ts: int, end_ts: int) -> list:
    """Fetches Open Interest data from Bybit for the agent's backfilling purposes."""
    session = get_bybit_session_agent()
    if not session:
        log_message("ERROR: Bybit session not available for fetching Open Interest.")
        return []

    log_message(f"Fetching Open Interest for {symbol} {interval} from {datetime.datetime.fromtimestamp(start_ts, tz=datetime.timezone.utc)} to {datetime.datetime.fromtimestamp(end_ts, tz=datetime.timezone.utc)}")
    all_oi_data: list = []
    current_start = start_ts
    
    # Bybit's get_open_interest intervalTime parameter has specific values.
    # We assume TRADING_TIMEFRAME (e.g., "5m") maps to a valid intervalTime like "5min".
    oi_interval_map = {"1m": "5min", "5m": "5min", "1h": "1h", "1d": "1d", "1w": "1d"}
    bybit_oi_interval = oi_interval_map.get(interval, "5min")

    oi_interval_seconds_map = {"5min": 300, "15min": 900, "30min": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
    interval_seconds = oi_interval_seconds_map.get(bybit_oi_interval)
    if not interval_seconds:
        log_message(f"ERROR: Unsupported Open Interest interval for calculation: {bybit_oi_interval}")
        return []

    while current_start < end_ts:
        batch_end = min(current_start + (200 * interval_seconds) - 1, end_ts)
        log_message(f"  Fetching OI batch: {datetime.datetime.fromtimestamp(current_start, tz=datetime.timezone.utc)} to {datetime.datetime.fromtimestamp(batch_end, tz=datetime.timezone.utc)}")
        try:
            response = session.get_open_interest(
                category="linear",
                symbol=symbol,
                intervalTime=bybit_oi_interval,
                start=current_start * 1000,
                end=batch_end * 1000,
                limit=200
            )
        except Exception as e:
            log_message(f"ERROR: Bybit API request for Open Interest failed: {e}")
            break

        if response.get("retCode") != 0:
            log_message(f"ERROR: Bybit API error for Open Interest: {response.get('retMsg', 'Unknown error')}")
            break

        list_data = response.get("result", {}).get("list", [])
        if not list_data:
            log_message("  No more Open Interest data available from Bybit for this range.")
            break
        
        batch_oi = []
        for item in reversed(list_data):
            batch_oi.append({
                "time": int(item["timestamp"]) // 1000,
                "open_interest": float(item["openInterest"])
            })
        all_oi_data.extend(batch_oi)
        
        if not batch_oi or len(list_data) < 200:
            break
        
        last_fetched_ts_in_batch = batch_oi[-1]["time"]
        current_start = last_fetched_ts_in_batch + interval_seconds
        
    all_oi_data.sort(key=lambda x: x["time"]) # Ensure chronological order
    log_message(f"Total Open Interest data fetched from Bybit: {len(all_oi_data)}")
    return all_oi_data

def cache_open_interest_agent(redis_conn, symbol: str, resolution: str, oi_data: list, redis_key_prefix=REDIS_OPEN_INTEREST_KEY_PREFIX):
    """Caches Open Interest data into Redis sorted set for the agent."""
    if not redis_conn or not oi_data: return
    log_message(f"Caching {len(oi_data)} Open Interest records to Redis key '{redis_key_prefix}'...")
    pipeline_batch_size = 500
    oi_processed_count = 0
    pipe = redis_conn.pipeline()
    try:
        for i, oi_entry in enumerate(oi_data):
            # Store the exact timestamp from Bybit
            timestamp = oi_entry["time"]
            data_str = json.dumps(oi_entry)
            pipe.zadd(redis_key_prefix, {data_str: timestamp})
            oi_processed_count += 1

            if (i + 1) % pipeline_batch_size == 0:
                pipe.execute()
        if len(pipe.command_stack) > 0:
            pipe.execute()
        log_message(f"Successfully cached {oi_processed_count} Open Interest records for {symbol} {resolution}.")
    except Exception as e:
        log_message(f"ERROR during Open Interest caching for {symbol} {resolution}: {e}")

def fetch_all_historical_data_from_redis(redis_conn, redis_key=REDIS_OHLCV_KEY_PREFIX, min_records=MIN_RECORDS_FOR_TRAINING):
    # Modified _fetch_and_process_from_redis_internal to accept score ranges
    def _fetch_and_process_from_redis_internal(r_conn, r_key, required_cols: list, min_score=None, max_score=None) -> pd.DataFrame:
        """
        DEBUG: This function is called to fetch and process data from Redis.
        Internal helper to fetch and process data from a Redis Sorted Set for a given score range.
    Assumes scores are timestamps and values are JSON strings of candle data.
        """
        import json # Explicitly import json within the function
        # Use zrangebyscore for time-based fetching
        # If min_score/max_score are None, it fetches all data (from -inf to +inf)
        raw_candles_with_scores_internal = r_conn.zrangebyscore(
            r_key,
            min=min_score if min_score is not None else '-inf',
            max=max_score if max_score is not None else '+inf',
            withscores=True
        )
        log_message(f"DEBUG: _fetch_and_process_from_redis_internal for key '{r_key}' range [{min_score}, {max_score}] returned {len(raw_candles_with_scores_internal)} raw items from Redis.")
        
        if not raw_candles_with_scores_internal:
            log_message(f"DEBUG: _fetch_and_process_from_redis_internal for key '{r_key}' returning empty DataFrame (no raw items).")
            return pd.DataFrame()
        data_internal = []
        for raw_candle_json, score_timestamp in raw_candles_with_scores_internal:
            try:
                # Decode bytes and parse JSON
                candle_data = json.loads(raw_candle_json.decode('utf-8'))
                # Add timestamp from the score
                candle_data['timestamp'] = int(score_timestamp)
                data_internal.append(candle_data)
            except Exception as e_proc:
                log_message(f"Warning: Error processing a candle from Redis (ts: {score_timestamp}): {e_proc}")

        if not data_internal:
            log_message(f"DEBUG: _fetch_and_process_from_redis_internal for key '{r_key}' returning empty DataFrame (data_internal empty after parsing).")
            return pd.DataFrame()

        # Create DataFrame and set datetime index
        df_internal = pd.DataFrame(data_internal)
        df_internal['datetime'] = pd.to_datetime(df_internal['timestamp'], unit='s', utc=True)
        df_internal.set_index('datetime', inplace=True)

        # Ensure required columns exist and are float type
        if not all(col in df_internal.columns for col in required_cols):
            log_message(f"CRITICAL: _fetch_and_process_from_redis_internal for key '{r_key}' returning empty DataFrame (missing required columns: {[col for col in required_cols if col not in df_internal.columns]}).")
            return pd.DataFrame()
        df_internal = df_internal[required_cols].astype(float).sort_index()

        # Remove duplicate indices (keep the last one in case of overlaps)
        df_internal = df_internal[~df_internal.index.duplicated(keep='last')]
        log_message(f"DEBUG: _fetch_and_process_from_redis_internal for key '{r_key}' returning DataFrame of shape {df_internal.shape} (empty: {df_internal.empty}).")

        return df_internal

    """
    Fetches historical OHLCV data from a Redis Sorted Set, filling gaps from Bybit if necessary.
    Ensures at least `min_records` are available, covering the most recent period.
    """
    log_message(f"Ensuring {min_records} records are available for Redis key '{redis_key}'...")
    if not redis_conn:
        log_message("No Redis connection available for fetching data.")
        return {'klines': pd.DataFrame(), 'open_interest': pd.DataFrame()}

    try:
        timeframe_seconds = get_timeframe_seconds_agent(TRADING_TIMEFRAME)
        
        # Determine the target end time (current time) and target start time
        target_end_ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        target_start_ts = target_end_ts - (min_records * timeframe_seconds) # Calculate desired start based on min_records

        # Define a segment size for fetching/checking (e.g., 1 day's worth of data)
        # This helps manage memory and allows for more granular gap filling.
        segment_duration_secs = 24 * 3600 # 1 day
        
        current_segment_start_ts = target_start_ts # Start checking from the desired historical start
        
        # Loop forward in time, checking segments and filling gaps
        while current_segment_start_ts < target_end_ts:
            segment_end_ts = min(current_segment_start_ts + segment_duration_secs - 1, target_end_ts)
            
            # Fetch data for this segment from Redis
            df_segment_redis = _fetch_and_process_from_redis_internal(redis_conn, redis_key,
                                                                     required_cols=['timestamp', 'open', 'high', 'low', 'close', 'volume'],
                                                                     min_score=current_segment_start_ts,
                                                                     max_score=segment_end_ts)
            
            expected_records_in_segment = (segment_end_ts - current_segment_start_ts + 1) // timeframe_seconds
            
            # Check if Redis data for this segment is insufficient
            # We allow a small tolerance for missing data (e.g., 5% or 1 candle)
            if len(df_segment_redis) < expected_records_in_segment * 0.95 or df_segment_redis.empty:
                log_message(f"Gap detected or insufficient data in Redis for kline segment: {datetime.datetime.fromtimestamp(current_segment_start_ts, datetime.timezone.utc)} to {datetime.datetime.fromtimestamp(segment_end_ts, datetime.timezone.utc)}. Expected: {expected_records_in_segment}, Found: {len(df_segment_redis)}. Fetching from Bybit...")
                
                fetched_bybit_klines = fetch_klines_from_bybit_agent(TRADING_SYMBOL, TRADING_TIMEFRAME, 
                                                                     current_segment_start_ts, segment_end_ts)
                if fetched_bybit_klines:
                    cache_klines_agent(redis_conn, TRADING_SYMBOL, TRADING_TIMEFRAME, fetched_bybit_klines, redis_key)
                    # After caching, the loop will re-evaluate this segment.
                else:
                    log_message(f"No data fetched from Bybit for segment {datetime.datetime.fromtimestamp(current_segment_start_ts, datetime.timezone.utc)} to {datetime.datetime.fromtimestamp(segment_end_ts, datetime.timezone.utc)}.")
                    # If no data could be fetched, we must advance to avoid an infinite loop.
                    current_segment_start_ts = segment_end_ts + 1
            else:
                # Segment is full, advance to the next one.
                current_segment_start_ts = segment_end_ts + 1

        # After attempting to fill all gaps, fetch the consolidated data for the target range
        log_message(f"Consolidating klines data from Redis for target range: {datetime.datetime.fromtimestamp(target_start_ts, datetime.timezone.utc)} to {datetime.datetime.fromtimestamp(target_end_ts, datetime.timezone.utc)}.")
        df_consolidated = _fetch_and_process_from_redis_internal(
            redis_conn, redis_key,
            required_cols=['timestamp', 'open', 'high', 'low', 'close', 'volume'],
            min_score=target_start_ts,
            max_score=target_end_ts)
        
        log_message(f"Consolidated klines data fetched: {len(df_consolidated)} records.")
        if len(df_consolidated) < min_records:
            log_message(f"Warning: Consolidated data ({len(df_consolidated)}) is still less than desired ({min_records}). This might indicate persistent gaps or insufficient historical data on Bybit.")

        df_klines = df_consolidated # This is the consolidated klines DataFrame

    except redis.exceptions.RedisError as e:
        log_message(f"Redis error during fetch_all_historical_data (Klines): {e}")
        df_klines = pd.DataFrame() # Ensure df_klines is a DataFrame even on error
    except Exception as e:
        log_message(f"General error during fetch_all_historical_data (Klines): {e}")
        traceback.print_exc() # Print full traceback for debugging
        df_klines = pd.DataFrame() # Ensure df_klines is a DataFrame even on error

    # --- Fetch and process Open Interest ---
    df_open_interest = pd.DataFrame()
    oi_redis_key = REDIS_OPEN_INTEREST_KEY_PREFIX
    try:
        # Determine the target end time (current time) and target start time for OI
        target_end_ts_oi = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        target_start_ts_oi = target_end_ts_oi - (min_records * timeframe_seconds)

        current_segment_start_ts_oi = target_start_ts_oi
        while current_segment_start_ts_oi < target_end_ts_oi:
            segment_end_ts_oi = min(current_segment_start_ts_oi + segment_duration_secs - 1, target_end_ts_oi)
            
            # Round segment boundaries to the nearest timeframe_seconds for OI
            # This is crucial if OI timestamps are strictly aligned to intervals
            rounded_segment_start_ts_oi = (current_segment_start_ts_oi // timeframe_seconds) * timeframe_seconds
            # Round up the end_ts to ensure the last interval is included, then subtract 1 to stay within the interval
            rounded_segment_end_ts_oi = ((segment_end_ts_oi + timeframe_seconds) // timeframe_seconds) * timeframe_seconds - 1
            
            log_message(f"DEBUG: OI segment original range: [{current_segment_start_ts_oi}, {segment_end_ts_oi}], rounded to: [{rounded_segment_start_ts_oi}, {rounded_segment_end_ts_oi}]")

            # Fetch data for this segment from Redis
            # Ensure required_cols is passed here
            df_segment_redis_oi = _fetch_and_process_from_redis_internal(redis_conn, oi_redis_key,
                                                                       required_cols=['timestamp', 'open_interest'],
                                                                       min_score=rounded_segment_start_ts_oi,
                                                                       max_score=rounded_segment_end_ts_oi) # Use rounded segment end for max_score
            expected_records_in_segment_oi = (segment_end_ts_oi - current_segment_start_ts_oi + 1) // timeframe_seconds
            
            if len(df_segment_redis_oi) < expected_records_in_segment_oi * 0.95 or df_segment_redis_oi.empty:
                log_message(f"Gap detected or insufficient data in Redis for OI segment: {datetime.datetime.fromtimestamp(current_segment_start_ts_oi, datetime.timezone.utc)} to {datetime.datetime.fromtimestamp(segment_end_ts_oi, datetime.timezone.utc)}. Expected: {expected_records_in_segment_oi}, Found: {len(df_segment_redis_oi)}. Fetching from Bybit...")
                
                fetched_bybit_oi = fetch_open_interest_from_bybit_agent(TRADING_SYMBOL, TRADING_TIMEFRAME, 
                                                                     current_segment_start_ts_oi, segment_end_ts_oi)
                if fetched_bybit_oi:
                    cache_open_interest_agent(redis_conn, TRADING_SYMBOL, TRADING_TIMEFRAME, fetched_bybit_oi, oi_redis_key)
                else:
                    log_message(f"No OI data fetched from Bybit for segment {datetime.datetime.fromtimestamp(current_segment_start_ts_oi, datetime.timezone.utc)} to {datetime.datetime.fromtimestamp(segment_end_ts_oi, datetime.timezone.utc)}.")
            
            # Always advance to the next segment to prevent an infinite loop.
            # This change makes the backfilling process complete in one pass,
            # relying on subsequent runs to use the now-cached data.
            current_segment_start_ts_oi = segment_end_ts_oi + 1

        log_message(f"Consolidating OI data from Redis for target range: {datetime.datetime.fromtimestamp(target_start_ts_oi, datetime.timezone.utc)} to {datetime.datetime.fromtimestamp(target_end_ts_oi, datetime.timezone.utc)}.")
        df_open_interest = _fetch_and_process_from_redis_internal(
            redis_conn, oi_redis_key,
            required_cols=['timestamp', 'open_interest'],
            min_score=target_start_ts_oi,
            max_score=target_end_ts_oi)
        
        log_message(f"Consolidated OI data fetched: {len(df_open_interest)} records.")
        if len(df_open_interest) < min_records:
            log_message(f"Warning: Consolidated OI data ({len(df_open_interest)}) is still less than desired ({min_records}).")

    except redis.exceptions.RedisError as e:
        log_message(f"Redis error during fetch_all_historical_data (Open Interest): {e}")
        df_open_interest = pd.DataFrame() # Ensure df_open_interest is a DataFrame even on error
    except Exception as e:
        log_message(f"General error during fetch_all_historical_data (Open Interest): {e}")
        traceback.print_exc()
        df_open_interest = pd.DataFrame() # Ensure df_open_interest is a DataFrame even on error

    return {'klines': df_klines, 'open_interest': df_open_interest}

def detect_and_report_buy_signals(df: pd.DataFrame):
    """
    Analyzes a DataFrame with technical indicators to find specific buy signals.
    The strategy identifies opportunities during a confirmed downtrend when momentum
    oscillators show a potential bottom and reversal.

    Args:
        df (pd.DataFrame): The DataFrame containing OHLCV data and un-normalized
                           technical indicators (EMAs, RSI, etc.).
    """
    log_message("--- Running Buy Signal Detection with Downtrend Logic ---")

    # --- Define Signal Conditions ---
    RSI_OVERSOLD_LEVEL = 30
    STORSI_OVERSOLD_LEVEL = 20
    SLOPE_LOOKBACK = 5  # Look back 5 periods to check the slope of the short-term EMA.

    # Ensure required columns from the new logic exist
    required_cols = ['close', 'RSI_14', 'STOCHRSIk_60_60_10_10', 'STOCHRSId_60_60_10_10',
                     'EMA_21', 'EMA_50', 'EMA_200']
    if not all(col in df.columns for col in required_cols):
        log_message(f"ERROR: Missing one or more required columns for signal detection: {required_cols}")
        return

    df_signal = df.copy()

    # --- Implement the Logic using Vectorized Operations ---

    # Condition 1: Confirm a clear downtrend (NEW and IMPROVED LOGIC)
    # Part A: The overall trend structure is bearish (medium-term EMA is below long-term EMA).
    cond_downtrend_regime = df_signal['EMA_50'] < df_signal['EMA_200']

    # Part B: There is recent downward momentum (the slope of the short-term EMA is negative).
    # We calculate the slope by seeing if the EMA value now is lower than it was a few periods ago.
    ema_slope = df_signal['EMA_21'].diff(periods=SLOPE_LOOKBACK)
    cond_recent_downward_move = ema_slope < 0

    # Combine both parts for a robust downtrend signal.
    cond_is_downtrend = cond_downtrend_regime & cond_recent_downward_move

    # Condition 2: RSI was oversold and is now rising.
    cond_rsi_recovering = (df_signal['RSI_14'].shift(1) < RSI_OVERSOLD_LEVEL) & \
                          (df_signal['RSI_14'] > df_signal['RSI_14'].shift(1))

    # Condition 3: The key STOCHRSI_60_10 shows a bullish crossover from the oversold zone.
    # This remains the primary trigger.
    k_line = df_signal['STOCHRSIk_60_60_10_10']
    d_line = df_signal['STOCHRSId_60_60_10_10']

    cond_storsi_crossover = (k_line.shift(1) < d_line.shift(1)) & \
                            (k_line > d_line) & \
                            (k_line.shift(1) < STORSI_OVERSOLD_LEVEL)

    # --- Combine all conditions to identify the final buy signals ---
    # The agent should BUY when we are in a DOWNTREND, but RSI and STO_RSI show a REVERSAL.
    buy_signals = df_signal[cond_is_downtrend & cond_rsi_recovering & cond_storsi_crossover]

    if not buy_signals.empty:
        log_message(f"Found {len(buy_signals)} potential BUY signals matching the criteria.")
        for timestamp, row in buy_signals.iterrows():
            signal_time = timestamp.strftime('%Y-%m-%d %H:%M:%S')
            log_message(
                f">>> BUY SIGNAL DETECTED <<< at {signal_time} UTC | "
                f"Price: {row['close']:.2f} (Trend: DOWN, EMA50: {row['EMA_50']:.2f} < EMA200: {row['EMA_200']:.2f}) | "
                f"RSI: {row['RSI_14']:.2f} (Recovering) | "
                f"StoRSI(60,10) k: {row['STOCHRSIk_60_60_10_10']:.2f} (Crossover)"
            )
    else:
        log_message("No buy signals matching the specified downtrend/reversal criteria were found.")


def process_dataframe_with_atr(data_dfs: dict, data_source_name="DataFrame"):
    """
    Processes the raw DataFrames (klines and open interest) by merging them,
    adding technical indicators, and normalizing features.
    """
    df_raw = data_dfs.get('klines')
    df_oi_raw = data_dfs.get('open_interest')

    log_message(f"Processing DataFrame from: {data_source_name} (Initial klines shape: {df_raw.shape if df_raw is not None else 'N/A'})")
    if df_raw is None or df_raw.empty:
        log_message("Input Kline DataFrame is empty. Cannot process.")
        return pd.DataFrame()
    try:
        df = df_raw.copy()
        # Ensure index is DatetimeIndex
        if not isinstance(df.index, pd.DatetimeIndex):
            if 'datetime' in df.columns:
                df['datetime'] = pd.to_datetime(df['datetime'])
                df.set_index('datetime', inplace=True)
            elif 'timestamp' in df.columns:
                df['datetime'] = pd.to_datetime(df['timestamp'], unit='s', utc=True)
                df.set_index('datetime', inplace=True)
            else:
                # If no datetime or timestamp column, assume index is already datetime or can be converted
                try:
                    df.index = pd.to_datetime(df.index, utc=True)
                except Exception:
                     raise ValueError("DataFrame must have DatetimeIndex or 'datetime'/'timestamp' column.")

        # Ensure OHLCV columns are present and numeric
        ohlcv_cols = ['open', 'high', 'low', 'close', 'volume']
        for col in ohlcv_cols:
            if col not in df.columns: raise ValueError(f"Required column '{col}' missing.")
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df.dropna(subset=ohlcv_cols, inplace=True)

        if df.empty:
            log_message(f"DataFrame empty after OHLCV processing from {data_source_name}.")
            return pd.DataFrame()

        # Store original close price before adding TA features and normalization
        df['original_close'] = df['close']

        # Merge Open Interest data
        if df_oi_raw is not None and not df_oi_raw.empty:
            # Ensure OI DataFrame has a datetime index for merging
            if not isinstance(df_oi_raw.index, pd.DatetimeIndex):
                if 'time' in df_oi_raw.columns:
                    df_oi_raw['datetime'] = pd.to_datetime(df_oi_raw['time'], unit='s', utc=True)
                    df_oi_raw.set_index('datetime', inplace=True)
            
            # Merge OI data with kline data. Use a left join to keep all kline timestamps.
            # Forward fill or backfill OI if its granularity is coarser than klines.
            df = pd.merge(df, df_oi_raw[['open_interest']], left_index=True, right_index=True, how='left')
            df['open_interest'] = df['open_interest'].ffill().bfill() # Fill NaNs from merge
            if df['open_interest'].isnull().any():
                log_message("Warning: Open Interest column still contains NaNs after ffill/bfill. Filling remaining with 0.")
                df['open_interest'] = df['open_interest'].fillna(0)

        # Add all TA features using pandas_ta
        # Note: pandas_ta expects lowercase column names for ohlcv
        df.columns = [col.lower() for col in df.columns]
        df = add_all_ta_features(df, open="open", high="high", low="low", close="close", volume="volume", fillna=True)

        # Add ATR specifically (often used for volatility)
        # Check if 'volatility_atr' exists after add_all_ta_features, if not, calculate it
        if 'volatility_atr' not in df.columns:
             log_message("Warning: 'volatility_atr' not found after add_all_ta_features. Calculating manually.")
             atr_indicator = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14, fillna=True)
             df['volatility_atr'] = atr_indicator.average_true_range()

        # --- Add Technical Indicators using pandas-ta for consistency with AppTradingView ---
        # MACD
        df.ta.macd(fast=12, slow=26, signal=9, append=True)
        # RSI
        df.ta.rsi(length=14, append=True)
        # ATR
        df.ta.atr(length=14, append=True)
        # Stochastic RSI variations
        df.ta.stochrsi(rsi_length=9, length=9, k=3, d=3, append=True)
        df.ta.stochrsi(rsi_length=14, length=14, k=3, d=3, append=True)
        df.ta.stochrsi(rsi_length=40, length=40, k=4, d=4, append=True)
        df.ta.stochrsi(rsi_length=60, length=60, k=10, d=10, append=True)
 
        # --- Add EMAs for Downtrend Detection ---
        df.ta.ema(length=21, append=True)
        df.ta.ema(length=50, append=True)
        df.ta.ema(length=200, append=True)
        
        # Define the features the environment expects
        # This list should match the features generated by add_all_ta_features + ATR that you want to use
        # Updated to include default Stochastic RSI features
        env_expected_features = [
            'open', 'high', 'low', 'close', 'volume', 'open_interest',
            'MACD_12_26_9', 'MACDh_12_26_9', 'MACDs_12_26_9',
            'RSI_14',
            'ATRr_14',
            'STOCHRSIk_9_9_3_3', 'STOCHRSId_9_9_3_3',
            'STOCHRSIk_14_14_3_3', 'STOCHRSId_14_14_3_3',
            'STOCHRSIk_40_40_4_4', 'STOCHRSId_40_40_4_4',
            'STOCHRSIk_60_60_10_10', 'STOCHRSId_60_60_10_10'
        ]

        # Ensure all expected features exist, fill missing ones with 0 (though add_all_ta_features should add many)
        missing_ta_features = [f for f in env_expected_features if f not in df.columns]
        for mf in missing_ta_features:
             log_message(f"Warning: Expected feature '{mf}' not found after TA calculation. Filling with 0.")
             df[mf] = 0.0

        # Drop rows where any of the *expected* features are NaN
        df.dropna(subset=env_expected_features, inplace=True)
        
        if df.empty:
            log_message(f"DataFrame became empty after dropna (post TA) for {data_source_name}.")

        # Normalize the features that the environment will use
        # IMPORTANT: Normalize only the features that go into the state, not the original OHLCV if they are needed raw elsewhere.
        # However, the environment uses the processed df, so normalizing the features here is appropriate.
        # Normalization should be done *after* dropping NaNs.
        for col in env_expected_features:
            mean = df[col].mean()
            std = df[col].std()
            # Handle case where std is zero (e.g., constant value column)
            if std == 0:
                log_message(f"Warning: Standard deviation for column '{col}' is zero. Skipping standardization for this column.")
                continue # Skip standardization for this column
            df[col] = (df[col] - mean) / (std + 1e-8) # Add small constant to avoid division by zero

        log_message(f"Data processing complete for {data_source_name}. Shape: {df.shape}")
        return df[env_expected_features + ['original_close']] # Return features and original_close
    except Exception as e:
        log_message(f"ERROR in process_dataframe_with_atr for {data_source_name}: {e}")
        traceback.print_exc()
        raise

# 2. Model Development
class DQN(nn.Module):
    """Deep Q-Network (DQN) model with enhanced architecture."""

    def __init__(self, state_size, action_size):
        super(DQN, self).__init__()
        # Modified network architecture: 256 -> 128 -> 64
        self.fc1 = nn.Linear(state_size, 256) # Increased size
        self.bn1 = nn.BatchNorm1d(256)  # Adjusted BatchNorm size
        self.dropout1 = nn.Dropout(0.2)  # Dropout for regularization
        
        self.fc2 = nn.Linear(256, 128) # Adjusted input size
        self.bn2 = nn.BatchNorm1d(128)
        self.dropout2 = nn.Dropout(0.2)
        
        self.fc3 = nn.Linear(128, 64) # Kept this layer
        self.bn3 = nn.BatchNorm1d(64)
        self.dropout3 = nn.Dropout(0.2)
        
        self.fc4 = nn.Linear(64, action_size)

    def forward(self, x):
        # Apply batch norm only during training (when batch size > 1)
        if x.size(0) > 1:
            x = torch.relu(self.bn1(self.fc1(x))) # Apply BN before ReLU
            x = self.dropout1(x)
            x = torch.relu(self.bn2(self.fc2(x))) # Apply BN before ReLU
            x = self.dropout2(x)
            x = torch.relu(self.bn3(self.fc3(x))) # Apply BN before ReLU
            x = self.dropout3(x)
        else:
            # During inference with a single sample
            x = torch.relu(self.fc1(x))
            x = torch.relu(self.fc2(x))
            x = torch.relu(self.fc3(x))
        
        x = self.fc4(x)
        return x


class ReplayMemory:
    """Replay memory for storing experiences."""

    def __init__(self, capacity):
        self.capacity = capacity
        self.memory = []
        self.position = 0

    def push(self, *args):
        """Saves a transition."""
        if len(self.memory) < self.capacity:
            self.memory.append(None)
        self.memory[self.position] = tuple(args)
        self.position = (self.position + 1) % self.capacity

    def sample(self, batch_size):
        """Samples a batch of experiences randomly."""
        return random.sample(self.memory, batch_size)

    def __len__(self):
        return len(self.memory)


# 3. Trading Logic
def get_state(data, t, n=10): # n is the window size
    """Gets the state from the data with enhanced features.

    Args:
        data (pandas.DataFrame): DataFrame containing historical data.
        t (int): Current time step.
        n (int): Window size for historical data.

    Returns:
        numpy.ndarray: State vector with enhanced features.
    """
    start = max(t - n + 1, 0)
    end = t + 1
    
    # Use all the technical indicators we've added
    features = [
        'open', 'high', 'low', 'close', 'volume', 'open_interest',
        'MACD_12_26_9', 'MACDh_12_26_9', 'MACDs_12_26_9',
        'RSI_14',
        'ATRr_14',
        'STOCHRSIk_9_9_3_3', 'STOCHRSId_9_9_3_3',
        'STOCHRSIk_14_14_3_3', 'STOCHRSId_14_14_3_3',
        'STOCHRSIk_40_40_4_4', 'STOCHRSId_40_40_4_4',
        'STOCHRSIk_60_60_10_10', 'STOCHRSId_60_60_10_10'
    ]
    
    state_data = data[features].iloc[start:end].values

    # Calculate the expected state length
    num_features = len(features)
    expected_length = n * num_features

    # Flatten the current state data
    flattened_state = state_data.flatten()

    # Pad the state if its length is less than the expected length
    if len(flattened_state) < expected_length:
        padding_length = expected_length - len(flattened_state)
        padded_state = np.pad(flattened_state, (padding_length, 0), 'constant') # Pad with zeros at the beginning
    else:
        padded_state = flattened_state

    return padded_state # Return the padded state vector

def select_action(state, epsilon, policy_net, action_space):
    """Selects an action using epsilon-greedy policy."""
    if random.random() > epsilon:
        with torch.no_grad():
            q_values = policy_net(torch.tensor(state, dtype=torch.float32).unsqueeze(0).to(device)) # unsqueeze for batch dimension
            return torch.argmax(q_values).item()
    else:
        return random.choice(action_space)


def optimize_model(memory, optimizer, policy_net, target_net, batch_size, gamma):
    """Does not print sampled state shapes."""
    if len(memory) < batch_size:
        return  # Not enough samples in memory

    transitions = memory.sample(batch_size)
    batch = tuple(zip(*transitions))

    # Convert states and next_states to tensors individually and then stack
    state_batch = torch.stack([torch.tensor(s, dtype=torch.float32) for s in batch[0]]).to(device)
    action_batch = torch.tensor(batch[1], dtype=torch.int64).to(device)
    reward_batch = torch.tensor(batch[2], dtype=torch.float32).to(device)
    next_state_batch = torch.stack([torch.tensor(s, dtype=torch.float32) for s in batch[3]]).to(device)
    done_batch = torch.tensor(batch[4], dtype=torch.float32).to(device)


    # Compute Q(s_t, a)
    q_values = policy_net(state_batch).gather(1, action_batch.unsqueeze(1))

    # Compute V(s_{t+1}) for all next states. Expected values of actions for non_final_next_states are computed based
    # on the "older" target_net; selecting their best reward with torch.max(1)[0].
    next_state_values = target_net(next_state_batch).max(1)[0]
    expected_q_values = reward_batch + (gamma * next_state_values * (1 - done_batch))

    # Compute Huber loss
    loss = nn.functional.smooth_l1_loss(q_values.squeeze(1), expected_q_values)

    # Optimize the model
    optimizer.zero_grad()
    loss.backward()
    for param in policy_net.parameters():
        param.grad.data.clamp_(-1, 1)  # Gradient clipping
    optimizer.step() # Correct indentation


def calculate_reward(current_price, previous_price, executed_action, trade_stats, current_position_type, original_current_price=None, original_previous_price=None, state=None):
    """Calculates the reward based on the executed action, price movement, and unrealized PnL shaping.

    Args:
        current_price: The current normalized price (less relevant now)
        previous_price: The previous normalized price (less relevant now)
        executed_action: The action that was executed (0: Buy, 1: Close Long, 2: Sell, 3: Close Short)
        trade_stats: Dictionary containing trade statistics
        current_position_type: The type of position held ('long', 'short', 'none') *before* the action.
        original_current_price: The current original (non-normalized) price
        original_previous_price: The previous original (non-normalized) price
        state: The current state vector containing technical indicators.

    Returns:
        float: The calculated reward
    """
    reward = 0.0  # Initialize reward at the beginning
    unrealized_pnl_reward = 0.0

    # Reward structure: Realized PnL at close + Unrealized PnL shaping + Penalties
    # Add entry rewards based on moving average trends
    if state is not None and executed_action in [0, 2]: # Check if state is provided
        # Get SMA values from state (SMA_5 at index 5, SMA_20 at index 6)
        # Ensure state has enough elements before accessing indices
        # It's better to pass the actual SMA values or use a more robust way to access them.
        # For now, I'll remove this part as the features list is dynamic.
        pass


    # --- Calculate Unrealized PnL Reward Shaping (if position was open before action) ---
    if original_current_price is not None and original_previous_price is not None:
        price_change = original_current_price - original_previous_price
        if current_position_type == 'long':
            # Reward proportional to price increase, penalty for decrease
            unrealized_pnl_reward = (price_change / original_previous_price) * UNREALIZED_PNL_REWARD_SCALE 
        elif current_position_type == 'short':
            # Reward proportional to price decrease, penalty for increase
            unrealized_pnl_reward = (-price_change / original_previous_price) * UNREALIZED_PNL_REWARD_SCALE
    
    reward += unrealized_pnl_reward # Add shaping reward

    # --- Calculate Rewards/Penalties based on Executed Action ---
    if executed_action == 0:  # Buy (Open Long)
        # No specific reward/penalty for opening, rely on shaping + closing reward
        pass 
            
    elif executed_action == 1:  # Close Long
        # Reward based *primarily* on realized profit/loss of the closed long position
        if trade_stats['last_trade_price'] is not None and trade_stats['last_trade_type'] == 'buy':
            # Use original prices for PnL calculation
            if original_current_price is not None and trade_stats['last_original_trade_price'] is not None:
                entry_price = trade_stats['last_original_trade_price']
                # Calculate percentage return
                pct_return = (original_current_price - entry_price) / entry_price
                # Scale the percentage return to get a reasonable reward value
                # Example scaling: 1% return = 0.1 reward, 10% return = 1.0 reward
                reward = pct_return * 10.0 
            else:
                # Fallback if original prices aren't available (should not happen ideally)
                reward = -0.01 # Small penalty if PnL cannot be calculated
        else:
            reward = -0.01  # Small penalty if trying to close long without an open long position
            
    elif executed_action == 2:  # Sell (Open Short)
        # No specific reward/penalty for opening, rely on shaping + closing reward
        pass
            
    elif executed_action == 3:  # Close Short
        # Reward based *primarily* on realized profit/loss of the closed short position
        if trade_stats['last_trade_price'] is not None and trade_stats['last_trade_type'] == 'sell':
            # Use original prices for PnL calculation
            if original_current_price is not None and trade_stats['last_original_trade_price'] is not None:
                entry_price = trade_stats['last_original_trade_price']
                # Calculate percentage return (inverted for short)
                pct_return = (entry_price - original_current_price) / entry_price
                # Scale the percentage return
                reward = pct_return * 10.0
            else:
                # Fallback if original prices aren't available
                reward = -0.01 # Small penalty if PnL cannot be calculated
        else:
            reward = -0.01  # Small penalty if trying to close short without an open short position
        
    # Overwrite shaping reward if a closing action provides a realized PnL reward
    # This prioritizes the final outcome reward over the step-by-step shaping
    if executed_action in [1, 3] and reward != -0.01: # If a valid close occurred
         pass # Keep the calculated PnL reward from above
    elif executed_action == -1:  # No trade executed (invalid action based on filtering)
        reward = -0.01  # Small penalty for invalid actions, overwrites shaping

    # If no closing action or invalid action, the reward is primarily the shaping reward (or 0 if no position)
    
    return reward


def trade(action, current_price_normalized, original_current_price, portfolio, btc_held, initial_capital, current_position_type, trade_stats=None):
    """Executes a trade based on the action and current position."""
    action_taken = "no_trade"  # Default action string for no trade executed
    updated_position_type = current_position_type  # Initialize updated position type

    # Use original_current_price for calculations involving actual money/assets
    current_price = original_current_price

    # Calculate current networth before executing the trade
    current_networth = calculate_portfolio_value(portfolio, btc_held, current_price, trade_stats)
    
    # Use the global POSITION_SIZE_PERCENT defined at the top of the file
    # global POSITION_SIZE_PERCENT is already set to 0.05 (5% of networth)

    # print(f"Trade function input: action={action}, current_position_type={current_position_type}, original_price={current_price})") # Debug print

    # Action mapping: 0: Buy (Open Long), 1: Close Long, 2: Sell (Open Short), 3: Close Short

    if action == -1:
        # Invalid action, no trade executed
        pass  # action_taken is already "no_trade", position remains unchanged
    elif current_position_type == 'none':
        if action == 0:  # Buy (Open Long)
            action_taken = "buy"
            if portfolio['USD'] > 0 and current_price > 0:  # Ensure price is positive
                # Calculate amount to buy based on 3% of networth
                position_value = current_networth * POSITION_SIZE_PERCENT
                amount_to_buy = position_value / current_price
                
                # Ensure we don't try to buy more than we can afford
                max_affordable = portfolio['USD'] / (current_price * 1.001)
                amount_to_buy = min(amount_to_buy, max_affordable)
                
                btc_held += amount_to_buy
                portfolio['USD'] -= amount_to_buy * current_price * 1.001 # Add commission
                updated_position_type = 'long'  # Update position type
            else:
                action_taken = "invalid_buy_zero_price_or_usd"  # Cannot buy if price is zero/negative or no USD
        elif action == 2:  # Sell (Open Short)
            action_taken = "sell"  # Log as 'sell' for opening short
            # Simplified: In a real scenario, this would involve borrowing and selling.
            # For this adaptation, we'll just track the position type and potential PNL.
            # We'll use a negative btc_held to represent a short position quantity.
            if portfolio['USD'] > 0 and current_price > 0:  # Ensure we have capital and positive price
                # Calculate position size based on 3% of networth
                position_value = current_networth * POSITION_SIZE_PERCENT
                short_size_btc = position_value / current_price
                
                # Only deduct margin requirement (10% of position value) plus commission
                margin_required = short_size_btc * current_price * 0.1  # 10% margin
                commission = short_size_btc * current_price * 0.001  # 0.1% commission
                
                # Ensure we don't try to short more than we can afford
                if portfolio['USD'] < (margin_required + commission):
                    # Adjust short size to what we can afford
                    max_affordable_margin = portfolio['USD'] * 0.9  # Leave 10% for commission
                    short_size_btc = max_affordable_margin / (current_price * 0.1)
                    margin_required = short_size_btc * current_price * 0.1
                    commission = short_size_btc * current_price * 0.001
                
                if portfolio['USD'] >= (margin_required + commission):
                    btc_held = -short_size_btc  # Represent short position with negative quantity
                    portfolio['USD'] -= (margin_required + commission)  # Only deduct margin + commission
                    updated_position_type = 'short'  # Update position type
                else:
                    action_taken = "invalid_sell_insufficient_margin"
            else:
                action_taken = "invalid_sell_zero_price_or_usd"  # Cannot short if price is zero/negative or no USD
        else:
            # Invalid action for 'none' position (should be caught by filtering)
            action_taken = "invalid_action_none"

    elif current_position_type == 'long':
        if action == 1:  # Close Long
            action_taken = "close_long"  # Log as 'close_long'
            # print(f"Close Long attempt: btc_held={btc_held})") # Debug print
            if btc_held > 0 and current_price > 0:
                portfolio['USD'] += btc_held * current_price * 0.999  # Sell all BTC with 0.1% commission (reduced from 1%)
                btc_held = 0
                updated_position_type = 'none'  # Update position type
                # print(f"Close Long successful: updated_position_type={updated_position_type})") # Debug print
            else:
                # Should not happen with correct filtering, but as a fallback
                action_taken = "invalid_action_long_no_btc"
                # print(f"Close Long failed (no btc): updated_position_type={updated_position_type})") # Debug print
        else:
            # Invalid action for 'long' position (should be caught by filtering)
            action_taken = "invalid_action_long"

    elif current_position_type == 'short':
        if action == 3:  # Close Short
            action_taken = "close_short"  # Log as 'close_short'
            # print(f"Close Short attempt: btc_held={btc_held})") # Debug print
            if btc_held < 0 and current_price > 0:  # Check if short position exists and price is valid
                # Calculate position details
                short_size = abs(btc_held)
                position_value = short_size * current_price
                margin_held = position_value * 0.1  # 10% margin that was locked
                commission = position_value * 0.001  # 0.1% commission for closing
                
                # Calculate and apply PnL for short position
                if trade_stats is not None and 'last_original_trade_price' in trade_stats and trade_stats['last_original_trade_price'] is not None:
                    # For shorts: profit = entry_size * (entry_price - exit_price)
                    entry_price = trade_stats['last_original_trade_price']
                    pnl = short_size * (entry_price - current_price)
                    
                    # Return the margin that was locked and apply PnL
                    portfolio['USD'] += margin_held + pnl - commission
                else:
                    # Fallback if we don't have the entry price (shouldn't happen)
                    portfolio['USD'] += margin_held - commission
                
                btc_held = 0
                updated_position_type = 'none'
        else:
            # Invalid action for 'short' position (should be caught by filtering)
            action_taken = "invalid_action_short"

    #print(f"Trade function returning: action_taken={action_taken}, updated_position_type={updated_position_type}, btc_held={btc_held})") # Debug print
    return portfolio, btc_held, action_taken, updated_position_type


# 4. Initial Capital and Evaluation

def calculate_portfolio_value(portfolio, btc_held, current_price, trade_stats=None):
    """Calculates the total portfolio value."""
    if btc_held >= 0:  # Long or no position
        return portfolio['USD'] + btc_held * current_price
    else:  # Short position
        # For shorts: USD balance + margin held + unrealized PnL
        short_size = abs(btc_held)
        position_value = short_size * current_price
        margin_held = position_value * 0.1  # 10% margin
        
        # Calculate unrealized PnL if we have the entry price
        if trade_stats is not None and 'last_original_trade_price' in trade_stats and trade_stats['last_original_trade_price'] is not None and trade_stats['last_trade_type'] == 'sell':
            entry_price = trade_stats['last_original_trade_price']
            unrealized_pnl = short_size * (entry_price - current_price)
            return portfolio['USD'] + margin_held + unrealized_pnl
        else:
            # If we don't have the entry price, just return USD + margin held
            # This is not accurate but better than adding the position value
            return portfolio['USD'] + margin_held

# --- Logging Functions ---
episode_data = []
episode_counter = 0
current_episode_file = None

def _log_step(data_row, action, reward, portfolio, btc_held, networth, done, action_taken, trade_stats, current_position_type_for_log, close_reason=None):
    """Logs details of the current trading step."""
    global episode_data

    # Use the action_taken string from the trade function for the 'action' column in the log
    action_for_log = action_taken

    # Determine position type for logging
    position_type = current_position_type_for_log # Use the position type returned by the trade function

    # --- Add ORIGINAL Indicator Values to Log Entry ---
    # List of ORIGINAL indicators to log
    indicators_to_log = [
        'open_interest',
        'MACD_12_26_9', 'MACDh_12_26_9', 'MACDs_12_26_9',
        'RSI_14',
        'ATRr_14',
        'STOCHRSIk_9_9_3_3', 'STOCHRSId_9_9_3_3',
        'STOCHRSIk_14_14_3_3', 'STOCHRSId_14_14_3_3',
        'STOCHRSIk_40_40_4_4', 'STOCHRSId_40_40_4_4',
        'STOCHRSIk_60_60_10_10', 'STOCHRSId_60_60_10_10',
        'EMA_21', 'EMA_50', 'EMA_200'
    ]
    # Fetch original values, rename keys for consistency in CSV (remove _orig suffix)
    indicator_values = {}
    for orig_col in indicators_to_log:
        if orig_col in data_row: # Check if original column exists in the data row
             # Use the base name (without _orig) as the key in the log entry
            base_col = orig_col.replace('_orig', '') 
            indicator_values[base_col] = data_row.get(orig_col, None) 
        else:
             # If original column somehow missing, log None with base name
             base_col = orig_col.replace('_orig', '')
             indicator_values[base_col] = None
    # --- End Add Original Indicator Values ---


    log_entry = {
        'datetime': data_row.name, # Use the datetime index as datetime
        'timestamp': int(data_row.name.timestamp()), # Convert datetime index to timestamp
        'price': data_row['original_close'],
        'action': action_for_log,
        'position_type': position_type,
        'quantity': btc_held, # Log BTC held as quantity
        'balance': portfolio['USD'],
        'networth': networth,
        'reward': reward,
        'reward_networth': 0.0, # Not directly calculated in this DQN
        'reward_action': reward, # Using the calculated reward as action reward for simplicity
        'reward_market': 0.0, # Not directly calculated in this DQN
        'done': done,
        'trade_count': trade_stats['trade_count'],
        'profitable_trades': trade_stats['profitable_trades'],
        'win_rate': trade_stats['win_rate'],
        'total_profit': trade_stats['total_profit'],
        'max_drawdown': trade_stats['max_drawdown'], # This needs to be tracked
        'close_reason': close_reason, # Added close reason
        **indicator_values # Merge indicator values into the log entry
    }
    episode_data.append(log_entry)

def _save_episode():
    """Saves the collected episode data to a CSV file."""
    global episode_data, episode_counter, current_episode_file

    if not episode_data:
        return

    df = pd.DataFrame(episode_data)

    # Create new file at the start of each episode
    if current_episode_file is None:
         current_episode_file = f"episode_{episode_counter:04d}.csv"
         # Clear the file if it exists from a previous run
         # REMOVED: if os.path.exists(current_episode_file):
         # REMOVED:    os.remove(current_episode_file)


    # Append to current episode file
    df.to_csv(current_episode_file, mode='a',
             header=not os.path.exists(current_episode_file),
             index=False)
    episode_data = [] # Clear data after saving
    current_episode_file = None # Reset for the next episode

# --- End Logging Functions ---


# 5. Main Trading Loop

if __name__ == "__main__":

    # Delete existing log file to start fresh
    if os.path.exists(LOG_FILE):
        try:
            os.remove(LOG_FILE)
        except OSError as e:
            print(f"Error deleting log file {LOG_FILE}: {e}") # Print to console as log_message isn't set up yet

    print("===== Starting Gemini RL Agent =====")

    redis_conn = get_redis_connection()
    if not redis_conn:
        log_message("CRITICAL: No Redis connection. Exiting.")
        exit()

    log_message("--- Initial Data Load from Redis ---")
    # Fetch all historical data (klines and OI)
    raw_data_dfs = fetch_all_historical_data_from_redis(redis_conn, REDIS_OHLCV_KEY_PREFIX, MIN_RECORDS_FOR_TRAINING) # This returns a dict
    df_raw_initial = raw_data_dfs.get('klines') # Extract the klines DataFrame from the dict

    if df_raw_initial is None or df_raw_initial.empty:
        log_message("CRITICAL: No initial historical data fetched from Redis. Exiting.")
        exit()

    # Process the data to add indicators and normalize
    data = process_dataframe_with_atr(raw_data_dfs, "Initial Redis Fetch")

    if data.empty:
        log_message("CRITICAL: Initial data processing resulted in an empty DataFrame. Exiting.")
        exit()

    log_message(f"Successfully loaded and processed {len(data)} data points.")

    # Split data into training and testing sets
    train_ratio = 0.8
    train_size = int(len(data) * train_ratio)
    train_data = data[:train_size]
    test_data = data[train_size:]

    # Delete previous episode files
    print("Deleting previous episode files...")
    for file_name in os.listdir('.'):
        if file_name.startswith('episode_') and file_name.endswith('.csv'):
            try:
                os.remove(file_name)
                print(f"Deleted {file_name}")
            except OSError as e:
                print(f"Error deleting file {file_name}: {e}")


    # Define state and action spaces
    # Calculate the expected state size based on window size and number of features
    features = [
        'open', 'high', 'low', 'close', 'volume', 'open_interest',
        'MACD_12_26_9', 'MACDh_12_26_9', 'MACDs_12_26_9',
        'RSI_14',
        'ATRr_14',
        'STOCHRSIk_9_9_3_3', 'STOCHRSId_9_9_3_3',
        'STOCHRSIk_14_14_3_3', 'STOCHRSId_14_14_3_3',
        'STOCHRSIk_40_40_4_4', 'STOCHRSId_40_40_4_4',
        'STOCHRSIk_60_60_10_10', 'STOCHRSId_60_60_10_10'
    ]
    num_features = len(features)
    window_size = 10 # Default window size in get_state
    state_size = window_size * num_features
    print(f"State size: {state_size} (window_size={window_size}, num_features={num_features})")

    # Define action space: 0: Buy (Open Long), 1: Close Long, 2: Sell (Open Short), 3: Close Short
    action_space = [0, 1, 2, 3]
    action_size = len(action_space)


    # Initialize DQN agent
    policy_net = DQN(state_size, action_size).to(device)
    target_net = DQN(state_size, action_size).to(device)
    target_net.load_state_dict(policy_net.state_dict())
    target_net.eval() # Set target net to evaluation mode.

    optimizer = optim.Adam(policy_net.parameters(), lr=LEARNING_RATE)
    memory = ReplayMemory(MEMORY_CAPACITY)


    # Initial capital
    initial_capital = 10000


    # Function to evaluate the model on test data
    def evaluate_model(model, test_data, initial_capital=10000, episode_num=0):
        """Evaluates the model on test data.
        
        Args:
            model: The trained model to evaluate
            test_data: The test dataset
            initial_capital: Initial capital for trading
            episode_num: Episode number for logging
            
        Returns:
            dict: Dictionary containing evaluation metrics
        """
        print("\nEvaluating model on test data...")
        
        # Initialize portfolio and position
        portfolio = {'USD': initial_capital}
        btc_held = 0
        current_position_type = 'none'
        
        # Initialize trade statistics
        trade_stats = {
            'trade_count': 0,
            'profitable_trades': 0,
            'total_profit': 0.0,
            'max_drawdown': 0.0,
            'peak_balance': initial_capital,
            'last_trade_price': None,
            'last_original_trade_price': None,
            'last_trade_type': None
        }
        
        # Initialize evaluation metrics
        eval_metrics = {
            'initial_capital': initial_capital,
            'final_capital': 0,
            'total_return_pct': 0,
            'trade_count': 0,
            'profitable_trades': 0,
            'win_rate': 0,
            'max_drawdown': 0,
            'max_drawdown_pct': 0
        }
        
        # Set model to evaluation mode
        model.eval()
        
        # Create a progress bar for evaluation
        # Iterate up to len(test_data) - 1 so that t+1 is a valid iloc index
        pbar = tqdm(range(len(test_data) - 1), desc="Evaluating")

        # Initialize episode data for logging
        global episode_data, episode_counter, current_episode_file
        episode_data = []
        episode_counter = episode_num  # Use provided episode number
        current_episode_file = None
        
        for t in pbar:
            with torch.no_grad():  # No gradient computation needed for evaluation
                state = get_state(test_data, t)
                
                # Get action with epsilon=0 (no exploration, only exploitation)
                q_values = model(torch.tensor(state, dtype=torch.float32).unsqueeze(0).to(device))
                action = torch.argmax(q_values).item()
                
                # Get current price using iloc for integer-location based indexing
                current_price_normalized = test_data['close'].iloc[t+1]
                original_current_price = test_data['original_close'].iloc[t+1]
                
                # Check for stop-loss or take-profit conditions
                force_close = False
                force_close_reason = ""
                reason_for_close = None # Initialize reason for close

                if current_position_type == 'long' and trade_stats['last_original_trade_price'] is not None:
                    # Calculate percentage change for long position
                    pct_change = (original_current_price - trade_stats['last_original_trade_price']) / trade_stats['last_original_trade_price']
                    
                    # Check stop-loss (negative change beyond threshold)
                    if pct_change < -STOP_LOSS_PERCENT:
                        force_close = True
                        force_close_reason = "stop_loss_long"
                        reason_for_close = force_close_reason # Assign reason
                        action_to_execute = 1  # Force Close Long

                    # Check take-profit (positive change beyond threshold)
                    elif pct_change > TAKE_PROFIT_PERCENT:
                        force_close = True
                        force_close_reason = "take_profit_long"
                        reason_for_close = force_close_reason # Assign reason
                        action_to_execute = 1  # Force Close Long

                elif current_position_type == 'short' and trade_stats['last_original_trade_price'] is not None:
                    # Calculate percentage change for short position (inverted)
                    pct_change = (trade_stats['last_original_trade_price'] - original_current_price) / trade_stats['last_original_trade_price']
                    
                    # Check stop-loss (negative change beyond threshold)
                    if pct_change < -STOP_LOSS_PERCENT:
                        force_close = True
                        force_close_reason = "stop_loss_short"
                        reason_for_close = force_close_reason # Assign reason
                        action_to_execute = 3  # Force Close Short

                    # Check take-profit (positive change beyond threshold)
                    elif pct_change > TAKE_PROFIT_PERCENT:
                        force_close = True
                        force_close_reason = "take_profit_short"
                        reason_for_close = force_close_reason # Assign reason
                        action_to_execute = 3  # Force Close Short

                # If not forcing a close due to stop-loss or take-profit, use normal action filtering
                if not force_close:
                    # Action filtering based on position
                    valid_actions = []
                    if current_position_type == 'none':
                        valid_actions = [0, 2]  # Buy or Sell
                    elif current_position_type == 'long':
                        valid_actions = [1]  # Close Long
                    elif current_position_type == 'short':
                        valid_actions = [3]  # Close Short

                    action_to_execute = action if action in valid_actions else -1
                    # Assign reason if model decides to close
                    if action_to_execute in [1, 3]:
                        reason_for_close = 'model_decision'

                # Store position type *before* calling trade
                position_type_before_eval_trade = current_position_type 
                
                # Execute trade (current_position_type gets updated here)
                portfolio, btc_held, action_taken_str, current_position_type = trade(
                    action_to_execute, current_price_normalized, original_current_price,
                    portfolio, btc_held, initial_capital, position_type_before_eval_trade, trade_stats # Pass the correct 'before' state
                )

                # Calculate reward using iloc - Pass the *correct* position type before the trade
                reward = calculate_reward(
                    current_price_normalized, test_data['close'].iloc[t],
                    action_to_execute, trade_stats, position_type_before_eval_trade, # Use the saved 'before' state
                    original_current_price, test_data['original_close'].iloc[t] if t < len(test_data) else None,
                    state # Pass the state variable
                )
                
                # Update trade statistics
                if action_taken_str in ["buy", "sell"]:
                    trade_stats['trade_count'] += 1
                    trade_stats['last_trade_price'] = current_price_normalized
                    trade_stats['last_original_trade_price'] = original_current_price
                    trade_stats['last_trade_type'] = action_taken_str
                    trade_stats['last_trade_timestamp'] = test_data.index[t+1] # Use datetime index
                    trade_stats['last_trade_index'] = len(episode_data)
                elif action_taken_str in ["close_long", "close_short"]:
                    if trade_stats['last_original_trade_price'] is not None:
                        # Calculate PnL
                        original_pnl = (original_current_price - trade_stats['last_original_trade_price']) if trade_stats['last_trade_type'] == 'buy' else (trade_stats['last_original_trade_price'] - original_current_price)
                        trade_stats['total_profit'] += original_pnl
                        if original_pnl > 0:
                            trade_stats['profitable_trades'] += 1
                        
                    trade_stats['last_trade_price'] = None
                    trade_stats['last_original_trade_price'] = None
                    trade_stats['last_trade_type'] = None
                    trade_stats['last_trade_timestamp'] = None
                    if 'last_trade_index' in trade_stats:
                        del trade_stats['last_trade_index']
                
                # Calculate current networth
                current_networth = calculate_portfolio_value(portfolio, btc_held, original_current_price, trade_stats)
                trade_stats['peak_balance'] = max(trade_stats['peak_balance'], current_networth)
                drawdown = trade_stats['peak_balance'] - current_networth
                trade_stats['max_drawdown'] = max(trade_stats['max_drawdown'], drawdown)
                trade_stats['win_rate'] = trade_stats['profitable_trades'] / max(1, trade_stats['trade_count'])
                
                # Log step - Pass the position type *after* the trade for logging consistency with visualization
                _log_step(
                    test_data.iloc[t+1], action_to_execute, reward,
                    portfolio, btc_held, current_networth, False,
                    action_taken_str, trade_stats, current_position_type, # Use the updated 'after' state
                    close_reason=reason_for_close # Pass reason
                )

                # Update progress bar
                pbar.set_postfix_str(f"Capital: ${current_networth:.2f} | Trades: {trade_stats['trade_count']} | Win Rate: {trade_stats['win_rate']:.2f}")
        
        # Save episode data
        _save_episode()
        
        # Calculate final evaluation metrics
        final_networth = calculate_portfolio_value(portfolio, btc_held, test_data['original_close'].iloc[-1], trade_stats)
        eval_metrics['final_capital'] = final_networth
        eval_metrics['total_return_pct'] = (final_networth / initial_capital - 1) * 100
        eval_metrics['trade_count'] = trade_stats['trade_count']
        eval_metrics['profitable_trades'] = trade_stats['profitable_trades']
        eval_metrics['win_rate'] = trade_stats['win_rate'] * 100
        eval_metrics['max_drawdown'] = trade_stats['max_drawdown']
        eval_metrics['max_drawdown_pct'] = (trade_stats['max_drawdown'] / trade_stats['peak_balance']) * 100
        
        # Print evaluation results with clear formatting
        print("\n" + "="*50)
        print("TEST DATA EVALUATION RESULTS")
        print("="*50)
        print(f"Initial Capital: ${initial_capital:.2f}")
        print(f"Final Capital: ${final_networth:.2f}")
        print(f"Total Return: {eval_metrics['total_return_pct']:.2f}%")
        print(f"Number of Trades: {eval_metrics['trade_count']}")
        print(f"Profitable Trades: {eval_metrics['profitable_trades']}")
        print(f"Win Rate: {eval_metrics['win_rate']:.2f}%")
        print(f"Max Drawdown: ${eval_metrics['max_drawdown']:.2f} ({eval_metrics['max_drawdown_pct']:.2f}%)")
        print("="*50)
        
        return eval_metrics

    # Training loop
    epsilon = EPSILON_START
    total_steps = 0


    print("Starting training...")
    # Initialize tqdm progress bar for episodes
    pbar_episode = tqdm(range(NUM_EPISODES), desc="Training Gemini RL")
    for episode in pbar_episode:
        episode_counter += 1  # Increment episode counter
        portfolio = {'USD': initial_capital}  # Reset portfolio for each episode
        btc_held = 0
        current_position_type = 'none'  # Initialize position type for the episode
        current_episode_file = None  # Reset file tracking for new episode

        # Initialize trade statistics for the episode
        trade_stats = {
            'trade_count': 0,
            'profitable_trades': 0,
            'total_profit': 0.0,
            'max_drawdown': 0.0,
            'peak_balance': initial_capital,
            'last_trade_price': None, # Track normalized price at last trade for PNL
            'last_original_trade_price': None, # Track original price at last trade for PNL
            'last_trade_type': None # Track type of last trade
        }

        for t in range(len(train_data) - 1): # Iterate up to the second-to-last element.

            state = get_state(train_data, t)
            action = select_action(state, epsilon, policy_net, action_space)
            next_state = get_state(train_data, t + 1)

            # Get current normalized price for agent state and original price for trading logic
            current_price_normalized = train_data['close'].iloc[t+1]
            original_current_price = train_data['original_close'].iloc[t+1]

            # Check for stop-loss or take-profit conditions
            force_close = False
            force_close_reason = ""
            reason_for_close = None # Initialize reason for close

            if current_position_type == 'long' and trade_stats['last_original_trade_price'] is not None:
                # Calculate percentage change for long position
                pct_change = (original_current_price - trade_stats['last_original_trade_price']) / trade_stats['last_original_trade_price']
                
                # Check stop-loss (negative change beyond threshold)
                if pct_change < -STOP_LOSS_PERCENT:
                    force_close = True
                    force_close_reason = "stop_loss_long"
                    reason_for_close = force_close_reason # Assign reason
                    action_to_execute = 1  # Force Close Long

                # Check take-profit (positive change beyond threshold)
                elif pct_change > TAKE_PROFIT_PERCENT:
                    force_close = True
                    force_close_reason = "take_profit_long"
                    reason_for_close = force_close_reason # Assign reason
                    action_to_execute = 1  # Force Close Long

            elif current_position_type == 'short' and trade_stats['last_original_trade_price'] is not None:
                # Calculate percentage change for short position (inverted)
                pct_change = (trade_stats['last_original_trade_price'] - original_current_price) / trade_stats['last_original_trade_price']
                
                # Check stop-loss (negative change beyond threshold)
                if pct_change < -STOP_LOSS_PERCENT:
                    force_close = True
                    force_close_reason = "stop_loss_short"
                    reason_for_close = force_close_reason # Assign reason
                    action_to_execute = 3  # Force Close Short

                # Check take-profit (positive change beyond threshold)
                elif pct_change > TAKE_PROFIT_PERCENT:
                    force_close = True
                    force_close_reason = "take_profit_short"
                    reason_for_close = force_close_reason # Assign reason
                    action_to_execute = 3  # Force Close Short

            # If not forcing a close due to stop-loss or take-profit, use normal action filtering
            if not force_close:
                # --- Action Filtering based on Position ---
                valid_actions = []
                if current_position_type == 'none':
                    valid_actions = [0, 2] # 0: Buy (Open Long), 2: Sell (Open Short)
                elif current_position_type == 'long':
                    valid_actions = [1] # 1: Close Long
                elif current_position_type == 'short':
                    valid_actions = [3] # 3: Close Short
    
                # If the selected action is not valid, choose a default valid action (e.g., do nothing or a specific valid action)
                # For this strategy, if an invalid action is chosen, we will force a 'hold' like behavior by not executing a trade.
                # The agent should learn to only pick valid actions.
                action_to_execute = action if action in valid_actions else -1 # Use -1 to indicate no trade should be executed
                # Assign reason if model decides to close
                if action_to_execute in [1, 3]:
                    reason_for_close = 'model_decision'

            # Store position type *before* calling trade
            position_type_before_trade = current_position_type

            # Execute trade and get the action taken string and updated position type
            # 'current_position_type' gets updated here by the trade function
            portfolio, btc_held, action_taken_str, current_position_type = trade(
                action_to_execute, current_price_normalized, original_current_price, 
                portfolio, btc_held, initial_capital, position_type_before_trade, trade_stats # Pass the correct 'before' state
            )

            # Calculate reward based on the executed action and ORIGINAL prices - Pass the *correct* position type before the trade
            reward = calculate_reward(
                current_price_normalized, 
                train_data['close'].iloc[t],   
                action_to_execute, 
                trade_stats,
                position_type_before_trade, # Use the saved 'before' state
                original_current_price,
                train_data['original_close'].iloc[t] if t < len(train_data) else None,
                state  # Pass the current state
            )

            done = (t == len(train_data) - 2)  # Last step in the episode

            # Update trade statistics based on action taken
            if action_taken_str in ["buy", "sell"]:
                trade_stats['trade_count'] += 1
                trade_stats['last_trade_price'] = current_price_normalized # Store normalized price
                trade_stats['last_original_trade_price'] = original_current_price # Store original price
                trade_stats['last_trade_type'] = action_taken_str
                # Store the timestamp of the opening trade for later reference
                trade_stats['last_trade_timestamp'] = train_data.index[t+1] # Use datetime index
                # Store the index in episode_data for the opening trade
                trade_stats['last_trade_index'] = len(episode_data)
            elif action_taken_str in ["close_long", "close_short"]: # Assuming these actions might be added later or derived
                 # Calculate PNL for the closed trade (simplified) using ORIGINAL price
                 if trade_stats['last_original_trade_price'] is not None:
                     # Use original prices for PNL calculation
                     original_pnl = (original_current_price - trade_stats['last_original_trade_price']) if trade_stats['last_trade_type'] == 'buy' else (trade_stats['last_original_trade_price'] - original_current_price)
                     trade_stats['total_profit'] += original_pnl
                     if original_pnl > 0:
                         trade_stats['profitable_trades'] += 1
                     
                     # Calculate reward based on PnL
                     trade_reward = original_pnl / 100.0  # Scale down the reward
                     
                     # Update the reward for this closing action
                     reward = trade_reward # Assign the calculated PnL-based reward
                     
                 trade_stats['last_trade_price'] = None
                 trade_stats['last_original_trade_price'] = None
                 trade_stats['last_trade_type'] = None
                 trade_stats['last_trade_timestamp'] = None
                 if 'last_trade_index' in trade_stats:
                     del trade_stats['last_trade_index']

            # Calculate current net worth using ORIGINAL price and update peak balance and drawdown
            current_networth = calculate_portfolio_value(portfolio, btc_held, original_current_price)
            trade_stats['peak_balance'] = max(trade_stats['peak_balance'], current_networth)
            drawdown = trade_stats['peak_balance'] - current_networth
            trade_stats['max_drawdown'] = max(trade_stats['max_drawdown'], drawdown)
            trade_stats['win_rate'] = trade_stats['profitable_trades'] / max(1, trade_stats['trade_count'])

            # Log the step details using the position type *after* the trade for logging consistency with visualization
            _log_step(train_data.iloc[t+1], action_to_execute, reward, portfolio, btc_held, current_networth, done, action_taken_str, trade_stats, current_position_type, close_reason=reason_for_close) # Use the updated 'after' state, pass reason

            # Save episode data when a trade is completed (close_long or close_short)
            if action_taken_str in ["close_long", "close_short"]:
                _save_episode()  # Save the episode data when a trade completes

            # Check if balance has fallen below 1/10 of initial capital
            if portfolio['USD'] < initial_capital / 10:
                print(f"Balance fell below 1/10 of initial capital. Ending episode {episode + 1}")
                done = True  # Mark episode as done
                _save_episode()  # Save the episode
                break  # End the episode
            # Ensure state and next_state are the padded vectors before pushing to memory
            padded_state = get_state(train_data, t) # Re-call get_state to be explicit
            padded_next_state = get_state(train_data, t + 1) # Re-call get_state to be explicit

            memory.push(padded_state, action, reward, padded_next_state, done)

            optimize_model(memory, optimizer, policy_net, target_net, BATCH_SIZE, GAMMA)

            epsilon = max(EPSILON_END, epsilon * EPSILON_DECAY)
            total_steps += 1

            if total_steps % UPDATE_FREQUENCY == 0:
                target_net.load_state_dict(policy_net.state_dict())  # Update target network

            # Log learning progress periodically (without saving to CSV)
            if total_steps % 100 == 0: # Log every 100 steps
                 # Log learning progress
                 current_portfolio_value = calculate_portfolio_value(portfolio, btc_held, original_current_price) # Use original price
                 episode_progress = f"Episode: {episode + 1}/{NUM_EPISODES}"
                 step_progress = f"Step: {t+1}/{len(train_data)-1}"
                 total_steps_str = f"Total Steps: {total_steps}"
                 epsilon_str = f"Epsilon: {epsilon:.4f}"
                 portfolio_value_str = f"Portfolio Value: {current_portfolio_value:.2f}"

                 pbar_episode.set_postfix_str(f"{episode_progress} | {step_progress} | {total_steps_str} | {epsilon_str} | {portfolio_value_str}")
        
        # Save episode data at the end of each episode
        _save_episode()
        
        # Evaluate the model on test data every 25 episodes
        if (episode + 1) % 25 == 0 or episode == NUM_EPISODES - 1:
            print(f"\nEvaluating model after episode {episode + 1}...")
            eval_metrics = evaluate_model(policy_net, test_data, initial_capital, episode_counter + 1)
            
            # Save evaluation metrics to a file
            eval_file = f"evaluation_metrics_{episode + 1}.csv"
            pd.DataFrame([eval_metrics]).to_csv(eval_file, index=False)
            print(f"Evaluation metrics saved to {eval_file}")
            
    # Final evaluation after training is complete
    print("\nTraining complete. Running final evaluation on test data...")
    final_eval_metrics = evaluate_model(policy_net, test_data, initial_capital, episode_counter + 1)
    
    # Save final model
    torch.save({
        'model_state_dict': policy_net.state_dict(),
        'optimizer_state_dict': optimizer.state_dict(),
        'epsilon': epsilon,
        'episode': NUM_EPISODES,
        'total_steps': total_steps,
        'eval_metrics': final_eval_metrics
    }, 'gemini_RL_model.pth')
    
    print("Final model saved to gemini_RL_model.pth")
    print("\nFinal Evaluation Results:")
    for key, value in final_eval_metrics.items():
        print(f"{key}: {value}")
