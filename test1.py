import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import mplfinance as mpf
from datetime import datetime, timedelta
import ta  # Technical analysis library
import redis
import json

# Configuration
SYMBOL = 'BTCUSDT'
INTERVAL = '1h'
LIMIT = 300  # Number of candles to fetch
INDICATOR_WINDOW = 14  # Standard window for indicators
KC_WINDOW = 20  # Keltner Channel window
KC_ATR_MULTIPLIER = 2.0  # Keltner Channel ATR multiplier

def fetch_data_from_redis(symbol=SYMBOL, interval=INTERVAL, limit=LIMIT):
    """
    Fetch OHLCV data from local Redis server
    """
    try:
        # Connect to Redis
        r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        
        # Get the sorted set key based on symbol and interval
        sorted_set_key = f"zset:kline:{symbol}:{interval}"
        
        # Get the last 'limit' items from the sorted set (newest first)
        # ZRANGE returns from lowest to highest score, so we use negative indices for the end
        klines_data = r.zrange(sorted_set_key, -limit, -1, withscores=False)
        
        if not klines_data:
            print(f"No data found in Redis for key: {sorted_set_key}")
            return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])
        
        # Parse JSON strings and collect data
        klines_list = []
        for data_str in klines_data:
            try:
                kline = json.loads(data_str)
                klines_list.append(kline)
            except json.JSONDecodeError as e:
                print(f"Error parsing JSON: {e}, data: {data_str}")
                continue
        
        if not klines_list:
            print("No valid kline data found after parsing")
            return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])
        
        # Convert to DataFrame
        df = pd.DataFrame(klines_list)
        
        # Ensure we have the required columns
        required_columns = ['time', 'open', 'high', 'low', 'close', 'vol']
        for col in required_columns:
            if col not in df.columns:
                print(f"Missing required column: {col}")
                return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])
        
        # Convert types
        numeric_columns = ['open', 'high', 'low', 'close', 'vol']
        df[numeric_columns] = df[numeric_columns].apply(pd.to_numeric)
        
        # Convert timestamp to datetime and set as index
        df['timestamp'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('timestamp', inplace=True)
        
        # Rename 'vol' to 'volume' for consistency
        df.rename(columns={'vol': 'volume'}, inplace=True)
        
        return df[['open', 'high', 'low', 'close', 'volume']]
        
    except redis.ConnectionError as e:
        print(f"Redis connection error: {e}")
        return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])
    except Exception as e:
        print(f"Error fetching data from Redis: {e}")
        return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])

def calculate_indicators(df):
    """
    Calculate RSI, Stochastic RSI, MACD, and Keltner Channel
    """
    # RSI
    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=INDICATOR_WINDOW).rsi()
    
    # Stochastic RSI
    stoch_rsi = ta.momentum.StochRSIIndicator(df['close'], window=INDICATOR_WINDOW)
    df['stoch_rsi'] = stoch_rsi.stochrsi()
    df['stoch_rsi_k'] = stoch_rsi.stochrsi_k()
    df['stoch_rsi_d'] = stoch_rsi.stochrsi_d()
    
    # MACD
    macd = ta.trend.MACD(df['close'])
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    df['macd_histogram'] = macd.macd_diff()
    
    # Keltner Channel
    df['kc_middle'] = ta.trend.EMAIndicator(df['close'], window=KC_WINDOW).ema_indicator()
    
    # Calculate ATR for Keltner Channel
    atr = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=KC_WINDOW).average_true_range()
    df['kc_upper'] = df['kc_middle'] + (atr * KC_ATR_MULTIPLIER)
    df['kc_lower'] = df['kc_middle'] - (atr * KC_ATR_MULTIPLIER)
    
    # Volume indicators
    df['volume_sma'] = ta.volume.VolumeWeightedAveragePrice(
        df['high'], df['low'], df['close'], df['volume']
    ).volume_weighted_average_price()
    
    return df


