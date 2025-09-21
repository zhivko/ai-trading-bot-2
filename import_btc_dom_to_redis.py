import redis
import pandas as pd
from datetime import datetime, timezone

def import_btc_dom_to_redis(csv_file='btc_dominance_cryptocompare.csv'):
    # Connect to Redis (assuming localhost:6379, adjust if needed)
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)

    # Load the CSV data
    df = pd.read_csv(csv_file)

    # Filter out rows with zero or invalid BTC dominance (likely early dates)
    df = df[df['btc_dominance'] > 0]

    print(f"Loading CSV with {len(df)} rows, keeping {len(df)} valid BTC dominance values")

    # Convert DataFrame to list of kline objects
    klines = []
    valid_count = 0
    invalid_count = 0

    for _, row in df.iterrows():
        date_str = row['time']  # Assumes 'time' column is in 'YYYY-MM-DD' format
        dominance = row['btc_dominance']

        # Validate dominance data - should be a reasonable percentage (0.1 to 99.9)
        try:
            dominance = float(dominance)
        except (ValueError, TypeError):
            invalid_count += 1
            continue

        # Skip values that are clearly invalid:
        # - Zero/negative values
        # - Values > 100% (impossible)
        # - Values < 1% (unlikely for BTC dominance after 2012)
        if dominance <= 0 or dominance > 100 or dominance < 1:
            invalid_count += 1
            continue

        # Convert date string to Unix timestamp (beginning of day)
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            timestamp = int(dt.timestamp())
        except ValueError:
            invalid_count += 1
            continue

        # Only process dates from 2010 onwards (skip extremely early data)
        if timestamp < 1262304000:  # 2010-01-01
            continue

        # Create kline object (using dominance as close price, others set to dominance)
        kline = {
            'time': timestamp,
            'open': dominance,
            'high': dominance,
            'low': dominance,
            'close': dominance,
            'vol': 1.0,  # Dummy volume
        }
        klines.append(kline)
        valid_count += 1
    print("Data filtering results:")
    print(f"  Invalid/zero BTC dominance values filtered: {invalid_count}")
    print(f"  Valid data points: {valid_count}")

    if not klines:
        print("No valid data found to import")
        return

    # Sort klines by timestamp
    klines.sort(key=lambda x: x['time'])
    print(f"Prepared {len(klines)} kline data points")

    # Clear any existing data first
    resolution = '1d'
    sorted_set_key = f"zset:kline:BTCDOM:{resolution}"
    import re
    takeaway_keys = r.keys(f"BTCDOM:*")  # Legacy keys to remove

    if takeaway_keys:
        r.delete(*takeaway_keys)
        print(f"Cleared {len(takeaway_keys)} legacy keys")

    # Store klines using the same format as cache_klines() function
    import json
    pipeline = r.pipeline()

    for kline in klines:
        timestamp = kline["time"]
        data_str = json.dumps(kline)
        individual_key = f"kline:BTCDOM:{resolution}:{timestamp}"
        expiration = 60 * 60 * 24 * 30  # 30 days

        # Store individual kline key (for direct access)
        pipeline.setex(individual_key, expiration, data_str)

        # Remove any existing members with same timestamp in sorted set
        pipeline.zremrangebyscore(sorted_set_key, timestamp, timestamp)

        # Add to sorted set indexed by timestamp
        pipeline.zadd(sorted_set_key, {data_str: timestamp})

    # Execute all commands
    pipeline.execute()

    # Trim sorted set to reasonable size (keep most recent data)
    r.zremrangebyrank(sorted_set_key, 0, -(10000 + 1))

    print("✅ BTC Dominance data imported successfully!")
    print(f"   📊 Stored {len(klines)} kline data points")
    print(f"   🔑 Individual keys: kline:BTCDOM:{resolution}:<timestamp>")
    print(f"   🔑 Sorted set: {sorted_set_key}")
    print(f"   📅 Date range: {datetime.fromtimestamp(klines[0]['time'], timezone.utc)} to {datetime.fromtimestamp(klines[-1]['time'], timezone.utc)}")
    print(f"   📈 Dominance range: {min(k['close'] for k in klines):.2f}% to {max(k['close'] for k in klines):.2f}%")

    # Test retrieval to verify data is accessible
    test_count = r.zcard(sorted_set_key)
    print(f"   ✅ Verification: Sorted set contains {test_count} data points")

if __name__ == "__main__":
    import_btc_dom_to_redis()
