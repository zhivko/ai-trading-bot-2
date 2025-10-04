#!/usr/bin/env python3
"""
Script to clean up drawings with invalid resolutions from Redis.

This script scans all drawing data in Redis and removes any drawings that have
resolutions not present in SUPPORTED_RESOLUTIONS (like '1' instead of '1m').
"""

import asyncio
import json
from redis_utils import get_redis_connection
from config import SUPPORTED_SYMBOLS, SUPPORTED_RESOLUTIONS
from logging_config import logger

async def clean_invalid_drawings():
    """Clean up drawings with invalid resolutions."""
    logger.info("Starting cleanup of drawings with invalid resolutions...")

    redis = await get_redis_connection()
    total_drawings_processed = 0
    total_invalid_drawings_removed = 0
    total_keys_processed = 0

    # Process each supported symbol
    for symbol in SUPPORTED_SYMBOLS:
        logger.info(f"Processing drawings for symbol: {symbol}")

        # Find all drawing keys for this symbol
        pattern = f"drawings:*:{symbol}"
        drawing_keys = []

        # Use scan_iter to get all matching keys
        async for key in redis.scan_iter(match=pattern):
            drawing_keys.append(key)
            total_keys_processed += 1

        logger.info(f"Found {len(drawing_keys)} drawing keys for {symbol}")

        for key in drawing_keys:
            try:
                # Parse user email from key: drawings:{email}:{symbol}
                key_parts = key.split(':')
                if len(key_parts) != 3:
                    logger.warning(f"Skipping malformed drawing key: {key}")
                    continue

                user_email = key_parts[1]

                # Get the drawing data
                drawing_data_str = await redis.get(key)
                if not drawing_data_str:
                    logger.warning(f"No data found for key: {key}")
                    continue

                user_drawings = json.loads(drawing_data_str)
                if not isinstance(user_drawings, list):
                    logger.warning(f"Drawing data for {key} is not a list, skipping")
                    continue

                original_count = len(user_drawings)
                filtered_drawings = []
                invalid_count = 0

                # Filter out drawings with invalid resolutions
                for drawing in user_drawings:
                    if not isinstance(drawing, dict):
                        logger.warning(f"Invalid drawing format in {key}, skipping")
                        continue

                    resolution = drawing.get('resolution')
                    drawing_id = drawing.get('id', 'unknown')

                    total_drawings_processed += 1

                    if resolution not in SUPPORTED_RESOLUTIONS:
                        logger.info(f"Removing drawing {drawing_id} with invalid resolution '{resolution}' for {user_email}:{symbol}")
                        logger.info(f"Supported resolutions: {SUPPORTED_RESOLUTIONS}")
                        invalid_count += 1
                        continue

                    # Keep valid drawings
                    filtered_drawings.append(drawing)

                # If we removed any invalid drawings, update Redis
                if invalid_count > 0:
                    if not filtered_drawings:
                        # No drawings left, delete the key entirely
                        await redis.delete(key)
                        logger.info(f"Deleted empty drawing key {key} after removing {invalid_count} invalid drawings")
                    else:
                        # Update with filtered drawings
                        await redis.set(key, json.dumps(filtered_drawings))
                        logger.info(f"Updated {key}: kept {len(filtered_drawings)} drawings, removed {invalid_count} invalid ones")

                    total_invalid_drawings_removed += invalid_count

            except Exception as e:
                logger.error(f"Error processing key {key}: {e}")
                continue

    logger.info("Cleanup completed!")
    logger.info(f"Summary:")
    logger.info(f"  - Keys processed: {total_keys_processed}")
    logger.info(f"  - Drawings processed: {total_drawings_processed}")
    logger.info(f"  - Invalid drawings removed: {total_invalid_drawings_removed}")

    return total_invalid_drawings_removed

async def main():
    """Main function."""
    try:
        removed_count = await clean_invalid_drawings()
        print(f"\nCleanup completed! Removed {removed_count} drawings with invalid resolutions.")

        if removed_count > 0:
            print("\nNote: You may need to restart any running email alert services for the changes to take effect.")
        else:
            print("\nNo invalid drawings found - all drawings have valid resolutions.")

    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        print(f"Error during cleanup: {e}")

if __name__ == "__main__":
    asyncio.run(main())
