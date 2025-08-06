
import redis
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
from datetime import datetime, timedelta, timezone
import time
import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State
import numpy as np
import logging

# --- Configuration ---
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
SYMBOL = "BTCUSDT"
TIMEFRAME = "5m"
DATA_DAYS_AGO = 5
INITIAL_USD = 10000
TRADE_PERCENTAGE = 0.05
MAKER_FEE_PERCENTAGE = 0.000550 # 0.0550%
MAX_LEVELS = 5  # 0 to 4

# Configure logging
import sys
import os
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[logging.FileHandler('algoTrade1.log')])

# --- Redis Data Fetching ---
def get_redis_connection():
    """Establishes connection to Redis."""
    try:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
        r.ping()
        logging.info("Successfully connected to Redis.")
        return r
    except redis.exceptions.ConnectionError as e:
        logging.error(f"Could not connect to Redis: {e}")
        return None

def get_sorted_set_key(symbol, resolution):
    """Constructs the key for the sorted set in Redis."""
    return f"zset:kline:{symbol}:{resolution}"

def get_klines_from_redis(r, symbol, resolution, start_ts, end_ts):
    """Fetches klines from Redis as a pandas DataFrame."""
    if not r:
        return pd.DataFrame()
    
    key = get_sorted_set_key(symbol, resolution)
    try:
        klines_json = r.zrangebyscore(key, min=start_ts, max=end_ts)
        if not klines_json:
            logging.warning(f"No data found in Redis for key '{key}' in the specified time range.")
            return pd.DataFrame()
        
        klines_data = [json.loads(k) for k in klines_json]
        df = pd.DataFrame(klines_data)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df = df.set_index('time')
        df = df.sort_index()
        # Ensure columns are correct type
        for col in ['open', 'high', 'low', 'close', 'vol']:
            df[col] = pd.to_numeric(df[col])
        logging.info(f"Successfully fetched {len(df)} klines from Redis.")
        return df
    except Exception as e:
        logging.error(f"Error fetching or processing data from Redis: {e}")
        return pd.DataFrame()

# --- High/Low Detection ---
def find_peaks(series, order=1):
    """
    Finds peaks (highs) and troughs (lows) in a series.
    A peak is a point higher than its `order` neighbors on each side.
    A trough is a point lower than its `order` neighbors on each side.
    Returns two lists of indices: [high_indices], [low_indices]
    """
    highs = []
    lows = []
    for i in range(order, len(series) - order):
        is_high = True
        is_low = True
        for j in range(1, order + 1):
            if series[i] < series[i-j] or series[i] < series[i+j]:
                is_high = False
            if series[i] > series[i-j] or series[i] > series[i+j]:
                is_low = False
        if is_high:
            highs.append(i)
        if is_low:
            lows.append(i)
    return highs, lows

def get_multi_level_peaks(df_close_series, df_full_ref):
    """
    Detects highs and lows for multiple levels.
    Returns a dictionary where keys are levels (0-4) and values are dicts
    of {'highs': [absolute_indices], 'lows': [absolute_indices]}.
    df_close_series: The current slice of the close prices (e.g., df_current['close'])
    df_full_ref: A reference to the full DataFrame (df_full) to get absolute indices
    """
    levels = {}
    
    # Level 0: Most granular, from close price
    # find_peaks returns indices relative to df_close_series.values
    level_0_highs_rel, level_0_lows_rel = find_peaks(df_close_series.values, order=1) 
    
    # Convert relative indices to absolute indices from the original DataFrame
    # This maps the index from the slice back to its original position in df_full_ref
    level_0_highs_abs = [df_full_ref.index.get_loc(df_close_series.index[i]) for i in level_0_highs_rel]
    level_0_lows_abs = [df_full_ref.index.get_loc(df_close_series.index[i]) for i in level_0_lows_rel]
    
    levels[0] = {'highs': level_0_highs_abs, 'lows': level_0_lows_abs}

    # Higher Levels (1-4)
    for i in range(1, MAX_LEVELS):
        prev_high_indices_abs = levels[i-1]['highs']
        prev_low_indices_abs = levels[i-1]['lows']
        
        if len(prev_high_indices_abs) >= 3: # Need at least 3 points for find_peaks with order=1
            # Create a temporary series of prices at these absolute indices from df_full_ref
            temp_high_prices_series = df_full_ref['close'].iloc[prev_high_indices_abs]
            new_highs_rel_to_temp, _ = find_peaks(temp_high_prices_series.values, order=1)
            
            # Map back to absolute indices from df_full_ref
            levels[i] = {'highs': [prev_high_indices_abs[j] for j in new_highs_rel_to_temp]}
        else:
            levels[i] = {'highs': []}

        if len(prev_low_indices_abs) >= 3: # Need at least 3 points for find_peaks with order=1
            temp_low_prices_series = df_full_ref['close'].iloc[prev_low_indices_abs]
            _, new_lows_rel_to_temp = find_peaks(temp_low_prices_series.values, order=1)
            
            levels[i]['lows'] = [prev_low_indices_abs[j] for j in new_lows_rel_to_temp]
        else:
            levels[i]['lows'] = []
            
    return levels

