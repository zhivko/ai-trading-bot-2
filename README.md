We want to build algorythmic trading strategy in python lets name it algoTrade1.py

We will use this libraries:
ccxt
pandas
import pandas_ta as ta
plotly
We have data in local redis server. Use @apptradingview.py to see how to read data from redis.
We will use BTCUSDT symbol
We Will use 5minute timescale 
We will use last 2 years of data so last bar will be last one from redis data
To detect level 0 (most granular level) of highs and lows, we will use close price of each bar:
    detect lows, we will create marker on chart with CLOSE price on chart where price makes lower lows
    detect highs, we will create marker on chart with CLOSE price on chart where price makes higher highs
To detect level 1 of highs and lows, we will use markers of level 0
To detect level 2 of highs and lows, we will use markers of level 1
To detect level 3 of highs and lows, we will use markers of level 2
To detect level 4 of highs and lows, we will use markers of level 3
lets plot data of OHLC price chart, lets connectdra traces of level 0, level 1, level 2, level 3, level 4