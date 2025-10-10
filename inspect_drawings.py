import asyncio
import json
from redis_utils import get_redis_connection

async def inspect_drawings():
    redis = await get_redis_connection()
    async for key in redis.scan_iter(match="drawings:*"):
        key_str = key.decode('utf-8') if isinstance(key, bytes) else key
        print(f"Inspecting key: {key_str}")

        drawing_data = await redis.get(key_str)
        if not drawing_data:
            print(f"  No data for {key_str}")
            continue

        try:
            user_drawings = json.loads(drawing_data)
            if not isinstance(user_drawings, list):
                print(f"  Invalid data type for {key_str}: {type(user_drawings)}")
                continue

            print(f"  {len(user_drawings)} drawings")
            corrupted = []
            for i, drawing in enumerate(user_drawings):
                if not isinstance(drawing, dict):
                    print(f"    Drawing {i}: not a dict")
                    continue
                drawing_id = drawing.get('id', f'index_{i}')
                start_time = drawing.get('start_time')
                end_time = drawing.get('end_time')
                print(f"    Drawing {drawing_id}: start_time={start_time} ({type(start_time)}), end_time={end_time} ({type(end_time)})")
                if start_time is None or end_time is None:
                    print(f"    Corrupted drawing {drawing_id}: start_time={start_time}, end_time={end_time}")
                    corrupted.append(drawing_id)

            if corrupted:
                print(f"  Corrupted drawings in {key_str}: {corrupted}")
            else:
                print(f"  No corrupted drawings in {key_str}")

        except json.JSONDecodeError as e:
            print(f"  Invalid JSON in {key_str}: {e}")

if __name__ == "__main__":
    asyncio.run(inspect_drawings())