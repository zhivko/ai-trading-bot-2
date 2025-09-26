window.newHoveredShapeId = null;
// Removed lastClickTime and lastClickedShapeId - long press functionality has been disabled

function updateOrAddCrosshairVLine(gd, xDataValue, doRelayout = true) {
    if (!gd || !gd.layout || !gd.layout.xaxis || !xDataValue) {
        return;
    }

    let shapes = gd.layout.shapes || [];
    shapes = shapes.filter(shape => shape.name !== CROSSHAIR_VLINE_NAME); // From config.js

    const lineDefinition = {
        type: 'line',
        name: CROSSHAIR_VLINE_NAME, // From config.js
        isSystemShape: true, // Mark as a system shape
        xref: 'x',
        yref: 'paper',
        x0: xDataValue,
        y0: 0,
        x1: xDataValue,
        y1: 1,
        line: {
            color: 'rgba(100, 100, 100, 0.6)',
            width: 1,
            dash: 'dash'
        },
        layer: 'above',
        editable: false // Explicitly make crosshair not editable
    };
    shapes.push(lineDefinition);

    if (doRelayout) {
        Plotly.relayout(gd, { shapes: shapes });
    } else {
        gd.layout.shapes = shapes;
    }
}


function colorTheLine(eventParam)
{
        /*
        console.groupCollapsed('[NativeMousemove] Event Processing');
        console.log('[DEBUG] colorTheLine called with event:', eventParam ? 'event provided' : 'no event');
        console.log('[colorTheLine] Current dragmode:', window.gd ? window.gd.layout.dragmode : 'N/A');
        */

        // Reset newHoveredShapeId at the start of each call
        window.newHoveredShapeId = null;

        // Skip if a shape is currently being dragged
        if (window.isDraggingShape) {
            console.log('[DEBUG] colorTheLine skipping because shape is being dragged');
            return;
        }

        // Use the passed event or fall back to global event
        const currentEvent = eventParam || event;

        if (!window.gd || !window.gd.layout) {
            //console.log('[NativeMousemove] Exiting early: Chart not ready.');
            if (window.hoveredShapeBackendId !== null) { // Assumes hoveredShapeBackendId is global from state.js
                window.hoveredShapeBackendId = null;
                if (typeof updateShapeVisuals === 'function') {
                    updateShapeVisuals();
                }
            }
            //console.groupEnd();
            return;
        }

        if (currentEvent && (currentEvent.target.closest('.modebar') ||
            currentEvent.target.closest('select') ||
            currentEvent.target.closest('input') ||
            currentEvent.target.closest('.rangeslider') ||
            currentEvent.target.closest('.legend'))) {
            //console.log('[NativeMousemove] Exiting early: Mouse over Plotly UI element.');
            //console.groupEnd();
            return;
        }

        const rect = window.chartDiv.getBoundingClientRect();

        // Try to get mouse coordinates from event, or use a fallback method
        let mouseX_div, mouseY_div;
        if (currentEvent && currentEvent.clientX !== undefined && currentEvent.clientY !== undefined &&
            currentEvent.clientX !== 0 && currentEvent.clientY !== 0) {
            mouseX_div = currentEvent.clientX - rect.left;
            mouseY_div = currentEvent.clientY - rect.top;
            // console.log(`[colorTheLine] Using event coordinates: clientX=${currentEvent.clientX}, clientY=${currentEvent.clientY}`);
        } else if (currentEvent && currentEvent.touches && currentEvent.touches.length > 0) {
            // Handle touch events
            const touch = currentEvent.touches[0] || currentEvent.changedTouches[0];
            mouseX_div = touch.clientX - rect.left;
            mouseY_div = touch.clientY - rect.top;
            // console.log(`[colorTheLine] Using touch coordinates: clientX=${touch.clientX}, clientY=${touch.clientY}`);
        } else {
            // Fallback: try to get mouse position from window.event or other methods
            const globalEvent = window.event;
            if (globalEvent && globalEvent.clientX !== undefined && globalEvent.clientY !== undefined &&
                globalEvent.clientX !== 0 && globalEvent.clientY !== 0) {
                mouseX_div = globalEvent.clientX - rect.left;
                mouseY_div = globalEvent.clientY - rect.top;
                // console.log(`[colorTheLine] Using global event coordinates: clientX=${globalEvent.clientX}, clientY=${globalEvent.clientY}`);
            } else {
                // Try to get mouse position from document.elementFromPoint or other methods
                try {
                    const centerX = rect.left + rect.width/2;
                    const centerY = rect.top + rect.height/2;
                    const elementsAtCenter = document.elementsFromPoint(centerX, centerY);
                    if (elementsAtCenter && elementsAtCenter.length > 0) {
                        mouseX_div = rect.width / 2;
                        mouseY_div = rect.height / 2;
                        // console.log(`[colorTheLine] Using center coordinates as fallback: x=${mouseX_div}, y=${mouseY_div}`);
                    } else {
                        throw new Error("No elements found at center");
                    }
                } catch (e) {
                    // Last resort: assume center of chart for testing
                    mouseX_div = rect.width / 2;
                    mouseY_div = rect.height / 2;
                    // console.log(`[colorTheLine] Using fallback center coordinates: x=${mouseX_div}, y=${mouseY_div}, error: ${e.message}`);
                }
            }
        }

        //console.log(`[colorTheLine] Chart div rect: left=${rect.left}, top=${rect.top}, width=${rect.width}, height=${rect.height}`);
        //console.log(`[colorTheLine] Mouse relative to div: x=${mouseX_div}, y=${mouseY_div}`);

        if (!window.gd._fullLayout || typeof window.gd._fullLayout.height === 'undefined' || !window.gd._fullLayout.yaxis || typeof window.gd._fullLayout.yaxis._length === 'undefined') {
            // console.log("[colorTheLine] Chart layout not ready, skipping hover detection");
            return;
        }

        // Convert DOM coordinates to Plotly paper coordinates
        // Paper coordinates are relative to the full chart area (including margins)
        const plotMargin = window.gd._fullLayout.margin;
        const mouseX_paper = mouseX_div;
        const mouseY_paper = mouseY_div;

        // console.log(`[colorTheLine] Chart dimensions: width=${window.gd._fullLayout.width}, height=${window.gd._fullLayout.height}`);
        // console.log(`[colorTheLine] Plot margins: l=${plotMargin.l}, r=${plotMargin.r}, t=${plotMargin.t}, b=${plotMargin.b}`);
        // console.log(`[colorTheLine] Mouse in paper coordinates: x=${mouseX_paper}, y=${mouseY_paper}`);

        // Check if mouse is within the chart's plotting area (with some tolerance for edge cases)
        const tolerance = 10; // Allow 10px tolerance for edge cases
        const isOutsideBounds = mouseX_paper < -tolerance ||
                               mouseX_paper > window.gd._fullLayout.width + tolerance ||
                               mouseY_paper < -tolerance ||
                               mouseY_paper > window.gd._fullLayout.height + tolerance;

        // console.log(`[colorTheLine] Bounds check: mouseX=${mouseX_paper}, mouseY=${mouseY_paper}, width=${window.gd._fullLayout.width}, height=${window.gd._fullLayout.height}, tolerance=${tolerance}, isOutside=${isOutsideBounds}`);

        if (isOutsideBounds) {
            // console.log("[colorTheLine] Mouse is outside the chart's plotting area. Ignoring.");
            if (window.hoveredShapeBackendId !== null) {
                window.hoveredShapeBackendId = null;
                if (typeof debouncedUpdateShapeVisuals === 'function') {
                    debouncedUpdateShapeVisuals();
                }
            }
            return;
        }

        const mainYAxis = window.gd._fullLayout.yaxis;
        const plotAreaHeight = mainYAxis._length;
        const mouseX_plotArea = mouseX_div - plotMargin.l;
        const mouseY_plotArea = plotAreaHeight - (mouseY_div - plotMargin.t);
        let minDistanceSq = Infinity;
        const HOVER_THRESHOLD_PIXELS_SQ = 15 * 15;

        const hoveredSubplotRefs = getSubplotRefsAtPaperCoords(mouseX_paper, mouseY_paper, window.gd._fullLayout);
        if (hoveredSubplotRefs) {
            //console.log(`[NativeMousemove] Hover detected in subplot: xref=${hoveredSubplotRefs.xref}, yref=${hoveredSubplotRefs.yref}`);
        } else {
            //console.log(`[NativeMousemove] Hover detected outside any known subplot area.`);
            if (window.hoveredShapeBackendId !== null) {
                window.hoveredShapeBackendId = null;
                if (typeof updateShapeVisuals === 'function') {
                    updateShapeVisuals();
                }
            }
        }

        const currentShapes = window.gd.layout.shapes || [];
        //console.log(`[colorTheLine] Checking ${currentShapes.length} shapes for hover detection`);
        console.groupCollapsed("Checking shapes for hover detection");
        for (let i = 0; i < currentShapes.length; i++) {
            const shape = currentShapes[i];
            //console.log(`[colorTheLine] Shape ${i}: type=${shape.type}, id=${shape.id}, isSystemShape=${shape.isSystemShape}`);
            if (shape.type === 'line' && shape.id && !shape.isSystemShape) { // Ignore system shapes
                //console.group(`[colorTheLine] Processing Shape ${i} (ID: ${shape.id})`);
                //console.log(`[colorTheLine] Processing shape ${i} (ID: ${shape.id}) for hover detection`);
                const xrefKeyForFilter = getAxisLayoutKey(shape.xref, 'xaxis'); // Assumes getAxisLayoutKey is global
                const yrefKeyForFilter = getAxisLayoutKey(shape.yref, 'yaxis');
                const shapeXaxisForFilter = window.gd._fullLayout[xrefKeyForFilter];
                const shapeYaxisForFilter = window.gd._fullLayout[yrefKeyForFilter];

                if (!shapeXaxisForFilter || !shapeYaxisForFilter) continue;

                if (hoveredSubplotRefs) {
                    if (shapeXaxisForFilter._id !== hoveredSubplotRefs.xref || shapeYaxisForFilter._id !== hoveredSubplotRefs.yref) {
                        //console.log(`[NativeMousemove DEBUG] Skipping shape ${i} (ID: ${shape.id}, shape_xref: ${shape.xref}, shape_yref: ${shape.yref}) because its axes (_id: ${shapeXaxisForFilter._id}, ${shapeYaxisForFilter._id}) don't match hovered subplot axes (hover_xref: ${hoveredSubplotRefs.xref}, hover_yref: ${hoveredSubplotRefs.yref}).`);
                        continue;
                    }
                } else {
                    continue;
                }

                const xrefKey = getAxisLayoutKey(shape.xref, 'xaxis');
                const yrefKey = getAxisLayoutKey(shape.yref, 'yaxis');
                const shapeXaxis = window.gd._fullLayout[xrefKey];
                const shapeYaxis = window.gd._fullLayout[yrefKey];

                if (!shapeXaxis || !shapeYaxis || typeof shapeXaxis.d2p !== 'function' || typeof shapeYaxis.d2p !== 'function') {
                    //console.warn(`[NativeMousemove DEBUG] Could not find valid axes for shape ${i} (ID: ${shape.id}) with xref=${shape.xref}, yref=${shape.yref}. Skipping hover test.`);
                    continue;
                }

                /*
                console.group(`[NativeMousemove DEBUG] Checking Shape ${i} (ID: ${shape.id})`);
                console.log(`Mouse Paper Coords: Px=${mouseX_paper.toFixed(2)}, Py=${mouseY_paper.toFixed(2)}`);
                console.log(`Shape Data Coords: x0=${shape.x0}, y0=${shape.y0}, x1=${shape.x1}, y1=${shape.y1}`);
                console.log(`Shape Axes: xref=${shapeXaxis._id}, yref=${shapeYaxis._id}`);
                */

                let shapeX0Val = (shapeXaxis.type === 'date') ? ((shape.x0 instanceof Date) ? shape.x0.getTime() : new Date(shape.x0).getTime()) : Number(shape.x0);
                let shapeX1Val = (shapeXaxis.type === 'date') ? ((shape.x1 instanceof Date) ? shape.x1.getTime() : new Date(shape.x1).getTime()) : Number(shape.x1);
                const p0y_subplot_relative_hover = shapeYaxis.d2p(shape.y0);
                const p1y_subplot_relative_hover = shapeYaxis.d2p(shape.y1);
                const p0x_subplot_relative_hover = shapeXaxis.d2p(shapeX0Val);
                const p1x_subplot_relative_hover = shapeXaxis.d2p(shapeX1Val);

                const p0 = { x: shapeXaxis._offset + p0x_subplot_relative_hover, y: shapeYaxis._offset + p0y_subplot_relative_hover };
                const p1 = { x: shapeXaxis._offset + p1x_subplot_relative_hover, y: shapeYaxis._offset + p1y_subplot_relative_hover };
                //console.log(`Shape Pixel Endpoints (Paper Relative): P0=(${p0.x.toFixed(2)},${p0.y.toFixed(2)}), P1=(${p1.x.toFixed(2)},${p1.y.toFixed(2)}). Mouse: (${mouseX_paper.toFixed(2)},${mouseY_paper.toFixed(2)})`);

                if (isNaN(p0.x) || isNaN(p0.y) || isNaN(p1.x) || isNaN(p1.y) || !isFinite(p0.x) || !isFinite(p0.y) || !isFinite(p1.x) || !isFinite(p1.y)) {
                    /*console.warn(`[NativeMousemove DEBUG] Shape ${i} (ID: ${shape.id}) had NaN/Infinite pixel coordinates. Skipping.`);
                    console.groupEnd();
                    */
                    continue;
                }
                const distSq = distToSegmentSquared({ x: mouseX_paper, y: mouseY_paper }, p0, p1); // From utils.js
                // console.log(`[colorTheLine] Shape ${i} (ID: ${shape.id}) - DistSq: ${distSq.toFixed(2)}, Threshold: ${HOVER_THRESHOLD_PIXELS_SQ}, Mouse: (${mouseX_paper.toFixed(2)}, ${mouseY_paper.toFixed(2)}), Shape endpoints: (${p0.x.toFixed(2)}, ${p0.y.toFixed(2)}) to (${p1.x.toFixed(2)}, ${p1.y.toFixed(2)})`);
                if (distSq < HOVER_THRESHOLD_PIXELS_SQ && distSq < minDistanceSq) {
                    minDistanceSq = distSq;
                    window.newHoveredShapeId = shape.id;
                   // console.log(`[colorTheLine] Shape ${i} (ID: ${shape.id}) is now the closest hovered shape!`);
                }
            }
        }
        console.groupEnd(); // End group for this shape

        //console.log(`[DEBUG] colorTheLine Final: hoveredShapeBackendId=${window.hoveredShapeBackendId}, newHoveredShapeId=${window.newHoveredShapeId}`);
        if (window.hoveredShapeBackendId !== window.newHoveredShapeId) {
            //console.log(`[DEBUG] colorTheLine Updated hoveredShapeBackendId to: ${window.newHoveredShapeId}`);
                window.hoveredShapeBackendId = window.newHoveredShapeId;
                if(window.hoveredShapeBackendId) {
                    //console.log(`[DEBUG] colorTheLine Calling findAndupdateSelectedShapeInfoPanel with ID: ${window.hoveredShapeBackendId}`);
                    findAndupdateSelectedShapeInfoPanel(window.hoveredShapeBackendId);
                }
                /*
                console.log(`[DEBUG] colorTheLine Calling debouncedUpdateShapeVisuals`);
                console.log(`[DEBUG] colorTheLine - typeof debouncedUpdateShapeVisuals:`, typeof debouncedUpdateShapeVisuals);
                console.log(`[DEBUG] colorTheLine - typeof window.debouncedUpdateShapeVisuals:`, typeof window.debouncedUpdateShapeVisuals);
                console.log(`[DEBUG] colorTheLine - debouncedUpdateShapeVisuals exists:`, !!window.debouncedUpdateShapeVisuals);
                */

                // Call updateShapeVisuals directly for immediate color changes
                if (typeof updateShapeVisuals === 'function') {
                    //console.log(`[DEBUG] colorTheLine - calling updateShapeVisuals directly for immediate update`);
                    updateShapeVisuals();
                } else {
                    //console.warn('[DEBUG] colorTheLine - updateShapeVisuals not available!');
                }
        } else {
            //console.log(`[DEBUG] colorTheLine No change in hovered shape ID`);
        }

        // Only clear shape ID if we're sure no shape should be hovered (mouse outside chart area)
        if (isOutsideBounds && window.hoveredShapeBackendId !== null) {
            // console.log(`[colorTheLine] Mouse outside bounds, clearing hovered shape`);
            window.hoveredShapeBackendId = null;
            if (typeof updateShapeVisuals === 'function') {
                updateShapeVisuals();
            }
        }

        // Crosshair logic - disabled on mobile devices for better touch performance
        if (!isMobileDevice()) {
            const mainXAxis = window.gd._fullLayout.xaxis;
            if (mainXAxis && typeof mainXAxis.p2d === 'function') {
                const xDataValueAtMouse = mainXAxis.p2d(mouseX_plotArea);
                if (xDataValueAtMouse !== undefined && xDataValueAtMouse !== null && !isNaN(new Date(xDataValueAtMouse).getTime())) {
                    const dateAtCursor = new Date(xDataValueAtMouse);
                    if (window.cursorTimeDisplay) { // Assumes cursorTimeDisplay is global
                        window.cursorTimeDisplay.textContent = dateAtCursor.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'medium' });
                    }
                    // DISABLED: Crosshair interferes with panning
                    // window.debouncedUpdateCrosshair(window.gd, dateAtCursor); // Assumes debouncedUpdateCrosshair is global

                    const mainTrace = window.gd.data[0];
                    let candleIndex = -1;
                    if (mainTrace && mainTrace.x && mainTrace.x.length > 0 && mainTrace.close && mainTrace.close.length > 0) {
                        const cursorTime = dateAtCursor.getTime();
                        for (let i = mainTrace.x.length - 1; i >= 0; i--) {
                            const candleTimeValue = mainTrace.x[i];
                            const candleTime = (candleTimeValue instanceof Date) ? candleTimeValue.getTime() : new Date(candleTimeValue).getTime();
                            if (!isNaN(candleTime) && candleTime <= cursorTime) {
                                candleIndex = i;
                                break;
                            }
                        }
                    }

                    if (candleIndex !== -1 && mainTrace.close[candleIndex] !== undefined) {
                        const closePrice = mainTrace.close[candleIndex];
                        window.cursorPriceDisplay.textContent = parseFloat(closePrice).toFixed(2); // Assumes cursorPriceDisplay is global
                    } else {
                        window.cursorPriceDisplay.textContent = 'N/A';
                    }
                } else {
                    // DISABLED: Crosshair interferes with panning
                    // removeCrosshairVLine(window.gd, true);
                    if (window.cursorTimeDisplay) window.cursorTimeDisplay.textContent = 'N/A';
                    if (window.cursorPriceDisplay) window.cursorPriceDisplay.textContent = 'N/A';
                }
            } else {
                // DISABLED: Crosshair interferes with panning
                // removeCrosshairVLine(window.gd, true);
                if (window.cursorTimeDisplay) window.cursorTimeDisplay.textContent = 'N/A';
                if (window.cursorPriceDisplay) window.cursorPriceDisplay.textContent = 'N/A';
            }
        } else {
            // On mobile, clear crosshair and cursor displays
            // DISABLED: Crosshair interferes with panning
            // removeCrosshairVLine(window.gd, true);
            if (window.cursorTimeDisplay) window.cursorTimeDisplay.textContent = 'N/A';
            if (window.cursorPriceDisplay) window.cursorPriceDisplay.textContent = 'N/A';
        }
        console.groupEnd(); // Close group at the end of the function
}

