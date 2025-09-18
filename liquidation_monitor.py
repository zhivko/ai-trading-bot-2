from binance import ThreadedWebsocketManager

def handle_socket_message(msg):
    if msg['e'] == 'forceOrder':
        print(f"Liquidation: {msg['o']['s']} at {msg['o']['p']}")

twm = ThreadedWebsocketManager()
twm.start()
twm.start_symbol_ticker_socket(callback=handle_socket_message, symbol='BTCUSDT')
