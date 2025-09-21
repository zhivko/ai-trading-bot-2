import asyncio
import json
import logging
from redis.asyncio import Redis
from redis_utils import get_redis_connection
from config import SUPPORTED_SYMBOLS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def clean_drawings_without_properties():
    """Delete all shapes/lines that don't have properties."""
    redis = await get_redis_connection()
    logger.info("Starting cleaning process for drawings without properties")

    cleaned_count = 0
    total_processed = 0

    for symbol in SUPPORTED_SYMBOLS:
        pattern = f"drawings:*:{symbol}"
        async for key in redis.scan_iter(match=pattern):
            key_str = key
            prefix = f"drawings:"
            suffix = f":{symbol}"
            if not (key_str.startswith(prefix) and key_str.endswith(suffix)):
                logger.warning(f"Skipping malformed drawing key: {key_str}")
                continue
            user_email = key_str[len(prefix):-len(suffix)]
            if not user_email:
                logger.warning(f"Skipping drawing key with empty user_email: {key_str}")
                continue

            drawing_data = await redis.get(key)
            if not drawing_data:
                continue

            try:
                user_drawings = json.loads(drawing_data)

                # Filter out drawings without properties
                cleaned_drawings = []
                for drawing in user_drawings:
                    if isinstance(drawing, dict) and drawing.get('properties') is not None:
                        cleaned_drawings.append(drawing)
                    else:
                        logger.info(f"Removing drawing {drawing.get('id', 'N/A')} for {user_email} on {symbol} due to missing properties")
                        cleaned_count += 1

                total_processed += len(user_drawings)

                # Update Redis with cleaned data
                if len(cleaned_drawings) != len(user_drawings):
                    await redis.set(key, json.dumps(cleaned_drawings))
                    logger.info(f"Updated {key} - removed {len(user_drawings) - len(cleaned_drawings)} drawings")

            except json.JSONDecodeError:
                logger.error(f"Invalid JSON data in {key_str}")
            except Exception as e:
                logger.error(f"Error processing {key_str}: {e}")

    logger.info(f"Cleaning completed. Processed {total_processed} drawings total, removed {cleaned_count} without properties")

if __name__ == "__main__":
    asyncio.run(clean_drawings_without_properties())