def create_chart(df, save_path='btc_chart.png'):
    """
    Create OHLC chart with Keltner Channel
    """
    # Create subplots
    apds = [
        mpf.make_addplot(df['rsi'], panel=1, color='purple', ylabel='RSI'),
        mpf.make_addplot(df['stoch_rsi'], panel=1, color='blue', ylabel='Stoch RSI'),
        mpf.make_addplot(df[['macd', 'macd_signal']], panel=2, ylabel='MACD'),
        mpf.make_addplot(df['volume'], panel=3, type='bar', color='orange', ylabel='Volume')
    ]
    
    # Add Keltner Channel to main panel
    kc_plots = [
        mpf.make_addplot(df['kc_upper'], color='green', linestyle='--', alpha=0.7, label='KC Upper'),
        mpf.make_addplot(df['kc_middle'], color='blue', linestyle='-', alpha=0.7, label='KC Middle'),
        mpf.make_addplot(df['kc_lower'], color='red', linestyle='--', alpha=0.7, label='KC Lower')
    ]
    
    # Combine all addplots
    all_apds = kc_plots + apds
    
    # Plot
    fig, axes = mpf.plot(
        df,
        type='candle',
        volume=False,
        addplot=all_apds,
        figratio=(12, 8),
        figscale=1.2,
        style='charles',
        returnfig=True
    )
    
    # Add titles
    axes[0].set_title(f'{SYMBOL} Price with Indicators and Keltner Channel')
    axes[0].legend()
    
    # Save chart
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    return save_path

def analyze_keltner_channel(df):
    """
    Analyze Keltner Channel and generate trading signals
    """
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest
    
    current_price = latest['close']
    kc_upper = latest['kc_upper']
    kc_middle = latest['kc_middle']
    kc_lower = latest['kc_lower']
    
    # Determine position relative to Keltner Channel
    channel_position = "MIDDLE"
    if current_price >= kc_upper * 0.98:  # Near upper channel
        channel_position = "UPPER"
    elif current_price <= kc_lower * 1.02:  # Near lower channel
        channel_position = "LOWER"
    
    # Determine trend based on EMA slope
    trend = "NEUTRAL"
    if len(df) > 2:
        ema_current = latest['kc_middle']
        ema_prev = prev['kc_middle']
        if ema_current > ema_prev:
            trend = "UPTREND"
        elif ema_current < ema_prev:
            trend = "DOWNTREND"
    
    # Check for squeeze (narrow channel)
    channel_width = kc_upper - kc_lower
    avg_channel_width = (df['kc_upper'] - df['kc_lower']).rolling(20).mean().iloc[-1]
    is_squeeze = channel_width < avg_channel_width * 0.7
    
    # Generate analysis text
    analysis = f"""
Keltner Channel Analysis:
- Current Trend: {trend}
- Channel Position: {channel_position}
- Current Price: ${current_price:.2f}
- KC Middle (EMA{KC_WINDOW}): ${kc_middle:.2f}
- KC Upper: ${kc_upper:.2f}
- KC Lower: ${kc_lower:.2f}
- Channel Width: ${channel_width:.2f}
- Volatility Squeeze: {'Yes' if is_squeeze else 'No'}

Trading Signals:
- BUY when price touches lower band in uptrend
- SELL when price touches upper band in downtrend
- BREAKOUT trades when price moves outside channel with volume
- SQUEEZE indicates potential volatility expansion

Current Recommendation:
Based on {trend} trend and {channel_position} channel position.
"""
    
    return analysis, trend, channel_position, is_squeeze

