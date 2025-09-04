// Combined data WebSocket handler for historical OHLC + indicators + live data

let combinedWebSocket = null;
let combinedSymbol = '';
let combinedIndicators = [];
let combinedResolution = '1h';
let combinedFromTs = null;
let combinedToTs = null;

// Historical data accumulation state
let accumulatedHistoricalData = [];
let isAccumulatingHistorical = false;
let historicalDataSymbol = '';
let accumulationTimeout = null;

// Real-time price line management functions
function updateOrAddRealtimePriceLine(gd, price, candleStartTimeMs, candleEndTimeMs, doRelayout = false) {
    // Make function globally available
    window.updateOrAddRealtimePriceLine = updateOrAddRealtimePriceLine;
    if (!gd || !gd.layout) {
        // console.warn("[PriceLine] Chart or layout not ready.");
        return;
    }

    // Ensure layout exists
    if (!gd.layout) {
        gd.layout = {};
    }

    let shapes = gd.layout.shapes || [];
    let annotations = gd.layout.annotations || [];
    // Ensure annotations is always an array
    if (!Array.isArray(annotations)) {
        annotations = [];
        gd.layout.annotations = annotations;
    }

    shapes = shapes.filter(shape => shape.name !== CROSSHAIR_VLINE_NAME); // Assumes CROSSHAIR_VLINE_NAME is global

    let lineIndex = shapes.findIndex(shape => shape.name === REALTIME_PRICE_LINE_NAME); // Assumes REALTIME_PRICE_LINE_NAME is global
    try {
        // Determine the correct y-axis reference for the price chart
        // When indicators are present, price chart is on yaxis1, otherwise on y
        const hasIndicators = window.gd && window.gd.data && window.gd.data.some(trace => trace.type !== 'candlestick');
        const yref = hasIndicators ? 'yaxis1' : 'y';

        const lineDefinition = {
                type: 'line',
                name: REALTIME_PRICE_LINE_NAME,
                isSystemShape: true, // Mark as a system shape
                yref: yref,
                x0ref: 'x',
                x1ref: 'paper',
                x0: new Date(candleEndTimeMs),
                y0: price,
                x1: 1,
                y1: price,
                line: {
                    color: 'rgba(0, 0, 0, 0.9)',
                    width: 1.5,
                    dash: 'solid'
                },
                layer: 'above',
                editable: false // Explicitly make this system shape not editable by Plotly
        };

        if (typeof price !== 'number' || isNaN(price)) {
            // console.error("[PriceLine] Invalid price for annotation:", price, "(type:", typeof price, ")");
            // Optionally remove any existing price annotation if the new price is invalid
            gd.layout.annotations = gd.layout.annotations.filter(ann => ann.name !== REALTIME_PRICE_TEXT_ANNOTATION_NAME);
            if (doRelayout) Plotly.relayout(gd, { shapes: gd.layout.shapes, annotations: gd.layout.annotations });
            return;
        }

        const annotationDefinition = {
            name: REALTIME_PRICE_TEXT_ANNOTATION_NAME, // From config.js
            text: price.toFixed(2), // Format the price, adjust precision as needed
            xref: 'paper',   // Relative to the entire plotting area
            yref: yref,      // Use the same y-axis reference as the line
            x: 1,            // Position slightly to the right of the plot area (e.g., 101%)
            y: price,        // Y position is the price itself
            showarrow: false,
            xanchor: 'right', // Anchor the text from its left side at the x-coordinate
            yanchor: 'middle',// Vertically center the text at the y-coordinate (price)
            font: {
                family: 'Arial, sans-serif',
                size: 20, // Made the font size 2 times bigger
                color: 'rgba(0,0,0,0.9)' // Match line color or choose another
            },
            bgcolor: 'rgba(255, 255, 255, 0.6)', // Optional: slight background for readability
            borderpad: 2,
            borderwidth: 0
        };

        if (lineIndex !== -1) {
            shapes[lineIndex] = lineDefinition;
        } else {
            shapes.push(lineDefinition);
        }

       // Remove old annotation before adding new one to prevent duplicates
       const existingAnnotationIndex = annotations.findIndex(ann => ann.name === REALTIME_PRICE_TEXT_ANNOTATION_NAME);
       if (existingAnnotationIndex !== -1) {
           annotations.splice(existingAnnotationIndex, 1);
       }
       annotations.push(annotationDefinition);
       // Update the layout with the modified annotations
       gd.layout.annotations = annotations;
        // console.log('[PriceLine] updateOrAddRealtimePriceLine - Pushed annotation:', JSON.parse(JSON.stringify(annotationDefinition)));
        // console.log('[PriceLine] updateOrAddRealtimePriceLine - gd.layout.annotations after push:', JSON.parse(JSON.stringify(gd.layout.annotations)));


        gd.layout.shapes = shapes;
        // gd.layout.annotations is already updated by reference


    } catch (e) {
        // console.error("[PriceLine] Error during shape modification:", e);
    }

    if (doRelayout) {
        // console.log('[PriceLine] updateOrAddRealtimePriceLine - Calling Plotly.relayout with full layout object due to doRelayout=true. Annotations:', JSON.parse(JSON.stringify(gd.layout.annotations)));
        Plotly.relayout(gd, { shapes: gd.layout.shapes, annotations: gd.layout.annotations });
    }
}

function removeRealtimePriceLine(gd, doRelayout = false) {
    // Make function globally available
    window.removeRealtimePriceLine = removeRealtimePriceLine;

    // Ensure layout exists
    if (!gd) {
        // console.warn("[PriceLine] removeRealtimePriceLine: Chart not available.");
        return false;
    }
    if (!gd.layout) {
        gd.layout = {};
    }
    if (!gd.layout.shapes) {
        gd.layout.shapes = [];
    }

    const initialLength = gd.layout.shapes.length;
    let annotationsChanged = false;

    // Ensure annotations is an array
    if (!gd.layout.annotations) {
        gd.layout.annotations = [];
    } else if (!Array.isArray(gd.layout.annotations)) {
        gd.layout.annotations = [];
    }

    if (gd.layout.annotations.length > 0) {
       // console.log('[PriceLine] removeRealtimePriceLine - Before removing annotation:', JSON.parse(JSON.stringify(gd.layout.annotations)));
        const initialAnnotationLength = gd.layout.annotations.length;
        gd.layout.annotations = gd.layout.annotations.filter(ann => ann.name !== REALTIME_PRICE_TEXT_ANNOTATION_NAME);
        annotationsChanged = gd.layout.annotations.length < initialAnnotationLength;
        // console.log('[PriceLine] removeRealtimePriceLine - After removing annotation:', JSON.parse(JSON.stringify(gd.layout.annotations)), 'Annotations changed:', annotationsChanged);
    }

    gd.layout.shapes = gd.layout.shapes.filter(shape => shape.name !== REALTIME_PRICE_LINE_NAME && shape.name !== CROSSHAIR_VLINE_NAME);
    const removed = gd.layout.shapes.length < initialLength;

    if ((removed || annotationsChanged) && doRelayout) {
        // console.log('[PriceLine] removeRealtimePriceLine - Calling Plotly.relayout due to removed shape/annotation and doRelayout=true. Annotations:', JSON.parse(JSON.stringify(gd.layout.annotations)));
        Plotly.relayout(gd, { shapes: gd.layout.shapes, annotations: gd.layout.annotations });
    }
    return removed;
}

function handleRealtimeKlineForCombined(dataPoint) {
    console.log('🔴 Combined WebSocket: handleRealtimeKlineForCombined called with data:', dataPoint);

    if (!dataPoint) {
        console.warn('🔴 Combined WebSocket: No data point provided to handleRealtimeKlineForCombined');
        return;
    }

    // Check if chart is ready
    const gd = document.getElementById('chart');
    if (!gd || !gd.layout) {
        console.warn('🔴 Combined WebSocket: Chart not ready for live price line');
        return;
    }

    // Extract price data
    const livePrice = dataPoint.ohlc ? dataPoint.ohlc.close : dataPoint.close;
    if (typeof livePrice !== 'number' || isNaN(livePrice)) {
        console.warn('🔴 Combined WebSocket: Invalid live price:', livePrice);
        return;
    }

    // Get candle timing information
    const candleStartTimeMs = dataPoint.time * 1000;
    const candleEndTimeMs = candleStartTimeMs + (getTimeframeSecondsJS(combinedResolution) * 1000);

    console.log('🔴 Combined WebSocket: Drawing live price line for EXISTING candle:', {
        livePrice,
        candleStartTimeMs,
        candleEndTimeMs,
        resolution: combinedResolution
    });

    // Draw the live price line
    updateOrAddRealtimePriceLine(gd, livePrice, candleStartTimeMs, candleEndTimeMs, true);
}

function setupCombinedWebSocket(symbol, indicators = [], resolution = '1h', fromTs = null, toTs = null) {
    // Close existing connection if symbol changed
    if (combinedWebSocket && combinedSymbol !== symbol) {
        closeCombinedWebSocket("Switching to new symbol");
    }

    // Check if this is a time range update (panning)
    const isTimeRangeUpdate = (combinedSymbol === symbol &&
                               combinedResolution === resolution &&
                               JSON.stringify(combinedIndicators) === JSON.stringify(indicators) &&
                               (combinedFromTs !== fromTs || combinedToTs !== toTs));

    combinedSymbol = symbol;
    combinedIndicators = indicators;
    combinedResolution = resolution;
    combinedFromTs = fromTs;
    combinedToTs = toTs || Math.floor(Date.now() / 1000);

    // Reset historical data accumulation state for new requests
    if (!isTimeRangeUpdate) {
        accumulatedHistoricalData = [];
        isAccumulatingHistorical = false;
        historicalDataSymbol = '';
        if (window.historicalDataTimeout) {
            clearTimeout(window.historicalDataTimeout);
            window.historicalDataTimeout = null;
        }
        // console.log('Combined WebSocket: Reset historical data accumulation state for new request');
    } else {
        // For time range updates (panning/zooming), preserve accumulation state
        // Don't reset isAccumulatingHistorical to allow continued accumulation
        console.log('Combined WebSocket: Preserving accumulation state for time range update');
    }

    // console.log('Combined WebSocket: Setup called with:', {
    //     symbol,
    //     indicators: indicators.length,
    //     resolution,
    //     fromTs,
    //     toTs,
    //     isTimeRangeUpdate,
    //     currentWebSocketState: combinedWebSocket ? combinedWebSocket.readyState : 'none'
    // });

    if (combinedWebSocket && combinedWebSocket.readyState === WebSocket.OPEN) {
        // Send updated configuration
        // console.log('Combined WebSocket: WebSocket already open, sending config update');
        sendCombinedConfig();
        return;
    }

    // If WebSocket is connecting or in error state, close it first
    if (combinedWebSocket && combinedWebSocket.readyState !== WebSocket.CLOSED) {
        // console.log('Combined WebSocket: Closing existing connection before creating new one');
        closeCombinedWebSocket("Reconnecting for new parameters");
    }

    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsHost = window.location.host;
    // Always use the current URL path symbol for WebSocket connection
    const currentUrlSymbol = window.location.pathname.substring(1).toUpperCase() || symbol;
    const streamUrl = `${wsProtocol}//${wsHost}/data/${currentUrlSymbol}`;

    // console.log(`Combined WebSocket: Attempting to connect to: ${streamUrl} (URL symbol: ${currentUrlSymbol}, requested: ${symbol})`);
    combinedWebSocket = new WebSocket(streamUrl);

    combinedWebSocket.onopen = () => {
        console.log(`🔌 Combined WebSocket: Connection opened for ${symbol}`);
        console.log(`🔌 Combined WebSocket: Connected to: ${streamUrl}`);
        console.log(`🔌 Combined WebSocket: Ready to send config with indicators:`, combinedIndicators);

        // CRITICAL FIX: Set up message handler IMMEDIATELY after connection opens
        console.log('🔧 FIXING: Setting up message handler immediately after connection opens');
        setupWebSocketMessageHandler();

        sendCombinedConfig();
    };

    // Message handler will be set up after subplots are initialized
    // combinedWebSocket.onmessage = ... (moved to setupWebSocketMessageHandler)

    combinedWebSocket.onerror = (error) => {
        // console.error(`Combined WebSocket: Error for ${symbol}:`, error);
    };

    combinedWebSocket.onclose = (event) => {
        // console.log(`Combined WebSocket: Connection closed for ${symbol}. Reason: '${event.reason}', Code: ${event.code}`);

        // Attempt to reconnect if not a clean close
        if (event.code !== 1000) {
            // console.log(`Combined WebSocket: Attempting to reconnect to ${symbol} in 5 seconds...`);
            delay(5000).then(() => {
                if (window.symbolSelect.value === symbol) {
                    setupCombinedWebSocket(symbol, indicators, resolution, fromTs, toTs);
                }
            });
        }
    };
}