# --- Dash App ---
# Fetch data once at the start
redis_conn = get_redis_connection()
end_ts = int(datetime.now(timezone.utc).timestamp())
start_ts = int((datetime.now(timezone.utc) - timedelta(days=DATA_DAYS_AGO)).timestamp())
df_full = get_klines_from_redis(redis_conn, SYMBOL, TIMEFRAME, start_ts, end_ts)

if df_full.empty:
    logging.error("Could not fetch data. Exiting.")
    exit()

# Levels will be calculated incrementally in the simulation loop.

# Initialize Dash app
app = dash.Dash(__name__)

app.layout = html.Div([
    html.H1(f"Algorithmic Trading Simulation: {SYMBOL}"),
    dcc.Graph(id='price-chart'),
    dcc.Interval(
        id='interval-component',
        interval=1*1000,  # in milliseconds
        n_intervals=0,
        max_intervals=len(df_full) -1
    ),
    html.Div([
        html.Label("Simulation Speed (Wait Time in ms):"),
        dcc.Slider(
            id='speed-slider',
            min=50,
            max=2000,
            step=50,
            value=1000,
            marks={i: str(i) for i in range(200, 2001, 200)},
        )
    ], style={'width': '80%', 'padding-left': '10%'}),
    # Hidden div to store simulation state
    dcc.Store(id='simulation-state', data={
        'usd_balance': INITIAL_USD,
        'btc_balance': 0,
        'position': 'flat', # 'long', 'short'
        'entry_price': 0,
        'trades': [], # List of {'index', 'price', 'type'}
        'net_worth_history': [],
        'usd_balance_history': [],
        'btc_value_history': [],
        'last_trade_close_index': -1, # Initialize to -1, meaning no trade has been closed yet
        'prev_l3_highs': [],
        'prev_l3_lows': []
    })
])

@app.callback(
    Output('interval-component', 'interval'),
    Input('speed-slider', 'value')
)
def update_interval(value):
    return value

