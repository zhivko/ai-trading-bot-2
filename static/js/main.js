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
    window.liveDataCheckbox = document.getElementById('live-data-checkbox');
    window.selectedShapeInfoDiv = document.getElementById('selected-shape-info');
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

    window.streamDeltaSlider = document.getElementById('stream-delta-slider');
    window.streamDeltaValueDisplay = document.getElementById('stream-delta-value');
    // Initialize debounced functions
    window.debouncedUpdateChart = debounce(updateChart, 1000);
    window.debouncedUpdateShapeVisuals = debounce(updateShapeVisuals, VISUAL_UPDATE_DEBOUNCE_DELAY); // VISUAL_UPDATE_DEBOUNCE_DELAY from config.js
    window.debouncedUpdateCrosshair = debounce(updateOrAddCrosshairVLine, 100); // updateOrAddCrosshairVLine from chartInteractions.js

    // Initialize Plotly chart (empty initially)
    Plotly.newPlot('chart', [], layout, config).then(function(gd) { // layout & config from config.js
        window.gd = gd; // Make Plotly graph div object global

        // Initialize Plotly specific event handlers after chart is ready
        initializePlotlyEventHandlers(gd); // From plotlyEventHandlers.js


    }).catch(err => console.error('Plotly initialization error:', err));


    loadSettings();
    // General UI event listeners
    window.symbolSelect.addEventListener('change', () => {
        window.currentXAxisRange = null; window.currentYAxisRange = null;
        window.xAxisMinDisplay.textContent = 'Auto'; window.xAxisMaxDisplay.textContent = 'Auto';
        window.yAxisMinDisplay.textContent = 'Auto'; window.yAxisMaxDisplay.textContent = 'Auto';
        window.activeShapeForPotentialDeletion = null;
        if (window.isProgrammaticallySettingSymbol) {
            console.log("Symbol change was triggered programmatically. Skipping saveSettings() and loadSettings().");
            return;
        }
        console.log("[main.js] Symbol changed. Clearing ranges, deselecting shape.");
        updateSelectedShapeInfoPanel(null);
        if (window.gd) removeRealtimePriceLine(window.gd); // removeRealtimePriceLine from liveData.js
        setLastSelectedSymbol(window.symbolSelect.value);
        loadSettings();
    }); // Replaced .onchange with addEventListener('change',...)
    window.resolutionSelect.addEventListener('change', () => {
        window.currentXAxisRange = null; window.currentYAxisRange = null;
        window.xAxisMinDisplay.textContent = 'Auto'; window.xAxisMaxDisplay.textContent = 'Auto';
        window.yAxisMinDisplay.textContent = 'Auto'; window.yAxisMaxDisplay.textContent = 'Auto';
        window.activeShapeForPotentialDeletion = null;
        updateSelectedShapeInfoPanel(null);
        console.log("[main.js] Resolution changed. Clearing ranges, deselecting shape. Triggering chart update.");
        if (window.gd) removeRealtimePriceLine(window.gd);
        saveSettings(); updateChart(); // updateChart from chartUpdater.js
    }); // Replaced .onchange with addEventListener('change',...)
    window.rangeSelect.addEventListener('change', () => {
        // Important: Clear only currentXAxisRange to allow dropdown to fully control the range
        window.currentXAxisRange = null; 
        window.xAxisMinDisplay.textContent = 'Auto'; window.xAxisMaxDisplay.textContent = 'Auto';
        window.yAxisMinDisplay.textContent = 'Auto'; window.yAxisMaxDisplay.textContent = 'Auto';
        window.activeShapeForPotentialDeletion = null;
        updateSelectedShapeInfoPanel(null);
        if (window.cancelRequests) window.cancelRequests("Range change initiated by user");
        console.log("[main.js] Range changed by user. Clearing custom x-axis range, deselecting shape, triggering chart update with new dropdown value.");
        if (window.gd) removeRealtimePriceLine(window.gd);
        saveSettings(); updateChart();
    }); // Replaced .onchange with addEventListener('change',...)

    window.liveDataCheckbox.addEventListener('change', () => {
        const selectedSymbol = window.symbolSelect.value;
        if (!selectedSymbol) return;
        if (window.liveDataCheckbox.checked) {
            console.log("Live data enabled by user.");
            saveSettings();
            setupWebSocket(selectedSymbol); // from liveData.js
        } else {
            console.log("Live data disabled by user.");
            closeWebSocket("Live data disabled by user via checkbox."); // from liveData.js
            saveSettings();
        }
    });

    const indicatorCheckboxes = document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]');
    indicatorCheckboxes.forEach(checkbox => {
        checkbox.addEventListener('change', () => {
            saveSettings(); updateChart();
        });
    });

    // Event listener for "Show Agent Trades" checkbox
    document.getElementById('showAgentTradesCheckbox').addEventListener('change', () => {
        saveSettings();
        updateChart();
    });

    // Event listener for Stream Delta Time slider
    window.streamDeltaSlider.addEventListener('input', () => {
        window.streamDeltaValueDisplay.textContent = window.streamDeltaSlider.value;
        saveSettings(); // from settingsManager.js
    });

    // Event listener for "Delete ALL Drawings" button
    if (window.deleteAllShapesBtn) {
        window.deleteAllShapesBtn.addEventListener('click', async () => {
            const symbol = window.symbolSelect.value;
            if (!symbol) {
                alert("Please select a symbol first.");
                return;
            }
            const confirmation = confirm(`Are you sure you want to delete ALL drawings for ${symbol}? This action cannot be undone.`);
            if (!confirmation) return;

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
    initializeLogStream(); // From chartUpdater.js

    await populateDropdowns(); // from settingsManager.js

    const lastSelectedSymbol = await getLastSelectedSymbol();
    if (lastSelectedSymbol) {
        window.symbolSelect.value = lastSelectedSymbol;
    }

    // Now that dropdowns are populated (and symbolSelect.value should be set by populate or default),
    // initialize chart interactions and then load settings.
    if (window.gd) initializeChartInteractions(); // From chartInteractions.js, ensure gd is available
    await loadSettings(); // From settingsManager.js (which calls updateChart)

    // Explicitly handle window resize
    const debouncedPlotlyResize = debounce(function() {
        if (window.gd) {
            Plotly.Plots.resize(window.gd);
        }
    }, 250);
    window.addEventListener('resize', debouncedPlotlyResize);
});

async function loadDrawingsAndRedraw(symbol) { // Keep this global for now, or move to api.js and call from there
    console.log(`Fetching and redrawing drawings for ${symbol}...`);
    updateChart(); // This will reload drawings as part of its process
}


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
        console.error("Autoscale: Plotly graph object not fully initialized (missing data, layout, or _fullLayout).");
        // Add more detailed logging for debugging this state:
        console.log("Debug Autoscale: plotlyGraphObj.data:", plotlyGraphObj.data);
        console.log("Debug Autoscale: plotlyGraphObj.layout:", plotlyGraphObj.layout);
        console.log("Debug Autoscale: plotlyGraphObj._fullLayout:", plotlyGraphObj._fullLayout);
        return;
    }

   const fullData = plotlyGraphObj.data;
   const inputLayout = plotlyGraphObj.layout;
   const layoutUpdate = {};

   // --- X-AXIS AUTOSCALE ---
   let xMin = Infinity, xMax = -Infinity;
   let xDataFound = false;

   fullData.forEach(trace => {
       if (trace.x && trace.x.length > 0) {  // Check if x-values are present
           trace.x.forEach(ts => {
               const timestamp = (ts instanceof Date) ? ts.getTime() : new Date(ts).getTime();
               if (!isNaN(timestamp)) {
                   if (timestamp < xMin) xMin = timestamp;
                   if (timestamp > xMax) xMax = timestamp;
                   xDataFound = true;
               }
           });
       }
   });

   if (xDataFound) {
       let xPadding;
       if (xMin === xMax) {
           xPadding = 60 * 60 * 1000; // 1 hour in milliseconds
       } else {
           xPadding = (xMax - xMin) * 0.05; // 5% padding
           if (xPadding < 60000 && (xMax - xMin) > 0) {
               xPadding = 60000;
           }
       }
       layoutUpdate['xaxis.range[0]'] = new Date(xMin - xPadding).toISOString();
       layoutUpdate['xaxis.range[1]'] = new Date(xMax + xPadding).toISOString();
       layoutUpdate['xaxis.autorange'] = false;

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
                            console.log(`Autoscale: Found price yVal=${yVal}`);
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

        layoutUpdate['yaxis.range[0]'] = priceChartYMin - yPadding;
        layoutUpdate['yaxis.range[1]'] = priceChartYMax + yPadding;
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