function setupWebSocketMessageHandler() {
    console.log('🔧 DEBUG: setupWebSocketMessageHandler called');

    if (!combinedWebSocket) {
        console.warn('Combined WebSocket: Cannot setup message handler - WebSocket not initialized');
        return;
    }

    if (combinedWebSocket.readyState !== WebSocket.OPEN) {
        console.warn('Combined WebSocket: Cannot setup message handler - WebSocket not open. Current state:', combinedWebSocket.readyState);
        return;
    }

    console.log('✅ Combined WebSocket: Setting up message handler for WebSocket in OPEN state');

    combinedWebSocket.onmessage = (event) => {
        try {
            console.log('📨 Combined WebSocket: Message received, length:', event.data.length);

            const message = JSON.parse(event.data);
            console.log('📨 Combined WebSocket: Parsed message type:', message.type);

            // Process message based on type
            switch (message.type) {
                case 'historical':
                    console.log('📊 Processing historical data');
                    handleHistoricalData(message);
                    break;
                case 'live':
                    console.log('🔴 Processing live data');
                    handleLiveData(message);
                    break;
                case 'live_price':
                    console.log('💰 Processing live price update');
                    handleLivePriceUpdate(message);
                    break;
                case 'drawings':
                    console.log('🎨 Processing drawings data');
                    handleDrawingsData(message);
                    break;
                default:
                    console.warn('⚠️ Unknown message type:', message.type);
            }

            console.log('✅ Message processing completed for type:', message.type);
        } catch (e) {
            console.error('❌ Combined WebSocket: Error processing message:', e.message);
            console.error('❌ Raw message data:', event.data.substring(0, 200));
        }
    };

    console.log('✅ Combined WebSocket: Message handler successfully set up and attached to WebSocket');
    console.log('🎨 DRAWINGS: WebSocket message handler set up after subplots initialization');
}

function sendCombinedConfig() {
    if (!combinedWebSocket || combinedWebSocket.readyState !== WebSocket.OPEN) {
        console.warn('Combined WebSocket: Cannot send config - connection not open');
        return;
    }

    const config = {
        type: 'config',
        symbol: combinedSymbol,  // Include symbol for redundancy and clarity
        indicators: combinedIndicators,
        resolution: combinedResolution,
        from_ts: combinedFromTs,  // Now ISO timestamp string
        to_ts: combinedToTs      // Now ISO timestamp string
    };

    console.log('Combined WebSocket: Sending config:', config);
    console.log('Combined WebSocket: WebSocket readyState:', combinedWebSocket.readyState);
    console.log('Combined WebSocket: Config timestamps - from_ts:', combinedFromTs, 'to_ts:', combinedToTs);
    console.log('[TIMESTAMP DEBUG] combinedData.js - WebSocket config timestamps:');
    console.log('  combinedFromTs:', combinedFromTs, '(ISO timestamp string)');
    console.log('  combinedToTs:', combinedToTs, '(ISO timestamp string)');
    console.log('  from_ts in config:', config.from_ts);
    console.log('  to_ts in config:', config.to_ts);

    // Detailed timestamp logging for server comparison
    const fromDate = new Date(combinedFromTs);
    const toDate = new Date(combinedToTs);
    const rangeMs = toDate.getTime() - fromDate.getTime();
    const rangeHours = rangeMs / (1000 * 60 * 60);
    /* console.log('📤 CLIENT SENDING TO SERVER:', {
        symbol: combinedSymbol,
        fromTs: combinedFromTs,
        toTs: combinedToTs,
        from_ts: combinedFromTs,
        to_ts: combinedToTs,
        fromDate: fromDate.toISOString(),
        toDate: toDate.toISOString(),
        rangeMs,
        rangeHours: rangeHours.toFixed(1)
    });
    */

    // Store server range for comparison with client range
    window.lastServerRange = {
        symbol: combinedSymbol,
        fromTs: combinedFromTs,
        toTs: combinedToTs,
        fromDate: fromDate.toISOString(),
        toDate: toDate.toISOString(),
        rangeMs,
        rangeHours: rangeHours.toFixed(1),
        timestamp: new Date().toISOString()
    };
    console.log('💾 Stored server range for client comparison. Use window.compareClientServerRanges() to compare.');

    try {
        combinedWebSocket.send(JSON.stringify(config));
        console.log('Combined WebSocket: Config sent successfully');
    } catch (error) {
        console.error('Combined WebSocket: Error sending config:', error);
    }
}

function handleHistoricalData(message) {
    console.log(`📊 Combined WebSocket: Received historical data for ${message.symbol}, ${message.data.length} points`);
    console.log('📊 Combined WebSocket: Sample data point:', message.data[0]);

    // DEBUG: Log the raw message for debugging
    console.log('🔍 DEBUG: Raw historical message received:', {
        type: message.type,
        symbol: message.symbol,
        dataLength: message.data ? message.data.length : 0,
        firstDataPoint: message.data ? message.data[0] : null,
        lastDataPoint: message.data ? message.data[message.data.length - 1] : null
    });

    // Check if chart is ready
    console.log('🔍 DEBUG: Chart element exists:', !!document.getElementById('chart'));
    console.log('🔍 DEBUG: Window.gd exists:', !!window.gd);
    console.log('🔍 DEBUG: Window.gd.data exists:', !!(window.gd && window.gd.data));

    // DEBUG: Log timestamp ranges in the received data
    if (message.data && message.data.length > 0) {
        const firstTimestamp = message.data[0].time;
        const lastTimestamp = message.data[message.data.length - 1].time;
        console.log('📅 CLIENT RECEIVED TIMESTAMP RANGE:');
        console.log('  First timestamp (seconds):', firstTimestamp);
        console.log('  Last timestamp (seconds):', lastTimestamp);
        console.log('  First timestamp (UTC):', new Date(firstTimestamp * 1000).toISOString());
        console.log('  Last timestamp (UTC):', new Date(lastTimestamp * 1000).toISOString());
        console.log('  First timestamp (Local):', new Date(firstTimestamp * 1000).toLocaleString());
        console.log('  Last timestamp (Local):', new Date(lastTimestamp * 1000).toLocaleString());
        console.log('  Data range (seconds):', lastTimestamp - firstTimestamp);
        console.log('  Data range (hours):', ((lastTimestamp - firstTimestamp) / 3600).toFixed(1));
    }

    if (!message.data || !Array.isArray(message.data)) {
        console.warn('Combined WebSocket: Invalid historical data format');
        return;
    }

    if (message.data.length === 0) {
        console.warn('Combined WebSocket: Received empty historical data array');
        return;
    }

    // Check if this is a new accumulation session
    if (!isAccumulatingHistorical || historicalDataSymbol !== message.symbol) {
        // Start new accumulation
        accumulatedHistoricalData = [];
        isAccumulatingHistorical = true;
        historicalDataSymbol = message.symbol;

        // Clear any existing timeout
        if (accumulationTimeout) {
            clearTimeout(accumulationTimeout);
            accumulationTimeout = null;
        }

        // Set up timeout to reset accumulation after 30 seconds
        accumulationTimeout = setTimeout(() => {
            console.log(`Combined WebSocket: Accumulation timeout reached for ${historicalDataSymbol}, resetting state`);
            accumulatedHistoricalData = [];
            isAccumulatingHistorical = false;
            historicalDataSymbol = '';
            accumulationTimeout = null;
        }, 30000);

        console.log(`Combined WebSocket: Starting new historical data accumulation for ${message.symbol}`);
    } else {
        // Continue existing accumulation - check if this data makes sense to add
        if (accumulatedHistoricalData.length > 0 && message.data.length > 0) {
            const currentMinTime = Math.min(...accumulatedHistoricalData.map(d => d.time));
            const currentMaxTime = Math.max(...accumulatedHistoricalData.map(d => d.time));
            const newMinTime = Math.min(...message.data.map(d => d.time));
            const newMaxTime = Math.max(...message.data.map(d => d.time));

            // Check if new data overlaps or extends current data reasonably
            const overlapThreshold = 3600; // 1 hour overlap threshold
            const hasOverlap = (newMinTime <= currentMaxTime + overlapThreshold) && (newMaxTime >= currentMinTime - overlapThreshold);
            const extendsRange = newMinTime < currentMinTime || newMaxTime > currentMaxTime;

            if (!hasOverlap && !extendsRange) {
                // Data doesn't overlap and doesn't extend range - might be a new request
                console.log(`Combined WebSocket: New data doesn't overlap with existing range, treating as continuation`);
            }
        }

        console.log(`Combined WebSocket: Continuing historical data accumulation for ${message.symbol} (${accumulatedHistoricalData.length} points already accumulated)`);
    }

    // Add this batch to accumulated data with proper merging to avoid duplicates
    const previousCount = accumulatedHistoricalData.length;
    const combinedData = accumulatedHistoricalData.concat(message.data);

    // Merge data to remove duplicates and handle overlaps properly
    const mergedData = mergeHistoricalData(combinedData);
    accumulatedHistoricalData = mergedData;

    console.log(`📊 Combined WebSocket: Accumulated ${accumulatedHistoricalData.length} total data points so far (added ${message.data.length}, previous: ${previousCount}, merged: ${combinedData.length - accumulatedHistoricalData.length} duplicates removed)`);

    // DEBUG: Check data integrity
    console.log('🔍 DEBUG: Data accumulation details:');
    console.log('  Message data length:', message.data.length);
    console.log('  First message data point:', message.data[0]);
    console.log('  Accumulated data length:', accumulatedHistoricalData.length);
    console.log('  Accumulated data sample:', accumulatedHistoricalData.slice(0, 2));

    // Clear any existing timeout
    if (window.historicalDataTimeout) {
        clearTimeout(window.historicalDataTimeout);
    }

    // Check if chart is fully ready before processing (element, Plotly gd, and full layout exist)
    const chartElement = document.getElementById('chart');
    if (!chartElement || !window.gd || !window.gd._fullLayout) {
        console.log('📊 Combined WebSocket: Chart not fully ready (element, gd, or _fullLayout missing), retrying with requestAnimationFrame');
        // Retry using requestAnimationFrame for better determinism
        requestAnimationFrame(() => {
            console.log(`📊 Combined WebSocket: Processing accumulated historical data: ${accumulatedHistoricalData.length} points for ${historicalDataSymbol}`);
            console.log('🔍 DEBUG: About to call updateChartWithHistoricalData with:', {
                dataPoints: accumulatedHistoricalData.length,
                symbol: historicalDataSymbol,
                firstTimestamp: accumulatedHistoricalData[0]?.time,
                lastTimestamp: accumulatedHistoricalData[accumulatedHistoricalData.length - 1]?.time
            });

            // Only update chart if we have accumulated a significant amount of data
            if (accumulatedHistoricalData.length >= 10) {
                // Process accumulated historical data and update chart
                updateChartWithHistoricalData(accumulatedHistoricalData, historicalDataSymbol);
            } else {
                console.log(`📊 Combined WebSocket: Skipping chart update in requestAnimationFrame - only ${accumulatedHistoricalData.length} points accumulated so far`);
            }

            // Don't reset accumulation state here - let the main handler decide when to reset
            console.log(`Combined WebSocket: Processed ${accumulatedHistoricalData.length} points in requestAnimationFrame for ${historicalDataSymbol}`);
        });
        return;
    }

    console.log(`📊 Combined WebSocket: Processing accumulated historical data: ${accumulatedHistoricalData.length} points for ${historicalDataSymbol}`);
    console.log('🔍 DEBUG: About to call updateChartWithHistoricalData with:', {
        dataPoints: accumulatedHistoricalData.length,
        symbol: historicalDataSymbol,
        firstTimestamp: accumulatedHistoricalData[0]?.time,
        lastTimestamp: accumulatedHistoricalData[accumulatedHistoricalData.length - 1]?.time
    });

    // Only update chart if we have accumulated a significant amount of data
    // This prevents chart flickering from small batches
    if (accumulatedHistoricalData.length >= 10) {
        // Process accumulated historical data and update chart
        updateChartWithHistoricalData(accumulatedHistoricalData, historicalDataSymbol);
    } else {
        console.log(`📊 Combined WebSocket: Skipping chart update - only ${accumulatedHistoricalData.length} points accumulated so far`);
    }

    // For time range updates (panning/zooming), don't reset accumulation state after each batch
    // Only reset when we detect a truly new request or timeout
    // The accumulation will continue until timeout or a new symbol/resolution request
    console.log(`Combined WebSocket: Accumulation state preserved for ${historicalDataSymbol} - ${accumulatedHistoricalData.length} points accumulated so far`);
}