function getSubplotRefsAtPaperCoords(paperX, paperY, fullLayout) {
    //console.log(`[getSubplotRefsAtPaperCoords] Mouse Coords (Paper): Px=${paperX.toFixed(2)}, Py=${paperY.toFixed(2)}. Paper Height: ${fullLayout.height.toFixed(2)}`);
    const paperHeight = fullLayout.height;
    //console.log("fullLayout.grid");
    //console.log(fullLayout.grid);

    const yAxisKeys = Object.keys(fullLayout)
        .filter(key => key.startsWith('yaxis') && fullLayout[key] && typeof fullLayout[key]._offset === 'number')
        .sort((a, b) => {
            const numA = (a === 'yaxis') ? 1 : parseInt(a.substring(5)) || Infinity;
            const numB = (b === 'yaxis') ? 1 : parseInt(b.substring(5)) || Infinity;
            return numA - numB;
        });

    for (const yAxisKey of yAxisKeys) {
        const yAxis = fullLayout[yAxisKey];
        if (!yAxis || typeof yAxis._offset !== 'number' || typeof yAxis._length !== 'number') continue;
        // Corrected yMinPaper and yMaxPaper calculation:
        const yMinPaper = yAxis._offset;
        const yMaxPaper = yAxis._offset + yAxis._length;

        //Consider the possible inversion
        const isYInverted = yAxis.range && yAxis.range[0] > yAxis.range[1];
        const isMouseInYBand = paperY >= yMinPaper && paperY <= yMaxPaper;
        //console.log(`[getSubplotRefsAtPaperCoords] Checking ${yAxisKey} (${yAxis._id}): yBand=[${yMinPaper.toFixed(2)}, ${yMaxPaper.toFixed(2)}]. Mouse Py=${paperY.toFixed(2)}. Is Py in yBand? ${isMouseInYBand}`);

        // Additional logging for debugging
        /*
        console.log(`  [getSubplotRefsAtPaperCoords] ${yAxisKey}:`);
        console.log(`  - _offset: ${yAxis._offset}`);
        console.log(`  - _length: ${yAxis._length}`);
        console.log(`  - domain: ${JSON.stringify(yAxis.domain)}`);
        */

        if (isMouseInYBand) {
            let xAxisKeyToTest;
            if (yAxis._id === 'y') {
                //if (fullLayout['xaxis'] && typeof fullLayout['xaxis']._offset === 'number')
                xAxisKeyToTest = 'xaxis';
            } else {
                const potentialXAxisKey = 'xaxis' + yAxis._id.substring(1);
                if (fullLayout[potentialXAxisKey] && (fullLayout[potentialXAxisKey].anchor === yAxis._id || (typeof fullLayout[potentialXAxisKey].matches === 'undefined' && typeof fullLayout[potentialXAxisKey].domain !== 'undefined'))) {
                    xAxisKeyToTest = potentialXAxisKey;
                } else {
                    //xAxisKeyToTest = 'xaxis';
                    //console.warn(`Could not find X axis for ${yAxis._id}. Skipping.`);
                    continue;
                }
            }
            const xAxis = fullLayout[xAxisKeyToTest];
            if (xAxis && typeof xAxis._offset === 'number' && typeof xAxis._length === 'number') {
                //console.log(`[DEBUG] ${xAxisKeyToTest} (${xAxis._id}) _offset=${xAxis._offset}, _length=${xAxis._length}`); // ADD THIS LINE
                const xMinPaper = xAxis._offset;
                const xMaxPaper = xAxis._offset + xAxis._length;
                const isMouseInXBand = paperX >= xMinPaper && paperX <= xMaxPaper;
                //console.log(`[getSubplotRefsAtPaperCoords]   ↳ Corresp. ${xAxisKeyToTest} (${xAxis._id}): xBand=[${xMinPaper.toFixed(2)}, ${xMaxPaper.toFixed(2)}]. Mouse Px=${paperX.toFixed(2)}. Is Px in xBand? ${isMouseInXBand}`);

                if (isMouseInXBand) {
                    //console.log(`[getSubplotRefsAtPaperCoords]   ✓✓ MATCH FOUND for ${yAxis._id} and ${xAxis._id}`);
                    return { xref: xAxis._id, yref: yAxis._id };
                }
            }
        }
    }
    //console.log(`[getSubplotRefsAtPaperCoords] No subplot matched after checking all y-axes.`);
    return null;
}

