import requests
print('Checking if trading service is running...')

try:
    response = requests.get('http://localhost:8000/account', timeout=5)
    print('Trading service response:', response.status_code)

    if response.status_code == 200:
        data = response.json()
        print('Message:', data.get('message', 'OK'))

        # Test trade history endpoint
        print('\nTesting trade-history endpoint...')
        trade_response = requests.get('http://localhost:8000/trade-history?symbol=BTC-USDT&limit=10', timeout=5)

        if trade_response.status_code == 200:
            trade_data = trade_response.json()
            print('Trade history status:', trade_data.get('status'))
            trades = trade_data.get('data', [])
            print('Number of trades:', len(trades))

            if trades:
                print('Sample trade:')
                for key, value in trades[0].items():
                    print(f'  {key}: {value}')
            else:
                print('No trades returned')
        else:
            print('Trade history endpoint failed:', trade_response.status_code, trade_response.text)

    else:
        print('Account endpoint failed:', response.status_code, response.text)

except Exception as e:
    print('Trading service not running or error:', e)