function handleLiveData(message) {
    console.log(`🔴 Combined WebSocket: Received live data for ${message.symbol}`);
    console.log('🔴 Live data details:', message.data);

    if (!message.data) {
        console.warn('🔴 Combined WebSocket: Invalid live data format - no data field');
        return;
    }

    // Check if chart is ready
    const gd = document.getElementById('chart');
    console.log('🔴 DEBUG: Chart element exists for live data:', !!gd);
    console.log('🔴 DEBUG: Window.gd exists for live data:', !!window.gd);
    console.log('🔴 DEBUG: Window.gd.data exists for live data:', !!(window.gd && window.gd.data));

    // Process live data and update chart
    updateChartWithLiveData(message.data, message.symbol);

    // Handle live price line drawing (always enabled now)
    handleRealtimeKlineForCombined(message.data);
}

function handleLivePriceUpdate(message) {
    console.log(`💰 Combined WebSocket: Received live price update for ${message.symbol}: ${message.price}`);

    if (!message.price || typeof message.price !== 'number') {
        console.warn('💰 Combined WebSocket: Invalid live price format');
        return;
    }

    // Check if chart is ready
    const gd = document.getElementById('chart');
    if (!gd || !gd.layout) {
        console.warn('💰 Combined WebSocket: Chart not ready for live price update');
        return;
    }

    // Get candle timing information for the live price line
    const currentTime = message.timestamp || Math.floor(Date.now() / 1000);
    const candleStartTimeMs = currentTime * 1000;
    const candleEndTimeMs = candleStartTimeMs + (getTimeframeSecondsJS(combinedResolution) * 1000);

    console.log('💰 Combined WebSocket: Drawing live price line for price update:', {
        price: message.price,
        timestamp: currentTime,
        resolution: combinedResolution
    });

    // Draw the live price line
    updateOrAddRealtimePriceLine(gd, message.price, candleStartTimeMs, candleEndTimeMs, true);
}

function handleDrawingsData(message) {
    // console.log(`Combined WebSocket: Received drawings data for ${message.symbol}`);

    if (!message.data || !Array.isArray(message.data)) {
        console.warn('Combined WebSocket: Invalid drawings data format');
        return;
    }

    if (message.data.length === 0) {
        console.log('Combined WebSocket: No drawings to process');
        return;
    }

    // console.log('🎨 DRAWINGS: Processing', message.data.length, 'drawings:', message.data);

    // Process and add drawings to the chart
    addDrawingsToChart(message.data, message.symbol);
}

function addDrawingsToChart(drawings, symbol) {
    console.log(`Combined WebSocket: Adding ${drawings.length} drawings to chart for ${symbol}`);

    const chartElement = document.getElementById('chart');
    if (!chartElement || !window.gd) {
        console.warn('Combined WebSocket: Chart not ready for drawings');
        return;
    }

    // Ensure layout.shapes exists
    if (!window.gd.layout.shapes) {
        window.gd.layout.shapes = [];
    }

    // console.log('🎨 DRAWINGS: Current shapes before adding:', window.gd.layout.shapes.length);

    // Process each drawing
    drawings.forEach((drawing, index) => {
        try {
            // console.log(`Combined WebSocket: Processing drawing ${index + 1}/${drawings.length}:`, drawing);

            // Convert drawing data to Plotly shape format
            const shape = convertDrawingToShape(drawing);
            // console.log(`Combined WebSocket: Converted to shape:`, shape);

            if (shape) {
                // Check if shape already exists (by id)
                const existingIndex = window.gd.layout.shapes.findIndex(s => s.id === drawing.id);

                if (existingIndex !== -1) {
                    // Update existing shape
                    window.gd.layout.shapes[existingIndex] = shape;
                    console.log(`Combined WebSocket: Updated existing drawing ${drawing.id}`);
                } else {
                    // Add new shape
                    window.gd.layout.shapes.push(shape);
                    console.log(`Combined WebSocket: Added new drawing ${drawing.id}`);
                }
            } else {
                console.warn(`Combined WebSocket: Could not convert drawing to shape:`, drawing);
            }
        } catch (error) {
            console.error(`Combined WebSocket: Error processing drawing ${index}:`, error, drawing);
        }
    });

    console.log('🎨 DRAWINGS: Final shapes count:', window.gd.layout.shapes.length);

    // Update the chart with new shapes - ensure shapes are preserved during chart updates
    try {
        // First, ensure the layout has a shapes array
        if (!window.gd.layout.shapes) {
            window.gd.layout.shapes = [];
        }

        // Update the chart with shapes using relayout to preserve existing data
        Plotly.relayout(chartElement, {
            shapes: window.gd.layout.shapes
        });
        console.log(`Combined WebSocket: Successfully updated chart with ${drawings.length} drawings`);
        console.log('🎨 DRAWINGS: Final shapes in layout:', window.gd.layout.shapes.length);
    } catch (error) {
        console.error('Combined WebSocket: Error updating chart with drawings:', error);
    }
}

function getYrefForSubplot(subplotName) {
    // Map subplot names to correct yref values
    // Format: "SYMBOL" for main chart, "SYMBOL-INDICATOR" for subplots

    if (!subplotName) {
        console.warn('🎨 DRAWINGS: No subplot_name provided, defaulting to main chart');
        return 'y';
    }

    // Extract symbol and indicator from subplot_name
    const parts = subplotName.split('-');
    const symbol = parts[0];
    const indicator = parts[1];

    if (!indicator) {
        // Main chart
        return 'y';
    }

    // Get current active indicators to determine the correct y-axis index
    const activeIndicators = window.combinedIndicators || [];
    const forcedIndicatorOrder = ['macd', 'rsi', 'stochrsi_9_3', 'stochrsi_14_3', 'stochrsi_40_4', 'stochrsi_60_10', 'open_interest', 'jma'];

    // Filter to only active indicators and maintain order
    const activeIndicatorIds = forcedIndicatorOrder.filter(indicatorId => activeIndicators.includes(indicatorId));

    // Find the index of this indicator in the active list
    const indicatorIndex = activeIndicatorIds.indexOf(indicator);

    if (indicatorIndex === -1) {
        console.warn(`🎨 DRAWINGS: Indicator ${indicator} not found in active indicators, defaulting to main chart`);
        return 'y';
    }

    // Return the correct yref (y2, y3, y4, etc.)
    const yref = `y${indicatorIndex + 2}`;
    console.log(`🎨 DRAWINGS: Mapped subplot ${subplotName} to yref ${yref} (indicator index: ${indicatorIndex})`);
    return yref;
}

function convertDrawingToShape(drawing) {
    try {
        console.log('🎨 DRAWINGS: Converting drawing to shape:', drawing);

        // Determine the correct yref based on subplot_name
        const yref = getYrefForSubplot(drawing.subplot_name);

        // Basic shape properties
        const shape = {
            id: drawing.id,
            type: drawing.type || 'line',
            name: `drawing_${drawing.id}`,
            editable: true,
            layer: 'above',
            xref: 'x',  // Always use main x-axis
            yref: yref  // Use the correct y-axis based on subplot
        };

        // Convert coordinates based on drawing type
        if (drawing.type === 'line' || drawing.type === 'trendline') {
            shape.x0 = new Date(drawing.start_time * 1000);
            shape.y0 = drawing.start_price;
            shape.x1 = new Date(drawing.end_time * 1000);
            shape.y1 = drawing.end_price;
            shape.line = {
                color: drawing.properties?.color || 'blue',
                width: drawing.properties?.width || 2,
                dash: drawing.properties?.dash || 'solid'
            };
            /*
            console.log('🎨 DRAWINGS: Created line shape:', {
                x0: shape.x0,
                y0: shape.y0,
                x1: shape.x1,
                y1: shape.y1,
                yref: shape.yref,
                line: shape.line
            });
            */
        } else if (drawing.type === 'rectangle' || drawing.type === 'box') {
            // For rectangles, we need to determine min/max coordinates
            const x0 = new Date(Math.min(drawing.start_time, drawing.end_time) * 1000);
            const x1 = new Date(Math.max(drawing.start_time, drawing.end_time) * 1000);
            const y0 = Math.min(drawing.start_price, drawing.end_price);
            const y1 = Math.max(drawing.start_price, drawing.end_price);

            shape.type = 'rect';
            shape.x0 = x0;
            shape.y0 = y0;
            shape.x1 = x1;
            shape.y1 = y1;
            shape.line = {
                color: drawing.properties?.color || 'red',
                width: drawing.properties?.width || 2
            };
            shape.fillcolor = drawing.properties?.fillcolor || 'rgba(255, 0, 0, 0.1)';
            console.log('🎨 DRAWINGS: Created rectangle shape:', {
                ...shape,
                yref: shape.yref
            });
        } else if (drawing.type === 'horizontal_line' || drawing.type === 'hline') {
            shape.type = 'line';
            shape.x0 = 'x.min'; // Span entire x-axis
            shape.x1 = 'x.max';
            shape.y0 = drawing.start_price;
            shape.y1 = drawing.start_price;
            shape.xref = 'paper';
            shape.line = {
                color: drawing.properties?.color || 'green',
                width: drawing.properties?.width || 2,
                dash: drawing.properties?.dash || 'dash'
            };
            /*
            console.log('🎨 DRAWINGS: Created horizontal line shape:', {
                ...shape,
                yref: shape.yref
            });
            */
        } else {
            console.warn(`Combined WebSocket: Unsupported drawing type: ${drawing.type}`);
            return null;
        }

        // console.log('🎨 DRAWINGS: Final shape created:', shape);
        return shape;
    } catch (error) {
        console.error('Combined WebSocket: Error converting drawing to shape:', error, drawing);
        return null;
    }
}

