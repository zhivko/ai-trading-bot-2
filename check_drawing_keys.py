import asyncio
from redis_utils import get_redis_connection

async def check_drawing_keys():
    redis = await get_redis_connection()
    keys = []
    async for key in redis.scan_iter(match="drawings:*"):
        keys.append(key.decode('utf-8') if isinstance(key, bytes) else key)
    print(f"Found {len(keys)} drawing keys:")
    for key in keys:
        print(key)

if __name__ == "__main__":
    asyncio.run(check_drawing_keys())