import os
import pandas as pd
import yfinance as yf
from ta.momentum import RSIIndicator, StochRSIIndicator
from ta.trend import MACD
from ta.volatility import BollingerBands
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta

# Step 1: Load or fetch data
csv_file = 'btcusdtHistory.csv'
end_date = datetime(2025, 7, 15)
start_date = end_date - timedelta(days=5*365)

if not os.path.exists(csv_file):
    print("Fetching 5 years of BTC-USD data...")
    df = yf.download('BTC-USD', start=start_date, end=end_date, interval='1d')
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].reset_index()
    df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    df.to_csv(csv_file, index=False)
else:
    print("Using existing CSV file.")
    df = pd.read_csv(csv_file, parse_dates=['timestamp'])

# Step 2: Add indicators
df['rsi'] = RSIIndicator(df['close'], window=14).rsi()
stoch_rsi = StochRSIIndicator(df['close'], window=14, smooth1=3, smooth2=3)
df['sto_rsi'] = stoch_rsi.stochrsi() * 100  # Normalize to 0-100
df['sto_rsi_d'] = stoch_rsi.stochrsi_d() * 100  # Signal line (unused directly)
macd = MACD(df['close'])
df['macd'] = macd.macd()
df['macd_signal'] = macd.macd_signal()
df['macd_hist'] = macd.macd_diff()
bb = BollingerBands(df['close'])
df['bb_upper'] = bb.bollinger_hband()
df['bb_middle'] = bb.bollinger_mavg()
df['bb_lower'] = bb.bollinger_lband()

# Drop NaNs
df = df.dropna().reset_index(drop=True)

# Trading Logic: Backtest (now with longs and shorts)
initial_balance = 10000
balance = initial_balance
positions = []  # Track open trades: {'type': 'long/short', 'open_idx': i, 'open_price': p, 'size': s, 'sl': sl}
trades = []  # Completed trades for markers: + 'type'
net_values = [initial_balance] * len(df)  # For net value plot

for i in range(1, len(df)):  # Start from 1 to check previous
    net_values[i] = net_values[i-1]  # Carry forward
    
    # Close open positions first (based on STO RSI)
    closed = []
    for pos in positions:
        if (pos['type'] == 'long' and df['sto_rsi'][i] < 50) or (pos['type'] == 'short' and df['sto_rsi'][i] > 50):
            close_price = df['close'][i]
            if pos['type'] == 'long':
                pnl_pct = (close_price - pos['open_price']) / pos['open_price']
            else:  # Short
                pnl_pct = (pos['open_price'] - close_price) / pos['open_price']
            pnl = pos['size'] * pnl_pct  # Leveraged size
            balance += pnl
            trades.append({'type': pos['type'], 'open_idx': pos['open_idx'], 'close_idx': i, 'pnl': pnl})
            closed.append(pos)
    positions = [p for p in positions if p not in closed]
    
    # Open new long if conditions met
    mid_candle = (df['open'][i] + df['close'][i]) / 2
    if (mid_candle > df['bb_middle'][i] and
        df['rsi'][i] > 50 and
        df['sto_rsi'][i-1] <= df['rsi'][i-1] and df['sto_rsi'][i] > df['rsi'][i]):  # STO RSI crosses above RSI
        
        # Check previous 5 bars: signal NOT below MACD (signal >= MACD in all)
        prev_bars_ok = all(df['macd_signal'][j] >= df['macd'][j] for j in range(max(0, i-5), i))
        if prev_bars_ok:
            trade_size = 0.1 * balance * 3  # 10% of balance, 3x leverage
            open_price = df['close'][i]
            sl = df['close'][i-1] * 0.95  # 5% below prev close
            positions.append({'type': 'long', 'open_idx': i, 'open_price': open_price, 'size': trade_size, 'sl': sl})
    
    # Open new short if inverse conditions met
    if (mid_candle < df['bb_middle'][i] and
        df['rsi'][i] < 50 and
        df['sto_rsi'][i-1] >= df['rsi'][i-1] and df['sto_rsi'][i] < df['rsi'][i]):  # STO RSI crosses below RSI
        
        # Check previous 5 bars: signal NOT above MACD (signal <= MACD in all)
        prev_bars_ok = all(df['macd_signal'][j] <= df['macd'][j] for j in range(max(0, i-5), i))
        if prev_bars_ok:
            trade_size = 0.1 * balance * 3  # 10% of balance, 3x leverage (short)
            open_price = df['close'][i]
            sl = df['close'][i-1] * 1.05  # 5% above prev close
            positions.append({'type': 'short', 'open_idx': i, 'open_price': open_price, 'size': trade_size, 'sl': sl})
    
    # Check SL hits
    closed = []
    for pos in positions:
        if (pos['type'] == 'long' and df['low'][i] <= pos['sl']) or (pos['type'] == 'short' and df['high'][i] >= pos['sl']):
            close_price = pos['sl'] if (pos['type'] == 'long' and df['low'][i] <= pos['sl']) else (pos['sl'] if pos['type'] == 'short' else df['open'][i])
            if pos['type'] == 'long':
                pnl_pct = (close_price - pos['open_price']) / pos['open_price']
            else:
                pnl_pct = (pos['open_price'] - close_price) / pos['open_price']
            pnl = pos['size'] * pnl_pct
            balance += pnl
            trades.append({'type': pos['type'], 'open_idx': pos['open_idx'], 'close_idx': i, 'pnl': pnl})
            closed.append(pos)
    positions = [p for p in positions if p not in closed]
    
    # Update net value with unrealized PnL
    unrealized = 0
    for pos in positions:
        if pos['type'] == 'long':
            pnl_pct = (df['close'][i] - pos['open_price']) / pos['open_price']
        else:
            pnl_pct = (pos['open_price'] - df['close'][i]) / pos['open_price']
        unrealized += pos['size'] * pnl_pct
    net_values[i] = balance + unrealized