function updateOrAddCrosshairVLine(gd, xDataValue, doRelayout = true) {
    if (!gd || !gd.layout || !gd.layout.xaxis || !xDataValue) {
        return;
    }
    let shapes = gd.layout.shapes || [];
    shapes = shapes.filter(shape => shape.name !== CROSSHAIR_VLINE_NAME); // From config.js

    const lineDefinition = {
        type: 'line',
        name: CROSSHAIR_VLINE_NAME, // From config.js
        isSystemShape: true, // Mark as a system shape
        xref: 'x',
        yref: 'paper',
        x0: xDataValue,
        y0: 0,
        x1: xDataValue,
        y1: 1,
        line: {
            color: 'rgba(100, 100, 100, 0.6)',
            width: 1,
            dash: 'dash'
        },
           layer: 'above',
           editable: false // Explicitly make crosshair not editable
    };
    shapes.push(lineDefinition);

    if (doRelayout) {
        Plotly.relayout(gd, { shapes: shapes });
    } else {
        gd.layout.shapes = shapes;
    }
}

function removeCrosshairVLine(gd, doRelayout = true) {
    if (!gd || !gd.layout || !gd.layout.shapes) return false;
    const initialLength = gd.layout.shapes.length;
    gd.layout.shapes = gd.layout.shapes.filter(shape => shape.name !== CROSSHAIR_VLINE_NAME); // From config.js
    const removed = gd.layout.shapes.length < initialLength;
    if (removed && doRelayout) {
        Plotly.relayout(gd, { shapes: gd.layout.shapes });
    }
    return removed;
}

