We want to build algorythmic trading strategy in python lets name it algoTrade1.py

We will use this libraries:
ccxt
pandas
import pandas_ta as ta
plotly
All libraries are already installed in venv. Make sure you activate venv before running python.

We have data in local redis server. Use @apptradingview.py to see how to read data from redis.
We will use BTCUSDT symbol
We Will use 5minute timescale 
We will use last 5 days of data so last bar will be last one from redis data

Simulation: 
Our initial value is 10000 USD.
We will start with oldest bar.
Start of the loop.

Each bar in simulation calculate levels acording to this logic:
To detect level 0 (most granular level) of highs and lows, we will use close price of each bar:
    detect lows, we will create marker on chart with CLOSE price on chart where price makes lower lows
    detect highs, we will create marker on chart with CLOSE price on chart where price makes higher highs
To detect level 1 of highs and lows, we will use markers of level 0
To detect level 2 of highs and lows, we will use markers of level 1
To detect level 3 of highs and lows, we will use markers of level 2
To detect level 4 of highs and lows, we will use markers of level 3

Opening trades:
We will wait for local low or local high to happen on level 3.
If High happens we will open short trade. If Low happens we will open long trade.
We will open trade with 5% of our FIAT USD value.
For each bar we will plot data of OHLC price chart, draw traces of level 0, level 1, level 2, level 3, level 4 on same price chart.
Marker with letter B will mark long trade.
Marker with letter S will mark short trade.
If we closed a trade on one bar - we can open new trade soonest in new bar.
You can always close just previously opened an trade.

Closing trades:
In case of long trade if previous line of lower level LOWS trace crosses current price.
In case of short trade if previous line of lower level HIGHS trace crosses current price.
Marker with letter BC will mark long trade.
Marker with letter SC will mark short trade.
Lets add 0.0550% of maker fee to calculation when buying and selling.
Succesfull trades should add USD value, unsuccesfull trade should reduce USD price.

We will wait a predefined wait time (1s initially) and then loop the code.
Include slider to increase or decrease wait time.
Lets include subplot to show netvalue of agent separately trace for BTC in USD, trace for USD, and together together btc in USD + USD.
