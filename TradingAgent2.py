import os
import time
import datetime
import shutil
import json # For serializing/deserializing data in Redis
import traceback # For detailed error logging

import numpy as np
import pandas as pd
import torch
import torch.nn as nn # Not strictly needed for PPO MlpPolicy, but good practice if custom nets are used

import gymnasium as gym # Use gymnasium instead of gym
from gymnasium import spaces # Use gymnasium spaces

from stable_baselines3 import PPO
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.vec_env import DummyVecEnv
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor # Needed if using custom feature extractor

import redis

# Use ta library for indicators, similar to TradingAgent.py
from ta import add_all_ta_features
from ta.volatility import AverageTrueRange
import pandas_ta as ta # Use pandas_ta for consistency with AppTradingView

# Use pybit for fetching data if needed for backfill
from pybit.unified_trading import HTTP as BybitHTTPClient

# --- Configuration (Copied/Adapted from TradingAgent.py) ---
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_OHLCV_KEY_PREFIX = f"agent:zset:kline:BTCUSDT:5m" # Use the same key as AppTradingView.py
REDIS_OPEN_INTEREST_KEY_PREFIX = f"agent:zset:open_interest:BTCUSDT:5m" # Dedicated key for Open Interest data
MIN_RECORDS_FOR_TRAINING = 100000 # Desired number of records
TENSORBOARD_LOG_PATH = "./trading_agent2_tensorboard_logs/"
LOOKBACK_PERIOD = 60 # Window size for the environment state


