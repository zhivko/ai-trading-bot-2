// tradeHistory.js - Trade history visualization module

let tradeHistoryData = [];
let volumeProfileData = [];
let tradeMarkers = [];
let volumeProfileTraces = [];

// Minimum volume slider configuration for crypto trades
const MIN_VOLUME_DEFAULT = 0;
const MIN_VOLUME_MIN = 0;
const MIN_VOLUME_MAX = 1000; // Max for crypto base assets (BTC trades can be large)
const MIN_VOLUME_STEP = 1;

// Initialize trade history functionality
function initializeTradeHistory() {
    console.log('[TRADE_HISTORY] Initializing trade history functionality');

    // Setup event listeners for trade visualization controls
    setupTradeHistoryControls();

    // Trade history data will come automatically via WebSocket when chart connects
    // No manual fetching needed - data flows through WebSocket messages
}

// Setup event listeners for trade history controls
function setupTradeHistoryControls() {
    console.log('[TRADE_HISTORY] Setting up trade history controls');

    // Get DOM elements
    const volumeProfileCheckbox = document.getElementById('show-volume-profile-checkbox');
    const tradeMarkersCheckbox = document.getElementById('show-trade-markers-checkbox');
    const minVolumeSlider = document.getElementById('min-volume-slider');
    const minVolumeValue = document.getElementById('min-volume-value');

    console.log('[TRADE_HISTORY] DOM elements found:', {
        volumeProfileCheckbox: !!volumeProfileCheckbox,
        tradeMarkersCheckbox: !!tradeMarkersCheckbox,
        minVolumeSlider: !!minVolumeSlider,
        minVolumeValue: !!minVolumeValue
    });

    // Trade visualization checkboxes
    if (volumeProfileCheckbox) {
        volumeProfileCheckbox.addEventListener('change', handleVolumeProfileToggle);
        console.log('[TRADE_HISTORY] Volume profile checkbox event listener added');
    }
    if (tradeMarkersCheckbox) {
        tradeMarkersCheckbox.addEventListener('change', handleTradeMarkersToggle);
        console.log('[TRADE_HISTORY] Trade markers checkbox event listener added');
    }

    // Trade filter slider
    if (minVolumeSlider) {
        minVolumeSlider.addEventListener('input', handleMinVolumeChange);
        console.log('[TRADE_HISTORY] Min volume slider event listener added');
    }

    // Trade history data will come automatically via WebSocket
    // No need to manually fetch on symbol change - WebSocket broadcasts to all clients

    console.log('[TRADE_HISTORY] Trade history controls setup completed');
}

