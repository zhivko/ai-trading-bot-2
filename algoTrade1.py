import pandas as pd
import numpy as np
import logging
from logging.handlers import RotatingFileHandler
import redis
import json
from datetime import datetime, timedelta

# Setup logging - write to both file and console
logger = logging.getLogger('FractalTrader')
logger.setLevel(logging.DEBUG) # Changed to DEBUG to see more logs

# File handler
file_handler = RotatingFileHandler('fractal_trader.log', maxBytes=10000000, backupCount=5)
# Console handler
console_handler = logging.StreamHandler()

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)

class FractalTradingStrategy:
    def __init__(self, redis_host='localhost', redis_port=6379):
        self.redis_client = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        self.klines = None
        self.ema_period = 15
        self.fractal_levels = 4  # L0 to L4
        self.position = 'flat'
        self.entry_price = 0
        self.stop_loss = 0
        self.take_profit = 0
        self.risk_per_trade = 0.02  # 2% risk per trade
        self.last_trade_index = -1
        self.cooldown_period = 5  # Bars to wait after a trade
        
        # Fractal detection parameters
        self.fractal_window = 5  # Window for fractal detection (2 bars on each side)
        
        # Initialize fractal arrays
        self.reset_fractals()
        
    def reset_fractals(self):
        """Initialize fractal arrays for all levels"""
        self.high_fractals = {f'L{i}': [] for i in range(self.fractal_levels)}
        self.low_fractals = {f'L{i}': [] for i in range(self.fractal_levels)}
        
    def connect_redis(self):
        """Connect to Redis"""
        try:
            self.redis_client.ping()
            logger.info("Successfully connected to Redis.")
            return True
        except redis.ConnectionError:
            logger.error("Failed to connect to Redis.")
            return False
            
    def fetch_klines(self, symbol='BTCUSDT', interval='5m', limit=1000):
        """Fetch klines from Redis using sorted sets (like AppTradingView.py)"""
        logger.info(f"Fetching klines for {symbol} with interval {interval}, limit {limit}.")
        try:
            # Use sorted set key format like AppTradingView.py
            sorted_set_key = f"zset:kline:{symbol}:{interval}"
            
            # Get the most recent klines from the sorted set
            klines_data = self.redis_client.zrange(sorted_set_key, -limit, -1, withscores=False)
            
            if not klines_data:
                logger.warning(f"No klines found in Redis for key {sorted_set_key}")
                return False
                
            klines = [json.loads(kline) for kline in klines_data]
            
            # Convert to DataFrame with the expected structure
            self.klines = pd.DataFrame(klines)
            
            # Debug: print the columns to see what's actually in the data
            logger.info(f"Kline columns found: {list(self.klines.columns)}")
            
            # Check if we have the required columns - note: Redis data uses 'vol' not 'volume'
            if 'time' not in self.klines.columns:
                logger.error("Kline data missing 'time' column")
                return False
                
            # Convert to numeric for OHLCV columns - note: volume is 'vol' in Redis data
            for col in ['open', 'high', 'low', 'close', 'vol']:
                if col in self.klines.columns:
                    self.klines[col] = pd.to_numeric(self.klines[col], errors='coerce')
            
            # Convert timestamp to datetime (assuming it's already in seconds)
            self.klines['timestamp'] = pd.to_datetime(self.klines['time'], unit='s')
            
            # Sort by timestamp to ensure chronological order
            self.klines = self.klines.sort_values('timestamp').reset_index(drop=True)
            
            logger.info(f"Successfully fetched {len(self.klines)} klines from Redis.")
            logger.info(f"Sample data: {self.klines[['timestamp', 'open', 'high', 'low', 'close', 'vol']].iloc[-1].to_dict()}")
            return True
            
        except Exception as e:
            logger.error(f"Error fetching klines: {e}")
            return False
            
    def calculate_ema(self, data, period):
        """Calculate EMA for given period"""
        return data['close'].ewm(span=period, adjust=False).mean()
        
    def detect_fractals(self, high_series, low_series, window=5):
        """
        Detect fractal patterns in price data
        Returns high_fractals, low_fractals arrays with fractal indices
        """
        high_fractals = []
        low_fractals = []
        
        # Middle index of the window
        mid = window // 2
        
        for i in range(mid, len(high_series) - mid):
            # Check for high fractal (pattern: middle bar is highest in the window)
            if high_series.iloc[i] == max(high_series.iloc[i-mid:i+mid+1]):
                high_fractals.append(i)
                
            # Check for low fractal (pattern: middle bar is lowest in the window)
            if low_series.iloc[i] == min(low_series.iloc[i-mid:i+mid+1]):
                low_fractals.append(i)
                
        return high_fractals, low_fractals
        
    def update_fractal_levels(self):
        """Update all fractal levels based on current price data"""
        logger.debug("Updating fractal levels...")
        if self.klines is None or len(self.klines) < 20:  # Need enough data
            logger.debug("Not enough data to update fractals.")
            return
            
        # Reset fractals
        self.reset_fractals()
        
        # Calculate L0 fractals (base level)
        high_series = self.klines['high']
        low_series = self.klines['low']
        
        self.high_fractals['L0'], self.low_fractals['L0'] = self.detect_fractals(high_series, low_series)
        logger.debug(f"Level 0 fractals: {len(self.high_fractals['L0'])} highs, {len(self.low_fractals['L0'])} lows")
        
        # Calculate higher-level fractals by filtering lower-level ones
        for level in range(1, self.fractal_levels):
            # Use previous level fractals as input
            prev_highs = [high_series.iloc[i] for i in self.high_fractals[f'L{level-1}']]
            prev_lows = [low_series.iloc[i] for i in self.low_fractals[f'L{level-1}']]
            
            if len(prev_highs) >= 5:
                prev_high_series = pd.Series(prev_highs)
                prev_low_series = pd.Series(prev_lows)
                
                # Detect fractals on the previous level fractals
                high_fractals, low_fractals = self.detect_fractals(prev_high_series, prev_low_series)
                
                # Map back to original indices
                self.high_fractals[f'L{level}'] = [self.high_fractals[f'L{level-1}'][i] for i in high_fractals]
                self.low_fractals[f'L{level}'] = [self.low_fractals[f'L{level-1}'][i] for i in low_fractals]
                
    def should_enter_long(self, current_index):
        """Check conditions for long entry"""
        if self.position != 'flat':
            return False
            
        # Check if we're in cooldown period after last trade
        if self.last_trade_index != -1 and current_index - self.last_trade_index < self.cooldown_period:
            return False
            
        current_close = self.klines['close'].iloc[current_index]
        current_high = self.klines['high'].iloc[current_index]
        current_low = self.klines['low'].iloc[current_index]
        ema = self.ema_values.iloc[current_index]
        
        # Price must be above EMA
        if current_close <= ema:
            return False
            
        # Check for L2 or higher bullish fractal pattern
        for level in range(2, self.fractal_levels):
            if f'L{level}' in self.high_fractals and self.high_fractals[f'L{level}']:
                # Get the most recent fractal
                last_fractal_idx = self.high_fractals[f'L{level}'][-1]
                fractal_high = self.klines['high'].iloc[last_fractal_idx]
                
                # Price breaks above the fractal high
                if current_high > fractal_high:
                    return True
                    
        return False
        
    def should_enter_short(self, current_index):
        """Check conditions for short entry"""
        if self.position != 'flat':
            return False
            
        # Check if we're in cooldown period after last trade
        if self.last_trade_index != -1 and current_index - self.last_trade_index < self.cooldown_period:
            return False
            
        current_close = self.klines['close'].iloc[current_index]
        current_high = self.klines['high'].iloc[current_index]
        current_low = self.klines['low'].iloc[current_index]
        ema = self.ema_values.iloc[current_index]
        
        # Price must be below EMA
        if current_close >= ema:
            return False
            
        # Check for L2 or higher bearish fractal pattern
        for level in range(2, self.fractal_levels):
            if f'L{level}' in self.low_fractals and self.low_fractals[f'L{level}']:
                # Get the most recent fractal
                last_fractal_idx = self.low_fractals[f'L{level}'][-1]
                fractal_low = self.klines['low'].iloc[last_fractal_idx]
                
                # Price breaks below the fractal low
                if current_low < fractal_low:
                    return True
                    
        return False
        
    def should_exit_long(self, current_index):
        """Check conditions for exiting long position"""
        if self.position != 'long':
            return False
            
        current_low = self.klines['low'].iloc[current_index]
        
        # Check stop loss
        if current_low <= self.stop_loss:
            return True
            
        # Check take profit
        if self.klines['high'].iloc[current_index] >= self.take_profit:
            return True
            
        # Check if price closes below EMA
        current_close = self.klines['close'].iloc[current_index]
        ema = self.ema_values.iloc[current_index]
        if current_close < ema:
            return True
            
        return False
        
    def should_exit_short(self, current_index):
        """Check conditions for exiting short position"""
        if self.position != 'short':
            return False
            
        current_high = self.klines['high'].iloc[current_index]
        
        # Check stop loss
        if current_high >= self.stop_loss:
            return True
            
        # Check take profit
        if self.klines['low'].iloc[current_index] <= self.take_profit:
            return True
            
        # Check if price closes above EMA
        current_close = self.klines['close'].iloc[current_index]
        ema = self.ema_values.iloc[current_index]
        if current_close > ema:
            return True
            
        return False
        
    def enter_long(self, current_index):
        """Enter long position"""
        entry_price = self.klines['close'].iloc[current_index]
        atr = self.calculate_atr(14, current_index)
        
        # Calculate stop loss and take profit
        self.stop_loss = entry_price - 2 * atr
        self.take_profit = entry_price + 3 * atr
        
        self.position = 'long'
        self.entry_price = entry_price
        self.last_trade_index = current_index
        
        logger.info(f"LONG entry at index {current_index}, price: {entry_price}, SL: {self.stop_loss}, TP: {self.take_profit}")
        
    def enter_short(self, current_index):
        """Enter short position"""
        entry_price = self.klines['close'].iloc[current_index]
        atr = self.calculate_atr(14, current_index)
        
        # Calculate stop loss and take profit
        self.stop_loss = entry_price + 2 * atr
        self.take_profit = entry_price - 3 * atr
        
        self.position = 'short'
        self.entry_price = entry_price
        self.last_trade_index = current_index
        
        logger.info(f"SHORT entry at index {current_index}, price: {entry_price}, SL: {self.stop_loss}, TP: {self.take_profit}")
        
    def exit_position(self, current_index, reason=""):
        """Exit current position"""
        exit_price = self.klines['close'].iloc[current_index]
        pnl_pct = ((exit_price - self.entry_price) / self.entry_price * 100) if self.position == 'long' else ((self.entry_price - exit_price) / self.entry_price * 100)
        
        logger.info(f"Exit {self.position} at index {current_index}, price: {exit_price}, PnL: {pnl_pct:.2f}% {reason}")
        
        self.position = 'flat'
        self.entry_price = 0
        self.stop_loss = 0
        self.take_profit = 0
        
    def calculate_atr(self, period, current_index):
        """Calculate Average True Range"""
        if current_index < period:
            return 0
            
        tr_values = []
        for i in range(current_index - period + 1, current_index + 1):
            high = self.klines['high'].iloc[i]
            low = self.klines['low'].iloc[i]
            prev_close = self.klines['close'].iloc[i-1] if i > 0 else self.klines['open'].iloc[i]
            
            tr1 = high - low
            tr2 = abs(high - prev_close)
            tr3 = abs(low - prev_close)
            tr = max(tr1, tr2, tr3)
            tr_values.append(tr)
            
        return sum(tr_values) / period
        
    def run(self):
        """Main strategy loop"""
        logger.info("Starting strategy run.")
        
        if not self.connect_redis():
            print("Failed to connect to Redis. Exiting...")
            return
            
        if not self.fetch_klines():
            print("Could not fetch klines. Exiting...")
            return
            
        # Calculate EMA
        self.ema_values = self.calculate_ema(self.klines, self.ema_period)
        
        # Process each bar
        for i in range(20, len(self.klines)):  # Start from index 20 to have enough data
            logger.debug(f"Processing index {i}, position: {self.position}")
            # Update fractals
            self.update_fractal_levels()
            
            # Check for exit conditions first
            if self.position == 'long' and self.should_exit_long(i):
                print(f"Exiting long at index {i}")
                self.exit_position(i, "Exit conditions met")
            elif self.position == 'short' and self.should_exit_short(i):
                print(f"Exiting short at index {i}")
                self.exit_position(i, "Exit conditions met")
                
            # Check for entry conditions
            if self.position == 'flat':
                if self.should_enter_long(i):
                    print(f"Entering long at index {i}")
                    self.enter_long(i)
                elif self.should_enter_short(i):
                    print(f"Entering short at index {i}")
                    self.enter_short(i)
                    
            # Log current state
            if i % 10 == 0:  # Log every 10 bars to avoid too much logging
                logger.info(f"Index: {i}, Position: {self.position}, Price: {self.klines['close'].iloc[i]}, EMA: {self.ema_values.iloc[i]}")
                
                # Log fractals
                for level in range(self.fractal_levels):
                    logger.info(f"L{level} Highs: {self.high_fractals.get(f'L{level}', [])[-5:]}")
                    logger.info(f"L{level} Lows: {self.low_fractals.get(f'L{level}', [])[-5:]}")
        logger.info("Strategy run finished.")

# Add this method to the class
def load_sample_data(self):
    """Load sample data for testing"""
    dates = pd.date_range(start='2025-08-01', periods=1000, freq='5min')
    np.random.seed(42)
    prices = np.cumsum(np.random.randn(1000) * 10) + 115000
    
    self.klines = pd.DataFrame({
        'timestamp': dates,
        'open': prices - np.random.rand(1000) * 50,
        'high': prices + np.random.rand(1000) * 50,
        'low': prices - np.random.rand(1000) * 50,
        'close': prices,
        'volume': np.random.rand(1000) * 100
    })
    
    logger.info("Loaded sample data for testing")
    
# Modify the run method to use sample data
def run(self, use_sample_data=False):
    """Main strategy loop"""
    if use_sample_data:
        self.load_sample_data()
    else:
        if not self.connect_redis():
            return
        if not self.fetch_klines():
            return

