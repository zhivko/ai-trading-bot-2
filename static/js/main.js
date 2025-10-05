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

    // Stream delta slider elements
    window.streamDeltaSlider = document.getElementById('stream-delta-slider');
    window.streamDeltaValueDisplay = document.getElementById('stream-delta-value-display');

    // Trade filter slider elements
    window.minValueSlider = document.getElementById('min-value-slider');
    window.minValueDisplay = document.getElementById('min-volume-value');

// Initialize trade filter slider to 0 by default to show all trades
    if (window.minValueSlider) {
        // Set slider properties for crypto USD values (range will be updated dynamically)
        window.minValueSlider.min = 0;
        window.minValueSlider.max = 10000; // $10k default max
        window.minValueSlider.step = 100;
        window.minValueSlider.value = 0; // Always start at 0 to show all trades
        updateMinValueDisplay(); // Sync display with initial value
        updateMaxValueDisplay(); // Sync max display with initial range

        // Trade filter slider event listener
        if (minValueSlider) {
            minValueSlider.addEventListener('input', handleMinValueChange);
            minValueSlider.value = 0; // Set default to 0
            handleMinValueChange(); // Update display
        }
    }

    // Trade visualization checkbox elements
    window.showVolumeProfileCheckbox = document.getElementById('show-volume-profile-checkbox');
    window.showTradeMarkersCheckbox = document.getElementById('show-trade-markers-checkbox');

    // Initialize debounced functions
    window.debouncedUpdateShapeVisuals = debounce(updateShapeVisuals, VISUAL_UPDATE_DEBOUNCE_DELAY); // VISUAL_UPDATE_DEBOUNCE_DELAY from config.js
    // Crosshair functionality disabled due to panning interference
    window.debouncedUpdateCrosshair = () => {}; // No-op function

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

        }

        return { fromTs: wsFromTs, toTs: wsToTs };
    };


    // Initialize Plotly chart (empty initially)
    const initialLayout = {
        title: 'Loading chart data...',
        xaxis: {
            rangeslider: { visible: false },
            type: 'date',
            autorange: true
        },
        yaxis: {
            title: 'Price',
            autorange: true
        },
        showlegend: false
    }; // Basic layout - full layout configuration handled in combinedData.js

    Plotly.newPlot('chart', [], initialLayout, config).then(function(gd) { // layout & config from config.js
        window.gd = gd; // Make Plotly graph div object global

        // Initialize Plotly specific event handlers after chart is ready
        initializePlotlyEventHandlers(gd); // From plotlyEventHandlers.js

        // Ensure mobile hover is disabled after chart creation
        disableMobileHover(gd);
        forceHideHoverElements(); // Force hide hover elements via CSS

        // Enable mobile pinch zoom features
        enableMobilePinchZoom(gd);

        // Ensure mouse wheel zoom is enabled after chart creation
        if (window.ensureScrollZoomEnabled) {
            window.ensureScrollZoomEnabled();
        }


        // Initialize trade history after chart is ready
        // initializeTradeHistory();

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
            setLastSelectedSymbol(selectedSymbol);
            await loadSettings(selectedSymbol);
            return;
        }

        if (window.isProgrammaticallySettingSymbol) {
            return;
        }


        // Clear the entire chart before switching symbols
        if (window.gd) {
            removeRealtimePriceLine(window.gd);
            // Clear all chart data and reset to empty state
            Plotly.react(window.gd, [], window.gd.layout || {});
        }

        // Close existing WebSocket connection
        if (window.combinedWebSocket) {
            closeCombinedWebSocket("Symbol changed - switching to new symbol");
        }

        // Update URL without full page reload for better UX
        const newUrl = `/${selectedSymbol}`;
        window.history.pushState({ symbol: selectedSymbol }, '', newUrl);

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

        // Clear trade history data for the old symbol
        window.tradeHistoryData = [];

        // Update selected shape info
        updateSelectedShapeInfoPanel(null);

        // Save the new symbol selection
        setLastSelectedSymbol(selectedSymbol);

        // Load settings for the new symbol SYNCHRONOUSLY
        await loadSettings(selectedSymbol);

        // Establish new WebSocket connection for the new symbol AFTER settings are loaded

        // Calculate time range for new symbol
        // Use current time for range calculations
        const currentTime = new Date().getTime(); // Use current time
        const fromTs = Math.floor((currentTime - 30 * 86400 * 1000) / 1000); // 30 days before current time
        const toTs = Math.floor((currentTime + 30 * 86400 * 1000) / 1000); // 30 days after current time



        // Now get the indicator values AFTER settings are loaded
        const activeIndicators = Array.from(document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
        const resolution = window.resolutionSelect.value;

        // 🔧 FIX TIMESTAMP SYNCHRONIZATION: Use the same timestamp source for both settings and WebSocket
        // If we have saved X-axis range from settings, use it for WebSocket too
        let wsFromTs = fromTs;
        let wsToTs = toTs;


        if (window.currentXAxisRange && Array.isArray(window.currentXAxisRange) && window.currentXAxisRange.length === 2) {
            // Convert saved milliseconds to ISO timestamp strings for WebSocket
            wsFromTs = new Date(window.currentXAxisRange[0]).toISOString();
            wsToTs = new Date(window.currentXAxisRange[1]).toISOString();
        }

        setupCombinedWebSocket(selectedSymbol, activeIndicators, resolution, wsFromTs, wsToTs);

    }); // Replaced .onchange with addEventListener('change',...)
    window.resolutionSelect.addEventListener('change', () => {
        // Check if this change was triggered programmatically (from settings load)
        if (window.isProgrammaticallySettingResolution) {
            // Still need to update WebSocket for new data stream
        } else {
            // Mark that user has modified resolution
            window.hasUserModifiedResolution = true;
            // Note: Resolution settings are saved in applyAutoscale() when axis ranges change
        }

        const newResolution = window.resolutionSelect.value;

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


        // Adjust time range if bars exceed limit
        let adjustedFromTs = currentFromTs;
        let adjustedToTs = currentToTs;

        if (estimatedBars > MAX_BARS) {
            const adjusted = adjustTimeRangeForMaxBars(currentFromTs, currentToTs, newResolution);
            adjustedFromTs = adjusted.fromTs;
            adjustedToTs = adjusted.toTs;
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

        // Clear the entire chart before changing resolution
        if (window.gd) {
            removeRealtimePriceLine(window.gd);
            // Clear all chart data and reset to empty state
            Plotly.react(window.gd, [], window.gd.layout || {});
        }

        // Update WebSocket with new resolution and adjusted time range
        const symbol = window.symbolSelect.value;
        const activeIndicators = Array.from(document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
        if (symbol && newResolution) {
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
        saveSettings(); // Save the resolution change to Redis
    }); // Replaced .onchange with addEventListener('change',...)
    window.rangeSelect.addEventListener('change', () => {
        // Check if this change was triggered programmatically (from settings load)
        if (window.isProgrammaticallySettingRange) {
            // Still need to update WebSocket for new data stream
        } else {
            // Mark that user has modified range
            // Note: Range settings are saved in applyAutoscale() when axis ranges change
        }

        const rangeDropdownValue = window.rangeSelect.value;

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


        // Adjust time range if bars exceed limit
        let finalFromTs = requestedFromTs;
        let finalToTs = requestedToTs;

        if (estimatedBars > MAX_BARS) {
            const adjusted = adjustTimeRangeForMaxBars(requestedFromTs, requestedToTs, currentResolution);
            finalFromTs = adjusted.fromTs;
            finalToTs = adjusted.toTs;
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

        // Clear the entire chart before changing range
        if (window.gd) {
            removeRealtimePriceLine(window.gd);
            // Clear all chart data and reset to empty state
            Plotly.react(window.gd, [], window.gd.layout || {});
        }

        // Update WebSocket with new time range (don't close/reopen, just send new config)
        const symbol = window.symbolSelect.value;
        const resolution = window.resolutionSelect.value;
        const activeIndicators = Array.from(document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
        if (symbol && resolution) {

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
        saveSettings(); // Save the range change to Redis
    }); // Replaced .onchange with addEventListener('change',...)


    const indicatorCheckboxes = document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]');
    indicatorCheckboxes.forEach(checkbox => {
        checkbox.addEventListener('change', () => {
            saveSettings();

            // Update combined WebSocket with new indicators
            const symbol = window.symbolSelect.value;
            const resolution = window.resolutionSelect.value;
            const activeIndicators = Array.from(document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);

            if (symbol && resolution) {
                // CRITICAL FIX: Always update chart layout when indicators change
                // This ensures subplots are created/destroyed immediately when indicators are selected/deselected
                if (window.gd) {
                    const layout = createLayoutForIndicators(activeIndicators);
                    Plotly.relayout(window.gd, layout);
                }

                // Update indicators and send new config if WebSocket is connected
                updateCombinedIndicators(activeIndicators);

                // If WebSocket is open, send updated config with new indicators
                if (window.combinedWebSocket && window.combinedWebSocket.readyState === WebSocket.OPEN) {
                    // Use current time for range calculations
                    const currentTime = new Date().getTime();
                    let wsFromTs = new Date(currentTime - 30 * 86400 * 1000).toISOString(); // 30 days before current time
                    let wsToTs = new Date(currentTime + 30 * 86400 * 1000).toISOString(); // 30 days after current time

                    // 🔧 FIX TIMESTAMP SYNCHRONIZATION: Use saved X-axis range if available
                    if (window.currentXAxisRange && Array.isArray(window.currentXAxisRange) && window.currentXAxisRange.length === 2) {
                        wsFromTs = new Date(window.currentXAxisRange[0]).toISOString();
                        wsToTs = new Date(window.currentXAxisRange[1]).toISOString();
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
            if (window.currentXAxisRange && Array.isArray(window.currentXAxisRange) && window.currentXAxisRange.length === 2) {
                wsFromTs = new Date(window.currentXAxisRange[0]).toISOString();
                wsToTs = new Date(window.currentXAxisRange[1]).toISOString();
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

                // Remove the shape from the chart
                if (window.gd && window.gd.layout && window.gd.layout.shapes) {
                    const shapes = window.gd.layout.shapes.filter(shape => shape.id !== drawingId);
                    Plotly.relayout(window.gd, { shapes: shapes });
                }

                // Remove associated volume profile traces for rectangles
                if (window.gd && window.gd.data) {
                    const filteredData = window.gd.data.filter(trace =>
                        !trace.name || !trace.name.startsWith(`VP-${drawingId}`)
                    );
                    if (filteredData.length !== window.gd.data.length) {
                        window.gd.data = filteredData;
                        Plotly.react(window.gd, window.gd.data, window.gd.layout).then(() => {
                            // Re-add trade history markers after shape deletion
                            if (window.tradeHistoryData && window.tradeHistoryData.length > 0 && window.updateTradeHistoryVisualizations) {
                                window.updateTradeHistoryVisualizations();
                            }
                        });
                    }
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
                // Get all drawings first to identify volume profile traces to remove
                const drawingsResponse = await fetch(`/get_drawings/${symbol}`);
                const drawingsResult = await drawingsResponse.json();
                const drawingIds = [];

                if (drawingsResponse.ok && drawingsResult.status === 'success') {
                    const drawings = drawingsResult.drawings || [];
                    drawingIds.push(...drawings.map(d => d.id));
                }

                const response = await fetch(`/delete_all_drawings/${symbol}`, { method: 'DELETE' });
                if (!response.ok) {
                    const errorBody = await response.text().catch(() => "Could not read error body");
                    throw new Error(`Failed to delete all drawings from backend: ${response.status} - ${errorBody}`);
                }

                if (window.gd && window.gd.layout) {
                    window.gd.layout.shapes = [];
                    Plotly.relayout(window.gd, { shapes: [] });
                }

                // Remove associated volume profile traces for all deleted drawings
                if (window.gd && window.gd.data && drawingIds.length > 0) {
                    const filteredData = window.gd.data.filter(trace => {
                        if (!trace.name) return true;
                        return !drawingIds.some(id => trace.name.startsWith(`VP-${id}`));
                    });
                    if (filteredData.length !== window.gd.data.length) {
                        window.gd.data = filteredData;
                        Plotly.react(window.gd, window.gd.data, window.gd.layout).then(() => {
                            // Re-add trade history markers after shape deletion
                            if (window.tradeHistoryData && window.tradeHistoryData.length > 0 && window.updateTradeHistoryVisualizations) {
                                window.updateTradeHistoryVisualizations();
                            }
                        });
                    }
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

    // Stream delta slider event listener
    if (window.streamDeltaSlider && window.streamDeltaValueDisplay) {
        window.streamDeltaSlider.addEventListener('input', () => {
            // Update the display value
            window.streamDeltaValueDisplay.textContent = window.streamDeltaSlider.value;
            // Save settings when slider value changes
            saveSettings();
        });
    }

    // Trade filter slider event listener - only if tradeHistory.js hasn't set it up
    if (window.minValueSlider && window.minValueDisplay && !window.tradeHistoryInitialized) {
        window.minValueSlider.addEventListener('input', () => {
            // Update the display value
            window.minValueDisplay.textContent = window.minValueSlider.value;
            // Save settings when slider value changes
            saveSettings();
        });
    }

    // Trade visualization checkboxes event listeners - only if tradeHistory.js hasn't set it up
    if (window.showVolumeProfileCheckbox && !window.tradeHistoryInitialized) {
        window.showVolumeProfileCheckbox.addEventListener('change', saveSettings);
    }
    if (window.showTradeMarkersCheckbox && !window.tradeHistoryInitialized) {
        window.showTradeMarkersCheckbox.addEventListener('change', saveSettings);
    }

    // Initialize other features
    initializeReplayControls(); // From replay.js
    initializeAIFeatures();   // From aiFeatures.js
    // initializeLogStream(); // Log streaming disabled

    // Check for symbol from template FIRST (highest priority)
    let initialSymbol = null;
    if (window.initialSymbol && window.initialSymbol !== 'BTCUSDT') {
        initialSymbol = window.initialSymbol;
        window.symbolSelect.value = initialSymbol;
    } else {
        // Check for requested symbol from URL path (second priority)
        const urlPath = window.location.pathname;
        if (urlPath && urlPath !== '/' && urlPath.length > 1) {
            initialSymbol = urlPath.substring(1).toUpperCase();
            window.symbolSelect.value = initialSymbol;
        } else {
            // Load last selected symbol if no URL symbol (lowest priority)
            const lastSelectedSymbol = await getLastSelectedSymbol();
            if (lastSelectedSymbol) {
                initialSymbol = lastSelectedSymbol;
                window.symbolSelect.value = lastSelectedSymbol;
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
        await loadSettings(symbolToLoad);
    } else {
        console.warn(`[main.js] No symbol available for settings loading, using defaults`);
    }

    // Now that dropdowns are populated (and symbolSelect.value should be set by populate or default),
    // initialize chart interactions and then load settings.
    if (window.gd) {
        initializeChartInteractions(); // From chartInteractions.js, ensure gd is available
    } else {
    }

    // Initialize combined WebSocket after settings are loaded
    const selectedSymbol = window.symbolSelect.value;
    const selectedResolution = window.resolutionSelect.value;

    if (selectedSymbol && selectedResolution) {
        const activeIndicators = Array.from(document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);

        // Initialize chart subplots layout before WebSocket messages arrive
        if (activeIndicators.length > 0 && window.gd) {
            const layout = createLayoutForIndicators(activeIndicators);
            Plotly.relayout(window.gd, layout);
        }

        // Use saved X-axis range if available, otherwise use default (30 days ago to now)
        let fromTs, toTs;
        if (window.currentXAxisRange && window.currentXAxisRange.length === 2) {
            // Convert milliseconds to ISO timestamp strings
            fromTs = new Date(window.currentXAxisRange[0]).toISOString();
            toTs = new Date(window.currentXAxisRange[1]).toISOString();
        } else {
            // Use current time for range calculations
            const currentTime = new Date().getTime();
            fromTs = new Date(currentTime - 30 * 86400 * 1000).toISOString(); // 30 days before current time
            toTs = new Date(currentTime + 30 * 86400 * 1000).toISOString(); // 30 days after current time
        }

        setupCombinedWebSocket(selectedSymbol, activeIndicators, selectedResolution, fromTs, toTs);
    } else {
        console.warn(`[main.js] Cannot initialize WebSocket - symbol: ${selectedSymbol}, resolution: ${selectedResolution}`);
    }

    // Force dragmode to 'pan' at the very end of initialization to override any other settings
    /*
    setTimeout(() => {
        if (window.gd) {
            Plotly.relayout(window.gd, { dragmode: 'pan' }).then(() => {
            }).catch(err => {
                console.error('[DEBUG] Failed to set final dragmode:', err);
            });
        }
    }, 1000);
    */

    // Handle browser back/forward navigation
    window.addEventListener('popstate', (event) => {
        const newSymbol = window.location.pathname.substring(1).toUpperCase();

        if (newSymbol && newSymbol !== window.symbolSelect.value) {

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

        // Clear trade history data for the old symbol
        window.tradeHistoryData = [];

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
            if (window.currentXAxisRange && Array.isArray(window.currentXAxisRange) && window.currentXAxisRange.length === 2) {
                wsFromTs = new Date(window.currentXAxisRange[0]).toISOString();
                wsToTs = new Date(window.currentXAxisRange[1]).toISOString();
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
        // Continue execution instead of returning to keep button functional
    }

   const fullData = plotlyGraphObj.data;
   const inputLayout = plotlyGraphObj.layout;
   const layoutUpdate = {};

   // --- X-AXIS AUTOSCALE DISABLED ---
   // Autoscale no longer modifies xaxis min and max values
// --- Y-AXES AUTOSCALE ---
// Collect y values for primary y-axis (y) from visible traces
let yMin = Infinity, yMax = -Infinity;
let yDataFound = false;
let yPadding = 0; // Declare yPadding here to make it accessible in both if blocks

 let indicatorYMin = Infinity;
 let indicatorYMax = -Infinity;
 let indicatorYDataFound = false;


   // Get current X-axis range to filter visible data points
   const currentXAxisRange = inputLayout.xaxis && inputLayout.xaxis.range;
   let xMinVisible = null;
   let xMaxVisible = null;


   if (currentXAxisRange && currentXAxisRange.length === 2) {
       // Plotly stores timestamps as milliseconds since epoch
       xMinVisible = typeof currentXAxisRange[0] === 'number' ? currentXAxisRange[0] : new Date(currentXAxisRange[0]).getTime();
       xMaxVisible = typeof currentXAxisRange[1] === 'number' ? currentXAxisRange[1] : new Date(currentXAxisRange[1]).getTime();
   } else {
   }

   fullData.forEach(trace => {
        if (trace.name === 'Buy Signal') return; // Skip traces named "Buy Signal"
        if (trace.yaxis === 'y') { // Ensure y-values are present AND for main chart
            // Iterate through open, high, low, close values
            const ohlc = [trace.open, trace.high, trace.low, trace.close];
            ohlc.forEach((yValues, ohlcIndex) => {
                if (yValues && Array.isArray(yValues)) {
                    yValues.forEach((yVal, index) => {
                        if (typeof yVal === 'number' && !isNaN(yVal)) {
                            // Check if this data point is within the visible X-axis range
                            let isVisible = true;
                            if (xMinVisible !== null && xMaxVisible !== null && trace.x && trace.x[index]) {
                                const xVal = trace.x[index] instanceof Date ? trace.x[index].getTime() : new Date(trace.x[index]).getTime();
                                isVisible = xVal >= xMinVisible && xVal <= xMaxVisible;
                            }

                            if (isVisible) {
                                if (yVal < yMin) yMin = yVal;
                                if (yVal > yMax) yMax = yVal;
                                yDataFound = true;
                            }
                        }
                    });
                } else {
                    if (trace.name) {
                        console.warn(`Autoscale: OHLC value is not an array in candlestick trace`, trace.name);
                    }
                }
            });
        } else if (trace.yaxis && trace.yaxis !== 'y' && trace.y && trace.y.length > 0) { // Handle indicator subplots
            trace.y.forEach((yVal, index) => {
                if (typeof yVal === 'number' && !isNaN(yVal)) {
                    // Check if this data point is within the visible X-axis range
                    let isVisible = true;
                    if (xMinVisible !== null && xMaxVisible !== null && trace.x && trace.x[index]) {
                        const xVal = trace.x[index] instanceof Date ? trace.x[index].getTime() : new Date(trace.x[index]).getTime();
                        isVisible = xVal >= xMinVisible && xVal <= xMaxVisible;
                    }

                    if (isVisible) {
                        if (yVal < indicatorYMin) indicatorYMin = yVal;
                        if (yVal > indicatorYMax) indicatorYMax = yVal;
                        indicatorYDataFound = true;
                    }
                }
            });
        }
   });


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
        layoutUpdate['yaxis.range[0]'] = 0;
        layoutUpdate['yaxis.range[1]'] = 100;
        layoutUpdate['yaxis.autorange'] = true;
    }



    // # Remove autoscale from indicators
    // // Apply autorange to indicator y-axes (to ensure they are still responsive)
    // Object.keys(inputLayout).forEach(key => {
    //     if (key.startsWith('yaxis') && key !== 'yaxis' && inputLayout[key]) {
    //         layoutUpdate[`${key}.autorange`] = true;
    //     }


    if (Object.keys(layoutUpdate).length > 0) {
        try {
            Plotly.relayout(plotlyGraphObj, layoutUpdate);

            // Save the new axis ranges after applying autoscale
            // Note: X-axis range is no longer modified by autoscale

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


    // Load current Y values from the shape properties endpoint
    if (startPrice && endPrice) {
        // Y values will be loaded from the properties response below
    }

    if (buyOnCross) buyOnCross.checked = false;
    if (sellOnCross) sellOnCross.checked = false;
    if (amount) amount.value = '';
    if (sendEmailOnCross) sendEmailOnCross.checked = true;
    if (emailSent) emailSent.checked = false;
    if (emailDateDisplay) emailDateDisplay.textContent = 'Not sent yet';

    // Fetch existing properties from backend
    try {
        const response = await fetch(`/get_shape_properties/${symbol}/${activeShape.id}`);
        const result = await response.json();

        if (response.ok && result.status === 'success') {
            const properties = result.properties || {};


            // Populate Y values
            if (startPrice) {
                if (properties.start_price !== undefined) {
                    startPrice.value = properties.start_price;
                } else {
                }
            }

            if (endPrice) {
                if (properties.end_price !== undefined) {
                    endPrice.value = properties.end_price;
                } else {
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
                // No longer disable the checkbox - allow manual changes
            }
            if (document.getElementById('buy-sent') && properties.buy_sent !== undefined) {
                document.getElementById('buy-sent').checked = properties.buy_sent;
            }
            if (document.getElementById('sell-sent') && properties.sell_sent !== undefined) {
                document.getElementById('sell-sent').checked = properties.sell_sent;
            }
            if (emailDateDisplay && properties.emailDate) {
                emailDateDisplay.textContent = new Date(properties.emailDate).toLocaleString();
            }

            // Populate alert actions
            if (document.getElementById('alert-actions-display') && properties.alert_actions) {
                document.getElementById('alert-actions-display').value = Array.isArray(properties.alert_actions) ? properties.alert_actions.join('\n') : properties.alert_actions;
            }

            // Populate resolution
            if (document.getElementById('shape-resolution')) {
                document.getElementById('shape-resolution').value = properties.resolution || '';
            }

        } else {
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
        resolution: document.getElementById('shape-resolution').value,
        buyOnCross,
        sellOnCross,
        sendEmailOnCross
    };

    const buySent = document.getElementById('buy-sent') ? document.getElementById('buy-sent').checked : false;
    const sellSent = document.getElementById('sell-sent') ? document.getElementById('sell-sent').checked : false;
    const emailSent = document.getElementById('email-sent') ? document.getElementById('email-sent').checked : false;

    // Handle amount - convert to number if provided
    if (amountInput.trim() !== '') {
        const amount = parseFloat(amountInput);
        if (isNaN(amount) || amount <= 0) {
            alert('Please enter a valid positive amount.');
            return;
        }
        properties.amount = amount;
    }

    // Add the special fields
    properties.buy_sent = buySent;
    properties.sell_sent = sellSent;
    properties.emailSent = emailSent;

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

}

// Custom Toolbar Functionality
document.addEventListener('DOMContentLoaded', function() {
    // Pan button
    const panBtn = document.getElementById('pan-btn');
    if (panBtn) {
        panBtn.addEventListener('click', function() {
            if (window.gd) {
                Plotly.relayout(window.gd, { dragmode: 'pan' });

                // Update button states
                updateToolbarButtonStates('pan');
            }
        });
    }

    // Zoom button
    const zoomBtn = document.getElementById('zoom-btn');
    if (zoomBtn) {
        zoomBtn.addEventListener('click', function() {
            if (window.gd) {
                Plotly.relayout(window.gd, { dragmode: 'zoom' });

                // Update button states
                updateToolbarButtonStates('zoom');
            }
        });
    }

    // Draw Line button
    const drawlineBtn = document.getElementById('drawline-btn');
    if (drawlineBtn) {
        drawlineBtn.addEventListener('click', function() {
            if (window.gd) {
                Plotly.relayout(window.gd, { dragmode: 'drawline' });

                // Update button states
                updateToolbarButtonStates('drawline');
            }
        });
    }

    // Draw Rectangle button
    const drawrectBtn = document.getElementById('drawrect-btn');
    if (drawrectBtn) {
        drawrectBtn.addEventListener('click', function() {
            if (window.gd) {
                Plotly.relayout(window.gd, { dragmode: 'drawrect' });

                // Update button states
                updateToolbarButtonStates('drawrect');
            }
        });
    }

    // Screenshot button
    const screenshotBtn = document.getElementById('screenshot-btn');
    if (screenshotBtn) {
        screenshotBtn.addEventListener('click', function() {
            if (window.gd) {
                try {
                    // Use Plotly's built-in download function
                    Plotly.downloadImage(window.gd, {
                        format: 'png',
                        width: 1200,
                        height: 800,
                        filename: `chart-${window.symbolSelect ? window.symbolSelect.value : 'trading'}-${new Date().toISOString().split('T')[0]}`
                    });
                } catch (error) {
                    console.error('Screenshot failed:', error);
                    alert('Screenshot failed. Please try again.');
                }
            }
        });
    }

    // Auto Scale button
    const autoscaleBtn = document.getElementById('autoscale-btn');
    if (autoscaleBtn) {
        autoscaleBtn.addEventListener('click', function() {
            if (window.gd && typeof applyAutoscale === 'function') {
                applyAutoscale(window.gd);
            }
        });
    }

    // Initialize button states
    updateToolbarButtonStates();
});

// Function to update toolbar button states based on current dragmode
function updateToolbarButtonStates(activeMode) {
    const panBtn = document.getElementById('pan-btn');
    const zoomBtn = document.getElementById('zoom-btn');
    const drawlineBtn = document.getElementById('drawline-btn');
    const drawrectBtn = document.getElementById('drawrect-btn');

    if (!panBtn || !zoomBtn || !drawlineBtn || !drawrectBtn) return;

    // Remove active class from all buttons
    panBtn.classList.remove('active');
    zoomBtn.classList.remove('active');
    drawlineBtn.classList.remove('active');
    drawrectBtn.classList.remove('active');

    // Add active class to current mode button
    if (activeMode === 'pan' || (!activeMode && window.gd && window.gd.layout.dragmode === 'pan')) {
        panBtn.classList.add('active');
    } else if (activeMode === 'zoom' || (!activeMode && window.gd && window.gd.layout.dragmode === 'zoom')) {
        zoomBtn.classList.add('active');
    } else if (activeMode === 'drawline' || (!activeMode && window.gd && window.gd.layout.dragmode === 'drawline')) {
        drawlineBtn.classList.add('active');
    } else if (activeMode === 'drawrect' || (!activeMode && window.gd && window.gd.layout.dragmode === 'drawrect')) {
        drawrectBtn.classList.add('active');
    }
}

// Update toolbar states when dragmode changes
document.addEventListener('plotly_relayout', function(event) {
    if (event.detail && event.detail.dragmode) {
        updateToolbarButtonStates(event.detail.dragmode);
    }
});

// Update trade history visualizations based on minimum value filter
window.updateTradeHistoryVisualizations = function() {
    if (!window.tradeHistoryData || window.tradeHistoryData.length === 0) {
        return;
    }

    // Get current min value filter
    const minValueSlider = document.getElementById('min-value-slider');
    const minVolumeInput = document.getElementById('min-volume-value');
    let minVolume = minValueSlider ? parseFloat(minValueSlider.value) || 0 : 0;

    // Check if user typed a custom value in the display input
    if (minVolumeInput && minVolumeInput.textContent) {
        const displayedValue = parseFloat(minVolumeInput.textContent.replace(/,/g, '')) || 0;
        if (!isNaN(displayedValue)) {
            minVolume = displayedValue;
        }
    }

    // Filter trades based on minimum USD value (price * amount)
    const filteredTrades = window.tradeHistoryData.filter(trade => {
        const tradeValue = trade.price * trade.amount;
        const passesFilter = tradeValue >= minVolume;
        return passesFilter;
    });

    console.log(`📊 After filtering: ${filteredTrades.length} trades pass filter`);

    // Always update markers - addTradeHistoryMarkersToChart handles clearing when no trades pass filter
    addTradeHistoryMarkersToChart(filteredTrades, window.symbolSelect ? window.symbolSelect.value : 'UNKNOWN');
};

// Update minimum value slider range based on trade data
function updateMinValueSliderRange() {
    const minValueSlider = document.getElementById('min-value-slider');

    if (!minValueSlider) return;

    // Check if trade history data exists
    if (!window.tradeHistoryData || window.tradeHistoryData.length === 0) {
        // No trade data - use default reasonable range for crypto values
        minValueSlider.min = 0;
        minValueSlider.max = 10000; // $10k default max
        minValueSlider.step = 100;
        return;
    }

    // Extract all USD value values from trade history (price * amount)
    const valueValues = window.tradeHistoryData.map(trade => trade.price * trade.amount).filter(value =>
        typeof value === 'number' && !isNaN(value) && value > 0
    );

    if (valueValues.length === 0) {
        // No valid value data - use default range
        minValueSlider.min = 0;
        minValueSlider.max = 10000;
        minValueSlider.step = 100;
        return;
    }

    // Find maximum value
    const maxValue = Math.max(...valueValues);

    // Calculate slider max as 1.5x the maximum value found
    let calculatedMax = maxValue * 1.5;

    // Apply caps to prevent extreme values
    const minAllowedMax = 10; // Minimum max to avoid too small ranges
    const maxAllowedMax = 1000000; // Maximum max to prevent huge ranges ($1M)

    calculatedMax = Math.max(minAllowedMax, Math.min(maxAllowedMax, calculatedMax));

    // Adjust step based on the scale
    let step = 100; // $100 default step
    if (calculatedMax > 100000) {
        step = 10000; // $10k steps for very large values
    } else if (calculatedMax > 50000) {
        step = 5000; // $5k steps for large values
    } else if (calculatedMax > 10000) {
        step = 1000; // $1k steps for medium values
    } else if (calculatedMax > 1000) {
        step = 100; // $100 steps for smaller values
    } else {
        step = 10; // $10 steps for very small values
    }

    // Update slider properties
    minValueSlider.min = 0;
    minValueSlider.max = calculatedMax;
    minValueSlider.step = step;

    // Update the max value display
    updateMaxValueDisplay();

    // Ensure current value stays within new range
    const currentValue = parseFloat(minValueSlider.value);
    if (currentValue > calculatedMax) {
        minValueSlider.value = calculatedMax;
        updateMinVolumeDisplay();
    } else if (currentValue < 0) {
        minValueSlider.value = 0;
        updateMinVolumeDisplay();
    }

    console.log(`Min Value slider updated: max=$${calculatedMax.toLocaleString()}, step=$${step.toLocaleString()}, trades=${window.tradeHistoryData.length}`);
}

// Update min volume display value
function updateMinValueDisplay() {
    const minValueSlider = document.getElementById('min-value-slider');
    const minVolumeValue = document.getElementById('min-volume-value');

    if (minValueSlider && minVolumeValue) {
        const currentValue = parseFloat(minValueSlider.value);
        minVolumeValue.textContent = currentValue.toLocaleString();
    }
}

// Update max volume display value (shows the current slider maximum range)
function updateMaxValueDisplay() {
    const minValueSlider = document.getElementById('min-value-slider');
    const maxVolumeValue = document.getElementById('max-volume-value');

    if (minValueSlider && maxVolumeValue) {
        const maxValue = parseFloat(minValueSlider.max);
        maxVolumeValue.textContent = maxValue.toLocaleString();
    }
}

// Handle minimum volume slider change
function handleMinValueChange() {
    updateMinValueDisplay();

    // Update visualizations
    updateTradeHistoryVisualizations();

    // Save settings if function exists
    if (typeof saveSettings === 'function') {
        saveSettings();
    }
}
