#!/usr/bin/env python3
"""
Migration script to rename 'activeIndicators' to 'active_indicators' in Redis settings keys.
"""

import json
import redis
import os
from config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD

def migrate_active_indicators():
    """Migrate activeIndicators to active_indicators in all settings:* keys."""

    # Connect to Redis
    r = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD,
        decode_responses=True
    )

    # Find all settings keys
    settings_keys = r.keys("settings:*")

    if not settings_keys:
        print("No settings keys found in Redis.")
        return

    print(f"Found {len(settings_keys)} settings keys to check.")

    migrated_count = 0

    for key in settings_keys:
        try:
            # Get the current data
            data_str = r.get(key)
            if not data_str:
                continue

            # Parse JSON
            data = json.loads(data_str)

            # Check if it has the old key
            if 'activeIndicators' in data:
                # Rename the key
                data['active_indicators'] = data.pop('activeIndicators')
                migrated_count += 1

                # Save back to Redis
                r.set(key, json.dumps(data))

                print(f"Migrated key: {key}")

        except json.JSONDecodeError as e:
            print(f"Error parsing JSON for key {key}: {e}")
        except Exception as e:
            print(f"Error processing key {key}: {e}")

    print(f"Migration complete. Updated {migrated_count} keys.")

if __name__ == "__main__":
    migrate_active_indicators()