#!/usr/bin/env python3
"""
Script to check if PAXGUSDT data is available in Redis.
"""

import asyncio
from redis_utils import get_redis_connection, get_sorted_set_key
from datetime import datetime, timezone
from logging_config import logger

async def check_paxg_data():
    """Check what PAXGUSDT data is available in Redis."""
    try:
        redis = await get_redis_connection()

        symbol = "PAXGUSDT"
        resolution = "1d"
        sorted_set_key = get_sorted_set_key(symbol, resolution)

        # Check if the key exists
        exists = await redis.exists(sorted_set_key)
        if not exists:
            print(f"[ERROR] No data found for {symbol} {resolution}")
            print(f"Redis key '{sorted_set_key}' does not exist")
            return

        # Get cardinality (number of records)
        cardinality = await redis.zcard(sorted_set_key)
        print(f"[SUCCESS] Found {cardinality} records for {symbol} {resolution}")

        if cardinality > 0:
            # Get first and last records
            first_records = await redis.zrange(sorted_set_key, 0, 4, withscores=True)
            last_records = await redis.zrange(sorted_set_key, -5, -1, withscores=True)

            print("\n[INFO] First 5 records:")
            for data_str, score in first_records:
                try:
                    import json
                    data = json.loads(data_str)
                    date = datetime.fromtimestamp(score, timezone.utc)
                    print(f"  {date.strftime('%Y-%m-%d %H:%M:%S UTC')}: O={data['open']}, H={data['high']}, L={data['low']}, C={data['close']}")
                except:
                    print(f"  {score}: {str(data_str)[:100]}...")

            print("\n[INFO] Last 5 records:")
            for data_str, score in last_records:
                try:
                    import json
                    data = json.loads(data_str)
                    date = datetime.fromtimestamp(score, timezone.utc)
                    print(f"  {date.strftime('%Y-%m-%d %H:%M:%S UTC')}: O={data['open']}, H={data['high']}, L={data['low']}, C={data['close']}")
                except:
                    print(f"  {score}: {str(data_str)[:100]}...")

            # Check current date range
            now = datetime.now(timezone.utc)
            current_ts = int(now.timestamp())
            thirty_days_ago = current_ts - (30 * 24 * 60 * 60)

            print(f"\n[INFO] Checking data for last 30 days ({datetime.fromtimestamp(thirty_days_ago, timezone.utc)} to {now}):")
            recent_data = await redis.zrangebyscore(sorted_set_key, thirty_days_ago, current_ts, withscores=False)
            print(f"Found {len(recent_data)} records in the last 30 days")

            if len(recent_data) > 0:
                print("[SUCCESS] Recent data is available!")
            else:
                print("[ERROR] No recent data found - this explains the empty chart")

    except Exception as e:
        logger.error(f"Error checking PAXGUSDT data: {e}")
        print(f"[ERROR] Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_paxg_data())