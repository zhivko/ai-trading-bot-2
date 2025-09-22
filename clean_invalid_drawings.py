import asyncio
import json
from redis_utils import get_redis_connection
from config import SUPPORTED_SYMBOLS

async def clean_drawings_with_zero_timestamps():
    """Remove drawings that have start_time=0 and end_time=0 from Redis."""
    try:
        redis = await get_redis_connection()
        print("Connected to Redis. Scanning for drawing keys...")

        all_keys_processed = 0
        total_invalid_drawings_removed = 0

        for symbol in SUPPORTED_SYMBOLS:
            pattern = f"drawings:*:{symbol}"
            print(f"Scanning pattern: {pattern}")

            async for key in redis.scan_iter(match=pattern):
                all_keys_processed += 1
                user_email = key.split(":", 2)[1]  # Extract email from drawings:email:symbol

                # Get current drawings list
                drawings_json = await redis.get(key)
                if not drawings_json:
                    continue

                try:
                    drawings = json.loads(drawings_json)
                except json.JSONDecodeError:
                    print(f"Invalid JSON in key {key}, skipping")
                    continue

                # Filter out invalid drawings (start_time=0 and end_time=0)
                original_count = len(drawings)
                valid_drawings = [
                    d for d in drawings
                    if not (d.get('start_time') == 0 and d.get('end_time') == 0)
                ]
                invalid_removed = original_count - len(valid_drawings)

                if invalid_removed > 0:
                    print(f"Key {key}: Removed {invalid_removed} invalid drawings (start_time=0, end_time=0)")

                    # Update or delete the key
                    if valid_drawings:
                        await redis.set(key, json.dumps(valid_drawings))
                        print("Updated key {} with {} remaining drawings".format(key, len(valid_drawings)))
                    else:
                        await redis.delete(key)
                        print(f"All drawings were invalid, deleted key {key}")

                    total_invalid_drawings_removed += invalid_removed

        print("\nCleanup complete!")
        print("Keys processed: {}".format(all_keys_processed))
        print("Total invalid drawings removed: {}".format(total_invalid_drawings_removed))

    except Exception as e:
        print("Error during cleanup: {}".format(e))
        raise

if __name__ == "__main__":
    asyncio.run(clean_drawings_with_zero_timestamps())
