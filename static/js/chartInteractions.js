window.newHoveredShapeId = null;
window.lastClickTime = 0;
window.lastClickedShapeId = null;

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
        // console.groupCollapsed('[NativeMousemove] Event Processing');
        console.log('[colorTheLine] Current dragmode:', window.gd ? window.gd.layout.dragmode : 'N/A');

        // Use the passed event or fall back to global event
        const currentEvent = eventParam || event;

        if (!window.gd || !window.gd.layout) {
            //console.log('[NativeMousemove] Exiting early: Chart not ready.');
            if (window.hoveredShapeBackendId !== null) { // Assumes hoveredShapeBackendId is global from state.js
                window.hoveredShapeBackendId = null;
                debouncedUpdateShapeVisuals(); // Assumes debouncedUpdateShapeVisuals is global
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
            console.log(`[colorTheLine] Using event coordinates: clientX=${currentEvent.clientX}, clientY=${currentEvent.clientY}`);
        } else if (currentEvent && currentEvent.touches && currentEvent.touches.length > 0) {
            // Handle touch events
            const touch = currentEvent.touches[0] || currentEvent.changedTouches[0];
            mouseX_div = touch.clientX - rect.left;
            mouseY_div = touch.clientY - rect.top;
            console.log(`[colorTheLine] Using touch coordinates: clientX=${touch.clientX}, clientY=${touch.clientY}`);
        } else {
            // Fallback: try to get mouse position from window.event or other methods
            const globalEvent = window.event;
            if (globalEvent && globalEvent.clientX !== undefined && globalEvent.clientY !== undefined &&
                globalEvent.clientX !== 0 && globalEvent.clientY !== 0) {
                mouseX_div = globalEvent.clientX - rect.left;
                mouseY_div = globalEvent.clientY - rect.top;
                console.log(`[colorTheLine] Using global event coordinates: clientX=${globalEvent.clientX}, clientY=${globalEvent.clientY}`);
            } else {
                // Try to get mouse position from document.elementFromPoint or other methods
                try {
                    const centerX = rect.left + rect.width/2;
                    const centerY = rect.top + rect.height/2;
                    const elementsAtCenter = document.elementsFromPoint(centerX, centerY);
                    if (elementsAtCenter && elementsAtCenter.length > 0) {
                        mouseX_div = rect.width / 2;
                        mouseY_div = rect.height / 2;
                        console.log(`[colorTheLine] Using center coordinates as fallback: x=${mouseX_div}, y=${mouseY_div}`);
                    } else {
                        throw new Error("No elements found at center");
                    }
                } catch (e) {
                    // Last resort: assume center of chart for testing
                    mouseX_div = rect.width / 2;
                    mouseY_div = rect.height / 2;
                    console.log(`[colorTheLine] Using fallback center coordinates: x=${mouseX_div}, y=${mouseY_div}, error: ${e.message}`);
                }
            }
        }

        console.log(`[colorTheLine] Chart div rect: left=${rect.left}, top=${rect.top}, width=${rect.width}, height=${rect.height}`);
        console.log(`[colorTheLine] Mouse relative to div: x=${mouseX_div}, y=${mouseY_div}`);

        if (!window.gd._fullLayout || typeof window.gd._fullLayout.height === 'undefined' || !window.gd._fullLayout.yaxis || typeof window.gd._fullLayout.yaxis._length === 'undefined') {
            console.log("[colorTheLine] Chart layout not ready, skipping hover detection");
            return;
        }

        // Convert DOM coordinates to Plotly paper coordinates
        // Paper coordinates are relative to the full chart area (including margins)
        const plotMargin = window.gd._fullLayout.margin;
        const mouseX_paper = mouseX_div;
        const mouseY_paper = mouseY_div;

        console.log(`[colorTheLine] Chart dimensions: width=${window.gd._fullLayout.width}, height=${window.gd._fullLayout.height}`);
        console.log(`[colorTheLine] Plot margins: l=${plotMargin.l}, r=${plotMargin.r}, t=${plotMargin.t}, b=${plotMargin.b}`);
        console.log(`[colorTheLine] Mouse in paper coordinates: x=${mouseX_paper}, y=${mouseY_paper}`);

        // Check if mouse is within the chart's plotting area (with some tolerance for edge cases)
        const tolerance = 10; // Allow 10px tolerance for edge cases
        const isOutsideBounds = mouseX_paper < -tolerance ||
                               mouseX_paper > window.gd._fullLayout.width + tolerance ||
                               mouseY_paper < -tolerance ||
                               mouseY_paper > window.gd._fullLayout.height + tolerance;

        console.log(`[colorTheLine] Bounds check: mouseX=${mouseX_paper}, mouseY=${mouseY_paper}, width=${window.gd._fullLayout.width}, height=${window.gd._fullLayout.height}, tolerance=${tolerance}, isOutside=${isOutsideBounds}`);

        if (isOutsideBounds) {
            console.log("[colorTheLine] Mouse is outside the chart's plotting area. Ignoring.");
            if (window.hoveredShapeBackendId !== null) {
                window.hoveredShapeBackendId = null;
                debouncedUpdateShapeVisuals();
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
                debouncedUpdateShapeVisuals();
            }
        }

        const currentShapes = window.gd.layout.shapes || [];
        console.log(`[colorTheLine] Checking ${currentShapes.length} shapes for hover detection`);
        for (let i = 0; i < currentShapes.length; i++) {
            const shape = currentShapes[i];
            console.log(`[colorTheLine] Shape ${i}: type=${shape.type}, backendId=${shape.backendId}, isSystemShape=${shape.isSystemShape}`);
            if (shape.type === 'line' && shape.backendId && !shape.isSystemShape) { // Ignore system shapes
                const xrefKeyForFilter = getAxisLayoutKey(shape.xref, 'xaxis'); // Assumes getAxisLayoutKey is global
                const yrefKeyForFilter = getAxisLayoutKey(shape.yref, 'yaxis');
                const shapeXaxisForFilter = window.gd._fullLayout[xrefKeyForFilter];
                const shapeYaxisForFilter = window.gd._fullLayout[yrefKeyForFilter];

                if (!shapeXaxisForFilter || !shapeYaxisForFilter) continue;

                if (hoveredSubplotRefs) {
                    if (shapeXaxisForFilter._id !== hoveredSubplotRefs.xref || shapeYaxisForFilter._id !== hoveredSubplotRefs.yref) {
                        //console.log(`[NativeMousemove DEBUG] Skipping shape ${i} (ID: ${shape.backendId}, shape_xref: ${shape.xref}, shape_yref: ${shape.yref}) because its axes (_id: ${shapeXaxisForFilter._id}, ${shapeYaxisForFilter._id}) don't match hovered subplot axes (hover_xref: ${hoveredSubplotRefs.xref}, hover_yref: ${hoveredSubplotRefs.yref}).`);
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
                    //console.warn(`[NativeMousemove DEBUG] Could not find valid axes for shape ${i} (ID: ${shape.backendId}) with xref=${shape.xref}, yref=${shape.yref}. Skipping hover test.`);
                    continue;
                }

                /*
                console.group(`[NativeMousemove DEBUG] Checking Shape ${i} (ID: ${shape.backendId})`);
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
                    /*console.warn(`[NativeMousemove DEBUG] Shape ${i} (ID: ${shape.backendId}) had NaN/Infinite pixel coordinates. Skipping.`);
                    console.groupEnd();
                    */
                    continue;
                }
                const distSq = distToSegmentSquared({ x: mouseX_paper, y: mouseY_paper }, p0, p1); // From utils.js
                console.log(`[colorTheLine] Shape ${i} (ID: ${shape.backendId}) - DistSq: ${distSq.toFixed(2)}, Threshold: ${HOVER_THRESHOLD_PIXELS_SQ}, Mouse: (${mouseX_paper.toFixed(2)}, ${mouseY_paper.toFixed(2)}), Shape endpoints: (${p0.x.toFixed(2)}, ${p0.y.toFixed(2)}) to (${p1.x.toFixed(2)}, ${p1.y.toFixed(2)})`);
                if (distSq < HOVER_THRESHOLD_PIXELS_SQ && distSq < minDistanceSq) {
                    minDistanceSq = distSq;
                    window.newHoveredShapeId = shape.backendId;
                    console.log(`[colorTheLine] Shape ${i} (ID: ${shape.backendId}) is now the closest hovered shape!`);
                }
                //console.groupEnd(); // End group for this shape
            }
        }

        console.log(`[colorTheLine] Final: hoveredShapeBackendId=${window.hoveredShapeBackendId}, newHoveredShapeId=${window.newHoveredShapeId}`);
        if (window.hoveredShapeBackendId !== window.newHoveredShapeId) {
            window.hoveredShapeBackendId = window.newHoveredShapeId;
            console.log(`[colorTheLine] Updated hoveredShapeBackendId to: ${window.hoveredShapeBackendId}`);
            if(window.hoveredShapeBackendId) findAndupdateSelectedShapeInfoPanel(window.hoveredShapeBackendId)
            debouncedUpdateShapeVisuals();
        }

        // Only clear shape ID if we're sure no shape should be hovered (mouse outside chart area)
        if (isOutsideBounds && window.hoveredShapeBackendId !== null) {
            console.log(`[colorTheLine] Mouse outside bounds, clearing hovered shape`);
            window.hoveredShapeBackendId = null;
            debouncedUpdateShapeVisuals();
        }

        // Crosshair logic
        const mainXAxis = window.gd._fullLayout.xaxis;
        if (mainXAxis && typeof mainXAxis.p2d === 'function') {
            const xDataValueAtMouse = mainXAxis.p2d(mouseX_plotArea);
            if (xDataValueAtMouse !== undefined && xDataValueAtMouse !== null && !isNaN(new Date(xDataValueAtMouse).getTime())) {
                const dateAtCursor = new Date(xDataValueAtMouse);
                if (window.cursorTimeDisplay) { // Assumes cursorTimeDisplay is global
                    window.cursorTimeDisplay.textContent = dateAtCursor.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'medium' });
                }
                window.debouncedUpdateCrosshair(window.gd, dateAtCursor); // Assumes debouncedUpdateCrosshair is global

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
                removeCrosshairVLine(window.gd, true);
                if (window.cursorTimeDisplay) window.cursorTimeDisplay.textContent = 'N/A';
                if (window.cursorPriceDisplay) window.cursorPriceDisplay.textContent = 'N/A';
            }
        } else {
            removeCrosshairVLine(window.gd, true);
            if (window.cursorTimeDisplay) window.cursorTimeDisplay.textContent = 'N/A';
            if (window.cursorPriceDisplay) window.cursorPriceDisplay.textContent = 'N/A';
        }
        //console.groupEnd(); // Close group at the end of the function
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