class TradingEnv(gym.Env):
    metadata = {"render_modes": ["human"], "render_fps": 4}

    # Simplified to handle a single ticker explicitly
    def __init__(self, data, window_size=LOOKBACK_PERIOD, initial_capital=10000, transaction_cost=0.001, render_mode: str | None = None):
        super(TradingEnv, self).__init__()
        self.data = data
        self.initial_capital = initial_capital # Store initial_capital
        self.render_mode = render_mode
        self.window_size = window_size
        self.current_step = 0
        self.cash = 10000  # Initial cash
        self.holdings = 0.0 # Single asset holding
        self.episode_count = 0 # Track episode number
        self.prev_portfolio_value = self.cash
        self.portfolio_history = [self.cash]  # Track portfolio value history
        
        # Action space: continuous action for the single ticker (-1 to 1)
        # -1: Sell, 1: Buy, 0: Hold. Scale action value to percentage of capital/holdings.
        self.action_space = spaces.Box(low=-1, high=1, shape=(1,), dtype=np.float32)

        # Features used by the environment (should match process_dataframe_with_atr output)
        self.features = ['open', 'high', 'low', 'close', 'volume',
                         'open_interest', # New: Open Interest
                         'trend_macd', 'momentum_rsi', 'volatility_atr',
                         'STOCHRSIk_14_14_3_3', 'STOCHRSId_14_14_3_3']
        self.features = [
            'open', 'high', 'low', 'close', 'volume', 'open_interest',
            'MACD_12_26_9', 'MACDh_12_26_9', 'MACDs_12_26_9',
            'RSI_14',
            'ATRr_14',
            'STOCHRSIk_9_9_3_3', 'STOCHRSId_9_9_3_3',
            'STOCHRSIk_14_14_3_3', 'STOCHRSId_14_14_3_3',
            'STOCHRSIk_40_40_4_4', 'STOCHRSId_40_40_4_4',
            'STOCHRSIk_60_60_10_10', 'STOCHRSId_60_60_10_10'
        ]

        # Observation space: windowed features, cash, and holdings
        state_size = (window_size * len(self.features)) + 1 + 1 # Windowed features + cash + holdings
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(state_size,), dtype=np.float32)
        
        self.max_steps = len(data) - window_size - 1

    def _get_state(self):
        # Ensure we have enough data for the window
        if self.current_step < self.window_size -1 or self.current_step >= len(self.data):
             # Return a zero state if not enough data or out of bounds
             return np.zeros(self.observation_space.shape, dtype=np.float32)

        # Get the window of data
        start_idx = self.current_step - self.window_size + 1
        end_idx = self.current_step + 1 # Include current step

        # Extract features for the window
        window_data = self.data[self.features].iloc[start_idx:end_idx].values

        # Flatten the window data
        flattened_window_data = window_data.flatten()

        # Get current price for holdings normalization
        current_price_for_holdings_norm = self.data['original_close'].iloc[self.current_step]
        
        # Normalize holdings: value of holdings relative to initial capital
        # If current_price is 0 (e.g., at start or bad data), normalized_holdings will be 0.
        normalized_holdings = (self.holdings * current_price_for_holdings_norm / self.initial_capital) if self.initial_capital > 0 and current_price_for_holdings_norm > 0 else 0.0

        # Append cash (already scaled by initial_capital) and normalized holdings
        state = np.append(flattened_window_data, [self.cash / self.initial_capital, normalized_holdings])

        return np.array(state, dtype=np.float32)

    def _take_action(self, action):
        # Action is a single value in [-1, 1]
        action_value = action[0] # Get the single action value
        current_price_actual = self.data['original_close'].iloc[self.current_step] # Use original_close for actual trading calculations
        transaction_cost_rate = 0.001 # 0.1%

        if current_price_actual <= 0: # Avoid division by zero or negative prices
            return

        # Buy action (action_value > 0)
        if action_value > 0:
            # Scale action value to a percentage of available cash to use (e.g., 0 to 100%)
            # A simple scaling: action_value 0 -> 0% cash, action_value 1 -> 100% cash
            allocation_percentage = action_value # Use action_value directly as percentage (0 to 1)
            amount_to_spend = self.cash * allocation_percentage
            if amount_to_spend > 0:
                shares_to_buy = amount_to_spend / current_price_actual
                cost = shares_to_buy * current_price_actual
                transaction_cost = cost * transaction_cost_rate
                if cost + transaction_cost <= self.cash:
                    self.holdings += shares_to_buy
                    self.cash -= (cost + transaction_cost)

        # Sell action (action_value < 0)
        elif action_value < 0:
            # Scale action value (negative) to a percentage of current holdings to sell
            # A simple scaling: action_value 0 -> 0% holdings, action_value -1 -> 100% holdings
            # Use abs(action_value) as percentage (0 to 1)
            sell_percentage = abs(action_value)
            shares_to_sell = self.holdings * sell_percentage
            if shares_to_sell > 0: # Ensure there are shares to sell
                value_from_sale = shares_to_sell * current_price_actual
                transaction_cost = value_from_sale * transaction_cost_rate
                self.holdings -= shares_to_sell
                self.cash += (value_from_sale - transaction_cost)

        # Hold action (action_value close to 0) - implicitly handled if action_value is not significantly positive or negative

    def step(self, action):
        # Extract the scalar action value for interpretation
        action_value = action[0]
        normalized_price_for_log = self.data['close'].iloc[self.current_step] # Normalized price for logging

        current_timestamp = self.data.index[self.current_step] # Get the timestamp
        # Calculate net worth at the start of the step (before action is taken)
        net_worth_at_start = self.cash + self.holdings * self.data['original_close'].iloc[self.current_step]
        # Use carriage return `\r` to move to the beginning of the line and `end=''` to not print a newline.
        print(f"\rEpisode: {self.episode_count:>4}, Step: {self.current_step:>6}, Timestamp: {current_timestamp.strftime('%Y-%m-%d %H:%M:%S')}, Action: {action_value:>8.4f}, Cash: {self.cash:>15.2f}, Holdings: {self.holdings:>12.4f}, NetWorth: {net_worth_at_start:>15.2f}  ", end="")
        
        # Interpret the continuous action for logging
        '''
        if action_value > 0.05: # Threshold for a significant buy (adjust as needed)
            print(f"  Agent intends to BUY: {action_value:.4f} (alloc % of cash), Normalized Price: {normalized_price_for_log:.4f}, Timestamp: {current_timestamp}")
        elif action_value < -0.05: # Threshold for a significant sell (adjust as needed)
            print(f"  Agent intends to SELL: {action_value:.4f} (sell % of holdings), Normalized Price: {normalized_price_for_log:.4f}, Timestamp: {current_timestamp}")
        else: # Action close to zero
            print(f"  Agent intends to HOLD: {action_value:.4f}, Normalized Price: {normalized_price_for_log:.4f}, Timestamp: {current_timestamp}")
        '''   
            
        self._take_action(action)
        self.current_step += 1
        
        current_price_actual = self.data['original_close'].iloc[self.current_step] # Use original_close for portfolio value calculation
        portfolio_value = self.cash + self.holdings * current_price_actual # Correct portfolio value for single asset

        # --- New Reward Calculation ---
        # 1. Primary reward: change in portfolio value, scaled by initial capital.
        # This gives a direct incentive to increase net worth.
        primary_reward = (portfolio_value - self.prev_portfolio_value) / self.initial_capital

        # 2. Risk-adjusted reward shaping using a rolling Sharpe-like ratio
        returns_window = 30  # Window for calculating returns for Sharpe ratio
        sharpe_reward = 0.0
        if len(self.portfolio_history) > returns_window:
            # Calculate percentage returns from portfolio values
            portfolio_series = pd.Series(self.portfolio_history[-returns_window:])
            returns = portfolio_series.pct_change().dropna()
            
            # A simple, non-annualized Sharpe ratio for reward shaping
            if not returns.empty and returns.std() > 1e-8:
                # Use a small scaling factor so it doesn't overpower the primary profit signal
                sharpe_reward = (returns.mean() / returns.std()) * 0.05
        
        # 3. Penalty for low portfolio growth (discourage doing nothing or losing slowly)
        # Check if the agent is consistently below the starting capital after a certain number of steps
        underwater_penalty = 0.0
        if self.current_step > self.window_size + 100 and portfolio_value < self.initial_capital:
            # The penalty is proportional to how far below it is.
            underwater_penalty = (self.initial_capital - portfolio_value) / self.initial_capital * 0.01 # Small penalty

        # 4. Combine rewards and penalties
        reward = primary_reward + sharpe_reward - underwater_penalty

        # 5. Large penalty for liquidation/negative portfolio
        if portfolio_value < 0:
            self.holdings = 0.0  # Sell all holdings
            self.cash = 0 # Reset cash
            portfolio_value = 0
            reward -= 10  # A large, scaled penalty for being liquidated

        # 6. Update portfolio history and previous value
        self.portfolio_history.append(portfolio_value)
        self.prev_portfolio_value = portfolio_value

        # 7. Clip the final reward to a reasonable range to stabilize training
        reward = np.clip(reward, -5, 5)
        # --- End New Reward Calculation ---

        terminated = self.current_step >= self.max_steps or portfolio_value < self.initial_capital * 0.1 # Terminate if end of data or portfolio crashes
        state = self._get_state()
        
        return state, reward, terminated, False, {} # Return terminated, truncated, info

    def reset(self, seed=None, options=None):
        super().reset(seed=seed) # Call the parent class's reset method

        self.episode_count += 1 # Increment episode count on reset
        self.current_step = self.window_size
        self.cash = 10000
        self.holdings = 0.0 # Correctly reset holdings for a single asset
        self.prev_portfolio_value = self.cash
        self.portfolio_history = [self.cash]
        # Ensure enough data exists for the initial state after reset
        if len(self.data) <= self.window_size:
             # Handle case where data is too short
             print(f"Warning: Data length ({len(self.data)}) is too short for window size ({self.window_size}). Cannot reset environment properly.")
             # Return a valid zero state and default info
             return np.zeros(self.observation_space.shape, dtype=np.float32), {}
        return self._get_state(), {} # Return observation and info

    def render(self):
        if self.render_mode == "human":
            # The print functionality is now handled in the `step` method to allow for a single, overwriting line.
            pass

