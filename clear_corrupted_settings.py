#!/usr/bin/env python3
"""
Script to clear corrupted chart settings from Redis.
This removes settings with invalid timestamp ranges that cause empty charts.
"""

import asyncio
import json
from redis_utils import get_redis_connection
from logging_config import logger

async def clear_corrupted_settings():
    """Clear corrupted settings that contain invalid timestamp ranges."""
    try:
        redis = await get_redis_connection()

        # Pattern to match all settings keys
        pattern = "settings:*:*"

        corrupted_keys = []
        async for key in redis.scan_iter(match=pattern):
            try:
                settings_json = await redis.get(key)
                if settings_json:
                    settings = json.loads(settings_json)

                    # Check for corrupted xAxisMin/xAxisMax values
                    x_axis_min = settings.get('xAxisMin')
                    x_axis_max = settings.get('xAxisMax')

                    if x_axis_min is not None and x_axis_max is not None:
                        # Check if these are corrupted timestamps from year 2000-2001
                        from datetime import datetime

                        # Try as seconds first (normal case)
                        try:
                            min_date = datetime.fromtimestamp(x_axis_min)
                            max_date = datetime.fromtimestamp(x_axis_max)
                        except (OSError, ValueError):
                            # If that fails, try as milliseconds
                            try:
                                min_date = datetime.fromtimestamp(x_axis_min / 1000)
                                max_date = datetime.fromtimestamp(x_axis_max / 1000)
                            except (OSError, ValueError):
                                logger.warning(f"Could not parse timestamps for key {key}: xAxisMin={x_axis_min}, xAxisMax={x_axis_max}")
                                continue

                        # Check if the range is corrupted (from year 2000-2001 or before 2010)
                        if (min_date.year == 2000 and max_date.year == 2001) or \
                           (min_date.year < 2010 or max_date.year < 2010):
                            corrupted_keys.append(key)
                            logger.warning(f"Found corrupted settings in key {key}: "
                                         f"xAxisMin={x_axis_min} ({min_date}), "
                                         f"xAxisMax={x_axis_max} ({max_date})")

            except json.JSONDecodeError:
                logger.warning(f"Could not parse JSON for key {key}")
            except Exception as e:
                logger.error(f"Error processing key {key}: {e}")

        # Delete corrupted keys
        if corrupted_keys:
            logger.info(f"Deleting {len(corrupted_keys)} corrupted settings keys...")
            for key in corrupted_keys:
                await redis.delete(key)
                logger.info(f"Deleted corrupted key: {key}")
        else:
            logger.info("No corrupted settings keys found.")

    except Exception as e:
        logger.error(f"Error clearing corrupted settings: {e}")

if __name__ == "__main__":
    logger.info("Starting corrupted settings cleanup...")
    asyncio.run(clear_corrupted_settings())
    logger.info("Corrupted settings cleanup completed.")