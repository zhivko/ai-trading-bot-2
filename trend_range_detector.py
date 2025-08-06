import pandas as pd
import numpy as np
import pandas_ta as ta
from typing import List, Dict, Any
import warnings
from datetime import datetime, timezone
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Suppress pandas_ta warning
warnings.filterwarnings("ignore", category=UserWarning, module="pandas_ta")

# Supported resolutions (replace with `from config import SUPPORTED_RESOLUTIONS` if in a separate module)
SUPPORTED_RESOLUTIONS = ["1m", "5m", "1h", "1d", "1w"]

def trend_range_detector(
    df: pd.DataFrame,
    length: int = 50,
    mult: float = 2.0,
    highlight_break: bool = True
) -> List[Dict[str, Any]]:
    """
    Detects trend ranges in price data and returns a list of range boxes.
    """
    # Validate columns
    required_cols = ['high', 'low', 'close']
    if not all(col in df.columns for col in required_cols):
        raise ValueError(f"DataFrame must contain {required_cols} columns.")
    
    # Check for NaN or non-numeric values
    if df[required_cols].isnull().any().any():
        print("Warning: Dropping rows with NaN in high, low, or close.")
        df = df.dropna(subset=required_cols)
    if not all(df[col].apply(lambda x: isinstance(x, (int, float))).all() for col in required_cols):
        raise ValueError("Non-numeric values in high, low, or close columns.")
    
    # Check DataFrame length for ATR
    atr_length = 2000
    if len(df) < atr_length:
        print(f"Warning: DataFrame has {len(df)} rows, but ATR requires {atr_length} rows. Using {len(df)-1} instead.")
        atr_length = len(df) - 1
        if atr_length < 1:
            print("Error: Not enough data to compute ATR.")
            return []
    
    # Calculate ATR
    atr_series = ta.atr(high=df['high'], low=df['low'], close=df['close'], length=atr_length)
    if atr_series is None:
        print("Error: ATR calculation returned None.")
        return []
    df['atr'] = atr_series * mult

    # Calculate weighted moving average
    df['delta'] = (df['close'] - df['close'].shift(1)).abs()
    df['w'] = df['delta'] / df['close'].shift(1)
    df['weighted_sum'] = (df['close'] * df['w']).rolling(window=length).sum()
    df['sum_weights'] = df['w'].rolling(window=length).sum()
    df['ma'] = df['weighted_sum'] / df['sum_weights']

    # Calculate maximum distance from MA
    max_dist = np.full(len(df), np.nan)
    for t in range(length - 1, len(df)):
        window = df['close'].iloc[t - length + 1 : t + 1]
        ma_t = df['ma'].iloc[t]
        max_dist[t] = np.max(np.abs(window - ma_t))
    df['max_dist'] = max_dist

    # Determine if in range
    df['in_range'] = df['max_dist'] <= df['atr']

    # Detect new range starts
    df['new_box'] = (df['in_range'] & ~df['in_range'].shift(1).fillna(False)).infer_objects(copy=False).astype(bool)

    # Collect boxes
    boxes = []
    for t in range(length, len(df)):
        if df['new_box'].iloc[t]:
            start_idx = t - length
            end_idx = t
            top = df['ma'].iloc[end_idx] + df['atr'].iloc[end_idx]
            bottom = df['ma'].iloc[end_idx] - df['atr'].iloc[end_idx]
            box = {
                'start_time': df.index[start_idx],
                'end_time': df.index[end_idx],
                'top': top,
                'bottom': bottom
            }
            if highlight_break:
                break_status = 'none'
                check_range = df['close'].iloc[start_idx:end_idx + 1]
                if any(check_range > top):
                    break_status = 'up'
                elif any(check_range < bottom):
                    break_status = 'down'
                if end_idx + 5 < len(df):
                    post_range = df['close'].iloc[end_idx + 1:end_idx + 6]
                    if any(post_range > top) and break_status == 'none':
                        break_status = 'up'
                    elif any(post_range < bottom) and break_status == 'none':
                        break_status = 'down'
                box['break_status'] = break_status
            boxes.append(box)

    return boxes