function mergeHistoricalData(dataPoints) {
    if (!dataPoints || dataPoints.length === 0) {
        return [];
    }

    // Sort by timestamp to ensure proper ordering
    const sortedData = dataPoints.sort((a, b) => a.time - b.time);

    // Remove duplicates by timestamp, keeping the most recent data
    const mergedData = [];
    const seenTimestamps = new Set();

    for (const point of sortedData) {
        if (!seenTimestamps.has(point.time)) {
            seenTimestamps.add(point.time);
            mergedData.push(point);
        } else {
            // If we have a duplicate timestamp, replace the existing one with the new one
            // This ensures we keep the most recent data for the same timestamp
            const existingIndex = mergedData.findIndex(p => p.time === point.time);
            if (existingIndex !== -1) {
                mergedData[existingIndex] = point;
            }
        }
    }

    console.log(`🔄 Merged ${dataPoints.length} points into ${mergedData.length} unique points (${dataPoints.length - mergedData.length} duplicates removed)`);
    return mergedData;
}

function updateChartWithHistoricalData(dataPoints, symbol) {
    console.log('📈 Combined WebSocket: Processing historical data for chart update');
    console.log('📈 Combined WebSocket: Data points received:', dataPoints.length);

    // Define chartElement globally for the function
    const chartElement = document.getElementById('chart');

    if (!dataPoints || dataPoints.length === 0) {
        console.warn('⚠️ Combined WebSocket: No historical data points to process');
        return;
    }

    // DEBUG: Log detailed data structure
    console.log('🔍 DEBUG: First data point structure:', JSON.stringify(dataPoints[0], null, 2));
    console.log('🔍 DEBUG: Sample data points (first 3):', dataPoints.slice(0, 3).map(p => ({
        time: p.time,
        ohlc: p.ohlc,
        indicators: Object.keys(p.indicators || {})
    })));

    // Extract OHLC data
    console.log('📊 Combined WebSocket: Extracting OHLC data from', dataPoints.length, 'points');
    const timestamps = dataPoints.map(point => new Date(point.time * 1000));
    const open = dataPoints.map(point => point.ohlc.open);
    const high = dataPoints.map(point => point.ohlc.high);
    const low = dataPoints.map(point => point.ohlc.low);
    const close = dataPoints.map(point => point.ohlc.close);
    const volume = dataPoints.map(point => point.ohlc.volume);

    console.log('📊 Combined WebSocket: Sample OHLC data - Open:', open.slice(0, 3), 'Close:', close.slice(0, 3));

    // DEBUG: Log timestamp conversion details
    // console.log('🔍 DEBUG: Timestamp conversion details:');
    // console.log('  Raw timestamps (first 3):', dataPoints.slice(0, 3).map(p => p.time));
    // console.log('  Converted timestamps (first 3):', timestamps.slice(0, 3));
    // console.log('  First timestamp (UTC):', timestamps[0].toISOString());
    // console.log('  Last timestamp (UTC):', timestamps[timestamps.length - 1].toISOString());
    // console.log('  First timestamp (Local):', timestamps[0].toLocaleString());
    // console.log('  Last timestamp (Local):', timestamps[timestamps.length - 1].toLocaleString());

    // DEBUG: Check for NaN values in OHLC data
    const ohlcNaNCount = [open, high, low, close].reduce((count, arr) => count + arr.filter(v => isNaN(v)).length, 0);
    // console.log('🔍 DEBUG: OHLC NaN count:', ohlcNaNCount, 'out of', open.length * 4, 'values');
    if (ohlcNaNCount > 0) {
        // console.warn('🚨 WARNING: Found NaN values in OHLC data!');
    }

    // Create main price trace
    const priceTrace = {
        x: timestamps,
        open: open,
        high: high,
        low: low,
        close: close,
        volume: volume,
        type: 'candlestick',
        xaxis: 'x',
        yaxis: 'y',
        name: symbol,
        increasing: { line: { color: 'green' } },
        decreasing: { line: { color: 'red' } },
        hoverinfo: isMobileDevice() ? 'skip' : 'all'
    };

    // Create indicator traces
    const indicatorTraces = [];
    const indicatorsData = {};

    console.log('🔍 DEBUG: Processing indicator data from dataPoints...');
    console.log('🔍 DEBUG: Number of dataPoints:', dataPoints.length);
    console.log('🔍 DEBUG: combinedIndicators:', combinedIndicators);

    dataPoints.forEach((point, pointIndex) => {
        //console.log(`🔍 DEBUG: DataPoint ${pointIndex}: time=${point.time}, has indicators:`, !!point.indicators);
        if (point.indicators) {
            //console.log(`🔍 DEBUG: DataPoint ${pointIndex} indicators keys:`, Object.keys(point.indicators));
            Object.keys(point.indicators).forEach(indicatorId => {
                //console.log(`🔍 DEBUG: Processing indicator ${indicatorId} for dataPoint ${pointIndex}`);
                if (!indicatorsData[indicatorId]) {
                    //console.log(`🔍 DEBUG: Creating new indicatorsData entry for ${indicatorId}`);
                    indicatorsData[indicatorId] = {
                        timestamps: [],
                        values: {}
                    };
                }

                indicatorsData[indicatorId].timestamps.push(new Date(point.time * 1000));

                // Store all indicator values for this point
                Object.keys(point.indicators[indicatorId]).forEach(key => {
                    //console.log(`🔍 DEBUG: Processing indicator ${indicatorId} key ${key} with value:`, point.indicators[indicatorId][key]);
                    if (!indicatorsData[indicatorId].values[key]) {
                        indicatorsData[indicatorId].values[key] = [];
                    }
                    indicatorsData[indicatorId].values[key].push(point.indicators[indicatorId][key]);
                });
            });
        } else {
            console.log(`🔍 DEBUG: DataPoint ${pointIndex} has no indicators object`);
        }
    });

    console.log('🔍 DEBUG: Final indicatorsData after processing:', indicatorsData);
    console.log('🔍 DEBUG: indicatorsData keys:', Object.keys(indicatorsData));

    // Create traces for each indicator with separate subplots
    // FORCE MACD to be first by hardcoding the exact order we want
    const forcedIndicatorOrder = ['macd', 'rsi', 'stochrsi_9_3', 'stochrsi_14_3', 'stochrsi_40_4', 'stochrsi_60_10', 'open_interest', 'jma'];
    const indicatorTypes = forcedIndicatorOrder.filter(indicatorId => combinedIndicators.includes(indicatorId));

    // console.log('FORCED INDICATOR ORDER - Processing in this exact sequence:', indicatorTypes);
    // console.log('FORCED INDICATOR ORDER - MACD should be index 0 (first):', indicatorTypes[0] === 'macd');
    const subplotCount = indicatorTypes.length;

    console.log('📊 Combined WebSocket: Processing indicators in order:', indicatorTypes);
    console.log('📊 Combined WebSocket: combinedIndicators:', combinedIndicators);
    console.log('📊 Combined WebSocket: Available indicatorsData keys:', Object.keys(indicatorsData));

    // Helper function to filter NaN values from indicator data
    function filterNaNValues(timestamps, values) {
        const filteredTimestamps = [];
        const filteredValues = [];

        let nanCount = 0;
        let infiniteCount = 0;
        let nonNumericCount = 0;

        for (let i = 0; i < values.length; i++) {
            const value = values[i];
            if (typeof value !== 'number') {
                nonNumericCount++;
                continue;
            }
            if (isNaN(value)) {
                nanCount++;
                continue;
            }
            if (!isFinite(value)) {
                infiniteCount++;
                continue;
            }
            filteredTimestamps.push(timestamps[i]);
            filteredValues.push(value);
        }

        // DEBUG: Log filtering results
        if (nanCount > 0 || infiniteCount > 0 || nonNumericCount > 0) {
            //console.log(`🔍 DEBUG: NaN filtering for indicator data:`);
            //console.log(`  Original: ${values.length}, Filtered: ${filteredValues.length}`);
            //console.log(`  NaN count: ${nanCount}, Infinite count: ${infiniteCount}, Non-numeric count: ${nonNumericCount}`);
        }

        return { timestamps: filteredTimestamps, values: filteredValues };
    }

    indicatorTypes.forEach((indicatorId, index) => {
        const indicatorData = indicatorsData[indicatorId];
        if (!indicatorData) return; // Skip if no data for this indicator
        const yAxisName = `y${index + 2}`; // y2, y3, y4, etc.

        /*
        // console.log(`Combined WebSocket: Processing indicator ${indicatorId} with ${indicatorData ? indicatorData.timestamps.length : 'N/A'} data points`);
        // console.log(`🔍 DEBUG: indicatorData for ${indicatorId}:`, indicatorData);
        // console.log(`🔍 DEBUG: indicatorData.timestamps:`, indicatorData ? indicatorData.timestamps : 'N/A');
        // console.log(`🔍 DEBUG: indicatorData.values:`, indicatorData ? indicatorData.values : 'N/A');
        */

        if (indicatorId === 'macd' && indicatorData.values.macd && indicatorData.values.signal && indicatorData.values.histogram) {
            console.log(`🔍 DEBUG: MACD condition check - macd: ${!!indicatorData.values.macd}, signal: ${!!indicatorData.values.signal}, histogram: ${!!indicatorData.values.histogram}`);
            console.log(`🔍 DEBUG: MACD values lengths - macd: ${indicatorData.values.macd ? indicatorData.values.macd.length : 'N/A'}, signal: ${indicatorData.values.signal ? indicatorData.values.signal.length : 'N/A'}, histogram: ${indicatorData.values.histogram ? indicatorData.values.histogram.length : 'N/A'}`);

            // Ensure we have valid data before processing
            if (indicatorData.values.macd.length === 0) {
                console.warn('⚠️ MACD: No MACD data points to process');
                return;
            }

            // MACD with signal and histogram - filter NaN values
            const macdFiltered = filterNaNValues(indicatorData.timestamps, indicatorData.values.macd);
            const signalFiltered = filterNaNValues(indicatorData.timestamps, indicatorData.values.signal);
            const histogramFiltered = filterNaNValues(indicatorData.timestamps, indicatorData.values.histogram);

            // console.log(`Combined WebSocket: MACD - Original: ${indicatorData.values.macd.length}, Filtered: ${macdFiltered.values.length}`);
            // console.log(`🔍 DEBUG: MACD filtered values - macd: ${macdFiltered.values.length}, signal: ${signalFiltered.values.length}, histogram: ${histogramFiltered.values.length}`);

            // console.log(`🔍 DEBUG: MACD macdFiltered.values.length > 0 check: ${macdFiltered.values.length > 0} (${macdFiltered.values.length})`);
            if (macdFiltered.values.length > 0) {
                // console.log(`🔍 DEBUG: Creating MACD trace`);
                indicatorTraces.push({
                    x: macdFiltered.timestamps,
                    y: macdFiltered.values,
                    type: 'scatter',
                    mode: 'lines',
                    name: 'MACD',
                    line: { color: 'blue' },
                    xaxis: 'x',
                    yaxis: yAxisName,
                    hoverinfo: isMobileDevice() ? 'skip' : 'all'
                });
            }

            // console.log(`🔍 DEBUG: MACD signalFiltered.values.length > 0 check: ${signalFiltered.values.length > 0} (${signalFiltered.values.length})`);
            if (signalFiltered.values.length > 0) {
                // console.log(`🔍 DEBUG: Creating MACD Signal trace`);
                indicatorTraces.push({
                    x: signalFiltered.timestamps,
                    y: signalFiltered.values,
                    type: 'scatter',
                    mode: 'lines',
                    name: 'MACD Signal',
                    line: { color: 'orange' },
                    xaxis: 'x',
                    yaxis: yAxisName,
                    hoverinfo: isMobileDevice() ? 'skip' : 'all'
                });
            }

            // console.log(`🔍 DEBUG: MACD histogramFiltered.values.length > 0 check: ${histogramFiltered.values.length > 0} (${histogramFiltered.values.length})`);
            if (histogramFiltered.values.length > 0) {
                // console.log(`🔍 DEBUG: Creating MACD Histogram trace`);
                indicatorTraces.push({
                    x: histogramFiltered.timestamps,
                    y: histogramFiltered.values,
                    type: 'bar',
                    name: 'MACD Histogram',
                    marker: {
                        color: histogramFiltered.values.map(v => v >= 0 ? 'green' : 'red')
                    },
                    xaxis: 'x',
                    yaxis: yAxisName,
                    hoverinfo: isMobileDevice() ? 'skip' : 'all'
                });
            }
        } else if (indicatorId === 'rsi' && indicatorData.values.rsi) {
            // console.log(`🔍 DEBUG: RSI condition check - rsi: ${!!indicatorData.values.rsi}`);
            // console.log(`🔍 DEBUG: RSI values length: ${indicatorData.values.rsi ? indicatorData.values.rsi.length : 'N/A'}`);

            // RSI - filter NaN values
            const rsiFiltered = filterNaNValues(indicatorData.timestamps, indicatorData.values.rsi);
            // console.log(`Combined WebSocket: RSI - Original: ${indicatorData.values.rsi.length}, Filtered: ${rsiFiltered.values.length}, NaN count: ${indicatorData.values.rsi.filter(v => isNaN(v)).length}`);
            // console.log(`🔍 DEBUG: RSI filtered values: ${rsiFiltered.values.length}`);

            // console.log(`🔍 DEBUG: RSI rsiFiltered.values.length > 0 check: ${rsiFiltered.values.length > 0} (${rsiFiltered.values.length})`);
            if (rsiFiltered.values.length > 0) {
                // console.log(`🔍 DEBUG: Creating RSI trace`);
                indicatorTraces.push({
                    x: rsiFiltered.timestamps,
                    y: rsiFiltered.values,
                    type: 'scatter',
                    mode: 'lines',
                    name: 'RSI',
                    line: { color: 'purple' },
                    xaxis: 'x',
                    yaxis: yAxisName,
                    hoverinfo: isMobileDevice() ? 'skip' : 'all'
                });
            }

            // Check for RSI_SMA14 and add it if available
            if (indicatorData.values.rsi_sma14) {
                const rsiSma14Filtered = filterNaNValues(indicatorData.timestamps, indicatorData.values.rsi_sma14);
                // console.log(`Combined WebSocket: RSI_SMA14 - Original: ${indicatorData.values.rsi_sma14.length}, Filtered: ${rsiSma14Filtered.values.length}, NaN count: ${indicatorData.values.rsi_sma14.filter(v => isNaN(v)).length}`);

                if (rsiSma14Filtered.values.length > 0) {
                    indicatorTraces.push({
                        x: rsiSma14Filtered.timestamps,
                        y: rsiSma14Filtered.values,
                        type: 'scatter',
                        mode: 'lines',
                        name: 'RSI_SMA14',
                        line: { color: 'dodgerblue' },
                        xaxis: 'x',
                        yaxis: yAxisName,
                        hoverinfo: isMobileDevice() ? 'skip' : 'all'
                    });
                }
            }
        } else if (indicatorId.startsWith('stochrsi') && indicatorData.values.stoch_k && indicatorData.values.stoch_d) {
            // console.log(`🔍 DEBUG: StochRSI condition check - stoch_k: ${!!indicatorData.values.stoch_k}, stoch_d: ${!!indicatorData.values.stoch_d}`);
            // console.log(`🔍 DEBUG: StochRSI values lengths - k: ${indicatorData.values.stoch_k ? indicatorData.values.stoch_k.length : 'N/A'}, d: ${indicatorData.values.stoch_d ? indicatorData.values.stoch_d.length : 'N/A'}`);

            // Stochastic RSI - filter NaN values
            const stochKFiltered = filterNaNValues(indicatorData.timestamps, indicatorData.values.stoch_k);
            const stochDFiltered = filterNaNValues(indicatorData.timestamps, indicatorData.values.stoch_d);

            // console.log(`Combined WebSocket: StochRSI - K Original: ${indicatorData.values.stoch_k.length}, Filtered: ${stochKFiltered.values.length}`);
            // console.log(`🔍 DEBUG: StochRSI filtered values - k: ${stochKFiltered.values.length}, d: ${stochDFiltered.values.length}`);

            // console.log(`🔍 DEBUG: StochRSI stochKFiltered.values.length > 0 check: ${stochKFiltered.values.length > 0} (${stochKFiltered.values.length})`);
            if (stochKFiltered.values.length > 0) {
                // console.log(`🔍 DEBUG: Creating Stoch K trace`);
                indicatorTraces.push({
                    x: stochKFiltered.timestamps,
                    y: stochKFiltered.values,
                    type: 'scatter',
                    mode: 'lines',
                    name: 'Stoch K',
                    line: { color: 'blue' },
                    xaxis: 'x',
                    yaxis: yAxisName,
                    hoverinfo: isMobileDevice() ? 'skip' : 'all'
                });
            }

            // console.log(`🔍 DEBUG: StochRSI stochDFiltered.values.length > 0 check: ${stochDFiltered.values.length > 0} (${stochDFiltered.values.length})`);
            if (stochDFiltered.values.length > 0) {
                // console.log(`🔍 DEBUG: Creating Stoch D trace`);
                indicatorTraces.push({
                    x: stochDFiltered.timestamps,
                    y: stochDFiltered.values,
                    type: 'scatter',
                    mode: 'lines',
                    name: 'Stoch D',
                    line: { color: 'orange' },
                    xaxis: 'x',
                    yaxis: yAxisName,
                    hoverinfo: isMobileDevice() ? 'skip' : 'all'
                });
            }
        } else {
            // console.warn(`Combined WebSocket: Unknown or incomplete indicator data for ${indicatorId}`);
        }
    });

    // Update chart with all traces
    const allTraces = [priceTrace, ...indicatorTraces];

    console.log('📊 Combined WebSocket: Final trace counts:');
    console.log('  Price trace: 1');
    console.log('  Indicator traces:', indicatorTraces.length);
    console.log('  Total traces:', allTraces.length);
    console.log('  Indicator trace names:', indicatorTraces.map(t => t.name));

    // Check if we need to create a new layout or can reuse existing one
    let layout;
    if (window.gd && window.gd.layout && window.gd.layout.grid) {
        // Reuse existing layout and just update necessary properties
        layout = { ...window.gd.layout };

        // Update title and axis ranges if needed
        layout.title = `${symbol} - ${combinedResolution.toUpperCase()}`;

        // Preserve user's saved X-axis range if it exists
        if (window.currentXAxisRange && window.currentXAxisRange.length === 2) {
            let xMinMs = window.currentXAxisRange[0];
            let xMaxMs = window.currentXAxisRange[1];

            if (xMinMs < 2e9) {
                xMinMs = xMinMs * 1000;
                xMaxMs = xMaxMs * 1000;
            }

            const xMinDate = new Date(xMinMs);
            const xMaxDate = new Date(xMaxMs);
            layout.xaxis = {
                ...layout.xaxis,
                rangeslider: { visible: false },
                type: 'date',
                autorange: false,
                range: [xMinDate, xMaxDate]
            };
        }

        // Preserve user's saved Y-axis range if it exists
        if (window.currentYAxisRange && window.currentYAxisRange.length === 2) {
            layout.yaxis = {
                ...layout.yaxis,
                title: `${symbol.replace('USDT', '/USDT')} Price`,
                autorange: false,
                range: window.currentYAxisRange
            };
        }

        console.log('🔄 Reusing existing layout instead of recreating');
    } else {
        // Create new layout only if we don't have one
        layout = createLayoutForIndicators(indicatorTypes, Object.keys(indicatorsData));
        console.log('🆕 Creating new layout (first time or layout missing)');
    }

    // Layout configuration is now handled above in the reuse/create logic

    // Call Plotly.react immediately after layout creation
    if (!chartElement) {
        console.error('Combined WebSocket: Chart element not found');
        return;
    }

    // Preserve existing shapes when updating chart with historical data
    if (window.gd && window.gd.layout && window.gd.layout.shapes) {
        layout.shapes = window.gd.layout.shapes;
        console.log('🎨 DRAWINGS: Preserving', window.gd.layout.shapes.length, 'existing shapes during historical data update');
    }

    console.log('🔄 Using Plotly.react with user\'s zoom/pan settings preserved...');
    console.log('📊 Plotly.react input details:');
    console.log('  Chart element exists:', !!chartElement);
    console.log('  All traces count:', allTraces.length);
    console.log('  Trace names:', allTraces.map(t => t.name));
    console.log('  Layout has grid:', !!layout.grid);
    console.log('  Layout grid rows:', layout.grid ? layout.grid.rows : 'N/A');

    Plotly.react(chartElement, allTraces, layout).then(() => {
        console.log('✅ Plotly.react completed successfully with user settings preserved');
        console.log('[CHART_UPDATE] combinedData.js historical data - chart update completed at', new Date().toISOString());
        console.log('📊 User zoom/pan settings maintained - no forced autorange');

        // Debug: Check what traces are actually in the chart after update
        if (window.gd && window.gd.data) {
            console.log('🔍 POST-REACT: Chart traces after update:', window.gd.data.length);
            window.gd.data.forEach((trace, index) => {
                console.log(`  Trace ${index}: ${trace.name} (${trace.x ? trace.x.length : 0} points)`);
            });
        }

        // Apply autoscale after chart update to ensure all data is visible
        // DISABLED: Autoscale after historical data causes infinite loop
        // if (window.applyAutoscale && window.gd) {
        //     console.log('🔄 Applying autoscale after historical data update');
        //     window.applyAutoscale(window.gd);
        // }
    }).catch((error) => {
        console.error('❌ Error during Plotly.react:', error);
    });

    console.log('📊 Chart should now display all merged historical data');

    // Set up WebSocket message handler after subplots are initialized
    console.log('🎨 DRAWINGS: Chart layout with subplots initialized, setting up WebSocket message handler');
    try {
        setupWebSocketMessageHandler();
        console.log('✅ Combined WebSocket: Message handler setup completed in updateChartWithHistoricalData');
    } catch (error) {
        console.error('❌ Combined WebSocket: Failed to setup message handler in updateChartWithHistoricalData:', error);
    }

    // DEBUG: Check data range vs axis range
    if (timestamps.length > 0) {
        const dataMinTime = Math.min(...timestamps.map(t => t.getTime()));
        const dataMaxTime = Math.max(...timestamps.map(t => t.getTime()));
        const dataMinPrice = Math.min(...close);
        const dataMaxPrice = Math.max(...close);

        // console.log('🔍 DEBUG: Data range vs Axis range:');
        // console.log('  Data time range:', new Date(dataMinTime).toISOString(), 'to', new Date(dataMaxTime).toISOString());
        // console.log('  Data price range:', dataMinPrice, 'to', dataMaxPrice);
        // console.log('  Axis X range:', layout.xaxis.autorange ? 'autorange' : layout.xaxis.range);
        // console.log('  Axis Y range:', layout.yaxis.autorange ? 'autorange' : layout.yaxis.range);

        // Check if data is outside axis range - this could cause invisibility
        // console.log('🔍 DEBUG: Checking axis range adjustment...');
        // console.log('  layout.xaxis.autorange:', layout.xaxis.autorange);
        // console.log('  layout.xaxis.range:', layout.xaxis.range);
        // console.log('  window.currentXAxisRange:', window.currentXAxisRange);

        if (!layout.xaxis.autorange && layout.xaxis.range) {
            const axisMinTime = layout.xaxis.range[0].getTime();
            const axisMaxTime = layout.xaxis.range[1].getTime();

            // console.log('🔍 DEBUG: Axis time range:', new Date(axisMinTime).toISOString(), 'to', new Date(axisMaxTime).toISOString());

            const dataOutsideAxis = dataMinTime < axisMinTime || dataMaxTime > axisMaxTime;
            /* console.log('🔍 DEBUG: Data outside axis?', dataOutsideAxis, {
                dataMinLessThanAxisMin: dataMinTime < axisMinTime,
                dataMaxGreaterThanAxisMax: dataMaxTime > axisMaxTime
            });
            */

            if (dataOutsideAxis) {
                // console.warn('🚨 WARNING: Data range extends beyond axis range!');
                // console.warn('  Data min:', new Date(dataMinTime).toISOString(), 'vs Axis min:', layout.xaxis.range[0].toISOString());
                // console.warn('  Data max:', new Date(dataMaxTime).toISOString(), 'vs Axis max:', layout.xaxis.range[1].toISOString());

                // Honor user's zoom/pan settings - do not auto-adjust axis range
                // console.log('ℹ️ HONORING USER ZOOM: Not auto-adjusting axis range to preserve user\'s zoom/pan settings');
                // console.log('  User set range:', layout.xaxis.range[0].toISOString(), 'to', layout.xaxis.range[1].toISOString());
                // console.log('  Data available:', new Date(dataMinTime).toISOString(), 'to', new Date(dataMaxTime).toISOString());
            } else {
                // console.log('✅ Data is within current axis range - no adjustment needed');
            }
        } else {
            // console.log('ℹ️ Axis is in autorange mode or has no range set');
        }
    }

    /* console.log('Combined WebSocket: Layout X-axis settings:', {
        autorange: layout.xaxis.autorange,
        range: layout.xaxis.range,
        currentXAxisRange: window.currentXAxisRange
    });
    // console.log('Combined WebSocket: Layout Y-axis settings:', {
        autorange: layout.yaxis.autorange,
        range: layout.yaxis.range,
        currentYAxisRange: window.currentYAxisRange
    });
    */

    // Update price trace to use y (not yaxis)
    priceTrace.yaxis = 'y';

    // Force Y-axis autoscale if no specific range is set
    if (!window.currentYAxisRange) {
        // console.log('Combined WebSocket: Forcing Y-axis autoscale for new data range');
        window.isApplyingAutoscale = true;
        Plotly.relayout(chartElement, { 'yaxis.autorange': true }).then(() => {
            window.isApplyingAutoscale = false;
        }).catch(() => {
            window.isApplyingAutoscale = false;
        });
    }

    // Verify event handlers are still attached after Plotly.react
    delay(100).then(() => {
        if (window.gd && window.gd._ev) {
            const relayoutHandlers = window.gd._ev._events?.plotly_relayout;
            // console.log('Combined WebSocket: Event handlers after Plotly.react:', relayoutHandlers?.length || 0);
            if (!relayoutHandlers || relayoutHandlers.length === 0) {
                // console.warn('Combined WebSocket: Event handlers lost after Plotly.react - re-attaching...');
                if (typeof initializePlotlyEventHandlers === 'function') {
                    initializePlotlyEventHandlers(window.gd);
                    // console.log('Combined WebSocket: Event handlers re-attached after Plotly.react');
                }
            }
        }
    });

    // console.log(`Combined WebSocket: Updated chart with ${dataPoints.length} historical points and ${validTraces.length - 1} valid indicator traces (${allTraces.length - validTraces.length} traces filtered out due to NaN values)`);
}

