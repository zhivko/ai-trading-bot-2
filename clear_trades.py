#!/usr/bin/env python3
"""
Clear all trade data from Redis and reset trade history
"""

import redis
import sys
import os
from pathlib import Path

# Add the current directory to the path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent))

from config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD, REDIS_TIMEOUT
from redis_utils import get_redis_connection

def clear_all_trades():
    """Clear all trade-related data from Redis"""
    try:
        r = get_redis_connection()

        # Keys to clear
        trade_keys = [
            "trades:*",  # All trade entries
            "trade_history:*",  # Trade history keys
            "volume_profile:*",  # Volume profile data
            "market_data:*",  # Market data related to trades
        ]

        total_deleted = 0
        for pattern in trade_keys:
            keys = r.keys(pattern)
            if keys:
                r.delete(*keys)
                total_deleted += len(keys)
                print(f"Cleared {len(keys)} keys matching pattern: {pattern}")

        print(f"\nTotal keys cleared: {total_deleted}")

        # Check if more agressive clearing is needed
        if total_deleted == 0:
            print("No trade keys found. Performing full Redis cleanup...")

            # More aggressive: clear keys containing 'trade' in any form
            all_keys = r.keys("*")
            trade_related_keys = [key for key in all_keys if b'trade' in key.lower()]
            if trade_related_keys:
                r.delete(*trade_related_keys)
                print(f"Cleared {len(trade_related_keys)} trade-related keys")
            else:
                print("No trade-related keys found in Redis")

        print("Trade data clearing complete!")

    except Exception as e:
        print(f"Error clearing trades: {e}")
        return False

    return True

if __name__ == "__main__":
    print("Clearing all trade data from Redis...")
    success = clear_all_trades()
    sys.exit(0 if success else 1)
