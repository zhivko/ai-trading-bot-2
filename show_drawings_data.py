import asyncio
import json
from redis.asyncio import Redis as AsyncRedis
from datetime import datetime, timezone

async def show_drawings_data():
    """Show Redis data for the specific drawings key."""
    redis = None
    try:
        redis = AsyncRedis(host='localhost', port=6379, db=0, decode_responses=True)
        await redis.ping()

        key = "drawings:klemenzivkovic@gmail.com:BTCUSDT"
        print(f"Checking Redis key: {key}")

        # Check if key exists
        exists = await redis.exists(key)
        print(f"Key exists: {exists}")

        if exists:
            # Get the data type
            key_type = await redis.type(key)
            print(f"Key type: {key_type}")

            if key_type == 'string':
                # Get string value
                data = await redis.get(key)
                print(f"Raw data: {data}")

                if data:
                    try:
                        parsed = json.loads(data)
                        print(f"Parsed JSON data:")
                        print(json.dumps(parsed, indent=2))
                    except json.JSONDecodeError:
                        print("Data is not valid JSON")

            elif key_type == 'hash':
                # Get all hash fields
                data = await redis.hgetall(key)
                print(f"Hash data ({len(data)} fields):")
                for field, value in data.items():
                    print(f"  {field}: {value}")
                    # Try to parse JSON values
                    try:
                        parsed_value = json.loads(value)
                        print(f"    Parsed: {json.dumps(parsed_value, indent=4)}")
                    except json.JSONDecodeError:
                        pass
                    print()

            elif key_type == 'list':
                # Get list elements
                data = await redis.lrange(key, 0, -1)
                print(f"List data ({len(data)} elements):")
                for i, item in enumerate(data):
                    print(f"  [{i}]: {item}")
                    try:
                        parsed_item = json.loads(item)
                        print(f"    Parsed: {json.dumps(parsed_item, indent=4)}")
                    except json.JSONDecodeError:
                        pass
                    print()

            elif key_type == 'set':
                # Get set members
                data = await redis.smembers(key)
                print(f"Set data ({len(data)} members):")
                for item in data:
                    print(f"  {item}")
                    try:
                        parsed_item = json.loads(item)
                        print(f"    Parsed: {json.dumps(parsed_item, indent=4)}")
                    except json.JSONDecodeError:
                        pass
                    print()

            elif key_type == 'zset':
                # Get sorted set members with scores
                data = await redis.zrange(key, 0, -1, withscores=True)
                print(f"Sorted set data ({len(data)} members):")
                for member, score in data:
                    dt_object = datetime.fromtimestamp(score, timezone.utc)
                    print(f"  Score: {score} ({dt_object.strftime('%Y-%m-%d %H:%M:%S UTC')})")
                    print(f"  Member: {member}")
                    try:
                        parsed_member = json.loads(member)
                        print(f"    Parsed: {json.dumps(parsed_member, indent=4)}")
                    except json.JSONDecodeError:
                        pass
                    print()

            else:
                print(f"Unsupported key type: {key_type}")

        else:
            print("Key does not exist.")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if redis:
            await redis.close()

if __name__ == "__main__":
    asyncio.run(show_drawings_data())