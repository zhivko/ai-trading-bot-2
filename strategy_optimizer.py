import re
import sys
import time
import io
from PIL import Image # For displaying image
import matplotlib.pyplot as plt
import numpy as np # Import numpy for array operations
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd
import pandas_ta as ta
import google.generativeai as genai
from redis.asyncio import Redis as AsyncRedis
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from redis.exceptions import ConnectionError as RedisConnectionError
import logging
import asyncio
import json

# Import necessary functions and constants from AppTradingView
# Assuming AppTradingView.py is in the same directory or accessible via PYTHONPATH
from AppTradingView import get_sorted_set_key, get_sorted_set_oi_key, get_cached_open_interest, calculate_macd, calculate_rsi, calculate_stoch_rsi, calculate_open_interest, _prepare_dataframe, AVAILABLE_INDICATORS, get_cached_klines # Removed fetch_ohlcv_and_oi_from_redis, added get_cached_klines
# Import divergence functions from detectBulishDivergence.py (no change needed here)
from detectBulishDivergence import find_bullish_divergences, plot_divergences

# --- Configuration ---
GEMINI_API_KEY = "YOUR_GEMINI_API_KEY" # Your key
REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_PASSWORD = None # Set if you have a password
REDIS_TIMEOUT = 10

TARGET_SYMBOL = "BTCUSDT"
TARGET_RESOLUTION = "1d" # Default for plotting 6 months of 1d data
BACKTEST_DAYS = 180 # Approximately 6 months

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("StrategyOptimizer")

# --- Redis Connection ---
redis_client_instance: AsyncRedis | None = None

async def init_redis() -> AsyncRedis:
    """Initialize Redis connection."""
    global redis_client_instance
    try:
        redis_client_instance = AsyncRedis (
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            decode_responses=True,
            socket_timeout=REDIS_TIMEOUT,
            retry_on_timeout=True # Enable retrying on socket timeouts
        )
        await redis_client_instance.ping()
        logger.info("Successfully connected to Redis.")
        return redis_client_instance
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        logger.error("Run this to start it on wsl2: cmd /c wsl --exec sudo service redis-server start && Exit /B 5")
        redis_client_instance = None
        raise

async def get_redis_connection() -> AsyncRedis:
    """Get a Redis connection."""
    global redis_client_instance
    if redis_client_instance is None:
        try:
            redis_client_instance = await init_redis()
        except Exception: 
            logger.critical("CRITICAL: Redis connection could not be established in get_redis_connection.")
            logger.critical("Run this to start it on wsl2: cmd /c wsl --exec sudo service redis-server start && Exit /B 5")
            raise 
    if redis_client_instance is None: 
        raise Exception("Redis client is None after attempting initialization.")
    return redis_client_instance

def get_sorted_set_key(symbol: str, resolution: str) -> str: # From AppTradingView
    return f"zset:kline:{symbol}:{resolution}"

