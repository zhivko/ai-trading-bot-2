#!/usr/bin/env python3
"""
Script to inspect current Redis settings for debugging.
"""

import asyncio
import json
from redis_utils import get_redis_connection
from logging_config import logger

async def inspect_settings():
    """Inspect all settings stored in Redis."""
    try:
        redis = await get_redis_connection()

        # Pattern to match all settings keys
        pattern = "settings:*:*"

        print("Current settings in Redis:")
        print("=" * 50)

        async for key in redis.scan_iter(match=pattern):
            try:
                settings_json = await redis.get(key)
                if settings_json:
                    settings = json.loads(settings_json)
                    print(f"\nKey: {key}")
                    print(f"Symbol: {settings.get('symbol', 'N/A')}")
                    print(f"Resolution: {settings.get('resolution', 'N/A')}")
                    print(f"Range: {settings.get('range', 'N/A')}")

                    x_axis_min = settings.get('xAxisMin')
                    x_axis_max = settings.get('xAxisMax')

                    if x_axis_min is not None and x_axis_max is not None:
                        print(f"xAxisMin: {x_axis_min}")
                        print(f"xAxisMax: {x_axis_max}")

                        # Check if they're in milliseconds
                        if x_axis_min > 1e12:
                            print("  -> These appear to be in MILLISECONDS")
                            from datetime import datetime
                            min_date = datetime.fromtimestamp(x_axis_min / 1000)
                            max_date = datetime.fromtimestamp(x_axis_max / 1000)
                            print(f"  -> As seconds: {x_axis_min / 1000} -> {min_date}")
                            print(f"  -> As seconds: {x_axis_max / 1000} -> {max_date}")
                        else:
                            print("  -> These appear to be in SECONDS")
                            from datetime import datetime
                            min_date = datetime.fromtimestamp(x_axis_min)
                            max_date = datetime.fromtimestamp(x_axis_max)
                            print(f"  -> Date: {min_date}")
                            print(f"  -> Date: {max_date}")
                    else:
                        print("xAxisMin/xAxisMax: None (Auto)")

            except json.JSONDecodeError:
                print(f"Could not parse JSON for key {key}")
            except Exception as e:
                print(f"Error processing key {key}: {e}")

    except Exception as e:
        logger.error(f"Error inspecting settings: {e}")

if __name__ == "__main__":
    asyncio.run(inspect_settings())