# --- Helper Functions (Copied/Adapted from TradingAgent.py) ---
LOG_FILE = "trading_agent2_log.txt" # Separate log file for this agent

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

# Bybit Configuration (used if backfilling data)
# These should ideally be environment variables or config file
BYBIT_API_KEY_AGENT = os.getenv("BYBIT_API_KEY_AGENT", "YOUR_BYBIT_API_KEY_HERE")
BYBIT_API_SECRET_AGENT = os.getenv("BYBIT_API_SECRET_AGENT", "YOUR_BYBIT_SECRET_HERE")
TRADING_SYMBOL = "BTCUSDT" # Symbol to trade
TRADING_TIMEFRAME = "5m" # Timeframe for data

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
        
    all_oi_data.sort(key=lambda x: x["time"])
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
        env_expected_features = ['open', 'high', 'low', 'close', 'volume', # OHLCV
                                 'open_interest', # New: Open Interest
                                 'trend_macd', 'momentum_rsi', 'volatility_atr',
                                 'STOCHRSIk_14_14_3_3', 'STOCHRSId_14_14_3_3']
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
        
        # =========================================================================
        # >>> NEW: CALL THE SIGNAL DETECTION FUNCTION HERE <<<
        # We call it now, using the data with real, un-normalized indicator values.
        if not df.empty:
            detect_and_report_buy_signals(df)
        # =========================================================================
        
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


