import asyncio
import json
import logging
from redis.asyncio import Redis as AsyncRedis

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def delete_specific_drawing(drawing_id: str):
    """Delete a specific drawing by ID from Redis across all symbols and users."""
    redis = None
    try:
        redis = AsyncRedis(host='localhost', port=6379, db=0, decode_responses=True)
        await redis.ping()

        logger.info(f"Searching for drawing with ID: {drawing_id}")

        # Scan for all drawing keys
        drawing_keys = []
        async for key in redis.scan_iter(match="drawings:*"):
            drawing_keys.append(key)

        logger.info(f"Found {len(drawing_keys)} drawing keys to check")

        deleted = False
        for key in drawing_keys:
            try:
                drawings_data_str = await redis.get(key)
                if not drawings_data_str:
                    continue

                drawings = json.loads(drawings_data_str)
                original_len = len(drawings)

                # Log the drawings data for debugging
                logger.info(f"Checking key {key} with {len(drawings)} drawings")
                for drawing in drawings:
                    if isinstance(drawing, dict) and drawing.get("id") == drawing_id:
                        logger.info(f"Found target drawing in key {key}: {json.dumps(drawing, indent=2)}")

                # Filter out the drawing with the matching ID
                drawings = [d for d in drawings if d.get("id") != drawing_id]

                if len(drawings) < original_len:
                    # Drawing was found and removed
                    await redis.set(key, json.dumps(drawings))
                    logger.info(f"Successfully deleted drawing {drawing_id} from key: {key}")
                    deleted = True
                    break  # Assuming ID is unique across all drawings

            except Exception as e:
                logger.error(f"Error processing key {key}: {e}")
                continue

        if not deleted:
            logger.warning(f"Drawing with ID {drawing_id} not found in any key")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if redis:
            await redis.aclose()

if __name__ == "__main__":
    drawing_id = "a58a1a5f-af75-4926-bdb1-cbbd588c2f6b"
    asyncio.run(delete_specific_drawing(drawing_id))