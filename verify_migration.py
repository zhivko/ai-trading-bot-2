#!/usr/bin/env python3
"""
Verification script to check that activeIndicators has been migrated to active_indicators.
"""

import json
import redis
from config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD

def verify_migration():
    """Verify that migration from activeIndicators to active_indicators was successful."""

    # Connect to Redis
    r = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD,
        decode_responses=True
    )

    # Check a few sample keys
    sample_keys = [
        "settings:klemenzivkovic@gmail.com:BTCUSDT",
        "settings:test@example.com:ETHUSDT",
        "settings:klemenzivkovic@gmail.com:ETHUSDT"
    ]

    print("Verifying migration results...")

    for key in sample_keys:
        try:
            data_str = r.get(key)
            if data_str:
                data = json.loads(data_str)

                has_old_key = 'activeIndicators' in data
                has_new_key = 'active_indicators' in data

                print(f"\nKey: {key}")
                print(f"  Has 'activeIndicators' (old): {has_old_key}")
                print(f"  Has 'active_indicators' (new): {has_new_key}")

                if has_new_key:
                    indicators = data.get('active_indicators', [])
                    print(f"  active_indicators value: {indicators}")
                elif has_old_key:
                    print("  ERROR: Still has old key format!")
        except Exception as e:
            print(f"Error checking key {key}: {e}")

    # Check if any keys still have the old format
    all_settings_keys = r.keys("settings:*")
    old_format_count = 0

    for key in all_settings_keys:
        try:
            data_str = r.get(key)
            if data_str:
                data = json.loads(data_str)
                if 'activeIndicators' in data:
                    old_format_count += 1
                    print(f"WARNING: Key {key} still has old 'activeIndicators' format")
        except Exception:
            pass

    if old_format_count == 0:
        print(f"\nSUCCESS: All {len(all_settings_keys)} settings keys have been migrated to use 'active_indicators'")
    else:
        print(f"\nERROR: {old_format_count} keys still use the old 'activeIndicators' format")

if __name__ == "__main__":
    verify_migration()