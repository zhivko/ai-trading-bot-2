
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timedelta
import time
from pybit.unified_trading import HTTP
import plotly.graph_objects as go
import google.generativeai as genai
import os
from PIL import Image
import io
import json
from scipy.signal import find_peaks

# 1. Fetch Data
def fetch_data():
    session = HTTP(testnet=False)
    end_time = datetime.now()
    start_time = end_time - timedelta(days=180)
    
    end_timestamp = int(time.mktime(end_time.timetuple())) * 1000
    start_timestamp = int(time.mktime(start_time.timetuple())) * 1000

    response = session.get_kline(
        category="spot",
        symbol="BTCUSDT",
        interval="D",
        start=start_timestamp,
        end=end_timestamp,
    )

    data = response['result']['list']
    df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df = df.set_index('timestamp')
    df = df.astype(float)
    df = df.iloc[::-1] # Reverse the dataframe to have the latest data at the end
    df.to_csv('btcusdt_daily.csv')
    return df

# 2. Add Indicators
def add_indicators(df):
    df.ta.rsi(length=14, append=True)
    df.ta.stochrsi(length=14, rsi_length=14, k=3, d=3, append=True)
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    df.ta.bbands(length=20, std=2, append=True)
    return df

# 3. Add Previous Day's Prices
def add_previous_days_prices(df):
    for i in range(1, 16):
        df[f'close_prev_{i}'] = df['close'].shift(i)
    return df

# 4. Normalize Indicator Columns
def normalize_indicators(df):
    # Exclude RSI from normalization as it's already in a 0-100 range
    indicator_cols = [col for col in df.columns if ('MACD' in col or 'BBL' in col or 'BBM' in col or 'BBU' in col) and 'RSI' not in col]
    for col in indicator_cols:
        df[col] = (df[col] - df[col].min()) / (df[col].max() - df[col].min())
    return df

# This function is no longer used for the specific user-defined pattern
# def find_bullish_reversal(df, window=30, start_index=0):
#     for i in range(start_index + window, len(df)):
#         price_window = df['close'].iloc[i-window:i]
#         rsi_window = df['RSI_14'].iloc[i-window:i]

#         price_low_indices, _ = find_peaks(-price_window.values)
#         rsi_high_indices, _ = find_peaks(rsi_window.values)

#         if len(price_low_indices) >= 2 and len(rsi_high_indices) >= 2:
#             price_two_lows = price_window.iloc[price_low_indices[-2:]]
#             rsi_two_highs = rsi_window.iloc[rsi_high_indices[-2:]]

#             is_price_falling = price_two_lows.values[1] < price_two_lows.values[0]
#             is_rsi_rising = rsi_two_highs.values[1] > rsi_two_highs.values[0]

#             if is_price_falling and is_rsi_rising:
#                 return price_window, rsi_window, price_two_lows, rsi_two_highs, i
                
#     return None, None, None, None, len(df)

def draw_plotly_image_with_specific_lines(df_period, price_line_coords, rsi_line_coords):
    fig = go.Figure()

    # ONLY PLOT RAW RSI FOR DEBUGGING
    fig.add_trace(go.Scatter(x=df_period.index, y=df_period['RSI_14'], mode='lines', name='RSI (Raw)', opacity=1.0, yaxis='y2'))

    # Calculate y-axis ranges for price (still needed for layout, even if not plotting price raw data)
    price_min = min(df_period['close'].min(), price_line_coords["start_price"], price_line_coords["end_price"]) * 0.95
    price_max = max(df_period['close'].max(), price_line_coords["start_price"], price_line_coords["end_price"]) * 1.05

    fig.update_layout(
        title='RSI Raw Data Debugging',
        xaxis_title='Date',
        yaxis=dict(title='Price (Placeholder)', range=[price_min, price_max], side='left', anchor='x'),
        yaxis2=dict(title='RSI', overlaying='y', side='right', range=[0, 100], anchor='x'), # Explicitly set RSI range to 0-100
        xaxis_tickformat='%Y-%m-%d'  # Human-readable date format
    )
    
    img_bytes = fig.to_image(format="png")
    fig.write_html("bullish_reversal.html") # Save as HTML for debugging

    # Print calculated y-axis ranges for debugging
    print(f"Price Y-axis Range: [{price_min}, {price_max}]")
    print(f"RSI Y-axis Range (fixed): [0, 100]")
    print(f"df_period.index dtype: {df_period.index.dtype}")
    print(f"df_period['RSI_14'] dtype: {df_period['RSI_14'].dtype}")

    try:
        import kaleido
    except ImportError:
        print("Warning: kaleido not found. PNG image generation might fail. Please install it using: pip install kaleido")

    return img_bytes

