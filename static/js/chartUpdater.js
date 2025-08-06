async function updateChart() {
    const symbol = window.symbolSelect.value;
    const resolution = window.resolutionSelect.value;
    const rangeDropdownValue = window.rangeSelect.value;
    let fromTs, toTs;

    if (!symbol || !resolution || !rangeDropdownValue) {
        console.warn("updateChart: Missing symbol, resolution, or range. Cannot update chart yet.");
        return;
    }

    if (window.currentXAxisRange) {
        fromTs = Math.floor(window.currentXAxisRange[0] / 1000);
        toTs = Math.floor(window.currentXAxisRange[1] / 1000);
    } else {
        const now = Math.floor(Date.now() / 1000);
        switch(rangeDropdownValue) {
            case '24h': fromTs = now - 86400; break;
            case '7d': fromTs = now - 7 * 86400; break;
            case '30d': fromTs = now - 30 * 86400; break;
            case '3m': fromTs = now - 90 * 86400; break;
            case '6m': fromTs = now - 180 * 86400; break;
            case '1y': fromTs = now - 365 * 86400; break;
            case '3y': fromTs = now - 3 * 365 * 86400; break;
            default: fromTs = now - 30 * 86400;
        }
        toTs = now;
    }

    const fetchURL = `/history?symbol=${symbol}&resolution=${resolution}&from_ts=${fromTs}&to_ts=${toTs}`;
    let response, jsonData;
    try {
        response = await fetch(fetchURL);
        if (!response.ok) {
            const errorBody = await response.text().catch(() => "Could not read error body");
            throw new Error(`Fetch failed with status ${response.status}: ${errorBody}`);
        }
        jsonData = await response.json();
    } catch (error) {
        console.error('[updateChart] Error fetching or parsing historical data:', error);
        Plotly.react('chart', [], { ...layout, title: `${symbol} - Data Error` }, config); // Assumes layout & config are global
        const nowMs = Date.now();
        window.currentDataStart = new Date(nowMs - 86400000);
        window.currentDataEnd = new Date(nowMs);
        return;
    }

    if (!jsonData || jsonData.s === 'no_data' || !jsonData.t || jsonData.t.length === 0) {
        console.warn('[updateChart] No data received or empty data for selected range/symbol.');
        Plotly.react('chart', [], { ...layout, title: `${symbol} - No Data Available` }, config);
        const nowMs = Date.now();
        window.currentDataStart = new Date(nowMs - 86400000);
        window.currentDataEnd = new Date(nowMs);
        return;
    }

    window.currentDataStart = new Date(jsonData.t[0] * 1000);
    window.currentDataEnd = new Date(jsonData.t[jsonData.t.length - 1] * 1000);

    const firstDate = window.currentDataStart;
    const lastDate = window.currentDataEnd;
    const timeDiff = lastDate.getTime() - firstDate.getTime();
    const numTicks = Math.min(jsonData.t.length, 10);
    let tickValues = [], tickTexts = [];

    if (jsonData.t.length > 0) {
        if (numTicks > 1) {
            for (let i = 0; i < numTicks; i++) {
                const date = new Date(firstDate.getTime() + (i * timeDiff / (numTicks - 1)));
                tickValues.push(date);
                if (timeDiff > 365 * 86400000) tickTexts.push(date.toLocaleString('en-US', { month: 'short', year: 'numeric' }));
                else if (timeDiff > 30 * 86400000) tickTexts.push(date.toLocaleString('en-US', { month: 'short', day: 'numeric' }));
                else tickTexts.push(date.toLocaleString('en-US', { hour: '2-digit', minute: '2-digit', day: 'numeric', month: 'short'}));
            }
        } else if (numTicks === 1) {
            tickValues.push(firstDate);
            tickTexts.push(firstDate.toLocaleString('en-US', { hour: '2-digit', minute: '2-digit', day: 'numeric', month: 'short'}));
        }
    }

    const newTrace = {
        x: jsonData.t.map(t => new Date(t * 1000)),
        open: jsonData.o,
        high: jsonData.h,
        low: jsonData.l,
        close: jsonData.c,
        volume: jsonData.v, // Volume trace will be added separately if needed
        increasing: { line: { color: 'green' } },
        decreasing: { line: { color: 'red' } },
        type: 'candlestick', // Main price chart
        xaxis: 'x', // Default, will be adjusted
        yaxis: 'y', // Default, will be adjusted if indicators are present
        name: symbol
    };

    let currentLayout = JSON.parse(JSON.stringify(layout)); // Assumes layout is global from config.js

    // Calculate the main price chart's desired Y-axis range once.
    // This will be used whether indicators are present or not.
    let mainPriceChartCalculatedRange;
    if (window.currentYAxisRange) {
        mainPriceChartCalculatedRange = window.currentYAxisRange;
    } else {
        if (jsonData.l && jsonData.l.length > 0 && jsonData.h && jsonData.h.length > 0) {
            const yMin = Math.min(...jsonData.l.filter(v => v !== null));
            const yMax = Math.max(...jsonData.h.filter(v => v !== null));
            if (isFinite(yMin) && isFinite(yMax)) {
                const padding = (yMax - yMin) * 0.05 || (yMax * 0.05) || 0.1;
                mainPriceChartCalculatedRange = [yMin - padding, yMax + padding];
            } else {
                mainPriceChartCalculatedRange = [0, 1]; // Fallback
            }
        } else {
            mainPriceChartCalculatedRange = [0, 1]; // Fallback
        }
    }


    // activeIndicatorIds needs to be known early to determine the structure
    const activeIndicatorIds = Array.from(document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);

    currentLayout.shapes = currentLayout.shapes ? currentLayout.shapes.filter(s => s.name !== REALTIME_PRICE_LINE_NAME && s.name !== CROSSHAIR_VLINE_NAME && s.name !== INDICATOR_OB_LINE_NAME && s.name !== INDICATOR_OS_LINE_NAME) : [];
    currentLayout.annotations = currentLayout.annotations ? currentLayout.annotations.filter(a => a.name !== REALTIME_PRICE_TEXT_ANNOTATION_NAME) : [];

    let indicatorTraces = [];
    let newActiveIndicatorsState = [];


    if (activeIndicatorIds.length > 0) {
        let validIndicatorData = [];
        const combinedIndicatorFetchUrl = `/indicatorHistory?symbol=${symbol}&resolution=${resolution}&from_ts=${fromTs}&to_ts=${toTs}&indicator_id=${activeIndicatorIds.join(',')}`;
        try {
            const indResponse = await fetch(combinedIndicatorFetchUrl);
            if (!indResponse.ok) throw new Error(`Combined indicator fetch failed: ${indResponse.status} ${await indResponse.text()}`);
            const allIndicatorsResponse = await indResponse.json();
            if (allIndicatorsResponse && allIndicatorsResponse.s === 'ok' && allIndicatorsResponse.data) {
                activeIndicatorIds.forEach(id => {
                    if (allIndicatorsResponse.data[id] && allIndicatorsResponse.data[id].s === 'ok') {
                        validIndicatorData.push({ id: id, data: allIndicatorsResponse.data[id] });
                    } else {
                        console.warn(`No data or error for indicator ${id} in combined response.`, allIndicatorsResponse.data[id]);
                    }
                });
            } else {
                console.error("Error in combined indicator response structure.", allIndicatorsResponse);
            }
        } catch (error) {
            console.error(`Error fetching combined indicator data:`, error);
        }

        const numValidIndicators = validIndicatorData.length;

       if (numValidIndicators === 0) { // All selected indicators failed to load
            newTrace.yaxis = 'yaxis'; // Default y-axis
            newTrace.xaxis = 'xaxis';
            currentLayout.yaxis.domain = [0, 1];
            currentLayout.yaxis.range = mainPriceChartCalculatedRange;
            currentLayout.yaxis.autorange = false;
            currentLayout.yaxis.title = { text: 'Price (USDT)', font: { size: 10 } };
            currentLayout.xaxis.showticklabels = true;
            // Clean up any numbered axes from a previous indicator view.
            Object.keys(currentLayout).forEach(key => {
                if ((key.startsWith('yaxis') && key !== 'yaxis') || 
                    (key.startsWith('xaxis') && key !== 'xaxis')) {
                    delete currentLayout[key];
                }
            });
            window.activeIndicatorsState = [];            
        } else {
            // Main price chart uses the first subplot in the grid
            newTrace.yaxis = 'y'; 
            newTrace.xaxis = 'x'; 

            const baseGlobalYAxis = JSON.parse(JSON.stringify(layout.yaxis));
            const baseGlobalXAxis = JSON.parse(JSON.stringify(layout.xaxis)); // Base for all x-axes
            
            // Setup layout.grid
            const numTotalPlots = 1 + numValidIndicators;
            const mainChartRelativeHeight = numValidIndicators === 1 ? 0.6 : (numValidIndicators >= 3 ? 0.4 : 0.5); // Dynamic height for main chart
            const totalIndicatorRelativeHeight = 1.0 - mainChartRelativeHeight;
            
            let rowHeights = [mainChartRelativeHeight];
            if (numValidIndicators > 0) {
                const heightPerIndicator = totalIndicatorRelativeHeight / numValidIndicators;
                for (let i = 0; i < numValidIndicators; i++) {
                    rowHeights.push(Math.max(heightPerIndicator, 0.05)); // Ensure a minimum height
                }
            }

            currentLayout.grid = {
                rows: numTotalPlots,
                columns: 1,
                pattern: 'independent',
                roworder: 'top to bottom',
                rowheights: rowHeights,
                ygap: 0.015
            };
            
            // Clean up any numbered yaxisN/xaxisN that are not part of the grid
            Object.keys(currentLayout).forEach(key => {
                if ((key.startsWith('yaxis') && key !== 'yaxis' && parseInt(key.substring(5)) > numTotalPlots) ||
                    (key.startsWith('xaxis') && key !== 'xaxis' && parseInt(key.substring(5)) > numTotalPlots)) {
                    delete currentLayout[key];
                }
            });

            // Configure main xaxis (for the first subplot)
            currentLayout.xaxis.showticklabels = (numValidIndicators === 0); // Only show if no indicators
            currentLayout.xaxis.rangeslider = { visible: false }; // Ensure no rangeslider on main x-axis with grid

            // Configure main yaxis (for the first subplot)
            currentLayout.yaxis.title = { text: 'Price (USDT)', font: { size: 10 } };
            currentLayout.yaxis.range = mainPriceChartCalculatedRange;
            currentLayout.yaxis.autorange = false;
            // domain for yaxis is handled by the grid

            validIndicatorData.forEach((indResult, i) => {
                const indicatorId = indResult.id;
                const data = indResult.data;
                const yAxisNum = i + 2; // Indicators start from yaxis2
                const yAxisTraceRef = `y${yAxisNum}`; // For trace.yaxis
                const xAxisTraceRef = `x${yAxisNum}`; // For trace.xaxis
                const yAxisLayoutKey = `yaxis${yAxisNum}`; // For layout.yaxisN
                const xAxisLayoutKey = `xaxis${yAxisNum}`; // For layout.xaxisN

                currentLayout[yAxisLayoutKey] = {
                    ...JSON.parse(JSON.stringify(baseGlobalYAxis)), // Start with base
                    title: { text: indicatorId.toUpperCase(), font: { size: 10 } },
                    autorange: true,
                    fixedrange: false // Allow zoom on indicator y-axes
                    // domain is handled by grid
                };

                currentLayout[xAxisLayoutKey] = {
                    ...JSON.parse(JSON.stringify(baseGlobalXAxis)), // Start with base
                    anchor: yAxisTraceRef, // Anchor to the trace's y-axis ref
                    matches: 'x',          // Match the main 'x' axis
                    showticklabels: (i === numValidIndicators - 1), // Only the last indicator shows x-axis labels
                    rangeslider: { visible: false }
                };

                newActiveIndicatorsState.push({ id: indicatorId, yAxisRef: yAxisTraceRef, xAxisRef: xAxisTraceRef });

                if (data.t && data.t.length > 0) {
                    const xValues = data.t.map(t => new Date(t * 1000));

                    // Specific debug log for MACD data
                    if (indicatorId === 'macd') {
                        console.log(`[DEBUG chartUpdater] Data for MACD (id: ${indicatorId}):`, {
                            hasMacd: !!data.macd, macdLength: data.macd?.length,
                            hasSignal: !!data.signal, signalLength: data.signal?.length,
                            hasHistogram: !!data.histogram, histogramLength: data.histogram?.length
                        });
                    }

                    if (indicatorId === 'rsi' && data.rsi) {
                        indicatorTraces.push({ x: xValues, y: data.rsi, type: 'scatter', mode: 'lines', name: 'RSI', yaxis: yAxisTraceRef, xaxis: xAxisTraceRef, line: {color: 'purple'} });
                    }
                    else if(indicatorId === 'jma') {
                        if(data.jma_up) {
                            indicatorTraces.push({
                                x: xValues, y: data.jma_up,
                                type: 'scatter',
                                mode: 'lines', name: 'JMA (Up)',
                                yaxis: yAxisTraceRef, xaxis: xAxisTraceRef,
                                line: { color: 'green' }
                            });
                        }
                        if(data.jma_down) {
                            indicatorTraces.push({
                                x: xValues, y: data.jma_down,

                                type: 'scatter',
                                mode: 'lines',
                                name: 'JMA (Down)',
                                yaxis: yAxisTraceRef,
                                xaxis: xAxisTraceRef,
                                line: { color: 'red' }
                            });
                        }
                    }
                    else if (indicatorId === 'macd' && data.macd && data.signal && data.histogram) {
                        indicatorTraces.push({ x: xValues, y: data.macd, type: 'scatter', mode: 'lines', name: 'MACD Line', yaxis: yAxisTraceRef, xaxis: xAxisTraceRef, line: { color: 'blue' } });
                        indicatorTraces.push({ x: xValues, y: data.histogram, type: 'bar', name: 'Histogram', yaxis: yAxisTraceRef, xaxis: xAxisTraceRef, marker: { color: data.histogram.map(v => v >= 0 ? 'green' : 'red') } });
                        indicatorTraces.push({ x: xValues, y: data.signal, type: 'scatter', mode: 'lines', name: 'Signal Line', yaxis: yAxisTraceRef, xaxis: xAxisTraceRef, line: { color: 'orange' } });
                    }
                    else if (indicatorId.startsWith('stochrsi') && data.stoch_k && data.stoch_d) {
                        indicatorTraces.push({ x: xValues, y: data.stoch_k, type: 'scatter', mode: 'lines', name: `StochK (${indicatorId})`, yaxis: yAxisTraceRef, xaxis: xAxisTraceRef, line: { color: 'dodgerblue' } });
                        indicatorTraces.push({ x: xValues, y: data.stoch_d, type: 'scatter', mode: 'lines', name: `StochD (${indicatorId})`, yaxis: yAxisTraceRef, xaxis: xAxisTraceRef, line: { color: 'darkorange' } });
                    }
                    else if (indicatorId === 'open_interest' && data.open_interest) {
                        // Open Interest is typically visualized as a bar chart (histogram)
                        indicatorTraces.push({ x: xValues, y: data.open_interest, type: 'bar', name: 'Open Interest', yaxis: yAxisTraceRef, xaxis: xAxisTraceRef, marker: { color: 'rgba(128, 0, 128, 0.6)' } }); // Purple bars
                    }

                    if ((indicatorId === 'rsi' || indicatorId.startsWith('stochrsi')) && xValues.length > 0) {
                        const obLevel = indicatorId === 'rsi' ? 70 : 80;
                        const osLevel = indicatorId === 'rsi' ? 30 : 20;
                        currentLayout.shapes.push({
                            type: 'line', xref: xAxisTraceRef, yref: yAxisTraceRef,
                            name: INDICATOR_OB_LINE_NAME,
                            isSystemShape: true,
                            editable: false,
                            x0: xValues[0], y0: obLevel, x1: xValues[xValues.length - 1], y1: obLevel,
                            line: { color: 'rgba(255,0,0,0.7)', width: 1, dash: 'dash' }, layer: 'below'
                        });
                        currentLayout.shapes.push({
                            type: 'line', xref: xAxisTraceRef, yref: yAxisTraceRef,
                            name: INDICATOR_OS_LINE_NAME,
                            isSystemShape: true,
                            editable: false,
                            x0: xValues[0], y0: osLevel, x1: xValues[xValues.length - 1], y1: osLevel,
                            line: { color: 'rgba(255,0,0,0.7)', width: 1, dash: 'dash' }, layer: 'below'
                        });
                    }
                }

            });

            window.activeIndicatorsState = newActiveIndicatorsState;
            console.log('[DEBUG chartUpdater] Final activeIndicatorsState:', JSON.parse(JSON.stringify(window.activeIndicatorsState)));
        }

        } else {
        newTrace.yaxis = 'yaxis'; // Plotly uses 'yaxis' for the default
        newTrace.xaxis = 'xaxis'; // Main chart uses the primary 'xaxis'

        delete currentLayout.grid;
        currentLayout.yaxis.range = mainPriceChartCalculatedRange;
        currentLayout.yaxis.autorange = false;

        currentLayout.yaxis.title = { text: 'Price (USDT)', font: { size: 10 } };
        currentLayout.yaxis.domain = [0, 1]; // Full height

        currentLayout.xaxis = JSON.parse(JSON.stringify(layout.xaxis)); // Ensure it's reset from base
        currentLayout.xaxis.showticklabels = true; // Show labels as it's the only x-axis

        // Clean up any numbered yaxisN (except yaxis itself if it exists)
        Object.keys(currentLayout).forEach(key => {
            if (key.startsWith('yaxis') && key !== 'yaxis') {        
                delete currentLayout[key];
            }
            if (key.startsWith('xaxis') && key !== 'xaxis') { // Should not be any, but just in case
                delete currentLayout[key];
            }            
        });
        window.activeIndicatorsState = []; // Update global state
    }

    // Apply X-axis range and tick configuration to the designated primary X-axis
    const primaryXAxisLayoutKey = 'xaxis'; // Always use the main xaxis object
    if (window.currentXAxisRange) {
        currentLayout[primaryXAxisLayoutKey].range = [new Date(window.currentXAxisRange[0]), new Date(window.currentXAxisRange[1])];
        currentLayout[primaryXAxisLayoutKey].autorange = false;
        currentLayout[primaryXAxisLayoutKey].dtick = null;
        currentLayout[primaryXAxisLayoutKey].tickvals = null;
        currentLayout[primaryXAxisLayoutKey].ticktext = null;
        currentLayout[primaryXAxisLayoutKey].tickformat = '%H:%M\n%b %d';
    } else { // Range selected from dropdown
        currentLayout[primaryXAxisLayoutKey].range = [new Date(fromTs * 1000), new Date(toTs * 1000)];
        currentLayout[primaryXAxisLayoutKey].autorange = false;
        switch(resolution) {
            case '1m': currentLayout[primaryXAxisLayoutKey].dtick = 60 * 1000; currentLayout[primaryXAxisLayoutKey].tickformat = '%H:%M\n%b %d'; break;
            case '5m': currentLayout[primaryXAxisLayoutKey].dtick = 5 * 60 * 1000; currentLayout[primaryXAxisLayoutKey].tickformat = '%H:%M\n%b %d'; break;
            case '1h': currentLayout[primaryXAxisLayoutKey].dtick = 60 * 60 * 1000; currentLayout[primaryXAxisLayoutKey].tickformat = '%H:%M\n%b %d'; break;
            case '1d': currentLayout[primaryXAxisLayoutKey].dtick = 86400000; currentLayout[primaryXAxisLayoutKey].tickformat = '%H:%M\n%b %d'; break;
            case '1w': currentLayout[primaryXAxisLayoutKey].dtick = 7 * 86400000; currentLayout[primaryXAxisLayoutKey].tickformat = '%b %d\n%Y'; break;
            default: currentLayout[primaryXAxisLayoutKey].dtick = null; currentLayout[primaryXAxisLayoutKey].tickformat = null;
        }
        if (tickValues.length > 0) {
            currentLayout[primaryXAxisLayoutKey].tickvals = tickValues.map(d => d.getTime());
            currentLayout[primaryXAxisLayoutKey].ticktext = tickTexts;
        } else {
            currentLayout[primaryXAxisLayoutKey].tickvals = null;
            currentLayout[primaryXAxisLayoutKey].ticktext = null;
        }
    }

    console.log('[DEBUG chartUpdater] About to call Plotly.react with layout ranges: ',currentLayout.yaxis.range)
    console.log('[DEBUG chartUpdater] About to call Plotly.react. Number of indicator traces:', indicatorTraces.length);
    console.log('[DEBUG chartUpdater] currentLayout before Plotly.react:', JSON.stringify(currentLayout, null, 2)); // Potentially very verbose, but necessary for debugging
    // Log the actual data being sent for indicator traces
    if (indicatorTraces.length > 0) {
        console.log('[DEBUG chartUpdater] Indicator Traces Data (first 5 y-values shown):', JSON.parse(JSON.stringify(indicatorTraces.map(t => ({name: t.name, yaxis: t.yaxis, x_length: t.x?.length, y_length: t.y?.length, y_sample: t.y?.slice(0,5) })))));
    }

    const allTraces = [newTrace, ...indicatorTraces];
    currentLayout.shapes = currentLayout.shapes || [];
    try {
        const drawings = await getDrawings(symbol); // Assumes getDrawings is global from api.js
        console.log(`Loaded ${drawings.length} drawings for ${symbol} (post-indicator setup).`);
        drawings.forEach(drawing => {
            // Adjust subplot name to match new main chart y-axis if needed
            let adjustedSubplotName = drawing.subplot_name; // This will be 'symbol' for main chart drawings
            if (activeIndicatorIds.length > 0 && drawing.subplot_name === symbol) { 
                adjustedSubplotName = `${symbol}-main`; // A temporary name to map to mainChartYAxisRef
            }

            // When calling getPlotlyRefsFromSubplotName, it needs to know the *actual* y-axis ref
            // the main chart is on, which is `mainChartYAxisRef` (e.g., yaxisN)
            // And for indicators, it needs their respective calculated y-axis refs.
            const refs = getPlotlyRefsFromSubplotName(adjustedSubplotName);
            
            if (refs && refs.xref && refs.yref) { // Only add shape if valid refs were found
                const shape = {
                    backendId: drawing.id,
                    type: drawing.type, // e.g., 'line'
                    xref: refs.xref,
                    yref: refs.yref,
                    x0: new Date(drawing.start_time * 1000),
                    y0: drawing.start_price,
                    x1: new Date(drawing.end_time * 1000),
                    y1: drawing.end_price,
                    line: { color: DEFAULT_DRAWING_COLOR, width: 2, layer: 'above' }, // DEFAULT_DRAWING_COLOR from config.js
                    editable: false, // Will be managed by updateShapeVisuals
                    name: `drawing-${drawing.id}` // Optional, for easier debugging
                };
                console.log(`[DEBUG chartUpdater] Adding drawing ${drawing.id} to ${refs.xref}/${refs.yref}`);
                currentLayout.shapes.push(shape);
            } else {
                console.log(`[DEBUG chartUpdater] Skipping drawing for ${adjustedSubplotName} (original: ${drawing.subplot_name}) as its indicator is not active or refs could not be determined.`);
            }
        });
        console.log(`Added ${drawings.length} saved drawing shapes to layout (post-indicator setup).`);
    } catch (error) {
        console.error('Error loading drawings (post-indicator setup):', error);
    }

    // Fetch and add buy/sell event markers from open trades
    try {
        const tradeHistory = await window.getOrderHistory(symbol); // Explicitly use window.getOrderHistory
        console.log(`Loaded ${tradeHistory.length} open trades for ${symbol}.`);


        const buyEventX = [];
        const buyEventUpdatedTime= [];
        const buyEventY = [];
        const buyEventCustomData = []; // New: To store additional data for hover
        const sellEventX = [];
        const sellEventUpdatedTime = [];
        const sellEventY = [];
        const sellEventCustomData = []; // New: To store additional data for hover

        tradeHistory.forEach(history => {

            // Ensure all relevant fields are parsed correctly, handling potential empty strings
            const size = parseFloat(history.size);
            const takeProfit = history.takeProfit || ''; // Can be empty string
            const stopLoss = history.stopLoss || ''; // Can be empty string
            const leverage = history.leverage || '';
            const positionValue = parseFloat(history.positionValue);
            const unrealisedPnl = parseFloat(history.unrealisedPnl);
            
            // createdTime is in milliseconds from Bybit - adapt to CET+1
            const createdTimeUTC = new Date(parseInt(history.createdTime));
            const updatedTimeUTC = new Date(parseInt(history.updatedTime));
            const cetOffset = 60 * 60 * 1000; // CET is UTC+1
            //const entryTime = new Date(createdTimeUTC.getTime() + cetOffset);
            entryCreatedTime = createdTimeUTC; 
            entryUpdatedTime = updatedTimeUTC;


            const entryPrice = parseFloat(history.avgPrice); // Corrected from avgEntryPrice to avgPrice
            const side = history.side; // "Buy" or "Sell"

            // Creating the customDataEntry object
            const customDataEntry = {
                side: side,
                size: isNaN(size) ? 'N/A' : size.toFixed(3),
                takeProfit: takeProfit,
                stopLoss: stopLoss,
                leverage: leverage,
                positionValue: isNaN(positionValue) ? 'N/A' : positionValue.toFixed(2),
                unrealisedPnl: isNaN(unrealisedPnl) ? 'N/A' : unrealisedPnl.toFixed(2)

            };

            if (side === "Buy") {
                buyEventX.push(createdTimeUTC);
                buyEventY.push(entryPrice);
                buyEventCustomData.push(customDataEntry); // <-- Custom data for Buy markers
            } else if (side === "Sell") {
                sellEventX.push(createdTimeUTC);
                sellEventY.push(entryPrice);
                sellEventCustomData.push(customDataEntry); // <-- Custom data for Sell markers
            }
        });


        if (buyEventX.length > 0) {
            allTraces.push({
                x: buyEventX, y: buyEventY, type: 'scatter', mode: 'markers', name: 'Buy Event', showlegend: false,
                marker: { symbol: window.BUY_EVENT_MARKER_SYMBOL, color: window.BUY_EVENT_MARKER_COLOR, size: 16 },
                xaxis: 'x', yaxis: 'y', isSystemShape: true, // Increased marker size
                customdata: buyEventCustomData, // <-- Attached here
                hovertemplate: `<b>%{fullData.name}</b><br>` +
                            `createdTime: %{x|%Y-%m-%d %H:%M:%S}<br>` +
                            `Price: %{y:.2f}<br>` +                            
                            `Side: %{customdata.side}<br>` +
                            `Size: %{customdata.size}<br>` +
                            `Leverage: %{customdata.leverage}<br>` +
                            `Position Value: %{customdata.positionValue}<br>` +
                            `Unrealized PnL: %{customdata.unrealisedPnl}<br>` +
                            `TP: %{customdata.takeProfit}<br>` +
                            `SL: %{customdata.stopLoss}<extra></extra>` // <-- Hover template defined here
            });
        }
        if (sellEventX.length > 0) {

            allTraces.push({
                x: sellEventX, y: sellEventY, type: 'scatter', mode: 'markers', name: 'Sell Event',
                marker: { symbol: window.SELL_EVENT_MARKER_SYMBOL, color: window.SELL_EVENT_MARKER_COLOR, size: 10 },
                xaxis: 'x', yaxis: 'y', isSystemShape: SVGComponentTransferFunctionElement,
                customdata: sellEventCustomData, // <-- Attached here
                hovertemplate: `<b>%{fullData.name}</b><br>` +
                            `Time: %{x|%Y-%m-%d %H:%M:%S}<br>` +
                            `Price: %{y:.2f}<br>` +
                            `Side: %{customdata.side}<br>` +
                            `Size: %{customdata.size}<br>` +
                            `Leverage: %{customdata.leverage}<br>` +
                            `Position Value: %{customdata.positionValue}<br>` +
                            `Unrealized PnL: %{customdata.unrealisedPnl}<br>` +
                            `TP: %{customdata.takeProfit}<br>` +
                            `SL: %{customdata.stopLoss}<extra></extra>` // <-- Hover template defined here               
            });
        }
    } catch (error) {
        console.error('Error loading open trades for markers:', error);
    }


    const showAgentTradesCheckbox = document.getElementById('showAgentTradesCheckbox');
    if (showAgentTradesCheckbox && showAgentTradesCheckbox.checked) {
        // Fetch and add agent trade markers from gemini_RL.py
        try {
            const agentTrades = await getAgentTrades(symbol, fromTs, toTs);
            console.log(`Loaded ${agentTrades.length} agent trades for ${symbol}.`);

            const buyMarkers = { x: [], y: [], customdata: [] };
            const sellMarkers = { x: [], y: [], customdata: [] };
            const closeLongMarkers = { x: [], y: [], customdata: [] };
            const closeShortMarkers = { x: [], y: [], customdata: [] };

            agentTrades.forEach(trade => {
                const tradeTime = new Date(trade.timestamp * 1000);
                const tradePrice = parseFloat(trade.price);
                const customData = {
                    action: trade.action,
                    price: tradePrice.toFixed(2),
                    networth: parseFloat(trade.networth).toFixed(2),
                    reason: trade.close_reason || 'N/A'
                };

                switch (trade.action) {
                    case 'buy':
                        buyMarkers.x.push(tradeTime);
                        buyMarkers.y.push(tradePrice);
                        buyMarkers.customdata.push(customData);
                        break;
                    case 'sell':
                        sellMarkers.x.push(tradeTime);
                        sellMarkers.y.push(tradePrice);
                        sellMarkers.customdata.push(customData);
                        break;
                    case 'close_long':
                        closeLongMarkers.x.push(tradeTime);
                        closeLongMarkers.y.push(tradePrice);
                        closeLongMarkers.customdata.push(customData);
                        break;
                    case 'close_short':
                        closeShortMarkers.x.push(tradeTime);
                        closeShortMarkers.y.push(tradePrice);
                        closeShortMarkers.customdata.push(customData);
                        break;
                }
            });

            if (buyMarkers.x.length > 0) {
                allTraces.push({
                    x: buyMarkers.x, y: buyMarkers.y, type: 'scatter', mode: 'markers', name: 'Agent Buy', showlegend: false,
                    marker: { symbol: 'triangle-up', color: 'rgba(0, 255, 0, 0.8)', size: 10, line: { color: 'darkgreen', width: 1 } },
                    xaxis: 'x', yaxis: 'y', isSystemShape: true,
                    customdata: buyMarkers.customdata,
                    hovertemplate: `<b>Agent Buy</b><br>Price: %{customdata.price}<br>Networth: %{customdata.networth}<br>Reason: %{customdata.reason}<extra></extra>`
                });
            }
            if (sellMarkers.x.length > 0) {
                allTraces.push({
                    x: sellMarkers.x, y: sellMarkers.y, type: 'scatter', mode: 'markers', name: 'Agent Sell', showlegend: false,
                    marker: { symbol: 'triangle-down', color: 'rgba(255, 0, 0, 0.8)', size: 10, line: { color: 'darkred', width: 1 } },
                    xaxis: 'x', yaxis: 'y', isSystemShape: true,
                    customdata: sellMarkers.customdata,
                    hovertemplate: `<b>Agent Sell</b><br>Price: %{customdata.price}<br>Networth: %{customdata.networth}<br>Reason: %{customdata.reason}<extra></extra>`
                });
            }
            if (closeLongMarkers.x.length > 0) {
                allTraces.push({
                    x: closeLongMarkers.x, y: closeLongMarkers.y, type: 'scatter', mode: 'markers', name: 'Agent Close Long', showlegend: false,
                    marker: { symbol: 'square', color: 'rgba(0, 255, 0, 0.5)', size: 8 },
                    xaxis: 'x', yaxis: 'y', isSystemShape: true,
                    customdata: closeLongMarkers.customdata,
                    hovertemplate: `<b>Close Long</b><br>Price: %{customdata.price}<br>Networth: %{customdata.networth}<br>Reason: %{customdata.reason}<extra></extra>`
                });
            }
            if (closeShortMarkers.x.length > 0) {
                allTraces.push({
                    x: closeShortMarkers.x, y: closeShortMarkers.y, type: 'scatter', mode: 'markers', name: 'Agent Close Short', showlegend: false,
                    marker: { symbol: 'square', color: 'rgba(255, 0, 0, 0.5)', size: 8 },
                    xaxis: 'x', yaxis: 'y', isSystemShape: true,
                    customdata: closeShortMarkers.customdata,
                    hovertemplate: `<b>Close Short</b><br>Price: %{customdata.price}<br>Networth: %{customdata.networth}<br>Reason: %{customdata.reason}<extra></extra>`
                });
            }
        } catch (error) {
            console.error('Error loading agent trades for markers:', error);
        }
    }

    // Fetch and add buy signals
    try {
        const buySignalsResponse = await fetch(`/get_buy_signals/${symbol}?resolution=${resolution}&from_ts=${fromTs}&to_ts=${toTs}`);
        if (buySignalsResponse.ok) {
            const buySignalsData = await buySignalsResponse.json();
            if (buySignalsData && buySignalsData.status === 'success' && Array.isArray(buySignalsData.signals) && buySignalsData.signals.length > 0) {
                const buySignalX = [];
                const buySignalY = [];
                const buySignalCustomData = [];

                buySignalsData.signals.forEach(signal => {
                    buySignalX.push(new Date(signal.timestamp * 1000));
                    buySignalY.push(signal.price);
                    buySignalCustomData.push({
                        rsi: (signal.rsi !== null && signal.rsi !== undefined) ? signal.rsi.toFixed(2) : 'N/A',
                        stoch_k: (signal.stoch_rsi_k !== null && signal.stoch_rsi_k !== undefined) ? signal.stoch_rsi_k.toFixed(2) : 'N/A'
                    });
                });

                allTraces.push({
                    x: buySignalX,
                    y: buySignalY,
                    type: 'scatter',
                    mode: 'markers',
                    name: 'Buy Signal',
                    showlegend: false,
                    marker: { symbol: 'arrow', color: 'green', size: 16, line: { color: 'darkgreen', width: 2 } },
                    xaxis: 'x', yaxis: 'y', isSystemShape: true,
                    customdata: buySignalCustomData,
                    hovertemplate: `<b>Buy Signal</b><br>Time: %{x|%Y-%m-%d %H:%M:%S}<br>Price: %{y:.2f}<br>RSI: %{customdata.rsi}<br>StochK: %{customdata.stoch_k}<extra></extra>`
                });
                console.log(`Added ${buySignalsData.signals.length} buy signal markers to the chart.`);
            }
        } else {
            console.warn("Failed to fetch buy signals:", await buySignalsResponse.text());
        }
    } catch (error) {
        console.error('Error fetching or processing buy signals:', error);
    }

    // Fetch and add trend drawings
    /*
    try {
        const trendDrawingsResponse = await fetch(`/get_trend_drawings/${symbol}?resolution=${resolution}&from_ts=${fromTs}&to_ts=${toTs}`);
        if (trendDrawingsResponse.ok) {
            const trendDrawingsData = await trendDrawingsResponse.json();
            if (trendDrawingsData.status === 'success' && Array.isArray(trendDrawingsData.drawings)) {
                trendDrawingsData.drawings.forEach(trend => {
                    let yRefToUse = 'y'; // Default to main price y-axis (first subplot if grid is used)
                    if (trend.y_axis_id !== 'price' && window.activeIndicatorsState) {
                        const indicatorState = window.activeIndicatorsState.find(ind => ind.id === trend.y_axis_id);
                        if (indicatorState && indicatorState.yAxisRef) {
                            yRefToUse = indicatorState.yAxisRef; // e.g., 'y2', 'y3'
                        } else {
                            console.warn(`Trend line for y_axis_id '${trend.y_axis_id}' requested, but indicator not active or yAxisRef not found. Defaulting to main y-axis.`);
                        }
                    }

                    const trendShape = {
                        type: 'line',
                        xref: 'x', // All trends share the main x-axis (or its matched counterparts)
                        yref: yRefToUse,
                        x0: new Date(trend.x0_ts * 1000),
                        y0: trend.y0_val,
                        x1: new Date(trend.x1_ts * 1000),
                        y1: trend.y1_val,
                        line: {
                            color: trend.line_style?.color || (trend.y_axis_id === 'rsi' ? 'rgba(229, 255, 0, 0.9)' : 'rgba(180, 173, 70, 0.6)'),
                            width: trend.line_style?.width || 2.5
                        },
                        name: trend.name || `${trend.y_axis_id}-${trend.trend_type}`,
                        isSystemShape: true,
                        editable: false,
                        layer: 'above'
                    };
                    currentLayout.shapes.push(trendShape);
                });
                console.log(`Added ${trendDrawingsData.drawings.length} trend drawing shapes to layout.`);
            }
        } else { console.warn("Failed to fetch trend drawings:", await trendDrawingsResponse.text()); }
    } catch (error) { console.error('Error fetching or processing trend drawings:', error); }
    */

    Plotly.react('chart', allTraces, currentLayout, config); // Assumes config is global

    if (window.gd && window.gd._fullLayout) {
        const fl = window.gd._fullLayout;
        const yAxesToLog = Object.keys(fl)
            .filter(k => k.startsWith('yaxis') && fl[k] && typeof fl[k]._offset === 'number')
            .sort((a, b) => {
                const numA = (a === 'yaxis') ? 1 : parseInt(a.substring(5)) || Infinity;
                const numB = (b === 'yaxis') ? 1 : parseInt(b.substring(5)) || Infinity;
                return numA - numB;
            });

        yAxesToLog.forEach(yKey => {
            const yAxis = fl[yKey];
            if (yAxis) {
                console.log(`  [DEBUG chartUpdater] ${yKey} (_id: ${yAxis._id}): _offset=${yAxis._offset?.toFixed(2)}, _length=${yAxis._length?.toFixed(2)}, domain=${JSON.stringify(yAxis.domain)}, yBand=[${yAxis._offset?.toFixed(2)}, ${(yAxis._offset + yAxis._length)?.toFixed(2)}]`);
            }
        });
        console.log(`  [DEBUG chartUpdater] fullLayout.height = ${fl.height?.toFixed(2)}`);
        if(fl.grid) console.log(`  [DEBUG chartUpdater] _fullLayout.grid reported:`, JSON.parse(JSON.stringify(fl.grid)));
    } else {
        console.log('[DEBUG chartUpdater] window.gd._fullLayout not available after react.');
    }

    if (window.liveDataCheckbox.checked) { // Assumes liveDataCheckbox is global
        const currentSymbolForStreamCheck = window.symbolSelect.value;
        // liveWebSocket and currentSymbolForStream are global state from state.js
        if (!liveWebSocket || liveWebSocket.readyState !== WebSocket.OPEN || currentSymbolForStream !== currentSymbolForStreamCheck) {
            console.log('[updateChart] Live data ON. Setting up or re-establishing WebSocket for', currentSymbolForStreamCheck);
            setupWebSocket(currentSymbolForStreamCheck); // from liveData.js
        } else {
            console.log('[updateChart] Live data ON. WebSocket already connected for', currentSymbolForStreamCheck);
            // Price line will be updated by incoming WebSocket messages via handleRealtimeKline
        }
    } else {
        console.log(`[updateChart] Live data OFF. Ensuring WebSocket is closed.`);
        closeWebSocket("Live data disabled and chart updated."); // Assumes closeWebSocket is global
    }
}

async function getAgentTrades(symbol, from_ts, to_ts) {
    const url = `/get_agent_trades?symbol=${symbol}&from_ts=${from_ts}&to_ts=${to_ts}`;
    try {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`Failed to fetch agent trades: ${response.status} ${response.statusText}`);
        }
        const data = await response.json();
        if (data.status === 'success') {
            return data.trades;
        } else {
            console.warn(`Could not get agent trades: ${data.message || 'Unknown error'}`);
            return [];
        }
    } catch (error) {
        console.error('Error fetching agent trades:', error);
        return [];
    }
}



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
            if (logElement.scrollTop < 10) { // A small tolerance
                logElement.scrollTop = 0;
            }

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
