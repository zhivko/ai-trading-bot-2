import asyncio
from redis.asyncio import Redis
from datetime import datetime, timezone

async def check_scores():
    try:
        redis = Redis(host='localhost', port=6379, db=0, decode_responses=True)
        await redis.ping()

        key = 'zset:kline:BTCUSDT:1m'
        print('Checking scores for', key)

        # Get all scores
        members_with_scores = await redis.zrange(key, 0, -1, withscores=True)
        print('Total members:', len(members_with_scores))

        if members_with_scores:
            print('First 3 scores:')
            for i, (member, score) in enumerate(members_with_scores[:3]):
                dt = datetime.fromtimestamp(score, timezone.utc)
                print(f'  Score {i+1}: {int(score)} -> {dt.strftime("%Y-%m-%d %H:%M:%S UTC")}')

            print('Last 3 scores:')
            last_three = members_with_scores[-3:]
            for i, (member, score) in enumerate(last_three):
                dt = datetime.fromtimestamp(score, timezone.utc)
                print(f'  Score {i+1}: {int(score)} -> {dt.strftime("%Y-%m-%d %H:%M:%S UTC")}')

            # Check ranges
            queried_min = 1759682627
            queried_max = 1759705951
            print(f'\nQueried range: [{queried_min}, {queried_max}]')
            qt1 = datetime.fromtimestamp(queried_min, timezone.utc)
            qt2 = datetime.fromtimestamp(queried_max, timezone.utc)
            print('Queried dates:', qt1.strftime('%Y-%m-%d %H:%M:%S UTC'), 'to', qt2.strftime('%Y-%m-%d %H:%M:%S UTC'))

            actual_min = members_with_scores[0][1]
            actual_max = members_with_scores[-1][1]
            at1 = datetime.fromtimestamp(actual_min, timezone.utc)
            at2 = datetime.fromtimestamp(actual_max, timezone.utc)
            print('Actual data dates:', at1.strftime('%Y-%m-%d %H:%M:%S UTC'), 'to', at2.strftime('%Y-%m-%d %H:%M:%S UTC'))

            # Check if ranges overlap
            overlap = max(0, min(queried_max, actual_max) - max(queried_min, actual_min))
            print(f'Range overlap (seconds): {overlap}')

            if overlap == 0:
                print('NO OVERLAP! The queried range does not intersect with the actual data range.')
            else:
                print(f'OVERLAP EXISTS: {overlap} seconds of overlap')

            # Test zrangebyscore directly
            print('\nTesting zrangebyscore directly...')
            test_result = await redis.zrangebyscore(key, min=queried_min, max=queried_max, withscores=True)
            print(f'zrangebyscore result count: {len(test_result)}')

            if test_result:
                print('Sample result (first one):')
                member, score = test_result[0]
                dt = datetime.fromtimestamp(score, timezone.utc)
                print(f'  Score: {int(score)} -> {dt.strftime("%Y-%m-%d %H:%M:%S UTC")}')
            else:
                print('zrangebyscore returned empty even though overlap exists!')

            # Check if there are scores >= queried_min
            count_ge_min = await redis.zcount(key, queried_min, '+inf')
            print(f'Count of scores >= {queried_min}: {count_ge_min}')

            # Check if there are scores <= queried_max
            count_le_max = await redis.zcount(key, '-inf', queried_max)
            print(f'Count of scores <= {queried_max}: {count_le_max}')

        await redis.close()
    except Exception as e:
        print('Error:', e)

if __name__ == "__main__":
    asyncio.run(check_scores())
