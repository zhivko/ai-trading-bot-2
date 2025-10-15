server side uses AppTradingView2.py.

basic communication with client works through ws endpoint with different message types.
Url to use for testing will be done using puppeteer and navigating to http://192.168.1.52:5000
When using puppeteer use --window-size=1920,1080
There are no existing test files. You should use puppeteer to execute below tests.

Server code is in python in AppTradingView2.py
Client code is in javascript in /static/js directory

To prepare tests you should use puppeteer_tests.js.
Assume server is running - so NEVER! run AppTradingView2.py like for example: python AppTradingView2.py - instead check to see if python is listening on port 5000. We should have python process running on that port.



Test proof as screenshots will be creates inside ./tests/test_[no of test]

Features tests:
1) shows price of btcusdt chart with indicators.
To test this you should navigate to url and confirm you see price chart with indicators.
Wait until OHLC bars are visible in price subplot of plotly chart. 
Proof - take screenshot.

2) remembers user settings of display on web page. 
Wait until OHLC bars are visible in price subplot of plotly chart. 
To test this you should try changing time scale, time range, adding indicators, removing indicators. After reload of a screen valudate last changed user config was correctly saved and it is retrieved with same setting.
Proof screenshot of loaded page.
Proof screenshot of change setting.
Proof screenshot of reload page with change setting.

3) pan inside price chart - usage of pan tool.
Wait until OHLC bars are visible in price subplot of plotly chart. 
To test: click on pan tool - first button in custom toolbox on right panel, and drag on chart subplot in chart div. client should send config message to ws endpoint of application and receive new data and plot new data.
Proof - save two screenshots - first one before pan, second one after pan.

4) zoom inside price chart - usage of zoom tool
Wait until OHLC bars are visible in price subplot of plotly chart. 
To test: click on zoom tool - 6th button in custom toolbox on right panel, and click and drag inside price subplot. client should send config message through ws endpoint of application and new data and plot new data that represent zoomed area
Proof - save two screenshots - first one before zoom, second one after zoom.

5) creation of line shape - usage of line tool
Wait until OHLC bars are visible in price subplot of plotly chart. 
To test: 
Click button Delete all drawings in right panel.
Click on line tool - 3rd button in custom toolbox on right panel.
You should draw line in price subplot of chart. In price subplot click first point, keep mouse down, move to next point also in subplot chart and mouse up.
Be careful to click correct coordinates so they will fall into price subplot.
Line should appear. Shape info in right panel should be populated.
Proof - save two screenshots - first one before line created, second one after line created.

6) click on line open shape properties
Wait until OHLC bars are visible in price subplot of plotly chart. 
To test: cick on pan tool - click on line should select line, In right panel shape properies - id of line should be visible.
Proof - save two screenshots - first one before line clicked, second one after line clicked.

7) edit shape properties
Wait until OHLC bars are visible in price subplot of plotly chart. 
To test: cick on pan tool
Click on existing line - it should select line - in right panel shape properies - id of line should be visible.
Click edit line.
Click "Buy On Cross" checkbox
Click Save button
Reopen page.
Same line with same ID should still be there - confirm it is.
Click edit line.
"Buy On Cross" should be checked - confirm it is checked.
Proof - save screenshot of modified shape properties. Make sure dialog of line apear when you are doing screenshots.

8) zoom in subplots
Wait until OHLC bars are visible in price subplot of plotly.js chart in div 'chart'
To test: cick on pan tool
Note Chart View State in right panel: X-Axis Min, X-Axis Max, Y-Axis Min, Y-Axis Max and remember values
Proof create screenshot before zoom
In price subplot simulate ctrl key and mouse wheel for zooming into price chart
Note Chart View State in right panel: X-Axis Min, X-Axis Max, Y-Axis Min, Y-Axis Max and remember values
Proof create screenshot after zoom
Succesfull test should change X-Axis Min, X-Axis Max, Y-Axis Min, Y-Axis Max