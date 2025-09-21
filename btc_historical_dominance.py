import requests
import pandas as pd
import time

def get_crypto_data():
    url = "https://min-api.cryptocompare.com/data/v2/histoday"
    all_data = []
    current_to = int(time.time())  # current Unix timestamp

    while True:
        params = {
            'fsym': 'BTC',
            'tsym': 'USD',
            'limit': 2000,
            'e': 'CCCAGG',
            'toTs': current_to
        }
        response = requests.get(url, params=params)
        data = response.json()
        
        data_points = data['Data']['Data']
        if not data_points:
            break
        all_data.extend(data_points)
        
        # Find the earliest timestamp in this batch
        valid_times = [dp['time'] for dp in data_points if dp['time'] > 0]
        if not valid_times:
            break
        min_time = min(valid_times)
        current_to = min_time - 86400  # Set toTs to 1 day before the earliest to get next batch (avoid overlap)
    
    df = pd.DataFrame(all_data)
    df.drop_duplicates(subset=['time'], inplace=True)
    df.sort_values('time', inplace=True)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['market_cap'] = df['close'] * df['volumeto']  # Close price * volume (approximation)

    # Filter to remove invalid timestamps before BTC public trading (approx 2010)
    df = df[df['time'] >= pd.Timestamp('2010-01-01')]

    return df[['time', 'market_cap']]

# Get BTC data and calculate dominance
btc_data = get_crypto_data()

# Assuming we already have total market cap data from CoinGecko
total_market_cap = 500000000000  # Example total market cap (in USD)

btc_data['btc_dominance'] = (btc_data['market_cap'] / total_market_cap) * 100

btc_data.to_csv('btc_dominance_cryptocompare.csv', index=False)
print(btc_data.head())
