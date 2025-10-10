import asyncio
import json
from redis_utils import get_redis_connection
from config import SUPPORTED_SYMBOLS

async def clean_corrupted_drawings():
    redis = await get_redis_connection()
    total_cleaned = 0

    for symbol in SUPPORTED_SYMBOLS:
        pattern = f"drawings:*:{symbol}"
        async for key in redis.scan_iter(match=pattern):
            key_str = key.decode('utf-8') if isinstance(key, bytes) else key
            print(f"Checking key: {key_str}")

            drawing_data = await redis.get(key_str)
            if not drawing_data:
                continue

            try:
                user_drawings = json.loads(drawing_data)
                if not isinstance(user_drawings, list):
                    print(f"Invalid data in {key_str}: not a list")
                    continue

                original_count = len(user_drawings)
                cleaned_drawings = []

                for drawing in user_drawings:
                    if not isinstance(drawing, dict):
                        print(f"Skipping non-dict drawing in {key_str}")
                        continue

                    start_time = drawing.get('start_time')
                    end_time = drawing.get('end_time')
                    drawing_id = drawing.get('id', 'unknown')

                    if start_time is None or end_time is None:
                        print(f"Removing corrupted drawing {drawing_id} in {key_str}: start_time={start_time}, end_time={end_time}")
                        continue

                    cleaned_drawings.append(drawing)

                if len(cleaned_drawings) < original_count:
                    await redis.set(key_str, json.dumps(cleaned_drawings))
                    removed = original_count - len(cleaned_drawings)
                    total_cleaned += removed
                    print(f"Cleaned {removed} drawings from {key_str}")

            except json.JSONDecodeError as e:
                print(f"Invalid JSON in {key_str}: {e}")

    print(f"Total corrupted drawings removed: {total_cleaned}")

if __name__ == "__main__":
    asyncio.run(clean_corrupted_drawings())