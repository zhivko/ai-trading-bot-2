# pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128



import os
import time
import datetime
import shutil
import json # For serializing/deserializing data in Redis

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import redis # For Redis interaction

# Explicitly import gymnasium and its submodules
import gymnasium
from gymnasium import spaces as gymnasium_spaces

from stable_baselines3 import PPO
from stable_baselines3.common.env_util import make_vec_env, DummyVecEnv
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor

from ta import add_all_ta_features
from ta.volatility import AverageTrueRange

from pybit.unified_trading import HTTP as BybitHTTPClient # For Bybit fetching
# --- Configuration ---
INITIAL_TRAINING_TIMESTEPS = 100000
INCREMENTAL_TRAINING_TIMESTEPS = 20000
MODEL_BASE_PATH = "./trading_agent_models"
ITERATIONAL_VAL_SET_SIZE = 200  # Number of data points for each walk-forward validation set
PROMOTION_SHARPE_THRESHOLD = 0.1 # Candidate Sharpe must be this much higher
MIN_PROFIT_FOR_PROMOTION = 0.0    # Candidate profit must be above this
EVAL_LOGS_PATH = "./trading_agent_eval_logs" # Directory for detailed evaluation CSVs
TENSORBOARD_LOG_PATH = "./trading_agent_tensorboard_logs/" # Path for TensorBoard logs
CURRENT_MODEL_FILENAME_BASE = "current_best_ppo_btc_trader"
LOG_FILE = "trading_agent_log.txt"
LOOKBACK_PERIOD = 60
TRADING_SYMBOL = "BTCUSDT" # Symbol to trade
TRADING_TIMEFRAME = "5m" # Timeframe for data

# Redis Configuration
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_OHLCV_KEY_PREFIX = f"zset:kline:{TRADING_SYMBOL}:{TRADING_TIMEFRAME}" # Key for sorted set
MIN_RECORDS_FOR_TRAINING = 100000 # Desired number of records

# Bybit Configuration (used if backfilling data)
BYBIT_API_KEY_AGENT = os.getenv("BYBIT_API_KEY_AGENT", "YOUR_BYBIT_API_KEY_HERE")
BYBIT_API_SECRET_AGENT = os.getenv("BYBIT_API_SECRET_AGENT", "YOUR_BYBIT_SECRET_HERE")

# Global path for the current best model
current_model_path = os.path.join(MODEL_BASE_PATH, f"{CURRENT_MODEL_FILENAME_BASE}.zip")

# --- Helper Functions ---
def log_message(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_message = f"[{timestamp}] {message}"
    print(full_message)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(full_message + "\n")

def get_redis_connection():
    try:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=False) # decode_responses=False for raw bytes if storing JSON
        r.ping()
        log_message(f"Successfully connected to Redis ({REDIS_HOST}:{REDIS_PORT}, DB {REDIS_DB}).")
        return r
    except redis.exceptions.ConnectionError as e:
        log_message(f"CRITICAL: Could not connect to Redis: {e}")
        return None

