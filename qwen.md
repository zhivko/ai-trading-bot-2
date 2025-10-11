server side uses AppTradingView2.py.

basic communication with client works through ws endpoint with different message types.
Url to use for testing will be done using puppeteer and navigating to http://192.168.1.52:5000
There are no existing test files. You should use puppeteer to execute below tests.

Server code is in python in AppTradingView2.py
Client code is in javascript in /static/js directory

To prepare tests you should use puppeteer_tests.js.
Assume server is running - you should never run AppTradingView2.py like for example: python AppTradingView2.py

Test proof as screenshots will be creates inside ./tests/test_[no of test]

Features tests:
1) shows price of btcusdt chart with indicators.
To test this you should navigate to url and confirm you see price chart with indicators.
Wait until chart loads. 
Proof - take screenshot.

2) remembers user settings of display on web page. 
Wait until chart loads. To test this you should try changing time scale, time range, adding indicators, removing indicators. After reload of a screen valudate last changed user config was correctly saved and it is retrieved with same setting.
Proof screenshot of loaded page.
Proof screenshot of change setting.
Proof screenshot of reload page with change setting.

3) pan inside price chart - usage of pan tool.
Wait until chart loads. Click on pan tool - first button in custom toolbox on right panel, and drag on chart subplot in chart div. client should send config message to ws endpoint of application and receive new data and plot new data.
Proof - save two screenshots - first one before pan, second one after pan.

4) zoom inside price chart - usage of zoom tool
Wait until chart loads. Click on zoom tool - 6th button in custom toolbox on right panel, and click and drag inside price subplot. client should send config message through ws endpoint of application and new data and plot new data that represent zoomed area
Proof - save two screenshots - first one before zoom, second one after zoom.

5) creation of line shape - usage of line tool
Wait until chart loads. Click on line tool - 3rd button in custom toolbox on right panel, then click first point in price subplot and click second point in price subplot. Line should appear.
Proof - save two screenshots - first one before line created, second one after line created.

6) click on line open shape properties
Wait until chart loads. Click on pan tool - click on line should select line, In right panel shape properies - id of line should be visible.
Proof - save two screenshots - first one before line clicked, second one after line clicked.