df['net_value'] = net_values

# Step 3-5: Construct charts with subplots
fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.05,
                    subplot_titles=('Price with BB', 'RSI and StoRSI', 'MACD', 'Net Value'),
                    row_heights=[0.4, 0.2, 0.2, 0.2])

# Price chart with OHLC candles and BB
fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'],
                             name='Price'), row=1, col=1)
fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_upper'], name='BB Upper', line=dict(color='blue')), row=1, col=1)
fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_middle'], name='BB Middle', line=dict(color='black')), row=1, col=1)
fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_lower'], name='BB Lower', line=dict(color='blue')), row=1, col=1)

# Add trade markers (green triangles for all long trades, red for all short trades; up for buys, down for sells)
for trade in trades:
    if trade['type'] == 'long':
        # Long open: green up-triangle below low (buy)
        fig.add_annotation(x=df['timestamp'][trade['open_idx']], y=df['low'][trade['open_idx']], text='▲', showarrow=True,
                           arrowhead=2, arrowsize=1, arrowwidth=2, arrowcolor='green', ax=0, ay=20, row=1, col=1)
        # Long close: green down-triangle above high (sell)
        fig.add_annotation(x=df['timestamp'][trade['close_idx']], y=df['high'][trade['close_idx']], text='▼', showarrow=True,
                           arrowhead=2, arrowsize=1, arrowwidth=2, arrowcolor='green', ax=0, ay=-20, row=1, col=1)
    else:  # Short
        # Short open: red down-triangle above high (sell)
        fig.add_annotation(x=df['timestamp'][trade['open_idx']], y=df['high'][trade['open_idx']], text='▼', showarrow=True,
                           arrowhead=2, arrowsize=1, arrowwidth=2, arrowcolor='red', ax=0, ay=-20, row=1, col=1)
        # Short close: red up-triangle below low (buy)
        fig.add_annotation(x=df['timestamp'][trade['close_idx']], y=df['low'][trade['close_idx']], text='▲', showarrow=True,
                           arrowhead=2, arrowsize=1, arrowwidth=2, arrowcolor='red', ax=0, ay=20, row=1, col=1)

# RSI and StoRSI chart
fig.add_trace(go.Scatter(x=df['timestamp'], y=df['rsi'], name='RSI', line=dict(color='purple')), row=2, col=1)
fig.add_trace(go.Scatter(x=df['timestamp'], y=df['sto_rsi'], name='StoRSI', line=dict(color='orange')), row=2, col=1)
fig.add_hline(y=50, line_dash="dash", line_color="gray", row=2, col=1)

# MACD chart with histogram
fig.add_trace(go.Scatter(x=df['timestamp'], y=df['macd'], name='MACD', line=dict(color='blue')), row=3, col=1)
fig.add_trace(go.Scatter(x=df['timestamp'], y=df['macd_signal'], name='Signal', line=dict(color='orange')), row=3, col=1)
fig.add_trace(go.Bar(x=df['timestamp'], y=df['macd_hist'], name='Histogram', marker_color='gray'), row=3, col=1)

# Net Value chart
fig.add_trace(go.Scatter(x=df['timestamp'], y=df['net_value'], name='Net Value', line=dict(color='green')), row=4, col=1)

# Layout
fig.update_layout(title='BTCUSDT Trading Backtest (Longs + Shorts)', xaxis_rangeslider_visible=False, height=1200)
fig.update_xaxes(title_text='Date', row=4, col=1)
fig.update_yaxes(title_text='Price (USD)', row=1, col=1)
fig.update_yaxes(title_text='Value', row=2, col=1)
fig.update_yaxes(title_text='Value', row=3, col=1)
fig.update_yaxes(title_text='Net Value (USD)', row=4, col=1)

fig.write_html('btcusdt_chart.html')
print("Chart saved as btcusdt_chart.html. Open in browser to view.")
print(f"Final Net Value: ${df['net_value'].iloc[-1]:.2f}")