# --- Bybit Data Fetching and Caching Utilities (for backfilling) ---
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
# --- Redis Data Interaction ---
def fetch_all_historical_data_from_redis(redis_conn, redis_key=REDIS_OHLCV_KEY_PREFIX, min_records=MIN_RECORDS_FOR_TRAINING):
    """
    Fetches all historical OHLCV data from a Redis Sorted Set.
    Assumes scores are timestamps and values are JSON strings of candle data.
    """
    log_message(f"Fetching all historical data from Redis key '{redis_key}'...")
    if not redis_conn:
        log_message("No Redis connection available for fetching data.")
        return pd.DataFrame()

    try:
        # Initial fetch attempt
        def _fetch_and_process_from_redis_internal(r_conn, r_key):
            raw_candles_with_scores_internal = r_conn.zrange(r_key, 0, -1, withscores=True)
            if not raw_candles_with_scores_internal:
                return pd.DataFrame()
            
            data_internal = []
            for raw_candle_json, score_timestamp in raw_candles_with_scores_internal:
                try:
                    candle_data = json.loads(raw_candle_json.decode('utf-8'))
                    if 'vol' in candle_data and 'volume' not in candle_data: # Ensure 'volume' is the key
                        candle_data['volume'] = candle_data.pop('vol')
                    candle_data['timestamp'] = int(score_timestamp)
                    data_internal.append(candle_data)
                except Exception as e_proc:
                    log_message(f"Warning: Error processing a candle from Redis (ts: {score_timestamp}): {e_proc}")
            
            if not data_internal: return pd.DataFrame()

            df_internal = pd.DataFrame(data_internal)
            df_internal['datetime'] = pd.to_datetime(df_internal['timestamp'], unit='s', utc=True)
            df_internal.set_index('datetime', inplace=True)
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in df_internal.columns for col in required_cols):
                log_message(f"CRITICAL: Required columns missing from Redis data for key '{r_key}'.")
                return pd.DataFrame()
            df_internal = df_internal[required_cols].astype(float).sort_index()
            return df_internal[~df_internal.index.duplicated(keep='last')]

        df_current_redis = _fetch_and_process_from_redis_internal(redis_conn, redis_key)
        log_message(f"Initial fetch from Redis for '{redis_key}': {len(df_current_redis)} records.")

        if len(df_current_redis) < min_records:
            log_message(f"Records in Redis ({len(df_current_redis)}) are less than desired ({min_records}). Attempting to backfill from Bybit...")
            
            records_needed_from_bybit = min_records - len(df_current_redis)
            timeframe_seconds = get_timeframe_seconds_agent(TRADING_TIMEFRAME)

            if not df_current_redis.empty:
                # Fetch data older than what's in Redis
                oldest_ts_in_redis = int(df_current_redis.index.min().timestamp())
                bybit_fetch_end_ts = oldest_ts_in_redis - timeframe_seconds # Fetch up to the candle *before* the oldest we have
            else:
                # Redis is empty, fetch data up to now
                bybit_fetch_end_ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
            
            # Calculate start_ts to get approximately records_needed_from_bybit
            # Add a small buffer (e.g., 10%) to account for potential gaps or shorter history on Bybit
            buffer_factor = 1.1 
            duration_seconds_needed = int(records_needed_from_bybit * timeframe_seconds * buffer_factor)
            bybit_fetch_start_ts = bybit_fetch_end_ts - duration_seconds_needed

            # Ensure start_ts is not too far in the past if Bybit has limits (e.g. 2 years for 5m)
            # For 5m, 2 years is approx 2 * 365 * 24 * 12 = 210,240 candles. 100k is well within this.
            
            if bybit_fetch_start_ts >= bybit_fetch_end_ts:
                log_message(f"Calculated Bybit fetch range is invalid (start >= end). Skipping Bybit fetch. StartTS: {bybit_fetch_start_ts}, EndTS: {bybit_fetch_end_ts}")
            else:
                fetched_bybit_klines = fetch_klines_from_bybit_agent(TRADING_SYMBOL, TRADING_TIMEFRAME, bybit_fetch_start_ts, bybit_fetch_end_ts)
                if fetched_bybit_klines:
                    cache_klines_agent(redis_conn, TRADING_SYMBOL, TRADING_TIMEFRAME, fetched_bybit_klines, redis_key)
                    # After caching, re-fetch everything from Redis to get a consolidated view
                    log_message("Re-fetching all data from Redis after Bybit backfill...")
                    df_current_redis = _fetch_and_process_from_redis_internal(redis_conn, redis_key)
                    log_message(f"Total records in Redis after backfill for '{redis_key}': {len(df_current_redis)}.")
                else:
                    log_message("No data fetched from Bybit for backfilling.")
        
        if df_current_redis.empty:
            log_message(f"No data available for '{redis_key}' even after potential backfill.")
        return df_current_redis

    except redis.exceptions.RedisError as e:
        log_message(f"Redis error during fetch_all_historical_data: {e}")
        return pd.DataFrame()
    except Exception as e:
        log_message(f"General error during fetch_all_historical_data: {e}")
        traceback.print_exc() # Print full traceback for debugging
        return pd.DataFrame()


def fetch_new_data_from_redis(redis_conn, last_known_timestamp, redis_key=REDIS_OHLCV_KEY_PREFIX):
    """
    Fetches new OHLCV data from Redis since the last_known_timestamp.
    Assumes last_known_timestamp is a Unix timestamp (integer).
    """
    log_message(f"Fetching new data from Redis key '{redis_key}' since timestamp {last_known_timestamp}...")
    if not redis_conn:
        log_message("No Redis connection available for fetching new data.")
        return pd.DataFrame()

    try:
        # Fetch records with score > last_known_timestamp.
        # The '(' indicates an exclusive lower bound for the score.
        raw_new_candles_with_scores = redis_conn.zrangebyscore(redis_key, f"({last_known_timestamp}", "+inf", withscores=True)
        
        if not raw_new_candles_with_scores:
            log_message(f"No new data found in Redis for '{redis_key}' since timestamp {last_known_timestamp}.")
            return pd.DataFrame()

        data = []
        for raw_candle_json, score_timestamp in raw_new_candles_with_scores:
            try:
                candle_data = json.loads(raw_candle_json.decode('utf-8'))
                # Rename 'vol' to 'volume' if present
                if 'vol' in candle_data:
                    candle_data['volume'] = candle_data.pop('vol')
                candle_data['timestamp'] = int(score_timestamp)
                data.append(candle_data)
            except Exception as e:
                log_message(f"Warning: Error processing a new candle (ts: {score_timestamp}): {e}")

        if not data:
            return pd.DataFrame()

        df_new = pd.DataFrame(data)
        df_new['datetime'] = pd.to_datetime(df_new['timestamp'], unit='s', utc=True)
        df_new.set_index('datetime', inplace=True)
        
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        for col in required_cols:
            if col not in df_new.columns:
                 log_message(f"CRITICAL: Column '{col}' missing from new data fetched from Redis for key '{redis_key}'.")
                 return pd.DataFrame()
        
        df_new = df_new[required_cols]
        df_new = df_new.astype(float)
        df_new.sort_index(inplace=True)
        df_new = df_new[~df_new.index.duplicated(keep='last')]
        
        log_message(f"Fetched and processed {len(df_new)} new records from Redis for '{redis_key}'.")
        return df_new
    except redis.exceptions.RedisError as e:
        log_message(f"Redis error during fetch_new_data: {e}")
        return pd.DataFrame()
    except Exception as e:
        log_message(f"General error during fetch_new_data: {e}")
        return pd.DataFrame()