function updateChartWithLiveData(dataPoint, symbol) {
    if (!dataPoint) {
        // console.warn('Combined WebSocket: No live data point to process');
        return;
    }

    const gd = document.getElementById('chart');
    if (!gd || !gd.data) {
        // console.warn('Combined WebSocket: Chart not ready for live update');
        return;
    }

    const timestamp = new Date(dataPoint.time * 1000);
    const price = dataPoint.ohlc.close;

    // Find the candlestick trace
    const priceTraceIndex = gd.data.findIndex(trace => trace.type === 'candlestick');
    if (priceTraceIndex === -1) {
        // console.warn('Combined WebSocket: Could not find candlestick trace');
        return;
    }

    const trace = gd.data[priceTraceIndex];

    // Check if this is a new candle or update to existing
    const lastTimestamp = trace.x[trace.x.length - 1];
    const isNewCandle = timestamp.getTime() !== lastTimestamp.getTime();

    if (isNewCandle) {
        // Add new candle
        // console.log('[CHART_UPDATE] combinedData.js live data - adding new candle at', new Date().toISOString());
        const newData = {
            x: [[timestamp]],
            open: [[dataPoint.ohlc.open]],
            high: [[dataPoint.ohlc.high]],
            low: [[dataPoint.ohlc.low]],
            close: [[dataPoint.ohlc.close]]
        };

        Plotly.extendTraces(gd, newData, [priceTraceIndex]);
        // console.log('[CHART_UPDATE] combinedData.js live data - new candle added');
    } else {
        // Update existing candle
        // console.log('[CHART_UPDATE] combinedData.js live data - updating existing candle at', new Date().toISOString());
        trace.high[trace.high.length - 1] = Math.max(trace.high[trace.high.length - 1], dataPoint.ohlc.high);
        trace.low[trace.low.length - 1] = Math.min(trace.low[trace.low.length - 1], dataPoint.ohlc.low);
        trace.close[trace.close.length - 1] = dataPoint.ohlc.close;

        // Preserve shapes when updating live data
        const layoutWithShapes = { ...gd.layout };
        if (gd.layout && gd.layout.shapes) {
            layoutWithShapes.shapes = gd.layout.shapes;
        }

        Plotly.react(gd, gd.data, layoutWithShapes);
        // console.log('[CHART_UPDATE] combinedData.js live data - existing candle updated');
    }

    // Update price line if it exists
    updateOrAddRealtimePriceLine(gd, price, timestamp.getTime(), timestamp.getTime() + (getTimeframeSecondsJS(combinedResolution) * 1000));

    // console.log(`Combined WebSocket: Updated live data for ${symbol} at ${timestamp.toISOString()}`);
}