class TradingAgent:
    def __init__(self):
        self.portfolio = {'usdt': 10000, 'btc': 0}
        self.trade_history = []
    
    def run_analysis(self):
        """
        Main method to fetch data, calculate indicators, and generate analysis
        """
        print("Fetching data from Redis...")
        try:
            df = fetch_data_from_redis()
            print(f"Data fetched successfully. Shape: {df.shape}")
        except Exception as e:
            print(f"Error fetching data: {e}")
            return {
                'data': None,
                'chart_path': None,
                'analysis': "Data fetch failed",
                'decision': {'action': 'HOLD', 'confidence': 0.5, 'reason': ['Data fetch error']}
            }
        
        print("Calculating indicators...")
        df = calculate_indicators(df)
        print("Indicators calculated.")
        
        print("Creating chart...")
        chart_path = create_chart(df)
        print(f"Chart created: {chart_path}")
        
        print("Analyzing Keltner Channel...")
        analysis, trend, channel_position, is_squeeze = analyze_keltner_channel(df)
        print("Keltner Channel analysis completed.")
        
        print("Making trading decision...")
        decision = self.make_trading_decision(df, trend, channel_position, is_squeeze)
        print("Decision made.")
        
        return {
            'data': df,
            'chart_path': chart_path,
            'analysis': analysis,
            'decision': decision
        }
    
    def make_trading_decision(self, df, trend, channel_position, is_squeeze):
        """
        Make trading decision based on Keltner Channel and technical indicators
        """
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        
        # Initialize decision
        decision = {
            'action': 'HOLD',
            'confidence': 0.5,
            'reason': []
        }
        
        # Keltner Channel based signals
        current_price = latest['close']
        kc_upper = latest['kc_upper']
        kc_lower = latest['kc_lower']
        
        # Breakout signals
        if current_price > kc_upper and prev['close'] <= prev['kc_upper']:
            decision['action'] = 'BUY'
            decision['confidence'] += 0.3
            decision['reason'].append('Breakout above upper Keltner Channel')
        
        elif current_price < kc_lower and prev['close'] >= prev['kc_lower']:
            decision['action'] = 'SELL'
            decision['confidence'] += 0.3
            decision['reason'].append('Breakout below lower Keltner Channel')
        
        # Mean reversion signals
        elif trend == "UPTREND" and channel_position == "LOWER":
            decision['action'] = 'BUY'
            decision['confidence'] += 0.25
            decision['reason'].append('Buy at lower channel in uptrend')
        
        elif trend == "DOWNTREND" and channel_position == "UPPER":
            decision['action'] = 'SELL'
            decision['confidence'] += 0.25
            decision['reason'].append('Sell at upper channel in downtrend')
        
        # Squeeze breakout anticipation
        if is_squeeze:
            decision['confidence'] += 0.15
            decision['reason'].append('Volatility squeeze detected - expect breakout')
        
        # RSI-based signals
        if latest['rsi'] < 30:
            if decision['action'] == 'HOLD':
                decision['action'] = 'BUY'
            decision['confidence'] += 0.2
            decision['reason'].append('Oversold based on RSI')
        elif latest['rsi'] > 70:
            if decision['action'] == 'HOLD':
                decision['action'] = 'SELL'
            decision['confidence'] += 0.2
            decision['reason'].append('Overbought based on RSI')
        
        # MACD-based signals
        if latest['macd'] > latest['macd_signal'] and prev['macd'] <= prev['macd_signal']:
            if decision['action'] == 'HOLD':
                decision['action'] = 'BUY'
            decision['confidence'] += 0.15
            decision['reason'].append('MACD crossover above signal line')
        elif latest['macd'] < latest['macd_signal'] and prev['macd'] >= prev['macd_signal']:
            if decision['action'] == 'HOLD':
                decision['action'] = 'SELL'
            decision['confidence'] += 0.15
            decision['reason'].append('MACD crossover below signal line')
        
        # Volume confirmation
        volume_avg = df['volume'].rolling(20).mean().iloc[-1]
        if latest['volume'] > volume_avg * 1.5:
            decision['confidence'] += 0.1
            decision['reason'].append('High volume confirmation')
        elif latest['volume'] < volume_avg * 0.5:
            decision['confidence'] -= 0.1
            decision['reason'].append('Low volume - weak signal')
        
        # Cap confidence between 0.1 and 0.95
        decision['confidence'] = max(0.1, min(decision['confidence'], 0.95))
        
        return decision
    
    def execute_trade(self, decision, current_price):
        """
        Execute trade based on decision
        """
        if decision['action'] == 'BUY' and self.portfolio['usdt'] > 10:
            # Buy with 50% of available USDT
            amount = (self.portfolio['usdt'] * 0.5) / current_price
            self.portfolio['btc'] += amount
            self.portfolio['usdt'] -= amount * current_price
            self.trade_history.append({
                'action': 'BUY',
                'amount': amount,
                'price': current_price,
                'timestamp': datetime.now()
            })
        
        elif decision['action'] == 'SELL' and self.portfolio['btc'] > 0:
            # Sell 50% of BTC holdings
            amount = self.portfolio['btc'] * 0.5
            self.portfolio['usdt'] += amount * current_price
            self.portfolio['btc'] -= amount
            self.trade_history.append({
                'action': 'SELL',
                'amount': amount,
                'price': current_price,
                'timestamp': datetime.now()
            })


