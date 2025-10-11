# Puppeteer Tests for AI Trading Bot

This document explains how to run the Puppeteer tests for the AI Trading Bot application.

## Prerequisites

- Node.js and npm installed on your system
- The AI Trading Bot server running at `http://192.168.1.52:5000` (or your configured address)
- Chrome browser (or Chromium) installed (Puppeteer will use this automatically)

## Installation

The Puppeteer dependency should already be installed. If not, run:

```bash
npm install
```

This will install Puppeteer along with all necessary dependencies.

## Running the Tests

### 1. Starting the Server

Before running the tests, make sure the AppTradingView2 server is running:

```bash
cd C:\git\ai-trading-bot-2
python AppTradingView2.py
```

Wait for the server to start and be available at `http://192.168.1.52:5000` (or your configured address).

### 2. Running All Tests

To run all Puppeteer tests:

```bash
node puppeteer_tests.js
```

This will run both test scenarios:
1. BTCUSDT chart with indicators
2. Remembering user settings across page reloads

### 3. Running Individual Tests

You can also run individual tests by importing and calling them in a separate script:

```javascript
const { testBtcusdtChartWithIndicators, testRememberingUserSettings } = require('./puppeteer_tests');

// Run just the BTCUSDT chart test
testBtcusdtChartWithIndicators()
  .then(result => console.log('BTCUSDT Chart Test Result:', result))
  .catch(err => console.error('BTCUSDT Chart Test Error:', err));

// Run just the settings test
testRememberingUserSettings()
  .then(result => console.log('Settings Test Result:', result))
  .catch(err => console.error('Settings Test Error:', err));
```

## Test Details

### 1. BTCUSDT Chart with Indicators Test

This test:
1. Navigates to the trading view page
2. Waits for the chart to load with historical data
3. Verifies that indicators are displayed on the chart
4. Takes a screenshot of the loaded chart

### 2. Remembering User Settings Test

This test:
1. Navigates to the trading view page
2. Changes time scale, time range, and adds/removes indicators
3. Reloads the page
4. Verifies that the settings were correctly saved and retrieved
5. Takes screenshots before and after the reload

## What the Tests Check

- **Chart Loading**: That the chart element appears and loads data
- **Indicators Display**: That indicators are visible on the chart
- **Settings Persistence**: That user changes to time scale, range, and indicators are preserved after page reload
- **WebSocket Connection**: That the WebSocket connection to the server is established and working
- **UI Elements**: That key UI controls are accessible and functional

## Test Results

Test results will be saved in the `test_results/` directory, including screenshots for verification.

- `btcusdt_chart_with_indicators.png` - Screenshot of the BTCUSDT chart with indicators
- `settings_after_reload.png` - Screenshot showing settings after page reload

## Troubleshooting

### Common Issues

1. **Server not reachable**: Make sure the AppTradingView2 server is running at the expected URL.
2. **Timeout errors**: Increase the timeout values in the test file if your system is slower.
3. **Chrome/Chromium issues**: Ensure Chrome or Chromium is installed, or run with headless mode.

### Headless Mode

To run tests in headless mode (without showing the browser), modify the puppeteer_tests.js file by changing:
```javascript
browser = await puppeteer.launch({
    headless: true,  // Change to true to run in headless mode
    // ...
});
```

## Notes

- The tests assume the server is running at `http://192.168.1.52:5000`
- Tests will open browser windows unless run in headless mode
- Make sure the Redis server is running as settings are stored there
- The tests include appropriate waits to ensure elements are loaded before proceeding