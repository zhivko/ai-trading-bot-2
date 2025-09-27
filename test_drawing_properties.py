import asyncio
import json
from redis_utils import get_redis_connection

async def main():
    redis = await get_redis_connection()
    target_id = "e974c10b-7c04-4278-a26b-0979a424f4b7"

    async for key in redis.scan_iter(match="drawings:*:*"):
        key_str = key.decode() if isinstance(key, bytes) else key
        parts = key_str.split(':')
        if len(parts) != 3 or parts[0] != 'drawings':
            continue

        user_email = parts[1]
        symbol = parts[2]

        drawing_data = await redis.get(key)
        if drawing_data:
            try:
                user_drawings = json.loads(drawing_data)
                for drawing in user_drawings:
                    if drawing.get('id') == target_id:
                        print(f"Found drawing with ID {target_id} for user {user_email} on {symbol}:")
                        print(json.dumps(drawing, indent=2))
                        return
            except json.JSONDecodeError:
                print(f"Failed to parse JSON for key {key_str}")
                continue

    print(f"Drawing with ID {target_id} not found")

if __name__ == "__main__":
    asyncio.run(main())
