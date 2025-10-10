import asyncio
import json
from redis.asyncio import Redis as AsyncRedis
from datetime import datetime, timezone

async def check_redis_key():
    """Check if the specific Redis key exists and has data."""
    redis = None
    try:
        redis = AsyncRedis(host='localhost', port=6379, db=0, decode_responses=True)
        await redis.ping()

        key = "zset:kline:BTCUSDT:1h"
        print(f"Checking Redis key: {key}")

        # Check if key exists
        exists = await redis.exists(key)
        print(f"Key exists: {exists}")

        if exists:
            # Get cardinality (number of members)
            cardinality = await redis.zcard(key)
            print(f"Number of members: {cardinality}")

            if cardinality > 0:
                # Get some sample data - first 5 and last 5
                first_data = await redis.zrange(key, 0, 4, withscores=True)  # First 5 records
                last_data = await redis.zrange(key, -5, -1, withscores=True)  # Last 5 records

                print(f"Sample data (first 5 records):")
                for i, (member, score) in enumerate(first_data):
                    dt_object = datetime.fromtimestamp(score, timezone.utc)
                    print(f"  Record {i+1}:")
                    print(f"    Timestamp: {int(score)} ({dt_object.strftime('%Y-%m-%d %H:%M:%S UTC')})")
                    try:
                        parsed = json.loads(member)
                        print(f"    OHLC: O={parsed.get('open')} H={parsed.get('high')} L={parsed.get('low')} C={parsed.get('close')} V={parsed.get('vol')}")
                    except:
                        print(f"    Data: {member[:100]}...")

                print(f"\nSample data (last 5 records):")
                for i, (member, score) in enumerate(last_data):
                    dt_object = datetime.fromtimestamp(score, timezone.utc)
                    print(f"  Record {i+1}:")
                    print(f"    Timestamp: {int(score)} ({dt_object.strftime('%Y-%m-%d %H:%M:%S UTC')})")
                    try:
                        parsed = json.loads(member)
                        print(f"    OHLC: O={parsed.get('open')} H={parsed.get('high')} L={parsed.get('low')} C={parsed.get('close')} V={parsed.get('vol')}")
                    except:
                        print(f"    Data: {member[:100]}...")

                # Check current time vs latest data
                if last_data:
                    latest_timestamp = last_data[-1][1]
                    current_time = datetime.now(timezone.utc).timestamp()
                    time_diff_hours = (current_time - latest_timestamp) / 3600
                    print(f"\nLatest data timestamp: {datetime.fromtimestamp(latest_timestamp, timezone.utc)}")
                    print(f"Current time: {datetime.fromtimestamp(current_time, timezone.utc)}")
                    print(f"Time difference: {time_diff_hours:.1f} hours")

            else:
                print("Key exists but has no members.")
        else:
            print("Key does not exist.")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if redis:
            await redis.close()

if __name__ == "__main__":
    asyncio.run(check_redis_key())