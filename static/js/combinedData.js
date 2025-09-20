// Combined data WebSocket handler for historical OHLC + indicators + live data

let combinedWebSocket = null;
let combinedSymbol = '';
let combinedIndicators = [];
let combinedResolution = '1h';
let combinedFromTs = null;
let combinedToTs = null;

// Initialize timestamps with default values (30 days ago to now)
function initializeDefaultTimestamps() {
    if (combinedFromTs === null || combinedToTs === null) {
        const currentTime = new Date().getTime();
        combinedFromTs = Math.floor((currentTime - 30 * 86400 * 1000) / 1000); // 30 days ago in seconds
        combinedToTs = Math.floor(currentTime / 1000); // Now in seconds
        console.log('🔧 Initialized default timestamps:', {
            combinedFromTs: combinedFromTs,
            combinedToTs: combinedToTs,
            fromDate: new Date(combinedFromTs * 1000).toISOString(),
            toDate: new Date(combinedToTs * 1000).toISOString()
        });
    }
}

// Message queue and synchronization
let messageQueue = [];
let isProcessingMessage = false;
let chartUpdateLock = false;
let chartUpdateDebounceTimer = null;
const CHART_UPDATE_DEBOUNCE_DELAY = 100; // ms

// WebSocket connection management
let websocketSetupDebounceTimer = null;
const WEBSOCKET_SETUP_DEBOUNCE_DELAY = 500; // ms
let isWebSocketConnecting = false;
let lastProcessedTimestampRange = null;
let processedMessageIds = new Set();
let websocketConnectionId = 0;

// WebSocket lifecycle logging
const websocketLogs = [];
const MAX_WEBSOCKET_LOGS = 50;

function logWebSocketEvent(event, details = {}) {
    const logEntry = {
        timestamp: new Date().toISOString(),
        event,
        connectionId: websocketConnectionId,
        details
    };
    websocketLogs.push(logEntry);
    if (websocketLogs.length > MAX_WEBSOCKET_LOGS) {
        websocketLogs.shift();
    }
    console.log(`🔌 WS[${websocketConnectionId}]: ${event}`, details);
}