@app.callback(
    [Output('price-chart', 'figure'),
     Output('simulation-state', 'data')],
    [Input('interval-component', 'n_intervals')],
    [State('simulation-state', 'data')]
)
def update_chart(n, sim_state):
    if n is None or n < 1:
        return go.Figure(), sim_state

    current_index = n
    df_current = df_full.iloc[:current_index+1]
    current_bar = df_current.iloc[-1]
    current_price = current_bar['close']
    current_timestamp = current_bar.name

    # --- Incremental Level Calculation ---
    # Pass df_full to get_multi_level_peaks to allow it to map relative indices to absolute
    if len(df_current) > 10: # Need a minimum number of bars to find peaks
        current_levels = get_multi_level_peaks(df_current['close'], df_full)
    else:
        current_levels = {i: {'highs': [], 'lows': []} for i in range(MAX_LEVELS)}


    # --- Trading Logic ---
    usd_balance = sim_state['usd_balance']
    btc_balance = sim_state['btc_balance']
    position = sim_state['position']
    entry_price = sim_state['entry_price']
    trades = sim_state['trades']
    
    # Trading Logic
    # --- Trading Logic ---
    usd_balance = sim_state['usd_balance']
    btc_balance = sim_state['btc_balance']
    position = sim_state['position']
    entry_price = sim_state['entry_price']
    trades = sim_state['trades']
    prev_l3_highs = sim_state['prev_l3_highs']
    prev_l3_lows = sim_state['prev_l3_lows']

    new_l3_highs = []
    new_l3_lows = []

    logging.info(f"Current Index: {current_index}")
    logging.info(f"L3 Highs (current): {current_levels[3]['highs']}")
    logging.info(f"L3 Lows (current): {current_levels[3]['lows']}")
    logging.info(f"Prev L3 Highs: {prev_l3_highs}")
    logging.info(f"Prev L3 Lows: {prev_l3_lows}")
    logging.info(f"New L3 Highs: {new_l3_highs}")
    logging.info(f"New L3 Lows: {new_l3_lows}")
    logging.info(f"Position: {position}, Last Trade Close Index: {sim_state['last_trade_close_index']}")

    # Detect newly appeared L3 highs and lows
    new_l3_highs = [h for h in current_levels[3]['highs'] if h not in prev_l3_highs]
    new_l3_lows = [l for l in current_levels[3]['lows'] if l not in prev_l3_lows]

    # Sort new highs/lows by index to process them in chronological order
    new_l3_highs.sort()
    new_l3_lows.sort()

    print(f"DEBUG: Before high_idx loop, new_l3_highs: {new_l3_highs} at current_index: {current_index}")
    # Process new L3 highs/lows that occurred up to the current bar
    for high_idx in new_l3_highs:
        logging.info(f"Processing new L3 high_idx: {high_idx}")
        cond1 = (high_idx <= current_index)
        cond2 = (position == 'flat')
        cond3 = (current_index > sim_state['last_trade_close_index'])
        logging.info(f"Conditions: high_idx <= current_index ({high_idx} <= {current_index}) = {cond1}")
        logging.info(f"Conditions: position == 'flat' ({position} == 'flat') = {cond2}")
        logging.info(f"Conditions: current_index > last_trade_close_index ({current_index} > {sim_state['last_trade_close_index']}) = {cond3}")

        if cond1:
            if cond2 and cond3:
                logging.info(f"All trade opening conditions met for high_idx {high_idx}. Attempting to open SHORT trade.")
                position = 'short'
                trade_amount_usd = usd_balance * TRADE_PERCENTAGE
                btc_to_sell = trade_amount_usd / current_price
                fee_usd = btc_to_sell * current_price * MAKER_FEE_PERCENTAGE
                usd_balance += (btc_to_sell * current_price - fee_usd)  # Add USD from selling, deduct fee
                btc_balance = -btc_to_sell  # BTC balance becomes negative for short
                entry_price = current_price
                trades.append({'index': current_timestamp, 'price': current_price, 'type': 'S'})  # Sell
                logging.info(f"Opened SHORT trade at index {current_index}, price {current_price}")
                break # Only one trade per bar

    for low_idx in new_l3_lows:
        logging.info(f"Processing new L3 low_idx: {low_idx}")
        cond1 = (low_idx <= current_index)
        cond2 = (position == 'flat')
        cond3 = (current_index > sim_state['last_trade_close_index'])
        logging.info(f"Conditions: low_idx <= current_index ({low_idx} <= {current_index}) = {cond1}")
        logging.info(f"Conditions: position == 'flat' ({position} == 'flat') = {cond2}")
        logging.info(f"Conditions: current_index > last_trade_close_index ({current_index} > {sim_state['last_trade_close_index']}) = {cond3}")

        if cond1:
            if cond2 and cond3:
                logging.info(f"All trade opening conditions met for low_idx {low_idx}. Attempting to open LONG trade.")
                position = 'long'
                trade_amount_usd = usd_balance * TRADE_PERCENTAGE
                btc_to_buy = trade_amount_usd / current_price
                fee_usd = btc_to_buy * current_price * MAKER_FEE_PERCENTAGE
                usd_balance -= (btc_to_buy * current_price + fee_usd)  # Deduct USD and fee
                btc_balance += btc_to_buy  # Add BTC
                entry_price = current_price
                trades.append({'index': current_timestamp, 'price': current_price, 'type': 'B'})  # Buy
                logging.info(f"Opened LONG trade at index {current_index}, price {current_price}")
                break # Only one trade per bar
                logging.info(f"Opened LONG trade at index {current_index}, price {current_price}")
                break # Only one trade per bar

    # Update previous L3 highs and lows for the next iteration
    sim_state['prev_l3_highs'] = current_levels[3]['highs']
    sim_state['prev_l3_lows'] = current_levels[3]['lows']

    # --- Position Management (Stop-Loss / Take-Profit based on lower level lines) ---
    # We will use the last two relevant high/low points from the *current_levels*
    # and check if the current price crosses the line formed by them.

    if position == 'long':
        # Check lower levels (0, 1, 2) for closing long trades
        for level in range(MAX_LEVELS - 2): # Iterate for levels 0, 1, 2
            level_lows_abs = [idx for idx in current_levels[level]['lows'] if idx < current_index]
            if len(level_lows_abs) >= 2:
                # Get the last two low points (absolute indices)
                p1_idx = level_lows_abs[-2]
                p2_idx = level_lows_abs[-1]

                # Get their timestamps and prices from the full DataFrame
                x1 = df_full.index[p1_idx].timestamp()
                y1 = df_full['close'].iloc[p1_idx]
                x2 = df_full.index[p2_idx].timestamp()
                y2 = df_full['close'].iloc[p2_idx]

                # Calculate the slope and intercept of the line
                if x2 - x1 != 0:
                    slope = (y2 - y1) / (x2 - x1)
                    intercept = y1 - slope * x1
                    
                    # Calculate the expected price on the line at the current timestamp
                    line_price_at_current_ts = slope * current_timestamp.timestamp() + intercept

                    # If current price crosses below the line, close long
                    if current_price < line_price_at_current_ts:
                        fee_usd = btc_balance * current_price * MAKER_FEE_PERCENTAGE
                        usd_balance += (btc_balance * current_price - fee_usd)
                        btc_balance = 0
                        position = 'flat'
                        trades.append({'index': current_timestamp, 'price': current_price, 'type': 'BC'}) # Buy Close
                        sim_state['last_trade_close_index'] = current_index # Mark trade closed
                        break # Exit loop after closing
            
    elif position == 'short':
        # Check lower levels (0, 1, 2) for closing short trades
        for level in range(MAX_LEVELS - 2): # Iterate for levels 0, 1, 2
            level_highs_abs = [idx for idx in current_levels[level]['highs'] if idx < current_index]
            if len(level_highs_abs) >= 2:
                # Get the last two high points (absolute indices)
                p1_idx = level_highs_abs[-2]
                p2_idx = level_highs_abs[-1]

                # Get their timestamps and prices from the full DataFrame
                x1 = df_full.index[p1_idx].timestamp()
                y1 = df_full['close'].iloc[p1_idx]
                x2 = df_full.index[p2_idx].timestamp()
                y2 = df_full['close'].iloc[p2_idx]

                # Calculate the slope and intercept of the line
                if x2 - x1 != 0:
                    slope = (y2 - y1) / (x2 - x1)
                    intercept = y1 - slope * x1

                    # Calculate the expected price on the line at the current timestamp
                    line_price_at_current_ts = slope * current_timestamp.timestamp() + intercept

                    # If current price crosses above the line, close short
                    if current_price > line_price_at_current_ts:
                        # Calculate P/L and apply fee
                        cost_to_buy_back = abs(btc_balance) * current_price
                        fee_usd = cost_to_buy_back * MAKER_FEE_PERCENTAGE
                        usd_balance -= (cost_to_buy_back + fee_usd)
                        btc_balance = 0
                        position = 'flat'
                        trades.append({'index': current_timestamp, 'price': current_price, 'type': 'SC'}) # Short Close
                        sim_state['last_trade_close_index'] = current_index # Mark trade closed
                        break # Exit loop after closing

    # --- Update State ---
    net_worth = usd_balance
    btc_value_in_usd = 0
    if position == 'long':
        btc_value_in_usd = btc_balance * current_price
        net_worth += btc_value_in_usd
    elif position == 'short':
        # For short, btc_balance is negative, representing BTC owed.
        # The unrealized P/L is (entry_price - current_price) * abs(btc_balance).
        # This P/L is added to the initial USD received from opening the short.
        # The btc_value_in_usd for plotting should represent this P/L.
        btc_value_in_usd = (entry_price - current_price) * abs(btc_balance) # This is the P/L from the short position
        net_worth += btc_value_in_usd

    sim_state['usd_balance'] = usd_balance
    sim_state['btc_balance'] = btc_balance
    sim_state['position'] = position
    sim_state['entry_price'] = entry_price
    sim_state['trades'] = trades
    sim_state['net_worth_history'].append({'time': current_timestamp, 'value': net_worth})
    sim_state['usd_balance_history'].append({'time': current_timestamp, 'value': usd_balance})
    sim_state['btc_value_history'].append({'time': current_timestamp, 'value': btc_value_in_usd})

    # --- Plotting ---
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05,
                        row_heights=[0.7, 0.3])

    # 1. OHLC Chart
    fig.add_trace(go.Candlestick(x=df_current.index,
                                open=df_current['open'],
                                high=df_current['high'],
                                low=df_current['low'],
                                close=df_current['close'],
                                name='OHLC'), row=1, col=1)

    # 2. Multi-level Highs/Lows
    colors = ['blue', 'green', 'red', 'purple', 'orange']
    for i in range(MAX_LEVELS):
        # Highs
        # Filter high_indices to only include those within the current df_current range
        high_indices_current_view = [idx for idx in current_levels[i]['highs'] if idx <= current_index]
        if high_indices_current_view:
            fig.add_trace(go.Scatter(x=df_full.index[high_indices_current_view],
                                     y=df_full['close'].iloc[high_indices_current_view],
                                     mode='markers',
                                     marker=dict(color=colors[i], symbol='triangle-down', size=i*2+5),
                                     name=f'L{i} High'), row=1, col=1)
        # Lows
        # Filter low_indices to only include those within the current df_current range
        low_indices_current_view = [idx for idx in current_levels[i]['lows'] if idx <= current_index]
        if low_indices_current_view:
            fig.add_trace(go.Scatter(x=df_full.index[low_indices_current_view],
                                     y=df_full['close'].iloc[low_indices_current_view],
                                     mode='markers',
                                     marker=dict(color=colors[i], symbol='triangle-up', size=i*2+5),
                                     name=f'L{i} Low'), row=1, col=1)

    # 3. Trade Markers
    buy_trades = [t for t in trades if t['type'] == 'B']
    sell_trades = [t for t in trades if t['type'] == 'S']
    buy_close_trades = [t for t in trades if t['type'] == 'BC']
    sell_close_trades = [t for t in trades if t['type'] == 'SC']

    if buy_trades:
        fig.add_trace(go.Scatter(x=[t['index'] for t in buy_trades],
                                 y=[t['price'] for t in buy_trades],
                                 mode='markers+text',
                                 marker=dict(color='darkgreen', symbol='circle', size=10),
                                 text='B', textposition='bottom center',
                                 name='Buy'), row=1, col=1)
    if sell_trades:
        fig.add_trace(go.Scatter(x=[t['index'] for t in sell_trades],
                                 y=[t['price'] for t in sell_trades],
                                 mode='markers+text',
                                 marker=dict(color='darkred', symbol='circle', size=10),
                                 text='S', textposition='top center',
                                 name='Sell'), row=1, col=1)
    if buy_close_trades:
        fig.add_trace(go.Scatter(x=[t['index'] for t in buy_close_trades],
                                 y=[t['price'] for t in buy_close_trades],
                                 mode='markers+text',
                                 marker=dict(color='orange', symbol='x', size=10),
                                 text='BC', textposition='top center',
                                 name='Buy Close'), row=1, col=1)
    if sell_close_trades:
        fig.add_trace(go.Scatter(x=[t['index'] for t in sell_close_trades],
                                 y=[t['price'] for t in sell_close_trades],
                                 mode='markers+text',
                                 marker=dict(color='purple', symbol='x', size=10),
                                 text='SC', textposition='bottom center',
                                 name='Sell Close'), row=1, col=1)

    # 4. Net Worth Subplot
    net_worth_df = pd.DataFrame(sim_state['net_worth_history'])
    usd_balance_df = pd.DataFrame(sim_state['usd_balance_history'])
    btc_value_df = pd.DataFrame(sim_state['btc_value_history'])

    if not net_worth_df.empty:
        fig.add_trace(go.Scatter(x=net_worth_df['time'], y=net_worth_df['value'],
                                 mode='lines', name='Total Net Worth', line=dict(color='blue')),
                      row=2, col=1)
    if not usd_balance_df.empty:
        fig.add_trace(go.Scatter(x=usd_balance_df['time'], y=usd_balance_df['value'],
                                 mode='lines', name='USD Balance', line=dict(color='green')),
                      row=2, col=1)
    if not btc_value_df.empty:
        fig.add_trace(go.Scatter(x=btc_value_df['time'], y=btc_value_df['value'],
                                 mode='lines', name='BTC Value (USD)', line=dict(color='red')),
                      row=2, col=1)

    fig.update_layout(title_text=f"Simulation at step {n}/{len(df_full)-1}",
                      xaxis_rangeslider_visible=False,
                      legend_orientation="h",
                      legend_yanchor="bottom",
                      legend_y=1.02,
                      legend_xanchor="right",
                      legend_x=1)
    fig.update_yaxes(title_text="Price (USD)", row=1, col=1)
    fig.update_yaxes(title_text="Net Worth (USD)", row=2, col=1)

    return fig, sim_state


if __name__ == '__main__':
    if df_full.empty:
        print("Cannot start server, data is empty.")
    else:
        print("Starting Dash server...")
        print("Open http://127.0.0.1:8050 in your web browser.")
        app.run(debug=True)
