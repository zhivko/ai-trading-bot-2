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

    // Setup event listeners for trade visualization controls
    setupTradeHistoryControls();

    // Trade history data will come automatically via WebSocket when chart connects
    // No manual fetching needed - data flows through WebSocket messages
}

// Setup event listeners for trade history controls
function setupTradeHistoryControls() {

    // Get DOM elements
    const volumeProfileCheckbox = document.getElementById('show-volume-profile-checkbox');
    const tradeMarkersCheckbox = document.getElementById('show-trade-markers-checkbox');
    const minVolumeSlider = document.getElementById('min-volume-slider');
    const minVolumeValue = document.getElementById('min-volume-value');


    // Trade visualization checkboxes
    if (volumeProfileCheckbox) {
        volumeProfileCheckbox.addEventListener('change', handleVolumeProfileToggle);
    }
    if (tradeMarkersCheckbox) {
        tradeMarkersCheckbox.addEventListener('change', handleTradeMarkersToggle);
    }

    // Trade filter slider
    if (minVolumeSlider) {
        minVolumeSlider.addEventListener('input', handleMinVolumeChange);
    }

    // Trade history data will come automatically via WebSocket
    // No need to manually fetch on symbol change - WebSocket broadcasts to all clients

}

// Fetch trade history data for the current symbol
async function fetchTradeHistoryForCurrentSymbol(symbol = null, limit = 20) {
    const currentSymbol = symbol || (window.symbolSelect ? window.symbolSelect.value : null);
    if (!currentSymbol) {
        console.warn('[TRADE_HISTORY] No symbol available for trade history fetch');
        return;
    }


    try {
        const response = await fetch(`/trade-history?symbol=${currentSymbol}&limit=${limit}`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const result = await response.json();
        if (result.status === 'success') {
            tradeHistoryData = result.data || [];

            // Process data for volume profile and trade markers
            processTradeHistoryData();

            // Update visualizations if enabled
            updateTradeHistoryVisualizations();
        } else if (Array.isArray(result)) {
            // Handle direct array response (fallback to old format)
            tradeHistoryData = result;

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
        return;
    }


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

}

// Update trade history visualizations on the chart
function updateTradeHistoryVisualizations() {
    const volumeProfileCheckbox = document.getElementById('show-volume-profile-checkbox');
    const tradeMarkersCheckbox = document.getElementById('show-trade-markers-checkbox');

    const showVolumeProfile = volumeProfileCheckbox ? volumeProfileCheckbox.checked : false;
    const showTradeMarkers = tradeMarkersCheckbox ? tradeMarkersCheckbox.checked : false;


    if (window.gd && window.gd.data) {

        // Remove existing trade-related traces
        const filteredData = window.gd.data.filter(trace =>
            !trace.name || (!trace.name.includes('Volume Profile') && !trace.name.includes('Buy Trades') && !trace.name.includes('Sell Trades'))
        );


        // Add volume profile if enabled
        if (showVolumeProfile && volumeProfileData.length > 0) {
            const volumeProfileTrace = createVolumeProfileTrace();
            if (volumeProfileTrace && volumeProfileTrace.length > 0) {
                filteredData.push(...volumeProfileTrace); // Spread array of traces
                volumeProfileTraces = volumeProfileTrace;
            }
        }

        // Add trade markers if enabled
        if (showTradeMarkers && tradeMarkers.length > 0) {
            const tradeMarkerTraces = createTradeMarkerTraces();
            if (tradeMarkerTraces && tradeMarkerTraces.length > 0) {
                filteredData.push(...tradeMarkerTraces);
            } else {
            }
        } else {
        }


        // Update the chart
        Plotly.react(window.gd, filteredData, window.gd.layout);
    } else {
        console.warn('[TRADE_HISTORY] Cannot update chart - window.gd or window.gd.data not available');
    }
}

// Create volume profile trace
function createVolumeProfileTrace() {
    if (!volumeProfileData || volumeProfileData.length === 0) {
        return null;
    }


    // Get current min volume filter
    const minVolumeSlider = document.getElementById('min-volume-slider');
    const minVolume = minVolumeSlider ? parseFloat(minVolumeSlider.value) || MIN_VOLUME_DEFAULT : MIN_VOLUME_DEFAULT;


    // Debug: Log some volume profile data samples
    volumeProfileData.slice(0, 3).forEach((item, index) => {
    });

    // Check if all volumes are below the filter (problematic case)
    const maxVolumeInData = Math.max(...volumeProfileData.map(level => level.totalVolume));
    const minDataVolume = Math.min(...volumeProfileData.map(level => level.totalVolume));

    // Filter volume profile data by volume
    const filteredData = volumeProfileData.filter(level => {
        const meetsFilter = level.totalVolume >= minVolume;
        if (!meetsFilter) {
        }
        return meetsFilter;
    });


    if (filteredData.length === 0) {
        return null;
    }

    // Find max volume for scaling the bars
    const maxFilteredVolume = Math.max(...filteredData.map(level => level.totalVolume));
    const maxBarWidth = 0.1; // Increased from 0.05 to 0.1 for better visibility


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


    // Filter trades by minimum volume
    const filteredTrades = tradeMarkers.filter(marker => marker.volume >= minVolume);


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


    // Update volume profile visualization immediately when checkbox changes
    // This will add/remove the horizontal bars overlay on the price chart
    updateVolumeProfileVisualization();

    // Also update other trade history visualizations to maintain consistency
    updateTradeHistoryVisualizations();

    // Save settings if function exists
    if (typeof saveSettings === 'function') {
        saveSettings();
    }
}

// Handle trade markers checkbox toggle
function handleTradeMarkersToggle(event) {
    const isChecked = event.target.checked;


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
}

// Memory management for volume profile traces
function cleanupOldVolumeProfileTraces() {

    // Clear the global volume profile data to prevent memory leaks
    window.volumeProfileData = [];

    // Remove volume profile traces from chart if they exist
    if (window.gd && window.gd.data) {
        const originalCount = window.gd.data.length;
        const filteredData = window.gd.data.filter(trace =>
            !trace.name || !trace.name.includes('Volume Profile')
        );

        if (filteredData.length < originalCount) {
            // Only update chart if traces were actually removed
            Plotly.react(window.gd, filteredData, window.gd.layout);
        }
    }

    // Clear volume profile layout axes to free up resources
    if (window.gd && window.gd.layout) {
        delete window.gd.layout.yaxis2;
        delete window.gd.layout.xaxis2;
    }

    volumeProfileTraces = [];

}

// Periodic memory cleanup - clear volume profile data after extended periods
function scheduleVolumeProfileCleanup(cleanupIntervalMinutes = 30) {
    const cleanupInterval = cleanupIntervalMinutes * 60 * 1000; // Convert to milliseconds


    // Clear any existing cleanup timer
    if (window.volumeProfileCleanupTimer) {
        clearInterval(window.volumeProfileCleanupTimer);
    }

    // Schedule periodic cleanup
    window.volumeProfileCleanupTimer = setInterval(() => {
        cleanupOldVolumeProfileTraces();

        // Optional: Force garbage collection if available (Chrome/Edge)
        if (window.gc) {
            window.gc();
        }
    }, cleanupInterval);

}

// Cleanup on symbol/resolution changes to prevent stale data
function handleSymbolResolutionChange() {

    // Delay cleanup slightly to allow new data to arrive
    setTimeout(() => {
        cleanupOldVolumeProfileTraces();

        // Clear the cleanup timer when changing symbols to prevent accumulation
        if (window.volumeProfileCleanupTimer) {
            clearInterval(window.volumeProfileCleanupTimer);
            window.volumeProfileCleanupTimer = null;
        }
    }, 1000); // 1 second delay
}

// Update volume profile data from WebSocket message
function updateVolumeProfileFromWebSocket(volumeProfileData, symbol = null) {
    if (!volumeProfileData || !Array.isArray(volumeProfileData) || volumeProfileData.length === 0) {
        return;
    }


    // Check if we have existing volume profile data for merging
    if (window.volumeProfileData && Array.isArray(window.volumeProfileData) && window.volumeProfileData.length > 0) {
        // Merge new data with existing data
        window.volumeProfileData = mergeVolumeProfileData(window.volumeProfileData, volumeProfileData);
    } else {
        // No existing data, use new data directly
        window.volumeProfileData = volumeProfileData;
    }

    // Synchronize the scaled volume bars on chart immediately
    updateVolumeProfileVisualization();

}

// Merge volume profile data by combining data at same price levels
function mergeVolumeProfileData(existingData, newData) {
    if (!existingData || !Array.isArray(existingData)) return newData;
    if (!newData || !Array.isArray(newData)) return existingData;


    // Create a map of existing data by price for quick lookup
    const mergedMap = new Map();

    // Add existing data to map
    existingData.forEach(level => {
        if (level && typeof level.price === 'number') {
            mergedMap.set(level.price, {
                price: level.price,
                totalVolume: level.totalVolume || 0,
                buyVolume: level.buyVolume || 0,
                sellVolume: level.sellVolume || 0,
                trades: level.trades || []
            });
        }
    });

    // Merge new data
    let mergedLevels = 0;
    let addedLevels = 0;

    newData.forEach(newLevel => {
        if (!newLevel || typeof newLevel.price !== 'number') return;

        const existingLevel = mergedMap.get(newLevel.price);

        if (existingLevel) {
            // Merge data at same price level - add to existing volumes
            existingLevel.totalVolume = (existingLevel.totalVolume || 0) + (newLevel.totalVolume || 0);
            existingLevel.buyVolume = (existingLevel.buyVolume || 0) + (newLevel.buyVolume || 0);
            existingLevel.sellVolume = (existingLevel.sellVolume || 0) + (newLevel.sellVolume || 0);

            // Combine trades arrays
            if (newLevel.trades && Array.isArray(newLevel.trades)) {
                existingLevel.trades = (existingLevel.trades || []).concat(newLevel.trades);
            }

            mergedLevels++;
        } else {
            // New price level, add it
            mergedMap.set(newLevel.price, {
                price: newLevel.price,
                totalVolume: newLevel.totalVolume || 0,
                buyVolume: newLevel.buyVolume || 0,
                sellVolume: newLevel.sellVolume || 0,
                trades: newLevel.trades || []
            });
            addedLevels++;
        }
    });

    // Convert map back to array and sort by price
    const mergedArray = Array.from(mergedMap.values()).sort((a, b) => a.price - b.price);


    // Log a sample of the merged data for verification
    if (mergedArray.length > 0) {
        mergedArray.slice(0, 3).forEach((level, idx) => {
        });
    }

    return mergedArray;
}

// Dedicated volume profile visualization that adds horizontal volume bars to the price chart
function updateVolumeProfileVisualization() {
    if (!window.volumeProfileData || window.volumeProfileData.length === 0) {
        return;
    }

    if (!window.gd || !window.gd.data) {
        return;
    }


    // Remove existing volume profile traces
    const filteredData = window.gd.data.filter(trace =>
        !trace.name || !trace.name.includes('Volume Profile')
    );

    // Check if volume profile is enabled
    const volumeProfileCheckbox = document.getElementById('show-volume-profile-checkbox');
    const showVolumeProfile = volumeProfileCheckbox ? volumeProfileCheckbox.checked : false;

    if (!showVolumeProfile) {
        // If not enabled, just update without adding the trace
        if (filteredData.length !== window.gd.data.length) {
            Plotly.react(window.gd, filteredData, window.gd.layout);
        }
        return;
    }

    // Create the volume profile horizontal bars
    const volumeProfileTrace = createVolumeProfileBars();

    if (volumeProfileTrace) {
        filteredData.push(volumeProfileTrace);

        // Ensure layout has proper y2 axis for volume profile
        const layout = { ...window.gd.layout };

        // Get current price range to position volume bars
        const yRange = layout.yaxis && layout.yaxis.range ? layout.yaxis.range : [0, 100];
        const priceRange = yRange[1] - yRange[0];
        const rightEdgePosition = yRange[1] + (priceRange * 0.05); // Position 5% above price max

        // Configure y2 axis for volume bars (right side, overlaid on price chart)
        layout.yaxis2 = {
            title: '',
            range: [yRange[0], rightEdgePosition],
            autorange: false,
            fixedrange: false,
            showticklabels: false,
            showgrid: false,
            side: 'right',
            overlaying: 'y',  // Overlay on main price y-axis
            layer: 'above'
        };

        // Configure x2 axis for volume bars
        layout.xaxis2 = {
            showticklabels: false,
            showgrid: false,
            overlaying: 'x'
        };

        Plotly.react(window.gd, filteredData, layout);

    } else {
        console.warn('[VOLUME_PROFILE] Failed to create volume profile bars');
        if (filteredData.length !== window.gd.data.length) {
            Plotly.react(window.gd, filteredData, window.gd.layout);
        }
    }
}

// Create horizontal bars for volume profile visualization
function createVolumeProfileBars() {
    if (!window.volumeProfileData || !Array.isArray(window.volumeProfileData)) {
        return null;
    }

    const data = window.volumeProfileData;
    if (data.length === 0) return null;


    // Find max volume for scaling
    const maxVolume = Math.max(...data.map(level => Math.max(level.totalVolume || 0, level.buyVolume || 0, level.sellVolume || 0)));

    if (maxVolume === 0) {
        console.warn('[VOLUME_PROFILE] No volume data found in volume profile');
        return null;
    }

    // Prepare x and y coordinates for horizontal bars
    const xCoords = [];
    const yCoords = [];
    const colors = [];
    const widths = [];
    const hoverText = [];
    const customData = [];

    // Bar length scaling (how far bars extend to the right)
    const maxBarLength = 50; // Relative units for bar length

    data.forEach(level => {
        const price = level.price;
        const totalVol = level.totalVolume || 0;
        const buyVol = level.buyVolume || 0;
        const sellVol = level.sellVolume || 0;
        const trades = level.trades || [];

        if (totalVol === 0) return; // Skip empty levels

        // Calculate bar lengths for buy and sell volumes
        const buyLength = buyVol > 0 ? (buyVol / maxVolume) * maxBarLength : 0;
        const sellLength = sellVol > 0 ? (sellVol / maxVolume) * maxBarLength : 0;

        // Increased line width for wider, more visible bars
        const lineWidth = Math.max(8, Math.min(20, (totalVol / maxVolume) * 16)); // Scale from 8 to 20 based on volume

        // Create horizontal line segments for each volume component
        if (buyLength > 0) {
            // Buy volume bar (green, extending to the right from price level)
            xCoords.push(0, buyLength);
            yCoords.push(price, price);
            colors.push('rgba(0, 255, 0, 0.8)', 'rgba(0, 255, 0, 0.8)');
            widths.push(lineWidth, lineWidth); // Increased line width
            hoverText.push(
                `Buy Volume: ${totalVol.toFixed(4)} @ $${price.toFixed(2)}`,
                `Buy Volume: ${totalVol.toFixed(4)} @ $${price.toFixed(2)}`
            );
            customData.push(level, level);
        }

        if (sellLength > 0) {
            // Sell volume bar (red, extending to the right from price level, offset if buy exists)
            const xOffset = buyLength; // Start after buy bar
            xCoords.push(xOffset, xOffset + sellLength);
            yCoords.push(price, price);
            colors.push('rgba(255, 0, 0, 0.8)', 'rgba(255, 0, 0, 0.8)');
            widths.push(lineWidth, lineWidth); // Increased line width
            hoverText.push(
                `Sell Volume: ${totalVol.toFixed(4)} @ $${price.toFixed(2)}`,
                `Sell Volume: ${totalVol.toFixed(4)} @ $${price.toFixed(2)}`
            );
            customData.push(level, level);
        }
    });

    if (xCoords.length === 0) {
        console.warn('[VOLUME_PROFILE] No valid volume data to create bars');
        return null;
    }

    // Create the volume profile bars trace
    const volumeProfileBars = {
        x: xCoords,
        y: yCoords,
        type: 'scatter',
        mode: 'lines',
        name: 'Volume Profile',
        line: {
            color: colors,
            width: widths
        },
        hovertemplate: '%{text}<br>Volume: %{customdata.totalVolume:.4f}<br>Buys: %{customdata.buyVolume:.4f}<br>Sells: %{customdata.sellVolume:.4f}<extra></extra>',
        hovertext: hoverText,
        customdata: customData,
        xaxis: 'x2',  // Use secondary x-axis (overlay)
        yaxis: 'y2',  // Use secondary y-axis (overlay on price)
        showlegend: true,
        hoverlabel: {
            bgcolor: 'rgba(255, 255, 255, 0.9)',
            bordercolor: 'black',
            font: { color: 'black', size: 12 }
        }
    };

    return volumeProfileBars;
}

// Update trade history data from WebSocket message (legacy or fallback)
function updateTradeHistoryFromWebSocket(tradeData, symbol = null) {
    if (!tradeData || !Array.isArray(tradeData) || tradeData.length === 0) {
        return;
    }


    // Update the internal trade data
    tradeHistoryData = tradeData;

    // Process the new data to generate volume profile
    processTradeHistoryData();

    // Update visualizations if enabled
    updateTradeHistoryVisualizations();

}

// Export functions for global access
window.initializeTradeHistory = initializeTradeHistory;
window.fetchTradeHistoryForCurrentSymbol = fetchTradeHistoryForCurrentSymbol;
window.updateTradeHistoryVisualizations = updateTradeHistoryVisualizations;
window.clearTradeHistoryData = clearTradeHistoryData;
window.updateTradeHistoryFromWebSocket = updateTradeHistoryFromWebSocket;
window.updateVolumeProfileFromWebSocket = updateVolumeProfileFromWebSocket;
