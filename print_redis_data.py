
import asyncio
import json
from redis.asyncio import Redis as AsyncRedis
from datetime import datetime, timezone

async def print_redis_data():
    """Connects to Redis and prints BTCUSDT 5m kline data."""
    redis = None
    try:
        redis = AsyncRedis(host='localhost', port=6379, db=0, decode_responses=True)
        await redis.ping()
        
        symbol = "BTCUSDT"
        resolution = "5m"
        sorted_set_key = f"zset:kline:{symbol}:{resolution}"

        print(f"Fetching data from Redis key: {sorted_set_key}")

        data = await redis.zrange(sorted_set_key, 0, -1, withscores=True)

        if not data:
            print("No data found.")
            return

        print(f"Found {len(data)} records. Printing a few samples:")
        
        for i, (member, score) in enumerate(data):
            dt_object = datetime.fromtimestamp(score, timezone.utc)
            print(f"Record {i+1}:")
            print(f"  Timestamp: {int(score)} ({dt_object.strftime('%Y-%m-%d %H:%M:%S UTC')})")
            print(f"  Data: {member}")
            if i > 20: # Print first 20 records
                break


    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if redis:
            await redis.close()

if __name__ == "__main__":
    asyncio.run(print_redis_data())
