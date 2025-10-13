applyAutoscale function is not scaling ALL indicators - make sure all indicators and price gets autoscaled in function. Code is in \\static\\js\\main.js.





Autoscale: X-axis range: 2025-10-12T12:21:48.243Z to 2025-10-14T06:01:48.243Z

main.js:1584 Autoscale: Processing main y-axis trace: Buy Trades, type: scatter

4main.js:1608 Autoscale: OHLC value is not an array in candlestick trace Buy Trades

(anonymous) @ main.js:1608

(anonymous) @ main.js:1587

applyAutoscale @ main.js:1581

(anonymous) @ main.js:2306Understand this warning

main.js:1615 Autoscale: Processing trace.y for Buy Trades, 4720 values

main.js:1584 Autoscale: Processing main y-axis trace: Sell Trades, type: scatter

4main.js:1608 Autoscale: OHLC value is not an array in candlestick trace Sell Trades

(anonymous) @ main.js:1608

(anonymous) @ main.js:1587

applyAutoscale @ main.js:1581

(anonymous) @ main.js:2306Understand this warning

main.js:1615 Autoscale: Processing trace.y for Sell Trades, 5280 values

main.js:1584 Autoscale: Processing main y-axis trace: Price, type: candlestick

main.js:1589 Autoscale: Processing OHLC open, 309 values

main.js:1589 Autoscale: Processing OHLC high, 309 values

main.js:1589 Autoscale: Processing OHLC low, 309 values

main.js:1589 Autoscale: Processing OHLC close, 309 values

main.js:1634 Autoscale: Skipping indicator trace: MACD on y2

main.js:1634 Autoscale: Skipping indicator trace: MACD Signal on y2

main.js:1634 Autoscale: Skipping indicator trace: MACD Histogram on y2

main.js:1634 Autoscale: Skipping indicator trace: RSI on y3

main.js:1634 Autoscale: Skipping indicator trace: StochRSI K (9,3) on y4

main.js:1634 Autoscale: Skipping indicator trace: StochRSI D (9,3) on y4

main.js:1634 Autoscale: Skipping indicator trace: StochRSI K (14,3) on y5

main.js:1634 Autoscale: Skipping indicator trace: StochRSI D (14,3) on y5

main.js:1634 Autoscale: Skipping indicator trace: StochRSI K (40,4) on y6

main.js:1634 Autoscale: Skipping indicator trace: StochRSI D (40,4) on y6

main.js:1634 Autoscale: Skipping indicator trace: StochRSI K (60,10) on y7

main.js:1634 Autoscale: Skipping indicator trace: StochRSI D (60,10) on y7

main.js:1634 Autoscale: Skipping indicator trace: CTO Upper on y8

main.js:1634 Autoscale: Skipping indicator trace: CTO Lower on y8

main.js:1634 Autoscale: Skipping indicator trace: CTO Trend on y8

main.js:1656 Autoscale: After processing - yDataFound: true, yMin: 49752.75, yMax: 115950.6

main.js:1668 Autoscale: Final price range - yDataFound: true, priceChartYMin: 49752.75, priceChartYMax: 115950.6

main.js:1681 Autoscale: Calculated range - yPadding: 3309.8925000000004, finalYMin: 46442.8575, finalYMax: 119260.49250000001

main.js:1693 Autoscale: Setting Y-axis range to: 46442.8575 to 119260.49250000001

main.js:1713 Autoscale: Applying layout update: {yaxis.range\[0]: 46442.8575, yaxis.range\[1]: 119260.49250000001, yaxis.autorange: false}

main.js:1732 Autoscale: Updated display elements and saved Y-axis range to window.currentYAxisRange

settingsManager.js:429 {

&nbsp;	"symbol": "BTCUSDT",

&nbsp;	"resolution": "5m",

&nbsp;	"range": "30d",

&nbsp;	"xAxisMin": 1760271708243,

&nbsp;	"xAxisMax": 1760421708243,

&nbsp;	"yAxisMin": 49752.75,

&nbsp;	"yAxisMax": 115950.6,

&nbsp;	"replayFrom": "",

&nbsp;	"replayTo": "",

&nbsp;	"replaySpeed": "1",

&nbsp;	"useLocalOllama": false,

&nbsp;	"localOllamaModelName": "",

&nbsp;	"active\_indicators": \[

&nbsp;		"macd",

&nbsp;		"rsi",

&nbsp;		"stochrsi\_9\_3",

&nbsp;		"stochrsi\_14\_3",

&nbsp;		"stochrsi\_40\_4",

&nbsp;		"stochrsi\_60\_10",

&nbsp;		"cto\_line"

&nbsp;	],

&nbsp;	"liveDataEnabled": true,

&nbsp;	"showAgentTrades": false,

&nbsp;	"streamDeltaTime": 0,

&nbsp;	"last\_selected\_symbol": "BTCUSDT",

&nbsp;	"minValueFilter": 0.2,

&nbsp;	"email": "klemenzivkovic@gmail.com"

}

main.js:1737 Autoscale: Settings saved

main.js:1749 Autoscale: COMPLETED