// Make functions globally available for main.js
window.updateOrAddCrosshairVLine = updateOrAddCrosshairVLine;
window.initializeChartInteractions = initializeChartInteractions;

function handleShapeClick(event) {
    console.log('[DEBUG] handleShapeClick called with event:', event);
    console.log('[DEBUG] handleShapeClick - event type:', event.type, 'target:', event.target);

    // Only handle clicks if we're not in drawing mode and not dragging
    if (window.isDraggingShape || !window.gd) {
        console.log('[DEBUG] handleShapeClick early return - isDraggingShape:', window.isDraggingShape, 'window.gd exists:', !!window.gd);
        return;
    }

    // Check if this might be a buy signal click FIRST before checking other shapes
    if (window.gd && window.gd.layout && window.gd.layout.shapes) {
        const currentShapes = window.gd.layout.shapes;
        const rect = window.chartDiv.getBoundingClientRect();
        const mouseX_div = event.clientX - rect.left;
        const mouseY_div = event.clientY - rect.top;
        const plotMargin = window.gd._fullLayout.margin;
        const mouseX_paper = mouseX_div;
        const mouseY_paper = mouseY_div;

        console.log('[DEBUG] handleShapeClick - checking for buy signals first');

        // Look for buy signal shapes specifically
        for (let i = 0; i < currentShapes.length; i++) {
            const shape = currentShapes[i];

            // Check if this is a buy signal shape
            if (shape.name && shape.name.startsWith('buy_signal_') && shape.systemType === 'buy_signal' && shape.signalData) {
                console.log('[DEBUG] handleShapeClick - found buy signal shape:', shape.name);

                // Check if the click is close to this shape
                const xrefKey = getAxisLayoutKey(shape.xref, 'xaxis');
                const yrefKey = getAxisLayoutKey(shape.yref, 'yaxis');
                const shapeXaxis = window.gd._fullLayout[xrefKey];
                const shapeYaxis = window.gd._fullLayout[yrefKey];

                if (!shapeXaxis || !shapeYaxis || typeof shapeXaxis.d2p !== 'function' || typeof shapeYaxis.d2p !== 'function') {
                    continue;
                }

                let shapeX0Val = (shapeXaxis.type === 'date') ? ((shape.x0 instanceof Date) ? shape.x0.getTime() : new Date(shape.x0).getTime()) : Number(shape.x0);
                let shapeX1Val = (shapeXaxis.type === 'date') ? ((shape.x1 instanceof Date) ? shape.x1.getTime() : new Date(shape.x1).getTime()) : Number(shape.x1);

                const p0y = shapeYaxis.d2p(shape.y0);
                const p1y = shapeYaxis.d2p(shape.y1);
                const p0x = shapeXaxis.d2p(shapeX0Val);
                const p1x = shapeXaxis.d2p(shapeX1Val);

                const p0 = { x: shapeXaxis._offset + p0x, y: shapeYaxis._offset + p0y };
                const p1 = { x: shapeXaxis._offset + p1x, y: shapeYaxis._offset + p1y };

                if (!isNaN(p0.x) && !isNaN(p0.y) && !isNaN(p1.x) && !isNaN(p1.y)) {
                    const distSq = distToSegmentSquared({ x: mouseX_paper, y: mouseY_paper }, p0, p1);
                    const CLICK_THRESHOLD = 30; // Larger threshold for buy signals since they're horizontal lines

                    if (distSq < CLICK_THRESHOLD * CLICK_THRESHOLD) {
                        console.log('[DEBUG] handleShapeClick - buy signal clicked, showing modal');
                        // Call the buy signal modal
                        if (typeof window.displayBuySignalDetails === 'function') {
                            window.displayBuySignalDetails(shape.signalData);
                        } else {
                            console.error('[DEBUG] handleShapeClick - displayBuySignalDetails function not found');
                        }

                        // Prevent event bubbling
                        event.stopPropagation();
                        return; // Exit early, don't check other shapes
                    }
                }
            }
        }
    }

    // Get mouse coordinates early - needed for YouTube marker detection
    const rect = window.chartDiv.getBoundingClientRect();
    const mouseX_div = event.clientX - rect.left;
    const mouseY_div = event.clientY - rect.top;

    // Convert DOM coordinates to Plotly paper coordinates (same as colorTheLine function)
    const plotMargin = window.gd._fullLayout.margin;
    const mouseX_paper = mouseX_div;
    const mouseY_paper = mouseY_div;

    // Check if this might be a YouTube marker click - use same coordinate system as line shapes
    if (window.gd && window.gd.data && window.gd._fullLayout) {
        // Check if any YouTube marker traces exist
        for (let i = 0; i < window.gd.data.length; i++) {
            const trace = window.gd.data[i];
            if (trace.name === 'YouTube Videos' && trace.type === 'scatter' && trace.mode === 'markers') {
                console.log('[DEBUG] handleShapeClick - YouTube marker trace detected, checking click proximity');

                // Find the closest marker to the click position using same coordinate system as lines
                if (trace.x && trace.y && trace.x.length > 0) {
                    let closestIndex = -1;
                    let minDistance = Infinity;

                    for (let j = 0; j < trace.x.length; j++) {
                        // Convert data coordinates to pixel coordinates (same as line shapes)
                        const xVal = trace.x[j];
                        const yVal = trace.y[j];

                        // Get the axis information
                        const xAxis = window.gd._fullLayout.xaxis;
                        const yAxis = window.gd._fullLayout.yaxis;

                        if (xAxis && yAxis && typeof xAxis.d2p === 'function' && typeof yAxis.d2p === 'function') {
                            const pixelX = xAxis._offset + xAxis.d2p(xVal instanceof Date ? xVal.getTime() : xVal);
                            const pixelY = yAxis._offset + yAxis.d2p(yVal);

                            //console.log(`[DEBUG] handleShapeClick - YouTube marker ${j}: data=(${xVal}, ${yVal}), pixel=(${pixelX.toFixed(2)}, ${pixelY.toFixed(2)}), mouse_paper=(${mouseX_paper.toFixed(2)}, ${mouseY_paper.toFixed(2)})`);

                            // Calculate distance using same paper coordinates as line shapes
                            const distance = Math.sqrt(Math.pow(mouseX_paper - pixelX, 2) + Math.pow(mouseY_paper - pixelY, 2));

                            // console.log(`[DEBUG] handleShapeClick - YouTube marker ${j} distance: ${distance.toFixed(2)}`);

                            if (distance < minDistance && distance < 25) { // Slightly larger threshold for markers
                                minDistance = distance;
                                closestIndex = j;
                                // console.log(`[DEBUG] handleShapeClick - YouTube marker ${j} is closest so far, distance: ${distance.toFixed(2)}`);
                            }
                        }
                    }

                    if (closestIndex !== -1) {
                        // console.log('[DEBUG] handleShapeClick - YouTube marker clicked at index:', closestIndex);

                        // Get marker data
                        const transcript = trace.transcripts ? trace.transcripts[closestIndex] : 'No description available';
                        const title = trace.text ? trace.text[closestIndex] : 'Unknown title';
                        const videoId = trace.video_ids ? trace.video_ids[closestIndex] : '';
                        const publishedDate = trace.customdata ? trace.customdata[closestIndex] : '';

                        console.log('[DEBUG] handleShapeClick - Opening YouTube modal for:', title);

                        // Show the YouTube modal directly
                        if (window.youtubeMarkersManager && window.youtubeMarkersManager.showTranscriptModal) {
                            window.youtubeMarkersManager.showTranscriptModal(title, transcript, videoId, publishedDate);
                        } else {
                            console.error('[DEBUG] handleShapeClick - YouTube markers manager not available');
                        }

                        // Prevent event bubbling to avoid conflicts
                        event.stopPropagation();
                        return;
                    }
                }

                console.log('[DEBUG] handleShapeClick - No YouTube marker found near click position');
            }
        }
    }

    console.log('[DEBUG] handleShapeClick - Starting shape click processing');

    // Check if click is on a shape by finding the closest shape to the click position
    console.log('[DEBUG] handleShapeClick - mouse coordinates:', { clientX: event.clientX, clientY: event.clientY, mouseX_div, mouseY_div });

    if (!window.gd._fullLayout) {
        console.log('[DEBUG] handleShapeClick - no _fullLayout, returning');
        return;
    }

    console.log('[DEBUG] handleShapeClick - chart rect:', { left: rect.left, top: rect.top, width: rect.width, height: rect.height });
    console.log('[DEBUG] handleShapeClick - plot margins:', { l: plotMargin.l, r: plotMargin.r, t: plotMargin.t, b: plotMargin.b });
    console.log('[DEBUG] handleShapeClick - paper coordinates:', { mouseX_paper, mouseY_paper });

    // Find the closest shape to the click position
    const currentShapes = window.gd.layout.shapes || [];
    console.log('[DEBUG] handleShapeClick - checking', currentShapes.length, 'shapes');
    let closestShape = null;
    let minDistance = Infinity;
    const CLICK_THRESHOLD = 20; // pixels

    //console.groupCollapsed("handleShapeClick");
    for (let i = 0; i < currentShapes.length; i++) {
        const shape = currentShapes[i];
        //console.log(`[DEBUG] handleShapeClick - shape ${i}: type=${shape.type}, id=${shape.id}, isSystemShape=${shape.isSystemShape}`);
        if (shape.type === 'line' && shape.id && !shape.isSystemShape) {
            //console.log(`[DEBUG] handleShapeClick - processing clickable shape ${i} (ID: ${shape.id})`);
            const xrefKey = getAxisLayoutKey(shape.xref, 'xaxis');
            const yrefKey = getAxisLayoutKey(shape.yref, 'yaxis');
            const shapeXaxis = window.gd._fullLayout[xrefKey];
            const shapeYaxis = window.gd._fullLayout[yrefKey];

            if (!shapeXaxis || !shapeYaxis || typeof shapeXaxis.d2p !== 'function' || typeof shapeYaxis.d2p !== 'function') {
                // console.log(`[DEBUG] handleShapeClick - invalid axes for shape ${i}`);
                continue;
            }

            let shapeX0Val = (shapeXaxis.type === 'date') ? ((shape.x0 instanceof Date) ? shape.x0.getTime() : new Date(shape.x0).getTime()) : Number(shape.x0);
            let shapeX1Val = (shapeXaxis.type === 'date') ? ((shape.x1 instanceof Date) ? shape.x1.getTime() : new Date(shape.x1).getTime()) : Number(shape.x1);

            const p0y = shapeYaxis.d2p(shape.y0);
            const p1y = shapeYaxis.d2p(shape.y1);
            const p0x = shapeXaxis.d2p(shapeX0Val);
            const p1x = shapeXaxis.d2p(shapeX1Val);

            const p0 = { x: shapeXaxis._offset + p0x, y: shapeYaxis._offset + p0y };
            const p1 = { x: shapeXaxis._offset + p1x, y: shapeYaxis._offset + p1y };

            // console.log(`[DEBUG] handleShapeClick - shape ${i} pixel endpoints: p0=(${p0.x.toFixed(2)},${p0.y.toFixed(2)}), p1=(${p1.x.toFixed(2)},${p1.y.toFixed(2)}), mouse=(${mouseX_paper.toFixed(2)},${mouseY_paper.toFixed(2)})`);

            if (!isNaN(p0.x) && !isNaN(p0.y) && !isNaN(p1.x) && !isNaN(p1.y)) {
                const distSq = distToSegmentSquared({ x: mouseX_paper, y: mouseY_paper }, p0, p1);
                // console.log(`[DEBUG] handleShapeClick - shape ${i} distance squared: ${distSq.toFixed(2)}, threshold: ${(CLICK_THRESHOLD * CLICK_THRESHOLD)}`);
                if (distSq < CLICK_THRESHOLD * CLICK_THRESHOLD && distSq < minDistance) {
                    minDistance = distSq;
                    closestShape = shape;
                    //console.log(`[DEBUG] handleShapeClick - shape ${i} is now closest`);
                }
            } else {
                //console.log(`[DEBUG] handleShapeClick - shape ${i} has NaN coordinates`);
            }
        }
    }
    // console.groupEnd();

    // Handle shape selection
    if (closestShape) {
        console.log('[DEBUG] handleShapeClick - found closest shape:', closestShape.id);
        const isCtrlPressed = event.ctrlKey || event.metaKey; // Support both Ctrl (Windows/Linux) and Cmd (Mac)
        const shapeId = closestShape.id;
        console.log('[DEBUG] handleShapeClick - isCtrlPressed:', isCtrlPressed, 'shapeId:', shapeId);

        if (isCtrlPressed) {
            // Multi-select: toggle selection
            if (window.isShapeSelected(closestShape.id)) {
                window.deselectShape(closestShape.id);
                console.log('Deselected shape:', closestShape.id);
            } else {
                window.selectShape(closestShape.id, true); // true for multi-select
                console.log('Added shape to selection:', closestShape.id);
            }
        } else {
            // Single select: clear previous selections and select this shape
            if (!window.isShapeSelected(closestShape.id) || window.getSelectedShapeCount() > 1) {
                window.selectShape(closestShape.id, false); // false for single select
                console.log('Selected shape:', closestShape.id);
            } else {
                // Clicking on already selected shape - deselect it
                window.deselectShape(closestShape.id);
                console.log('Deselected shape:', closestShape.id);
            }
        }

        // Log selection state after update
        console.log('[DEBUG] handleShapeClick - Selection state after update:', {
            selectedIds: window.getSelectedShapeIds(),
            selectedCount: window.getSelectedShapeCount(),
            lastSelected: window.lastSelectedShapeId,
            isShapeSelected: window.isShapeSelected(shapeId)
        });

        // Update visual feedback by calling colorTheLine to handle the color change
        console.log('[DEBUG] handleShapeClick - calling colorTheLine for immediate color update at', new Date().toISOString());
        if (typeof colorTheLine === 'function') {
            // Pass the click event to colorTheLine for coordinate handling if needed
            colorTheLine(event);
        } else {
            console.error('[DEBUG] handleShapeClick - colorTheLine not available!');
        }

        // Update info panel
        console.log('[DEBUG] handleShapeClick - calling updateSelectedShapeInfoPanel with activeShape:', window.activeShapeForPotentialDeletion);
        updateSelectedShapeInfoPanel(window.activeShapeForPotentialDeletion);

        // Prevent event bubbling to avoid conflicts
        event.stopPropagation();
    } else {
        console.log('[DEBUG] handleShapeClick - no closest shape found, clicked on empty space');
        // Clicked on empty space - deselect all shapes
        if (window.getSelectedShapeCount() > 0) {
            window.deselectAllShapes();
            console.log('[DEBUG] handleShapeClick - deselected all shapes, calling colorTheLine');
            if (typeof colorTheLine === 'function') {
                colorTheLine(event);
            }
            updateSelectedShapeInfoPanel(null);
            console.log('Deselected all shapes (clicked on empty space)');
        }
    }
}

