import asyncio
import json
from redis_utils import get_redis_connection

async def show_drawing(drawing_id: str):
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

            for drawing in user_drawings:
                if isinstance(drawing, dict) and drawing.get('id') == drawing_id:
                    print(f"Found drawing {drawing_id} in key: {key_str}")
                    print(json.dumps(drawing, indent=2))
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
    if len(sys.argv) != 2:
        print("Usage: python show_drawing.py <drawing_id>")
        sys.exit(1)

    drawing_id = sys.argv[1]
    asyncio.run(show_drawing(drawing_id))