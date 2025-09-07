document.addEventListener('DOMContentLoaded', async () => {
    // Make DOM elements globally available (or pass them as needed)
    window.symbolSelect = document.getElementById('symbol-select');
    window.resolutionSelect = document.getElementById('resolution-select');
    window.rangeSelect = document.getElementById('range-select');
    window.chartDiv = document.getElementById('chart');
    window.eventOutput = document.getElementById('event-output');
    window.xAxisMinDisplay = document.getElementById('x-axis-min-display');
    window.xAxisMaxDisplay = document.getElementById('x-axis-max-display');
    window.yAxisMinDisplay = document.getElementById('y-axis-min-display');
    window.yAxisMaxDisplay = document.getElementById('y-axis-max-display');
    window.selectedShapeInfoDiv = document.getElementById('selected-shape-info');
    window.deleteShapeBtn = document.getElementById('delete-shape-btn');
    window.editShapeBtn = document.getElementById('edit-shape-btn');
    window.deleteAllShapesBtn = document.getElementById('delete-all-shapes-btn');
    window.cursorTimeDisplay = document.getElementById('cursor-time-display');
    window.cursorPriceDisplay = document.getElementById('cursor-price-display');
    window.startReplayButton = document.getElementById('start-replay');
    window.stopReplayButton = document.getElementById('stop-replay');
    window.aiSuggestionButton = document.getElementById('ai-suggestion-btn');
    window.aiSuggestionTextarea = document.getElementById('ai-suggestion');
    window.useLocalOllamaCheckbox = document.getElementById('use-local-ollama-checkbox');
    window.localOllamaModelDiv = document.getElementById('local-ollama-model-selection-div');
    window.localOllamaModelSelect = document.getElementById('local-ollama-model-select');

    // Initialize debounced functions
    window.debouncedUpdateShapeVisuals = debounce(updateShapeVisuals, VISUAL_UPDATE_DEBOUNCE_DELAY); // VISUAL_UPDATE_DEBOUNCE_DELAY from config.js
    window.debouncedUpdateCrosshair = debounce(updateOrAddCrosshairVLine, 100); // updateOrAddCrosshairVLine from chartInteractions.js

    // Bar limit configuration
    const MAX_BARS = 500;

    // Resolution to seconds mapping
    const RESOLUTION_SECONDS = {
        '1m': 60,
        '5m': 300,
        '1h': 3600,
        '1d': 86400,
        '1w': 604800
    };

    // Range to seconds mapping
    const RANGE_SECONDS = {
        '1h': 3600,
        '8h': 8 * 3600,
        '24h': 24 * 3600,
        '3d': 3 * 24 * 3600,
        '7d': 7 * 24 * 3600,
        '30d': 30 * 24 * 3600,
        '3m': 90 * 24 * 3600,  // 3 months approx
        '6m': 180 * 24 * 3600, // 6 months approx
        '1y': 365 * 24 * 3600, // 1 year approx
        '3y': 3 * 365 * 24 * 3600 // 3 years approx
    };

    // Function to calculate number of bars for given time range and resolution
    function calculateBars(timeRangeSeconds, resolution) {
        const resolutionSeconds = RESOLUTION_SECONDS[resolution];
        if (!resolutionSeconds) {
            console.warn(`Unknown resolution: ${resolution}`);
            return 0;
        }
        return Math.ceil(timeRangeSeconds / resolutionSeconds);
    }

    // Function to adjust time range to limit bars to MAX_BARS
    function adjustTimeRangeForMaxBars(fromTs, toTs, resolution) {
        const timeRangeSeconds = (toTs - fromTs) / 1000; // Convert to seconds
        const bars = calculateBars(timeRangeSeconds, resolution);

        if (bars <= MAX_BARS) {
            return { fromTs, toTs, bars };
        }

        // Calculate new fromTs to get exactly MAX_BARS
        const resolutionSeconds = RESOLUTION_SECONDS[resolution];
        const newTimeRangeSeconds = MAX_BARS * resolutionSeconds;
        const newFromTs = toTs - (newTimeRangeSeconds * 1000); // Convert back to milliseconds

        console.log(`Adjusting time range: original bars=${bars}, new bars=${MAX_BARS}, from ${new Date(fromTs).toISOString()} to ${new Date(newFromTs).toISOString()}`);

        return { fromTs: newFromTs, toTs, bars: MAX_BARS };
    }

    // 🔧 TIMESTAMP SYNCHRONIZATION HELPER FUNCTION
    window.getSynchronizedTimestamps = function(fromTs, toTs) {
        // Convert to ISO timestamp strings for WebSocket
        let wsFromTs = fromTs;
        let wsToTs = toTs;

        // If timestamps are in milliseconds (values > 1e12), convert to ISO strings
        if (fromTs > 1e12) {
            wsFromTs = new Date(fromTs).toISOString();
        }
        if (toTs > 1e12) {
            wsToTs = new Date(toTs).toISOString();
        }

        // If we have saved X-axis range from settings, use it to ensure consistency
        if (window.currentXAxisRange && window.currentXAxisRange.length === 2) {
            wsFromTs = new Date(window.currentXAxisRange[0]).toISOString();
            wsToTs = new Date(window.currentXAxisRange[1]).toISOString();
            console.log(`🔧 TIMESTAMP SYNC: Using saved X-axis range for consistency:`, {
                savedRange: window.currentXAxisRange,
                wsFromTs: wsFromTs,
                wsToTs: wsToTs
            });
        }

        return { fromTs: wsFromTs, toTs: wsToTs };
    };

    console.log('[DEBUG] Starting Plotly chart initialization');

    // Initialize Plotly chart (empty initially)
    const initialLayout = {}; // Basic layout - full layout configuration handled in combinedData.js
    console.log('[DEBUG] Initial layout:', initialLayout);

    Plotly.newPlot('chart', [], initialLayout, config).then(function(gd) { // layout & config from config.js
        console.log('[DEBUG] Plotly.newPlot completed successfully, gd:', gd);
        window.gd = gd; // Make Plotly graph div object global


        // Ensure dragmode is set to 'pan' for panning detection
        console.log('[DEBUG] Setting initial dragmode to pan for panning detection');
        Plotly.relayout(gd, { dragmode: 'pan' }).then(() => {
            console.log('[DEBUG] Dragmode set to pan successfully');
        }).catch(err => {
            console.error('[DEBUG] Failed to set dragmode:', err);
        });

        console.log('[DEBUG] About to call initializePlotlyEventHandlers');
        // Initialize Plotly specific event handlers after chart is ready
        initializePlotlyEventHandlers(gd); // From plotlyEventHandlers.js
        console.log('[DEBUG] initializePlotlyEventHandlers completed');

        // Ensure mobile hover is disabled after chart creation
        disableMobileHover(gd);
        forceHideHoverElements(); // Force hide hover elements via CSS

        console.log('[DEBUG] Chart initialization completed');
    
    }).catch(err => {
        console.error('[DEBUG] Plotly initialization error:', err);
        console.error('Full error details:', err);
    });
    // General UI event listeners
    window.symbolSelect.addEventListener('change', async () => {
        window.currentXAxisRange = null; window.currentYAxisRange = null;
        window.xAxisMinDisplay.textContent = 'Auto'; window.xAxisMaxDisplay.textContent = 'Auto';
        window.yAxisMinDisplay.textContent = 'Auto'; window.yAxisMaxDisplay.textContent = 'Auto';
        window.activeShapeForPotentialDeletion = null;

        const selectedSymbol = window.symbolSelect.value;
        const currentUrlSymbol = window.location.pathname.substring(1).toUpperCase() || null;

        // Skip if this is the same symbol as currently loaded
        if (selectedSymbol === currentUrlSymbol) {
            console.log(`[main.js] Symbol ${selectedSymbol} is already loaded, skipping change`);
            setLastSelectedSymbol(selectedSymbol);
            await loadSettings(selectedSymbol);
            return;
        }

        if (window.isProgrammaticallySettingSymbol) {
            console.log("Symbol change was triggered programmatically. Skipping saveSettings() and loadSettings().");
            return;
        }

        console.log(`[main.js] Symbol changed from ${currentUrlSymbol} to ${selectedSymbol}. Performing seamless switch.`);

        // Clear the entire chart before switching symbols
        if (window.gd) {
            console.log("[main.js] Clearing chart data for symbol switch");
            console.log("[CHART_UPDATE] main.js symbol switch - clearing chart at", new Date().toISOString());
            removeRealtimePriceLine(window.gd);
            // Clear all chart data and reset to empty state
            Plotly.react(window.gd, [], window.gd.layout || {});
            console.log("[CHART_UPDATE] main.js symbol switch - chart cleared, ready for new data");
        }

        // Close existing WebSocket connection
        if (window.combinedWebSocket) {
            console.log("[main.js] Closing existing WebSocket connection for symbol switch");
            closeCombinedWebSocket("Symbol changed - switching to new symbol");
        }

        // Update URL without full page reload for better UX
        const newUrl = `/${selectedSymbol}`;
        window.history.pushState({ symbol: selectedSymbol }, '', newUrl);
        console.log(`[main.js] Updated URL to: ${newUrl} (no page reload)`);

        // Clear any pending timeouts
        if (window.historicalDataTimeout) {
            clearTimeout(window.historicalDataTimeout);
            window.historicalDataTimeout = null;
        }

        // Reset WebSocket state
        window.combinedSymbol = '';
        window.combinedIndicators = [];
        window.combinedResolution = '1h';
        window.combinedFromTs = null;
        window.combinedToTs = null;
        window.accumulatedHistoricalData = [];
        window.isAccumulatingHistorical = false;
        window.historicalDataSymbol = '';

        // Update selected shape info
        updateSelectedShapeInfoPanel(null);

        // Save the new symbol selection
        setLastSelectedSymbol(selectedSymbol);

        // Load settings for the new symbol SYNCHRONOUSLY
        console.log(`[main.js] Loading settings for ${selectedSymbol}...`);
        await loadSettings(selectedSymbol);
        console.log(`[main.js] Settings loaded successfully for ${selectedSymbol}`);

        // Establish new WebSocket connection for the new symbol AFTER settings are loaded
        console.log(`[main.js] Establishing new WebSocket connection for ${selectedSymbol}`);

        // Calculate time range for new symbol
        // Use current time for range calculations
        const currentTime = new Date().getTime(); // Use current time
        const fromTs = Math.floor((currentTime - 30 * 86400 * 1000) / 1000); // 30 days before current time
        const toTs = Math.floor((currentTime + 30 * 86400 * 1000) / 1000); // 30 days after current time

        console.log('[TIMESTAMP DEBUG] Initial time range calculation (using current time):', {
            currentTime: currentTime,
            currentDate: new Date(currentTime).toISOString(),
            fromTs: fromTs,
            toTs: toTs,
            fromTsDate: new Date(fromTs * 1000).toISOString(),
            toTsDate: new Date(toTs * 1000).toISOString(),
            timezoneOffset: new Date().getTimezoneOffset(),
            timezoneOffsetMinutes: new Date().getTimezoneOffset()
        });

        // Now get the indicator values AFTER settings are loaded
        const activeIndicators = Array.from(document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
        const resolution = window.resolutionSelect.value;
        console.log(`[main.js] WebSocket setup - indicators: ${activeIndicators}, resolution: ${resolution}`);

        // 🔧 FIX TIMESTAMP SYNCHRONIZATION: Use the same timestamp source for both settings and WebSocket
        // If we have saved X-axis range from settings, use it for WebSocket too
        let wsFromTs = fromTs;
        let wsToTs = toTs;

        console.log(`[main.js] 🔍 DEBUG TIMESTAMP SYNC: Checking currentXAxisRange before WebSocket setup`);
        console.log(`[main.js] 🔍 DEBUG TIMESTAMP SYNC: window.currentXAxisRange:`, window.currentXAxisRange);
        console.log(`[main.js] 🔍 DEBUG TIMESTAMP SYNC: window.currentXAxisRange type:`, typeof window.currentXAxisRange);
        console.log(`[main.js] 🔍 DEBUG TIMESTAMP SYNC: window.currentXAxisRange length:`, window.currentXAxisRange ? window.currentXAxisRange.length : 'undefined');

        if (window.currentXAxisRange && Array.isArray(window.currentXAxisRange) && window.currentXAxisRange.length === 2) {
            // Convert saved milliseconds to ISO timestamp strings for WebSocket
            wsFromTs = new Date(window.currentXAxisRange[0]).toISOString();
            wsToTs = new Date(window.currentXAxisRange[1]).toISOString();
            console.log(`[main.js] ✅ TIMESTAMP SYNC: Using saved X-axis range for WebSocket:`, {
                savedRange: window.currentXAxisRange,
                wsFromTs: wsFromTs,
                wsToTs: wsToTs
            });
        } else {
            console.log(`[main.js] ⚠️ TIMESTAMP SYNC: No valid currentXAxisRange found, using calculated time range for WebSocket:`, {
                wsFromTs: wsFromTs,
                wsToTs: wsToTs,
                currentXAxisRangeStatus: window.currentXAxisRange ? 'exists but invalid' : 'null/undefined'
            });
        }

        setupCombinedWebSocket(selectedSymbol, activeIndicators, resolution, wsFromTs, wsToTs);

    }); // Replaced .onchange with addEventListener('change',...)
    window.resolutionSelect.addEventListener('change', () => {
        // Check if this change was triggered programmatically (from settings load)
        if (window.isProgrammaticallySettingResolution) {
            console.log("[main.js] Resolution change was triggered programmatically (from settings load). Skipping user modification flag.");
            // Still need to update WebSocket for new data stream
        } else {
            // Mark that user has modified resolution
            window.hasUserModifiedResolution = true;
            console.log("[main.js] User manually changed resolution. Marking as modified.");
            // Note: Resolution settings are saved in applyAutoscale() when axis ranges change
        }

        const newResolution = window.resolutionSelect.value;
        console.log(`[main.js] Resolution changed to ${newResolution}`);

        // Get current time range or use default
        let currentFromTs, currentToTs;
        const currentTime = new Date().getTime();

        if (window.currentXAxisRange && window.currentXAxisRange.length === 2) {
            currentFromTs = window.currentXAxisRange[0];
            currentToTs = window.currentXAxisRange[1];
        } else {
            // Use default 30-day range
            currentFromTs = currentTime - 30 * 86400 * 1000;
            currentToTs = currentTime;
        }

        // Calculate bars for current time range with new resolution
        const timeRangeSeconds = (currentToTs - currentFromTs) / 1000;
        const estimatedBars = calculateBars(timeRangeSeconds, newResolution);

        console.log(`[main.js] Estimated bars with new resolution ${newResolution}: ${estimatedBars}`);

        // Adjust time range if bars exceed limit
        let adjustedFromTs = currentFromTs;
        let adjustedToTs = currentToTs;

        if (estimatedBars > MAX_BARS) {
            const adjusted = adjustTimeRangeForMaxBars(currentFromTs, currentToTs, newResolution);
            adjustedFromTs = adjusted.fromTs;
            adjustedToTs = adjusted.toTs;
            console.log(`[main.js] Adjusted time range for resolution change: bars limited to ${MAX_BARS}`);
        }

        // Update current axis range
        window.currentXAxisRange = [adjustedFromTs, adjustedToTs];
        window.xAxisMinDisplay.textContent = `${new Date(adjustedFromTs).toISOString()}`;
        window.xAxisMaxDisplay.textContent = `${new Date(adjustedToTs).toISOString()}`;

        window.currentYAxisRange = null; // Reset Y-axis range for new data
        window.yAxisMinDisplay.textContent = 'Auto';
        window.yAxisMaxDisplay.textContent = 'Auto';
        window.activeShapeForPotentialDeletion = null;
        updateSelectedShapeInfoPanel(null);
        console.log("[main.js] Resolution changed. Clearing ranges, deselecting shape. Triggering chart update.");

        // Clear the entire chart before changing resolution
        if (window.gd) {
            console.log("[main.js] Clearing chart data for resolution change");
            console.log("[CHART_UPDATE] main.js resolution change - clearing chart at", new Date().toISOString());
            removeRealtimePriceLine(window.gd);
            // Clear all chart data and reset to empty state
            Plotly.react(window.gd, [], window.gd.layout || {});
            console.log("[CHART_UPDATE] main.js resolution change - chart cleared, ready for new data");
        }

        // Update WebSocket with new resolution and adjusted time range
        const symbol = window.symbolSelect.value;
        const activeIndicators = Array.from(document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
        if (symbol && newResolution) {
            console.log(`[main.js] Resolution changed to ${newResolution}, updating WebSocket config with adjusted time range`);
            updateCombinedResolution(newResolution);

            // Convert to seconds for WebSocket
            const wsFromTs = Math.floor(adjustedFromTs / 1000);
            const wsToTs = Math.floor(adjustedToTs / 1000);

            // If WebSocket is open, send new config, otherwise establish new connection
            if (window.combinedWebSocket && window.combinedWebSocket.readyState === WebSocket.OPEN) {
                setupCombinedWebSocket(symbol, activeIndicators, newResolution, wsFromTs, wsToTs);
            } else {
                delay(100).then(() => {
                    setupCombinedWebSocket(symbol, activeIndicators, newResolution, wsFromTs, wsToTs);
                });
            }
        }
    }); // Replaced .onchange with addEventListener('change',...)
    window.rangeSelect.addEventListener('change', () => {
        // Check if this change was triggered programmatically (from settings load)
        if (window.isProgrammaticallySettingRange) {
            console.log("[main.js] Range change was triggered programmatically (from settings load). Skipping user modification flag.");
            // Still need to update WebSocket for new data stream
        } else {
            // Mark that user has modified range
            console.log("[main.js] User manually changed range. Marking as modified.");
            // Note: Range settings are saved in applyAutoscale() when axis ranges change
        }

        const rangeDropdownValue = window.rangeSelect.value;
        console.log(`[main.js] Range changed to ${rangeDropdownValue}`);

        // Use current time as base for range calculations (not hardcoded 2022)
        const currentTime = new Date().getTime(); // Keep in milliseconds
        let requestedFromTs;
        switch(rangeDropdownValue) {
            case '1h': requestedFromTs = currentTime - 3600 * 1000; break;
            case '8h': requestedFromTs = currentTime - 8 * 3600 * 1000; break;
            case '24h': requestedFromTs = currentTime - 86400 * 1000; break;
            case '3d': requestedFromTs = currentTime - 3 * 86400 * 1000; break;
            case '7d': requestedFromTs = currentTime - 7 * 86400 * 1000; break;
            case '30d': requestedFromTs = currentTime - 30 * 86400 * 1000; break;
            case '3m': requestedFromTs = currentTime - 90 * 86400 * 1000; break;
            case '6m': requestedFromTs = currentTime - 180 * 86400 * 1000; break;
            case '1y': requestedFromTs = currentTime - 365 * 86400 * 1000; break;
            case '3y': requestedFromTs = currentTime - 3 * 365 * 86400 * 1000; break;
            default: requestedFromTs = currentTime - 30 * 86400 * 1000;
        }
        const requestedToTs = currentTime;

        // Get current resolution
        const currentResolution = window.resolutionSelect.value;

        // Calculate bars for requested time range with current resolution
        const timeRangeSeconds = (requestedToTs - requestedFromTs) / 1000;
        const estimatedBars = calculateBars(timeRangeSeconds, currentResolution);

        console.log(`[main.js] Estimated bars for range ${rangeDropdownValue} with resolution ${currentResolution}: ${estimatedBars}`);

        // Adjust time range if bars exceed limit
        let finalFromTs = requestedFromTs;
        let finalToTs = requestedToTs;

        if (estimatedBars > MAX_BARS) {
            const adjusted = adjustTimeRangeForMaxBars(requestedFromTs, requestedToTs, currentResolution);
            finalFromTs = adjusted.fromTs;
            finalToTs = adjusted.toTs;
            console.log(`[main.js] Adjusted time range for range change: bars limited to ${MAX_BARS}`);
        }

        window.currentXAxisRange = [finalFromTs, finalToTs]; // Keep in milliseconds
        window.xAxisMinDisplay.textContent = `${new Date(finalFromTs).toISOString()}`;
        window.xAxisMaxDisplay.textContent = `${new Date(finalToTs).toISOString()}`;

        window.currentYAxisRange = null; // Reset Y-axis range for new data
        window.yAxisMinDisplay.textContent = 'Auto';
        window.yAxisMaxDisplay.textContent = 'Auto';
        window.activeShapeForPotentialDeletion = null;
        updateSelectedShapeInfoPanel(null);
        if (window.cancelRequests) window.cancelRequests("Range change initiated by user");
        console.log("[main.js] Range changed by user. Calculating and setting new x-axis range, triggering chart update.");

        // Clear the entire chart before changing range
        if (window.gd) {
            console.log("[main.js] Clearing chart data for range change");
            console.log("[CHART_UPDATE] main.js range change - clearing chart at", new Date().toISOString());
            removeRealtimePriceLine(window.gd);
            // Clear all chart data and reset to empty state
            Plotly.react(window.gd, [], window.gd.layout || {});
            console.log("[CHART_UPDATE] main.js range change - chart cleared, ready for new data");
        }

        // Update WebSocket with new time range (don't close/reopen, just send new config)
        const symbol = window.symbolSelect.value;
        const resolution = window.resolutionSelect.value;
        const activeIndicators = Array.from(document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
        if (symbol && resolution) {
            console.log(`[main.js] Time range changed to ${rangeDropdownValue}, updating WebSocket config with adjusted time range`);

            // Convert to seconds for WebSocket
            const wsFromTs = Math.floor(finalFromTs / 1000);
            const wsToTs = Math.floor(finalToTs / 1000);

            // If WebSocket is open, send new config with updated time range, otherwise establish new connection
            if (window.combinedWebSocket && window.combinedWebSocket.readyState === WebSocket.OPEN) {
                setupCombinedWebSocket(symbol, activeIndicators, resolution, wsFromTs, wsToTs);
            } else {
                delay(100).then(() => {
                    setupCombinedWebSocket(symbol, activeIndicators, resolution, wsFromTs, wsToTs);
                });
            }
        }
    }); // Replaced .onchange with addEventListener('change',...)


    const indicatorCheckboxes = document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]');
    indicatorCheckboxes.forEach(checkbox => {
        checkbox.addEventListener('change', () => {
            saveSettings();

            // Update combined WebSocket with new indicators
            const symbol = window.symbolSelect.value;
            const resolution = window.resolutionSelect.value;
            const activeIndicators = Array.from(document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
            console.log('main.js: Indicator checkbox change - activeIndicators:', activeIndicators);

            if (symbol && resolution) {
                // Update indicators and send new config if WebSocket is connected
                updateCombinedIndicators(activeIndicators);

                // If WebSocket is open, send updated config with new indicators
                if (window.combinedWebSocket && window.combinedWebSocket.readyState === WebSocket.OPEN) {
                    // Use current time for range calculations
                    const currentTime = new Date().getTime();
                    let wsFromTs = new Date(currentTime - 30 * 86400 * 1000).toISOString(); // 30 days before current time
                    let wsToTs = new Date(currentTime + 30 * 86400 * 1000).toISOString(); // 30 days after current time

                    // 🔧 FIX TIMESTAMP SYNCHRONIZATION: Use saved X-axis range if available
                    console.log(`[main.js] 🔍 DEBUG TIMESTAMP SYNC: Checking currentXAxisRange for indicator change WebSocket`);
                    console.log(`[main.js] 🔍 DEBUG TIMESTAMP SYNC: window.currentXAxisRange:`, window.currentXAxisRange);
                    if (window.currentXAxisRange && Array.isArray(window.currentXAxisRange) && window.currentXAxisRange.length === 2) {
                        wsFromTs = new Date(window.currentXAxisRange[0]).toISOString();
                        wsToTs = new Date(window.currentXAxisRange[1]).toISOString();
                        console.log(`[main.js] ✅ TIMESTAMP SYNC: Using saved X-axis range for indicator change WebSocket:`, {
                            savedRange: window.currentXAxisRange,
                            wsFromTs: wsFromTs,
                            wsToTs: wsToTs
                        });
                    } else {
                        console.log(`[main.js] ⚠️ TIMESTAMP SYNC: No valid currentXAxisRange for indicator change, using calculated range`);
                    }

                    setupCombinedWebSocket(symbol, activeIndicators, resolution, wsFromTs, wsToTs);
                }
            }
        });
    });

    // Event listener for "Show Agent Trades" checkbox
    document.getElementById('showAgentTradesCheckbox').addEventListener('change', () => {
        saveSettings();
        // Agent trades will be handled by the combined WebSocket when data is refreshed
        const symbol = window.symbolSelect.value;
        const resolution = window.resolutionSelect.value;
        if (symbol && resolution) {
            const activeIndicators = Array.from(document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);

            // Calculate time range for agent trades update
            // Use current time for range calculations
            const currentTime = new Date().getTime();
            let wsFromTs = new Date(currentTime - 30 * 86400 * 1000).toISOString(); // 30 days before current time
            let wsToTs = new Date(currentTime + 30 * 86400 * 1000).toISOString(); // 30 days after current time

            // 🔧 FIX TIMESTAMP SYNCHRONIZATION: Use saved X-axis range if available
            console.log(`[main.js] 🔍 DEBUG TIMESTAMP SYNC: Checking currentXAxisRange for agent trades WebSocket`);
            console.log(`[main.js] 🔍 DEBUG TIMESTAMP SYNC: window.currentXAxisRange:`, window.currentXAxisRange);
            if (window.currentXAxisRange && Array.isArray(window.currentXAxisRange) && window.currentXAxisRange.length === 2) {
                wsFromTs = new Date(window.currentXAxisRange[0]).toISOString();
                wsToTs = new Date(window.currentXAxisRange[1]).toISOString();
                console.log(`[main.js] ✅ TIMESTAMP SYNC: Using saved X-axis range for agent trades WebSocket:`, {
                    savedRange: window.currentXAxisRange,
                    wsFromTs: wsFromTs,
                    wsToTs: wsToTs
                });
            } else {
                console.log(`[main.js] ⚠️ TIMESTAMP SYNC: No valid currentXAxisRange for agent trades, using default range`);
            }

            setupCombinedWebSocket(symbol, activeIndicators, resolution, wsFromTs, wsToTs);
        }
    });


    // Event listener for "Delete line" button
    if (window.deleteShapeBtn) {
        window.deleteShapeBtn.addEventListener('click', async () => {
            if (!window.activeShapeForPotentialDeletion || !window.activeShapeForPotentialDeletion.id) {
                alert("No shape selected for deletion.");
                return;
            }

            const symbol = window.symbolSelect.value;
            if (!symbol) {
                alert("Please select a symbol first.");
                return;
            }

            const drawingId = window.activeShapeForPotentialDeletion.id;
            // Removed confirmation dialog - delete immediately

            try {
                const response = await fetch(`/delete_drawing/${symbol}/${drawingId}`, { method: 'DELETE' });
                if (!response.ok) {
                    const errorBody = await response.text().catch(() => "Could not read error body");
                    throw new Error(`Failed to delete drawing from backend: ${response.status} - ${errorBody}`);
                }
                console.log(`Drawing ${drawingId} deleted successfully from backend.`);

                // Remove the shape from the chart
                if (window.gd && window.gd.layout && window.gd.layout.shapes) {
                    const shapes = window.gd.layout.shapes.filter(shape => shape.id !== drawingId);
                    Plotly.relayout(window.gd, { shapes: shapes });
                }

                // Clear the active shape state
                window.activeShapeForPotentialDeletion = null;
                updateSelectedShapeInfoPanel(null);
                hoveredShapeBackendId = null;

            } catch (error) {
                console.error(`Error deleting drawing ${drawingId}:`, error);
                alert(`Failed to delete drawing: ${error.message}`);
            }
        });
    }

    // Event listener for "Edit line" button
    if (window.editShapeBtn) {
        window.editShapeBtn.addEventListener('click', () => {
            if (!window.activeShapeForPotentialDeletion || !window.activeShapeForPotentialDeletion.id) {
                alert("No shape selected for editing.");
                return;
            }

            // Show the dialog first
            const dialog = document.getElementById('shape-properties-dialog');
            if (dialog) {
                dialog.style.display = 'block';
        
                // Then populate the dialog with current shape properties
                populateShapePropertiesDialog(window.activeShapeForPotentialDeletion);
            }
        });
    }

    // Event listener for "Delete ALL Drawings" button
    if (window.deleteAllShapesBtn) {
        window.deleteAllShapesBtn.addEventListener('click', async () => {
            const symbol = window.symbolSelect.value;
            if (!symbol) {
                alert("Please select a symbol first.");
                return;
            }
            // Removed confirmation dialog - delete all immediately

            try {
                const response = await fetch(`/delete_all_drawings/${symbol}`, { method: 'DELETE' });
                if (!response.ok) {
                    const errorBody = await response.text().catch(() => "Could not read error body");
                    throw new Error(`Failed to delete all drawings from backend: ${response.status} - ${errorBody}`);
                }
                console.log(`All drawings for ${symbol} deleted successfully from backend.`);
                if (window.gd && window.gd.layout) {
                    window.gd.layout.shapes = [];
                    Plotly.relayout(window.gd, { shapes: [] });
                }
                activeShapeForPotentialDeletion = null; // from state.js
                updateSelectedShapeInfoPanel(null); // from uiUpdaters.js
                hoveredShapeBackendId = null; // from state.js
            } catch (error) {
                console.error(`Error deleting all drawings for ${symbol}:`, error);
                alert(`Failed to delete all drawings: ${error.message}`);
                loadDrawingsAndRedraw(symbol); // from this file (main.js)
            }
        });
    }

    // Add event listeners for replay controls and Ollama settings to save settings on change
    document.getElementById('replay-from').addEventListener('change', saveSettings);
    document.getElementById('replay-to').addEventListener('change', saveSettings);
    document.getElementById('replay-speed').addEventListener('input', saveSettings);
    window.useLocalOllamaCheckbox.addEventListener('change', () => { // Already has a listener in aiFeatures.js, ensure saveSettings is also called
        saveSettings(); // Call saveSettings from settingsManager.js
    });
    window.localOllamaModelSelect.addEventListener('change', saveSettings);

    // Initialize other features
    initializeReplayControls(); // From replay.js
    initializeAIFeatures();   // From aiFeatures.js
    initializeLogStream(); // Initialize log streaming

    // Check for symbol from template FIRST (highest priority)
    let initialSymbol = null;
    if (window.initialSymbol && window.initialSymbol !== 'BTCUSDT') {
        initialSymbol = window.initialSymbol;
        console.log(`[main.js] Symbol from template/server: ${initialSymbol}`);
        window.symbolSelect.value = initialSymbol;
    } else {
        // Check for requested symbol from URL path (second priority)
        const urlPath = window.location.pathname;
        if (urlPath && urlPath !== '/' && urlPath.length > 1) {
            initialSymbol = urlPath.substring(1).toUpperCase();
            console.log(`[main.js] Requested symbol from URL: ${initialSymbol}`);
            window.symbolSelect.value = initialSymbol;
        } else {
            // Load last selected symbol if no URL symbol (lowest priority)
            const lastSelectedSymbol = await getLastSelectedSymbol();
            if (lastSelectedSymbol) {
                initialSymbol = lastSelectedSymbol;
                window.symbolSelect.value = lastSelectedSymbol;
                console.log(`[main.js] Loaded last selected symbol: ${lastSelectedSymbol}`);
            }
        }
    }

    // Store the initial symbol for comparison
    window.initialSymbol = initialSymbol;

    await populateDropdowns(); // Populate dropdown first

    // Load settings after dropdown is populated
    // Use initial symbol if available, otherwise use dropdown value
    const symbolToLoad = initialSymbol || window.symbolSelect.value;
    if (symbolToLoad) {
        console.log(`[main.js] Loading settings for symbol: ${symbolToLoad}`);
        await loadSettings(symbolToLoad);
    } else {
        console.warn(`[main.js] No symbol available for settings loading, using defaults`);
    }

    // Now that dropdowns are populated (and symbolSelect.value should be set by populate or default),
    // initialize chart interactions and then load settings.
    if (window.gd) {
        console.log('[DEBUG] About to call initializeChartInteractions');
        initializeChartInteractions(); // From chartInteractions.js, ensure gd is available
        console.log('[DEBUG] initializeChartInteractions completed');
    } else {
        console.log('[DEBUG] window.gd not available, skipping initializeChartInteractions');
    }

    // Initialize combined WebSocket after settings are loaded
    const selectedSymbol = window.symbolSelect.value;
    const selectedResolution = window.resolutionSelect.value;
    console.log(`[main.js] Initializing combined WebSocket with symbol: ${selectedSymbol}, resolution: ${selectedResolution}`);

    if (selectedSymbol && selectedResolution) {
        const activeIndicators = Array.from(document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
        console.log(`[main.js] Active indicators:`, activeIndicators);

        // Initialize chart subplots layout before WebSocket messages arrive
        if (activeIndicators.length > 0 && window.gd) {
            console.log('[main.js] Setting up chart subplots layout before WebSocket initialization');
            const layout = createLayoutForIndicators(activeIndicators);
            Plotly.relayout(window.gd, layout);
            console.log('[main.js] Chart subplots layout initialized');
        }

        // Use saved X-axis range if available, otherwise use default (30 days ago to now)
        let fromTs, toTs;
        if (window.currentXAxisRange && window.currentXAxisRange.length === 2) {
            // Convert milliseconds to ISO timestamp strings
            fromTs = new Date(window.currentXAxisRange[0]).toISOString();
            toTs = new Date(window.currentXAxisRange[1]).toISOString();
            console.log(`[main.js] Using saved X-axis range: from ${fromTs} to ${toTs}`);
        } else {
            // Use current time for range calculations
            const currentTime = new Date().getTime();
            fromTs = new Date(currentTime - 30 * 86400 * 1000).toISOString(); // 30 days before current time
            toTs = new Date(currentTime + 30 * 86400 * 1000).toISOString(); // 30 days after current time
            console.log(`[main.js] Using default current time range: from ${fromTs} to ${toTs}`);
        }

        setupCombinedWebSocket(selectedSymbol, activeIndicators, selectedResolution, fromTs, toTs);
    } else {
        console.warn(`[main.js] Cannot initialize WebSocket - symbol: ${selectedSymbol}, resolution: ${selectedResolution}`);
    }

    // Force dragmode to 'pan' at the very end of initialization to override any other settings
    /*
    setTimeout(() => {
        if (window.gd) {
            console.log('[DEBUG] Forcing final dragmode to pan');
            Plotly.relayout(window.gd, { dragmode: 'pan' }).then(() => {
                console.log('[DEBUG] Final dragmode set to pan successfully');
            }).catch(err => {
                console.error('[DEBUG] Failed to set final dragmode:', err);
            });
        }
    }, 1000);
    */

    // Handle browser back/forward navigation
    window.addEventListener('popstate', (event) => {
        console.log('[main.js] Browser navigation detected, updating chart for new symbol');
        const newSymbol = window.location.pathname.substring(1).toUpperCase();

        if (newSymbol && newSymbol !== window.symbolSelect.value) {
            console.log(`[main.js] Updating symbol from ${window.symbolSelect.value} to ${newSymbol} due to navigation`);

            // Update dropdown without triggering change event
            window.isProgrammaticallySettingSymbol = true;
            window.symbolSelect.value = newSymbol;
            window.isProgrammaticallySettingSymbol = false;

            // Perform symbol switch
            window.currentXAxisRange = null;
            window.currentYAxisRange = null;
            window.xAxisMinDisplay.textContent = 'Auto';
            window.xAxisMaxDisplay.textContent = 'Auto';
            window.yAxisMinDisplay.textContent = 'Auto';
            window.yAxisMaxDisplay.textContent = 'Auto';
            window.activeShapeForPotentialDeletion = null;

            // Clear chart and close WebSocket
            if (window.gd) {
                removeRealtimePriceLine(window.gd);
                Plotly.react(window.gd, [], window.gd.layout || {});
            }
            closeCombinedWebSocket("Browser navigation - switching symbols");

            // Reset state
            window.combinedSymbol = '';
            window.combinedIndicators = [];
            window.combinedResolution = '1h';
            window.combinedFromTs = null;
            window.combinedToTs = null;
            window.accumulatedHistoricalData = [];
            window.isAccumulatingHistorical = false;
            window.historicalDataSymbol = '';

            updateSelectedShapeInfoPanel(null);
            setLastSelectedSymbol(newSymbol);
            loadSettings(newSymbol);

            // Establish new connection
            const activeIndicators = Array.from(document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
            const resolution = window.resolutionSelect.value;
            // Use current time for range calculations
            const currentTime = new Date().getTime();
            let wsFromTs = new Date(currentTime - 30 * 86400 * 1000).toISOString();
            let wsToTs = new Date(currentTime + 30 * 86400 * 1000).toISOString();

            // 🔧 FIX TIMESTAMP SYNCHRONIZATION: Use saved X-axis range if available
            console.log(`[main.js] 🔍 DEBUG TIMESTAMP SYNC: Checking currentXAxisRange for browser navigation WebSocket`);
            console.log(`[main.js] 🔍 DEBUG TIMESTAMP SYNC: window.currentXAxisRange:`, window.currentXAxisRange);
            if (window.currentXAxisRange && Array.isArray(window.currentXAxisRange) && window.currentXAxisRange.length === 2) {
                wsFromTs = new Date(window.currentXAxisRange[0]).toISOString();
                wsToTs = new Date(window.currentXAxisRange[1]).toISOString();
                console.log(`[main.js] ✅ TIMESTAMP SYNC: Using saved X-axis range for browser navigation WebSocket:`, {
                    savedRange: window.currentXAxisRange,
                    wsFromTs: wsFromTs,
                    wsToTs: wsToTs
                });
            } else {
                console.log(`[main.js] ⚠️ TIMESTAMP SYNC: No valid currentXAxisRange for browser navigation, using calculated range`);
            }

            delay(200).then(() => {
                setupCombinedWebSocket(newSymbol, activeIndicators, resolution, wsFromTs, wsToTs);
            });
        }
    });

    // Explicitly handle window resize
    const debouncedPlotlyResize = debounce(function() {
        if (window.gd) {
            Plotly.Plots.resize(window.gd);
        }
    }, 250);
    window.addEventListener('resize', debouncedPlotlyResize);
});

/**
 * Applies autoscaling to the chart, focusing on historical data
 * and ignoring the full extent of a specified live data trace for scaling.
 */
function applyAutoscale(gdFromClick) { // Added gdFromClick argument
    console.info("Autoscale INITIATED.");
    // Ensure we are using the Plotly graph object, not just the DOM element.
    // gdFromClick is expected to be the graph object from the modebar button.
    // window.gd is the global reference to the graph object.
    const plotlyGraphObj = gdFromClick || window.gd;

    if (!plotlyGraphObj) {
        console.error("Autoscale: Plotly graph object not available (gdFromClick or window.gd is null/undefined).");
        return;
    }
    // Check for essential properties of a fully initialized Plotly graph object.
    if (!plotlyGraphObj.data || !plotlyGraphObj.layout || !plotlyGraphObj._fullLayout) {
        console.warn("Autoscale: Plotly graph object not fully initialized (missing data, layout, or _fullLayout). Proceeding anyway to keep button functional.");
        // Add more detailed logging for debugging this state:
        console.log("Debug Autoscale: plotlyGraphObj.data:", plotlyGraphObj.data);
        console.log("Debug Autoscale: plotlyGraphObj.layout:", plotlyGraphObj.layout);
        console.log("Debug Autoscale: plotlyGraphObj._fullLayout:", plotlyGraphObj._fullLayout);
        // Continue execution instead of returning to keep button functional
    }

   const fullData = plotlyGraphObj.data;
   const inputLayout = plotlyGraphObj.layout;
   const layoutUpdate = {};

   // --- X-AXIS AUTOSCALE ---
   let xMin = Infinity, xMax = -Infinity;
   let xDataFound = false;
   console.log("Autoscale: Starting X-axis calculation...");

   fullData.forEach((trace, index) => {
       console.log(`Autoscale: Checking trace ${index}, type: ${trace.type}, name: ${trace.name}, has x: ${!!trace.x}, x length: ${trace.x ? trace.x.length : 0}`);
       if (trace.x && trace.x.length > 0) {  // Check if x-values are present
           console.log(`Autoscale: Processing trace ${index} x-values:`, trace.x.slice(0, 3), "... (showing first 3)");
           trace.x.forEach((ts, tsIndex) => {
               const timestamp = (ts instanceof Date) ? ts.getTime() : new Date(ts).getTime();
               if (!isNaN(timestamp)) {
                   if (timestamp < xMin) {
                       xMin = timestamp;
                       console.log(`Autoscale: New xMin found at trace ${index}, index ${tsIndex}: ${new Date(timestamp).toISOString()}`);
                   }
                   if (timestamp > xMax) {
                       xMax = timestamp;
                       console.log(`Autoscale: New xMax found at trace ${index}, index ${tsIndex}: ${new Date(timestamp).toISOString()}`);
                   }
                   xDataFound = true;
               } else {
                   console.warn(`Autoscale: Invalid timestamp at trace ${index}, index ${tsIndex}:`, ts);
               }
           });
       }
   });

   console.log(`Autoscale: X-axis calculation complete. xDataFound: ${xDataFound}, xMin: ${xMin} (${new Date(xMin).toISOString()}), xMax: ${xMax} (${new Date(xMax).toISOString()})`);

   if (xDataFound) {
       let xPadding;
       if (xMin === xMax) {
           xPadding = 60 * 60 * 1000; // 1 hour in milliseconds
           console.log("Autoscale: xMin equals xMax, using 1 hour padding");
       } else {
           xPadding = (xMax - xMin) * 0.05; // 5% padding
           console.log(`Autoscale: Calculated 5% padding: ${(xMax - xMin) * 0.05}ms`);
           if (xPadding < 60000 && (xMax - xMin) > 0) {
               xPadding = 60000;
               console.log("Autoscale: Padding was too small, setting minimum 1 minute padding");
           }
       }
       const finalXMin = xMin - xPadding;
       const finalXMax = xMax + xPadding;

       // Validate that the calculated dates are valid before converting to ISO strings
       if (!isFinite(finalXMin) || !isFinite(finalXMax)) {
           console.error("Autoscale: Invalid X-axis range calculated - xMin:", xMin, "xMax:", xMax, "xPadding:", xPadding);
           console.error("Autoscale: Skipping X-axis autoscale due to invalid date range");
           return; // Exit early to prevent the error
       }

       const minDate = new Date(finalXMin);
       const maxDate = new Date(finalXMax);

       // Additional validation for date objects
       if (isNaN(minDate.getTime()) || isNaN(maxDate.getTime())) {
           console.error("Autoscale: Invalid Date objects created - finalXMin:", finalXMin, "finalXMax:", finalXMax);
           console.error("Autoscale: Skipping X-axis autoscale due to invalid date objects");
           return; // Exit early to prevent the error
       }

       layoutUpdate['xaxis.range[0]'] = minDate.toISOString();
       layoutUpdate['xaxis.range[1]'] = maxDate.toISOString();
       layoutUpdate['xaxis.autorange'] = false;
       console.log(`Autoscale: Final X-axis range: ${minDate.toISOString()} to ${maxDate.toISOString()}`);

       // Apply to matching x-axes
       Object.keys(inputLayout).forEach(key => {
           if (key.startsWith('xaxis') && key !== 'xaxis' && inputLayout[key] && inputLayout[key].matches === 'x') {
               layoutUpdate[`${key}.range[0]`] = layoutUpdate['xaxis.range[0]'];
               layoutUpdate[`${key}.range[1]`] = layoutUpdate['xaxis.range[1]'];
               layoutUpdate[`${key}.autorange`] = false;
           }
       });
   } else {
       layoutUpdate['xaxis.autorange'] = true;
       // Ensure matching x-axes also autorange
       Object.keys(inputLayout).forEach(key => {
           if (key.startsWith('xaxis') && key !== 'xaxis' && inputLayout[key] && inputLayout[key].matches === 'x') {
               layoutUpdate[`${key}.autorange`] = true;
           }
       });
   }
// --- Y-AXES AUTOSCALE ---
// Collect y values for primary y-axis (y) from visible traces
let yMin = Infinity, yMax = -Infinity;
let yDataFound = false;
let yPadding = 0; // Declare yPadding here to make it accessible in both if blocks

 let indicatorYMin = Infinity;
 let indicatorYMax = -Infinity;
 let indicatorYDataFound = false;

 console.log("Autoscale: Examining traces for y-axis range...");

   fullData.forEach(trace => {
        if (trace.name === 'Buy Signal') return; // Skip traces named "Buy Signal"
        if (trace.yaxis === 'y') { // Ensure y-values are present AND for main chart
            // Iterate through open, high, low, close values
            const ohlc = [trace.open, trace.high, trace.low, trace.close];
            ohlc.forEach(yValues => {
                if (yValues && Array.isArray(yValues)) {
                    yValues.forEach(yVal => {
                        if (typeof yVal === 'number' && !isNaN(yVal)) {
                            if (yVal < yMin) yMin = yVal;
                            if (yVal > yMax) yMax = yVal;
                            yDataFound = true;
                            //console.log(`Autoscale: Found price yVal=${yVal}`);
                        }
                    });
                } else {

                   if (trace.name)
                    {
                       console.warn(`Autoscale: OHLC value is not an array in candlestick trace`, trace.name)
                    }
                }
            });
        } else if (trace.yaxis && trace.yaxis !== 'y' && trace.y && trace.y.length > 0) { // Handle indicator subplots
            trace.y.forEach(yVal => {
                if (typeof yVal === 'number' && !isNaN(yVal)) {

                    if (yVal < indicatorYMin) indicatorYMin = yVal;
                    if (yVal > indicatorYMax) indicatorYMax = yVal;
                    indicatorYDataFound = true;
                }

            });

        }
   });

    console.log(`Autoscale: Price yDataFound=${yDataFound}, yMin=${yMin}, yMax=${yMax}`);
    console.log(`Autoscale: Indicator yDataFound=${indicatorYDataFound}, indicatorYMin=${indicatorYMin}, indicatorYMax=${indicatorYMax}`);

    // Combine the Y-axis ranges
    let priceChartYMin = Infinity;
    let priceChartYMax = -Infinity;

    if (yDataFound) {
        priceChartYMin = Math.min(priceChartYMin, yMin);
        priceChartYMax = Math.max(priceChartYMax, yMax);
    }

    if (priceChartYMin !== Infinity && priceChartYMax !== -Infinity) {
        let yPadding;
        if (priceChartYMin === priceChartYMax) {
            yPadding = Math.abs(priceChartYMin) * 0.1 || 0.1; // 10% of the price or a default value
        } else {
            yPadding = (priceChartYMax - priceChartYMin) * 0.05; // 5% padding
        }

        const finalYMin = priceChartYMin - yPadding;
        const finalYMax = priceChartYMax + yPadding;

        // Validate that the calculated Y-axis values are finite
        if (!isFinite(finalYMin) || !isFinite(finalYMax)) {
            console.error("Autoscale: Invalid Y-axis range calculated - priceChartYMin:", priceChartYMin, "priceChartYMax:", priceChartYMax, "yPadding:", yPadding);
            console.error("Autoscale: Skipping Y-axis autoscale due to invalid range");
            return; // Exit early to prevent the error
        }

        layoutUpdate['yaxis.range[0]'] = finalYMin;
        layoutUpdate['yaxis.range[1]'] = finalYMax;
        layoutUpdate['yaxis.autorange'] = false;
    } else {
        // If no data is found, force a default range. This prevents errors.
        layoutUpdate['yaxis.range[0]'] = 0
        layoutUpdate['yaxis.range[1]'] = 100
        layoutUpdate['yaxis.autorange'] = true;
        console.log("Autoscale: No price chart Y-axis data found. Setting yaxis.autorange to true.");
    }



    // # Remove autoscale from indicators
    // // Apply autorange to indicator y-axes (to ensure they are still responsive)
    // Object.keys(inputLayout).forEach(key => {
    //     if (key.startsWith('yaxis') && key !== 'yaxis' && inputLayout[key]) {
    //         layoutUpdate[`${key}.autorange`] = true;
    //     }


    if (Object.keys(layoutUpdate).length > 0) {
        console.log("Autoscale: Applying layoutUpdate:", JSON.stringify(layoutUpdate, null, 2));
        try {
            Plotly.relayout(plotlyGraphObj, layoutUpdate);

            // Save the new axis ranges after applying autoscale
            if (xDataFound) {
                // Convert from ISO strings back to milliseconds for storage
                const newXMin = new Date(layoutUpdate['xaxis.range[0]']).getTime();
                const newXMax = new Date(layoutUpdate['xaxis.range[1]']).getTime();

                // Update global variables (store in milliseconds as expected by the system)
                window.currentXAxisRange = [newXMin, newXMax];

                // Update display elements with validation
                if (window.xAxisMinDisplay) {
                    try {
                        window.xAxisMinDisplay.textContent = `${new Date(newXMin).toISOString()}`;
                    } catch (e) {
                        console.error("Autoscale: Error formatting xAxisMinDisplay:", e);
                        window.xAxisMinDisplay.textContent = `${newXMin}`;
                    }
                }
                if (window.xAxisMaxDisplay) {
                    try {
                        window.xAxisMaxDisplay.textContent = `${new Date(newXMax).toISOString()}`;
                    } catch (e) {
                        console.error("Autoscale: Error formatting xAxisMaxDisplay:", e);
                        window.xAxisMaxDisplay.textContent = `${newXMax}`;
                    }
                }

                console.log("Autoscale: Updated currentXAxisRange:", window.currentXAxisRange);
            }

            // Save Y-axis range if it was calculated
            if (priceChartYMin !== Infinity && priceChartYMax !== -Infinity) {
                window.currentYAxisRange = [priceChartYMin - yPadding, priceChartYMax + yPadding];

                // Update display elements
                if (window.yAxisMinDisplay) {
                    window.yAxisMinDisplay.textContent = (priceChartYMin - yPadding).toFixed(2);
                }
                if (window.yAxisMaxDisplay) {
                    window.yAxisMaxDisplay.textContent = (priceChartYMax + yPadding).toFixed(2);
                }

                console.log("Autoscale: Updated currentYAxisRange:", window.currentYAxisRange);
            }

            // Save the new ranges to Redis
            saveSettings();

        } catch (e) {
            console.error("Autoscale: Error during Plotly.relayout:", e);
            console.error("Autoscale: Failed layoutUpdate was:", JSON.stringify(layoutUpdate, null, 2));
            console.error("Autoscale: Current plotlyGraphObj state (data and layout):", { data: plotlyGraphObj.data, layout: plotlyGraphObj.layout, _fullLayout: plotlyGraphObj._fullLayout });
            throw e;
        }
    } else {
        console.info("Autoscale: No layout changes to apply.");
    }
}

async function setLastSelectedSymbol(symbol) {
    try {
        const response = await fetch(`/set_last_symbol/${symbol}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        if (!response.ok) {
            console.error(`Failed to set last selected symbol: ${response.status} ${await response.text()}`);
        }
    } catch (error) {
        console.error("Error setting last selected symbol:", error);
    }
}

async function getLastSelectedSymbol() {
    try {
        const response = await fetch(`/get_last_symbol`, {
            method: 'GET',
            headers: { 'Content-Type': 'application/json' }
        });
        if (response.ok) {
            const data = await response.json();
            if (data.status === 'success') {
                return data.symbol;
            } else {
                console.warn(`Could not get last selected symbol: ${data.message || 'Unknown error'}`);
                return null;
            }
        }
        console.error(`Failed to get last selected symbol: ${response.status} ${await response.text()}`);
    } catch (error) {
        console.error("Error getting last selected symbol:", error);
    }
    return null;
}

window.applyAutoscale = applyAutoscale; // Ensure it's globally available if called from config.js

// Shape Properties Dialog Functions
async function populateShapePropertiesDialog(activeShape) {
    if (!activeShape || !activeShape.id) return;

    // Set the shape ID display
    const shapeIdDisplay = document.getElementById('shape-id-display');
    if (shapeIdDisplay) {
        shapeIdDisplay.textContent = activeShape.id;
    }

    // Get symbol
    const symbol = window.symbolSelect ? window.symbolSelect.value : null;
    if (!symbol) {
        console.warn('No symbol selected, cannot fetch shape properties');
        return;
    }

    // Set default values initially
    const startPrice = document.getElementById('start-price');
    const endPrice = document.getElementById('end-price');
    const buyOnCross = document.getElementById('buy-on-cross');
    const sellOnCross = document.getElementById('sell-on-cross');
    const amount = document.getElementById('amount');
    const sendEmailOnCross = document.getElementById('send-email-on-cross');
    const emailSent = document.getElementById('email-sent');
    const emailDateDisplay = document.getElementById('email-date-display');

    console.log('DEBUG: DOM elements found:');
    console.log('  startPrice element:', startPrice);
    console.log('  endPrice element:', endPrice);
    console.log('  buyOnCross element:', buyOnCross);

    // Load current Y values from the shape properties endpoint
    if (startPrice && endPrice) {
        // Y values will be loaded from the properties response below
    }

    if (buyOnCross) buyOnCross.checked = false;
    if (sellOnCross) sellOnCross.checked = false;
    if (amount) amount.value = '';
    if (sendEmailOnCross) sendEmailOnCross.checked = false;
    if (emailSent) emailSent.checked = false;
    if (emailDateDisplay) emailDateDisplay.textContent = 'Not sent yet';

    // Fetch existing properties from backend
    try {
        const response = await fetch(`/get_shape_properties/${symbol}/${activeShape.id}`);
        const result = await response.json();

        if (response.ok && result.status === 'success') {
            const properties = result.properties || {};

            console.log('DEBUG: Full properties response:', properties);
            console.log('DEBUG: start_price in properties:', properties.start_price);
            console.log('DEBUG: end_price in properties:', properties.end_price);

            // Populate Y values
            if (startPrice) {
                if (properties.start_price !== undefined) {
                    startPrice.value = properties.start_price;
                    console.log('DEBUG: Set startPrice to:', properties.start_price);
                } else {
                    console.log('DEBUG: start_price not found in properties');
                }
            }

            if (endPrice) {
                if (properties.end_price !== undefined) {
                    endPrice.value = properties.end_price;
                    console.log('DEBUG: Set endPrice to:', properties.end_price);
                } else {
                    console.log('DEBUG: end_price not found in properties');
                }
            }

            // Populate form with existing properties
            if (buyOnCross && properties.buyOnCross !== undefined) {
                buyOnCross.checked = properties.buyOnCross;
            }
            if (sellOnCross && properties.sellOnCross !== undefined) {
                sellOnCross.checked = properties.sellOnCross;
            }
            if (amount && properties.amount !== undefined) {
                amount.value = properties.amount;
            }
            if (sendEmailOnCross && properties.sendEmailOnCross !== undefined) {
                sendEmailOnCross.checked = properties.sendEmailOnCross;
            }
            if (emailSent && properties.emailSent !== undefined) {
                emailSent.checked = properties.emailSent;
            }
            if (emailDateDisplay && properties.emailDate) {
                emailDateDisplay.textContent = new Date(properties.emailDate).toLocaleString();
            }

            console.log('Loaded existing shape properties:', properties);
        } else {
            console.log('No existing properties found for shape, using defaults');
            console.log('Response status:', response.status, 'Result:', result);
        }
    } catch (error) {
        console.error('Error fetching shape properties:', error);
        // Continue with default values
    }
}

async function saveShapeProperties() {
    // Get values from the dialog
    const startPriceInput = document.getElementById('start-price').value;
    const endPriceInput = document.getElementById('end-price').value;
    const buyOnCross = document.getElementById('buy-on-cross').checked;
    const sellOnCross = document.getElementById('sell-on-cross').checked;
    const amountInput = document.getElementById('amount').value;
    const sendEmailOnCross = document.getElementById('send-email-on-cross').checked;

    // Get symbol and drawing ID
    const symbol = window.symbolSelect ? window.symbolSelect.value : null;
    const drawingId = document.getElementById('shape-id-display').textContent;

    if (!symbol) {
        alert('Please select a symbol first.');
        return;
    }

    if (!drawingId) {
        alert('No shape selected.');
        return;
    }

    // Validate Y values
    let startPrice, endPrice;
    if (startPriceInput.trim() !== '') {
        startPrice = parseFloat(startPriceInput);
        if (isNaN(startPrice)) {
            alert('Please enter a valid start price.');
            return;
        }
    }

    if (endPriceInput.trim() !== '') {
        endPrice = parseFloat(endPriceInput);
        if (isNaN(endPrice)) {
            alert('Please enter a valid end price.');
            return;
        }
    }

    // Prepare properties object
    const properties = {
        buyOnCross,
        sellOnCross,
        sendEmailOnCross
    };

    // Handle amount - convert to number if provided
    if (amountInput.trim() !== '') {
        const amount = parseFloat(amountInput);
        if (isNaN(amount) || amount <= 0) {
            alert('Please enter a valid positive amount.');
            return;
        }
        properties.amount = amount;
    }

    try {
        // First, save shape properties
        const response = await fetch(`/save_shape_properties/${symbol}/${drawingId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(properties)
        });

        const result = await response.json();

        if (response.ok && result.status === 'success') {
            console.log('Shape properties saved successfully:', {
                shapeId: drawingId,
                symbol,
                properties
            });

            // If Y values were provided, update the shape coordinates
            if (startPrice !== undefined || endPrice !== undefined) {
                await updateShapeYValues(symbol, drawingId, startPrice, endPrice);
            }

            // Close the dialog
            closeShapePropertiesDialog();

            // Refresh the chart to show updated shape
            if (window.combinedWebSocket && window.combinedWebSocket.readyState === WebSocket.OPEN) {
                // Trigger a refresh by sending current config
                const activeIndicators = Array.from(document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
                const resolution = window.resolutionSelect.value;
                const currentTime = new Date().getTime();
                let wsFromTs = new Date(currentTime - 30 * 86400 * 1000).toISOString();
                let wsToTs = new Date(currentTime + 30 * 86400 * 1000).toISOString();

                if (window.currentXAxisRange && Array.isArray(window.currentXAxisRange) && window.currentXAxisRange.length === 2) {
                    wsFromTs = new Date(window.currentXAxisRange[0]).toISOString();
                    wsToTs = new Date(window.currentXAxisRange[1]).toISOString();
                }

                setupCombinedWebSocket(symbol, activeIndicators, resolution, wsFromTs, wsToTs);
            }

            // Show success message
            // alert('Shape properties saved successfully!');
        } else {
            console.error('Failed to save shape properties:', result.message);
            alert(`Failed to save shape properties: ${result.message || 'Unknown error'}`);
        }
    } catch (error) {
        console.error('Error saving shape properties:', error);
        alert('An error occurred while saving shape properties. Please try again.');
    }
}

async function updateShapeYValues(symbol, drawingId, startPrice, endPrice) {
    try {
        // Get current drawings
        const response = await fetch(`/get_drawings/${symbol}`);
        const result = await response.json();

        if (response.ok && result.status === 'success') {
            const drawings = result.drawings || [];
            const drawingIndex = drawings.findIndex(d => d.id === drawingId);

            if (drawingIndex !== -1) {
                // Update the Y values
                if (startPrice !== undefined) {
                    drawings[drawingIndex].start_price = startPrice;
                }
                if (endPrice !== undefined) {
                    drawings[drawingIndex].end_price = endPrice;
                }

                // Update the drawing via PUT request
                const updateResponse = await fetch(`/update_drawing/${symbol}/${drawingId}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(drawings[drawingIndex])
                });

                if (updateResponse.ok) {
                    console.log('Shape Y values updated successfully');
                } else {
                    console.error('Failed to update shape Y values');
                }
            }
        }
    } catch (error) {
        console.error('Error updating shape Y values:', error);
    }
}

function closeShapePropertiesDialog() {
    const dialog = document.getElementById('shape-properties-dialog');
    if (dialog) {
        dialog.style.display = 'none';
    }
}

// Initialize log streaming
function initializeLogStream() {
    const logElement = document.getElementById('event-output');

    if (!logElement) {
        console.error("Log element with ID 'event-output' not found in the DOM.");
        return;
    }

    const eventSource = new EventSource('/stream/logs');

    eventSource.onmessage = function(event) {
        try {
            const logLineText = JSON.parse(event.data);

            // Get current content, split into lines, and prepend the new log
            let currentLog = logElement.value;
            let lines = currentLog.split('\n');
            lines.unshift(logLineText);

            // Limit the number of lines to prevent the UI from slowing down
            if (lines.length > 200) {
                lines = lines.slice(0, 200);
            }

            logElement.value = lines.join('\n');

            // Auto-scroll to the top to show the latest message if already there
            /*
            if (logElement.scrollTop < 10) { // A small tolerance
                logElement.scrollTop = 0;
            }
            */

        } catch (e) {
            console.error("Error parsing log data:", e, "Raw data:", event.data);
        }
    };

    eventSource.onerror = function(err) {
        console.error("EventSource for logs failed:", err);
        // The browser will automatically attempt to reconnect.
    };

    console.log("Log stream initialized.");
}