def process_dataframe_with_atr(df_raw, data_source_name="DataFrame"):
    log_message(f"Processing DataFrame from: {data_source_name} (Initial shape: {df_raw.shape})")
    if df_raw.empty:
        log_message("Input DataFrame is empty. Cannot process.")
        return pd.DataFrame()
    try:
        df = df_raw.copy()
        if not isinstance(df.index, pd.DatetimeIndex):
            if 'datetime' in df.columns:
                df['datetime'] = pd.to_datetime(df['datetime'])
                df.set_index('datetime', inplace=True)
            elif 'timestamp' in df.columns:
                df['datetime'] = pd.to_datetime(df['timestamp'], unit='s', utc=True)
                df.set_index('datetime', inplace=True)
            else:
                raise ValueError("DataFrame must have DatetimeIndex or 'datetime'/'timestamp' column.")

        ohlcv_cols = ['open', 'high', 'low', 'close', 'volume']
        for col in ohlcv_cols:
            if col not in df.columns: raise ValueError(f"Required column '{col}' missing.")
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df.dropna(subset=ohlcv_cols, inplace=True)

        if df.empty:
            log_message(f"DataFrame empty after OHLCV processing from {data_source_name}.")
            return pd.DataFrame()
            
        df = add_all_ta_features(df, open="open", high="high", low="low", close="close", volume="volume", fillna=True)
        atr_indicator = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14, fillna=True)
        df['volatility_atr'] = atr_indicator.average_true_range()
        
        env_expected_features = AdvancedBTCTradingEnvWithShort.FEATURES
        missing_ta_features = [f for f in env_expected_features if f not in df.columns and f not in ohlcv_cols]
        for mf in missing_ta_features: df[mf] = 0.0 # Fill missing TA features with 0

        df.dropna(subset=env_expected_features, inplace=True)
        if df.empty:
            log_message(f"DataFrame became empty after dropna (post TA) for {data_source_name}.")
        
        log_message(f"Data processing complete for {data_source_name}. Shape: {df.shape}")
        return df
    except Exception as e:
        log_message(f"ERROR in process_dataframe_with_atr for {data_source_name}: {e}")
        raise

# --- LSTMExtractor and AdvancedBTCTradingEnvWithShort Classes (remain the same as in previous full code) ---
class LSTMExtractor(BaseFeaturesExtractor):
    def __init__(self, observation_space: gymnasium_spaces.Box, features_dim=128):
        super(LSTMExtractor, self).__init__(observation_space, features_dim)
        self.lstm_input_size = observation_space.shape[1]
        self.lstm = nn.LSTM(input_size=self.lstm_input_size, hidden_size=128, batch_first=True)
        self.fc = nn.Linear(128, features_dim)
        self.relu = nn.ReLU()

    def forward(self, observations: torch.Tensor) -> torch.Tensor:
        x = observations
        lstm_out, _ = self.lstm(x)
        x = lstm_out[:, -1, :]
        x = self.relu(self.fc(x))
        return x

