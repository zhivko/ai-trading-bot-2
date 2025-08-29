#!/usr/bin/env python3
"""
Script to test the history endpoint directly.
"""

import asyncio
import json
from datetime import datetime, timezone
from redis_utils import get_redis_connection
from endpoints.chart_endpoints import history_endpoint

async def test_history_endpoint():
    """Test the history endpoint with proper timestamps."""

    # Test with current date range (last 30 days)
    now = int(datetime.now(timezone.utc).timestamp())
    thirty_days_ago = now - (30 * 24 * 60 * 60)

    print(f"Testing history endpoint with:")
    print(f"Symbol: PAXGUSDT")
    print(f"Resolution: 1d")
    print(f"From: {thirty_days_ago} ({datetime.fromtimestamp(thirty_days_ago, timezone.utc)})")
    print(f"To: {now} ({datetime.fromtimestamp(now, timezone.utc)})")
    print()

    try:
        response = await history_endpoint("PAXGUSDT", "1d", thirty_days_ago, now)

        # Check if response is a JSONResponse
        if hasattr(response, 'body'):
            response_data = json.loads(response.body.decode('utf-8'))
        else:
            response_data = response

        print(f"Response status: {response_data.get('s', 'unknown')}")
        print(f"Number of data points: {len(response_data.get('t', []))}")

        if response_data.get('s') == 'ok' and response_data.get('t'):
            print("[SUCCESS] History endpoint returned data!")
            first_ts = response_data['t'][0]
            last_ts = response_data['t'][-1]
            print(f"Data range: {datetime.fromtimestamp(first_ts, timezone.utc)} to {datetime.fromtimestamp(last_ts, timezone.utc)}")
        elif response_data.get('s') == 'no_data':
            print("[ERROR] History endpoint returned no data")
        else:
            print(f"[ERROR] Unexpected response: {response_data}")

    except Exception as e:
        print(f"[ERROR] Exception during test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_history_endpoint())