def plot_data_with_indicators(df: pd.DataFrame, filename: str = "chart_with_indicators.png"):
    """
    Plots candlestick chart with MACD, RSI, Stochastic RSI, and Open Interest. Saves the plot to a file and returns the filename.
    """
    if df.empty:
        logger.warning("DataFrame is empty, cannot plot.")
        return

    # Ensure 'timestamp' is datetime for plotting
    if not isinstance(df.index, pd.DatetimeIndex):
        if 'timestamp' in df.columns:
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
            df.set_index('datetime', inplace=True)
        else:
            logger.error("DataFrame must have a 'timestamp' column or DatetimeIndex for plotting.") # type: ignore
            return

    # Create subplots
    # 5 rows: Price, MACD, RSI, StochRSI, Open Interest
    fig = make_subplots(rows=5, cols=1, shared_xaxes=True,
                        vertical_spacing=0.05,
                        row_heights=[0.4, 0.15, 0.15, 0.15, 0.15])

    # Plot Candlestick
    fig.add_trace(go.Candlestick(x=df.index,
                                 open=df['open'],
                                 high=df['high'],
                                 low=df['low'],
                                 close=df['close'],
                                 name='Price'), row=1, col=1)
    fig.update_yaxes(title_text="Price", row=1, col=1)

    # Plot MACD
    macd_col = f'MACD_{12}_{26}_{9}' # Assuming default MACD params
    macds_col = f'MACDs_{12}_{26}_{9}'
    macdh_col = f'MACDh_{12}_{26}_{9}'
    if macd_col in df.columns and macds_col in df.columns and macdh_col in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df[macd_col], mode='lines', name='MACD', line=dict(color='blue')), row=2, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df[macds_col], mode='lines', name='Signal', line=dict(color='red')), row=2, col=1)
        fig.add_trace(go.Bar(x=df.index, y=df[macdh_col], name='Histogram', marker_color='green'), row=2, col=1)
        fig.update_yaxes(title_text="MACD", row=2, col=1)
    else:
        logger.warning(f"MACD columns not found for plotting: {macd_col}, {macds_col}, {macdh_col}")

    # Plot RSI
    rsi_col = f'RSI_{14}' # Assuming default RSI period
    if rsi_col in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df[rsi_col], mode='lines', name='RSI', line=dict(color='purple')), row=3, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="gray", row=3, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="gray", row=3, col=1)
        fig.update_yaxes(title_text="RSI", range=[0, 100], row=3, col=1)
    else:
        logger.warning(f"RSI column not found for plotting: {rsi_col}")

    # Plot Stochastic RSI (using the slowest one, 60_60_10_10)
    stochrsi_k_col = f'STOCHRSIk_60_60_10_10'
    stochrsi_d_col = f'STOCHRSId_60_60_10_10'
    if stochrsi_k_col in df.columns and stochrsi_d_col in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df[stochrsi_k_col], mode='lines', name='StochRSI %K', line=dict(color='orange')), row=4, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df[stochrsi_d_col], mode='lines', name='StochRSI %D', line=dict(color='teal')), row=4, col=1)
        fig.add_hline(y=80, line_dash="dash", line_color="gray", row=4, col=1)
        fig.add_hline(y=20, line_dash="dash", line_color="gray", row=4, col=1)
        fig.update_yaxes(title_text="StochRSI", range=[0, 100], row=4, col=1)
    else:
        logger.warning(f"StochRSI columns not found for plotting: {stochrsi_k_col}, {stochrsi_d_col}")

    # Plot Open Interest
    if 'open_interest' in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df['open_interest'], mode='lines', name='Open Interest', line=dict(color='brown')), row=5, col=1)
        fig.update_yaxes(title_text="Open Interest", row=5, col=1)
    else:
        logger.warning("Open Interest column not found for plotting.")

    fig.update_layout(title_text=f'{df.index.min().strftime("%Y-%m-%d")} to {df.index.max().strftime("%Y-%m-%d")} - BTCUSDT 1D with Indicators',
                      xaxis_rangeslider_visible=False,
                      height=1400, width=1800, # Already large, but ensuring scale is applied
                      xaxis=dict(tickformat="%Y-%m-%d")) # Explicit date format
    fig.write_image(filename, scale=2) # Added scale=2 for higher resolution
    logger.info(f"Main chart saved to {filename}")
    return filename