class AdvancedBTCTradingEnvWithShort(gymnasium.Env):
    metadata = {'render_modes': ['human'], 'render_fps': 30}
    NO_POSITION = 0
    LONG_POSITION = 1
    SHORT_POSITION = -1
    FEATURES = ['open', 'high', 'low', 'close', 'volume', 'trend_macd', 'momentum_rsi', 'volatility_atr']

    def __init__(self, df, lookback=LOOKBACK_PERIOD, initial_capital=10000, transaction_cost=0.001,
                 position_size_options=None, sl_options=None, tp_options=None):
        super().__init__()
        self.df = df.reset_index(drop=True)
        self.lookback = lookback
        self.initial_capital = initial_capital
        self.transaction_cost = transaction_cost

        self.position_size_map = position_size_options or {0: 0.25, 1: 0.50, 2: 0.75, 3: 1.0}
        self.sl_map = sl_options or {0: 0.01, 1: 0.02, 2: 0.03, 3: 0.05}
        self.tp_map = tp_options or {0: 0.02, 1: 0.04, 2: 0.06, 3: 0.10}
        self.features = AdvancedBTCTradingEnvWithShort.FEATURES

        self.current_step = 0; self.cash = 0.0; self.position_type = self.NO_POSITION
        self.position_units = 0.0; self.entry_price = 0.0
        self.stop_loss_price = 0.0; self.take_profit_price = 0.0
        self.max_steps = len(self.df) - 1

        self.observation_space = gymnasium_spaces.Box(low=-np.inf, high=np.inf, shape=(lookback, len(self.features)), dtype=np.float32)
        self.action_space = gymnasium_spaces.MultiDiscrete([4, len(self.position_size_map), len(self.sl_map), len(self.tp_map)])

    def _calculate_portfolio_value(self, current_price):
        value = self.cash
        if self.position_type == self.LONG_POSITION: value += self.position_units * current_price
        elif self.position_type == self.SHORT_POSITION: value += self.position_units * (self.entry_price - current_price)
        return value

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.current_step = self.lookback; self.cash = self.initial_capital
        self.position_type = self.NO_POSITION; self.position_units = 0.0
        self.entry_price = 0.0; self.stop_loss_price = 0.0; self.take_profit_price = 0.0
        
        if self.current_step >= len(self.df): # Should be caught before env creation ideally
            log_message(f"Env Reset Warning: df too short ({len(self.df)}) for lookback ({self.lookback}).")
            # Return a valid zero observation and default info
            return np.zeros(self.observation_space.shape, dtype=np.float32), self._get_info_at_step(0)

        current_price_at_reset = self.df.iloc[min(self.current_step, len(self.df)-1)]['close']
        self.total_value_history = [self._calculate_portfolio_value(current_price_at_reset)]
        return self._get_observation(), self._get_info()

    def _get_observation(self):
        if self.current_step < self.lookback or self.current_step >= len(self.df) :
            return np.zeros(self.observation_space.shape, dtype=np.float32)
        start = self.current_step - self.lookback; end = self.current_step
        obs_data = self.df.iloc[start:end][self.features].values
        mean = np.mean(obs_data, axis=0); std = np.std(obs_data, axis=0)
        std[std == 0] = 1
        return ((obs_data - mean) / std).astype(np.float32)

    def _get_info_at_step(self, step_index):
        safe_idx = min(max(step_index, 0), len(self.df) - 1)
        if safe_idx < 0 or safe_idx >= len(self.df): # Should not happen if df is valid
            current_price = self.initial_capital # Fallback
        else:
            current_price = self.df.iloc[safe_idx]['close']
        
        total_val = self._calculate_portfolio_value(current_price)
        pos_str = "None"
        if self.position_type == self.LONG_POSITION: pos_str = "Long"
        elif self.position_type == self.SHORT_POSITION: pos_str = "Short"
        return {'total_value': total_val, 'cash': self.cash, 'position_type': pos_str, 
                'position_units': self.position_units, 'entry_price': self.entry_price, 
                'sl_price': self.stop_loss_price, 'tp_price': self.take_profit_price, 
                'current_price': current_price, 'profit': total_val - self.initial_capital, 
                'step': self.current_step}

    def _get_info(self): return self._get_info_at_step(self.current_step)

    def step(self, action):
        action_type, ps_idx, sl_idx, tp_idx = action
        if self.current_step >= len(self.df): # Should be terminated
            obs = np.zeros(self.observation_space.shape, dtype=np.float32)
            last_price = self.df.iloc[-1]['close'] if not self.df.empty else self.initial_capital
            val = self._calculate_portfolio_value(last_price)
            return obs, (val - self.initial_capital) / self.initial_capital, True, False, self._get_info_at_step(len(self.df)-1)

        bar = self.df.iloc[self.current_step]; price = bar['close']; closed = False
        if self.position_type == self.LONG_POSITION:
            if bar['low'] <= self.stop_loss_price: self._close_position(self.stop_loss_price); closed=True
            elif bar['high'] >= self.take_profit_price: self._close_position(self.take_profit_price); closed=True
        elif self.position_type == self.SHORT_POSITION:
            if bar['high'] >= self.stop_loss_price: self._close_position(self.stop_loss_price); closed=True
            elif bar['low'] <= self.take_profit_price: self._close_position(self.take_profit_price); closed=True
        if not closed:
            if action_type == 1 and self.position_type == self.NO_POSITION: self._enter_long(price,ps_idx,sl_idx,tp_idx)
            elif action_type == 2 and self.position_type == self.NO_POSITION: self._enter_short(price,ps_idx,sl_idx,tp_idx)
            elif action_type == 3 and self.position_type != self.NO_POSITION: self._close_position(price)
        self.current_step += 1; terminated=False; truncated=False
        
        next_price = self.df.iloc[self.current_step]['close'] if self.current_step < len(self.df) else price
        if self.current_step >= self.max_steps:
            terminated=True
            if self.position_type != self.NO_POSITION: self._close_position(price); next_price=price
        
        val = self._calculate_portfolio_value(next_price)
        if val < 0.1 * self.initial_capital:
            terminated=True
            if self.position_type != self.NO_POSITION: self._close_position(next_price); val=self._calculate_portfolio_value(next_price)
        
        reward = (val - self.initial_capital) / self.initial_capital
        self.total_value_history.append(val)
        obs = self._get_observation() if not terminated else np.zeros(self.observation_space.shape, dtype=np.float32)
        info = self._get_info() if not terminated else self._get_info_at_step(self.current_step-1)
        return obs, reward, terminated, truncated, info

    def _enter_long(self,price,ps_idx,sl_idx,tp_idx): # Simplified
        if self.cash<=0: return
        units = (self.cash*self.position_size_map[ps_idx]/price)*(1-self.transaction_cost)
        if units > 1e-8: # Min tradeable
            self.cash -= units*price/(1-self.transaction_cost); self.position_type=self.LONG_POSITION; self.position_units=units; self.entry_price=price
            self.stop_loss_price=price*(1-self.sl_map[sl_idx]); self.take_profit_price=price*(1+self.tp_map[tp_idx])
    def _enter_short(self,price,ps_idx,sl_idx,tp_idx): # Simplified
        units=(self.cash*self.position_size_map[ps_idx]/price) # Nominal
        if units > 1e-8:
            self.cash += units*price*(1-self.transaction_cost); self.position_type=self.SHORT_POSITION; self.position_units=units; self.entry_price=price
            self.stop_loss_price=price*(1+self.sl_map[sl_idx]); self.take_profit_price=price*(1-self.tp_map[tp_idx])
    def _close_position(self,price): # Simplified
        if self.position_type==self.LONG_POSITION: self.cash+=self.position_units*price*(1-self.transaction_cost)
        elif self.position_type==self.SHORT_POSITION: self.cash-=self.position_units*price*(1+self.transaction_cost) # Cost to cover
        self.position_type=self.NO_POSITION; self.position_units=0; self.entry_price=0; self.stop_loss_price=0; self.take_profit_price=0
    def render(self): info=self._get_info(); print(f"S:{info['step']}/{self.max_steps},V:{info['total_value']:.2f}(P/L:{info['profit']:.2f}),C:{info['cash']:.2f},P:{info['position_type']}({info['position_units']:.4f}@E:{info['entry_price']:.2f}),SL:{info['sl_price']:.2f},TP:{info['tp_price']:.2f},M:{info['current_price']:.2f}")

