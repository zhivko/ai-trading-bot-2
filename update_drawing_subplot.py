import asyncio
import json
from redis_utils import get_redis_connection

async def update_drawing_subplot(drawing_id: str, new_subplot_name: str):
    redis = await get_redis_connection()
    found = False

    async for key in redis.scan_iter(match="drawings:*"):
        key_str = key.decode('utf-8') if isinstance(key, bytes) else key

        drawing_data = await redis.get(key_str)
        if not drawing_data:
            continue

        try:
            user_drawings = json.loads(drawing_data)
            if not isinstance(user_drawings, list):
                continue

            for i, drawing in enumerate(user_drawings):
                if isinstance(drawing, dict) and drawing.get('id') == drawing_id:
                    print(f"Found drawing {drawing_id} in key: {key_str}")
                    print(f"Old subplot_name: {drawing.get('subplot_name')}")
                    drawing['subplot_name'] = new_subplot_name
                    print(f"New subplot_name: {drawing['subplot_name']}")

                    # Save back to Redis
                    await redis.set(key_str, json.dumps(user_drawings))
                    print(f"Updated drawing {drawing_id} successfully.")
                    found = True
                    break

            if found:
                break

        except json.JSONDecodeError as e:
            print(f"Invalid JSON in {key_str}: {e}")

    if not found:
        print(f"Drawing {drawing_id} not found in any Redis key.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: python update_drawing_subplot.py <drawing_id> <new_subplot_name>")
        sys.exit(1)

    drawing_id = sys.argv[1]
    new_subplot_name = sys.argv[2]
    asyncio.run(update_drawing_subplot(drawing_id, new_subplot_name))