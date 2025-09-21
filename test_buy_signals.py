#!/usr/bin/env python3
"""
Simple test to verify buy signals functionality works correctly
"""

import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Add current directory to path so we can import indicators
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from indicators import find_buy_signals

def create_test_dataframe():
    """Create a test DataFrame similar to what WebSocket handlers create"""
    # Create timestamps for the last 100 hours
    base_time = datetime(2025, 9, 17, 0, 0, 0)  # Recent date
    timestamps = [base_time + timedelta(hours=i) for i in range(100)]

    # Create realistic RSI data
    np.random.seed(42)  # For reproducible results

    # Generate RSI values that oscillate around 50, but create some divergence scenarios
    rsi_values = []
    for i in range(100):
        # Create some oversold periods where RSI drops significantly below its SMA
        if 30 <= i <= 35:  # Period where RSI drops below SMA by >15 points
            rsi_values.append(25.0 + np.random.normal(0, 2))  # RSI around 25
        elif 60 <= i <= 65:  # Another oversold period
            rsi_values.append(20.0 + np.random.normal(0, 2))  # RSI around 20
        else:
            rsi_values.append(45.0 + np.random.normal(0, 10))  # Normal RSI oscillation

    # Create SMA14 values that are higher than RSI during oversold periods
    rsi_sma14_values = []
    for i, rsi_val in enumerate(rsi_values):
        if i < 14:
            # Use RSI average for first 14 values
            avg = np.mean(rsi_values[:i+1]) if i > 0 else rsi_values[0]
            rsi_sma14_values.append(avg)
        else:
            # Use SMA14
            avg = np.mean(rsi_values[i-14:i])
            rsi_sma14_values.append(avg)

        # During oversold periods, make SMA higher
        if 30 <= i <= 35:
            rsi_sma14_values[-1] = 42.0  # SMA stays around 42
        elif 60 <= i <= 65:
            rsi_sma14_values[-1] = 38.0  # SMA stays around 38

    # Create OHLC data
    prices = []
    current_price = 60000  # BTC starting price

    for i in range(100):
        # Add some price movement
        change = np.random.normal(0, 100)
        current_price += change
        current_price = max(50000, min(70000, current_price))  # Keep in reasonable range

        prices.append({
            'open': current_price - 50,
            'high': current_price + 100,
            'low': current_price - 100,
            'close': current_price
        })

    # Create DataFrame with the expected structure
    df_data = []
    for i, timestamp in enumerate(timestamps):
        row = {
            'time': timestamp,
            'open': prices[i]['open'],
            'high': prices[i]['high'],
            'low': prices[i]['low'],
            'close': prices[i]['close'],
            'RSI_14': rsi_values[i],
            'RSI_14_sma14': rsi_sma14_values[i]
        }
        df_data.append(row)

    df = pd.DataFrame(df_data)
    print(f"Created test DataFrame with {len(df)} rows")
    print("RSI columns present:", 'RSI_14' in df.columns, 'RSI_14_sma14' in df.columns)
    print("Sample data (last 10 rows):")
    print(df[['time', 'close', 'RSI_14', 'RSI_14_sma14']].tail(10))

    return df

def test_buy_signals():
    """Test the buy signals functionality"""
    print("=" * 60)
    print("TESTING BUY SIGNALS FUNCTIONALITY")
    print("=" * 60)

    # Create test data
    df = create_test_dataframe()

    print("\n" + "=" * 60)
    print("TEST 1: Run find_buy_signals on test data")
    print("=" * 60)

    # Test the function
    signals = find_buy_signals(df)

    print(f"\nRESULT: Found {len(signals)} buy signals")

    if signals:
        print("\nSignals found:")
        for i, signal in enumerate(signals, 1):
            timestamp = signal['timestamp']
            dt = datetime.fromtimestamp(timestamp)

            print(f"Signal {i}: {dt.strftime('%Y-%m-%d %H:%M')} - Price: ${signal['price']:.0f}, "
                  f"RSI: {signal['rsi']:.1f}, SMA: {signal['rsi_sma14']:.1f}, Deviation: {signal['deviation']:.1f}")
    else:
        print("No signals found - checking why...")

        # Check if we're in the expected oversold periods
        oversold_periods = []
        for i in range(len(df)):
            rsi_val = df['RSI_14'].iloc[i]
            sma_val = df['RSI_14_sma14'].iloc[i]
            if not (pd.isna(rsi_val) or pd.isna(sma_val)):
                deviation = sma_val - rsi_val
                if deviation > 15:
                    oversold_periods.append((i, df['time'].iloc[i], rsi_val, sma_val, deviation))

        if oversold_periods:
            print(f"Found {len(oversold_periods)} oversold periods (>15 point deviation):")
            for period in oversold_periods[:5]:  # Show first 5
                i, time_val, rsi, sma, dev = period
                print(f"  Bar {i}: {time_val.strftime('%Y-%m-%d %H:%M')} - RSI: {rsi:.1f}, SMA: {sma:.1f}, Deviation: {dev:.1f}")
            if len(oversold_periods) > 5:
                print(f"  ... and {len(oversold_periods) - 5} more oversold periods")
        else:
            print("No oversold periods found in the test data!")

    print("\n" + "=" * 60)
    print("TEST 2: Check DataFrame structure matches expectations")
    print("=" * 60)

    expected_cols = ['RSI_14', 'RSI_14_sma14', 'time', 'close']
    missing_cols = [col for col in expected_cols if col not in df.columns]
    if missing_cols:
        print(f"❌ MISSING COLUMNS: {missing_cols}")
    else:
        print("✅ All expected columns present")

    print(f"DataFrame shape: {df.shape}")
    print(f"Columns: {list(df.columns)}")

    # Check for NaN values
    nan_counts = df[['RSI_14', 'RSI_14_sma14']].isnull().sum()
    if nan_counts.sum() > 0:
        print(f"⚠️ NaN values found: {nan_counts.to_dict()}")
    else:
        print("✅ No NaN values in RSI columns")

    print("\nTest completed!")

if __name__ == "__main__":
    test_buy_signals()
