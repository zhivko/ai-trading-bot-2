import ccxt
import pandas as pd
from datetime import datetime, timedelta
import pandas_ta as ta
from scipy.signal import find_peaks
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- 1. CONFIGURATION ---
SYMBOL = 'BTC/USDT'
TIMEFRAME = '1d'
MONTHS_AGO = 6
CSV_FILENAME = 'btcusdt_daily_data.csv'
RSI_PERIOD = 14
PRICE_PEAK_COL = 'high'
RSI_COL_NAME = f'RSI_{RSI_PERIOD}'
RSI_OVERSOLD_LEVEL = 40

# --- 2. DATA FETCHING (No Changes) ---
def fetch_data(symbol, timeframe, months_ago):
    print(f"Fetching {timeframe} data for {symbol} for the last {months_ago} months...")
    try:
        exchange = ccxt.binance()
        since = exchange.parse8601((datetime.now() - timedelta(days=months_ago * 30)).strftime('%Y-%m-%dT%H:%M:%SZ'))
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        print(f"Successfully fetched {len(df)} data points.")
        return df
    except Exception as e:
        print(f"An error occurred during data fetching: {e}")
        return pd.DataFrame()

# --- 3. INDICATOR CALCULATION (No Changes) ---
def add_indicators(df):
    print("Adding technical indicators (RSI, Stoch RSI, MACD, Bollinger Bands)...")
    if df.empty: return df
    df.ta.rsi(length=RSI_PERIOD, append=True)
    df.ta.stochrsi(append=True)
    df.ta.macd(append=True)
    df.ta.bbands(append=True)
    df.dropna(inplace=True)
    print("Indicators added successfully.")
    return df

# --- 4. BULLISH DIVERGENCE DETECTION (No Changes) ---
def detect_bullish_divergence(df, price_col, rsi_col, rsi_oversold_level):
    print(f"Detecting all candidate divergences...")
    candidate_divergences = []
    
    price_peaks_indices, _ = find_peaks(df[price_col], distance=5, prominence=df[price_col].std() * 0.3)
    rsi_lows_indices, _ = find_peaks(-df[rsi_col], distance=5, prominence=df[rsi_col].std() * 0.3)

    for i in range(len(rsi_lows_indices) - 1):
        for j in range(i + 1, len(rsi_lows_indices)):
            r_low1_idx, r_low2_idx = rsi_lows_indices[i], rsi_lows_indices[j]

            if (df[rsi_col].iloc[r_low2_idx] > df[rsi_col].iloc[r_low1_idx] and
                df[rsi_col].iloc[r_low1_idx] < rsi_oversold_level):
                try:
                    search_window_1 = [p for p in price_peaks_indices if abs(p - r_low1_idx) < 10]
                    if not search_window_1: continue
                    p_peak1_idx = max(search_window_1, key=lambda p: df[price_col].iloc[p])

                    search_window_2 = [p for p in price_peaks_indices if abs(p - r_low2_idx) < 10]
                    if not search_window_2: continue
                    p_peak2_idx = max(search_window_2, key=lambda p: df[price_col].iloc[p])
                    
                    if p_peak1_idx >= p_peak2_idx: continue
                except (ValueError, IndexError):
                    continue

                if df[price_col].iloc[p_peak2_idx] < df[price_col].iloc[p_peak1_idx]:
                    divergence_info = {
                        "price_start_idx": p_peak1_idx, "price_end_idx": p_peak2_idx,
                        "rsi_start_idx": r_low1_idx, "rsi_end_idx": r_low2_idx,
                        "duration": r_low2_idx - r_low1_idx
                    }
                    candidate_divergences.append(divergence_info)

    if not candidate_divergences:
        print("No bullish divergence patterns found.")
        return []

    most_significant_divergence = max(candidate_divergences, key=lambda div: div['duration'])
    print(f"Found {len(candidate_divergences)} candidates. Selected the most significant one.")
    return [most_significant_divergence]

# --- 5. NEW: BREAKOUT DETECTION FUNCTION ---
def find_breakout_intersection(df, divergence_info):
    """
    Finds the first intersection of a future price bar with the extrapolated price trendline.
    
    Args:
        df (pd.DataFrame): The dataframe with OHLC data.
        divergence_info (dict): The dictionary for the single significant divergence.

    Returns:
        dict: A dictionary with the date, price, and index of the breakout, or None.
    """
    print("Searching for breakout point...")
    # Define the trendline using the original price peaks
    p_start_idx = divergence_info['price_start_idx']
    p_end_idx = divergence_info['price_end_idx']
    p_start_y = df[PRICE_PEAK_COL].iloc[p_start_idx]
    p_end_y = df[PRICE_PEAK_COL].iloc[p_end_idx]

    # Calculate slope (m) and y-intercept (b) for the line y = mx + b
    slope = (p_end_y - p_start_y) / (p_end_idx - p_start_idx)
    intercept = p_start_y - slope * p_start_idx

    # Start searching for a breakout *after* the divergence pattern completes
    search_start_idx = max(divergence_info['price_end_idx'], divergence_info['rsi_end_idx']) + 1
    
    for i in range(search_start_idx, len(df)):
        # Calculate the trendline's value at the current index 'i'
        trendline_value = slope * i + intercept
        
        # Check if the high of the current bar has crossed above the trendline
        if df[PRICE_PEAK_COL].iloc[i] > trendline_value:
            intersection_info = {
                "date": df.index[i],
                "price": trendline_value, # The price level of the trendline that was broken
                "index": i
            }
            print(f"Breakout found!")
            return intersection_info
            
    print("No breakout detected yet in the given data range.")
    return None