// Historical data processing - direct handling without accumulation

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
            x: 1,         // Position more inside the chart area (95% from left)
            y: price,        // Y position is the price itself
            showarrow: false,
            xanchor: 'right', // Anchor the text from its right side
            yanchor: 'middle',// Vertically center the text at the y-coordinate (price)
            font: {
                family: 'Arial, sans-serif',
                size: 24, // Increased font size for better visibility
                color: 'black' // Solid black for better contrast
            },
            bgcolor: 'white', // Solid white background for SVG
            bordercolor: 'black', // Black border for visibility
            borderwidth: 2,  // Thicker border
            borderpad: 6     // More padding
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
       console.log('💰 LIVE PRICE: Added annotation:', annotationDefinition);
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
    } else {
        // For live price updates, use Plotly.update to refresh shapes/annotations without triggering relayout events
        // console.log('[PriceLine] updateOrAddRealtimePriceLine - Calling Plotly.update to refresh shapes/annotations without relayout');
        Plotly.update(gd, {}, { shapes: gd.layout.shapes, annotations: gd.layout.annotations });
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

// Message queue processing functions
function enqueueMessage(message) {
    // Generate message ID for deduplication with better uniqueness
    let messageId;

    if (message.type === 'live_price') {
        // For live_price messages, include price and timestamp for uniqueness
        const price = message.price || (message.data && message.data.price) || 'unknown';
        const timestamp = message.timestamp || (message.data && message.data.timestamp) || Date.now();
        messageId = `${message.type}_${message.symbol || 'unknown'}_${price}_${timestamp}`;
    } else if (message.type === 'live') {
        // For live data messages, include timestamp and price
        const timestamp = message.data && message.data.time ? message.data.time : Date.now();
        const price = message.data && message.data.ohlc ? message.data.ohlc.close : 'unknown';
        messageId = `${message.type}_${message.symbol || 'unknown'}_${timestamp}_${price}`;
    } else {
        // For other message types, use the original method
        messageId = `${message.type}_${message.symbol || 'unknown'}_${JSON.stringify(message.data || {}).slice(0, 100)}`;
    }

    // Check for duplicate messages
    if (processedMessageIds.has(messageId)) {
        console.log(`🚫 Duplicate message detected and skipped: ${message.type} (${messageId})`);
        return;
    }

    // Add timestamp range validation for historical data with safe data handling
    if (message.type === 'historical' && lastProcessedTimestampRange) {
        if (!message.data || !Array.isArray(message.data) || message.data.length === 0) {
            console.warn('⚠️ Invalid or empty historical data in duplicate range check - skipping');
        } else {
            // Find first valid timestamp
            let messageFromTs = null;
            for (const point of message.data) {
                if (point && point.time && !isNaN(point.time) && point.time > 0) {
                    messageFromTs = point.time;
                    break;
                }
            }

            // Find last valid timestamp
            let messageToTs = null;
            for (let i = message.data.length - 1; i >= 0; i--) {
                const point = message.data[i];
                if (point && point.time && !isNaN(point.time) && point.time > 0) {
                    messageToTs = point.time;
                    break;
                }
            }

            if (messageFromTs !== null && messageToTs !== null) {
                const isDuplicateRange = (
                    Math.abs(messageFromTs - lastProcessedTimestampRange.fromTs) < 60 && // Within 1 minute
                    Math.abs(messageToTs - lastProcessedTimestampRange.toTs) < 60
                );

                if (isDuplicateRange) {
                    console.log(`🚫 Duplicate timestamp range detected and skipped: safe timestamp logging`);
                    return;
                }

                // Update last processed range
                lastProcessedTimestampRange = { fromTs: messageFromTs, toTs: messageToTs };
            } else {
                console.warn('⚠️ No valid timestamps found in historical data for range validation');
            }
        }
    }

    // Mark message as processed
    processedMessageIds.add(messageId);

    // Keep only last 1000 processed message IDs to prevent memory leaks
    if (processedMessageIds.size > 1000) {
        const idsArray = Array.from(processedMessageIds);
        processedMessageIds.clear();
        idsArray.slice(-500).forEach(id => processedMessageIds.add(id)); // Keep last 500
    }

    messageQueue.push(message);
    console.log(`📨 Message queued. Queue length: ${messageQueue.length}, Type: ${message.type}`);
    processMessageQueue();
}

function processMessageQueue() {
    if (isProcessingMessage || messageQueue.length === 0) {
        return;
    }

    isProcessingMessage = true;
    const message = messageQueue.shift();

    console.log(`🔄 Processing message: ${message.type} (${messageQueue.length} remaining in queue)`);

    try {
        // Validate message type exists
        if (!message || typeof message !== 'object') {
            console.warn('⚠️ Invalid message format:', message);
            isProcessingMessage = false;
            return;
        }

        if (!message.type) {
            console.warn('⚠️ Message missing type:', message);
            isProcessingMessage = false;
            return;
        }

        // Log message processing with safe timestamp handling
        let safeLogMessage = 'Processing message';
        if (message.type === 'historical' && !lastProcessedTimestampRange && message.data && Array.isArray(message.data) && message.data.length > 0) {
            safeLogMessage += ` (${message.data.length} historical points)`;
        } else if (message.type === 'historical' && lastProcessedTimestampRange && message.data && Array.isArray(message.data) && message.data.length > 0) {
            // Safe timestamp logging
            const msgFromTs = message.data[0]?.time;
            const msgToTs = message.data[message.data.length - 1]?.time;
            if (typeof msgFromTs === 'number' && !isNaN(msgFromTs) && typeof msgToTs === 'number' && !isNaN(msgToTs)) {
                safeLogMessage += ` (${new Date(msgFromTs * 1000).toISOString()} to ${new Date(msgToTs * 1000).toISOString()})`;
            } else {
                safeLogMessage += ` (${message.data.length} points, timestamp conversion skipped)`;
            }
        }
        console.log(`🔄 ${safeLogMessage}`);

        // Process message based on type
        switch (message.type) {
            case 'historical':
                handleHistoricalData(message);
                break;
            case 'live':
                handleLiveData(message);
                break;
            case 'live_price':
                handleLivePriceUpdate(message);
                break;
            case 'drawings':
                handleDrawingsData(message);
                break;
            case 'buy_signals':
                handleBuySignals(message);
                break;
            case 'history_update':
                handleHistoryUpdate(message);
                break;
            default:
                console.warn('⚠️ Unknown message type:', message.type);
        }

        console.log('✅ Message processing completed for type:', message.type);
    } catch (e) {
        console.error('❌ Combined WebSocket: Error processing queued message:', e.message);
        console.error('❌ Stack trace:', e.stack);
        console.error('❌ Raw message data:', JSON.stringify(message, null, 2));
    } finally {
        isProcessingMessage = false;
        // Process next message if available
        if (messageQueue.length > 0) {
            setTimeout(processMessageQueue, 10); // Small delay to prevent blocking
        }
    }
}

// Chart update lock functions
function acquireChartUpdateLock() {
    if (chartUpdateLock) {
        console.warn('🔒 Chart update lock already held, waiting...');
        return false;
    }
    chartUpdateLock = true;
    console.log('🔒 Chart update lock acquired');
    return true;
}

function releaseChartUpdateLock() {
    chartUpdateLock = false;
    console.log('🔓 Chart update lock released');
}

function isChartUpdateLocked() {
    return chartUpdateLock;
}

// Debounced chart update function
function debouncedChartUpdate(updateFunction, ...args) {
    clearTimeout(chartUpdateDebounceTimer);
    chartUpdateDebounceTimer = setTimeout(() => {
        if (!acquireChartUpdateLock()) {
            console.warn('⚠️ Skipping debounced chart update - lock held');
            return;
        }

        try {
            updateFunction(...args);
        } finally {
            releaseChartUpdateLock();
        }
    }, CHART_UPDATE_DEBOUNCE_DELAY);
}

function handleRealtimeKlineForCombined(dataPoint) {
    console.log('🔴 Combined WebSocket: handleRealtimeKlineForCombined called with data:', dataPoint);

    if (!dataPoint) {
        console.warn('🔴 Combined WebSocket: No data point provided to handleRealtimeKlineForCombined');
        return;
    }

    // Check if currently dragging a shape - skip live price updates during dragging
    if (window.isDraggingShape) {
        console.log('🔴 Combined WebSocket: Skipping live data update during shape dragging');
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

    // Get candle timing information with validation
    let candleStartTimeMs;
    if (dataPoint.time && !isNaN(dataPoint.time) && dataPoint.time > 0) {
        candleStartTimeMs = dataPoint.time * 1000;
        // Validate the result
        if (!isFinite(candleStartTimeMs)) {
            console.warn('⚠️ Invalid candle start time calculated:', candleStartTimeMs);
            return;
        }
    } else {
        console.warn('⚠️ Invalid data point time for candle timing:', dataPoint.time);
        return;
    }

    const timeframeSeconds = getTimeframeSecondsJS(combinedResolution);
    const candleEndTimeMs = candleStartTimeMs + (timeframeSeconds * 1000);

    // Validate candle end time
    if (!isFinite(candleEndTimeMs)) {
        console.warn('⚠️ Invalid candle end time calculated:', candleEndTimeMs);
        return;
    }

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
    // Initialize default timestamps if not provided
    if (fromTs === null || toTs === null) {
        initializeDefaultTimestamps();
        // Use the initialized timestamps if none were provided
        if (fromTs === null) fromTs = combinedFromTs;
        if (toTs === null) toTs = combinedToTs;
    }

    // Increment connection ID for logging
    websocketConnectionId++;

    logWebSocketEvent('setup_called', {
        symbol,
        indicatorsCount: indicators.length,
        resolution,
        fromTs,
        toTs,
        currentState: combinedWebSocket ? combinedWebSocket.readyState : 'none'
    });

    // Check if this is a duplicate call (same parameters)
    const isDuplicateCall = (
        combinedSymbol === symbol &&
        combinedResolution === resolution &&
        JSON.stringify(combinedIndicators) === JSON.stringify(indicators) &&
        combinedFromTs === fromTs &&
        combinedToTs === toTs
    );

    if (isDuplicateCall && combinedWebSocket && combinedWebSocket.readyState === WebSocket.OPEN) {
        logWebSocketEvent('duplicate_call_skipped', {
            reason: 'Same parameters, WebSocket already open'
        });
        return;
    }

    // Clear any pending debounced calls
    if (websocketSetupDebounceTimer) {
        clearTimeout(websocketSetupDebounceTimer);
        websocketSetupDebounceTimer = null;
    }

    // Debounce the WebSocket setup
    websocketSetupDebounceTimer = setTimeout(() => {
        // Check if we're already connecting
        if (isWebSocketConnecting) {
            logWebSocketEvent('connection_in_progress', {
                reason: 'Another connection attempt in progress'
            });
            return;
        }

        isWebSocketConnecting = true;

        try {
            _setupCombinedWebSocketInternal(symbol, indicators, resolution, fromTs, toTs);
        } finally {
            isWebSocketConnecting = false;
        }
    }, WEBSOCKET_SETUP_DEBOUNCE_DELAY);
}

function _setupCombinedWebSocketInternal(symbol, indicators = [], resolution = '1h', fromTs = null, toTs = null) {
    logWebSocketEvent('internal_setup_started', {
        symbol,
        indicatorsCount: indicators.length,
        resolution
    });

    // Close existing connection if symbol changed or connection is in error state
    if (combinedWebSocket && (combinedSymbol !== symbol || combinedWebSocket.readyState === WebSocket.CLOSED || combinedWebSocket.readyState === WebSocket.CLOSING)) {
        closeCombinedWebSocket("Switching to new symbol or cleaning up failed connection");
    }

    // Store old resolution for change detection
    const oldResolution = combinedResolution;

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

    // Reset processed message tracking for new connection
    processedMessageIds.clear();
    lastProcessedTimestampRange = null;

    logWebSocketEvent('parameters_updated', {
        symbol: combinedSymbol,
        indicatorsCount: combinedIndicators.length,
        resolution: combinedResolution,
        fromTs: combinedFromTs,
        toTs: combinedToTs,
        isTimeRangeUpdate
    });

    // If WebSocket is already open and parameters haven't changed significantly, just send config update
    if (combinedWebSocket && combinedWebSocket.readyState === WebSocket.OPEN) {
        logWebSocketEvent('config_update_only', {
            reason: 'WebSocket open, sending config update',
            isTimeRangeUpdate
        });
        sendCombinedConfig(oldResolution);
        return;
    }

    // If WebSocket is connecting, wait for it to open
    if (combinedWebSocket && combinedWebSocket.readyState === WebSocket.CONNECTING) {
        logWebSocketEvent('waiting_for_connection', {
            reason: 'WebSocket is connecting, will send config when open'
        });
        // The onopen handler will send the config
        return;
    }

    // If WebSocket is in error state, close it first
    if (combinedWebSocket && combinedWebSocket.readyState === WebSocket.CLOSING) {
        logWebSocketEvent('closing_existing_connection', {
            reason: 'WebSocket is closing, waiting to create new connection'
        });
        // Wait a bit for the close to complete
        setTimeout(() => {
            _setupCombinedWebSocketInternal(symbol, indicators, resolution, fromTs, toTs);
        }, 100);
        return;
    }

    // Close any existing connection before creating new one
    if (combinedWebSocket) {
        closeCombinedWebSocket("Creating new connection for updated parameters");
    }

    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsHost = window.location.host;
    // Always use the current URL path symbol for WebSocket connection
    const currentUrlSymbol = window.location.pathname.substring(1).toUpperCase() || symbol;
    const streamUrl = `${wsProtocol}//${wsHost}/data/${currentUrlSymbol}`;

    logWebSocketEvent('creating_connection', {
        streamUrl,
        currentUrlSymbol,
        requestedSymbol: symbol
    });

    combinedWebSocket = new WebSocket(streamUrl);

    combinedWebSocket.onopen = () => {
        logWebSocketEvent('connection_opened', {
            streamUrl,
            symbol: combinedSymbol
        });

        // CRITICAL FIX: Set up message handler IMMEDIATELY after connection opens
        setupWebSocketMessageHandler();

        // Send initial configuration
        sendCombinedConfig(oldResolution);
    };

    combinedWebSocket.onerror = (error) => {
        logWebSocketEvent('connection_error', {
            error: error.message || 'Unknown error',
            symbol: combinedSymbol
        });
    };

    combinedWebSocket.onclose = (event) => {
        logWebSocketEvent('connection_closed', {
            code: event.code,
            reason: event.reason,
            symbol: combinedSymbol,
            wasClean: event.wasClean
        });

        // Attempt to reconnect if not a clean close and symbol hasn't changed
        if (event.code !== 1000 && window.symbolSelect && window.symbolSelect.value === symbol) {
            logWebSocketEvent('scheduling_reconnect', {
                delay: 5000,
                symbol
            });

            setTimeout(() => {
                if (window.symbolSelect && window.symbolSelect.value === symbol) {
                    setupCombinedWebSocket(symbol, indicators, resolution, fromTs, toTs);
                }
            }, 5000);
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

            // Enqueue message for sequential processing
            enqueueMessage(message);
        } catch (e) {
            console.error('❌ Combined WebSocket: Error parsing message:', e.message);
            console.error('❌ Raw message data:', event.data.substring(0, 200));
        }
    };

    console.log('✅ Combined WebSocket: Message handler successfully set up and attached to WebSocket');
    console.log('🎨 DRAWINGS: WebSocket message handler set up after subplots initialization');
}

function sendCombinedConfig(oldResolution = null) {
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
        to_ts: combinedToTs,      // Now ISO timestamp string
        old_resolution: oldResolution  // Include old resolution for change detection
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

function validateIndicatorData(data, indicatorName) {
    /**
     * Validates indicator data for null values.
     * - Null values are allowed during indicator warmup periods (earlier timestamps)
     * - No null values allowed in the user's requested time range (combinedFromTs to combinedToTs)
     * Returns true if validation passes, false only for data issues in requested time range.
     */
    if (!data || !Array.isArray(data)) {
        console.error(`❌ VALIDATION FAILED: ${indicatorName} - Invalid data format`);
        return false;
    }

    if (!combinedFromTs || !combinedToTs) {
        console.warn(`⚠️ VALIDATION WARNING: ${indicatorName} - No time range defined, allowing any data`);
        return true;
    }

    // Validate that time range values are valid (numbers, Date objects, or ISO strings)
    const fromTsValid = isValidTimestamp(combinedFromTs);
    const toTsValid = isValidTimestamp(combinedToTs);

    // Helper function to validate timestamps in any supported format
    function isValidTimestamp(ts) {
        if (ts === null || ts === undefined) return false;
        if (typeof ts === 'string') {
            // Check if it's a valid ISO string
            try {
                const date = new Date(ts);
                return !isNaN(date.getTime()) && date.getTime() > 0;
            } catch(e) {
                return false;
            }
        }
        if (typeof ts === 'number') {
            return !isNaN(ts) && ts > 0;
        }
        if (ts instanceof Date) {
            return !isNaN(ts.getTime()) && ts.getTime() > 0;
        }
        return false;
    }

    let lookbackNulls = 0;
    let lookbackPoints = 0;
    let userRangeNulls = 0;
    let userRangePoints = 0;

    // Check each data point for null values in indicator fields
    // Count nulls SEPARATELY for user-requested range vs lookback period
    data.forEach((point, index) => {
        if (point.indicators) {
            // Determine if this point is within user's requested time range
            const isInUserRange = fromTsValid && toTsValid && combinedFromTs <= point.time && point.time <= combinedToTs;

            // Determine if this point is outside user range (before or after)
            const isBeforeUserRange = point.time < combinedFromTs;
            const isAfterUserRange = point.time > combinedToTs;
            const isInLookbackRange = !isInUserRange && (isBeforeUserRange || isAfterUserRange);

            Object.keys(point.indicators).forEach(indicatorId => {
                const indicatorData = point.indicators[indicatorId];
                if (indicatorData) {
                    Object.keys(indicatorData).forEach(key => {
                        const value = indicatorData[key];
                        const isNull = value === null || value === undefined;

                        if (isNull) {
                            if (isInUserRange) {
                                userRangeNulls++;
                            } else if (isInLookbackRange) {
                                lookbackNulls++;
                            }
                        }

                        if (isInUserRange) {
                            userRangePoints++;
                        } else if (isInLookbackRange) {
                            lookbackPoints++;
                        }
                    });
                }
            });
        }
    });

    // LOGGING: Show data range breakdown with safe date formatting
    console.log(`📊 VALIDATION ANALYSIS: ${indicatorName}`);
    console.log(`  Total data points: ${data.length}`);

    if (!fromTsValid || !toTsValid) {
        console.warn(`⚠️ VALIDATION WARNING: ${indicatorName} - Invalid time range values (fromTs: ${combinedFromTs}, toTs: ${combinedToTs}), using fallback range determination`);
    }

    let lookbackDateStr = 'invalid';
    if (fromTsValid) {
        try {
            lookbackDateStr = new Date((combinedFromTs - 86400) * 1000).toISOString(); // 1 day before
        } catch(e) {
            lookbackDateStr = 'date_conversion_error';
        }
    }
    console.log(`  Lookback period (${lookbackDateStr} before): ${lookbackPoints} points, ${lookbackNulls} nulls ${(lookbackPoints > 0 ? (lookbackNulls / lookbackPoints * 100).toFixed(1) : 0)}%`);

    let userRangeStartStr = 'invalid';
    let userRangeEndStr = 'invalid';
    if (fromTsValid) {
        try {
            userRangeStartStr = new Date(combinedFromTs * 1000).toISOString();
        } catch(e) {
            userRangeStartStr = 'date_conversion_error';
        }
    }
    if (toTsValid) {
        try {
            userRangeEndStr = new Date(combinedToTs * 1000).toISOString();
        } catch(e) {
            userRangeEndStr = 'date_conversion_error';
        }
    }
    console.log(`  User requested range (${userRangeStartStr} to ${userRangeEndStr}): ${userRangePoints} points, ${userRangeNulls} nulls ${(userRangePoints > 0 ? (userRangeNulls / userRangePoints * 100).toFixed(1) : 0)}%`);

    // CRITICAL FIX: Accept nulls from indicator warmup periods at the start of data series
    // Only reject if there are nulls in the middle of the completed data (real gaps)
    if (userRangeNulls > 0) {
        // Find the pattern of nulls in user range
        // Look for consecutive nulls early in the series (warmup period)
        // vs isolated nulls later in the series (actual data gaps)

        let firstValidPointIndex = -1;
        let lastNullPointIndex = -1;
        let totalPointsInRange = 0;

        data.forEach((point, index) => {
            const isInUserRange = fromTsValid && toTsValid && point.time >= combinedFromTs && point.time <= combinedToTs;

            if (!isInUserRange) return; // Skip points outside user range

            totalPointsInRange++;
            let hasValidIndicators = false;

            if (point.indicators) {
                for (const indicatorId in point.indicators) {
                    for (const key in point.indicators[indicatorId]) {
                        const value = point.indicators[indicatorId][key];
                        if (value !== null && value !== undefined && !isNaN(value)) {
                            hasValidIndicators = true;
                            break;
                        }
                    }
                    if (hasValidIndicators) break;
                }
            }

            if (hasValidIndicators && firstValidPointIndex === -1) {
                firstValidPointIndex = index;
            }

            if (!hasValidIndicators) {
                lastNullPointIndex = index;
            }
        });

        // Check if nulls are clustered at the beginning (warmup periods)
        // vs nulls appearing later in the series (actual data gaps)
        const nullsAreWarmupPeriod = (firstValidPointIndex > 0 && (lastNullPointIndex < firstValidPointIndex));

        // Calculate nulls before first valid value vs nulls after first valid value
        let nullsInWarmupPeriod = 0;
        let nullsAfterWarmupPeriod = 0;
        let pointsProcessed = 0;

        data.forEach((point, index) => {
            const isInUserRange = fromTsValid && toTsValid && point.time >= combinedFromTs && point.time <= combinedToTs;

            if (!isInUserRange) return;

            pointsProcessed++;
            let hasValidIndicators = false;

            if (point.indicators) {
                for (const indicatorId in point.indicators) {
                    for (const key in point.indicators[indicatorId]) {
                        const value = point.indicators[indicatorId][key];
                        if (value !== null && value !== undefined && !isNaN(value)) {
                            hasValidIndicators = true;
                            break;
                        }
                    }
                    if (hasValidIndicators) break;
                }
            }

            // Count nulls:
            // - Before first valid point: expected warmup period nulls
            // - After first valid point: unexpected data gaps
            if (!hasValidIndicators) {
                if (pointsProcessed <= (firstValidPointIndex - point.index + 1) || firstValidPointIndex === -1) {
                    nullsInWarmupPeriod++;
                } else {
                    nullsAfterWarmupPeriod++;
                }
            }
        });

        // Only reject if there are nulls AFTER the warmup period (real data gaps)
        if (nullsAfterWarmupPeriod > 0) {
            const rangeStr = fromTsValid && toTsValid ? `(${userRangeStartStr} to ${userRangeEndStr})` : '(invalid time range)';
            console.error(`❌ VALIDATION FAILED: ${indicatorName} - Found ${nullsAfterWarmupPeriod} null values in COMPLETED data (after warmup period) within requested time range ${rangeStr}. This indicates data gaps that are not acceptable.`);
            return false;
        }

        // Accept nulls if they're concentrated in warmup period (normal behavior)
        console.log(`✅ ${indicatorName} - Accepted ${nullsInWarmupPeriod} warmup-period nulls, ${nullsAfterWarmupPeriod} unexpected nulls. Indicators are properly aligned.`);
        console.log(`   First valid point: index ${firstValidPointIndex}/${totalPointsInRange}, Last null point: index ${lastNullPointIndex}/${totalPointsInRange}`);
    }

    // If time range is completely corrupted, we have no way to know what's the "last bar"
    // Return false to reject this data and wait for a proper time range
    if (!fromTsValid || !toTsValid) {
        console.error(`❌ VALIDATION FAILED: ${indicatorName} - Time range is completely corrupted (fromTs: ${combinedFromTs}, toTs: ${combinedToTs}). Cannot determine user range.`);
        return false;
    }

    // WARNING: Log lookback (warmup) nulls (this is expected and acceptable)
    if (lookbackNulls > 0) {
        console.log(`✅ VALIDATION PASSED: ${indicatorName} - ${lookbackNulls} null values in lookback period (expected), 0 null values in requested time range (${userRangePoints} valid data points)`);
    } else {
        console.log(`✅ VALIDATION PASSED: ${indicatorName} - All ${userRangePoints} data points in requested range are valid`);
    }

    return true;
}

function handleHistoricalData(message) {
    console.log(`📊 Combined WebSocket: Received historical data for ${message.symbol}, ${message.data.length} points`);

    if (!message.data || !Array.isArray(message.data) || message.data.length === 0) {
        console.warn('Combined WebSocket: Invalid or empty historical data');
        return;
    }

    // Validate indicator data with enhanced diagnostics
    if (!validateIndicatorData(message.data, `historical_${message.symbol}`)) {
        console.error('🚨 CRITICAL: Historical data validation failed - rejecting data to prevent chart issues');
        console.error('📊 VALIDATION FAILURE DETAILS:');
        console.error('  Symbol:', message.symbol);
        console.error('  Data points:', message.data.length);
        console.error('  First point time:', message.data[0]?.time);
        console.error('  Last point time:', message.data[message.data.length - 1]?.time);
        return;
    }

    // Check if chart is ready
    const chartElement = document.getElementById('chart');
    if (!chartElement || !window.gd || !window.gd._fullLayout) {
        console.log('📊 Combined WebSocket: Chart not ready, skipping update');
        return;
    }

    // Get existing chart data to merge with
    const existingTrace = window.gd.data.find(trace => trace.type === 'candlestick');
    let existingData = [];

    if (existingTrace && existingTrace.x && existingTrace.x.length > 0) {
        // Convert existing chart data back to our format
        existingData = existingTrace.x.map((timestamp, index) => ({
            time: timestamp.getTime() / 1000, // Convert back to seconds
            ohlc: {
                open: existingTrace.open[index],
                high: existingTrace.high[index],
                low: existingTrace.low[index],
                close: existingTrace.close[index],
                volume: existingTrace.volume ? existingTrace.volume[index] : 0
            },
            indicators: {} // Will be populated from existing chart traces
        }));

        // Extract indicator data from existing chart traces
        const indicatorTraces = window.gd.data.filter(trace => trace.type !== 'candlestick');

        // Create a map of timestamps to their indices for quick lookup
        const timestampToIndex = new Map();
        existingTrace.x.forEach((timestamp, index) => {
            timestampToIndex.set(timestamp.getTime(), index);
        });

        // Process each indicator trace
        indicatorTraces.forEach(trace => {
            if (!trace.x || !trace.y) return;

            // Determine indicator type from trace name
            let indicatorId = null;
            let valueKey = null;

            if (trace.name === 'MACD') {
                indicatorId = 'macd';
                valueKey = 'macd';
            } else if (trace.name === 'MACD Signal') {
                indicatorId = 'macd';
                valueKey = 'signal';
            } else if (trace.name === 'MACD Histogram') {
                indicatorId = 'macd';
                valueKey = 'histogram';
            } else if (trace.name === 'RSI') {
                indicatorId = 'rsi';
                valueKey = 'rsi';
            } else if (trace.name === 'RSI_SMA14') {
                indicatorId = 'rsi';
                valueKey = 'rsi_sma14';
            } else if (trace.name.startsWith('Stoch K')) {
                // Extract variant from trace name (e.g., 'Stoch K (14,3)' -> 'stochrsi_14_3')
                const variantMatch = trace.name.match(/Stoch K \((\d+),(\d+)\)/);
                if (variantMatch) {
                    indicatorId = `stochrsi_${variantMatch[1]}_${variantMatch[2]}`;
                } else {
                    // Fallback to first stochrsi variant if no variant found
                    indicatorId = combinedIndicators.find(id => id.startsWith('stochrsi'));
                }
                valueKey = 'stoch_k';
            } else if (trace.name.startsWith('Stoch D')) {
                // Extract variant from trace name (e.g., 'Stoch D (14,3)' -> 'stochrsi_14_3')
                const variantMatch = trace.name.match(/Stoch D \((\d+),(\d+)\)/);
                if (variantMatch) {
                    indicatorId = `stochrsi_${variantMatch[1]}_${variantMatch[2]}`;
                } else {
                    // Fallback to first stochrsi variant if no variant found
                    indicatorId = combinedIndicators.find(id => id.startsWith('stochrsi'));
                }
                valueKey = 'stoch_d';
            } else if (trace.name === 'JMA') {
                indicatorId = 'jma';
                valueKey = 'jma';
            } else if (trace.name === 'Open Interest') {
                indicatorId = 'open_interest';
                valueKey = 'open_interest';
            }

            if (!indicatorId || !valueKey) return;

            // Add indicator values to existing data points
            trace.x.forEach((timestamp, traceIndex) => {
                const timestampMs = timestamp.getTime();
                const dataIndex = timestampToIndex.get(timestampMs);

                if (dataIndex !== undefined && trace.y[traceIndex] !== null && trace.y[traceIndex] !== undefined) {
                    if (!existingData[dataIndex].indicators[indicatorId]) {
                        existingData[dataIndex].indicators[indicatorId] = {};
                    }
                    existingData[dataIndex].indicators[indicatorId][valueKey] = trace.y[traceIndex];
                }
            });
        });

        console.log(`📊 Found ${existingData.length} existing data points in chart with indicators extracted`);
    }

    // Merge new data with existing data, preserving indicators where possible
    const mergedData = mergeDataPointsWithIndicators(existingData, message.data);

    console.log(`📊 Merged ${existingData.length} existing + ${message.data.length} new = ${mergedData.length} total points`);

    // Update chart with merged data
    updateChartWithHistoricalData(mergedData, message.symbol);

    console.log(`📊 Combined WebSocket: Chart updated with ${mergedData.length} merged data points`);
}

function mergeDataPoints(existingData, newData) {
    console.log(`🔄 MERGE DEBUG: mergeDataPoints called with ${existingData?.length || 0} existing + ${newData?.length || 0} new points`);

    if (!existingData || existingData.length === 0) {
        console.log('🔄 MERGE DEBUG: No existing data, returning sorted new data');
        return newData.sort((a, b) => a.time - b.time);
    }

    if (!newData || newData.length === 0) {
        console.log('🔄 MERGE DEBUG: No new data, returning existing data');
        return existingData;
    }

    // Log timestamp ranges for debugging
    const existingTimestamps = existingData.map(p => p.time).sort((a, b) => a - b);
    const newTimestamps = newData.map(p => p.time).sort((a, b) => a - b);

    console.log(`🔄 MERGE DEBUG: Existing data range: ${new Date(existingTimestamps[0] * 1000).toISOString()} to ${new Date(existingTimestamps[existingTimestamps.length - 1] * 1000).toISOString()}`);
    console.log(`🔄 MERGE DEBUG: New data range: ${new Date(newTimestamps[0] * 1000).toISOString()} to ${new Date(newTimestamps[newTimestamps.length - 1] * 1000).toISOString()}`);

    // Combine all data points
    const combinedData = [...existingData, ...newData];
    console.log(`🔄 MERGE DEBUG: Combined ${combinedData.length} total points`);

    // Sort by timestamp to ensure proper ordering
    const sortedData = combinedData.sort((a, b) => a.time - b.time);

    // Remove duplicates by timestamp, keeping the most recent data
    const mergedData = [];
    const seenTimestamps = new Set();
    let duplicatesFound = 0;
    let overlapsFound = 0;

    for (const point of sortedData) {
        if (!seenTimestamps.has(point.time)) {
            seenTimestamps.add(point.time);
            mergedData.push(point);
        } else {
            // If we have a duplicate timestamp, replace the existing one with the new one
            // This ensures we keep the most recent data for the same timestamp
            const existingIndex = mergedData.findIndex(p => p.time === point.time);
            if (existingIndex !== -1) {
                // Safe timestamp logging
                let timestampStr = 'invalid';
                if (point.time && !isNaN(point.time) && point.time > 0) {
                    try {
                        timestampStr = new Date(point.time * 1000).toISOString();
                    } catch(e) {
                        timestampStr = 'conversion_error';
                    }
                }
                console.log(`🔄 MERGE DEBUG: Replacing duplicate timestamp ${point.time} (${timestampStr})`);
                mergedData[existingIndex] = point;
                duplicatesFound++;
            }
            overlapsFound++;
        }
    }

    const duplicatesRemoved = combinedData.length - mergedData.length;
    console.log(`🔄 MERGE DEBUG: Processing complete - ${duplicatesFound} duplicates replaced, ${overlapsFound} overlaps detected, ${duplicatesRemoved} total points removed, ${mergedData.length} unique points remaining`);

    if (duplicatesRemoved > 0) {
        console.log(`🔄 Merged data: ${duplicatesRemoved} duplicates removed, ${mergedData.length} unique points`);
    }

    return mergedData;
}

function mergeDataPointsWithIndicators(existingData, newData) {
    console.log(`🔄 MERGE DEBUG: mergeDataPointsWithIndicators called with ${existingData?.length || 0} existing + ${newData?.length || 0} new points`);

    if (!existingData || existingData.length === 0) {
        console.log('🔄 MERGE DEBUG: No existing data, returning sorted new data');
        return newData.sort((a, b) => a.time - b.time);
    }

    if (!newData || newData.length === 0) {
        console.log('🔄 MERGE DEBUG: No new data, returning existing data');
        return existingData;
    }

    // Analyze indicator presence
    const existingWithIndicators = existingData.filter(p => Object.keys(p.indicators || {}).length > 0).length;
    const newWithIndicators = newData.filter(p => Object.keys(p.indicators || {}).length > 0).length;

    console.log(`🔄 MERGE DEBUG: Indicator analysis - Existing: ${existingWithIndicators}/${existingData.length} with indicators, New: ${newWithIndicators}/${newData.length} with indicators`);

    // Create a map of existing data by timestamp for quick lookup
    const existingDataMap = new Map();
    existingData.forEach(point => {
        existingDataMap.set(point.time, point);
    });

    // Process new data and merge with existing
    const mergedData = [...existingData]; // Start with existing data
    let replacedPoints = 0;
    let addedPoints = 0;
    let mergedIndicators = 0;

    newData.forEach(newPoint => {
        const existingPoint = existingDataMap.get(newPoint.time);

        if (existingPoint) {
            // Timestamp exists - merge the data, preferring data with indicators
            const hasExistingIndicators = Object.keys(existingPoint.indicators || {}).length > 0;
            const hasNewIndicators = Object.keys(newPoint.indicators || {}).length > 0;

            // Safe timestamp logging
            let timestampStr = 'invalid';
            if (newPoint.time && !isNaN(newPoint.time) && newPoint.time > 0) {
                try {
                    timestampStr = new Date(newPoint.time * 1000).toISOString();
                } catch(e) {
                    timestampStr = 'conversion_error';
                }
            }
            console.log(`🔄 MERGE DEBUG: Timestamp ${newPoint.time} (${timestampStr}) - Existing indicators: ${hasExistingIndicators}, New indicators: ${hasNewIndicators}`);

            if (hasNewIndicators && !hasExistingIndicators) {
                // New data has indicators, existing doesn't - use new data
                const index = mergedData.findIndex(p => p.time === newPoint.time);
                if (index !== -1) {
                    mergedData[index] = { ...newPoint };
                    replacedPoints++;
                    console.log(`🔄 MERGE DEBUG: Replaced point with new indicator data`);
                }
            } else if (hasNewIndicators && hasExistingIndicators) {
                // Both have indicators - merge them
                const index = mergedData.findIndex(p => p.time === newPoint.time);
                if (index !== -1) {
                    const existingIndicatorKeys = Object.keys(existingPoint.indicators);
                    const newIndicatorKeys = Object.keys(newPoint.indicators);
                    console.log(`🔄 MERGE DEBUG: Merging indicators - Existing: [${existingIndicatorKeys.join(', ')}], New: [${newIndicatorKeys.join(', ')}]`);

                    mergedData[index] = {
                        ...newPoint,
                        indicators: { ...existingPoint.indicators, ...newPoint.indicators }
                    };
                    mergedIndicators++;
                }
            } else {
                console.log(`🔄 MERGE DEBUG: Keeping existing data (no new indicators to merge)`);
            }
            // If existing has indicators but new doesn't, keep existing
        } else {
            // New timestamp - add it
            mergedData.push(newPoint);
            addedPoints++;
        }
    });

    // Sort by timestamp to ensure proper ordering
    const sortedData = mergedData.sort((a, b) => a.time - b.time);

    console.log(`🔄 MERGE DEBUG: Merge summary - ${replacedPoints} points replaced, ${addedPoints} points added, ${mergedIndicators} indicator merges, ${sortedData.length} total points`);
    console.log(`🔄 Merged data with indicators: ${existingData.length} existing + ${newData.length} new = ${sortedData.length} total points`);

    return sortedData;
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

    // Check if currently dragging a shape - skip live price updates during dragging
    if (window.isDraggingShape) {
        console.log('💰 Combined WebSocket: Skipping live price update during shape dragging');
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

    // Draw the live price line without triggering relayout to prevent unwanted plotly_relayout events
    updateOrAddRealtimePriceLine(gd, message.price, candleStartTimeMs, candleEndTimeMs, false);
}

function handleBuySignals(message) {
    console.log(`💰 Combined WebSocket: Received buy signals for ${message.symbol}, ${message.data.length} signals`);

    if (!message.data || !Array.isArray(message.data)) {
        console.warn('Combined WebSocket: Invalid buy signals data format');
        return;
    }

    if (message.data.length === 0) {
        console.log('Combined WebSocket: No buy signals to process');
        return;
    }

    // Process and add buy signals to the chart
    addBuySignalsToChart(message.data, message.symbol);
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

function handleHistoryUpdate(message) {
    console.log(`📈 Combined WebSocket: Received smart history update for ${message.symbol}`);

    if (!message.data || !Array.isArray(message.data)) {
        console.warn('📈 Combined WebSocket: Invalid history update data format');
        return;
    }

    if (message.data.length === 0) {
        console.log('📈 Combined WebSocket: No history data to process');
        return;
    }

    // Check if chart is ready
    const chartElement = document.getElementById('chart');
    if (!chartElement || !window.gd || !window.gd.layout) {
        console.warn('📈 Combined WebSocket: Chart not ready for history update');
        return;
    }

    console.log(`📈 Processing ${message.data.length} history update data points`);

    // Process the new data points and update the chart
    // Use the same logic as handleHistoricalData but for smaller batches
    const newDataPoints = message.data;

    // Get existing chart data to merge with
    const existingTrace = window.gd.data.find(trace => trace.type === 'candlestick');
    let existingData = [];

    if (existingTrace && existingTrace.x && existingTrace.x.length > 0) {
        // Convert existing chart data back to our format
        existingData = existingTrace.x.map((timestamp, index) => ({
            time: timestamp.getTime() / 1000, // Convert back to seconds
            ohlc: {
                open: existingTrace.open[index],
                high: existingTrace.high[index],
                low: existingTrace.low[index],
                close: existingTrace.close[index],
                volume: existingTrace.volume ? existingTrace.volume[index] : 0
            },
            indicators: {} // Will be populated from existing chart traces
        }));

        // Extract indicator data from existing chart traces
        const indicatorTraces = window.gd.data.filter(trace => trace.type !== 'candlestick');

        // Create a map of timestamps to their indices for quick lookup
        const timestampToIndex = new Map();
        existingTrace.x.forEach((timestamp, index) => {
            timestampToIndex.set(timestamp.getTime(), index);
        });

        // Process each indicator trace
        indicatorTraces.forEach(trace => {
            if (!trace.x || !trace.y) return;

            // Determine indicator type from trace name
            let indicatorId = null;
            let valueKey = null;

            if (trace.name === 'MACD') {
                indicatorId = 'macd';
                valueKey = 'macd';
            } else if (trace.name === 'MACD Signal') {
                indicatorId = 'macd';
                valueKey = 'signal';
            } else if (trace.name === 'MACD Histogram') {
                indicatorId = 'macd';
                valueKey = 'histogram';
            } else if (trace.name === 'RSI') {
                indicatorId = 'rsi';
                valueKey = 'rsi';
            } else if (trace.name === 'RSI_SMA14') {
                indicatorId = 'rsi';
                valueKey = 'rsi_sma14';
            } else if (trace.name.startsWith('Stoch K')) {
                // Extract variant from trace name
                const variantMatch = trace.name.match(/Stoch K \((\d+),(\d+)\)/);
                if (variantMatch) {
                    indicatorId = `stochrsi_${variantMatch[1]}_${variantMatch[2]}`;
                } else {
                    indicatorId = combinedIndicators.find(id => id.startsWith('stochrsi'));
                }
                valueKey = 'stoch_k';
            } else if (trace.name.startsWith('Stoch D')) {
                // Extract variant from trace name
                const variantMatch = trace.name.match(/Stoch D \((\d+),(\d+)\)/);
                if (variantMatch) {
                    indicatorId = `stochrsi_${variantMatch[1]}_${variantMatch[2]}`;
                } else {
                    indicatorId = combinedIndicators.find(id => id.startsWith('stochrsi'));
                }
                valueKey = 'stoch_d';
            } else if (trace.name === 'JMA') {
                indicatorId = 'jma';
                valueKey = 'jma';
            } else if (trace.name === 'Open Interest') {
                indicatorId = 'open_interest';
                valueKey = 'open_interest';
            }

            if (!indicatorId || !valueKey) return;

            // Add indicator values to existing data points
            trace.x.forEach((timestamp, traceIndex) => {
                const timestampMs = timestamp.getTime();
                const dataIndex = timestampToIndex.get(timestampMs);

                if (dataIndex !== undefined && trace.y[traceIndex] !== null && trace.y[traceIndex] !== undefined) {
                    if (!existingData[dataIndex].indicators[indicatorId]) {
                        existingData[dataIndex].indicators[indicatorId] = {};
                    }
                    existingData[dataIndex].indicators[indicatorId][valueKey] = trace.y[traceIndex];
                }
            });
        });
    }

    // Merge new data with existing data
    const mergedData = mergeDataPointsWithIndicators(existingData, newDataPoints);

    console.log(`📈 Merged ${existingData.length} existing + ${newDataPoints.length} new = ${mergedData.length} total points`);

    // Update chart with merged data
    updateChartWithHistoricalData(mergedData, message.symbol);

    console.log(`📈 Combined WebSocket: Chart updated with ${mergedData.length} merged data points from history update`);
}

function addBuySignalsToChart(buySignals, symbol) {
    console.log(`💰 Combined WebSocket: Adding ${buySignals.length} buy signals to chart for ${symbol}`);

    const chartElement = document.getElementById('chart');
    if (!chartElement || !window.gd) {
        console.warn('Combined WebSocket: Chart not ready for buy signals');
        return;
    }

    // Ensure layout.shapes exists
    if (!window.gd.layout.shapes) {
        window.gd.layout.shapes = [];
    }

    // Remove existing buy signal shapes
    window.gd.layout.shapes = window.gd.layout.shapes.filter(shape => !shape.name || !shape.name.startsWith('buy_signal_'));

    // Process each buy signal
    buySignals.forEach((signal, index) => {
        try {
            console.log(`💰 Combined WebSocket: Processing buy signal ${index + 1}/${buySignals.length}:`, signal);

            // Convert buy signal to Plotly shape format
            const shape = convertBuySignalToShape(signal, index);
            console.log(`💰 Combined WebSocket: Converted to shape:`, shape);

            if (shape) {
                window.gd.layout.shapes.push(shape);
                console.log(`💰 Combined WebSocket: Added buy signal ${signal.timestamp}`);
            } else {
                console.warn(`💰 Combined WebSocket: Could not convert buy signal to shape:`, signal);
            }
        } catch (error) {
            console.error(`💰 Combined WebSocket: Error processing buy signal ${index}:`, error, signal);
        }
    });

    console.log('💰 BUY SIGNALS: Final shapes count:', window.gd.layout.shapes.length);

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
        console.log(`💰 Combined WebSocket: Successfully updated chart with ${buySignals.length} buy signals`);
    } catch (error) {
        console.error('💰 Combined WebSocket: Error updating chart with buy signals:', error);
    }
}

function convertBuySignalToShape(signal, index) {
    try {
        console.log('💰 BUY SIGNALS: Converting buy signal to shape:', signal);

        // Basic shape properties for buy signal marker
        const shape = {
            name: `buy_signal_${signal.timestamp}_${index}`,
            type: 'line',
            xref: 'x',
            yref: 'y',  // Always on main price chart
            x0: new Date(signal.timestamp * 1000),
            x1: new Date(signal.timestamp * 1000),
            y0: signal.price,
            y1: signal.price,
            line: {
                color: 'green',
                width: 3,
                dash: 'solid'
            },
            layer: 'above',
            editable: false,
            isSystemShape: true,  // Mark as system shape to prevent saving
            systemType: 'buy_signal'  // Additional identification
        };

        // Add a small horizontal line to make it more visible
        shape.x0 = new Date((signal.timestamp - 3600) * 1000); // 1 hour before
        shape.x1 = new Date((signal.timestamp + 3600) * 1000); // 1 hour after
        shape.y0 = signal.price;
        shape.y1 = signal.price;

        console.log('💰 BUY SIGNALS: Final buy signal shape created:', shape);
        return shape;
    } catch (error) {
        console.error('💰 BUY SIGNALS: Error converting buy signal to shape:', error, signal);
        return null;
    }
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
                    // console.log(`Combined WebSocket: Updated existing drawing ${drawing.id}`);
                } else {
                    // Add new shape
                    window.gd.layout.shapes.push(shape);
                    // console.log(`Combined WebSocket: Added new drawing ${drawing.id}`);
                }
            } else {
                // console.warn(`Combined WebSocket: Could not convert drawing to shape:`, drawing);
            }
        } catch (error) {
            // console.error(`Combined WebSocket: Error processing drawing ${index}:`, error, drawing);
        }
    });

    // console.log('🎨 DRAWINGS: Final shapes count:', window.gd.layout.shapes.length);

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
        // console.log('🎨 DRAWINGS: Converting drawing to shape:', drawing);

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
            // console.log('🎨 DRAWINGS: Created rectangle shape:', {...shape, yref: shape.yref});
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