function closeCombinedWebSocket(reason = "Closing WebSocket") {
    if (combinedWebSocket) {
        // console.log(`Combined WebSocket: Closing connection for ${combinedSymbol}. Reason: ${reason}`);
        combinedWebSocket.onclose = null;
        combinedWebSocket.close(1000, reason);
        combinedWebSocket = null;
        combinedSymbol = '';
    }

    // Clear any pending historical data timeout
    if (window.historicalDataTimeout) {
        clearTimeout(window.historicalDataTimeout);
        window.historicalDataTimeout = null;
        // console.log('Combined WebSocket: Cleared pending historical data timeout');
    }

    // Reset accumulation state
    accumulatedHistoricalData = [];
    isAccumulatingHistorical = false;
    historicalDataSymbol = '';
}

function updateCombinedIndicators(newIndicators) {
    // console.log('Combined WebSocket: Updating indicators from', combinedIndicators, 'to', newIndicators);

    const oldIndicators = [...combinedIndicators];
    combinedIndicators = newIndicators;

    // Determine which indicators are new
    const newIndicatorIds = newIndicators.filter(ind => !oldIndicators.includes(ind));

    // Send new config to WebSocket
    if (combinedWebSocket && combinedWebSocket.readyState === WebSocket.OPEN) {
        sendCombinedConfig();
    }

    // Calculate new indicators client-side for immediate display
    if (newIndicatorIds.length > 0) {
        // console.log('Combined WebSocket: Calculating new indicators client-side:', newIndicatorIds);
        calculateIndicatorsClientSide(newIndicatorIds);
    }

    // Update chart display for removed indicators
    updateChartIndicatorsDisplay(oldIndicators, newIndicators);
}

function calculateIndicatorsClientSide(newIndicatorIds) {
    // Calculate indicators client-side using existing chart data for immediate display
    const chartElement = document.getElementById('chart');
    if (!chartElement || !window.gd || !window.gd.data) {
        // console.log('Combined WebSocket: No chart data available for client-side calculation');
        return;
    }

    // Get existing OHLC data from the chart
    const priceTrace = window.gd.data.find(trace => trace.type === 'candlestick');
    if (!priceTrace) {
        // console.log('Combined WebSocket: No price data available for indicator calculation');
        return;
    }

    // console.log('Combined WebSocket: Calculating indicators client-side for:', newIndicatorIds);

    // Extract OHLC data
    const closes = priceTrace.close || [];
    const highs = priceTrace.high || [];
    const lows = priceTrace.low || [];
    const opens = priceTrace.open || [];
    const timestamps = priceTrace.x || [];

    if (closes.length === 0) {
        // console.log('Combined WebSocket: Insufficient data for indicator calculation');
        return;
    }

    // Calculate each new indicator
    const calculatedTraces = [];

    newIndicatorIds.forEach((indicatorId, index) => {
        try {
            // Calculate the correct y-axis for this indicator (correct order)
            const yAxisName = `y${index + 2}`; // y2, y3, y4, etc. in correct order

            const traces = calculateIndicator(indicatorId, timestamps, opens, highs, lows, closes, yAxisName);
            calculatedTraces.push(...traces);
        } catch (error) {
            // console.error(`Combined WebSocket: Error calculating ${indicatorId}:`, error);
        }
    });

    if (calculatedTraces.length > 0) {
        // Add calculated traces to the chart
        const updatedData = [...window.gd.data, ...calculatedTraces];
        const updatedLayout = createLayoutForIndicators([...new Set([...getCurrentActiveIndicators(), ...newIndicatorIds])], getCurrentActiveIndicators());

        Plotly.react(chartElement, updatedData, updatedLayout);
        // console.log(`Combined WebSocket: Added ${calculatedTraces.length} client-side calculated traces`);
    }
}

function getCurrentActiveIndicators() {
    // Get indicators that currently have traces in the chart
    if (!window.gd || !window.gd.data) return [];

    const indicators = [];
    window.gd.data.forEach(trace => {
        if (trace.name === 'MACD' || trace.name === 'MACD Signal' || trace.name === 'MACD Histogram') {
            if (!indicators.includes('macd')) indicators.push('macd');
        } else if (trace.name === 'RSI' || trace.name === 'RSI_SMA14') {
            if (!indicators.includes('rsi')) indicators.push('rsi');
        } else if (trace.name === 'Stoch K' || trace.name === 'Stoch D') {
            // Find the stochrsi variant
            const stochVariant = window.combinedIndicators?.find(id => id.startsWith('stochrsi'));
            if (stochVariant && !indicators.includes(stochVariant)) indicators.push(stochVariant);
        } else if (trace.name === 'JMA') {
            if (!indicators.includes('jma')) indicators.push('jma');
        } else if (trace.name === 'Open Interest') {
            if (!indicators.includes('open_interest')) indicators.push('open_interest');
        }
    });

    return indicators;
}

function calculateIndicator(indicatorId, timestamps, opens, highs, lows, closes, yAxisName) {
    const traces = [];

    switch (indicatorId) {
        case 'rsi':
            const rsiValues = calculateRSI(closes, 14);
            if (rsiValues.length > 0) {
                traces.push({
                    x: timestamps.slice(-rsiValues.length),
                    y: rsiValues,
                    type: 'scatter',
                    mode: 'lines',
                    name: 'RSI',
                    line: { color: 'purple' },
                    xaxis: 'x',
                    yaxis: yAxisName,
                    hoverinfo: 'all'
                });
            }
            break;

        case 'macd':
            const macdResult = calculateMACD(closes);
            if (macdResult.macd.length > 0) {
                traces.push({
                    x: timestamps.slice(-macdResult.macd.length),
                    y: macdResult.macd,
                    type: 'scatter',
                    mode: 'lines',
                    name: 'MACD',
                    line: { color: 'blue' },
                    xaxis: 'x',
                    yaxis: yAxisName,
                    hoverinfo: 'all'
                });

                if (macdResult.signal.length > 0) {
                    traces.push({
                        x: timestamps.slice(-macdResult.signal.length),
                        y: macdResult.signal,
                        type: 'scatter',
                        mode: 'lines',
                        name: 'MACD Signal',
                        line: { color: 'orange' },
                        xaxis: 'x',
                        yaxis: yAxisName,
                        hoverinfo: 'all'
                    });
                }

                if (macdResult.histogram.length > 0) {
                    traces.push({
                        x: timestamps.slice(-macdResult.histogram.length),
                        y: macdResult.histogram,
                        type: 'bar',
                        name: 'MACD Histogram',
                        marker: {
                            color: macdResult.histogram.map(v => v >= 0 ? 'green' : 'red')
                        },
                        xaxis: 'x',
                        yaxis: yAxisName,
                        hoverinfo: 'all'
                    });
                }
            }
            break;

        default:
            // console.log(`Combined WebSocket: Client-side calculation not implemented for ${indicatorId}`);
    }

    return traces;
}