function initializeChartInteractions() {
    // Add double-click handler first
    addDoubleClickHandler();
    
    // Throttle mousemove events to prevent excessive processing
    let mousemoveThrottleTimer = null;
    let isMouseDown = false;

    window.chartDiv.addEventListener('mousedown', function() {
        isMouseDown = true;
    }, { capture: true, passive: true });

    window.chartDiv.addEventListener('mouseup', function() {
        isMouseDown = false;
    }, { capture: true, passive: true });

    window.chartDiv.addEventListener('mousemove', function(event) {
        // Only process mousemove when mouse is not pressed (to avoid interfering with drags)
        if (isMouseDown) return;

        if (mousemoveThrottleTimer) return; // Skip if already processing

        mousemoveThrottleTimer = setTimeout(() => {
            colorTheLine(event); // Pass the event for coordinate detection
            mousemoveThrottleTimer = null;
        }, 16); // ~60fps throttling
    }, { capture: true, passive: true });

    window.chartDiv.addEventListener('mouseleave', function() {
        if (window.hoveredShapeBackendId !== null) { // From state.js
            window.hoveredShapeBackendId = null;
            debouncedUpdateShapeVisuals(); // From main.js
        }
        /*
        removeCrosshairVLine(window.gd, true); // removeCrosshairVLine from this file
        if (window.cursorTimeDisplay) window.cursorTimeDisplay.textContent = 'N/A'; // From main.js
        updateSelectedShapeInfoPanel(null)
        if (window.cursorPriceDisplay) window.cursorPriceDisplay.textContent = 'N/A'; // From main.js
        */
    });

    document.addEventListener('keydown', async function(event) {
        if (!window.gd || !window.gd.layout) return;

        if (event.key === 'Delete' || event.key === 'Backspace') {
            const targetElement = event.target;
            if (targetElement.tagName === 'INPUT' || targetElement.tagName === 'TEXTAREA' || targetElement.isContentEditable) {
                if (targetElement !== document.body && targetElement !== window.chartDiv && !window.chartDiv.contains(targetElement)) {
                    return;
                }
            }

            if (window.activeShapeForPotentialDeletion && window.activeShapeForPotentialDeletion.id) { // From state.js
                console.log('Delete/Backspace key pressed. Attempting to delete active shape:', window.activeShapeForPotentialDeletion);
                event.preventDefault();

                const { id: drawingId } = window.activeShapeForPotentialDeletion;
                const symbol = window.symbolSelect.value; // From main.js

                if (!symbol) {
                    console.warn("Cannot delete drawing via key: No symbol selected.");
                    return;
                }

                try {
                    const response = await fetch(`/delete_drawing/${symbol}/${drawingId}`, { method: 'DELETE' });
                    if (!response.ok) {
                        const errorBody = await response.text().catch(() => "Could not read error body");
                        throw new Error(`Failed to delete drawing ${drawingId} from backend: ${response.status} - ${errorBody}`);
                    }
                    console.log(`Drawing ${drawingId} deleted successfully from backend via key press.`);

                    const currentShapes = window.gd.layout.shapes || [];
                    const shapeToRemoveIndex = currentShapes.findIndex(s => s.backendId === drawingId);
                    if (shapeToRemoveIndex !== -1) {
                        currentShapes.splice(shapeToRemoveIndex, 1);
                        Plotly.relayout(window.gd, { shapes: currentShapes }).catch(err => { console.error("Error relayouting after shape removal by keydown:", err); loadDrawingsAndRedraw(symbol); }); // loadDrawingsAndRedraw from main.js
                    } else {
                        loadDrawingsAndRedraw(symbol);
                    }
                    window.activeShapeForPotentialDeletion = null;
                    updateSelectedShapeInfoPanel(null); // From uiUpdaters.js
                    await updateShapeVisuals(); // From uiUpdaters.js
                } catch (error) {
                    console.error(`Error deleting drawing ${drawingId} via key press:`, error);
                    alert(`Failed to delete drawing: ${error.message}`);
                    window.activeShapeForPotentialDeletion = null;
                    updateSelectedShapeInfoPanel(null);
                    await updateShapeVisuals();
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
            if(shape.backendId === id) {
            foundShape = shape;
            break;
            }
        }

        if(foundShape) {
            const activeShape = { id: foundShape.backendId, index: currentShapes.indexOf(foundShape), shape: foundShape };
            updateSelectedShapeInfoPanel(activeShape);
        } else {
            updateSelectedShapeInfoPanel(null)
        }
}

// Handle double-click on shapes
function handleShapeDoubleClick(shapeId) {
    console.log(`[DEBUG] handleShapeDoubleClick called with shapeId: ${shapeId}`);
    const currentTime = Date.now();
    const doubleClickThreshold = 1000; // ms between clicks to count as double-click
    
    console.log(`[DEBUG] Last click time: ${window.lastClickTime}, Last clicked shape: ${window.lastClickedShapeId}`);
    console.log(`[DEBUG] Current time: ${currentTime}, Time difference: ${currentTime - window.lastClickTime}ms`);
    
    if (window.lastClickedShapeId === shapeId && (currentTime - window.lastClickTime) < doubleClickThreshold) {
        // Double-click detected - open shape properties
        console.log(`[DEBUG] Double-click detected on shape: ${shapeId}`);
        if (typeof window.openShapePropertiesDialog === 'function') {
            console.log(`[DEBUG] Calling openShapePropertiesDialog for shape: ${shapeId}`);
            window.openShapePropertiesDialog(shapeId);
        } else {
            console.warn('openShapePropertiesDialog function not found');
        }
        // Reset after handling double-click
        window.lastClickTime = 0;
        window.lastClickedShapeId = null;
    } else {
        // Single click or different shape - update tracking
        console.log(`[DEBUG] Single click detected on shape: ${shapeId}`);
        window.lastClickTime = currentTime;
        window.lastClickedShapeId = shapeId;
    }
}

// Add double-click handler to chart div
function addDoubleClickHandler() {
    if (window.chartDiv) {
        console.log('[DEBUG] Adding double-click event listener to chart div');

        // Track mouse state to distinguish clicks from drags
        let mouseDownTime = 0;
        let mouseDownPos = { x: 0, y: 0 };
        let isDragging = false;

        // Function to handle clicks on SVG elements (for double-click simulation)
        function handleSVGClick(event) {
            // Skip if this was a drag operation
            if (isDragging) {
                console.log('[DEBUG] Skipping click - was part of drag operation');
                return;
            }

            console.log('[DEBUG] Click event detected on SVG element');
            console.log(`[DEBUG] Event coordinates: clientX=${event.clientX}, clientY=${event.clientY}`);
            console.log(`[DEBUG] SVG Event target: ${event.target.tagName}, Event type: ${event.type}`);

            // Use the current hovered shape if available, otherwise try to detect it
            let currentShapeId = window.hoveredShapeBackendId;

            // If no current hovered shape, try to detect one at click location
            if (!currentShapeId) {
                colorTheLine(event);
                currentShapeId = window.hoveredShapeBackendId;
            }

            console.log(`[DEBUG] Current hovered shape ID: ${currentShapeId}`);

            if (currentShapeId) {
                const currentTime = Date.now();
                const timeDiff = currentTime - (window.lastClickTime || 0);
                console.log(`[DEBUG] Double-click check: currentTime=${currentTime}, lastClickTime=${window.lastClickTime || 0}, timeDiff=${timeDiff}ms, threshold=1000ms`);
                console.log(`[DEBUG] Shape check: currentShape=${currentShapeId}, lastShape=${window.lastClickedShapeId || 'null'}`);

                if (window.lastClickedShapeId === currentShapeId &&
                    timeDiff < 1000) { // 1000ms threshold
                    // Double-click detected!
                    console.log(`[DEBUG] DOUBLE-CLICK detected on shape: ${currentShapeId}`);
                    // Don't stop propagation or prevent default to allow Plotly's native behavior
                    handleShapeDoubleClick(currentShapeId);

                    // Reset after handling double-click
                    window.lastClickTime = 0;
                    window.lastClickedShapeId = null;
                } else {
                    // Single click - update tracking
                    console.log(`[DEBUG] Single click on shape: ${currentShapeId}`);
                    window.lastClickTime = currentTime;
                    window.lastClickedShapeId = currentShapeId;
                }
            } else {
                console.log('[DEBUG] No shape detected at click location');
            }
        }

        // Track mouse down to detect drags
        window.chartDiv.addEventListener('mousedown', function(event) {
            mouseDownTime = Date.now();
            mouseDownPos = { x: event.clientX, y: event.clientY };
            isDragging = false;
            console.log(`[DEBUG] Mouse down at: ${mouseDownPos.x}, ${mouseDownPos.y}, target: ${event.target.tagName}`);

            // Don't interfere with Plotly's drag handles or resize elements
            const targetClass = event.target.className || '';
            const targetTag = event.target.tagName || '';
            if ((typeof targetClass === 'string' && (targetClass.includes('drag') || targetClass.includes('resize'))) ||
                targetTag === 'circle' || targetTag === 'rect' ||
                event.target.closest('.plotly-drag-layer')) {
                console.log('[DEBUG] Mouse down on Plotly drag element - allowing native behavior');
                // Don't set isDragging to false here, let Plotly handle it
                return;
            }
        }, { capture: true, passive: true });

        // Track mouse up to detect if it was a drag
        window.chartDiv.addEventListener('mouseup', function(event) {
            const mouseUpTime = Date.now();
            const mouseUpPos = { x: event.clientX, y: event.clientY };
            const timeDiff = mouseUpTime - mouseDownTime;
            const distance = Math.sqrt(
                Math.pow(mouseUpPos.x - mouseDownPos.x, 2) +
                Math.pow(mouseUpPos.y - mouseDownPos.y, 2)
            );

            // Consider it a drag if moved more than 5px or held for more than 500ms
            isDragging = distance > 5 || timeDiff > 500;
            console.log(`[DEBUG] Mouse up - distance: ${distance.toFixed(1)}px, time: ${timeDiff}ms, isDragging: ${isDragging}`);
        }, { capture: true, passive: true });

        // Add click handler to the main chart div
        window.chartDiv.addEventListener('click', function(event) {
            // Skip if this was a drag operation
            if (isDragging) {
                console.log('[DEBUG] Skipping chart div click - was part of drag operation');
                return;
            }

            // Skip if Plotly is in a drawing or editing mode
            const currentDragMode = window.gd && window.gd.layout ? window.gd.layout.dragmode : 'pan';
            if (currentDragMode === 'drawline' || currentDragMode === 'drawopenpath' ||
                currentDragMode === 'drawclosedpath' || currentDragMode === 'drawcircle' ||
                currentDragMode === 'drawrect') {
                console.log(`[DEBUG] Skipping click - Plotly in draw mode: ${currentDragMode}`);
                return;
            }

            // Skip if clicking on Plotly UI elements
            if (event.target.closest('.modebar') || event.target.closest('select') ||
                event.target.closest('input') || event.target.closest('.rangeslider')) {
                console.log('[DEBUG] Skipping click - on Plotly UI element');
                return;
            }

            // Allow Plotly's native drag operations to work by not preventing default
            // Only process our custom click logic if it's clearly not a drag operation
            console.log('[DEBUG] CLICK EVENT DETECTED ON CHART DIV');
            console.log(`[DEBUG] Event coordinates: clientX=${event.clientX}, clientY=${event.clientY}`);
            console.log(`[DEBUG] Event target: ${event.target.tagName}, Event type: ${event.type}`);
            console.log(`[DEBUG] Chart div bounds: left=${window.chartDiv.getBoundingClientRect().left}, top=${window.chartDiv.getBoundingClientRect().top}`);

            // Use the current hovered shape if available, otherwise try to detect it
            let currentShapeId = window.hoveredShapeBackendId;

            // If no current hovered shape, try to detect one at click location
            if (!currentShapeId) {
                colorTheLine(event);
                currentShapeId = window.hoveredShapeBackendId;
            }

            // Handle double-click detection
            if (currentShapeId) {
                const currentTime = Date.now();
                const timeDiff = currentTime - (window.lastClickTime || 0);
                console.log(`[DEBUG] Chart div double-click check: currentTime=${currentTime}, lastClickTime=${window.lastClickTime || 0}, timeDiff=${timeDiff}ms, threshold=1000ms`);
                console.log(`[DEBUG] Chart div shape check: currentShape=${currentShapeId}, lastShape=${window.lastClickedShapeId || 'null'}`);

                if (window.lastClickedShapeId === currentShapeId &&
                    timeDiff < 1000) { // 1000ms threshold
                    // Double-click detected!
                    console.log(`[DEBUG] DOUBLE-CLICK detected on chart div for shape: ${currentShapeId}`);
                    handleShapeDoubleClick(currentShapeId);

                    // Reset after handling double-click
                    window.lastClickTime = 0;
                    window.lastClickedShapeId = null;
                } else {
                    // Single click - update tracking
                    console.log(`[DEBUG] Single click on chart div for shape: ${currentShapeId}`);
                    window.lastClickTime = currentTime;
                    window.lastClickedShapeId = currentShapeId;
                }
            } else {
                console.log('[DEBUG] No shape detected at chart div click location');
            }

            handleSVGClick(event);
        }, { capture: true, passive: true });

        // Add click handlers to SVG elements using mutation observer
        const observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(mutation) {
                mutation.addedNodes.forEach(function(node) {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        // Check if it's an SVG element or contains SVG elements
                        if (node.tagName === 'svg' || node.querySelector('svg')) {
                            const svgElement = node.tagName === 'svg' ? node : node.querySelector('svg');
                            if (svgElement) {
                                console.log('[DEBUG] Found SVG element, adding click listener for double-click simulation');
                                // Add drag-aware click handler
                                svgElement.addEventListener('click', function(event) {
                                    // Skip if this was a drag operation
                                    if (isDragging) {
                                        console.log('[DEBUG] Skipping SVG click - was part of drag operation');
                                        return;
                                    }
                                    handleSVGClick(event);
                                }, { capture: true, passive: true });
                            }
                        }
                        // Also check for any existing SVG elements in the added node
                        const svgElements = node.querySelectorAll ? node.querySelectorAll('svg') : [];
                        svgElements.forEach(function(svg) {
                            console.log('[DEBUG] Found existing SVG element in added node, adding click listener for double-click simulation');
                            // Add drag-aware click handler
                            svg.addEventListener('click', function(event) {
                                // Skip if this was a drag operation
                                if (isDragging) {
                                    console.log('[DEBUG] Skipping SVG click - was part of drag operation');
                                    return;
                                }
                                handleSVGClick(event);
                            }, { capture: true, passive: true });
                        });
                    }
                });
            });
        });

        // Start observing the chart div for changes
        observer.observe(window.chartDiv, {
            childList: true,
            subtree: true
        });

        // Also try to find and add listeners to any existing SVG elements
        const existingSVGs = window.chartDiv.querySelectorAll('svg');
        existingSVGs.forEach(function(svg) {
            console.log('[DEBUG] Found existing SVG element, adding click listener for double-click simulation');
            // Add drag-aware click handler
            svg.addEventListener('click', function(event) {
                // Skip if this was a drag operation
                if (isDragging) {
                    console.log('[DEBUG] Skipping existing SVG click - was part of drag operation');
                    return;
                }
                handleSVGClick(event);
            }, { capture: true, passive: true });
        });


    } else {
        console.warn('[DEBUG] chartDiv not found when adding double-click handler');
    }
}