def generate_trading_signals(df):
    """
    Generate optimized trading signals based on Keltner Channel strategy
    with improved risk management and trend confirmation
    """
    signals = pd.DataFrame(index=df.index)
    signals['price'] = df['close']
    signals['kc_upper'] = df['kc_upper']
    signals['kc_middle'] = df['kc_middle']
    signals['kc_lower'] = df['kc_lower']
    signals['rsi'] = df['rsi']
    signals['macd'] = df['macd']
    signals['macd_signal'] = df['macd_signal']
    signals['volume'] = df['volume']
    
    # Calculate additional indicators for confirmation
    signals['ema_20'] = df['close'].ewm(span=20).mean()
    signals['ema_50'] = df['close'].ewm(span=50).mean()
    signals['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
    signals['volume_sma'] = df['volume'].rolling(20).mean()
    
    # Initialize signals
    signals['signal'] = 0
    signals['position'] = 0
    signals['stop_loss'] = 0.0
    signals['take_profit'] = 0.0
    signals['risk_reward'] = 0.0
    
    # Trading rules with improved filters
    for i in range(20, len(signals)):  # Start from index 20 to have enough data for indicators
        current = signals.iloc[i]
        previous = signals.iloc[i-1]
        
        # Determine trend direction
        is_uptrend = current['ema_20'] > current['ema_50']
        is_downtrend = current['ema_20'] < current['ema_50']
        
        # Volume confirmation
        volume_ok = current['volume'] > current['volume_sma'] * 1.2
        
        # MACD confirmation
        macd_bullish = current['macd'] > current['macd_signal']
        macd_bearish = current['macd'] < current['macd_signal']
        
        # BUY Signals - Only in uptrend or neutral with strong confirmation
        if (current['price'] > current['kc_middle'] and 
            previous['price'] <= previous['kc_middle'] and 
            current['rsi'] > 50 and
            volume_ok and
            macd_bullish and
            (is_uptrend or current['rsi'] < 70)):  # Avoid overbought in uptrend
            
            signals.loc[signals.index[i], 'signal'] = 1  # BUY
            # Use ATR-based stop loss
            atr_stop = current['atr'] * 1.5
            stop_loss = max(current['kc_lower'], current['price'] - atr_stop)
            signals.loc[signals.index[i], 'stop_loss'] = stop_loss
            # Set take profit with 1:2 risk-reward ratio
            risk = current['price'] - stop_loss
            signals.loc[signals.index[i], 'take_profit'] = current['price'] + risk * 2
            signals.loc[signals.index[i], 'risk_reward'] = 2.0
        
        # SELL Signals - Only in downtrend or for profit taking
        elif (current['price'] < current['kc_middle'] and 
              previous['price'] >= previous['kc_middle'] and 
              current['rsi'] < 50 and
              volume_ok and
              macd_bearish and
              (is_downtrend or current['rsi'] > 30)):  # Avoid oversold in downtrend
            
            signals.loc[signals.index[i], 'signal'] = -1  # SELL/Close
        
        # Oversold bounce BUY with stronger confirmation
        elif (current['price'] <= current['kc_lower'] * 1.01 and 
              current['rsi'] < 35 and 
              current['volume'] > current['volume_sma'] * 1.5 and
              macd_bullish and
              is_uptrend):  # Only in uptrend for safety
            
            signals.loc[signals.index[i], 'signal'] = 1  # BUY
            # Use ATR-based stop loss
            atr_stop = current['atr'] * 2
            stop_loss = current['price'] - atr_stop
            signals.loc[signals.index[i], 'stop_loss'] = stop_loss
            # Set take profit at middle channel
            signals.loc[signals.index[i], 'take_profit'] = current['kc_middle']
            signals.loc[signals.index[i], 'risk_reward'] = 1.5
    
    return signals

def execute_strategy(account_balance=10000):
    """
    Main strategy execution function
    """
    # Fetch data
    df = fetch_data_from_redis()
    df = calculate_indicators(df)
    
    signals = generate_trading_signals(df)
    
    # Track positions
    position = 0
    entry_price = 0
    stop_loss = 0
    take_profit = 0
    
    for i, signal in enumerate(signals['signal']):
        current_price = signals['price'].iloc[i]
        
        if signal == 1 and position == 0:  # BUY signal, no position
            position_size = calculate_position_size(account_balance, current_price, signals['stop_loss'].iloc[i])
            position = position_size
            entry_price = current_price
            stop_loss = signals['stop_loss'].iloc[i]
            take_profit = signals['take_profit'].iloc[i]
            print(f"BUY {position_size} at {current_price}, SL: {stop_loss}, TP: {take_profit}")
        
        elif signal == -1 and position > 0:  # SELL signal, have position
            profit = (current_price - entry_price) * position
            account_balance += profit
            print(f"SELL at {current_price}, Profit: {profit}")
            position = 0
        
        # Check stop loss and take profit
        elif position > 0:
            if current_price <= stop_loss:
                loss = (current_price - entry_price) * position
                account_balance += loss
                print(f"Stop Loss triggered at {current_price}, Loss: {loss}")
                position = 0
            elif current_price >= take_profit:
                profit = (current_price - entry_price) * position
                account_balance += profit
                print(f"Take Profit hit at {current_price}, Profit: {profit}")
                position = 0
            else:
                # Update trailing stop
                new_stop = trailing_stop_loss(current_price, max(entry_price, current_price))
                stop_loss = max(stop_loss, new_stop)  # Only move stop up for long positions
    
    return account_balance

def calculate_position_size(account_balance, entry_price, stop_loss_price):
    """Calculate position size based on 2% risk rule"""
    risk_per_trade = account_balance * 0.02
    price_risk = abs(entry_price - stop_loss_price)
    position_size = risk_per_trade / price_risk
    return position_size

def trailing_stop_loss(current_price, highest_price, trail_percent=2):
    """Dynamic trailing stop loss"""
    return highest_price * (1 - trail_percent/100)


if __name__ == "__main__":
    # Initialize trading agent
    agent = TradingAgent()
    
    # Run analysis
    try:
        result = agent.run_analysis()
        
        # Display results
        print("=== BTC/USDT Trading Analysis ===")
        print(f"Current Price: ${result['data']['close'].iloc[-1]:.2f}")
        print(f"RSI: {result['data']['rsi'].iloc[-1]:.2f}")
        print(f"Stochastic RSI: {result['data']['stoch_rsi'].iloc[-1]:.2f}")
        print(f"MACD: {result['data']['macd'].iloc[-1]:.4f}")
        print(f"Volume: {result['data']['volume'].iloc[-1]:.2f}")
        print(f"KC Middle: ${result['data']['kc_middle'].iloc[-1]:.2f}")
        print(f"KC Upper: ${result['data']['kc_upper'].iloc[-1]:.2f}")
        print(f"KC Lower: ${result['data']['kc_lower'].iloc[-1]:.2f}")
        
        print("\n=== Trading Decision ===")
        print(f"Action: {result['decision']['action']}")
        print(f"Confidence: {result['decision']['confidence']:.2f}")
        print("Reasons:")
        for reason in result['decision']['reason']:
            print(f"- {reason}")
        
        print("\n=== Analysis Results ===")
        print(result['analysis'])
        
        print(f"\nChart saved to: {result['chart_path']}")
        
        # Execute strategy simulation
        print("\n=== Strategy Execution Simulation ===")
        final_balance = execute_strategy(account_balance=10000)
        print(f"Final account balance after strategy execution: ${final_balance:.2f}")
        
    except Exception as e:
        print(f"Error running analysis: {e}")
        import traceback
        traceback.print_exc()