# --- Model Training and Evaluation Functions (remain mostly the same, use process_dataframe_with_atr) ---
def train_model(train_df_processed, model_path_to_save, existing_model_path=None, timesteps=INITIAL_TRAINING_TIMESTEPS):
    log_message(f"Preparing training env with {len(train_df_processed)} processed data points...")
    if len(train_df_processed) < LOOKBACK_PERIOD + 20: # Min data for env + some trading
        log_message(f"Not enough data ({len(train_df_processed)}) to train. Min: {LOOKBACK_PERIOD + 20}. Skipping.")
        return None
    
    # Ensure only features needed by env are passed
    train_df_env_features = train_df_processed[AdvancedBTCTradingEnvWithShort.FEATURES].copy()

    vec_env = None
    try:
        if existing_model_path:
            env_fn = lambda: AdvancedBTCTradingEnvWithShort(train_df_env_features.copy(), lookback=LOOKBACK_PERIOD)
            vec_env = DummyVecEnv([env_fn])
        else:
            vec_env = make_vec_env(lambda: AdvancedBTCTradingEnvWithShort(train_df_env_features.copy(), lookback=LOOKBACK_PERIOD), n_envs=4)

        policy_kwargs = dict(features_extractor_class=LSTMExtractor, features_extractor_kwargs=dict(features_dim=128),
                             net_arch=dict(pi=[64, 64], vf=[64, 64]))


        # Set CUDA environment variables before importing torch
        cuda_path = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8"
        if os.path.exists(cuda_path):
            os.environ["CUDA_HOME"] = cuda_path
            os.environ["CUDA_PATH"] = cuda_path

            # Add CUDA bin directory to PATH
            cuda_bin = os.path.join(cuda_path, "bin")
            if os.path.exists(cuda_bin):
                os.environ["PATH"] = cuda_bin + os.pathsep + os.environ["PATH"]

            # Add CUDA lib directory to PATH
            cuda_lib = os.path.join(cuda_path, "lib", "x64")  # Use x64 for 64-bit Windows
            if os.path.exists(cuda_lib):
                os.environ["PATH"] = cuda_lib + os.pathsep + os.environ["PATH"]

            # Add cuDNN path if it exists
            cudnn_path = os.path.join(cuda_path, "extras", "CUPTI", "lib64")
            if os.path.exists(cudnn_path):
                os.environ["PATH"] = cudnn_path + os.pathsep + os.environ["PATH"]

            # print(f"CUDA environment variables set to {cuda_path}")
            # print(f"PATH now includes: {os.environ['PATH']}")
        else:
            print(f"Warning: CUDA path {cuda_path} not found")
    
        device = "cuda" if torch.cuda.is_available() else "cpu"

        
        model = None
        if existing_model_path and os.path.exists(existing_model_path):
            log_message(f"Loading existing model from {existing_model_path} for fine-tuning...")
            model = PPO.load(existing_model_path, env=vec_env, device=device, verbose=1) # Increased verbosity
        else:
            log_message("Initializing new PPO model for full training...")
            model = PPO("MlpPolicy", vec_env, policy_kwargs=policy_kwargs, verbose=1, # Increased verbosity
                        learning_rate=0.0003, batch_size=64, n_steps=1024, gamma=0.99, tensorboard_log=TENSORBOARD_LOG_PATH,
                        gae_lambda=0.95, device=device) # Ensure device is passed here

        log_message(f"Starting model training for {timesteps} timesteps on {device}...")
        model.learn(total_timesteps=timesteps, reset_num_timesteps=not bool(existing_model_path))
        model.save(model_path_to_save)
        log_message(f"Model saved to {model_path_to_save}")
        return model_path_to_save
    except Exception as e:
        log_message(f"ERROR during model training or saving: {e}")
        return None
    finally:
        if vec_env: vec_env.close()