def ask_gemini(image_bytes):
    with open("c:/git/VidWebServer/authcreds.json", "r", encoding="utf-8") as f:
        creds = json.load(f)
        gemini_api_key = creds["GEMINI_API_KEY"]

    genai.configure(api_key=gemini_api_key)
    
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
    
    image = Image.open(io.BytesIO(image_bytes))
    
    response = model.generate_content([
        "Analyze the attached image. Describe the price trend line and the RSI trend line. Based on these two lines, does the image show a bullish reversal pattern? Explain your reasoning.",
        image
    ])
    
    return response.text.strip().lower()

if __name__ == '__main__':
    df = fetch_data()
    df = add_indicators(df)
    df = add_previous_days_prices(df)
    df = normalize_indicators(df)
    df.to_csv('btcusdt_daily_with_indicators.csv')
    print("Data with indicators saved to btcusdt_daily_with_indicators.csv")

    # User-provided drawing coordinates
    price_line_coords = {
        "start_time": 1737210002,
        "end_time": 1745275483,
        "start_price": 109886.34637739029,
        "end_price": 79719.01831265265
    }
    rsi_line_coords = {
        "start_time": 1740345912,
        "end_time": 1744333470,
        "start_price": 23.157954323770944,
        "end_price": 34.750380503549074
    }

    # Determine the overall time window for plotting raw data
    overall_start_time = min(price_line_coords["start_time"], rsi_line_coords["start_time"])
    overall_end_time = max(price_line_coords["end_time"], rsi_line_coords["end_time"])

    # Convert timestamps to datetime objects for filtering
    overall_start_dt = datetime.fromtimestamp(overall_start_time)
    overall_end_dt = datetime.fromtimestamp(overall_end_time)

    print(f"Plotting raw data from: {overall_start_dt.strftime('%Y-%m-%d')} to {overall_end_dt.strftime('%Y-%m-%d')}")
    print(f"Price Line: Start Time: {datetime.fromtimestamp(price_line_coords["start_time"]).strftime('%Y-%m-%d %H:%M:%S')}, Start Price: {price_line_coords["start_price"]}, End Time: {datetime.fromtimestamp(price_line_coords["end_time"]).strftime('%Y-%m-%d %H:%M:%S')}, End Price: {price_line_coords["end_price"]}")
    print(f"RSI Line: Start Time: {datetime.fromtimestamp(rsi_line_coords["start_time"]).strftime('%Y-%m-%d %H:%M:%S')}, Start Price: {rsi_line_coords["start_price"]}, End Time: {datetime.fromtimestamp(rsi_line_coords["end_time"]).strftime('%Y-%m-%d %H:%M:%S')}, End Price: {rsi_line_coords["end_price"]}")

    # Filter the DataFrame to the relevant period
    df_period = df.loc[(df.index >= overall_start_dt) & (df.index <= overall_end_dt)]

    if not df_period.empty:
        image_bytes = draw_plotly_image_with_specific_lines(df_period, price_line_coords, rsi_line_coords)
        with open("bullish_reversal.png", "wb") as f:
            f.write(image_bytes)
        print("Successfully generated bullish_reversal.png and bullish_reversal.html with your specified lines.")
        
        gemini_answer = ask_gemini(image_bytes)
        print(f"Gemini says: {gemini_answer}")
    else:
        print("No data available for the specified time range to plot.")