function initializeChartInteractions() {
    console.log('[DEBUG] initializeChartInteractions called');
    console.log('[DEBUG] window.chartDiv exists:', !!window.chartDiv);
    console.log('[DEBUG] window.chartDiv element:', window.chartDiv);

    // Double-click handling is now done by plotlyEventHandlers.js plotly_click event
    // addDoubleClickHandler(); // Disabled to prevent conflicts

    // Add shape selection click handler
    console.log('[DEBUG] Adding click event listener for shape selection');
    window.chartDiv.addEventListener('click', handleShapeClick, { capture: true, passive: true });

    // Throttle mousemove events to prevent excessive processing
    let mousemoveThrottleTimer = null;
    let isMouseDown = false;
    let isTouchActive = false;

    console.log('[DEBUG] Initial variable state - mousemoveThrottleTimer:', mousemoveThrottleTimer, 'isMouseDown:', isMouseDown, 'isTouchActive:', isTouchActive);

    // Make throttling state global for debugging
    window.mousemoveThrottleTimer = mousemoveThrottleTimer;
    window.isMouseDown = isMouseDown;
    window.isTouchActive = isTouchActive;

    console.log('[DEBUG] Adding mousedown event listener');
    window.chartDiv.addEventListener('mousedown', function() {
        isMouseDown = true;
        console.log('[DEBUG] Mouse down detected, isMouseDown =', isMouseDown);
    }, { capture: true, passive: true });

    console.log('[DEBUG] Adding mouseup event listener');
    window.chartDiv.addEventListener('mouseup', function() {
        isMouseDown = false;
        console.log('[DEBUG] Mouse up detected, isMouseDown =', isMouseDown);
    }, { capture: true, passive: true });

    // Add a test function to manually trigger colorTheLine
    window.testColorTheLine = function() {
        console.log('[DEBUG] Manually testing colorTheLine function');
        if (window.lastMouseEvent) {
            console.log('[DEBUG] Using last mouse event for test');
            colorTheLine(window.lastMouseEvent);
        } else {
            console.log('[DEBUG] No last mouse event, creating test event at center');
            const rect = window.chartDiv.getBoundingClientRect();
            const testEvent = {
                clientX: rect.left + rect.width / 2,
                clientY: rect.top + rect.height / 2,
                target: window.chartDiv
            };
            colorTheLine(testEvent);
        }
    };

    console.log('[DEBUG] Adding mousemove event listener');
    window.chartDiv.addEventListener('mousemove', async function(event) {
        console.log('[DEBUG] MOUSEMOVE EVENT FIRED on chart div - coordinates:', event.clientX, event.clientY);

        // Only process mousemove when mouse is not pressed (to avoid interfering with drags)
        if (isMouseDown) {
            console.log('[DEBUG] Skipping mousemove - mouse is down');
            return;
        }

        if (mousemoveThrottleTimer) {
            console.log('[DEBUG] Skipping mousemove - throttling active');
            return; // Skip if already processing
        }

        mousemoveThrottleTimer = true; // Set flag
        await delay(16); // ~60fps throttling
        console.log('[DEBUG] Calling colorTheLine from mousemove event');
        colorTheLine(event); // Pass the event for coordinate detection
        mousemoveThrottleTimer = null;
    }, { capture: true, passive: true });

    // Touch event handling for mobile devices
    window.chartDiv.addEventListener('touchstart', function(event) {
        isTouchActive = true;
        // Prevent default to avoid scrolling/zooming conflicts
        event.preventDefault();

        // Convert touch to mouse-like event for colorTheLine function
        const touch = event.touches[0] || event.changedTouches[0];
        const mouseEvent = {
            clientX: touch.clientX,
            clientY: touch.clientY,
            target: event.target,
            preventDefault: () => {},
            stopPropagation: () => {}
        };

        colorTheLine(mouseEvent);
    }, { capture: true, passive: false });

    window.chartDiv.addEventListener('touchmove', async function(event) {
        if (!isTouchActive) return;

        // Throttle touchmove events
        if (mousemoveThrottleTimer) return;

        // Prevent default to avoid scrolling/zooming
        event.preventDefault();

        mousemoveThrottleTimer = true; // Set flag
        await delay(16); // ~60fps throttling
        // Convert touch to mouse-like event
        const touch = event.touches[0] || event.changedTouches[0];
        const mouseEvent = {
            clientX: touch.clientX,
            clientY: touch.clientY,
            target: event.target,
            preventDefault: () => {},
            stopPropagation: () => {}
        };

        colorTheLine(mouseEvent);
        mousemoveThrottleTimer = null;
    }, { capture: true, passive: false });

    window.chartDiv.addEventListener('touchend', function(event) {
        isTouchActive = false;

        // Clear any pending throttled events
        if (mousemoveThrottleTimer) {
            clearTimeout(mousemoveThrottleTimer);
            mousemoveThrottleTimer = null;
        }

        // Optional: Clear hover state when touch ends
        // This prevents shapes from staying highlighted after touch ends
        if (window.hoveredShapeBackendId !== null) {
            window.hoveredShapeBackendId = null;
            if (typeof updateShapeVisuals === 'function') {
                updateShapeVisuals();
            }
        }
    }, { capture: true, passive: true });

    window.chartDiv.addEventListener('touchcancel', function(event) {
        isTouchActive = false;

        // Clear any pending throttled events
        if (mousemoveThrottleTimer) {
            clearTimeout(mousemoveThrottleTimer);
            mousemoveThrottleTimer = null;
        }

        // Clear hover state when touch is cancelled
        if (window.hoveredShapeBackendId !== null) {
            window.hoveredShapeBackendId = null;
            if (typeof updateShapeVisuals === 'function') {
                updateShapeVisuals();
            }
        }
    }, { capture: true, passive: true });

    window.chartDiv.addEventListener('mouseleave', function() {
        if (window.hoveredShapeBackendId !== null) { // From state.js
            window.hoveredShapeBackendId = null;
            if (typeof updateShapeVisuals === 'function') {
                updateShapeVisuals();
            }
        }
        // DISABLED: Crosshair interferes with panning
        /*
        removeCrosshairVLine(window.gd, true); // removeCrosshairVLine from this file
        if (window.cursorTimeDisplay) window.cursorTimeDisplay.textContent = 'N/A'; // From main.js
        updateSelectedShapeInfoPanel(null)
        if (window.cursorPriceDisplay) window.cursorPriceDisplay.textContent = 'N/A'; // From main.js
        */
    });

    document.addEventListener('keydown', async function(event) {
        if (!window.gd || !window.gd.layout) return;

        // Handle Escape key to deselect all shapes
        if (event.key === 'Escape') {
            if (window.getSelectedShapeCount() > 0) {
                event.preventDefault();
                window.deselectAllShapes();
                if (typeof updateShapeVisuals === 'function') {
                    updateShapeVisuals();
                }
                updateSelectedShapeInfoPanel(null);
                console.log('Deselected all shapes via Escape key');
            }
            return;
        }

        // Handle Ctrl+A to select all shapes
        if (event.key === 'a' && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            const currentShapes = window.gd?.layout?.shapes || [];
            const shapeIds = currentShapes
                .filter(s => s.id && !s.isSystemShape)
                .map(s => s.id);

            if (shapeIds.length > 0) {
                shapeIds.forEach(id => window.selectShape(id, true));
                if (typeof updateShapeVisuals === 'function') {
                    updateShapeVisuals();
                }
                updateSelectedShapeInfoPanel(window.activeShapeForPotentialDeletion);
                console.log('Selected all shapes via Ctrl+A');
            }
            return;
        }

        // Handle arrow keys for navigation between selected shapes
        if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(event.key)) {
            const selectedIds = window.getSelectedShapeIds();
            if (selectedIds.length > 1) {
                event.preventDefault();
                const currentIndex = selectedIds.indexOf(window.lastSelectedShapeId);
                let newIndex;

                switch (event.key) {
                    case 'ArrowUp':
                    case 'ArrowLeft':
                        newIndex = currentIndex > 0 ? currentIndex - 1 : selectedIds.length - 1;
                        break;
                    case 'ArrowDown':
                    case 'ArrowRight':
                        newIndex = currentIndex < selectedIds.length - 1 ? currentIndex + 1 : 0;
                        break;
                }

                if (newIndex !== currentIndex) {
                    window.lastSelectedShapeId = selectedIds[newIndex];
                    // Update activeShapeForPotentialDeletion for the new last selected shape
                        const currentShapes = window.gd?.layout?.shapes || [];
                        const shape = currentShapes.find(s => s.id === window.lastSelectedShapeId);
                        if (shape) {
                            const shapeIndex = currentShapes.indexOf(shape);
                            window.activeShapeForPotentialDeletion = {
                                id: window.lastSelectedShapeId,
                                index: shapeIndex,
                                shape: shape
                            };
                        }
                    if (typeof updateShapeVisuals === 'function') {
                        updateShapeVisuals();
                    }
                    updateSelectedShapeInfoPanel(window.activeShapeForPotentialDeletion);
                    console.log('Navigated to shape:', window.lastSelectedShapeId);
                }
            }
            return;
        }

        // Handle Delete/Backspace for shape deletion
        if (event.key === 'Delete' || event.key === 'Backspace') {
            const targetElement = event.target;
            if (targetElement.tagName === 'INPUT' || targetElement.tagName === 'TEXTAREA' || targetElement.isContentEditable) {
                if (targetElement !== document.body && targetElement !== window.chartDiv && !window.chartDiv.contains(targetElement)) {
                    return;
                }
            }

            const selectedShapeIds = window.getSelectedShapeIds();
            if (selectedShapeIds.length > 0) {
                console.log('Delete/Backspace key pressed. Attempting to delete selected shapes:', selectedShapeIds);
                event.preventDefault();

                const symbol = window.symbolSelect.value; // From main.js

                if (!symbol) {
                    console.warn("Cannot delete drawings via key: No symbol selected.");
                    return;
                }

                // Delete all selected shapes
                const deletePromises = selectedShapeIds.map(async (drawingId) => {
                    try {
                        const response = await fetch(`/delete_drawing/${symbol}/${drawingId}`, { method: 'DELETE' });
                        if (!response.ok) {
                            const errorBody = await response.text().catch(() => "Could not read error body");
                            throw new Error(`Failed to delete drawing ${drawingId} from backend: ${response.status} - ${errorBody}`);
                        }
                        console.log(`Drawing ${drawingId} deleted successfully from backend via key press.`);
                        return drawingId;
                    } catch (error) {
                        console.error(`Error deleting drawing ${drawingId} via key press:`, error);
                        return null; // Return null for failed deletions
                    }
                });

                try {
                    const results = await Promise.all(deletePromises);
                    const successfulDeletions = results.filter(id => id !== null);

                    if (successfulDeletions.length > 0) {
                        // Remove successfully deleted shapes from the chart
                        const currentShapes = window.gd.layout.shapes || [];
                        const remainingShapes = currentShapes.filter(s => !successfulDeletions.includes(s.id));

                        if (remainingShapes.length !== currentShapes.length) {
                            Plotly.relayout(window.gd, { shapes: remainingShapes }).catch(err => {
                                console.error("Error relayouting after shape removal by keydown:", err);
                                loadDrawingsAndRedraw(symbol);
                            });
                        } else {
                            loadDrawingsAndRedraw(symbol);
                        }

                        console.log(`Successfully deleted ${successfulDeletions.length} out of ${selectedShapeIds.length} shapes`);
                    }

                    // Clear selection regardless of success/failure
                    window.deselectAllShapes();
                    if (typeof updateShapeVisuals === 'function') {
                        updateShapeVisuals();
                    }
                    updateSelectedShapeInfoPanel(null);

                    // Show error message if some deletions failed
                    const failedCount = selectedShapeIds.length - (results.filter(id => id !== null).length);
                    if (failedCount > 0) {
                        alert(`Failed to delete ${failedCount} out of ${selectedShapeIds.length} shapes. Check console for details.`);
                    }

                } catch (error) {
                    console.error('Error during batch shape deletion:', error);
                    alert(`Failed to delete shapes: ${error.message}`);
                    window.deselectAllShapes();
                    if (typeof updateShapeVisuals === 'function') {
                        updateShapeVisuals();
                    }
                    updateSelectedShapeInfoPanel(null);
                }
            }
        }
    });
}

