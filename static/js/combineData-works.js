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
        const lineDefinition = {
                type: 'line',
                name: REALTIME_PRICE_LINE_NAME,
                isSystemShape: true, // Mark as a system shape
                yref: 'y',
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
            yref: 'y',       // Relative to the y-axis data scale of the main price chart
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
        sendCombinedConfig();
    };

    // Message handler will be set up after subplots are initialized
    // combinedWebSocket.onmessage = ... (moved to setupWebSocketMessageHandler)

    combinedWebSocket.onerror = (error) => {
        // console.error(`Combined WebSocket: Error for ${symbol}:`, error);
    };

    combinedWebSocket.onclose = (event) => {
        // console.log(`Combined WebSocket: Connection closed for ${symbol}. Reason: '${event.reason}', Code: ${event.code}`);

        // Attempt to reconnect if live data is still enabled
        if (window.liveDataCheckbox && window.liveDataCheckbox.checked && event.code !== 1000) {
            // console.log(`Combined WebSocket: Attempting to reconnect to ${symbol} in 5 seconds...`);
            setTimeout(() => {
                if (window.liveDataCheckbox.checked && window.symbolSelect.value === symbol) {
                    setupCombinedWebSocket(symbol, indicators, resolution, fromTs, toTs);
                }
            }, 5000);
        }
    };
}

function setupWebSocketMessageHandler() {
    if (!combinedWebSocket) {
        console.warn('Combined WebSocket: Cannot setup message handler - WebSocket not initialized');
        return;
    }

    combinedWebSocket.onmessage = (event) => {
        try {
            const message = JSON.parse(event.data);
            console.log('📨 Combined WebSocket: Received message:', message.type, message.symbol || '');
            console.log('📨 Combined WebSocket: Message details:', {
                type: message.type,
                symbol: message.symbol,
                dataLength: message.data ? message.data.length : 0,
                hasIndicators: message.data && message.data[0] ? !!message.data[0].indicators : false
            });

            if (message.type === 'historical') {
                console.log('📊 Processing historical data message');
                handleHistoricalData(message);
            } else if (message.type === 'live') {
                console.log('🔴 Processing live data message');
                handleLiveData(message);
            } else if (message.type === 'drawings' || (message.type && message.type.trim() === 'drawings')) {
                console.log('🎨 DRAWINGS: Processing drawings message with', message.data ? message.data.length : 0, 'drawings');
                console.log('🎨 DRAWINGS: Full message:', message);
                handleDrawingsData(message);
            } else {
                console.warn('🎨 DRAWINGS: Unknown message type:', message.type, '(expected: historical, live, or drawings)');
            }
        } catch (e) {
            console.error("❌ Combined WebSocket: Error parsing message:", e, "Raw data:", event.data);
        }
    };

    console.log('🎨 DRAWINGS: WebSocket message handler set up after subplots initialization');
}

