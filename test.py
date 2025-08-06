import ccxt
import pandas as pd
import pandas_ta as ta

def get_buy_signals(symbol='BTC/USDT', timeframe='1h', limit=1000, window=10):
    """
    Fetches OHLCV data for the given symbol and timeframe, calculates indicators,
    and detects buy signals based on the interpreted conditions from the picture.
    
    Relaxed condition: All signals must be true at least once within a rolling window of 'window' bars (default 10).
    A buy signal is generated at the bar where this condition first becomes true (transition from False to True).
    
    Conditions:
    - MACD bullish crossover happened within last 'window' bars.
    - DMI (+DI crosses above -DI) happened within last 'window' bars.
    - Stochastic merging in oversold happened within last 'window' bars.
    - On 4H timeframe, CCI was oversold and rising happened within last 'window' bars.
    - Bullish trend (close > SuperTrend) happened within last 'window' bars.
    
    Returns a DataFrame with the data and a 'buy_signal' column (True at signal bars).
    Prints the timestamps where buy signals occur.
    """
    # Initialize exchange
    exchange = ccxt.binance()
    
    # Fetch OHLCV data
    bars = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    
    # Calculate indicators on current timeframe (1h)
    # MACD
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    df['macd'] = macd['MACD_12_26_9']
    df['macd_signal'] = macd['MACDs_12_26_9']
    
    # DMI/ADX
    dmi = ta.adx(df['high'], df['low'], df['close'], length=14)
    df['plus_di'] = dmi['DMP_14']
    df['minus_di'] = dmi['DMN_14']
    
    # Stochastic
    stoch = ta.stoch(df['high'], df['low'], df['close'], k=14, d=3, smooth_k=3)
    df['stoch_k'] = stoch['STOCHk_14_3_3']
    df['stoch_d'] = stoch['STOCHd_14_3_3']
    
    # SuperTrend for bullish trend
    supertrend = ta.supertrend(df['high'], df['low'], df['close'], length=10, multiplier=3)
    df['supertrend'] = supertrend['SUPERT_10_3.0']
    
    # Resample to 4H for multi-timeframe analysis
    df_4h = df.resample('4H').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    })
    
    # Calculate CCI on 4H
    df_4h['cci'] = ta.cci(df_4h['high'], df_4h['low'], df_4h['close'], length=20)
    
    # Reindex 4H CCI to 1H timestamps with ffill
    df['cci_4h'] = df_4h['cci'].reindex(df.index, method='ffill')
    
    # Define conditions
    # MACD bullish crossover
    df['macd_buy'] = (df['macd'] > df['macd_signal']) & (df['macd'].shift(1) <= df['macd_signal'].shift(1))
    
    # DMI bullish crossover
    df['dmi_buy'] = (df['plus_di'] > df['minus_di']) & (df['plus_di'].shift(1) <= df['minus_di'].shift(1))
    
    # Stochastic merging in oversold
    df['stoch_merge'] = (abs(df['stoch_k'] - df['stoch_d']) < 5) & (df['stoch_k'] < 20) & (df['stoch_d'] < 20)
    
    # Bullish trend
    df['bullish_trend'] = df['close'] > df['supertrend']
    
    # 4H CCI oversold and rising (detected at the 1H bar where 4H closes)
    df['cci_4h_change'] = df['cci_4h'] != df['cci_4h'].shift(1)
    df['cci_oversold_rising'] = df['cci_4h_change'] & (df['cci_4h'] > df['cci_4h'].shift(1)) & (df['cci_4h'].shift(1) < -100)
    
    # Relaxed conditions: any True in rolling window
    df['macd_buy_window'] = df['macd_buy'].rolling(window, min_periods=1).max().fillna(False)
    df['dmi_buy_window'] = df['dmi_buy'].rolling(window, min_periods=1).max().fillna(False)
    df['stoch_merge_window'] = df['stoch_merge'].rolling(window, min_periods=1).max().fillna(False)
    df['cci_oversold_rising_window'] = df['cci_oversold_rising'].rolling(window, min_periods=1).max().fillna(False)
    df['bullish_trend_window'] = df['bullish_trend'].rolling(window, min_periods=1).max().fillna(False)
    
    # All conditions met in the window
    df['all_met'] = (
        df['macd_buy_window'] &
        df['dmi_buy_window'] &
        df['stoch_merge_window'] &
        df['cci_oversold_rising_window'] &
        df['bullish_trend_window']
    )
    
    # Buy signal on transition to all_met True
    df['buy_signal'] = df['all_met'] & ~df['all_met'].shift(1).fillna(False)
    
    # Print buy signals
    buy_dates = df[df['buy_signal']].index
    if not buy_dates.empty:
        print("Buy signals detected at:")
        for date in buy_dates:
            print(date)
    else:
        print("No buy signals detected in the data.")
    
    return df

# Example usage
# df = get_buy_signals(symbol='BTC/USDT', timeframe='1h', limit=1000, window=10)