def main():
    # Delete existing log file to start fresh
    if os.path.exists(LOG_FILE):
        try:
            os.remove(LOG_FILE)
        except OSError as e:
            print(f"Error deleting log file {LOG_FILE}: {e}") # Print to console as log_message isn't set up yet

    os.makedirs(TENSORBOARD_LOG_PATH, exist_ok=True)

    log_message("===== Starting Trading Agent 2 (Redis Data) =====")

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
    df_processed = process_dataframe_with_atr(raw_data_dfs, "Initial Redis Fetch")

    if df_processed.empty:
        log_message("CRITICAL: Initial data processing resulted in an empty DataFrame. Exiting.")
        exit()

    # Ensure enough data for the environment window
    if len(df_processed) <= LOOKBACK_PERIOD:
         log_message(f"CRITICAL: Processed data length ({len(df_processed)}) is not enough for the environment window size ({LOOKBACK_PERIOD}). Exiting.")
         exit()

    log_message(f"Successfully loaded and processed {len(df_processed)} data points.")

    # Create the environment using the processed data
    # The environment now expects a single DataFrame for one asset
    env = make_vec_env(
        lambda: TradingEnv(df_processed, window_size=LOOKBACK_PERIOD, render_mode="human"),
        n_envs=1,
        vec_env_cls=DummyVecEnv
    )

    # --- CUDA Environment Setup (similar to TradingAgent.py) ---
    cuda_path_agent2 = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8" # Standard path
    if os.path.exists(cuda_path_agent2):
        os.environ["CUDA_HOME"] = cuda_path_agent2
        os.environ["CUDA_PATH"] = cuda_path_agent2

        cuda_bin_agent2 = os.path.join(cuda_path_agent2, "bin")
        if os.path.exists(cuda_bin_agent2):
            os.environ["PATH"] = cuda_bin_agent2 + os.pathsep + os.environ.get("PATH", "")

        cuda_lib_agent2 = os.path.join(cuda_path_agent2, "lib", "x64")
        if os.path.exists(cuda_lib_agent2):
            os.environ["PATH"] = cuda_lib_agent2 + os.pathsep + os.environ.get("PATH", "")
        
        cudnn_path_agent2 = os.path.join(cuda_path_agent2, "extras", "CUPTI", "lib64") # Often part of CUDA toolkit
        if os.path.exists(cudnn_path_agent2):
             os.environ["PATH"] = cudnn_path_agent2 + os.pathsep + os.environ.get("PATH", "")
        log_message(f"Attempted to set CUDA environment variables using path: {cuda_path_agent2}")
    else:
        log_message(f"Warning: CUDA path {cuda_path_agent2} not found. GPU acceleration might not be available or configured correctly.")
    # --- End CUDA Environment Setup ---

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    log_message(f"Using {device} device. CUDA available: {torch.cuda.is_available()}")

    model = PPO("MlpPolicy", env, learning_rate=0.0003, n_steps=2048, batch_size=64, n_epochs=10, gamma=0.99, verbose=1, device=device)
    model = PPO("MlpPolicy", env, learning_rate=0.0003, n_steps=2048, batch_size=64, n_epochs=10, gamma=0.99, verbose=1, device=device, tensorboard_log=TENSORBOARD_LOG_PATH)
    model.learn(total_timesteps=1_000_000)

    # Save the trained model
    model_filename = f"trading_model_ppo_{TRADING_SYMBOL}_{TRADING_TIMEFRAME}_{int(time.time())}"
    model.save(model_filename)
    log_message(f"Model saved to {model_filename}.zip")

    # --- Evaluation Loop (Optional) ---
    log_message("\n--- Starting Evaluation ---")
    obs = env.reset()
    
    # List to store categorized actions for distribution analysis
    categorized_actions = []
        
    for _ in range(1000):
        action, _ = model.predict(obs, deterministic=True) # Use deterministic=True for evaluation
        action_value = action[0][0] # Get the single action value from the (1,1) array

        # Categorize continuous action into discrete labels for distribution analysis
        if action_value > 0.05:
            categorized_actions.append(0) # Buy
        elif action_value < -0.05:
            categorized_actions.append(1) # Sell
        else:
            categorized_actions.append(2) # Hold
            
        # VecEnv.step() returns: observations, rewards, dones, infos
        # For a single environment (n_envs=1):
        # - obs is the observation array/dict
        # - rewards is a numpy array like array([actual_reward])
        # - dones is a numpy array like array([True/False]) where True means terminated OR truncated
        # - infos is a list containing one dictionary: [actual_info_dict]

        obs, rewards, dones, infos = env.step(action)
        env.render()
        if dones[0]: # dones[0] is True if the episode for the first (and only) env is done
            log_message(f"Evaluation episode finished at step {env.get_attr('current_step')[0]}.")
            obs = env.reset()

    # Add a newline after the evaluation loop to move to the next line in the terminal
    print() 


    # Log the action distribution after the evaluation loop
    if categorized_actions:
        # Create labels for the bincount output
        action_labels = {0: "Buy", 1: "Sell", 2: "Hold"}
        # Get counts for each category
        counts = np.bincount(categorized_actions, minlength=len(action_labels))
        
        distribution_str = "Action Distribution (Buy, Sell, Hold):\n"
        for i, count in enumerate(counts):
            distribution_str += f"  {action_labels.get(i, f'Category {i}')}: {count} times\n"
        log_message(distribution_str)
    else:
        log_message("No actions recorded during evaluation.")


    log_message("===== Trading Agent 2 Finished =====")

    if redis_conn:
        redis_conn.close()
        log_message("Redis connection closed.")

if __name__ == "__main__":
    main()