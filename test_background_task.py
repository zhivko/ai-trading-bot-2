import asyncio
from background_tasks import fetch_and_publish_klines
from config import timeframe_config

async def test_kline_fetch():
    """Test the kline fetching for 1h resolution."""
    print("Testing kline fetch for 1h resolution...")

    # Check if 1h is in supported resolutions
    print(f"Supported resolutions: {timeframe_config.supported_resolutions}")
    print(f"1h in supported: {'1h' in timeframe_config.supported_resolutions}")

    # Run one cycle of the fetch task
    try:
        await fetch_and_publish_klines()
    except Exception as e:
        print(f"Error running fetch task: {e}")

if __name__ == "__main__":
    asyncio.run(test_kline_fetch())