// Fetch trade history data for the current symbol
async function fetchTradeHistoryForCurrentSymbol(symbol = null, limit = 20) {
    const currentSymbol = symbol || (window.symbolSelect ? window.symbolSelect.value : null);
    if (!currentSymbol) {
        console.warn('[TRADE_HISTORY] No symbol available for trade history fetch');
        return;
    }

    console.log(`[TRADE_HISTORY] Fetching trade history for symbol: ${currentSymbol}, limit: ${limit}`);

    try {
        const response = await fetch(`/trade-history?symbol=${currentSymbol}&limit=${limit}`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const result = await response.json();
        if (result.status === 'success') {
            tradeHistoryData = result.data || [];
            console.log(`[TRADE_HISTORY] Fetched ${tradeHistoryData.length} trade records`);

            // Process data for volume profile and trade markers
            processTradeHistoryData();

            // Update visualizations if enabled
            updateTradeHistoryVisualizations();
        } else if (Array.isArray(result)) {
            // Handle direct array response (fallback to old format)
            tradeHistoryData = result;
            console.log(`[TRADE_HISTORY] Fetched ${tradeHistoryData.length} trade records (legacy format)`);

            // Process data for volume profile and trade markers
            processTradeHistoryData();

            // Update visualizations if enabled
            updateTradeHistoryVisualizations();
        } else {
            console.error('[TRADE_HISTORY] Failed to fetch trade history:', result.message || result);
            tradeHistoryData = [];
        }
    } catch (error) {
        console.error('[TRADE_HISTORY] Error fetching trade history:', error);
        tradeHistoryData = [];
    }
}

// Process trade history data for visualization
function processTradeHistoryData() {
    if (!tradeHistoryData || tradeHistoryData.length === 0) {
        console.log('[TRADE_HISTORY] No trade data to process');
        return;
    }

    console.log('[TRADE_HISTORY] Processing trade history data');

    // Group trades by price level for volume profile
    const volumeMap = new Map();
    const priceLevels = [];

    tradeHistoryData.forEach(trade => {
        const price = trade.price;
        const volume = Math.abs(trade.quantity || trade.qty || trade.size);
        const side = trade.side && trade.side.toUpperCase() === 'SELL' ? 'sell' : 'buy';
        const timestamp = new Date(trade.timestamp || trade.time);

        // Round price to a reasonable precision for grouping (e.g., 2 decimal places for BTC-USDT)
        const priceKey = Math.round(price * 100) / 100;

        if (!volumeMap.has(priceKey)) {
            volumeMap.set(priceKey, { totalVolume: 0, buyVolume: 0, sellVolume: 0, trades: [] });
        }

        const volData = volumeMap.get(priceKey);
        volData.totalVolume += volume;
        if (side === 'buy') {
            volData.buyVolume += volume;
        } else {
            volData.sellVolume += volume;
        }
        volData.trades.push({
            price: price,
            volume: volume,
            side: side,
            timestamp: timestamp
        });

        if (!priceLevels.includes(priceKey)) {
            priceLevels.push(priceKey);
        }
    });

    // Sort price levels for volume profile
    priceLevels.sort((a, b) => a - b);

    // Create volume profile data
    volumeProfileData = priceLevels.map(price => ({
        price: price,
        totalVolume: volumeMap.get(price).totalVolume,
        buyVolume: volumeMap.get(price).buyVolume,
        sellVolume: volumeMap.get(price).sellVolume,
        trades: volumeMap.get(price).trades
    }));

    // Store processed trade markers
    tradeMarkers = tradeHistoryData.map(trade => ({
        x: new Date(trade.timestamp || trade.time),
        y: trade.price,
        volume: Math.abs(trade.quantity || trade.qty || trade.size),
        side: trade.side && trade.side.toUpperCase() === 'SELL' ? 'sell' : 'buy',
        timestamp: new Date(trade.timestamp || trade.time),
        id: `trade_${trade.timestamp || trade.time}_${trade.price}_${Math.random().toString(36).substr(2, 9)}`
    }));

    console.log(`[TRADE_HISTORY] Processed ${volumeProfileData.length} price levels and ${tradeMarkers.length} trade markers`);
}

// Update trade history visualizations on the chart
function updateTradeHistoryVisualizations() {
    const volumeProfileCheckbox = document.getElementById('show-volume-profile-checkbox');
    const tradeMarkersCheckbox = document.getElementById('show-trade-markers-checkbox');

    const showVolumeProfile = volumeProfileCheckbox ? volumeProfileCheckbox.checked : false;
    const showTradeMarkers = tradeMarkersCheckbox ? tradeMarkersCheckbox.checked : false;

    console.log(`[TRADE_HISTORY] Updating visualizations - Volume Profile: ${showVolumeProfile}, Trade Markers: ${showTradeMarkers}`);

    if (window.gd && window.gd.data) {
        console.log('[TRADE_HISTORY] Original traces count:', window.gd.data.length);

        // Remove existing trade-related traces
        const filteredData = window.gd.data.filter(trace =>
            !trace.name || (!trace.name.includes('Volume Profile') && !trace.name.includes('Buy Trades') && !trace.name.includes('Sell Trades'))
        );

        console.log('[TRADE_HISTORY] After filtering traces count:', filteredData.length);

        // Add volume profile if enabled
        if (showVolumeProfile && volumeProfileData.length > 0) {
            const volumeProfileTrace = createVolumeProfileTrace();
            if (volumeProfileTrace && volumeProfileTrace.length > 0) {
                filteredData.push(...volumeProfileTrace); // Spread array of traces
                volumeProfileTraces = volumeProfileTrace;
                console.log('[TRADE_HISTORY] Added', volumeProfileTrace.length, 'volume profile traces');
            }
        }

        // Add trade markers if enabled
        if (showTradeMarkers && tradeMarkers.length > 0) {
            console.log('[TRADE_HISTORY] Creating trade marker traces, tradeMarkers length:', tradeMarkers.length);
            const tradeMarkerTraces = createTradeMarkerTraces();
            console.log('[TRADE_HISTORY] createTradeMarkerTraces returned:', tradeMarkerTraces ? tradeMarkerTraces.length : 'null/undefined', 'traces');
            if (tradeMarkerTraces && tradeMarkerTraces.length > 0) {
                filteredData.push(...tradeMarkerTraces);
                console.log('[TRADE_HISTORY] Added', tradeMarkerTraces.length, 'trade marker traces');
            } else {
                console.log('[TRADE_HISTORY] No trade marker traces to add');
            }
        } else {
            console.log('[TRADE_HISTORY] Trade markers not enabled or no tradeMarkers. showTradeMarkers:', showTradeMarkers, 'tradeMarkers.length:', tradeMarkers.length);
        }

        console.log('[TRADE_HISTORY] Final traces count:', filteredData.length);
        console.log('[TRADE_HISTORY] Trace names:', filteredData.map(t => t.name || 'unnamed'));

        // Update the chart
        Plotly.react(window.gd, filteredData, window.gd.layout);
        console.log('[TRADE_HISTORY] Chart updated with trade history visualizations');
    } else {
        console.warn('[TRADE_HISTORY] Cannot update chart - window.gd or window.gd.data not available');
    }
}

// Create volume profile trace
function createVolumeProfileTrace() {
    if (!volumeProfileData || volumeProfileData.length === 0) {
        console.log('[TRADE_HISTORY] Volume profile data is empty, cannot create trace');
        return null;
    }

    console.log('[TRADE_HISTORY] Creating volume profile trace with', volumeProfileData.length, 'price levels');

    // Get current min volume filter
    const minVolumeSlider = document.getElementById('min-volume-slider');
    const minVolume = minVolumeSlider ? parseFloat(minVolumeSlider.value) || MIN_VOLUME_DEFAULT : MIN_VOLUME_DEFAULT;

    console.log('[TRADE_HISTORY] Min volume filter value:', minVolume, 'type:', typeof minVolume);

    // Debug: Log some volume profile data samples
    console.log('[TRADE_HISTORY] Sample volume profile data (first 3):');
    volumeProfileData.slice(0, 3).forEach((item, index) => {
        console.log(`  [${index}] Price: ${item.price}, Total Volume: ${item.totalVolume}, Type: ${typeof item.totalVolume}`);
    });

    // Check if all volumes are below the filter (problematic case)
    const maxVolumeInData = Math.max(...volumeProfileData.map(level => level.totalVolume));
    const minDataVolume = Math.min(...volumeProfileData.map(level => level.totalVolume));
    console.log('[TRADE_HISTORY] Volume range in data - Min:', minDataVolume, 'Max:', maxVolumeInData, 'Filter:', minVolume);

    // Filter volume profile data by volume
    const filteredData = volumeProfileData.filter(level => {
        const meetsFilter = level.totalVolume >= minVolume;
        if (!meetsFilter) {
            console.log(`[TRADE_HISTORY] Filtered out price level: ${level.price}, volume: ${level.totalVolume} (below min: ${minVolume})`);
        }
        return meetsFilter;
    });

    console.log('[TRADE_HISTORY] Filtered data:', filteredData.length, 'of', volumeProfileData.length, 'price levels passed filter');

    if (filteredData.length === 0) {
        console.log('[TRADE_HISTORY] No volume profile data passed the minimum volume filter of', minVolume);
        return null;
    }

    // Find max volume for scaling the bars
    const maxFilteredVolume = Math.max(...filteredData.map(level => level.totalVolume));
    const maxBarWidth = 0.1; // Increased from 0.05 to 0.1 for better visibility

    console.log('[TRADE_HISTORY] Volume profile bars - max volume:', maxFilteredVolume, 'bar width:', maxBarWidth);

    // Create highly visible volume profile bars as scatter plot lines
    const volumeBars = [];
    const maxVolumeForScaling = Math.max(...filteredData.map(d => d.totalVolume));
    const chartWidth = 100; // Arbitrary width units for visibility

    filteredData.forEach((level, index) => {
        const volumeRatio = level.totalVolume / maxVolumeForScaling;
        const barLength = Math.max(5, volumeRatio * chartWidth); // Min 5 units, scale up

        // Create horizontal line representing the bar
        volumeBars.push({
            x: [0, barLength],           // Bar extends from 0 to volume
            y: [level.price, level.price], // Same price level
            type: 'scatter',
            mode: 'lines+markers',
            name: `Volume @ ${level.price.toFixed(2)}: ${level.totalVolume.toFixed(4)} BTC`,
            line: {
                color: level.buyVolume > level.sellVolume ? 'rgba(0, 255, 0, 0.9)' : 'rgba(255, 0, 0, 0.9)',
                width: Math.max(3, volumeRatio * 8), // Thicker lines for higher volume
            },
            marker: {
                size: 6,
                color: level.buyVolume > level.sellVolume ? 'green' : 'red',
                symbol: 'square'
            },
            hovertemplate:
                `<b>Volume Profile</b><br>` +
                `Price: $${level.price.toFixed(2)}<br>` +
                `Total Volume: ${level.totalVolume.toFixed(4)} BTC<br>` +
                `Buy Volume: ${level.buyVolume.toFixed(4)} BTC<br>` +
                `Sell Volume: ${level.sellVolume.toFixed(4)} BTC<br>` +
                `Trades: ${level.trades.length}<br>` +
                `<extra></extra>`,
            xaxis: 'x3',  // Use third x-axis for overlay
            yaxis: 'y3',  // Use third y-axis for overlay
            showlegend: false
        });
    });

    // Create highly visible volume profile dot markers on main price chart
    // Position them as a vertical line of dots at the right edge of visible data
    const baseTime = new Date(Date.now() + (filteredData.length * 2000)); // Space them out

    const volumeProfileTrace = {
        x: filteredData.map((d, i) => new Date(baseTime.getTime() + (i * 15000))), // Spread dots across time
        y: filteredData.map(d => d.price),
        type: 'scatter',
        mode: 'markers+text',
        name: '📊 VOLUME PROFILE',
        marker: {
            size: filteredData.map(d => {
                const ratio = d.totalVolume / maxFilteredVolume;
                return Math.max(25, Math.min(80, ratio * 60)); // MASSIVE size range
            }),
            color: filteredData.map(d => d.buyVolume > d.sellVolume ? 'limegreen' : 'crimson'),
            symbol: 'circle',
            line: {
                color: 'white',
                width: 4
            },
            opacity: 1.0
        },
        text: filteredData.map(d => {
            const compactVol = (d.totalVolume * 1000).toFixed(1) + 'k';
            return d.buyVolume > d.sellVolume ? '🟢' + compactVol : '🔴' + compactVol;
        }),
        textposition: 'middle right',
        textfont: {
            size: 12,
            color: 'white',
            family: 'Arial Black'
        },
        hovertemplate:
            '<b>💰 VOLUME AT PRICE LEVEL 💰</b><br>' +
            '<b>Price: $%{y:.2f}</b><br>' +
            '<b>Total Volume: %{customdata[0]:.4f} BTC</b><br>' +
            '<b style="color:lime">Buy Volume: %{customdata[1]:.4f} BTC</b><br>' +
            '<b style="color:crimson">Sell Volume: %{customdata[2]:.4f} BTC</b><br>' +
            '<b>Trades: %{customdata[3]}</b><br>' +
            '<extra></extra>',
        customdata: filteredData.map(d => [d.totalVolume, d.buyVolume, d.sellVolume, d.trades.length]),
        xaxis: 'x', // MAIN CHART - should be visible
        yaxis: 'y', // MAIN PRICE AXIS - should be visible
        showlegend: true
    };

    console.log('[TRADE_HISTORY] Created volume profile dots on main chart with', volumeProfileTrace.x.length, 'points');
    return volumeProfileTrace;
}

// Create trade marker traces (buy/sell circles)
function createTradeMarkerTraces() {
    if (!tradeMarkers || tradeMarkers.length === 0) {
        return [];
    }

    // Get current min volume filter
    const minVolumeSlider = document.getElementById('min-volume-slider');
    const minVolume = minVolumeSlider ? parseFloat(minVolumeSlider.value) || MIN_VOLUME_DEFAULT : MIN_VOLUME_DEFAULT;

    console.log(`[TRADE_HISTORY] Creating trade markers - Min volume filter: ${minVolume}`);
    console.log(`[TRADE_HISTORY] Sample trade volumes:`, tradeMarkers.slice(0, 5).map(t => t.volume));

    // Filter trades by minimum volume
    const filteredTrades = tradeMarkers.filter(marker => marker.volume >= minVolume);

    console.log(`[TRADE_HISTORY] Filtered ${filteredTrades.length} trades from ${tradeMarkers.length} total`);

    if (filteredTrades.length === 0) {
        return [];
    }

    // Separate buy and sell trades
    const buyTrades = filteredTrades.filter(marker => marker.side === 'buy');
    const sellTrades = filteredTrades.filter(marker => marker.side === 'sell');

    const traces = [];

    // Create buy trade markers with enhanced visibility
    if (buyTrades.length > 0) {
        const sizes = buyTrades.map(trade => Math.max(12, Math.min(35, trade.volume * 300))); // Larger sizes, better scaling
        console.log('[TRADE_HISTORY] Buy trade marker sizes:', sizes.slice(0, 5));
        console.log('[TRADE_HISTORY] Buy trade first 3 positions:', buyTrades.slice(0, 3).map(t => `(x:${t.x.getTime()}, y:${t.y})`));

        traces.push({
            x: buyTrades.map(trade => trade.x),
            y: buyTrades.map(trade => trade.y),
            type: 'scatter',
            mode: 'markers',
            name: 'Buy Trades',
            marker: {
                size: sizes,
                color: 'rgba(0, 255, 0, 0.9)', // Bright green with high opacity
                symbol: 'circle-open', // Open circle for better visibility
                line: {
                    color: 'green',
                    width: 3
                },
                opacity: 1
            },
            hovertemplate:
                '🟢 BUY: %{y}<br>' +
                'Volume: %{customdata}<br>' +
                'Time: %{x}<br>' +
                '<extra></extra>',
            customdata: buyTrades.map(trade => trade.volume),
            xaxis: 'x',
            yaxis: 'y',
            showlegend: true
        });
    }

    // Create sell trade markers with enhanced visibility
    if (sellTrades.length > 0) {
        const sizes = sellTrades.map(trade => Math.max(12, Math.min(35, trade.volume * 300))); // Larger sizes, better scaling
        console.log('[TRADE_HISTORY] Sell trade marker sizes:', sizes.slice(0, 5));
        console.log('[TRADE_HISTORY] Sell trade first 3 positions:', sellTrades.slice(0, 3).map(t => `(x:${t.x.getTime()}, y:${t.y})`));

        traces.push({
            x: sellTrades.map(trade => trade.x),
            y: sellTrades.map(trade => trade.y),
            type: 'scatter',
            mode: 'markers',
            name: 'Sell Trades',
            marker: {
                size: sizes,
                color: 'rgba(255, 0, 0, 0.9)', // Bright red with high opacity
                symbol: 'diamond-open', // Open diamond for better visibility
                line: {
                    color: 'red',
                    width: 3
                },
                opacity: 1
            },
            hovertemplate:
                '🔴 SELL: %{y}<br>' +
                'Volume: %{customdata}<br>' +
                'Time: %{x}<br>' +
                '<extra></extra>',
            customdata: sellTrades.map(trade => trade.volume),
            xaxis: 'x',
            yaxis: 'y',
            showlegend: true
        });
    }

    return traces;
}

// Calculate marker size based on volume (relative to max volume)
function calculateMarkerSize(volume) {
    if (!tradeMarkers || tradeMarkers.length === 0) return 5;

    const maxVolume = Math.max(...tradeMarkers.map(marker => marker.volume));
    const minSize = 5;
    const maxSize = 25;

    if (maxVolume === 0) return minSize;

    const normalized = volume / maxVolume;
    const size = minSize + (maxSize - minSize) * normalized;

    return Math.max(minSize, Math.min(maxSize, size));
}

// Handle volume profile checkbox toggle
function handleVolumeProfileToggle(event) {
    const isChecked = event.target.checked;

    console.log(`[TRADE_HISTORY] Volume profile toggled: ${isChecked}`);

    // Trade history data comes automatically via WebSocket
    // Just update the visualizations based on current data
    updateTradeHistoryVisualizations();

    // Save settings if function exists
    if (typeof saveSettings === 'function') {
        saveSettings();
    }
}

// Handle trade markers checkbox toggle
function handleTradeMarkersToggle(event) {
    const isChecked = event.target.checked;

    console.log(`[TRADE_HISTORY] Trade markers toggled: ${isChecked}`);

    // Trade history data comes automatically via WebSocket
    // Just update the visualizations based on current data
    updateTradeHistoryVisualizations();

    // Save settings if function exists
    if (typeof saveSettings === 'function') {
        saveSettings();
    }
}

// Handle minimum volume slider change
function handleMinVolumeChange() {
    const minVolumeSlider = document.getElementById('min-volume-slider');
    const minVolumeValue = document.getElementById('min-volume-value');

    if (!minVolumeSlider) return;

    const minVolume = parseFloat(minVolumeSlider.value);

    console.log(`[TRADE_HISTORY] Minimum volume changed to: ${minVolume}`);

    // Update display value
    if (minVolumeValue) {
        minVolumeValue.textContent = minVolume.toLocaleString();
    }

    // Update visualizations
    updateTradeHistoryVisualizations();

    // Save settings if function exists
    if (typeof saveSettings === 'function') {
        saveSettings();
    }
}

// Clear existing trade history visualizations
function clearTradeHistoryVisualizations() {
    if (window.gd && window.gd.data) {
        // Remove volume profile and trade marker traces
        const filteredData = window.gd.data.filter(trace =>
            !trace.name || (!trace.name.includes('Volume Profile') && !trace.name.includes('Buy Trades') && !trace.name.includes('Sell Trades'))
        );

        if (filteredData.length !== window.gd.data.length) {
            Plotly.react(window.gd, filteredData, window.gd.layout);
            console.log('[TRADE_HISTORY] Cleared existing trade history visualizations');
        }
    }

    volumeProfileTraces = [];
    tradeMarkers = [];
}

// Clear trade history data
function clearTradeHistoryData() {
    tradeHistoryData = [];
    volumeProfileData = [];
    clearTradeHistoryVisualizations();
    console.log('[TRADE_HISTORY] Cleared all trade history data');
}

// Update trade history data from WebSocket message
function updateTradeHistoryFromWebSocket(tradeData, symbol = null) {
    if (!tradeData || !Array.isArray(tradeData) || tradeData.length === 0) {
        console.log('[TRADE_HISTORY] No trade data received from WebSocket');
        return;
    }

    console.log(`[TRADE_HISTORY] Updating trade history from WebSocket: ${tradeData.length} trades`);

    // Update the internal trade data
    tradeHistoryData = tradeData;

    // Process the new data
    processTradeHistoryData();

    // Update visualizations if enabled
    updateTradeHistoryVisualizations();

    console.log(`[TRADE_HISTORY] Trade history updated from WebSocket for ${symbol || 'unknown symbol'}`);
}

// Export functions for global access
window.initializeTradeHistory = initializeTradeHistory;
window.fetchTradeHistoryForCurrentSymbol = fetchTradeHistoryForCurrentSymbol;
window.updateTradeHistoryVisualizations = updateTradeHistoryVisualizations;
window.clearTradeHistoryData = clearTradeHistoryData;
window.updateTradeHistoryFromWebSocket = updateTradeHistoryFromWebSocket;
