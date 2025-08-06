import redis

# --- Configuration ---
# These should match the settings in your other Python scripts.
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0

# List of key patterns to delete.
# Using '*' as a wildcard to match all keys starting with these prefixes.
KEY_PATTERNS_TO_DELETE = [
    "zset:open_interest:*",
    "kline:*",
    "stream:kline:*",
    "zset:kline:*",
    "settings:*",
    "drawings:*",
    "live:tick:*",
    "agent:zset:*"  # This covers both agent kline and open interest keys
]

def main():
    """
    Connects to Redis and deletes all keys matching the defined patterns.
    """
    print("--- Redis Cleanup Script ---")

    try:
        # Connect to Redis
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
        r.ping()
        print(f"Successfully connected to Redis at {REDIS_HOST}:{REDIS_PORT}, DB: {REDIS_DB}")
    except redis.exceptions.ConnectionError as e:
        print(f"Error: Could not connect to Redis. Please ensure it is running. Details: {e}")
        return

    total_deleted_count = 0

    for pattern in KEY_PATTERNS_TO_DELETE:
        print(f"\nScanning for keys matching pattern: '{pattern}'...")

        try:
            # Use scan_iter to safely find keys without blocking the server
            keys_to_delete = list(r.scan_iter(match=pattern))

            if not keys_to_delete:
                print(f"No keys found for pattern '{pattern}'.")
                continue

            print(f"Found {len(keys_to_delete)} keys to delete for pattern '{pattern}'.")

            # Use a pipeline to delete keys in a single batch for efficiency
            deleted_count = r.delete(*keys_to_delete)
            total_deleted_count += deleted_count

            print(f"Successfully deleted {deleted_count} keys for pattern '{pattern}'.")

        except Exception as e:
            print(f"An error occurred while processing pattern '{pattern}': {e}")

    print("\n--- Cleanup Summary ---")
    print(f"Total keys deleted: {total_deleted_count}")
    print("Redis cleanup complete.")

if __name__ == "__main__":
    main()