# --- HELPER FUNCTION (No Changes) ---
def extrapolate_line(start_idx, start_y, end_idx, end_y, new_idx):
    slope = (end_y - start_y) / (end_idx - start_idx)
    new_y = slope * (new_idx - start_idx) + start_y
    return new_y

# --- 6. PLOTTING (UPGRADED TO MARK INTERSECTION) ---
def plot_chart_with_divergence(df, divergences, symbol, intersection=None):
    print("Generating final plot...")
    # ... (rest of the function setup is the same)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3], subplot_titles=(f'{symbol} OHLC with Bollinger Bands', 'RSI'))
    fig.add_trace(go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='OHLC'), row=1, col=1)
    try:
        lower_band_col = [col for col in df.columns if col.startswith('BBL_')][0]
        upper_band_col = [col for col in df.columns if col.startswith('BBU_')][0]
        fig.add_trace(go.Scatter(x=df.index, y=df[lower_band_col], mode='lines', line=dict(color='blue', width=0.7), name='Lower BB'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df[upper_band_col], mode='lines', line=dict(color='blue', width=0.7), name='Upper BB'), row=1, col=1)
    except IndexError: print("Warning: Could not find Bollinger Band columns.")
    fig.add_trace(go.Scatter(x=df.index, y=df[RSI_COL_NAME], mode='lines', line=dict(color='purple', width=1.5), name='RSI'), row=2, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", line_width=1, row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", line_width=1, row=2, col=1)
    fig.add_hline(y=RSI_OVERSOLD_LEVEL, line_dash="dot", line_color="grey", line_width=1, row=2, col=1)
    
    div = divergences[0] # We know there's only one
    min_plot_idx = min(div['price_start_idx'], div['rsi_start_idx'])
    max_plot_idx = max(div['price_end_idx'], div['rsi_end_idx'])
    
    price_start_y_orig, price_end_y_orig = df[PRICE_PEAK_COL].iloc[div['price_start_idx']], df[PRICE_PEAK_COL].iloc[div['price_end_idx']]
    price_start_y_extrap = extrapolate_line(div['price_start_idx'], price_start_y_orig, div['price_end_idx'], price_end_y_orig, min_plot_idx)
    price_end_y_extrap = extrapolate_line(div['price_start_idx'], price_start_y_orig, div['price_end_idx'], price_end_y_orig, max_plot_idx)

    rsi_start_y_orig, rsi_end_y_orig = df[RSI_COL_NAME].iloc[div['rsi_start_idx']], df[RSI_COL_NAME].iloc[div['rsi_end_idx']]
    rsi_start_y_extrap = extrapolate_line(div['rsi_start_idx'], rsi_start_y_orig, div['rsi_end_idx'], rsi_end_y_orig, min_plot_idx)
    rsi_end_y_extrap = extrapolate_line(div['rsi_start_idx'], rsi_start_y_orig, div['rsi_end_idx'], rsi_end_y_orig, max_plot_idx)

    fig.add_shape(type="line", x0=df.index[min_plot_idx], y0=price_start_y_extrap, x1=df.index[max_plot_idx], y1=price_end_y_extrap, line=dict(color="red", width=2.5), xref="x1", yref="y1")
    fig.add_shape(type="line", x0=df.index[min_plot_idx], y0=rsi_start_y_extrap, x1=df.index[max_plot_idx], y1=rsi_end_y_extrap, line=dict(color="red", width=2.5), xref="x2", yref="y2")

    # --- ADD MARKER FOR INTERSECTION ---
    if intersection:
        fig.add_trace(go.Scatter(
            x=[intersection['date']],
            y=[intersection['price']],
            mode='markers',
            marker=dict(symbol='star', color='gold', size=15, line=dict(color='black', width=1)),
            name='Breakout Point'
        ), row=1, col=1)

    fig.update_layout(title_text=f'Significant Bullish Divergence and Breakout for {symbol}', height=800, showlegend=True, xaxis_rangeslider_visible=False)
    fig.update_yaxes(title_text="Price (USDT)", row=1, col=1)
    fig.update_yaxes(title_text="RSI Value", row=2, col=1)
    fig.show()

# --- 7. MAIN EXECUTION (MODIFIED TO CALL NEW FUNCTIONS) ---
if __name__ == "__main__":
    data = fetch_data(SYMBOL, TIMEFRAME, MONTHS_AGO)
    if not data.empty:
        data_with_indicators = add_indicators(data.copy())
        data_with_indicators.to_csv(CSV_FILENAME)
        print(f"Data with indicators saved to '{CSV_FILENAME}'")
        
        significant_divergence = detect_bullish_divergence(
            data_with_indicators, 
            price_col=PRICE_PEAK_COL, 
            rsi_col=RSI_COL_NAME,
            rsi_oversold_level=RSI_OVERSOLD_LEVEL
        )
        
        if significant_divergence:
            intersection_point = find_breakout_intersection(data_with_indicators, significant_divergence[0])
            
            # Print the final result to the console
            if intersection_point:
                print("\n--- BREAKOUT ANALYSIS COMPLETE ---")
                print(f"  > Trendline Breakout Date: {intersection_point['date'].strftime('%Y-%m-%d')}")
                print(f"  > Breakout Price Level:    ${intersection_point['price']:.2f}")
                print("----------------------------------\n")
            
            # Plot the chart with the breakout point marked
            # plot_chart_with_divergence(data_with_indicators, significant_divergence, SYMBOL, intersection=intersection_point)