def evaluate_model_performance(model_path_to_eval, eval_df_processed, log_suffix="eval"):
    model_filename_no_ext = os.path.splitext(os.path.basename(model_path_to_eval))[0]
    log_message(f"Evaluating model {model_path_to_eval} on eval data ({len(eval_df_processed)} points) for '{log_suffix}'...")
    if len(eval_df_processed) < LOOKBACK_PERIOD + 10:
        log_message(f"Not enough test data ({len(eval_df_processed)}) for evaluation.")
        return {'profit': -float('inf'), 'final_value': 0, 'sharpe_ratio': -float('inf'), 'num_trades': 0}
    
    # Ensure only features needed by env are passed
    eval_df_env_features = eval_df_processed[AdvancedBTCTradingEnvWithShort.FEATURES].copy()
    
    eval_env = None
    try:
        model = PPO.load(model_path_to_eval, device="cuda" if torch.cuda.is_available() else "cpu")
        eval_env = AdvancedBTCTradingEnvWithShort(eval_df_env_features.copy(), lookback=LOOKBACK_PERIOD) # Env doesn't need verbose
        obs, info = eval_env.reset()
        if obs is None : # Reset failed or df too short
             log_message(f"Environment reset failed for evaluation of {model_path_to_eval}. DF length: {len(eval_df_env_features)}")
             return {'profit': -float('inf'), 'final_value': 0, 'sharpe_ratio': -float('inf'), 'num_trades': 0}

        portfolio_values = [eval_env.initial_capital]
        detailed_log_entries = []
        num_trades_entered = 0
        previous_position_type = eval_env.NO_POSITION

        num_eval_steps = len(eval_df_env_features) - eval_env.lookback
        
        for i in range(num_eval_steps):
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = eval_env.step(action)
            portfolio_values.append(info['total_value'])

            # Log detailed step info
            current_data_idx = eval_env.current_step -1 # df index for current candle data
            if current_data_idx < 0 or current_data_idx >= len(eval_df_env_features):
                log_message(f"Warning: current_data_idx {current_data_idx} out of bounds for eval_df_env_features (len {len(eval_df_env_features)}). Skipping detailed log for this step.")
                data_datetime = pd.NaT # Or some placeholder
            else:
                data_datetime = eval_df_env_features.index[current_data_idx]

            detailed_log_entries.append({
                'eval_step': i,
                'data_datetime': data_datetime,
                'current_price_at_decision': eval_df_env_features.iloc[current_data_idx]['close'] if 0 <= current_data_idx < len(eval_df_env_features) else info.get('current_price', None),
                'predicted_action_type': action[0],
                'predicted_ps_idx': action[1],
                'predicted_sl_idx': action[2],
                'predicted_tp_idx': action[3],
                'reward_from_step': reward,
                'position_type_after_step': info['position_type'],
                'position_units_after_step': info['position_units'],
                'entry_price_after_step': info['entry_price'],
                'stop_loss_price_after_step': info['sl_price'],
                'take_profit_price_after_step': info['tp_price'],
                'cash_after_step': info['cash'],
                'total_value_after_step': info['total_value'],
                'profit_vs_initial_after_step': info['profit'],
                'env_step_num_after_step': info['step']
            })

            # Count trades (entries)
            current_position_type_from_info = info['position_type']
            if previous_position_type == eval_env.NO_POSITION and \
               (current_position_type_from_info == eval_env.LONG_POSITION or \
                current_position_type_from_info == eval_env.SHORT_POSITION):
                num_trades_entered += 1
            previous_position_type = current_position_type_from_info

            if terminated or truncated: break
        
        final_val = portfolio_values[-1]; profit = final_val - eval_env.initial_capital
        returns = pd.Series(portfolio_values).pct_change().dropna()
        sharpe = (returns.mean()/returns.std())*np.sqrt(252) if not returns.empty and returns.std()>1e-8 else 0.0
        log_message(f"Eval for {model_path_to_eval} ({log_suffix}): P={profit:.2f}, FV={final_val:.2f}, S={sharpe:.2f}, Trades={num_trades_entered}")

        # Save detailed log
        if detailed_log_entries:
            eval_log_df = pd.DataFrame(detailed_log_entries)
            eval_log_filename = f"eval_details_{model_filename_no_ext}_{log_suffix}.csv"
            eval_log_filepath = os.path.join(EVAL_LOGS_PATH, eval_log_filename)
            eval_log_df.to_csv(eval_log_filepath, index=False)
            log_message(f"Detailed evaluation log saved to {eval_log_filepath}")

        return {'profit': profit, 'final_value': final_val, 'sharpe_ratio': sharpe, 'num_trades': num_trades_entered}
    except Exception as e:
        log_message(f"ERROR during model evaluation for {model_path_to_eval}: {e}")
        return {'profit': -float('inf'), 'final_value': 0, 'sharpe_ratio': -float('inf'), 'num_trades': 0}
    finally:
        if eval_env : pass # eval_env.close() not needed for DummyVecEnv

