import requests

def get_btc_dominance():
    url = "https://api.coingecko.com/api/v3/global"
    response = requests.get(url)
    data = response.json()
    btc_dominance = data['data']['market_cap_percentage']['btc']
    return btc_dominance

btc_dom = get_btc_dominance()
print(f"BTC Dominance: {btc_dom}%")