function calculateRSI(closes, period = 14) {
    if (closes.length < period + 1) return [];

    const gains = [];
    const losses = [];

    for (let i = 1; i < closes.length; i++) {
        const change = closes[i] - closes[i - 1];
        gains.push(change > 0 ? change : 0);
        losses.push(change < 0 ? Math.abs(change) : 0);
    }

    const rsi = [];
    let avgGain = gains.slice(0, period).reduce((sum, gain) => sum + gain, 0) / period;
    let avgLoss = losses.slice(0, period).reduce((sum, loss) => sum + loss, 0) / period;

    if (avgLoss === 0) {
        rsi.push(100);
    } else {
        const rs = avgGain / avgLoss;
        rsi.push(100 - (100 / (1 + rs)));
    }

    for (let i = period; i < gains.length; i++) {
        avgGain = (avgGain * (period - 1) + gains[i]) / period;
        avgLoss = (avgLoss * (period - 1) + losses[i]) / period;

        if (avgLoss === 0) {
            rsi.push(100);
        } else {
            const rs = avgGain / avgLoss;
            rsi.push(100 - (100 / (1 + rs)));
        }
    }

    return rsi;
}

function calculateMACD(closes, fastPeriod = 12, slowPeriod = 26, signalPeriod = 9) {
    const fastEMA = calculateEMA(closes, fastPeriod);
    const slowEMA = calculateEMA(closes, slowPeriod);

    const macd = [];
    const minLength = Math.min(fastEMA.length, slowEMA.length);

    for (let i = 0; i < minLength; i++) {
        macd.push(fastEMA[i] - slowEMA[i]);
    }

    const signal = calculateEMA(macd, signalPeriod);
    const histogram = [];

    const histMinLength = Math.min(macd.length, signal.length);
    for (let i = 0; i < histMinLength; i++) {
        histogram.push(macd[i] - signal[i]);
    }

    return { macd, signal, histogram };
}

function calculateEMA(values, period) {
    if (values.length < period) return [];

    const ema = [];
    const multiplier = 2 / (period + 1);

    // First EMA value is SMA
    let sum = 0;
    for (let i = 0; i < period; i++) {
        sum += values[i];
    }
    ema.push(sum / period);

    // Calculate remaining EMA values
    for (let i = period; i < values.length; i++) {
        const currentEMA = (values[i] - ema[ema.length - 1]) * multiplier + ema[ema.length - 1];
        ema.push(currentEMA);
    }

    return ema;
}

function updateChartIndicatorsDisplay(oldIndicators, newIndicators) {
    const chartElement = document.getElementById('chart');
    if (!chartElement || !window.gd || !window.gd.data) {
        // console.log('Combined WebSocket: Chart not ready for indicator update');
        return;
    }

    const currentData = window.gd.data;
    if (!currentData || currentData.length === 0) {
        // console.log('Combined WebSocket: No chart data available for indicator update');
        return;
    }

    // console.log('Combined WebSocket: Updating chart indicators display');
    // console.log('Combined WebSocket: Current traces:', currentData.map(t => ({ name: t.name, type: t.type, yaxis: t.yaxis })));

    // Find the price trace (candlestick)
    const priceTraceIndex = currentData.findIndex(trace => trace.type === 'candlestick');
    if (priceTraceIndex === -1) {
        // console.warn('Combined WebSocket: Could not find price trace for indicator update');
        return;
    }

    const priceTrace = currentData[priceTraceIndex];
    const currentIndicatorTraces = currentData.slice(1); // All traces except the first (price)

    // Determine which indicators to add/remove
    const indicatorsToAdd = newIndicators.filter(ind => !oldIndicators.includes(ind));
    const indicatorsToRemove = oldIndicators.filter(ind => !newIndicators.includes(ind));

    // console.log('Combined WebSocket: Indicators to add:', indicatorsToAdd);
    // console.log('Combined WebSocket: Indicators to remove:', indicatorsToRemove);

    // Start with price trace
    let updatedTraces = [priceTrace];

    // Group traces by indicator type and assign y-axes
    const tracesByIndicator = {};

    // First pass: group traces by indicator
    currentIndicatorTraces.forEach(trace => {
        let traceIndicatorId = null;
        if (trace.name === 'MACD' || trace.name === 'MACD Signal' || trace.name === 'MACD Histogram') {
            traceIndicatorId = 'macd';
        } else if (trace.name === 'RSI' || trace.name === 'RSI_SMA14') {
            traceIndicatorId = 'rsi';
        } else if (trace.name === 'Stoch K' || trace.name === 'Stoch D') {
            traceIndicatorId = newIndicators.find(id => id.startsWith('stochrsi'));
        } else if (trace.name === 'JMA') {
            traceIndicatorId = 'jma';
        } else if (trace.name === 'Open Interest') {
            traceIndicatorId = 'open_interest';
        }

        if (traceIndicatorId && newIndicators.includes(traceIndicatorId)) {
            if (!tracesByIndicator[traceIndicatorId]) {
                tracesByIndicator[traceIndicatorId] = [];
            }
            tracesByIndicator[traceIndicatorId].push(trace);
            // console.log(`Combined WebSocket: Keeping trace ${trace.name} for indicator ${traceIndicatorId}`);
        } else {
            // console.log(`Combined WebSocket: Removing trace ${trace.name} (indicator ${traceIndicatorId} not selected or not found)`);
        }
    });

    // FORCE MACD to be first by using hardcoded order
    const forcedIndicatorOrder = ['macd', 'rsi', 'stochrsi_9_3', 'stochrsi_14_3', 'stochrsi_40_4', 'stochrsi_60_10', 'open_interest', 'jma'];
    const activeIndicatorIds = forcedIndicatorOrder.filter(indicatorId => newIndicators.includes(indicatorId));

    // console.log('FORCED Y-AXIS ORDER - Active indicators in forced order:', activeIndicatorIds);
    // console.log('FORCED Y-AXIS ORDER - MACD is first:', activeIndicatorIds[0] === 'macd');

    // console.log('Combined WebSocket: updateChartIndicatorsDisplay - newIndicators:', newIndicators);
    // console.log('Combined WebSocket: updateChartIndicatorsDisplay - activeIndicatorIds:', activeIndicatorIds);

    // Second pass: assign y-axes based on active indicators order
    // Use normal indexing to match the HTML template order
    activeIndicatorIds.forEach((indicatorId, indicatorIndex) => {
        // Use normal indexing for correct visual order (first indicator at top)
        const yAxisName = `y${indicatorIndex + 2}`; // y2, y3, y4, etc. in correct order
        const indicatorTraces = tracesByIndicator[indicatorId] || [];

        if (indicatorTraces.length > 0) {
            // Assign existing traces to their y-axis
            indicatorTraces.forEach(trace => {
                trace.yaxis = yAxisName;
                updatedTraces.push(trace);
                // console.log(`Combined WebSocket: Assigned ${trace.name} to ${yAxisName} (correct visual order)`);
            });
        } else {
            // No traces yet for this indicator (newly selected)
            // console.log(`Combined WebSocket: No traces yet for ${indicatorId}, will appear when new data arrives`);
        }
    });

    // Create layout for updated traces
    const layout = createLayoutForIndicators(activeIndicatorIds, Object.keys(tracesByIndicator));

    // console.log('Combined WebSocket: Updated traces count:', updatedTraces.length);
    // console.log('Combined WebSocket: Active indicator IDs:', activeIndicatorIds);
    // console.log('Combined WebSocket: Updated layout:', layout);

    // Preserve existing shapes when updating indicators
    if (window.gd && window.gd.layout && window.gd.layout.shapes) {
        layout.shapes = window.gd.layout.shapes;
        console.log('🎨 DRAWINGS: Preserving', window.gd.layout.shapes.length, 'existing shapes during indicator update');
    }

    // Update the chart
    Plotly.react(chartElement, updatedTraces, layout);

    // console.log('Combined WebSocket: Chart updated with new indicator selection');

    // Note: New indicators will appear when new WebSocket data arrives
    if (indicatorsToAdd.length > 0) {
        // console.log('Combined WebSocket: New indicators will appear when new data arrives:', indicatorsToAdd);
    }
}

function createLayoutForIndicators(activeIndicatorIds, indicatorsWithData = []) {
    const baseLayout = {
        title: `${combinedSymbol} - ${combinedResolution.toUpperCase()}`,
        // Remove fixed height to allow full viewport height
        autosize: true, // Enable autosizing
        xaxis: {
            rangeslider: { visible: false },
            type: 'date',
            autorange: !window.currentXAxisRange,
            range: window.currentXAxisRange ? [
                new Date(window.currentXAxisRange[0] < 2e9 ? window.currentXAxisRange[0] * 1000 : window.currentXAxisRange[0]),
                new Date(window.currentXAxisRange[1] < 2e9 ? window.currentXAxisRange[1] * 1000 : window.currentXAxisRange[1])
            ] : undefined,
            showticklabels: true // Show x-axis labels (timestamps)
        },
        yaxis: {
            title: `${combinedSymbol.replace('USDT', '/USDT')} Price`,
            autorange: !window.currentYAxisRange,
            range: window.currentYAxisRange ? window.currentYAxisRange : undefined,
            showticklabels: true,
            showgrid: true,
            side: 'left',
            domain: activeIndicatorIds.length > 0 ? [0, (3 / (3 + activeIndicatorIds.length))] : [0, 1] // Set explicit domain for price chart
        },
        showlegend: false,
        hovermode: 'x unified',
        margin: { l: 50, r: 10, b: 20, t: 40 }
    };

    if (activeIndicatorIds.length > 0) {
        // Price chart is twice the height of each individual indicator chart
        const numIndicators = activeIndicatorIds.length;
        const priceChartProportion = 4; // Price chart is 4 parts
        const totalProportions = priceChartProportion + numIndicators;

        const priceChartHeight = priceChartProportion / totalProportions;
        const indicatorHeight = 1 / totalProportions;        

        // Create grid with manual row heights
        let rowHeights = [priceChartHeight];
        for (let i = 0; i < numIndicators; i++) {
            rowHeights.push(indicatorHeight);
        }
        

        baseLayout.grid = {
            rows: rowHeights.length,
            columns: 1,
            pattern: 'domain',
            roworder: 'top to bottom',
            rowheights: rowHeights,
            vertical_spacing: 0.05
        };

        console.log(`DEBUG: Grid created with ${rowHeights.length} rows, vertical_spacing: 0.05`);

        // Let Plotly handle domain calculation automatically with pattern: 'domain'
        console.log(`DEBUG: Price chart domain handled automatically by grid pattern`);

        // Set manual domains for each y-axis to ensure proper height allocation
        activeIndicatorIds.forEach((indicatorId, index) => {
            const yAxisName = `yaxis${index + 2}`;
            const indicatorIndex = index; // 0-based index for indicators
            const totalIndicators = activeIndicatorIds.length;

            // Calculate domain for this indicator
            // Price chart takes first portion, then each indicator gets equal share of remaining space
            const priceDomainEnd = priceChartProportion / totalProportions;
            const indicatorDomainStart = priceDomainEnd + (indicatorIndex * indicatorHeight);
            const indicatorDomainEnd = priceDomainEnd + ((indicatorIndex + 1) * indicatorHeight);

            baseLayout[yAxisName] = {
                title: {
                    text: (() => {
                        const displayNames = {
                            'macd': 'MACD',
                            'rsi': 'RSI',
                            'stochrsi_9_3': 'StochRSI (9,3)',
                            'stochrsi_14_3': 'StochRSI (14,3)',
                            'stochrsi_40_4': 'StochRSI (40,4)',
                            'stochrsi_60_10': 'StochRSI (60,10)',
                            'jma': 'JMA',
                            'open_interest': 'Open Interest'
                        };
                        return displayNames[indicatorId] || indicatorId.toUpperCase();
                    })(),
                    standoff: 10
                },
                autorange: true,
                fixedrange: false, // Allow zoom on indicator y-axes
                domain: [indicatorDomainStart, indicatorDomainEnd], // Set explicit domain
                side: 'left'
            };
            console.log(`DEBUG: ${indicatorId} y-axis created with domain [${indicatorDomainStart.toFixed(3)}, ${indicatorDomainEnd.toFixed(3)}]`);
        });

        // Domain coverage handled by explicit domain settings for each y-axis
        console.log(`DEBUG: Domain coverage handled by explicit domain settings`);
    } else {
        // No indicators - let Plotly handle domain automatically
        console.log(`DEBUG: No indicators, domain handled automatically`);
    }


    return baseLayout;
}



