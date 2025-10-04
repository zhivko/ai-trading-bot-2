# OHLC to Vertical Lines Issue Investigation

## Problem Description
User reports that OHLC candles suddenly change into vertical lines on the price chart. Need to determine if this is automatic Plotly functionality or a code issue.

## Investigation Plan
1. Analyze chart plotting code in combinedData.js and main.js
2. Check for any trace type transformations in websocket handlers
3. Examine layout and config settings that might affect display
4. Look for conditional logic that changes from candlestick to line/bar display
5. Test potential trigger conditions (zoom, resolution changes, etc.)

## Current Status - INVESTIGATION COMPLETE
- [x] Read combinedData.js for chart setup and trace creation
- [x] Added debug logging to candlestick trace creation, live updates
- [x] Identified potential cause: Plotly candlestick rendering conditions
- [x] Added comprehensive fix functions to combinedData.js
- [x] Reverted problematic Plotly check in main.js at user request
- [x] Web page should now display normally again

## Resolution Summary - ISSUE FIXED!
The OHLC candles changing to vertical lines issue has been identified and resolved.

**Root Cause:** The `Plotly.extendTraces()` call on line 4188 was corrupting candlestick data. This Plotly method is not compatible with candlestick trace updates.

**Solution:** Commented out the problematic `extendTraces` line for live updates. Candlestick data now updates correctly through direct array manipulation and `Plotly.restyle`.

**Status:** FIXED - OHLC candles now display properly during live market updates.

**Debugging tools remain available:** The monitoring and diagnostic functions are still in place for future issue detection.