def fetch_and_analyze(
    symbol: str,
    resolution: str,
    start_ts: int,
    end_ts: int,
    length: int = 50,
    mult: float = 2.0,
    highlight_break: bool = True
) -> List[Dict[str, Any]]:
    """
    Fetches historical data from Bybit's /history endpoint and runs the trend range detector.
    """
    # FastAPI endpoint URL
    base_url = "http://192.168.1.52:5000/history"

    # Validate resolution
    if resolution not in SUPPORTED_RESOLUTIONS:
        print(f"Error: Resolution {resolution} not in supported resolutions: {SUPPORTED_RESOLUTIONS}")
        return []

    # Paginate to fetch enough candles (Bybit typically limits to ~1000 candles)
    all_klines = []
    chunk_size = 1000 * 3600  # 1000 hours (~41.7 days)
    current_ts = start_ts
    while current_ts < end_ts:
        params = {
            "symbol": symbol,
            "resolution": resolution,  # Use resolution directly (e.g., '1h')
            "from_ts": current_ts,
            "to_ts": min(current_ts + chunk_size, end_ts)
        }
        try:
            response = requests.get(base_url, params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("s") != "ok":
                print(f"Error from /history: {data.get('errmsg', 'Unknown error')}")
                return []

            klines = [
                {
                    "time": t,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "vol": v
                }
                for t, o, h, l, c, v in zip(
                    data["t"], data["o"], data["h"], data["l"], data["c"], data["v"]
                )
            ]
            if not klines:
                print(f"No data returned for {symbol} {resolution} from {current_ts} to {min(current_ts + chunk_size, end_ts)}")
                break

            all_klines.extend(klines)
            current_ts = int(klines[-1]["time"]) + 3600  # Advance by 1 hour
            if len(klines) < 1000:  # Less than max candles, likely reached end
                break
        except requests.RequestException as e:
            print(f"HTTP error fetching klines: {e}")
            return []

    if not all_klines:
        print(f"No data fetched for {symbol} from {start_ts} to {end_ts}.")
        return []

    # Convert to DataFrame
    df = pd.DataFrame(all_klines)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('time', inplace=True)
    df.rename(columns={'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close', 'vol': 'volume'}, inplace=True)
    print("DataFrame head:\n", df.head())
    print("DataFrame length:", len(df))
    print("Data types:\n", df.dtypes)

    # Ensure numeric columns
    for col in ['high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    ranges = trend_range_detector(df, length, mult, highlight_break)
    return ranges

def plot_trend_ranges(df: pd.DataFrame, ranges: List[Dict[str, Any]], symbol: str) -> None:
    """
    Plots candlestick chart with range boxes using Plotly.
    """
    # Create candlestick chart
    fig = make_subplots(rows=1, cols=1, shared_xaxes=True)
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df['open'],
            high=df['high'],
            low=df['low'],
            close=df['close'],
            name=symbol
        )
    )

    # Add range boxes as rectangles
    for r in ranges:
        break_status = r.get('break_status', 'none')
        # Color-code based on break_status
        fill_color = (
            'rgba(0, 255, 0, 0.2)' if break_status == 'up' else
            'rgba(255, 0, 0, 0.2)' if break_status == 'down' else
            'rgba(0, 0, 255, 0.2)'
        )
        fig.add_shape(
            type="rect",
            x0=r['start_time'],
            x1=r['end_time'],
            y0=r['bottom'],
            y1=r['top'],
            fillcolor=fill_color,
            line=dict(color=fill_color.replace('0.2', '1.0'), width=2),
            opacity=0.3,
            layer="below"
        )

    # Update layout
    fig.update_layout(
        title=f"{symbol} Price with Trend Range Boxes",
        xaxis_title="Time",
        yaxis_title="Price",
        xaxis_rangeslider_visible=False,
        showlegend=True,
        template="plotly_dark"  # Use dark theme for visibility
    )

    # Show plot
    fig.show()

if __name__ == "__main__":
    symbol = "BTCUSDT"
    resolution = "1h"
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - pd.Timedelta(days=90)  # Fetch 90 days (~2160 rows)
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())
    ranges = fetch_and_analyze(symbol, resolution, start_ts, end_ts)
    if ranges:
        # Get DataFrame from fetch_and_analyze for plotting
        df = pd.DataFrame(fetch_and_analyze(symbol, resolution, start_ts, end_ts, return_df=True))
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('time', inplace=True)
        df.rename(columns={'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close', 'vol': 'volume'}, inplace=True)
        plot_trend_ranges(df, ranges, symbol)
    for r in ranges:
        print(f"Range from {r['start_time']} to {r['end_time']}, "
              f"top={r['top']:.2f}, bottom={r['bottom']:.2f}, "
              f"break_status={r.get('break_status', 'N/A')}")