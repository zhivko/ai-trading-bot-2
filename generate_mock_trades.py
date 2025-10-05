#!/usr/bin/env python3
"""
Generate mock trade data for testing the trade history visualization
"""

import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

import redis_utils

def generate_mock_trades():
    """Generate realistic mock trade data"""

    # Create mock trades with varying sizes and prices around BTC/USDT price
    base_price = 95000  # BTC price in USD
    base_time = datetime.now() - timedelta(hours=24)  # Last 24 hours

    mock_trades = []

    for i in range(20):  # Generate 20 mock trades
        # Vary price slightly (±2% of base price)
        price_variation = random.uniform(-0.02, 0.02)
        price = base_price * (1 + price_variation)

        # Random trade size (0.001 to 0.1 BTC)
        size = random.uniform(0.001, 0.1)

        # Random timestamp within last 24 hours
        time_offset = random.uniform(0, 24*60*60)  # seconds
        trade_time = base_time + timedelta(seconds=time_offset)

        # Random side (60% buy, 40% sell for more realistic distribution)
        side = 'BUY' if random.random() < 0.6 else 'SELL'

        trade = {
            'id': f'mock_trade_{i+1}',
            'symbol': 'BTCUSDT',
            'price': round(price, 2),
            'size': round(size, 6),
            'quantity': round(size, 6),
            'qty': round(size, 6),
            'side': side,
            'timestamp': int(trade_time.timestamp() * 1000),
            'time': int(trade_time.timestamp() * 1000),
            'datetime': trade_time.isoformat() + 'Z',
            'isBuyerMaker': side == 'SELL',  # Bybit convention
        }

        mock_trades.append(trade)

    # Sort trades by timestamp
    mock_trades.sort(key=lambda x: x['timestamp'])

    return mock_trades


def save_mock_trades_to_file():
    """Save mock trades to a file that can be loaded by the system"""

    mock_trades = generate_mock_trades()

    mock_data = {
        'status': 'success',
        'data': mock_trades,
        'source': 'mock_data',
        'timestamp': datetime.now().isoformat()
    }

    filename = 'mock_trades.json'
    with open(filename, 'w') as f:
        json.dump(mock_data, f, indent=2, default=str)

    print(f"Generated {len(mock_trades)} mock trades and saved to {filename}")

    # Show sample
    print("\nSample trade data:")
    if mock_trades:
        sample = mock_trades[0]
        for key, value in sample.items():
            print(f"  {key}: {value}")

    return mock_data

def inject_mock_trades_into_redis():
    """Try to inject mock trades into Redis for real-time testing"""

    try:
        r = redis_utils.get_sync_redis_connection()

        mock_trades = generate_mock_trades()

        # Store in Redis with a key that the frontend can access
        redis_key = "mock:trade_history:BTCUSDT"

        # Convert to JSON string
        trades_json = json.dumps(mock_trades, default=str)

        # Store in Redis with expiry (24 hours)
        r.setex(redis_key, 86400, trades_json)

        print(f"Injected {len(mock_trades)} mock trades into Redis key: {redis_key}")

        # Also store as individual trade keys for WebSocket access
        for i, trade in enumerate(mock_trades):
            trade_key = f"trade:{trade['id']}"
            r.setex(trade_key, 86400, json.dumps(trade, default=str))

        print(f"Also stored {len(mock_trades)} individual trade keys")

        return True

    except Exception as e:
        print(f"Error injecting mock trades to Redis: {e}")
        print("Make sure Redis is running and redis_utils.py is properly configured")
        return False

if __name__ == "__main__":
    print("Generating mock trade data for testing...")

    # Generate and save to file
    mock_data = save_mock_trades_to_file()

    print("\nAttempting to inject into Redis...")
    redis_success = inject_mock_trades_into_redis()

    if redis_success:
        print("\n✅ Mock trade data successfully generated and injected!")
        print("\nNext steps:")
        print("1. Restart your trading visualization application")
        print("2. Check the trade history visualization - you should now see 20 trades")
        print("3. The trades will show volume profile and trade markers on the chart")
    else:
        print("\n⚠️  Mock trades saved to file but Redis injection failed.")
        print("To use the mock data, you can manually load the mock_trades.json file")

    print("\nMock trades generated successfully!")
