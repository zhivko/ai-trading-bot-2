#!/usr/bin/env python3
"""
Test script to debug where null values are coming from in indicator calculations.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timezone
from indicators import calculate_macd, _extract_results

def create_test_dataframe():
    """Create a test DataFrame with sample OHLC data."""
    # Create timestamps for 100 data points (5-minute intervals)
    base_time = int(datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp())
    timestamps = [base_time + i * 300 for i in range(100)]  # 100 points, 5-min intervals

    # Create sample OHLC data
    np.random.seed(42)  # For reproducible results
    close_prices = []
    price = 50000.0
    for i in range(100):
        # Random walk with some trend
        change = np.random.normal(0, 50)
        price += change
        close_prices.append(max(price, 1000))  # Ensure positive prices

    # Create OHLC data
    data = []
    for i, ts in enumerate(timestamps):
        close = close_prices[i]
        high = close * (1 + np.random.uniform(0, 0.01))
        low = close * (1 - np.random.uniform(0, 0.01))
        open_price = close_prices[i-1] if i > 0 else close

        data.append({
            'time': ts,
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': np.random.uniform(100, 1000)
        })

    return data

def test_macd_calculation():
    """Test MACD calculation and track where nulls come from."""
    print("Creating test DataFrame...")
    klines = create_test_dataframe()

    # Prepare DataFrame like the real system does
    from indicators import _prepare_dataframe
    df_ohlcv = _prepare_dataframe(klines, [])
    if df_ohlcv is None:
        print("❌ Failed to prepare DataFrame")
        return

    print(f"Prepared DataFrame with {len(df_ohlcv)} rows")
    print(f"DataFrame index range: {df_ohlcv.index.min()} to {df_ohlcv.index.max()}")

    # Test MACD calculation
    print("\nTesting MACD calculation...")
    result = calculate_macd(df_ohlcv, 12, 26, 9)

    print(f"MACD result keys: {list(result.keys())}")
    print(f"Timestamps count: {len(result.get('t', []))}")
    print(f"MACD values count: {len(result.get('macd', []))}")
    print(f"Signal values count: {len(result.get('signal', []))}")
    print(f"Histogram values count: {len(result.get('histogram', []))}")

    # Check for nulls
    macd_values = result.get('macd', [])
    signal_values = result.get('signal', [])
    histogram_values = result.get('histogram', [])

    macd_nulls = sum(1 for v in macd_values if v is None)
    signal_nulls = sum(1 for v in signal_values if v is None)
    histogram_nulls = sum(1 for v in histogram_values if v is None)

    print("\nNull counts:")
    print(f"  MACD: {macd_nulls}/{len(macd_values)}")
    print(f"  Signal: {signal_nulls}/{len(signal_values)}")
    print(f"  Histogram: {histogram_nulls}/{len(histogram_values)}")

    if macd_nulls > 0 or signal_nulls > 0 or histogram_nulls > 0:
        print("\n❌ NULL VALUES DETECTED - INVESTIGATING FURTHER...")

        # Show first 10 values
        print("\nFirst 10 MACD values:")
        for i, v in enumerate(macd_values[:10]):
            print(f"  [{i}]: {v}")

        print("\nFirst 10 Signal values:")
        for i, v in enumerate(signal_values[:10]):
            print(f"  [{i}]: {v}")

        print("\nFirst 10 Histogram values:")
        for i, v in enumerate(histogram_values[:10]):
            print(f"  [{i}]: {v}")

        # Check if nulls are at the beginning (expected for indicators with lookback)
        first_null_m = next((i for i, v in enumerate(macd_values) if v is None), -1)
        first_null_s = next((i for i, v in enumerate(signal_values) if v is None), -1)
        first_null_h = next((i for i, v in enumerate(histogram_values) if v is None), -1)

        print("\nFirst null positions:")
        print(f"  MACD: {first_null_m}")
        print(f"  Signal: {first_null_s}")
        print(f"  Histogram: {first_null_h}")

        # Check if all nulls are at the beginning
        macd_has_nulls_after_start = any(v is None for v in macd_values[35:])  # After expected lookback
        signal_has_nulls_after_start = any(v is None for v in signal_values[35:])
        histogram_has_nulls_after_start = any(v is None for v in histogram_values[35:])

        print("\nNulls after position 35 (should be False):")
        print(f"  MACD: {macd_has_nulls_after_start}")
        print(f"  Signal: {signal_has_nulls_after_start}")
        print(f"  Histogram: {histogram_has_nulls_after_start}")

    else:
        print("\n✅ NO NULL VALUES - Calculation successful!")

if __name__ == "__main__":
    print("Testing indicator null value sources...\n")
    test_macd_calculation()
    print("\nTest completed.")