function updateChartWithHistoricalData(dataPoints, symbol) {
    console.log('📈 Combined WebSocket: Processing historical data for chart update');
    console.log('📈 Combined WebSocket: Data points received:', dataPoints.length);

    // Define chartElement globally for the function
    const chartElement = document.getElementById('chart');

    if (!dataPoints || dataPoints.length === 0) {
        console.warn('⚠️ Combined WebSocket: No historical data points to process');
        return;
    }

    // Check if chart update is locked
    if (isChartUpdateLocked()) {
        console.warn('🔒 Chart update locked, queuing historical data update');
        // Queue the update for later
        setTimeout(() => updateChartWithHistoricalData(dataPoints, symbol), CHART_UPDATE_DEBOUNCE_DELAY);
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

    // Validate timestamp data before converting to Date objects
    const validDataPoints = dataPoints.filter(point => {
        if (!point.time || isNaN(point.time) || point.time <= 0) {
            console.warn(`⚠️ Invalid timestamp in data point:`, {
                time: point.time,
                timeType: typeof point.time,
                isNaN: isNaN(point.time),
                dataKeys: Object.keys(point)
            });
            return false;
        }
        return true;
    });

    if (validDataPoints.length === 0) {
        console.error(`❌ No valid data points with timestamps found in ${dataPoints.length} total points`);
        return;
    }

    if (validDataPoints.length !== dataPoints.length) {
        console.warn(`⚠️ Filtered out ${dataPoints.length - validDataPoints.length} invalid data points`);
        dataPoints = validDataPoints; // Update the working dataset
    }

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

    // Find the earliest point that has ALL indicators available
    let firstCompletePointIndex = -1;
    let lastCompletePointIndex = -1;

    dataPoints.forEach((point, index) => {
        if (point.indicators && combinedIndicators.every(indicatorId => point.indicators[indicatorId])) {
            if (firstCompletePointIndex === -1) {
                firstCompletePointIndex = index;
            }
            lastCompletePointIndex = index;
        }
    });

    console.log(`📊 Indicator availability analysis:`);
    console.log(`  First complete data point: ${firstCompletePointIndex}/${dataPoints.length}`);
    console.log(`  Last complete data point: ${lastCompletePointIndex}/${dataPoints.length}`);
    console.log(`  Points with indicators: ${lastCompletePointIndex - firstCompletePointIndex + 1}`);

    // Only process points that have indicators
    // FIX: Don't filter out points with missing indicators early in the dataset
    // This is normal for indicators during warmup periods
    const processedDataPoints = dataPoints.filter((point, index) =>
        // Only require OHLC data, indicators can be null/undefined
        point.ohlc && point.ohlc.open !== undefined && point.ohlc.close !== undefined
    );

    console.log(`🔄 Filtered data - keeping ${processedDataPoints.length} points with valid OHLC data`);
    console.log(`💡 NOTE: ${dataPoints.length - processedDataPoints.length} points filtered out due to missing OHLC data`);

    processedDataPoints.forEach((point, pointIndex) => {
        // Safe timestamp conversion with validation
        let validTimestamp = null;
        if (point.time && !isNaN(point.time) && point.time > 0) {
            try {
                validTimestamp = new Date(point.time * 1000);
                // Verify the date is valid
                if (isNaN(validTimestamp.getTime())) {
                    validTimestamp = null;
                }
            } catch(e) {
                validTimestamp = null;
            }
        }

        if (!validTimestamp) {
            console.warn(`⚠️ Invalid timestamp in dataPoint ${pointIndex}:`, point.time);
            return; // Skip this data point
        }

        if (point.indicators) {
            Object.keys(point.indicators).forEach(indicatorId => {
                if (!indicatorsData[indicatorId]) {
                    indicatorsData[indicatorId] = {
                        timestamps: [],
                        values: {}
                    };
                }

                indicatorsData[indicatorId].timestamps.push(validTimestamp);

                // Store all indicator values for this point
                Object.keys(point.indicators[indicatorId]).forEach(key => {
                    const value = point.indicators[indicatorId][key];

                    if (!indicatorsData[indicatorId].values[key]) {
                        indicatorsData[indicatorId].values[key] = [];
                    }
                    indicatorsData[indicatorId].values[key].push(value);
                });
            });
        }
    });

    console.log(`✅ Processed ${processedDataPoints.length} points with complete indicator data`);

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

            // MACD with signal and histogram - use data directly from Python backend
            console.log(`Combined WebSocket: MACD - Using ${indicatorData.values.macd.length} data points from Python backend`);

            // DEBUG: Log last 5 MACD data points being sent to Plotly
            const macdLast5 = indicatorData.values.macd.slice(-5);
            const signalLast5 = indicatorData.values.signal.slice(-5);
            const histogramLast5 = indicatorData.values.histogram.slice(-5);
            const macdTimestampsLast5 = indicatorData.timestamps.slice(-5);
            console.log(`📊 MACD TRACE DATA (last 5 points):`);
            macdLast5.forEach((val, idx) => {
                console.log(`  MACD[${indicatorData.values.macd.length - 5 + idx}]: ${val} at ${macdTimestampsLast5[idx] ? new Date(macdTimestampsLast5[idx]).toISOString() : 'N/A'}`);
                console.log(`  Signal[${indicatorData.values.signal.length - 5 + idx}]: ${signalLast5[idx]} at ${macdTimestampsLast5[idx] ? new Date(macdTimestampsLast5[idx]).toISOString() : 'N/A'}`);
                console.log(`  Histogram[${indicatorData.values.histogram.length - 5 + idx}]: ${histogramLast5[idx]} at ${macdTimestampsLast5[idx] ? new Date(macdTimestampsLast5[idx]).toISOString() : 'N/A'}`);
            });

            // Use the backend's timestamps for this indicator to maintain proper alignment
            indicatorTraces.push({
                x: indicatorData.timestamps,  // Use backend timestamps for proper alignment
                y: indicatorData.values.macd,
                type: 'scatter',
                mode: 'lines',
                name: 'MACD',
                line: { color: 'blue' },
                yaxis: yAxisName,
                hoverinfo: isMobileDevice() ? 'skip' : 'all',
                connectgaps: false  // Don't connect gaps to show natural indicator behavior
            });

            indicatorTraces.push({
                x: indicatorData.timestamps,  // Use backend timestamps for proper alignment
                y: indicatorData.values.signal,
                type: 'scatter',
                mode: 'lines',
                name: 'MACD Signal',
                line: { color: 'orange' },
                yaxis: yAxisName,
                hoverinfo: isMobileDevice() ? 'skip' : 'all',
                connectgaps: false  // Don't connect gaps to show natural indicator behavior
            });

            indicatorTraces.push({
                x: indicatorData.timestamps,  // Use backend timestamps for proper alignment
                y: indicatorData.values.histogram,
                type: 'bar',
                name: 'MACD Histogram',
                marker: {
                    color: indicatorData.values.histogram.map(v => v !== null && v >= 0 ? 'green' : 'red')
                },
                yaxis: yAxisName,
                hoverinfo: isMobileDevice() ? 'skip' : 'all',
                connectgaps: false  // Don't connect gaps to show natural indicator behavior
            });
        } else if (indicatorId === 'rsi' && indicatorData.values.rsi) {
            console.log(`🔍 DEBUG: RSI condition check - rsi: ${!!indicatorData.values.rsi}`);
            console.log(`🔍 DEBUG: RSI values length: ${indicatorData.values.rsi ? indicatorData.values.rsi.length : 'N/A'}`);

            // RSI - use data directly from Python backend
            console.log(`Combined WebSocket: RSI - Using ${indicatorData.values.rsi.length} data points from Python backend`);

            // DEBUG: Log last 5 RSI data points being sent to Plotly
            const rsiLast5 = indicatorData.values.rsi.slice(-5);
            const rsiTimestampsLast5 = indicatorData.timestamps.slice(-5);
            console.log(`📊 RSI TRACE DATA (last 5 points):`);
            rsiLast5.forEach((val, idx) => {
                console.log(`  RSI[${indicatorData.values.rsi.length - 5 + idx}]: ${val} at ${rsiTimestampsLast5[idx] ? new Date(rsiTimestampsLast5[idx]).toISOString() : 'N/A'}`);
            });

            // Use the backend's timestamps for this indicator to maintain proper alignment
            const rsiValues = indicatorData.values.rsi;

            // Check for null/undefined values that might cause display issues
            const rsiNullCount = rsiValues.filter(v => v === null || v === undefined).length;
            console.log(`🔍 DEBUG: RSI null values: ${rsiNullCount}/${rsiValues.length}`);

            indicatorTraces.push({
                x: indicatorData.timestamps,  // Use backend timestamps for proper alignment
                y: rsiValues,
                type: 'scatter',
                mode: 'lines',
                name: 'RSI',
                line: { color: 'purple' },
                yaxis: yAxisName,
                hoverinfo: isMobileDevice() ? 'skip' : 'all',
                connectgaps: false  // Don't connect gaps - show natural indicator behavior
            });

            // Check for RSI_SMA14 and add it if available
            if (indicatorData.values.rsi_sma14) {
                console.log(`Combined WebSocket: RSI_SMA14 - Using ${indicatorData.values.rsi_sma14.length} data points from Python backend`);

                const rsiSma14Values = indicatorData.values.rsi_sma14;
                console.log(`🔍 DEBUG: RSI_SMA14 data - nulls: ${rsiSma14Values.filter(v => v === null).length}`);

                indicatorTraces.push({
                    x: indicatorData.timestamps,  // Use backend timestamps for proper alignment
                    y: rsiSma14Values,
                    type: 'scatter',
                    mode: 'lines',
                    name: 'RSI_SMA14',
                    line: { color: 'dodgerblue' },
                    yaxis: yAxisName,
                    hoverinfo: isMobileDevice() ? 'skip' : 'all',
                    connectgaps: false  // Don't connect gaps - show natural indicator behavior
                });
            }
        } else if (indicatorId.startsWith('stochrsi') && indicatorData.values.stoch_k && indicatorData.values.stoch_d) {
            console.log(`🔍 DEBUG: StochRSI condition check - stoch_k: ${!!indicatorData.values.stoch_k}, stoch_d: ${!!indicatorData.values.stoch_d}`);
            console.log(`🔍 DEBUG: StochRSI values lengths - k: ${indicatorData.values.stoch_k ? indicatorData.values.stoch_k.length : 'N/A'}, d: ${indicatorData.values.stoch_d ? indicatorData.values.stoch_d.length : 'N/A'}`);
            console.log(`🔍 DEBUG: StochRSI timestamps length: ${indicatorData.timestamps ? indicatorData.timestamps.length : 'N/A'}`);

            // Stochastic RSI - use data directly from Python backend
            console.log(`Combined WebSocket: StochRSI - Using ${indicatorData.values.stoch_k.length} data points from Python backend`);

            // DEBUG: Log last 5 StochRSI data points being sent to Plotly
            const stochKLast5 = indicatorData.values.stoch_k.slice(-5);
            const stochDLast5 = indicatorData.values.stoch_d.slice(-5);
            const stochTimestampsLast5 = indicatorData.timestamps.slice(-5);
            console.log(`📊 StochRSI TRACE DATA (last 5 points):`);
            stochKLast5.forEach((val, idx) => {
                console.log(`  Stoch K[${indicatorData.values.stoch_k.length - 5 + idx}]: ${val} at ${stochTimestampsLast5[idx] ? new Date(stochTimestampsLast5[idx]).toISOString() : 'N/A'}`);
            });
            stochDLast5.forEach((val, idx) => {
                console.log(`  Stoch D[${indicatorData.values.stoch_d.length - 5 + idx}]: ${val} at ${stochTimestampsLast5[idx] ? new Date(stochTimestampsLast5[idx]).toISOString() : 'N/A'}`);
            });

            // Extract variant parameters from indicatorId (e.g., 'stochrsi_14_3' -> '14,3')
            const variantMatch = indicatorId.match(/stochrsi_(\d+)_(\d+)/);
            const variantLabel = variantMatch ? `(${variantMatch[1]},${variantMatch[2]})` : '';

            // Use the backend's timestamps for this indicator to maintain proper alignment
            const kValues = indicatorData.values.stoch_k;
            const dValues = indicatorData.values.stoch_d;

            // Check for null/undefined values that might cause display issues
            const kNullCount = kValues.filter(v => v === null || v === undefined).length;
            const dNullCount = dValues.filter(v => v === null || v === undefined).length;

            console.log(`🔍 DEBUG: StochRSI null values - K: ${kNullCount}/${kValues.length}, D: ${dNullCount}/${dValues.length}`);

            indicatorTraces.push({
                x: indicatorData.timestamps,  // Use backend timestamps for proper alignment
                y: kValues,
                type: 'scatter',
                mode: 'lines',
                name: `Stoch K ${variantLabel}`,
                line: { color: 'blue' },
                yaxis: yAxisName,
                hoverinfo: isMobileDevice() ? 'skip' : 'all',
                connectgaps: false  // Don't connect gaps - show natural indicator behavior
            });

            indicatorTraces.push({
                x: indicatorData.timestamps,  // Use backend timestamps for proper alignment
                y: dValues,
                type: 'scatter',
                mode: 'lines',
                name: `Stoch D ${variantLabel}`,
                line: { color: 'orange' },
                yaxis: yAxisName,
                hoverinfo: isMobileDevice() ? 'skip' : 'all',
                connectgaps: false  // Don't connect gaps - show natural indicator behavior
            });
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

    // DEBUG: Export data as CSV for analysis
    window.exportPlotlyDataAsCSV = function() {
        console.log('📊 EXPORTING PLOTLY DATA AS CSV FOR DEBUGGING...');

        if (!window.gd || !window.gd.data) {
            console.log('❌ No chart data to export');
            return;
        }

        try {
            // Prepare CSV data
            const csvRows = [];
            const headers = ['timestamp', 'iso_timestamp'];

            // Add OHLC data headers
            headers.push('open', 'high', 'low', 'close', 'volume');

            // Add indicator headers
            const allIndicatorNames = [];
            window.gd.data.forEach(trace => {
                if (trace.name === 'MACD') allIndicatorNames.push('macd');
                else if (trace.name === 'MACD Signal') allIndicatorNames.push('macd_signal');
                else if (trace.name === 'MACD Histogram') allIndicatorNames.push('macd_histogram');
                else if (trace.name === 'RSI') allIndicatorNames.push('rsi');
                else if (trace.name === 'RSI_SMA14') allIndicatorNames.push('rsi_sma14');
                else if (trace.name.startsWith('Stoch K')) allIndicatorNames.push('stoch_k');
                else if (trace.name.startsWith('Stoch D')) allIndicatorNames.push('stoch_d');
            });

            allIndicatorNames.forEach(name => headers.push(name));

            csvRows.push(headers.join(','));

            // Get price trace
            const priceTrace = window.gd.data.find(t => t.type === 'candlestick');
            if (!priceTrace || !priceTrace.x) {
                console.log('❌ No price trace found');
                return;
            }

            // Process each data point
            for (let i = 0; i < priceTrace.x.length; i++) {
                const timestamp = Math.floor(priceTrace.x[i].getTime() / 1000); // Convert to seconds
                const isoTimestamp = priceTrace.x[i].toISOString();

                const row = [timestamp, isoTimestamp];

                // Add OHLC data
                row.push(
                    priceTrace.open[i] || '',
                    priceTrace.high[i] || '',
                    priceTrace.low[i] || '',
                    priceTrace.close[i] || '',
                    priceTrace.volume[i] || ''
                );

                // Add indicator data
                allIndicatorNames.forEach(indicatorName => {
                    let value = '';

                    // Find corresponding indicator trace
                    let targetTrace = null;
                    if (indicatorName === 'macd') {
                        targetTrace = window.gd.data.find(t => t.name === 'MACD');
                    } else if (indicatorName === 'macd_signal') {
                        targetTrace = window.gd.data.find(t => t.name === 'MACD Signal');
                    } else if (indicatorName === 'macd_histogram') {
                        targetTrace = window.gd.data.find(t => t.name === 'MACD Histogram');
                    } else if (indicatorName === 'rsi') {
                        targetTrace = window.gd.data.find(t => t.name === 'RSI');
                    } else if (indicatorName === 'rsi_sma14') {
                        targetTrace = window.gd.data.find(t => t.name === 'RSI_SMA14');
                    } else if (indicatorName === 'stoch_k') {
                        targetTrace = window.gd.data.find(t => t.name.startsWith('Stoch K'));
                    } else if (indicatorName === 'stoch_d') {
                        targetTrace = window.gd.data.find(t => t.name.startsWith('Stoch D'));
                    }

                    if (targetTrace && targetTrace.y) {
                        // Check if the current index is valid for this trace
                        if (i < targetTrace.y.length) {
                            const traceValue = targetTrace.y[i];
                            // If value is a number or valid value, use it; otherwise empty string
                            value = (typeof traceValue === 'number' && !isNaN(traceValue)) ? traceValue : '';
                        } else {
                            // Index out of bounds - likely due to filtering removing early data points
                            value = '';
                        }
                    } else {
                        value = '';
                    }

                    row.push(value);
                });

                csvRows.push(row.join(','));
            }

            // Create and download CSV
            const csvContent = csvRows.join('\n');
            const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            const link = document.createElement('a');

            if (link.download !== undefined) {
                const url = URL.createObjectURL(blob);
                link.setAttribute('href', url);
                const filename = `plotly_data_${combinedSymbol}_${combinedResolution}_${new Date().getTime()}.csv`;
                link.setAttribute('download', filename);
                link.style.visibility = 'hidden';
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                URL.revokeObjectURL(url);

                console.log(`✅ CSV exported successfully: ${filename}`);
                console.log(`📊 Exported ${csvRows.length - 1} data points`);
                console.log('📋 CSV contains columns:', headers.join(', '));
            } else {
                console.log('❌ Browser does not support CSV download');
                console.log('📋 CSV Content:');
                console.log(csvContent);
            }

            return csvContent;

        } catch (error) {
            console.error('❌ Error exporting CSV:', error);
            return null;
        }
    };

    console.log('🛠️ DEBUG: exportPlotlyDataAsCSV() function is now available - call it to download current chart data as CSV');

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

    // Acquire chart update lock
    if (!acquireChartUpdateLock()) {
        console.warn('🔒 Could not acquire chart update lock for historical data');
        return;
    }

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
    }).finally(() => {
        // Always release the lock
        releaseChartUpdateLock();
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

    // Check if chart update is locked
    if (isChartUpdateLocked()) {
        console.warn('🔒 Chart update locked, queuing live data update');
        // Queue the update for later
        setTimeout(() => updateChartWithLiveData(dataPoint, symbol), CHART_UPDATE_DEBOUNCE_DELAY);
        return;
    }

    // Safe timestamp conversion with validation
    let timestamp;
    if (dataPoint.time && !isNaN(dataPoint.time) && dataPoint.time > 0) {
        try {
            timestamp = new Date(dataPoint.time * 1000);
            if (isNaN(timestamp.getTime())) {
                console.warn(`⚠️ Invalid timestamp in live data:`, dataPoint.time);
                return;
            }
        } catch(e) {
            console.warn(`⚠️ Error converting timestamp in live data:`, dataPoint.time);
            return;
        }
    } else {
        console.warn(`⚠️ Invalid or missing timestamp in live data:`, dataPoint.time);
        return;
    }

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

    // Acquire chart update lock
    if (!acquireChartUpdateLock()) {
        console.warn('🔒 Could not acquire chart update lock for live data');
        return;
    }

    try {
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
    } finally {
        // Always release the lock
        releaseChartUpdateLock();
    }

    // Update price line if it exists
    updateOrAddRealtimePriceLine(gd, price, timestamp.getTime(), timestamp.getTime() + (getTimeframeSecondsJS(combinedResolution) * 1000));

    // console.log(`Combined WebSocket: Updated live data for ${symbol} at ${timestamp.toISOString()}`);
}

function closeCombinedWebSocket(reason = "Closing WebSocket") {
    logWebSocketEvent('close_requested', { reason });

    if (combinedWebSocket) {
        const wasConnected = combinedWebSocket.readyState === WebSocket.OPEN;
        const connectionId = websocketConnectionId;

        // Remove all event handlers to prevent any further processing
        combinedWebSocket.onopen = null;
        combinedWebSocket.onmessage = null;
        combinedWebSocket.onerror = null;
        combinedWebSocket.onclose = null;

        // Close the connection
        if (combinedWebSocket.readyState === WebSocket.OPEN || combinedWebSocket.readyState === WebSocket.CONNECTING) {
            combinedWebSocket.close(1000, reason);
        }

        logWebSocketEvent('connection_closed', {
            wasConnected,
            finalState: combinedWebSocket.readyState,
            connectionId
        });

        combinedWebSocket = null;
    }

    // Reset all state variables
    combinedSymbol = '';
    combinedIndicators = [];
    combinedResolution = '1h';
    combinedFromTs = null;
    combinedToTs = null;

    // Clear message queue and processing state
    messageQueue = [];
    isProcessingMessage = false;

    // Clear processed message tracking
    processedMessageIds.clear();
    lastProcessedTimestampRange = null;

    // Reset connection flags
    isWebSocketConnecting = false;
    if (websocketSetupDebounceTimer) {
        clearTimeout(websocketSetupDebounceTimer);
        websocketSetupDebounceTimer = null;
    }

    logWebSocketEvent('state_reset', { reason });
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
        } else if (trace.name.startsWith('Stoch K') || trace.name.startsWith('Stoch D')) {
            // Extract variant from trace name (e.g., 'Stoch K (14,3)' -> 'stochrsi_14_3')
            const variantMatch = trace.name.match(/Stoch [KD] \((\d+),(\d+)\)/);
            if (variantMatch) {
                const stochVariant = `stochrsi_${variantMatch[1]}_${variantMatch[2]}`;
                if (!indicators.includes(stochVariant)) indicators.push(stochVariant);
            } else {
                // Fallback to first stochrsi variant if no variant found
                const stochVariant = window.combinedIndicators?.find(id => id.startsWith('stochrsi'));
                if (stochVariant && !indicators.includes(stochVariant)) indicators.push(stochVariant);
            }
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
        } else if (trace.name.startsWith('Stoch K') || trace.name.startsWith('Stoch D')) {
            // Extract variant from trace name (e.g., 'Stoch K (14,3)' -> 'stochrsi_14_3')
            const variantMatch = trace.name.match(/Stoch [KD] \((\d+),(\d+)\)/);
            if (variantMatch) {
                traceIndicatorId = `stochrsi_${variantMatch[1]}_${variantMatch[2]}`;
            } else {
                // Fallback to first stochrsi variant if no variant found
                traceIndicatorId = newIndicators.find(id => id.startsWith('stochrsi'));
            }
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
            showticklabels: true,
            side: 'bottom',
            minor: {
                ticks: 'inside',
                ticklen: 4,
                tickcolor: 'rgba(0,0,0,0.3)',
                showgrid: false
            }
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
        const priceChartProportion = 3; // Price chart is 3 parts
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
            pattern: 'independent',
            roworder: 'top to bottom',
            rowheights: rowHeights,
            vertical_spacing: 0.05
        };

        console.log(`DEBUG: Grid created with ${rowHeights.length} rows, vertical_spacing: 0.05`);

        // Add background colors to even indicators
        baseLayout.shapes = baseLayout.shapes || [];

        // Add separator lines between indicators
        // Use the same domain calculation as the y-axes
        const priceDomainEnd = priceChartProportion / totalProportions;

        for (let i = 0; i < numIndicators - 1; i++) {
            const linePosition = priceDomainEnd + ((i + 1) * indicatorHeight);
            baseLayout.shapes.push({
                type: 'line',
                xref: 'paper',
                yref: 'paper',
                x0: 0,
                y0: linePosition,
                x1: 1,
                y1: linePosition,
                line: { color: 'rgba(0, 0, 0, 0.92)', width: 1 },
                layer: 'below'
            });
        }

        // Set manual domains for each y-axis to ensure proper height allocation
        activeIndicatorIds.forEach((indicatorId, index) => {
            const yAxisName = `yaxis${index + 2}`;
            const xAxisName = `xaxis${index + 2}`;
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

            // Create separate x-axis for each indicator subplot (but hide the labels)
            baseLayout[xAxisName] = {
                rangeslider: { visible: false },
                type: 'date',
                autorange: !window.currentXAxisRange,
                range: window.currentXAxisRange ? [
                    new Date(window.currentXAxisRange[0] < 2e9 ? window.currentXAxisRange[0] * 1000 : window.currentXAxisRange[0]),
                    new Date(window.currentXAxisRange[1] < 2e9 ? window.currentXAxisRange[1] * 1000 : window.currentXAxisRange[1])
                ] : undefined,
                showticklabels: false, // Hide x-axis labels for indicator subplots
                anchor: yAxisName // Anchor to the corresponding y-axis
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
    const oldResolution = combinedResolution;
    combinedResolution = newResolution;
    if (combinedWebSocket && combinedWebSocket.readyState === WebSocket.OPEN) {
        sendCombinedConfig(oldResolution);
    }
}

// Helper function to get timeframe seconds (assuming it's defined elsewhere)
function getTimeframeSecondsJS(timeframe) {
    const multipliers = {
        "1m": 60,
        "5m": 300,
        "1h": 3600,
        "4h": 14400,
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
window.mergeDataPoints = mergeDataPoints;
window.mergeDataPointsWithIndicators = mergeDataPointsWithIndicators;

// DEBUG: Add debugging function for chart diagnosis
window.debugChartState = function() {
    // console.log('🔍 CHART DEBUG INFORMATION:');
    // console.log('Current WebSocket state:', combinedWebSocket ? combinedWebSocket.readyState : 'none');

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

// DEBUG: Add functions for testing the new synchronization features
window.getMessageQueueStatus = function() {
    console.log('📨 MESSAGE QUEUE STATUS:');
    console.log('  Queue length:', messageQueue.length);
    console.log('  Is processing:', isProcessingMessage);
    console.log('  Chart update locked:', chartUpdateLock);
    console.log('  Queue contents:', messageQueue.map(msg => msg.type));
    return {
        queueLength: messageQueue.length,
        isProcessing: isProcessingMessage,
        chartLocked: chartUpdateLock,
        messageTypes: messageQueue.map(msg => msg.type)
    };
};

// DEBUG: Comprehensive chart inspection for data overlapping issues
window.inspectChartData = function() {
    console.log('🔍 CHART DATA INSPECTION:');
    if (!window.gd || !window.gd.data) {
        console.log('❌ No chart data available');
        return { error: 'No chart data' };
    }

    const traces = window.gd.data;
    console.log(`📊 Total traces: ${traces.length}`);

    const inspection = {
        totalTraces: traces.length,
        traces: [],
        overlappingDetected: false,
        issues: []
    };

    traces.forEach((trace, index) => {
        const traceInfo = {
            index,
            name: trace.name,
            type: trace.type,
            yaxis: trace.yaxis,
            dataPoints: trace.x ? trace.x.length : 0,
            firstTimestamp: trace.x && trace.x.length > 0 ? new Date(trace.x[0]).toISOString() : null,
            lastTimestamp: trace.x && trace.x.length > 0 ? new Date(trace.x[trace.x.length - 1]).toISOString() : null,
            yRange: trace.y ? [Math.min(...trace.y), Math.max(...trace.y)] : null
        };

        inspection.traces.push(traceInfo);
        console.log(`  Trace ${index}: ${trace.name} (${trace.type}) - ${traceInfo.dataPoints} points on ${trace.yaxis}`);
        console.log(`    Time range: ${traceInfo.firstTimestamp} to ${traceInfo.lastTimestamp}`);
        console.log(`    Y range: ${traceInfo.yRange ? traceInfo.yRange.join(' to ') : 'N/A'}`);
    });

    // Check for overlapping issues
    const priceTraces = traces.filter(t => t.type === 'candlestick');
    const indicatorTraces = traces.filter(t => t.type !== 'candlestick');

    // Check if multiple price traces exist
    if (priceTraces.length > 1) {
        inspection.issues.push(`Multiple price traces detected: ${priceTraces.length}`);
        inspection.overlappingDetected = true;
    }

    // Check for traces on wrong y-axes
    const mainAxisTraces = traces.filter(t => t.yaxis === 'y' || !t.yaxis);
    if (mainAxisTraces.length > 1) {
        inspection.issues.push(`Multiple traces on main y-axis: ${mainAxisTraces.map(t => t.name).join(', ')}`);
        inspection.overlappingDetected = true;
    }

    // Check for duplicate trace names
    const traceNames = traces.map(t => t.name);
    const duplicateNames = traceNames.filter((name, index) => traceNames.indexOf(name) !== index);
    if (duplicateNames.length > 0) {
        inspection.issues.push(`Duplicate trace names: ${[...new Set(duplicateNames)].join(', ')}`);
        inspection.overlappingDetected = true;
    }

    console.log('🚨 ISSUES DETECTED:', inspection.issues.length);
    inspection.issues.forEach(issue => console.log(`  ❌ ${issue}`));

    return inspection;
};

// DEBUG: Comprehensive diagnostic report for data overlapping issues
window.diagnoseDataOverlapping = function() {
    console.log('🔬 COMPREHENSIVE DATA OVERLAPPING DIAGNOSIS');
    console.log('='.repeat(50));

    const diagnosis = {
        timestamp: new Date().toISOString(),
        issues: [],
        recommendations: [],
        severity: 'low'
    };

    // 1. Chart data inspection
    console.log('\n1️⃣ CHART DATA INSPECTION:');
    const chartInspection = window.inspectChartData();
    if (chartInspection.overlappingDetected) {
        diagnosis.issues.push(...chartInspection.issues);
        diagnosis.severity = 'high';
    }

    // 2. Data merging analysis
    console.log('\n2️⃣ DATA MERGING ANALYSIS:');
    const dataAnalysis = window.analyzeDataMerging();
    if (dataAnalysis.duplicates > 0) {
        diagnosis.issues.push(`Found ${dataAnalysis.duplicates} duplicate timestamps`);
        diagnosis.recommendations.push('Check data merging logic in mergeDataPoints functions');
    }
    if (dataAnalysis.gaps > 0) {
        diagnosis.issues.push(`Found ${dataAnalysis.gaps} data gaps`);
    }

    // 3. Layout inspection
    console.log('\n3️⃣ LAYOUT INSPECTION:');
    const layoutInspection = window.inspectLayout();
    if (layoutInspection.issues.length > 0) {
        diagnosis.issues.push(...layoutInspection.issues);
        diagnosis.severity = 'high';
    }

    // 4. WebSocket status
    console.log('\n4️⃣ WEBSOCKET STATUS:');
    const wsStatus = window.checkWebSocketStatus();
    console.log(`  Connected: ${wsStatus.connected}`);
    console.log(`  State: ${wsStatus.readyState}`);
    console.log(`  Has handler: ${wsStatus.hasHandler}`);

    // 5. Current state
    console.log('\n5️⃣ CURRENT STATE:');
    console.log(`  Symbol: ${combinedSymbol}`);
    console.log(`  Resolution: ${combinedResolution}`);
    console.log(`  Indicators: ${JSON.stringify(combinedIndicators)}`);
    console.log(`  Time range: ${combinedFromTs} to ${combinedToTs}`);

    // 6. Message queue status
    console.log('\n6️⃣ MESSAGE QUEUE STATUS:');
    const queueStatus = window.getMessageQueueStatus();
    console.log(`  Queue length: ${queueStatus.queueLength}`);
    console.log(`  Processing: ${queueStatus.isProcessing}`);
    console.log(`  Chart locked: ${queueStatus.chartLocked}`);

    // Summary and recommendations
    console.log('\n📋 SUMMARY:');
    console.log(`  Total issues found: ${diagnosis.issues.length}`);
    console.log(`  Severity: ${diagnosis.severity}`);

    if (diagnosis.issues.length > 0) {
        console.log('\n🚨 ISSUES FOUND:');
        diagnosis.issues.forEach((issue, index) => {
            console.log(`  ${index + 1}. ${issue}`);
        });
    }

    if (diagnosis.recommendations.length > 0) {
        console.log('\n💡 RECOMMENDATIONS:');
        diagnosis.recommendations.forEach((rec, index) => {
            console.log(`  ${index + 1}. ${rec}`);
        });
    }

    // Quick fix suggestions
    console.log('\n🔧 QUICK FIXES TO TRY:');
    console.log('  1. Run: window.clearChartData() - Clear all chart data');
    console.log('  2. Run: window.forceReloadChart() - Force chart reload');
    console.log('  3. Run: window.resetWebSocket() - Reset WebSocket connection');
    console.log('  4. Check browser console for detailed error messages');

    return diagnosis;
};

// DEBUG: Quick fix functions
window.clearChartData = function() {
    if (window.gd) {
        console.log('🧹 Clearing all chart data...');
        Plotly.react(window.gd, [], window.gd.layout || {});
        console.log('✅ Chart data cleared');
    } else {
        console.log('❌ No chart available to clear');
    }
};

window.forceReloadChart = function() {
    console.log('🔄 Forcing chart reload...');
    if (window.gd) {
        // Clear and reinitialize
        Plotly.react(window.gd, [], {});
        // Reconnect WebSocket
        if (combinedSymbol) {
            setupCombinedWebSocket(combinedSymbol, combinedIndicators, combinedResolution, combinedFromTs, combinedToTs);
        }
        console.log('✅ Chart reload initiated');
    } else {
        console.log('❌ No chart available to reload');
    }
};

window.resetWebSocket = function() {
    console.log('🔌 Resetting WebSocket connection...');
    closeCombinedWebSocket("Manual reset for debugging");
    setTimeout(() => {
        if (combinedSymbol) {
            setupCombinedWebSocket(combinedSymbol, combinedIndicators, combinedResolution, combinedFromTs, combinedToTs);
            console.log('✅ WebSocket reset complete');
        }
    }, 1000);
};

// DEBUG: Test data clearing on resolution changes
window.testResolutionChangeDataClearing = function() {
    console.log('🧪 TESTING RESOLUTION CHANGE DATA CLEARING');

    // Get current state
    const originalResolution = combinedResolution;
    const originalDataCount = window.gd && window.gd.data ? window.gd.data.length : 0;

    console.log(`📊 Before resolution change:`);
    console.log(`  Resolution: ${originalResolution}`);
    console.log(`  Data traces: ${originalDataCount}`);

    // Simulate resolution change from 1h to 1d
    const newResolution = originalResolution === '1h' ? '1d' : '1h';
    console.log(`🔄 Simulating resolution change: ${originalResolution} → ${newResolution}`);

    // Check if chart data is cleared (this should happen in main.js resolution change handler)
    setTimeout(() => {
        const afterDataCount = window.gd && window.gd.data ? window.gd.data.length : 0;
        console.log(`📊 After resolution change:`);
        console.log(`  Data traces: ${afterDataCount}`);

        if (afterDataCount === 0) {
            console.log('✅ Chart data was properly cleared');
        } else if (afterDataCount === originalDataCount) {
            console.log('⚠️ Chart data was NOT cleared - this could cause overlapping');
        } else {
            console.log('🤔 Chart data partially cleared - investigate further');
        }

        // Test WebSocket config update
        if (combinedWebSocket && combinedWebSocket.readyState === WebSocket.OPEN) {
            console.log('🔌 WebSocket is connected, testing config update...');
            sendCombinedConfig(originalResolution); // Pass old resolution to test change detection
        } else {
            console.log('❌ WebSocket not connected');
        }
    }, 100);

    return {
        originalResolution,
        newResolution,
        originalDataCount,
        testCompleted: true
    };
};

// DEBUG: Monitor chart updates for overlapping
window.monitorChartUpdates = function(duration = 30000) {
    console.log(`👀 MONITORING CHART UPDATES for ${duration / 1000} seconds`);

    let updateCount = 0;
    let lastTraceCount = window.gd && window.gd.data ? window.gd.data.length : 0;
    let overlappingDetected = false;

    const monitorInterval = setInterval(() => {
        if (!window.gd || !window.gd.data) {
            console.log('❌ Chart not available for monitoring');
            clearInterval(monitorInterval);
            return;
        }

        const currentTraceCount = window.gd.data.length;
        updateCount++;

        if (currentTraceCount !== lastTraceCount) {
            console.log(`📊 Update ${updateCount}: Trace count changed from ${lastTraceCount} to ${currentTraceCount}`);

            // Check for potential overlapping
            const priceTraces = window.gd.data.filter(t => t.type === 'candlestick');
            if (priceTraces.length > 1) {
                console.log('🚨 OVERLAPPING DETECTED: Multiple price traces!');
                overlappingDetected = true;
            }

            lastTraceCount = currentTraceCount;
        }
    }, 1000); // Check every second

    // Stop monitoring after duration
    setTimeout(() => {
        clearInterval(monitorInterval);
        console.log(`🏁 MONITORING COMPLETE:`);
        console.log(`  Total updates detected: ${updateCount}`);
        console.log(`  Overlapping detected: ${overlappingDetected}`);
    }, duration);

    return {
        monitoring: true,
        duration,
        monitorInterval
    };
};

// DEBUG: Check data merging logic for duplicates and overlaps
window.analyzeDataMerging = function() {
    console.log('🔄 DATA MERGING ANALYSIS:');
    if (!window.gd || !window.gd.data) {
        console.log('❌ No chart data available');
        return { error: 'No chart data' };
    }

    const priceTrace = window.gd.data.find(t => t.type === 'candlestick');
    if (!priceTrace || !priceTrace.x) {
        console.log('❌ No price data available');
        return { error: 'No price data' };
    }

    const timestamps = priceTrace.x.map(t => t.getTime());
    const analysis = {
        totalPoints: timestamps.length,
        duplicates: 0,
        gaps: 0,
        timeRange: {
            start: new Date(Math.min(...timestamps)).toISOString(),
            end: new Date(Math.max(...timestamps)).toISOString()
        }
    };

    // Check for duplicate timestamps
    const seenTimestamps = new Set();
    timestamps.forEach(ts => {
        if (seenTimestamps.has(ts)) {
            analysis.duplicates++;
        }
        seenTimestamps.add(ts);
    });

    // Check for gaps in data
    const sortedTimestamps = [...timestamps].sort((a, b) => a - b);
    const expectedInterval = getTimeframeSecondsJS(combinedResolution) * 1000; // Convert to milliseconds

    for (let i = 1; i < sortedTimestamps.length; i++) {
        const gap = sortedTimestamps[i] - sortedTimestamps[i - 1];
        if (gap > expectedInterval * 1.5) { // Allow 50% tolerance
            analysis.gaps++;
        }
    }

    console.log(`📊 Data Analysis Results:`);
    console.log(`  Total data points: ${analysis.totalPoints}`);
    console.log(`  Duplicate timestamps: ${analysis.duplicates}`);
    console.log(`  Data gaps: ${analysis.gaps}`);
    console.log(`  Time range: ${analysis.timeRange.start} to ${analysis.timeRange.end}`);
    console.log(`  Expected interval: ${expectedInterval}ms (${expectedInterval / 1000}s)`);

    return analysis;
};

// DEBUG: Inspect subplot layout for overlapping issues
window.inspectLayout = function() {
    console.log('📐 LAYOUT INSPECTION:');
    if (!window.gd || !window.gd.layout) {
        console.log('❌ No chart layout available');
        return { error: 'No layout' };
    }

    const layout = window.gd.layout;
    const inspection = {
        hasGrid: !!layout.grid,
        gridRows: layout.grid ? layout.grid.rows : 0,
        gridColumns: layout.grid ? layout.grid.columns : 0,
        yAxes: [],
        xAxes: [],
        issues: []
    };

    // Check Y-axes
    Object.keys(layout).forEach(key => {
        if (key.startsWith('yaxis')) {
            const axis = layout[key];
            inspection.yAxes.push({
                name: key,
                domain: axis.domain,
                range: axis.range,
                title: axis.title ? axis.title.text : 'No title'
            });
        }
    });

    // Check X-axes
    Object.keys(layout).forEach(key => {
        if (key.startsWith('xaxis')) {
            const axis = layout[key];
            inspection.xAxes.push({
                name: key,
                domain: axis.domain,
                range: axis.range
            });
        }
    });

    console.log(`📊 Layout Analysis:`);
    console.log(`  Grid: ${inspection.gridRows} rows x ${inspection.gridColumns} columns`);
    console.log(`  Y-axes: ${inspection.yAxes.length}`);
    console.log(`  X-axes: ${inspection.xAxes.length}`);

    inspection.yAxes.forEach(axis => {
        console.log(`    ${axis.name}: domain [${axis.domain.join(', ')}], range [${axis.range ? axis.range.join(', ') : 'auto'}]`);
    });

    // Check for overlapping domains
    for (let i = 0; i < inspection.yAxes.length - 1; i++) {
        const current = inspection.yAxes[i];
        const next = inspection.yAxes[i + 1];

        if (current.domain && next.domain) {
            const currentEnd = current.domain[1];
            const nextStart = next.domain[0];

            if (currentEnd > nextStart) {
                inspection.issues.push(`Overlapping Y-axis domains: ${current.name} ends at ${currentEnd}, ${next.name} starts at ${nextStart}`);
            }
        }
    }

    // Check for missing domains
    inspection.yAxes.forEach(axis => {
        if (!axis.domain) {
            inspection.issues.push(`Missing domain for ${axis.name}`);
        }
    });

    console.log('🚨 LAYOUT ISSUES:', inspection.issues.length);
    inspection.issues.forEach(issue => console.log(`  ❌ ${issue}`));

    return inspection;
};

window.clearMessageQueue = function() {
    const clearedCount = messageQueue.length;
    messageQueue = [];
    console.log(`🧹 Cleared ${clearedCount} messages from queue`);
    return clearedCount;
};

window.forceReleaseChartLock = function() {
    if (chartUpdateLock) {
        releaseChartUpdateLock();
        console.log('🔓 Force released chart update lock');
        return true;
    } else {
        console.log('ℹ️ Chart update lock was not held');
        return false;
    }
};

// DEBUG: Get WebSocket logs for debugging
window.getWebSocketLogs = function(limit = 20) {
    console.log(`🔌 WEBSOCKET LOGS (last ${limit} entries):`);
    const logsToShow = websocketLogs.slice(-limit);

    if (logsToShow.length === 0) {
        console.log('❌ No WebSocket logs available');
        return [];
    }

    logsToShow.forEach((log, index) => {
        const time = new Date(log.timestamp).toLocaleTimeString();
        console.log(`${index + 1}. [${time}] WS[${log.connectionId}]: ${log.event}`, log.details);
    });

    console.log(`📊 Total logs available: ${websocketLogs.length}`);
    return logsToShow;
};

// DEBUG: Clear WebSocket logs
window.clearWebSocketLogs = function() {
    const clearedCount = websocketLogs.length;
    websocketLogs.length = 0;
    console.log(`🧹 Cleared ${clearedCount} WebSocket logs`);
    return clearedCount;
};
