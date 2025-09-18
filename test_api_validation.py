#!/usr/bin/env python3
"""
Test script to verify the API validation logic works correctly.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone
from endpoints.indicator_endpoints import _calculate_and_return_indicators

async def test_api_validation():
    """Test the full API flow including validation."""

    # Create test data that simulates what the API would receive
    symbol = "BTCUSDT"
    resolution = "5m"
    from_ts = int(datetime(2024, 1, 1, 2, 0, 0, tzinfo=timezone.utc).timestamp())  # Start at position 24 (after lookback)
    to_ts = int(datetime(2024, 1, 1, 8, 15, 0, tzinfo=timezone.utc).timestamp())   # End at last position

    print(f"Testing API validation for range: {from_ts} to {to_ts}")
    print(f"Human readable: {datetime.fromtimestamp(from_ts, timezone.utc)} to {datetime.fromtimestamp(to_ts, timezone.utc)}")

    # Test MACD indicator
    requested_indicator_ids = ["macd"]

    try:
        # Call the API function (this will do the full calculation and validation)
        result = await _calculate_and_return_indicators(
            symbol=symbol,
            resolution=resolution,
            from_ts=from_ts,
            to_ts=to_ts,
            requested_indicator_ids=requested_indicator_ids,
            simulation=False
        )

        print("\nAPI Response:")
        print(f"Status: {result.status_code}")
        response_data = result.body
        if isinstance(response_data, bytes):
            import json
            response_data = json.loads(response_data.decode('utf-8'))

        print(f"Response data keys: {list(response_data.keys())}")

        if response_data.get('s') == 'ok' and 'data' in response_data:
            indicator_data = response_data['data'].get('macd', {})
            print(f"MACD data status: {indicator_data.get('s')}")

            if indicator_data.get('s') == 'ok':
                timestamps = indicator_data.get('t', [])
                macd_values = indicator_data.get('macd', [])
                signal_values = indicator_data.get('signal', [])
                histogram_values = indicator_data.get('histogram', [])

                print(f"Returned timestamps: {len(timestamps)}")
                print(f"MACD values: {len(macd_values)}")
                print(f"Signal values: {len(signal_values)}")
                print(f"Histogram values: {len(histogram_values)}")

                # Check for nulls in the returned data (this should be the requested range only)
                macd_nulls = sum(1 for v in macd_values if v is None)
                signal_nulls = sum(1 for v in signal_values if v is None)
                histogram_nulls = sum(1 for v in histogram_values if v is None)

                print("\nNull counts in API response:")
                print(f"  MACD: {macd_nulls}/{len(macd_values)}")
                print(f"  Signal: {signal_nulls}/{len(signal_values)}")
                print(f"  Histogram: {histogram_nulls}/{len(histogram_values)}")

                if macd_nulls == 0 and signal_nulls == 0 and histogram_nulls == 0:
                    print("\n✅ SUCCESS: API validation passed - no nulls in requested range!")
                    return True
                else:
                    print("\n❌ FAIL: API validation failed - nulls found in requested range!")
                    return False
            else:
                print(f"❌ FAIL: MACD calculation failed with status: {indicator_data.get('s')}")
                print(f"Error: {indicator_data.get('errmsg')}")
                return False
        else:
            print(f"❌ FAIL: API call failed with status: {response_data.get('s')}")
            print(f"Error: {response_data.get('errmsg')}")
            return False

    except Exception as e:
        print(f"❌ ERROR: Exception during API test: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Testing API validation logic...\n")

    # Run the async test
    import asyncio
    success = asyncio.run(test_api_validation())

    if success:
        print("\n🎉 API validation test passed!")
    else:
        print("\n💥 API validation test failed!")

    print("Test completed.")