// debouncedUpdateCrosshair will be defined in main.js

function removeCrosshairVLine(gd, doRelayout = true) {
    if (!gd || !gd.layout || !gd.layout.shapes) return false;
    const initialLength = gd.layout.shapes.length;
    gd.layout.shapes = gd.layout.shapes.filter(shape => shape.name !== CROSSHAIR_VLINE_NAME); // From config.js
    const removed = gd.layout.shapes.length < initialLength;
    if (removed && doRelayout) {
        Plotly.relayout(gd, { shapes: gd.layout.shapes });
    }
    return removed;
}


function findAndupdateSelectedShapeInfoPanel(id) {
        const currentShapes = window.gd.layout.shapes || [];
        let foundShape = null
        for (let i = 0; i < currentShapes.length; i++) {
            const shape = currentShapes[i];
            if(shape.id === id) {
            foundShape = shape;
            break;
            }
        }

        if(foundShape) {
            const activeShape = { id: foundShape.id, index: currentShapes.indexOf(foundShape), shape: foundShape };
            updateSelectedShapeInfoPanel(activeShape);
        } else {
            updateSelectedShapeInfoPanel(null)
        }
}

// Long press detection is now handled by plotlyEventHandlers.js
// Removed handleShapeDoubleClick function

// Long press detection is now handled by plotlyEventHandlers.js
// Removed addDoubleClickHandler function