async def main():
    logger.info("===== Starting Strategy Optimizer (Plotting Mode) =====")

    # Configure Gemini API key globally
    genai.configure(api_key=GEMINI_API_KEY)

    redis_conn = await get_redis_connection()
    if not redis_conn:
        logger.critical("CRITICAL: No Redis connection. Exiting.")
        return

    # Set parameters for 6 months of 1d data
    # TARGET_RESOLUTION and BACKTEST_DAYS are defined globally


    to_dt = datetime.now(timezone.utc)
    from_dt = to_dt - timedelta(days=BACKTEST_DAYS)
    from_ts = int(from_dt.timestamp())
    to_ts = int(to_dt.timestamp())

    logger.info(f"Fetching {BACKTEST_DAYS} days of {TARGET_SYMBOL} {TARGET_RESOLUTION} data from {from_dt.strftime('%Y-%m-%d')} to {to_dt.strftime('%Y-%m-%d')}")

    klines_list_of_dicts = await get_cached_klines(TARGET_SYMBOL, TARGET_RESOLUTION, from_ts, to_ts)
    oi_list_of_dicts = await get_cached_open_interest(TARGET_SYMBOL, TARGET_RESOLUTION, from_ts, to_ts)
    
    if not klines_list_of_dicts:
        logger.error("No historical kline data fetched. Exiting.")
        return
    
    # klines_list_of_dicts and oi_list_of_dicts are already lists of dicts
    # No need for .to_dict(orient='records')
    # Pass oi_list_of_dicts as an empty list if it's None
    df_ohlcv = _prepare_dataframe(klines_list_of_dicts, oi_list_of_dicts)
    
    if df_ohlcv is None or df_ohlcv.empty:
        logger.error("DataFrame preparation failed. Exiting.")
        return

    # Calculate all 4 indicators
    # MACD
    df_ohlcv.ta.macd(fast=12, slow=26, signal=9, append=True)
    # RSI
    df_ohlcv.ta.rsi(length=14, append=True)
    # Stochastic RSI (using the slowest one, 60_60_10_10)
    df_ohlcv.ta.stochrsi(rsi_length=60, length=60, k=10, d=10, append=True)
    # Open Interest is already merged and named 'open_interest'

    # Drop any rows with NaN values that result from indicator calculations
    df_ohlcv.dropna(inplace=True)
    if df_ohlcv.empty:
        logger.error("DataFrame became empty after indicator calculations and dropna. Not enough data for indicators.")
        return

    logger.info(f"DataFrame shape after indicator calculation and dropna: {df_ohlcv.shape}")

    # Initialize figure and subplots ONCE outside the loop
    fig, axes = plt.subplots(1, 2, figsize=(20, 10))
    plt.show(block=False) # Show the figure once, non-blocking

    # Initialize image holders with placeholder data
    # These will be updated in the loop
    im1 = axes[0].imshow(np.zeros((10, 10, 3))) # Placeholder image
    im2 = axes[1].imshow(np.zeros((10, 10, 3))) # Placeholder image

    # Set initial titles and turn off axes
    axes[0].set_title("Main Indicators Chart")
    axes[0].axis('off')
    axes[1].set_title("Bullish Divergences")
    axes[1].axis('off')

    # Parameters for divergence detection (defined once outside the loop)
    rsi_period_div = 14
    price_prominence_factor_div = 0.01
    rsi_prominence_factor_div = 0.05
    min_points_between_troughs_div = 5
    max_time_diff_between_troughs_days_div = 30

    # Loop to display image
    # Loop to display images
    while True:
        # Plot main chart
        main_chart_filename = plot_data_with_indicators(df_ohlcv.copy(), filename="btcusdt_1d_indicators.png")
        
        # Update the main chart image
        img1_data = Image.open(main_chart_filename)
        im1.set_data(img1_data)
        # Update extent in case image dimensions change (though unlikely for fixed Plotly output)
        im1.set_extent([0, img1_data.width, img1_data.height, 0]) 
        axes[0].set_title("Main Indicators Chart") # Ensure title is present
        axes[0].axis('off') # Ensure axes are off

        # Detect and plot divergences
        divergences = await find_bullish_divergences(
            df_ohlcv.copy(),
            rsi_period=rsi_period_div,
            price_prominence_factor=price_prominence_factor_div,
            rsi_prominence_factor=rsi_prominence_factor_div,
            min_points_between_troughs=min_points_between_troughs_div,
            max_time_diff_between_troughs_days=max_time_diff_between_troughs_days_div
        )
        divergence_chart_filename = None
        if divergences:
            divergence_chart_filename = plot_divergences(df_ohlcv.copy(), divergences, rsi_period=rsi_period_div, filename="bullish_divergences.png") # type: ignore
        else:
            logger.info("No bullish divergences found for plotting.")

        # Display divergence chart
        if divergence_chart_filename:
            img2_data = Image.open(divergence_chart_filename)
            im2.set_data(img2_data)
            im2.set_extent([0, img2_data.width, img2_data.height, 0])
            axes[1].set_title("Bullish Divergences")
            axes[1].axis('off')
        else:
            # If no divergence, display "No Divergence" text
            im2.set_data(np.zeros((10, 10, 3))) # Clear image data
            axes[1].clear() # Clear axes to remove previous image and text
            axes[1].text(0.5, 0.5, "No Bullish Divergences Found", horizontalalignment='center', verticalalignment='center', transform=axes[1].transAxes, fontsize=14)
            axes[1].set_title("Bullish Divergences")
            axes[1].axis('off')

        fig.canvas.draw_idle() # Request a redraw of the canvas
        fig.canvas.flush_events() # Process events to update the display
        plt.pause(5) # Pause for 5 seconds, allowing matplotlib to update
        # No need for plt.close('all') as we are reusing the figure.

        logger.info("Displaying charts. Press Ctrl+C to stop.")
        try:
            # asyncio.sleep is not needed if plt.pause is used for blocking
            pass
        except asyncio.CancelledError:
            logger.info("Loop cancelled.")
            break
        except KeyboardInterrupt:
            logger.info("Loop interrupted by user.")
            break

    logger.info("===== Strategy Optimizer (Plotting Mode) Finished =====")

    if redis_conn:
        await redis_conn.close()
        logger.info("Redis connection closed.")

if __name__ == "__main__":
    asyncio.run(main())