# --- Main Self-Improving Loop ---
if __name__ == "__main__":
    # Delete existing log file to start fresh
    if os.path.exists(LOG_FILE):
        try:
            os.remove(LOG_FILE)
        except OSError as e:
            print(f"Error deleting log file {LOG_FILE}: {e}") # Print to console as log_message isn't set up yet

    os.makedirs(MODEL_BASE_PATH, exist_ok=True)
    os.makedirs(EVAL_LOGS_PATH, exist_ok=True) # Create eval logs directory
    os.makedirs(TENSORBOARD_LOG_PATH, exist_ok=True) # Create TensorBoard logs directory
    log_message("===== Starting Trading Agent Self-Improvement Cycle (Redis Version) =====")

    # Check and log CUDA availability
    if torch.cuda.is_available():
        log_message(f"CUDA is available. PyTorch version: {torch.__version__}. CUDA version: {torch.version.cuda}. GPU: {torch.cuda.get_device_name(0)}")
    else:
        log_message(f"CUDA not available. PyTorch version: {torch.__version__}. Training will use CPU.")

    
    redis_conn = get_redis_connection()
    if not redis_conn:
        log_message("CRITICAL: No Redis connection. Exiting.")
        exit()

    log_message("--- Initial Data Load from Redis ---")
    df_raw_initial = fetch_all_historical_data_from_redis(redis_conn)
    if df_raw_initial.empty:
        log_message("CRITICAL: No initial historical data fetched from Redis. Exiting.")
        exit()
    
    df_main_processed_full = process_dataframe_with_atr(df_raw_initial, "Initial Redis Fetch")
    if df_main_processed_full.empty:
        log_message("CRITICAL: Initial data processing resulted in an empty DataFrame. Exiting.")
        exit()

    total_len = len(df_main_processed_full)
    # Reserve the last 15-20% for true holdout, or a fixed number of points if dataset is small
    holdout_size = max(int(total_len * 0.15), LOOKBACK_PERIOD + ITERATIONAL_VAL_SET_SIZE + 20) # Ensure holdout is substantial
    if total_len <= holdout_size * 2: # Ensure training data is at least as large as holdout
        holdout_size = int(total_len * 0.3) # Adjust if dataset is very small
    
    # final_holdout_test_df is fixed based on the *very first* load of df_main_processed_full
    # This ensures the final test is truly unseen by any iterative process.
    final_holdout_test_df = df_main_processed_full.iloc[-holdout_size:].copy()
    
    # operational_data_pool is the pool for training and iterative validation; it can grow.
    operational_data_pool = df_main_processed_full.iloc[:-holdout_size].copy()
    
    # df_cumulative_training_data starts as a portion of operational_data_pool
    df_cumulative_training_data = operational_data_pool.iloc[:int(len(operational_data_pool) * 0.7)].copy()
    log_message(f"Initial Operational Data Pool: {len(operational_data_pool)}, Initial Cumulative Train: {len(df_cumulative_training_data)}, Final Holdout Test: {len(final_holdout_test_df)}")

    if not os.path.exists(current_model_path):
        log_message(f"--- No existing model at {current_model_path}. Initial training... ---")
        trained_model_file = train_model(df_cumulative_training_data, current_model_path, timesteps=INITIAL_TRAINING_TIMESTEPS)
        if not trained_model_file: log_message("CRITICAL: Initial model training failed. Exiting."); exit()
        current_model_path = trained_model_file
    else:
        log_message(f"--- Found existing model: {current_model_path} ---")

    # Define df_cumulative_training_data here in case the existing model is used
    df_cumulative_training_data = operational_data_pool.iloc[:int(len(operational_data_pool) * 0.7)].copy()

    last_processed_timestamp = df_cumulative_training_data.index.max().timestamp() if not df_cumulative_training_data.empty else 0

    num_iterations = 5
    for iteration in range(num_iterations):
        log_message(f"\n--- Self-Improvement Iteration {iteration + 1}/{num_iterations} ---")

        # 1. Fetch New Data from Redis
        human_readable_ts = datetime.datetime.fromtimestamp(last_processed_timestamp, tz=datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')
        log_message(f"Fetching new data from Redis since timestamp: {last_processed_timestamp} ({human_readable_ts})")
        df_new_raw = fetch_new_data_from_redis(redis_conn, last_processed_timestamp)
        
        if not df_new_raw.empty:
            df_new_processed = process_dataframe_with_atr(df_new_raw, f"New Redis Data Iter {iteration+1}")
            if not df_new_processed.empty:
                # Append new data to the master full dataset first
                df_main_processed_full = pd.concat([df_main_processed_full, df_new_processed]).sort_index()
                df_main_processed_full = df_main_processed_full[~df_main_processed_full.index.duplicated(keep='last')]

                # Re-define the operational_data_pool based on the updated df_main_processed_full,
                # still respecting the original final_holdout_test_df's start time.
                operational_data_pool = df_main_processed_full[df_main_processed_full.index < final_holdout_test_df.index.min()].copy()
                
                # Update cumulative training data by appending the new processed data
                df_cumulative_training_data = pd.concat([df_cumulative_training_data, df_new_processed]).sort_index()
                df_cumulative_training_data = df_cumulative_training_data[~df_cumulative_training_data.index.duplicated(keep='last')]
                # Ensure cumulative training data does not exceed the updated operational pool
                df_cumulative_training_data = df_cumulative_training_data[df_cumulative_training_data.index <= operational_data_pool.index.max()]
                last_processed_timestamp = df_cumulative_training_data.index.max().timestamp() # Update last_processed_timestamp
                log_message(f"New data added. Cumulative training data size: {len(df_cumulative_training_data)}, Operational data pool size: {len(operational_data_pool)}")
            else:
                log_message("Newly fetched data processed to empty. No update to training data.")
        else:
            log_message("No new data fetched from Redis for this iteration.")

        # 2. Candidate Model Retraining
        log_message("--- Candidate Model Retraining ---")
        candidate_model_name = f"candidate_model_iter_{iteration+1}.zip"
        candidate_model_path_iter = os.path.join(MODEL_BASE_PATH, candidate_model_name)
        
        trained_candidate_path = train_model(df_cumulative_training_data,
                                             candidate_model_path_iter,
                                             existing_model_path=current_model_path,
                                             timesteps=INCREMENTAL_TRAINING_TIMESTEPS)

        # 3. Evaluate Candidate Model
        if not (trained_candidate_path and os.path.exists(trained_candidate_path)):
            log_message(f"Candidate training failed iter {iteration+1}. Keeping: {current_model_path}")
        else:
            # --- Prepare Walk-Forward Validation Set for this Iteration ---
            validation_set_for_iter = pd.DataFrame()
            last_train_idx_dt = df_cumulative_training_data.index.max()

            # Potential validation pool is from the (potentially updated) operational_data_pool
            potential_val_pool = operational_data_pool[operational_data_pool.index > last_train_idx_dt]

            if len(potential_val_pool) >= ITERATIONAL_VAL_SET_SIZE + LOOKBACK_PERIOD:
                validation_set_for_iter = potential_val_pool.iloc[:ITERATIONAL_VAL_SET_SIZE + LOOKBACK_PERIOD]
                log_message(f"Using walk-forward validation slice of {len(validation_set_for_iter)} points for iter {iteration+1} (ends {validation_set_for_iter.index.max()}).")
            elif len(potential_val_pool) >= LOOKBACK_PERIOD + 20: # Use smaller if not enough for full ITERATIONAL_VAL_SET_SIZE
                validation_set_for_iter = potential_val_pool.iloc[:LOOKBACK_PERIOD + 20]
                log_message(f"Using smaller walk-forward validation slice of {len(validation_set_for_iter)} points for iter {iteration+1} (ends {validation_set_for_iter.index.max()}).")
            else:
                log_message(f"Not enough 'future' data in training/walk-forward pool for iter {iteration+1} validation. Candidate cannot be reliably validated.")
            
            if not validation_set_for_iter.empty and len(validation_set_for_iter) > LOOKBACK_PERIOD + 10:
                log_message(f"Evaluating models on validation set of {len(validation_set_for_iter)} points.")
                candidate_perf = evaluate_model_performance(trained_candidate_path, validation_set_for_iter, log_suffix=f"iter{iteration+1}_cand_val")
                current_model_perf = evaluate_model_performance(current_model_path, validation_set_for_iter, log_suffix=f"iter{iteration+1}_curr_val")

                cand_p = candidate_perf.get('profit', -float('inf')); cand_s = candidate_perf.get('sharpe_ratio',-float('inf'))
                curr_s = current_model_perf.get('sharpe_ratio',-float('inf'))
                if cand_p > MIN_PROFIT_FOR_PROMOTION and cand_s > (curr_s + PROMOTION_SHARPE_THRESHOLD) and cand_s > -float('inf'):
                    log_message(f"PROMOTING candidate (Iter {iteration+1}, P:{cand_p:.2f}, S:{cand_s:.3f}) over current (S:{curr_s:.3f}).")
                    promoted_base = f"{CURRENT_MODEL_FILENAME_BASE}_iter{iteration+1}_promoted.zip"
                    new_promoted_path = os.path.join(MODEL_BASE_PATH, promoted_base)
                    try:
                        shutil.copy2(trained_candidate_path, new_promoted_path)
                        current_model_path = new_promoted_path
                        log_message(f"New current best model: {current_model_path}")
                    except Exception as e: log_message(f"ERROR promoting: {e}. Current: {current_model_path}")
                else:
                    log_message(f"Candidate (Iter {iteration+1}, P:{cand_p:.2f}, S:{cand_s:.3f}) not better or not profitable enough. Current: {current_model_path} (S:{curr_s:.3f})")
            else:
                log_message(f"Insufficient validation data for iter {iteration+1}. Skipping promotion.")
        
        log_message(f"--- End Iter {iteration + 1}. Best: {current_model_path} ---")
        time.sleep(5) # Simulate delay for next data cycle

    log_message("===== Trading Agent Self-Improvement Cycle Finished =====")
    log_message(f"Final best model: {current_model_path}")

    if os.path.exists(current_model_path) and not final_holdout_test_df.empty:
        log_message("\n--- Final Evaluation on Holdout Test Set ---")
        final_perf = evaluate_model_performance(current_model_path, final_holdout_test_df, log_suffix="holdout_final")
        log_message(f"Final Model ({current_model_path}) Holdout Perf: {final_perf}")

    if redis_conn:
        redis_conn.close()
        log_message("Redis connection closed.")