function sendCombinedConfig() {
    if (!combinedWebSocket || combinedWebSocket.readyState !== WebSocket.OPEN) {
        // console.warn('Combined WebSocket: Cannot send config - connection not open');
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

    // console.log('Combined WebSocket: Sending config:', config);
    // console.log('Combined WebSocket: WebSocket readyState:', combinedWebSocket.readyState);
    // console.log('Combined WebSocket: Config timestamps - from_ts:', combinedFromTs, 'to_ts:', combinedToTs);
    // console.log('[TIMESTAMP DEBUG] combinedData.js - WebSocket config timestamps:');
    // console.log('  combinedFromTs:', combinedFromTs, '(ISO timestamp string)');
    // console.log('  combinedToTs:', combinedToTs, '(ISO timestamp string)');
    // console.log('  from_ts in config:', config.from_ts);
    // console.log('  to_ts in config:', config.to_ts);

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
    // console.log('💾 Stored server range for client comparison. Use window.compareClientServerRanges() to compare.');

    try {
        combinedWebSocket.send(JSON.stringify(config));
        // console.log('Combined WebSocket: Config sent successfully');
    } catch (error) {
        // console.error('Combined WebSocket: Error sending config:', error);
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
        // console.warn('Combined WebSocket: Invalid historical data format');
        return;
    }

    if (message.data.length === 0) {
        // console.warn('Combined WebSocket: Received empty historical data array');
        return;
    }

    // Check if this is a new accumulation session
    if (!isAccumulatingHistorical || historicalDataSymbol !== message.symbol) {
        // Start new accumulation
        accumulatedHistoricalData = [];
        isAccumulatingHistorical = true;
        historicalDataSymbol = message.symbol;
        // console.log(`Combined WebSocket: Starting new historical data accumulation for ${message.symbol}`);
    }

    // Add this batch to accumulated data
    const previousCount = accumulatedHistoricalData.length;
    accumulatedHistoricalData = accumulatedHistoricalData.concat(message.data);
    console.log(`📊 Combined WebSocket: Accumulated ${accumulatedHistoricalData.length} total data points so far (added ${message.data.length}, previous: ${previousCount})`);

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

    // Set a timeout to process accumulated data after a delay (assuming all batches received)
    window.historicalDataTimeout = setTimeout(() => {
        console.log(`📊 Combined WebSocket: Processing accumulated historical data: ${accumulatedHistoricalData.length} points for ${historicalDataSymbol}`);
        console.log('🔍 DEBUG: About to call updateChartWithHistoricalData with:', {
            dataPoints: accumulatedHistoricalData.length,
            symbol: historicalDataSymbol,
            firstTimestamp: accumulatedHistoricalData[0]?.time,
            lastTimestamp: accumulatedHistoricalData[accumulatedHistoricalData.length - 1]?.time
        });

        // Process accumulated historical data and update chart
        updateChartWithHistoricalData(accumulatedHistoricalData, historicalDataSymbol);

        // Reset accumulation state
        accumulatedHistoricalData = [];
        isAccumulatingHistorical = false;
        historicalDataSymbol = '';
    }, 500); // 500ms delay to allow for more batches
}

function handleLiveData(message) {
    // console.log(`Combined WebSocket: Received live data for ${message.symbol}`);

    if (!message.data) {
        // console.warn('Combined WebSocket: Invalid live data format');
        return;
    }

    // Process live data and update chart
    updateChartWithLiveData(message.data, message.symbol);
}

function handleDrawingsData(message) {
    console.log(`Combined WebSocket: Received drawings data for ${message.symbol}`);

    if (!message.data || !Array.isArray(message.data)) {
        console.warn('Combined WebSocket: Invalid drawings data format');
        return;
    }

    if (message.data.length === 0) {
        console.log('Combined WebSocket: No drawings to process');
        return;
    }

    console.log('🎨 DRAWINGS: Processing', message.data.length, 'drawings:', message.data);

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

    console.log('🎨 DRAWINGS: Current shapes before adding:', window.gd.layout.shapes.length);

    // Process each drawing
    drawings.forEach((drawing, index) => {
        try {
            console.log(`Combined WebSocket: Processing drawing ${index + 1}/${drawings.length}:`, drawing);

            // Convert drawing data to Plotly shape format
            const shape = convertDrawingToShape(drawing);
            console.log(`Combined WebSocket: Converted to shape:`, shape);

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
            console.log('🎨 DRAWINGS: Created line shape:', {
                x0: shape.x0,
                y0: shape.y0,
                x1: shape.x1,
                y1: shape.y1,
                yref: shape.yref,
                line: shape.line
            });
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
            console.log('🎨 DRAWINGS: Created horizontal line shape:', {
                ...shape,
                yref: shape.yref
            });
        } else {
            console.warn(`Combined WebSocket: Unsupported drawing type: ${drawing.type}`);
            return null;
        }

        console.log('🎨 DRAWINGS: Final shape created:', shape);
        return shape;
    } catch (error) {
        console.error('Combined WebSocket: Error converting drawing to shape:', error, drawing);
        return null;
    }
}

function updateChartWithHistoricalData(dataPoints, symbol) {
    console.log('📈 Combined WebSocket: Processing historical data for chart update');
    console.log('📈 Combined WebSocket: Data points received:', dataPoints.length);

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

    dataPoints.forEach((point, pointIndex) => {
        console.log(`🔍 DEBUG: DataPoint ${pointIndex}: time=${point.time}, has indicators:`, !!point.indicators);
        if (point.indicators) {
            console.log(`🔍 DEBUG: DataPoint ${pointIndex} indicators keys:`, Object.keys(point.indicators));
            Object.keys(point.indicators).forEach(indicatorId => {
                console.log(`🔍 DEBUG: Processing indicator ${indicatorId} for dataPoint ${pointIndex}`);
                if (!indicatorsData[indicatorId]) {
                    console.log(`🔍 DEBUG: Creating new indicatorsData entry for ${indicatorId}`);
                    indicatorsData[indicatorId] = {
                        timestamps: [],
                        values: {}
                    };
                }

                indicatorsData[indicatorId].timestamps.push(new Date(point.time * 1000));

                // Store all indicator values for this point
                Object.keys(point.indicators[indicatorId]).forEach(key => {
                    console.log(`🔍 DEBUG: Processing indicator ${indicatorId} key ${key} with value:`, point.indicators[indicatorId][key]);
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
    const indicatorTypes = forcedIndicatorOrder.filter(indicatorId => combinedIndicators.includes(indicatorId) && indicatorsData[indicatorId]);

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
            console.log(`🔍 DEBUG: NaN filtering for indicator data:`);
            console.log(`  Original: ${values.length}, Filtered: ${filteredValues.length}`);
            console.log(`  NaN count: ${nanCount}, Infinite count: ${infiniteCount}, Non-numeric count: ${nonNumericCount}`);
        }

        return { timestamps: filteredTimestamps, values: filteredValues };
    }

    indicatorTypes.forEach((indicatorId, index) => {
        const indicatorData = indicatorsData[indicatorId];
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

    // Create layout using the same function as updateChartIndicatorsDisplay
    const layout = createLayoutForIndicators(indicatorTypes);

    // Override the title and axis settings for historical data
    layout.title = `${symbol} - ${combinedResolution.toUpperCase()}`;

    // Preserve user's saved X-axis range if it exists
    if (window.currentXAxisRange && window.currentXAxisRange.length === 2) {
        // Check if timestamps are already in milliseconds (values > 1e12 indicate milliseconds)
        let xMinMs = window.currentXAxisRange[0];
        let xMaxMs = window.currentXAxisRange[1];

        // If values are in seconds (reasonable for 2025), convert to milliseconds
        if (xMinMs < 2e9) { // Less than 2 billion (reasonable for seconds since 1970)
            xMinMs = xMinMs * 1000;
            xMaxMs = xMaxMs * 1000;
            /* console.log('🔍 DEBUG: Converted X-axis timestamps from seconds to milliseconds:', {
                originalMin: window.currentXAxisRange[0],
                originalMax: window.currentXAxisRange[1],
                convertedMin: xMinMs,
                convertedMax: xMaxMs
            }); */
        } else {
            /*  console.log('🔍 DEBUG: X-axis timestamps already in milliseconds:', {
                min: xMinMs,
                max: xMaxMs
            });
            */
        }

        const xMinDate = new Date(xMinMs);
        const xMaxDate = new Date(xMaxMs);
        layout.xaxis = {
            rangeslider: { visible: false },
            type: 'date',
            autorange: false,
            range: [xMinDate, xMaxDate]
        };
        // console.log('Combined WebSocket: Applied saved X-axis range:', window.currentXAxisRange);
        // console.log('🔍 DEBUG: X-axis range dates:', xMinDate.toISOString(), 'to', xMaxDate.toISOString());
    } else {
        layout.xaxis = {
            rangeslider: { visible: false },
            type: 'date',
            autorange: true
        };
        // console.log('Combined WebSocket: No saved X-axis range, using autorange');
    }

    // Preserve user's saved Y-axis range if it exists
    if (window.currentYAxisRange && window.currentYAxisRange.length === 2) {
        layout.yaxis = {
            title: `${symbol.replace('USDT', '/USDT')} Price`,
            autorange: false,
            range: window.currentYAxisRange
        };
        // console.log('Combined WebSocket: Applied saved Y-axis range:', window.currentYAxisRange);
        // console.log('🔍 DEBUG: Y-axis range values:', window.currentYAxisRange[0], 'to', window.currentYAxisRange[1]);
    } else {
        layout.yaxis = {
            title: `${symbol.replace('USDT', '/USDT')} Price`,
            autorange: true
        };
        // console.log('Combined WebSocket: No saved Y-axis range, using autorange');
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

    const chartElement = document.getElementById('chart');
    if (!chartElement) {
        // console.error('Combined WebSocket: Chart element not found');
        return;
    }

    // console.log('Combined WebSocket: About to update chart');
    // console.log('Combined WebSocket: Chart element found:', !!chartElement);
    // console.log('Combined WebSocket: Window.gd exists:', !!window.gd);
    // console.log('Combined WebSocket: All traces count:', allTraces.length);
    // console.log('Combined WebSocket: Price trace:', allTraces[0] ? 'exists' : 'missing');
    // console.log('Combined WebSocket: Indicator traces:', indicatorTraces.length);

    // DEBUG: Log final data ranges before chart update
    if (timestamps.length > 0) {
        // console.log('📊 FINAL DATA TO DISPLAY:');
        // console.log('  Data points:', timestamps.length);
        // console.log('  Time range (UTC):', timestamps[0].toISOString(), 'to', timestamps[timestamps.length - 1].toISOString());
        // console.log('  Time range (Local):', timestamps[0].toLocaleString(), 'to', timestamps[timestamps.length - 1].toLocaleString());
        // console.log('  Price range:', Math.min(...close), 'to', Math.max(...close));
    }

    // Compare with server range if available
    if (window.lastServerRange) {
        // console.log('🔄 COMPARING CLIENT VS SERVER RANGES:');
        // console.log('  Server range (UTC):', window.lastServerRange.fromDate, 'to', window.lastServerRange.toDate);
        // console.log('  Client data range (UTC):', timestamps[0].toISOString(), 'to', timestamps[timestamps.length - 1].toISOString());
        // console.log('  Server range (Local):', new Date(window.lastServerRange.fromTs * 1000).toLocaleString(), 'to', new Date(window.lastServerRange.toTs * 1000).toLocaleString());
        // console.log('  Client data range (Local):', timestamps[0].toLocaleString(), 'to', timestamps[timestamps.length - 1].toLocaleString());

        const serverStart = new Date(window.lastServerRange.fromTs * 1000);
        const serverEnd = new Date(window.lastServerRange.toTs * 1000);
        const clientStart = timestamps[0];
        const clientEnd = timestamps[timestamps.length - 1];

        const startDiff = Math.abs(clientStart.getTime() - serverStart.getTime()) / 1000;
        const endDiff = Math.abs(clientEnd.getTime() - serverEnd.getTime()) / 1000;

        // console.log('  Start time difference:', startDiff, 'seconds');
        // console.log('  End time difference:', endDiff, 'seconds');
    }

    // Log details about each trace
    allTraces.forEach((trace, index) => {
        const dataPoints = trace.x ? trace.x.length : 0;
        // console.log(`Combined WebSocket: Trace ${index} (${trace.name}): ${dataPoints} data points, type: ${trace.type}`);
        if (dataPoints === 0) {
            // console.warn(`Combined WebSocket: Trace ${trace.name} has no data points!`);
        }
    });

    // Filter out traces with no data
    const validTraces = allTraces.filter(trace => {
        const hasData = trace.x && trace.x.length > 0;
        if (!hasData) {
            // console.warn(`Combined WebSocket: Removing trace ${trace.name} - no data points`);
        }
        return hasData;
    });

    console.log(`📊 Combined WebSocket: Valid traces: ${validTraces.length}/${allTraces.length}`);

    // DEBUG: Detailed trace analysis
    console.log('🔍 DEBUG: Trace details before filtering:');
    allTraces.forEach((trace, index) => {
        const dataPoints = trace.x ? trace.x.length : 0;
        const hasNaN = trace.y ? trace.y.some(v => isNaN(v)) : false;
        console.log(`  Trace ${index} (${trace.name}): ${dataPoints} points, type: ${trace.type}, hasNaN: ${hasNaN}, yaxis: ${trace.yaxis}`);
    });

    console.log('🔍 DEBUG: Valid traces after filtering:');
    validTraces.forEach((trace, index) => {
        const dataPoints = trace.x ? trace.x.length : 0;
        const hasNaN = trace.y ? trace.y.some(v => isNaN(v)) : false;
        console.log(`  Valid Trace ${index} (${trace.name}): ${dataPoints} points, type: ${trace.type}, hasNaN: ${hasNaN}, yaxis: ${trace.yaxis}`);
    });

    // Check if chart already has data - if so, we need to merge with existing data
    let finalTraces = validTraces;
    if (window.gd && window.gd.data && window.gd.data.length > 0) {
        // console.log('Combined WebSocket: Chart already has data, merging with historical data');

        // Find existing price trace
        const existingPriceTrace = window.gd.data.find(trace => trace.type === 'candlestick');
        if (existingPriceTrace) {
            // console.log('Combined WebSocket: Found existing price trace with', existingPriceTrace.x ? existingPriceTrace.x.length : 0, 'points');

            // Merge historical data with existing data
            const existingTimestamps = existingPriceTrace.x || [];
            const historicalTimestamps = priceTrace.x || [];

            // Combine and sort all timestamps
            const allTimestamps = [...new Set([...existingTimestamps, ...historicalTimestamps])];
            allTimestamps.sort((a, b) => new Date(a) - new Date(b));

            // console.log('Combined WebSocket: Merging data - existing:', existingTimestamps.length, 'historical:', historicalTimestamps.length, 'combined:', allTimestamps.length);

            // Create merged price trace
            const mergedPriceTrace = {
                ...priceTrace,
                x: allTimestamps,
                open: new Array(allTimestamps.length),
                high: new Array(allTimestamps.length),
                low: new Array(allTimestamps.length),
                close: new Array(allTimestamps.length),
                volume: new Array(allTimestamps.length)
            };

            // Fill merged data
            allTimestamps.forEach((timestamp, index) => {
                const existingIndex = existingTimestamps.findIndex(t => t.getTime() === timestamp.getTime());
                const historicalIndex = historicalTimestamps.findIndex(t => t.getTime() === timestamp.getTime());

                if (existingIndex !== -1) {
                    // Use existing data
                    mergedPriceTrace.open[index] = existingPriceTrace.open[existingIndex];
                    mergedPriceTrace.high[index] = existingPriceTrace.high[existingIndex];
                    mergedPriceTrace.low[index] = existingPriceTrace.low[existingIndex];
                    mergedPriceTrace.close[index] = existingPriceTrace.close[existingIndex];
                    mergedPriceTrace.volume[index] = existingPriceTrace.volume[existingIndex];
                } else if (historicalIndex !== -1) {
                    // Use historical data
                    mergedPriceTrace.open[index] = priceTrace.open[historicalIndex];
                    mergedPriceTrace.high[index] = priceTrace.high[historicalIndex];
                    mergedPriceTrace.low[index] = priceTrace.low[historicalIndex];
                    mergedPriceTrace.close[index] = priceTrace.close[historicalIndex];
                    mergedPriceTrace.volume[index] = priceTrace.volume[historicalIndex];
                }
            });

            // Replace price trace in validTraces
            finalTraces = validTraces.map(trace =>
                trace.type === 'candlestick' ? mergedPriceTrace : trace
            );

            /* console.log('Combined WebSocket: Successfully merged historical data with existing chart data');
            console.log('🔍 DEBUG: Merged data verification:');
            console.log('  Merged timestamps range:', mergedPriceTrace.x[0], 'to', mergedPriceTrace.x[mergedPriceTrace.x.length - 1]);
            console.log('  Merged data points:', mergedPriceTrace.x.length);
            console.log('  Sample merged data - First:', {
                time: mergedPriceTrace.x[0],
                open: mergedPriceTrace.open[0],
                close: mergedPriceTrace.close[0]
            });
            // console.log('  Sample merged data - Last:', {
                time: mergedPriceTrace.x[mergedPriceTrace.x.length - 1],
                open: mergedPriceTrace.open[mergedPriceTrace.x.length - 1],
                close: mergedPriceTrace.close[mergedPriceTrace.x.length - 1]
            });
            */
        } else {
            // console.log('Combined WebSocket: No existing price trace found, using historical data only');
        }
    } else {
        // console.log('Combined WebSocket: No existing chart data found, using historical data only');
    }

    // Always update existing chart - we should never need to create a new one
    // console.log('Combined WebSocket: Updating existing chart with Plotly.react');
    // console.log('[CHART_UPDATE] combinedData.js historical data - updating chart at', new Date().toISOString());
    // console.log('[CHART_UPDATE] combinedData.js - finalTraces count:', finalTraces.length);

    // DEBUG: Log chart update details
    // console.log('🔍 DEBUG: Plotly.react call details:');
    // console.log('  Chart element exists:', !!chartElement);
    // console.log('  Final traces count:', finalTraces.length);
    // console.log('  Layout object keys:', Object.keys(layout));
    // console.log('  Layout xaxis:', layout.xaxis);
    // console.log('  Layout yaxis:', layout.yaxis);

    // Preserve existing shapes when updating chart with historical data
    if (window.gd && window.gd.layout && window.gd.layout.shapes) {
        layout.shapes = window.gd.layout.shapes;
        console.log('🎨 DRAWINGS: Preserving', window.gd.layout.shapes.length, 'existing shapes during historical data update');
    }

    // console.log('🔍 DEBUG: About to call Plotly.react...');
    // console.log('  Chart element type:', chartElement?.tagName);
    // console.log('  Chart element id:', chartElement?.id);
    // console.log('  Final traces to update:', finalTraces.length);
    // console.log('  Layout xaxis range:', layout.xaxis.range);

    try {
        // Honor user's zoom/pan settings - do not force autorange
        console.log('🔄 Using Plotly.react with user\'s zoom/pan settings preserved...');

        // Use the original layout which preserves user's axis ranges and existing shapes
        Plotly.react(chartElement, finalTraces, layout);
        console.log('✅ Plotly.react completed successfully with user settings preserved');
        console.log('[CHART_UPDATE] combinedData.js historical data - chart update completed at', new Date().toISOString());
        console.log('📊 User zoom/pan settings maintained - no forced autorange');

        console.log('📊 Chart should now display all merged historical data');

        // Set up WebSocket message handler after subplots are initialized
        console.log('🎨 DRAWINGS: Chart layout with subplots initialized, setting up WebSocket message handler');
        setupWebSocketMessageHandler();

        // DEBUG: Verify chart state after update
        setTimeout(() => {
            if (window.gd && window.gd.data) {
                // console.log('🔍 DEBUG: Chart state after Plotly.react:');
                // console.log('  Chart has data:', window.gd.data.length > 0);
                // console.log('  Data traces count:', window.gd.data.length);
                // console.log('  First trace data points:', window.gd.data[0] ? window.gd.data[0].x.length : 0);
                // console.log('  Layout xaxis range:', window.gd.layout.xaxis.range);
                // console.log('  Layout yaxis range:', window.gd.layout.yaxis.range);

                // Check if the data actually contains the historical data
                if (window.gd.data[0] && window.gd.data[0].x && window.gd.data[0].x.length > 0) {
                    const firstDataPoint = window.gd.data[0].x[0];
                    const lastDataPoint = window.gd.data[0].x[window.gd.data[0].x.length - 1];
                    // console.log('  Chart data range:', firstDataPoint, 'to', lastDataPoint);
                }
            } else {
                // console.error('🚨 ERROR: Chart state invalid after Plotly.react');
                // console.error('  window.gd exists:', !!window.gd);
                // console.error('  window.gd.data exists:', !!(window.gd && window.gd.data));
            }
        }, 100);
    } catch (error) {
        // console.error('🚨 ERROR: Plotly.react failed:', error);
        // console.error('  Error details:', error.message);
        // console.error('  Error stack:', error.stack);
    }

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
    setTimeout(() => {
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
    }, 100);

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
    // updateOrAddRealtimePriceLine(gd, price, timestamp.getTime(), timestamp.getTime() + (getTimeframeSecondsJS(combinedResolution) * 1000));

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
        const updatedLayout = createLayoutForIndicators([...new Set([...getCurrentActiveIndicators(), ...newIndicatorIds])]);

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
            const stochVariant = combinedIndicators.find(id => id.startsWith('stochrsi'));
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
    const layout = createLayoutForIndicators(activeIndicatorIds);

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

function createLayoutForIndicators(activeIndicatorIds) {
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
            showticklabels: false // Hide x-axis labels (can be enabled later by setting to true)
        },
        yaxis: {
            title: `${combinedSymbol.replace('USDT', '/USDT')} Price`,
            autorange: !window.currentYAxisRange,
            range: window.currentYAxisRange ? window.currentYAxisRange : undefined,
            showticklabels: true,
            showgrid: true,
            side: 'left'
        },
        showlegend: false,
        margin: { l: 40, r: 10, b: 20, t: 30 }
    };

    if (activeIndicatorIds.length > 0) {
        // Optimized space usage with 3:1 ratio - ensure full height utilization
        // Calculate from bottom up to eliminate any remaining blank space
        const totalUnits = 1 + activeIndicatorIds.length; // Price gets 2 units, each indicator gets 1 unit
        const unitHeight = 1.0 / totalUnits; // Each unit's height

        const priceChartHeight = 1 * unitHeight; // Price chart gets 2 units
        const labelGap = isMobileDevice() ? 0.04 : 0.04; // Increased gap: 6% mobile, 12% desktop
        const availableForIndicators = 1.0 - priceChartHeight - labelGap;
        const gapBetweenIndicators = 0.02; // 2% gap between indicators
        const totalIndicatorSpace = availableForIndicators - (activeIndicatorIds.length - 1) * gapBetweenIndicators;
        const indicatorHeight = totalIndicatorSpace / activeIndicatorIds.length; // Redistribute remaining space

        const priceChartDomain = [1.0 - priceChartHeight, 1.0]; // Price chart at top
        const indicatorsStartAt = 1.0 - priceChartHeight - labelGap; // Indicators start below labels

        // Create grid with manual row heights - must match domain calculations exactly
        let rowHeights = [priceChartHeight]; // Price chart height (calculated, not hardcoded)
        for (let i = 0; i < activeIndicatorIds.length; i++) {
            rowHeights.push(indicatorHeight);
            if (i < activeIndicatorIds.length - 1) rowHeights.push(gapBetweenIndicators);
        }

        baseLayout.grid = {
            rows: rowHeights.length,
            columns: 1,
            pattern: 'independent',
            roworder: 'top to bottom',
            rowheights: rowHeights,
            xgap: 0,
            ygap: 0
        };

        // console.log(`DEBUG: Unit-based calculation - totalUnits: ${totalUnits}, unitHeight: ${unitHeight.toFixed(3)}`);
        // console.log(`DEBUG: Price chart height: ${priceChartHeight.toFixed(3)}, domain: [${priceChartDomain[0].toFixed(3)}, ${priceChartDomain[1].toFixed(3)}]`);
        // console.log(`DEBUG: Indicator height: ${indicatorHeight.toFixed(3)}, total indicators: ${activeIndicatorIds.length}`);
        // console.log(`DEBUG: Grid row heights: [${rowHeights.map(h => h.toFixed(3)).join(', ')}]`);

        // Set price chart domain
        baseLayout.yaxis.domain = priceChartDomain;
        // console.log(`DEBUG: Price chart domain set to [${priceChartDomain[0].toFixed(3)}, ${priceChartDomain[1].toFixed(3)}]`);

        // Assign indicator domains from bottom up within the remaining space
        activeIndicatorIds.forEach((indicatorId, index) => {
            const yAxisName = `yaxis${index + 2}`;
            const indicatorIndex = activeIndicatorIds.length - 1 - index; // Reverse order for bottom-up stacking

            // Optimized domain calculation for indicators - ensure last indicator reaches exactly 0.0
            const isLastIndicator = indicatorIndex === activeIndicatorIds.length - 1;

            // Declare variables outside if/else blocks to avoid scoping issues
            let domainStart, domainEnd;
            const higherStartPadding = 0.2 * indicatorHeight;

            // Calculate domain with gaps between indicators
            domainStart = (activeIndicatorIds.length - 1 - indicatorIndex) * (indicatorHeight + gapBetweenIndicators);
            domainEnd = domainStart + indicatorHeight;
            // Apply higher start padding for first indicator
            if (indicatorIndex === 0) {
                domainStart += higherStartPadding;
            }

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
                domain: [domainStart, domainEnd] // Explicitly set domain based on grid rowheights
            };
            // console.log(`DEBUG: ${indicatorId} domain set to [${domainStart.toFixed(3)}, ${domainEnd.toFixed(3)}]`);
        });

        // Verify total height coverage
        const totalCoverage = baseLayout.yaxis.domain[1] - baseLayout.yaxis.domain[0] +
            activeIndicatorIds.reduce((sum, _, i) => sum + (baseLayout[`yaxis${i + 2}`].domain[1] - baseLayout[`yaxis${i + 2}`].domain[0]), 0);
        // console.log(`DEBUG: Total domain coverage: ${totalCoverage.toFixed(3)} (should be 1.0)`);
    } else {
        baseLayout.yaxis.domain = [0, 1];
        // console.log(`DEBUG: No indicators, price chart domain set to [0, 1]`);
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
