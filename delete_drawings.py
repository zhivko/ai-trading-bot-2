import asyncio
from redis.asyncio import Redis as AsyncRedis

async def delete_drawings():
    """Delete the specific drawings key from Redis."""
    redis = None
    try:
        redis = AsyncRedis(host='localhost', port=6379, db=0, decode_responses=True)
        await redis.ping()

        key = "drawings:klemenzivkovic@gmail.com:BTCUSDT"
        print(f"Deleting Redis key: {key}")

        # Check if key exists before deletion
        exists = await redis.exists(key)
        if exists:
            # Delete the key
            result = await redis.delete(key)
            if result == 1:
                print("Successfully deleted the drawings key")
            else:
                print("Failed to delete the key")
        else:
            print("Key does not exist - nothing to delete")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if redis:
            await redis.aclose()

if __name__ == "__main__":
    asyncio.run(delete_drawings())