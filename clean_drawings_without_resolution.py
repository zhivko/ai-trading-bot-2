import asyncio
import json
from redis_utils import get_redis_connection
from config import SUPPORTED_SYMBOLS
from logging_config import logger

async def clean_drawings_without_resolution():
    """
    Remove drawings that don't have a 'resolution' field from Redis.
    This cleans up old drawings that were created before resolution was required.
    """
    redis = await get_redis_connection()
    total_cleaned = 0
    total_keys_processed = 0

    # Scan for all drawing keys using pattern
    pattern = "drawings:*"
    async for key in redis.scan_iter(match=pattern):
        key_str = key.decode('utf-8') if isinstance(key, bytes) else key
        total_keys_processed += 1

        logger.info(f"Processing key: {key_str}")

        drawing_data = await redis.get(key_str)
        if not drawing_data:
            logger.warning(f"No data found for key: {key_str}")
            continue

        try:
            user_drawings = json.loads(drawing_data)
            if not isinstance(user_drawings, list):
                logger.warning(f"Invalid data in {key_str}: not a list")
                continue

            original_count = len(user_drawings)
            logger.info(f"Found {original_count} drawings in {key_str}")

            # Filter out drawings without resolution
            cleaned_drawings = []
            removed_count = 0

            for drawing in user_drawings:
                if not isinstance(drawing, dict):
                    logger.warning(f"Skipping non-dict drawing in {key_str}")
                    removed_count += 1
                    continue

                drawing_id = drawing.get('id', 'unknown')
                resolution = drawing.get('resolution')

                if resolution is None:
                    logger.info(f"Removing drawing {drawing_id} in {key_str}: missing resolution field")
                    removed_count += 1
                    continue

                # Keep drawings that have resolution
                cleaned_drawings.append(drawing)
                logger.debug(f"Keeping drawing {drawing_id} with resolution: {resolution}")

            if removed_count > 0:
                await redis.set(key_str, json.dumps(cleaned_drawings))
                total_cleaned += removed_count
                logger.info(f"Cleaned {removed_count} drawings from {key_str} (kept {len(cleaned_drawings)})")
            else:
                logger.info(f"No drawings to clean in {key_str}")

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {key_str}: {e}")
            continue
        except Exception as e:
            logger.error(f"Error processing {key_str}: {e}")
            continue

    logger.info(f"Processing complete. Total keys processed: {total_keys_processed}")
    logger.info(f"Total drawings removed: {total_cleaned}")

if __name__ == "__main__":
    asyncio.run(clean_drawings_without_resolution())