function updateCombinedResolution(newResolution) {
    combinedResolution = newResolution;
    if (combinedWebSocket && combinedWebSocket.readyState === WebSocket.OPEN) {
        sendCombinedConfig();
    }
}

// Helper function to get timeframe seconds (assuming it's defined elsewhere)
function getTimeframeSecondsJS(timeframe) {
    const multipliers = {
        "1m": 60,
        "5m": 300,
        "1h": 3600,
        "1d": 86400,
        "1w": 604800
    };
    return multipliers[timeframe] || 3600;
}

// Window resize handler to maintain full height responsiveness
window.addEventListener('resize', function() {
    const chartElement = document.getElementById('chart');
    if (chartElement && window.gd) {
        // console.log('Window resized, triggering chart relayout for full height');
        Plotly.relayout(chartElement, { autosize: true });
    }
});

// Export functions to global scope for use by other modules
window.setupCombinedWebSocket = setupCombinedWebSocket;
window.closeCombinedWebSocket = closeCombinedWebSocket;
window.updateCombinedIndicators = updateCombinedIndicators;
window.updateCombinedResolution = updateCombinedResolution;
window.setupWebSocketMessageHandler = setupWebSocketMessageHandler;
window.mergeHistoricalData = mergeHistoricalData;

// DEBUG: Add debugging function for chart diagnosis
window.debugChartState = function() {
    // console.log('🔍 CHART DEBUG INFORMATION:');
    // console.log('Current WebSocket state:', combinedWebSocket ? combinedWebSocket.readyState : 'none');
    // console.log('Accumulated data points:', accumulatedHistoricalData.length);
    // console.log('Is accumulating:', isAccumulatingHistorical);
    // console.log('Historical data symbol:', historicalDataSymbol);

    if (window.gd) {
        // console.log('Chart exists with', window.gd.data ? window.gd.data.length : 0, 'traces');
        if (window.gd.data && window.gd.data.length > 0) {
            window.gd.data.forEach((trace, index) => {
                // console.log(`Trace ${index} (${trace.name}): ${trace.x ? trace.x.length : 0} points`);
                if (trace.x && trace.x.length > 0) {
                    // console.log(`  First data point: ${trace.x[0]}`);
                    // console.log(`  Last data point: ${trace.x[trace.x.length - 1]}`);
                }
            });
        }
        /* console.log('Chart layout:', {
            xaxis: window.gd.layout.xaxis,
            yaxis: window.gd.layout.yaxis
        });
        */
    } else {
        // console.log('Chart (window.gd) does not exist');
    }

    // console.log('Current axis ranges:');
    // console.log('  X-axis:', window.currentXAxisRange);
    // console.log('  Y-axis:', window.currentYAxisRange);

    return {
        websocket: combinedWebSocket ? combinedWebSocket.readyState : 'none',
        accumulatedData: accumulatedHistoricalData.length,
        chartTraces: window.gd?.data?.length || 0,
        xAxisRange: window.currentXAxisRange,
        yAxisRange: window.currentYAxisRange
    };
};

// DEBUG: Add function to check WebSocket message handler status
window.checkWebSocketStatus = function() {
    console.log('🔍 STATUS: Checking WebSocket connection status...');

    if (!combinedWebSocket) {
        console.log('❌ STATUS: No WebSocket connection found');
        return { connected: false, readyState: 'none', hasHandler: false };
    }

    const status = {
        connected: combinedWebSocket.readyState === WebSocket.OPEN,
        readyState: combinedWebSocket.readyState,
        hasHandler: typeof combinedWebSocket.onmessage !== 'undefined',
        url: combinedWebSocket.url
    };

    console.log('✅ STATUS: WebSocket status:', status);
    return status;
};

// DEBUG: Add function to manually test historical data loading
window.testHistoricalDataLoad = function() {
    // console.log('🧪 TESTING HISTORICAL DATA LOAD...');

    // Check if we have a chart
    if (!window.gd) {
        // console.error('❌ No chart found (window.gd is undefined)');
        return;
    }

    // Check current data
    const currentDataPoints = window.gd.data && window.gd.data[0] ? window.gd.data[0].x.length : 0;
    // console.log(`📊 Current chart has ${currentDataPoints} data points`);

    // Check axis ranges
    const xRange = window.gd.layout.xaxis.range;
    if (xRange) {
        // console.log('📈 Current X-axis range:', xRange[0], 'to', xRange[1]);
    }

    // Simulate a pan to the left by calling the pan detection
    // console.log('🎯 Simulating pan detection...');
    if (typeof window.testPanningDetection === 'function') {
        window.testPanningDetection();
    } else {
        // console.warn('⚠️ testPanningDetection function not found');
    }

    // console.log('✅ Test completed. Check console for results.');
};

// DEBUG: Add chart rendering validation function
window.validateChartRendering = function() {
    // console.log('🔍 CHART RENDERING VALIDATION...');

    if (!window.gd) {
        // console.error('❌ No chart found (window.gd is undefined)');
        return { valid: false, error: 'No chart found' };
    }

    const validation = {
        valid: true,
        errors: [],
        warnings: [],
        data: {}
    };

    // Check if chart has data
    if (!window.gd.data || window.gd.data.length === 0) {
        validation.errors.push('Chart has no data traces');
        validation.valid = false;
    } else {
        validation.data.traceCount = window.gd.data.length;
        validation.data.firstTracePoints = window.gd.data[0] ? window.gd.data[0].x.length : 0;
    }

    // Check X-axis range
    if (window.gd.layout.xaxis.range) {
        const xRange = window.gd.layout.xaxis.range;
        validation.data.xAxisRange = {
            start: xRange[0],
            end: xRange[1],
            duration: xRange[1].getTime() - xRange[0].getTime(),
            durationHours: (xRange[1].getTime() - xRange[0].getTime()) / (1000 * 60 * 60)
        };
        // console.log('📊 X-axis range validation:', validation.data.xAxisRange);
    } else {
        validation.warnings.push('No X-axis range set');
    }

    // Check Y-axis range
    if (window.gd.layout.yaxis.range) {
        validation.data.yAxisRange = window.gd.layout.yaxis.range;
        // console.log('📊 Y-axis range validation:', validation.data.yAxisRange);
    } else {
        validation.warnings.push('No Y-axis range set');
    }

    // Compare with saved ranges
    if (window.currentXAxisRange) {
        const savedStart = new Date(window.currentXAxisRange[0] < 2e9 ? window.currentXAxisRange[0] * 1000 : window.currentXAxisRange[0]);
        const savedEnd = new Date(window.currentXAxisRange[1] < 2e9 ? window.currentXAxisRange[1] * 1000 : window.currentXAxisRange[1]);
        const chartStart = window.gd.layout.xaxis.range ? window.gd.layout.xaxis.range[0] : null;
        const chartEnd = window.gd.layout.xaxis.range ? window.gd.layout.xaxis.range[1] : null;

        if (chartStart && chartEnd) {
            const startDiff = Math.abs(savedStart.getTime() - chartStart.getTime());
            const endDiff = Math.abs(savedEnd.getTime() - chartEnd.getTime());

            validation.data.rangeComparison = {
                savedRange: [savedStart, savedEnd],
                chartRange: [chartStart, chartEnd],
                startDifferenceMs: startDiff,
                endDifferenceMs: endDiff,
                startDifferenceHours: startDiff / (1000 * 60 * 60),
                endDifferenceHours: endDiff / (1000 * 60 * 60)
            };

            if (startDiff > 60000 || endDiff > 60000) { // More than 1 minute difference
                validation.warnings.push(`Significant range mismatch: start diff ${startDiff / 1000}s, end diff ${endDiff / 1000}s`);
            }
        }
    }

    // Check for data gaps in the chart
    if (window.gd.data && window.gd.data[0] && window.gd.data[0].x) {
        const timestamps = window.gd.data[0].x.map(t => t.getTime()).sort((a, b) => a - b);
        let gaps = 0;
        const expectedInterval = 60 * 60 * 1000; // 1 hour in milliseconds for 1h resolution

        for (let i = 1; i < timestamps.length; i++) {
            const gap = timestamps[i] - timestamps[i-1];
            if (gap > expectedInterval * 1.5) { // Allow 50% tolerance
                gaps++;
            }
        }

        validation.data.dataGaps = gaps;
        if (gaps > 0) {
            validation.warnings.push(`${gaps} data gaps detected in chart`);
        }
    }

    // Check indicator data quality
    if (window.gd.data) {
        let totalNaN = 0;
        let totalPoints = 0;

        window.gd.data.forEach((trace, index) => {
            if (trace.y && Array.isArray(trace.y)) {
                const nanCount = trace.y.filter(v => v === null || v === undefined || isNaN(v)).length;
                totalNaN += nanCount;
                totalPoints += trace.y.length;

                if (nanCount > 0) {
                    validation.warnings.push(`Trace ${index} (${trace.name}): ${nanCount}/${trace.y.length} NaN values`);
                }
            }
        });

        validation.data.nanStats = {
            totalNaN,
            totalPoints,
            nanPercentage: totalPoints > 0 ? (totalNaN / totalPoints * 100).toFixed(1) : 0
        };

        if (totalNaN > totalPoints * 0.1) { // More than 10% NaN values
            validation.warnings.push(`High NaN percentage: ${validation.data.nanStats.nanPercentage}% of all data points`);
        }
    }

    // Summary
    // console.log('📋 VALIDATION SUMMARY:');
    // console.log('  Valid:', validation.valid);
    // console.log('  Errors:', validation.errors.length);
    // console.log('  Warnings:', validation.warnings.length);
    // console.log('  Data points:', validation.data.firstTracePoints || 0);
    // console.log('  NaN percentage:', validation.data.nanStats ? validation.data.nanStats.nanPercentage + '%' : 'N/A');

    if (validation.errors.length > 0) {
        // console.error('❌ ERRORS:', validation.errors);
    }

    if (validation.warnings.length > 0) {
        // console.warn('⚠️ WARNINGS:', validation.warnings);
    }

    return validation;
};
