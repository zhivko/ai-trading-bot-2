let newHoveredShapeId = null;

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


function colorTheLine()
{
        //console.groupCollapsed('[NativeMousemove] Event Processing');
        console.log('[colorTheLine] Current dragmode:', window.gd ? window.gd.layout.dragmode : 'N/A');
        if (!window.gd || !window.gd.layout || window.gd.layout.dragmode !== 'pan') {
            //console.log('[NativeMousemove] Exiting early: Chart not ready or dragmode not pan.');
            if (hoveredShapeBackendId !== null) { // Assumes hoveredShapeBackendId is global from state.js
                hoveredShapeBackendId = null;
                debouncedUpdateShapeVisuals(); // Assumes debouncedUpdateShapeVisuals is global
            }
            //console.groupEnd();
            return;
        }

        if (event.target.closest('.modebar') ||
            event.target.closest('select') ||
            event.target.closest('input') ||
            event.target.closest('.rangeslider') ||
            event.target.closest('.legend')) {
            //console.log('[NativeMousemove] Exiting early: Mouse over Plotly UI element.');
            //console.groupEnd();
            return;
        }

        const rect = window.chartDiv.getBoundingClientRect();
        const mouseX_div = event.clientX - rect.left;
        const mouseY_div = event.clientY - rect.top;

        if (!window.gd._fullLayout || typeof window.gd._fullLayout.height === 'undefined' || !window.gd._fullLayout.yaxis || typeof window.gd._fullLayout.yaxis._length === 'undefined') {
            console.log("[NativeMousemove] Mouse is outside the chart's plotting area. Ignoring.");
            return;
        }

        const mouseX_paper = mouseX_div;
        const mouseY_paper = mouseY_div;

        /*
        console.log("Mouse x: ", mouseX_paper)
        console.log("Mouse y: ", mouseY_paper)
        */

        //New check - is the cursor in plot area?
         if (mouseX_paper < 0 || mouseX_paper > window.gd._fullLayout.width || mouseY_paper < 0 || mouseY_paper > window.gd._fullLayout.height) {
            console.log("[NativeMousemove] Mouse is outside the chart's plotting area. Ignoring.");
            if (hoveredShapeBackendId !== null) {
                hoveredShapeBackendId = null;
                debouncedUpdateShapeVisuals();
            }
            //console.groupEnd();
            return;
        }

        const plotMargin = window.gd._fullLayout.margin;
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
            if (hoveredShapeBackendId !== null) {
                hoveredShapeBackendId = null;
                debouncedUpdateShapeVisuals();
            }
        }

        const currentShapes = window.gd.layout.shapes || [];
        for (let i = 0; i < currentShapes.length; i++) {
            const shape = currentShapes[i];
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
                //console.log(`Calculated DistSq: ${distSq.toFixed(2)}. Threshold: ${HOVER_THRESHOLD_PIXELS_SQ}`);
                if (distSq < HOVER_THRESHOLD_PIXELS_SQ && distSq < minDistanceSq) {
                    minDistanceSq = distSq;
                    newHoveredShapeId = shape.backendId;
                    if(window.gd) activateShape(window.gd, `shapes[${i}]`);
                }
                //console.groupEnd(); // End group for this shape
            }
        }

        if (hoveredShapeBackendId !== newHoveredShapeId) {
            hoveredShapeBackendId = newHoveredShapeId;
            if(hoveredShapeBackendId) findAndupdateSelectedShapeInfoPanel(hoveredShapeBackendId)
            debouncedUpdateShapeVisuals();
        }
        if (!hoveredSubplotRefs && hoveredShapeBackendId !== null) {
            hoveredShapeBackendId = null;
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
    
    window.chartDiv.addEventListener('mousemove', function(event) {
        colorTheLine();
    });

    window.chartDiv.addEventListener('mouseleave', function() {
        if (hoveredShapeBackendId !== null) { // From state.js
            hoveredShapeBackendId = null;
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

            if (activeShapeForPotentialDeletion && activeShapeForPotentialDeletion.id) { // From state.js
                console.log('Delete/Backspace key pressed. Attempting to delete active shape:', activeShapeForPotentialDeletion);
                event.preventDefault();

                const { id: drawingId } = activeShapeForPotentialDeletion;
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
                    activeShapeForPotentialDeletion = null;
                    updateSelectedShapeInfoPanel(null); // From uiUpdaters.js
                    await updateShapeVisuals(); // From uiUpdaters.js
                } catch (error) {
                    console.error(`Error deleting drawing ${drawingId} via key press:`, error);
                    alert(`Failed to delete drawing: ${error.message}`);
                    activeShapeForPotentialDeletion = null;
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
