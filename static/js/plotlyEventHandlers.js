console.log('[DEBUG] plotlyEventHandlers.js loaded.');

async function handleNewShapeSave(shapeObject) {
    const symbol = window.symbolSelect.value; // Assumes symbolSelect is global
    const resolution = window.resolutionSelect.value;
    if (!symbol) {
        console.warn("Cannot save drawing: No symbol selected.");
        return null;
    }

    if (shapeObject.type === 'line' && typeof shapeObject.x0 !== 'undefined' && typeof shapeObject.y0 !== 'undefined' && typeof shapeObject.x1 !== 'undefined' && typeof shapeObject.y1 !== 'undefined') {
        try {
            const start_time_ms = (shapeObject.x0 instanceof Date) ? shapeObject.x0.getTime() : new Date(shapeObject.x0).getTime();
            const end_time_ms = (shapeObject.x1 instanceof Date) ? shapeObject.x1.getTime() : new Date(shapeObject.x1).getTime();
            const drawingData = {
                symbol: symbol,
                type: shapeObject.type,
                start_time: Math.floor(start_time_ms / 1000),
                end_time: Math.floor(end_time_ms / 1000),
                start_price: parseFloat(shapeObject.y0),
                end_price: parseFloat(shapeObject.y1),
                subplot_name: determineSubplotNameForShape(shapeObject), // Assumes determineSubplotNameForShape is global
                resolution: resolution
            };
            console.log(`Attempting to save new shape for ${symbol}:`, drawingData);
            const response = await fetch(`/save_drawing/${symbol}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(drawingData)
            });

            if (!response.ok) throw new Error(`Failed to save drawing: ${response.status} ${await response.text()}`);
            const result = await response.json();
            console.log('Drawing saved via handleNewShapeSave:', result);
            return result.id;
        } catch (error) {
            console.error('Error in handleNewShapeSave:', error);
            alert(`Failed to save drawing: ${error.message}`);
            loadDrawingsAndRedraw(symbol); // Assumes loadDrawingsAndRedraw is global
            return null;
        }
    }
    return null;
}

function initializePlotlyEventHandlers(gd) {
    console.log('[DEBUG] initializePlotlyEventHandlers called with gd:', gd);

    // Test if Plotly events are working
    try {
        if (typeof console !== 'undefined' && console.log) {
            console.log('[DEBUG] Plotly event handlers initialized');
            console.log('[DEBUG] Chart object:', gd);
            console.log('[DEBUG] Chart has _ev:', !!gd._ev);
        }
    } catch (e) {
        alert('[DEBUG] Plotly event handlers initialized');
    }

    // Add test event listeners to verify event system is working
    gd.on('plotly_click', function() {
        console.log('[DEBUG] plotly_click event received - event system is working');
    });

    // Add keyboard shortcut for testing (press 'T' to trigger test event)
    document.addEventListener('keydown', function(event) {
        if (event.key === 't' || event.key === 'T') {
            try {
                if (typeof console !== 'undefined' && console.log) {
                    console.log('[DEBUG] Test key pressed - manually triggering plotly_relayout simulation');
                } else {
                    alert('[DEBUG] Test key pressed - manually triggering plotly_relayout simulation');
                }
            } catch (e) {
                alert('[DEBUG] Test key pressed - manually triggering plotly_relayout simulation');
            }

            // Simulate a relayout event
            const testEventData = {
                'xaxis.range[0]': new Date(Date.now() - 24 * 60 * 60 * 1000), // 24 hours ago
                'xaxis.range[1]': new Date()
            };

            try {
                gd.emit('plotly_relayout', testEventData);
                if (typeof console !== 'undefined' && console.log) {
                    console.log('[DEBUG] Test event emitted successfully');
                }
            } catch (e) {
                alert('[DEBUG] Failed to emit test event: ' + e.message);
            }
        }
    });

    let currentDragMode = gd.layout.dragmode || 'pan';
    let previousDragMode = gd.layout.dragmode || 'pan'; // Store previous mode for restoration
    let isDragging = false;
    let shapeWasMoved = false;
    
    /* OLD DRAG DETECTION DISABLED - Using SVG observer instead
    // Track drag state
    gd.addEventListener('mousedown', function() {
        isDragging = true;
        console.log('ISDRAGGING TRUE');
    });
    
    gd.addEventListener('mouseup', function() {
        isDragging = false;
        console.log('ISDRAGGING false');
        if (shapeWasMoved) {
            console.log('Detected shape movement - switching to edit mode');
            currentDragMode = gd.layout.dragmode;
            Plotly.relayout(gd, 'dragmode', 'drawline');
            shapeWasMoved = false;
        }
    });
    
    // Detect shape movement
    gd.on('plotly_relayout', function(eventData) {
        const shapeKeys = Object.keys(eventData).filter(key => key.startsWith('shapes['));
        if (shapeKeys.length > 0 && isDragging) {
            shapeWasMoved = true;
        }
    });
    */
    
    gd.on('plotly_shapedrawn', async function(eventShapeData) {
        console.log('[DEBUG] plotly_shapedrawn FIRED. Shape from event:', JSON.parse(JSON.stringify(eventShapeData)));

        // The shape drawn is usually the last one added to gd.layout.shapes
        // and it won't have an id yet.
        const currentLayoutShapes = gd.layout.shapes || [];
        let newlyAddedShapeInLayout = null;

        if (currentLayoutShapes.length > 0) {
            const lastShapeInLayout = currentLayoutShapes[currentLayoutShapes.length - 1];
            // Basic check: if it's a line, has no id, and isn't already being processed.
            // A more robust match would compare coordinates if Plotly guarantees eventShapeData matches.
            if (lastShapeInLayout.type === eventShapeData.type &&
                !lastShapeInLayout.id &&
                !lastShapeInLayout.isSystemShape && // Should not be needed for user-drawn shapes
                !lastShapeInLayout._savingInProgress) {
                newlyAddedShapeInLayout = lastShapeInLayout;
            }
        }

        if (newlyAddedShapeInLayout) {
            console.log('[plotly_shapedrawn] Identified new shape in layout to process:', newlyAddedShapeInLayout);
            newlyAddedShapeInLayout._savingInProgress = true; // Set flag on the actual layout shape

            // Ensure the layout shape has editable and layer properties consistent with eventShapeData or defaults
            newlyAddedShapeInLayout.editable = true;
            if (newlyAddedShapeInLayout.line) {
                newlyAddedShapeInLayout.line.layer = 'above';
            } else if (newlyAddedShapeInLayout.type === 'line') { // Ensure line property exists
                newlyAddedShapeInLayout.line = { color: DEFAULT_DRAWING_COLOR, width: 2, layer: 'above' };
            }

            // Add larger markers for mobile touch targets (only for user-drawn lines)
            if (newlyAddedShapeInLayout.type === 'line' && !newlyAddedShapeInLayout.isSystemShape) {
                newlyAddedShapeInLayout.marker = {
                    size: isMobileDevice() ? 24 : 16, // Even larger markers for maximum visibility
                    color: DEFAULT_DRAWING_COLOR,
                    symbol: 'diamond', // Diamond symbol is more distinctive than circle
                    line: { width: 3, color: 'white' }, // Thicker white border
                    opacity: 0.95 // Make markers more opaque for better visibility
                };
            }

            // Pass the layout shape to handleNewShapeSave, as it has resolved xref/yref
            const backendId = await handleNewShapeSave(newlyAddedShapeInLayout);

            if (backendId) {
                newlyAddedShapeInLayout.id = backendId;
                // editable is already true
                window.activeShapeForPotentialDeletion = { id: backendId, index: currentLayoutShapes.indexOf(newlyAddedShapeInLayout), shape: newlyAddedShapeInLayout };
                updateSelectedShapeInfoPanel(window.activeShapeForPotentialDeletion);
                await updateShapeVisuals();
                console.log(`[plotly_shapedrawn] Shape processed and updated in layout with id: ${backendId}`);
            } else {
                console.warn('[plotly_shapedrawn] handleNewShapeSave did not return a backendId. Removing shape from layout to prevent duplicates.');
                const indexToRemove = currentLayoutShapes.indexOf(newlyAddedShapeInLayout);
                if (indexToRemove > -1) currentLayoutShapes.splice(indexToRemove, 1);
                Plotly.relayout(gd, {shapes: currentLayoutShapes}); // Update layout
            }
            delete newlyAddedShapeInLayout._savingInProgress; // Clear the flag
        } else {
            console.warn('[plotly_shapedrawn] Could not identify the newly drawn shape in gd.layout.shapes or it was already processed. Relayout might handle it.');
        }
    });

    const originalRelayoutHandler = gd.onplotly_relayout;

    let shapeDragEndTimer = null;
    const DEBOUNCE_DELAY = 500; // ms

    gd.on('plotly_relayouting', function(eventData) {
        // Clean up duplicate drag helpers that might interfere with dragging
        if (window.d3) {
            d3.selectAll('g[drag-helper="true"]').remove();
        }

        // Analyze the eventData to distinguish drag types
        const eventKeys = Object.keys(eventData);
        const hasShapeChanges = eventKeys.some(key => key.startsWith('shapes['));
        const hasAxisRangeChanges = eventKeys.some(key => key.includes('axis.range'));
        const isDragModeChange = eventKeys.includes('dragmode');

        // Only set dragging flag for actual shape interactions, NOT dragmode changes
        if (hasShapeChanges && !isDragModeChange) {
            console.log('[DRAGGING] Shape dragging detected - switching to drawline mode');
            window.isDraggingShape = true;

            // Store current mode before switching
            previousDragMode = gd.layout.dragmode;

            // Switch to drawline mode when dragging shapes
            if (gd.layout.dragmode !== 'drawline') {
                Plotly.relayout(gd, { dragmode: 'drawline' });
                console.log('[DRAGGING] Switched to drawline mode for shape editing');
            }

            // 🚨 DISABLE LIVE DATA when dragging shapes to prevent interference
            if (window.liveDataCheckbox && window.liveDataCheckbox.checked) {
                console.log('[DRAGGING] Disabling live data during shape dragging to prevent interference');
                window.liveDataCheckbox.checked = false;
                window.liveDataCheckbox.dispatchEvent(new Event('change'));
            }
        } else if (isDragModeChange) {
            // Handle dragmode changes separately - don't set dragging flag
            console.log('[DRAGMODE] Dragmode changed to:', eventData.dragmode);
            // Allow line coloring in draw mode by not setting isDraggingShape
        } else {
            // For axis range changes or unknown events, don't set dragging flag
            window.isDraggingShape = false;
        }
    });


    // Handle Plotly click events for better coordinate handling
    gd.on('plotly_click', function(plotlyEventData) {
        console.log('[DEBUG] PLOTLY_CLICK EVENT FIRED! Event data:', plotlyEventData);

        // Plotly provides better coordinate handling
        if (plotlyEventData.points && plotlyEventData.points.length > 0) {
            const point = plotlyEventData.points[0];
            console.log('[DEBUG] Plotly click point:', point);

            // For now, let's just try to detect if we're near any shapes
            // We'll use a simpler approach - check all shapes and see if any are close to the click
            const currentShapes = gd.layout.shapes || [];
            console.log(`[DEBUG] Checking ${currentShapes.length} shapes for click proximity`);

            for (let i = 0; i < currentShapes.length; i++) {
                const shape = currentShapes[i];
                if (shape.type === 'line' && shape.id && !shape.isSystemShape) {
                    console.log(`[DEBUG] Found clickable shape ${i}: ID=${shape.id}, x0=${shape.x0}, y0=${shape.y0}, x1=${shape.x1}, y1=${shape.y1}`);
        
                    // For now, let's just assume any line shape that exists is clickable
                    // This is a simplified approach to test if the event handling works
                    const clickedShapeId = shape.id;
                    console.log(`[DEBUG] Clicked on shape ID: ${clickedShapeId}`);

                    // Update UI for click (selection)
                    if(clickedShapeId) {
                        findAndupdateSelectedShapeInfoPanel(clickedShapeId);
                    }
                    debouncedUpdateShapeVisuals();

                    break; // Stop after finding first shape
                }
            }
        }
    });


    gd.on('plotly_relayout', async function(eventData) {
        // Safe console logging for Puppeteer compatibility
        try {
            if (typeof console !== 'undefined' && console.log) {
                console.log('[DEBUG] plotly_relayout event fired with data:', eventData);
            }
        } catch (e) {
            alert('[DEBUG] plotly_relayout event fired');
        }

        // 🚨 PANNING DETECTION 🚨 - Check for ANY range changes
        const hasXRangeChange = eventData['xaxis.range[0]'] !== undefined || eventData['xaxis.range[1]'] !== undefined;
        const hasYRangeChange = eventData['yaxis.range[0]'] !== undefined || eventData['yaxis.range[1]'] !== undefined;
        const hasAutorange = eventData['xaxis.autorange'] === true || eventData['yaxis.autorange'] === true;

        const isAnyRangeChange = hasXRangeChange || hasYRangeChange || hasAutorange;

        if (isAnyRangeChange) {
            try {
                if (typeof console !== 'undefined' && console.log) {
                    // Extract x-axis range values for debugging
                    const xMin = gd.layout.xaxis?.range?.[0];
                    const xMax = gd.layout.xaxis?.range?.[1];

                    // Convert to timestamps, accounting for timezone offset
                    // Plotly displays in local time, but we need UTC timestamps for the server
                    // getTimezoneOffset() returns minutes, convert to milliseconds
                    let xMinTimestamp = null;
                    let xMaxTimestamp = null;

                    if (xMin) {
                        const minDate = new Date(xMin);
                        // getTimezoneOffset() returns the offset in minutes from UTC to local time
                        // For UTC+2, it returns 120 (local is 120 minutes ahead of UTC)
                        // To get UTC timestamp from local time, we need to subtract this offset
                        const timezoneOffsetMs = minDate.getTimezoneOffset() * 60 * 1000;
                        xMinTimestamp = Math.floor((minDate.getTime() - timezoneOffsetMs) / 1000);
                        console.log('[TIMESTAMP DEBUG] xMin conversion:', {
                            xMin: xMin,
                            minDate: minDate.toISOString(),
                            timezoneOffsetMs: timezoneOffsetMs,
                            timezoneOffsetMinutes: minDate.getTimezoneOffset(),
                            xMinTimestamp: xMinTimestamp,
                            xMinTimestampDate: new Date(xMinTimestamp * 1000).toISOString()
                        });
                    }

                    if (xMax) {
                        const maxDate = new Date(xMax);
                        const timezoneOffsetMs = maxDate.getTimezoneOffset() * 60 * 1000;
                        xMaxTimestamp = Math.floor((maxDate.getTime() - timezoneOffsetMs) / 1000);
                        console.log('[TIMESTAMP DEBUG] xMax conversion:', {
                            xMax: xMax,
                            maxDate: maxDate.toISOString(),
                            timezoneOffsetMs: timezoneOffsetMs,
                            timezoneOffsetMinutes: maxDate.getTimezoneOffset(),
                            xMaxTimestamp: xMaxTimestamp,
                            xMaxTimestampDate: new Date(xMaxTimestamp * 1000).toISOString()
                        });
                    }

                    console.log('🚨 CHART RANGE CHANGE DETECTED 🚨', {
                        xRangeChanged: hasXRangeChange,
                        yRangeChanged: hasYRangeChange,
                        autorange: hasAutorange,
                        xRange: [xMin, xMax],
                        xTimestamps: [xMinTimestamp, xMaxTimestamp],
                        xRangeHuman: xMin && xMax ? `${new Date(xMin).toISOString()} to ${new Date(xMax).toISOString()}` : 'N/A',
                        yRange: gd.layout.yaxis?.range,
                        timestamp: new Date().toISOString(),
                        eventData: eventData
                    });

                    // Specific logging for server comparison
                    if (xMinTimestamp && xMaxTimestamp) {
                        // xMinTimestamp and xMaxTimestamp are already in seconds (converted above)
                        const clientRange = {
                            xMinTimestamp,
                            xMaxTimestamp,
                            xMinDate: new Date(xMinTimestamp * 1000).toISOString(),
                            xMaxDate: new Date(xMaxTimestamp * 1000).toISOString(),
                            rangeSeconds: xMaxTimestamp - xMinTimestamp,
                            rangeHours: (xMaxTimestamp - xMinTimestamp) / 3600
                        };

                        console.log('📊 CLIENT X-AXIS RANGE (for server comparison):', clientRange);

                        // Store for comparison with server response
                        window.lastClientRange = clientRange;
                        console.log('💾 Stored client range for server comparison. Look for 📊 SERVER RECEIVED RANGE in server logs.');
                    }
                } else {
                    alert('🚨 CHART RANGE CHANGE DETECTED 🚨');
                }
            } catch (e) {
                alert('🚨 CHART RANGE CHANGE DETECTED 🚨 (console not available)');
            }

            // Dispatch custom event for other parts of the app to listen to
            const panEvent = new CustomEvent('chartPanned', {
                detail: {
                    xRange: gd.layout.xaxis?.range,
                    yRange: gd.layout.yaxis?.range,
                    eventData: eventData
                }
            });
            document.dispatchEvent(panEvent);

            // Update UI indicator
            updatePanningStatus(true);

            // Reset status after 3 seconds
            setTimeout(() => {
                updatePanningStatus(false);
            }, 3000);
        } else {
            // Log non-range events too for debugging
            try {
                if (typeof console !== 'undefined' && console.log) {
                    console.log('[DEBUG] plotly_relayout event (non-range):', Object.keys(eventData));
                }
            } catch (e) {
                // Ignore console errors
            }
        }

        // Check if dragmode changed to 'drawline'
        if (eventData['dragmode'] === 'drawline') {
            if (window.liveDataCheckbox && window.liveDataCheckbox.checked) {
                window.liveDataCheckbox.checked = false;
                // Optionally, trigger the change event if other listeners depend on it
                window.liveDataCheckbox.dispatchEvent(new Event('change'));
                console.log('Live data unchecked due to drawline mode activation.');
            }
        }

        if(eventData.shape) {
            console.log('Shape hovered:', eventData.shape);
            return;
        }
        if (originalRelayoutHandler) originalRelayoutHandler(eventData);

        let interactedShapeIndex = -1;
        console.log(`[plotly_relayout] Checking for shape changes in eventData keys:`, Object.keys(eventData));

        for (const key in eventData) {
            if (key.startsWith('shapes[')) {
                console.log(`[plotly_relayout] Found shape-related key: ${key} = ${eventData[key]}`);
                const match = key.match(/shapes\[(\d+)\]/);
                if (match && match[1]) {
                    interactedShapeIndex = parseInt(match[1], 10);
                    console.log(`[plotly_relayout] Extracted shape index: ${interactedShapeIndex}`);
                    break;
                }
            }
        }

        if (interactedShapeIndex !== -1 && gd.layout.shapes && gd.layout.shapes[interactedShapeIndex]) {
            const interactedShape = gd.layout.shapes[interactedShapeIndex];
            if (interactedShape.id && !interactedShape.isSystemShape) {

                // --- Visual feedback on drag start (Temporarily disabled to fix line disappearing)---
                // if (interactedShape.line.color !== 'rgba(255, 0, 255, 0.5)') {
                //     const currentShapes = [...gd.layout.shapes];
                //     currentShapes[interactedShapeIndex].line.color = 'rgba(255, 0, 255, 0.5)'; // Temporary color
                //     Plotly.relayout(gd, { shapes: currentShapes });
                //     }
                // --- Debounced save on drag end ---
                clearTimeout(shapeDragEndTimer);
                shapeDragEndTimer = setTimeout(async () => {
                    console.log(`[plotly_relayout] Drag end detected for shape ${interactedShape.id}, attempting to save.`);
                    console.log(`[plotly_relayout] Shape data:`, {
                        id: interactedShape.id,
                        x0: interactedShape.x0,
                        y0: interactedShape.y0,
                        x1: interactedShape.x1,
                        y1: interactedShape.y1,
                        type: interactedShape.type
                    });

                    // It's possible the shape was deleted or changed, so we get the latest version
                    const finalShapeState = gd.layout.shapes[interactedShapeIndex];
                    if (finalShapeState && finalShapeState.id === interactedShape.id) {
                        console.log(`[plotly_relayout] Final shape state:`, {
                            id: finalShapeState.id,
                            x0: finalShapeState.x0,
                            y0: finalShapeState.y0,
                            x1: finalShapeState.x1,
                            y1: finalShapeState.y1,
                            type: finalShapeState.type
                        });

                        const saveSuccess = await sendShapeUpdateToServer(finalShapeState, window.symbolSelect.value);
                        console.log(`[plotly_relayout] Shape update result: ${saveSuccess ? 'SUCCESS' : 'FAILED'}`);

                        if (!saveSuccess) {
                            console.warn(`[plotly_relayout] Shape update failed, reloading drawings`);
                            loadDrawingsAndRedraw(window.symbolSelect.value);
                        } else {
                            // Restore original color after successful save
                            console.log(`[plotly_relayout] Shape update successful, updating visuals`);
                            await updateShapeVisuals(); // This should handle restoring the color
                        }
                    } else {
                        console.warn(`[plotly_relayout] Shape state mismatch or shape was deleted during update`);
                    }
                }, DEBOUNCE_DELAY);

                const selectionChanged = !window.activeShapeForPotentialDeletion || window.activeShapeForPotentialDeletion.id !== interactedShape.id;
                if (selectionChanged) {
                    window.activeShapeForPotentialDeletion = { id: interactedShape.id, index: interactedShapeIndex, shape: interactedShape };
                    await updateShapeVisuals();
                } else {
                    window.activeShapeForPotentialDeletion.shape = interactedShape;
                }
                updateSelectedShapeInfoPanel(window.activeShapeForPotentialDeletion);
            }
        }

        // New shape detection logic (fallback or for shapes not caught by plotly_shapedrawn)
        const currentLayoutShapesForNewCheck = window.gd.layout.shapes || [];
        let newShapesProcessedInRelayout = false;
        for (let i = 0; i < currentLayoutShapesForNewCheck.length; i++) {
            const shapeInLayout = currentLayoutShapesForNewCheck[i];

            // Check if this is already a processed drawing (has drawing_ prefix in name)
            const isAlreadyProcessedDrawing = shapeInLayout.name && shapeInLayout.name.startsWith('drawing_');

            // Additional check: warn if we have an id but it's still being processed
            if (shapeInLayout.id && !shapeInLayout._savingInProgress) {
                console.warn('[plotly_relayout] WARNING: Shape already has id but is being considered for processing:', {
                    name: shapeInLayout.name,
                    id: shapeInLayout.id,
                    type: shapeInLayout.type,
                    isSystemShape: shapeInLayout.isSystemShape,
                    isAlreadyProcessedDrawing: isAlreadyProcessedDrawing
                });
                continue; // Skip this shape entirely
            }

            if (shapeInLayout.type === 'line' &&
                !shapeInLayout.id &&
                !shapeInLayout.isSystemShape && // Already correctly ignores system shapes
                !shapeInLayout._savingInProgress && // Check this flag
                !isAlreadyProcessedDrawing // Additional check for already processed drawings
               ) {

                // DETAILED LOGGING FOR POTENTIALLY MISIDENTIFIED NEW SHAPE
                console.warn('[plotly_relayout] Fallback: Potential new shape to save. Inspecting properties:', {
                    name: shapeInLayout.name,
                    type: shapeInLayout.type,
                    x0: shapeInLayout.x0, y0: shapeInLayout.y0,
                    x1: shapeInLayout.x1, y1: shapeInLayout.y1,
                    xref: shapeInLayout.xref, yref: shapeInLayout.yref,
                    id: shapeInLayout.id, // Should be undefined/null
                    isSystemShape: shapeInLayout.isSystemShape, // CRITICAL: Should be true for system shapes to be ignored
                    _savingInProgress: shapeInLayout._savingInProgress, // Should be false or undefined
                    isAlreadyProcessedDrawing: isAlreadyProcessedDrawing
                });
                shapeInLayout._savingInProgress = true; // Set flag on the layout shape
                console.log(`[plotly_relayout] Fallback: Found new unsaved line (index ${i}), attempting to save:`, JSON.parse(JSON.stringify(shapeInLayout)));
                
                // Ensure shape has necessary properties before saving
                shapeInLayout.editable = true;
                if (shapeInLayout.line) {
                    shapeInLayout.line.layer = 'above';
                } else if (shapeInLayout.type === 'line') {
                    shapeInLayout.line = { color: DEFAULT_DRAWING_COLOR, width: 2, layer: 'above' };
                }

                // Add larger markers for mobile touch targets (only for user-drawn lines)
                if (shapeInLayout.type === 'line' && !shapeInLayout.isSystemShape) {
                    shapeInLayout.marker = {
                        size: isMobileDevice() ? 24 : 16, // Even larger markers for maximum visibility
                        color: DEFAULT_DRAWING_COLOR,
                        symbol: 'diamond', // Diamond symbol is more distinctive than circle
                        line: { width: 3, color: 'white' }, // Thicker white border
                        opacity: 0.95 // Make markers more opaque for better visibility
                    };
                }

                const backendId = await handleNewShapeSave(shapeInLayout);

                if (backendId) {
                    // Find the current index of the shape in the live layout (it might have shifted due to removals)
                    const currentIndex = window.gd.layout.shapes.indexOf(shapeInLayout);
                    if (currentIndex > -1 && !window.gd.layout.shapes[currentIndex].id) {
                        window.gd.layout.shapes[currentIndex].id = backendId;
                        // editable and layer already set
                        window.activeShapeForPotentialDeletion = { id: backendId, index: currentIndex, shape: window.gd.layout.shapes[currentIndex] };
                        updateSelectedShapeInfoPanel(window.activeShapeForPotentialDeletion);
                        console.log(`[plotly_relayout] Fallback: New shape (index ${currentIndex}) saved with id: ${backendId}`);
                        newShapesProcessedInRelayout = true;
                    } else {
                          console.warn(`[plotly_relayout] Fallback: Shape was already processed, changed, or removed before id could be assigned by relayout.`);
                    }
                } else {
                    console.warn(`[plotly_relayout] Fallback: Failed to save new shape. Removing from layout.`);
                    // Remove the shape if save failed to prevent it from being re-processed
                    const indexToRemove = window.gd.layout.shapes.indexOf(shapeInLayout);
                    if (indexToRemove > -1) window.gd.layout.shapes.splice(indexToRemove, 1);
                    // No need to Plotly.relayout here, as this loop is part of a relayout,
                    // but a full redraw might be needed if things get out of sync.
                    // For now, just remove from the array being iterated if possible, or mark it.
                    // A full loadDrawingsAndRedraw might be too disruptive here.
                }
                delete shapeInLayout._savingInProgress; // Clear the flag
            }
        }
        if (newShapesProcessedInRelayout) {
            await updateShapeVisuals(); // Update visuals if relayout processed new shapes
        }

        // Axis range change handling
        let rangesChangedByEvent = false;
        let userModifiedRanges = false;

        console.log('[DEBUG] Checking for axis range changes in eventData:', {
            hasXRange0: !!eventData['xaxis.range[0]'],
            hasXRange1: !!eventData['xaxis.range[1]'],
            hasAutorange: eventData['xaxis.autorange'] === true,
            eventDataKeys: Object.keys(eventData)
        });

        if (eventData['xaxis.range[0]'] || eventData['xaxis.range[1]']) {
            console.log('[DEBUG] X-axis range change detected');
            const currentLayoutShapes = gd.layout.shapes || [];
            const xRange = gd.layout.xaxis.range;
            console.log('[DEBUG] Current xRange from layout:', xRange);
            if (xRange && xRange.length === 2) {
                // Keep in milliseconds - Plotly already provides proper Date objects/timestamps
                const minTimestamp = (xRange[0] instanceof Date) ? xRange[0].getTime() : new Date(xRange[0]).getTime();
                const maxTimestamp = (xRange[1] instanceof Date) ? xRange[1].getTime() : new Date(xRange[1]).getTime();

                console.log('[DEBUG] Calculated timestamps:', { minTimestamp, maxTimestamp });

                // 🚨 OLD ALARM CHECK: Validate zoom/pan timestamps before saving
                const minDate = new Date(minTimestamp);
                const maxDate = new Date(maxTimestamp);
                if (minDate.getFullYear() < 2000 || maxDate.getFullYear() < 2000) {
                    const minDateStr = isNaN(minDate.getTime()) ? 'Invalid Date' : minDate.toISOString();
                    const maxDateStr = isNaN(maxDate.getTime()) ? 'Invalid Date' : maxDate.toISOString();
                    console.warn('🚨 OLD ALARM DETECTED: Chart zoom/pan resulted in very old dates!', {
                        source: 'plotly_relayout_zoom',
                        xRange: xRange,
                        minTimestamp: minTimestamp,
                        maxTimestamp: maxTimestamp,
                        minDate: minDateStr,
                        maxDate: maxDateStr,
                        minYear: minDate.getFullYear(),
                        maxYear: maxDate.getFullYear(),
                        action: 'Chart zoom/pan calculated timestamps before year 2000 - this should not happen!'
                    });
                }

                // Store timestamps in milliseconds for consistency with the rest of the system
                window.currentXAxisRange = [minTimestamp, maxTimestamp];

                // Update display elements with validation
                try {
                    window.xAxisMinDisplay.textContent = new Date(minTimestamp).toISOString();
                } catch (e) {
                    console.error("Error formatting xAxisMinDisplay:", e);
                    window.xAxisMinDisplay.textContent = `Invalid Date: ${minTimestamp}`;
                }

                try {
                    window.xAxisMaxDisplay.textContent = new Date(maxTimestamp).toISOString();
                } catch (e) {
                    console.error("Error formatting xAxisMaxDisplay:", e);
                    window.xAxisMaxDisplay.textContent = `Invalid Date: ${maxTimestamp}`;
                }

                if (!window.isApplyingAutoscale) {
                    rangesChangedByEvent = true;
                    userModifiedRanges = true;
                }
                console.log('[DEBUG] Updated currentXAxisRange (in seconds):', window.currentXAxisRange);
            } else {
                console.log('[DEBUG] xRange is invalid or missing:', xRange);
            }
        } else if (eventData['xaxis.autorange'] === true) {
            if (window.currentXAxisRange !== null) {
                console.log('[DEBUG] Autorange detected, clearing currentXAxisRange');
                window.currentXAxisRange = null;
                window.xAxisMinDisplay.textContent = 'Auto';
                window.xAxisMaxDisplay.textContent = 'Auto';
                rangesChangedByEvent = true;
            } else {
                // On first load or when no previous range, update to actual range
                const xRange = gd.layout.xaxis.range;
                if (xRange && xRange.length === 2) {
                    const minTimestamp = (xRange[0] instanceof Date) ? xRange[0].getTime() : new Date(xRange[0]).getTime();
                    const maxTimestamp = (xRange[1] instanceof Date) ? xRange[1].getTime() : new Date(xRange[1]).getTime();
                    window.currentXAxisRange = [minTimestamp, maxTimestamp];

                    // Update display elements with validation
                    try {
                        window.xAxisMinDisplay.textContent = new Date(minTimestamp).toISOString();
                    } catch (e) {
                        console.error("Error formatting xAxisMinDisplay on autorange:", e);
                        window.xAxisMinDisplay.textContent = `Invalid Date: ${minTimestamp}`;
                    }

                    try {
                        window.xAxisMaxDisplay.textContent = new Date(maxTimestamp).toISOString();
                    } catch (e) {
                        console.error("Error formatting xAxisMaxDisplay on autorange:", e);
                        window.xAxisMaxDisplay.textContent = `Invalid Date: ${maxTimestamp}`;
                    }

                    console.log('[DEBUG] Autorange on first load, updating to actual range');
                    // Don't save settings for initial autorange
                    rangesChangedByEvent = false;
                }
            }
        } else {
            console.log('[DEBUG] No axis range changes detected in this event');
        }

        if (eventData['yaxis.range[0]'] || eventData['yaxis.range[1]']) {
            const yRange = gd.layout.yaxis.range;
            if (yRange && yRange.length === 2) {
                window.currentYAxisRange = [yRange[0], yRange[1]];
                window.yAxisMinDisplay.textContent = window.currentYAxisRange[0].toFixed(2);
                window.yAxisMaxDisplay.textContent = window.currentYAxisRange[1].toFixed(2);
                if (!window.isApplyingAutoscale) {
                    rangesChangedByEvent = true;
                    userModifiedRanges = true;
                }
            }
        } else if (eventData['yaxis.autorange'] === true && window.currentYAxisRange !== null) {
            window.currentYAxisRange = null;
            window.yAxisMinDisplay.textContent = 'Auto';
            window.yAxisMaxDisplay.textContent = 'Auto';
            rangesChangedByEvent = true;
        }

        if (rangesChangedByEvent && userModifiedRanges) {
            console.log('[plotly_relayout] Ranges changed by user. User modified:', userModifiedRanges, 'New X-Range:', window.currentXAxisRange, 'New Y-Range:', window.currentYAxisRange);
            saveSettings(); // from settingsManager.js
            // Debounce chart update if ranges were changed by user panning/zooming,
            // or if autorange occurred (which means we need to reload based on dropdowns)
            clearTimeout(window.fetchDataDebounceTimer); // fetchDataDebounceTimer from state.js
            window.fetchDataDebounceTimer = setTimeout(() => {
                console.log('[plotly_relayout] Debounced chart update due to axis range change.');
                // Update combined WebSocket with new time range
                const symbol = window.symbolSelect ? window.symbolSelect.value : null;
                const resolution = window.resolutionSelect ? window.resolutionSelect.value : '1h';
                if (symbol && resolution && window.currentXAxisRange) {
                    const activeIndicators = Array.from(document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
                    // currentXAxisRange is already in seconds, no need to divide by 1000
                    const fromTs = Math.floor(window.currentXAxisRange[0]);
                    const toTs = Math.floor(window.currentXAxisRange[1]);

                    // Check if we need to request more historical data
                    const needsMoreData = checkIfHistoricalDataNeeded(fromTs, toTs, resolution);
                    if (needsMoreData) {
                        console.log('[plotly_relayout] Requesting additional historical data for new time range');
                        // Request historical data with expanded range to provide buffer
                        const bufferMultiplier = 2; // Request 2x the visible range for buffer
                        const bufferedFromTs = Math.floor(fromTs - (toTs - fromTs) * (bufferMultiplier - 1) / 2);
                        const bufferedToTs = Math.floor(toTs + (toTs - fromTs) * (bufferMultiplier - 1) / 2);

                        setupCombinedWebSocket(symbol, activeIndicators, resolution, bufferedFromTs, bufferedToTs);
                    } else {
                        // 🔧 FIX TIMESTAMP SYNCHRONIZATION: Use ISO timestamp strings with timezone
                        // window.currentXAxisRange is in milliseconds, convert to ISO strings
                        const wsFromTs = new Date(window.currentXAxisRange[0]).toISOString();
                        const wsToTs = new Date(window.currentXAxisRange[1]).toISOString();

                        console.log('[plotly_relayout] 🔍 TIMESTAMP CONVERSION DEBUG:');
                        console.log('  window.currentXAxisRange:', window.currentXAxisRange);
                        console.log('  wsFromTs (ISO):', wsFromTs);
                        console.log('  wsToTs (ISO):', wsToTs);

                        // If WebSocket is open, send new config, otherwise establish new connection
                        if (window.combinedWebSocket && window.combinedWebSocket.readyState === WebSocket.OPEN) {
                            setupCombinedWebSocket(symbol, activeIndicators, resolution, wsFromTs, wsToTs);
                        } else {
                            setTimeout(() => {
                                setupCombinedWebSocket(symbol, activeIndicators, resolution, wsFromTs, wsToTs);
                            }, 100);
                        }
                    }
                }
            }, FETCH_DEBOUNCE_DELAY); // FETCH_DEBOUNCE_DELAY from config.js
        } else if (rangesChangedByEvent && !userModifiedRanges) {
            console.log('[plotly_relayout] Ranges changed programmatically. User modified:', userModifiedRanges, 'New X-Range:', window.currentXAxisRange, 'New Y-Range:', window.currentYAxisRange);
            // Don't save settings for programmatic changes
        }

        // Reset dragging flag and restore previous drag mode after relayout completes
        if (window.isDraggingShape) {
            window.isDraggingShape = false;
            // Restore previous drag mode
            if (gd.layout.dragmode !== previousDragMode) {
                Plotly.relayout(gd, { dragmode: previousDragMode });
                console.log(`[DRAGGING] Shape dragging completed - restored to ${previousDragMode} mode`);
            } else {
                console.log('[DRAGGING] Shape dragging completed');
            }

            // Re-trigger hover detection after drag completion to restore line coloring
            setTimeout(() => {
                if (window.colorTheLine) {
                    window.colorTheLine();
                    console.log('[DRAGGING] Re-triggered hover detection after drag completion');
                }
            }, 100); // Small delay to ensure relayout is complete
        }
    });

    gd.on('plotly_shapeupdate', async function(eventData) {
        // This event name 'plotly_shapeupdate' is not standard Plotly.
        // Shape modifications (dragging handles) trigger 'plotly_relayout'.
        // The logic for handling shape modifications is already within the 'plotly_relayout' handler
        // using 'interactedShapeIndex'. If this was a custom event or a specific
        // interpretation in the old index.html, its exact trigger is unclear.
        // For now, assuming this was intended for modifications caught by 'plotly_relayout'.
        console.warn('[plotly_shapeupdate] This event handler was called. Standard shape modifications are handled by plotly_relayout. Event data:', eventData);
        // If eventData contains a shape index and the update:
        const shapeIndex = eventData.shapeindex; // Hypothetical eventData structure
        if (shapeIndex !== undefined && gd.layout.shapes && gd.layout.shapes[shapeIndex]) {
            const updatedShape = gd.layout.shapes[shapeIndex];
            if (updatedShape.id) {
                console.log(`[plotly_shapeupdate] Detected update for shape ${updatedShape.id}, attempting to save.`);
                const saveSuccess = await sendShapeUpdateToServer(updatedShape, window.symbolSelect.value);
                if (!saveSuccess) {
                    loadDrawingsAndRedraw(window.symbolSelect.value);
                    return;
                }
                // Update active shape state if this is the one being edited
                if (!window.activeShapeForPotentialDeletion || window.activeShapeForPotentialDeletion.id !== updatedShape.id) {
                    window.activeShapeForPotentialDeletion = { id: updatedShape.id, index: shapeIndex, shape: updatedShape };
                } else { // It is the active shape, ensure its 'shape' property is updated
                    window.activeShapeForPotentialDeletion.shape = updatedShape;
                }
                updateSelectedShapeInfoPanel(window.activeShapeForPotentialDeletion);
                await updateShapeVisuals();
            }
        }
    });

    gd.on('plotly_remove_shape', async function(eventData) {
        // This event name 'plotly_remove_shape' is not standard Plotly.
        // Deletions (e.g., via modebar if configured, or programmatically) would trigger 'plotly_relayout'.
        // The primary deletion mechanism in this app is the 'Delete' key, handled by a separate listener.
        // This handler is speculative, assuming 'eventData' contains the removed shape.
        console.warn('[plotly_remove_shape] This event handler was called. Deletions are primarily handled by keydown. Event data:', eventData);
        const removedShape = eventData.shape; // Hypothetical: eventData directly provides the removed shape object
        if (removedShape && removedShape.id) {
            const symbol = window.symbolSelect.value;
            console.log(`[plotly_remove_shape] Attempting to delete shape ${removedShape.id} from backend.`);
            try {
                const response = await fetch(`/delete_drawing/${symbol}/${removedShape.id}`, { method: 'DELETE' });
                if (!response.ok) throw new Error(`Backend delete failed: ${response.status} ${await response.text()}`);
                console.log(`Drawing ${removedShape.id} deleted from backend via plotly_remove_shape.`);
                if (window.activeShapeForPotentialDeletion && window.activeShapeForPotentialDeletion.id === removedShape.id) {
                    window.activeShapeForPotentialDeletion = null;
                    updateSelectedShapeInfoPanel(null);
                }
                await updateShapeVisuals(); // Refresh visuals
            } catch (error) {
                console.error(`Error deleting drawing ${removedShape.id} via plotly_remove_shape:`, error);
                alert(`Failed to delete drawing: ${error.message}`);
                loadDrawingsAndRedraw(symbol); // Sync with backend
            }
        }
    });
}

function observeShapeDAttributeChanges(plotDivId) {
    const plotDiv = document.getElementById(plotDivId);
    if (!plotDiv) {
        console.error(`Plotly div with id "${plotDivId}" not found.`);
        return;
    }

    // Target the 'g' element with class 'shapelayer'
    const shapeLayer = plotDiv.querySelector('.shapelayer');
    if (!shapeLayer) {
        console.error('Shape layer not found. Is a shape being drawn?');
        return;
    }

    // Select all 'path' elements that are part of the 'drag-helper' groups
    const dragHelperPaths = shapeLayer.querySelectorAll('g[drag-helper="true"] > path');

    if (dragHelperPaths.length === 0) {
        console.warn('No draggable shape paths found. Make sure shape editing is enabled.');
        return;
    }

    dragHelperPaths.forEach(pathElement => {
        // Create an observer instance
        const observer = new MutationObserver(mutationsList => {
            for (const mutation of mutationsList) {
                // Check if the 'd' attribute was the one that changed
                if (mutation.type === 'attributes' && mutation.attributeName === 'd') {
                    const newDValue = mutation.target.getAttribute('d');
                    console.log('Path d attribute changed:', newDValue);
                    // You can perform an action here, like updating a different element or triggering a function
                }
            }
        });

        // Start observing the target path element for attribute changes
        observer.observe(pathElement, { attributes: true, attributeFilter: ['d'] });
    });
}

// Function to observe changes to the 'd' attribute of paths in the shape layer
function observeShapeDAttributeChanges(plotDivId) {
    const plotDiv = document.getElementById(plotDivId);
    if (!plotDiv) {
        console.error(`Plotly div with id "${plotDivId}" not found.`);
        return;
    }

    // Target the 'g' element with class 'shapelayer'
    const shapeLayer = plotDiv.querySelector('.shapelayer');
    if (!shapeLayer) {
        console.error('Shape layer not found. Is a shape being drawn?');
        return;
    }

    // Select all 'path' elements that are part of the 'drag-helper' groups
    const dragHelperPaths = shapeLayer.querySelectorAll('g[drag-helper="true"] > path');

    if (dragHelperPaths.length === 0) {
        console.warn('No draggable shape paths found. Make sure shape editing is enabled.');
        return;
    }

    dragHelperPaths.forEach(pathElement => {
        // Create an observer instance
        const observer = new MutationObserver(mutationsList => {
            for (const mutation of mutationsList) {
                // Check if the 'd' attribute was the one that changed
                if (mutation.type === 'attributes' && mutation.attributeName === 'd') {
                    const newDValue = mutation.target.getAttribute('d');
                    console.log('Path d attribute changed:', newDValue);
                    // You can perform an action here, like updating a different element or triggering a function
                }
            }
        });

        // Start observing the target path element for attribute changes
        observer.observe(pathElement, { attributes: true, attributeFilter: ['d'] });
    });
}

// Function to check if we need more historical data for the current visible range
function checkIfHistoricalDataNeeded(fromTs, toTs, resolution) {
    console.log('[checkIfHistoricalDataNeeded] Called with:', { fromTs, toTs, resolution });

    // Get current chart data to see what time range we already have
    const gd = window.gd;
    if (!gd || !gd.data || gd.data.length === 0) {
        console.log('[checkIfHistoricalDataNeeded] No chart data available, requesting historical data');
        return true; // No data at all, definitely need historical data
    }

    // Find the main price trace (candlestick)
    const priceTrace = gd.data.find(trace => trace.type === 'candlestick');
    if (!priceTrace || !priceTrace.x || priceTrace.x.length === 0) {
        console.log('[checkIfHistoricalDataNeeded] No price data available, requesting historical data');
        return true;
    }

    console.log('[checkIfHistoricalDataNeeded] Found price trace with', priceTrace.x.length, 'data points');

    // Get the time range of current data
    const currentDataMin = Math.min(...priceTrace.x.map(x => (x instanceof Date) ? x.getTime() : new Date(x).getTime())) / 1000;
    const currentDataMax = Math.max(...priceTrace.x.map(x => (x instanceof Date) ? x.getTime() : new Date(x).getTime())) / 1000;

    console.log('[checkIfHistoricalDataNeeded] Current data time range:', {
        currentDataMin: new Date(currentDataMin * 1000).toISOString(),
        currentDataMax: new Date(currentDataMax * 1000).toISOString(),
        requestedFrom: new Date(fromTs * 1000).toISOString(),
        requestedTo: new Date(toTs * 1000).toISOString()
    });

    // Check if the requested range extends beyond current data
    const rangeExtension = 0.1; // 10% buffer
    const extendedFromTs = fromTs - (toTs - fromTs) * rangeExtension;
    const extendedToTs = toTs + (toTs - fromTs) * rangeExtension;

    const needsEarlierData = extendedFromTs < currentDataMin;
    const needsLaterData = extendedToTs > currentDataMax;

    console.log('[checkIfHistoricalDataNeeded] Range analysis:', {
        extendedFromTs: new Date(extendedFromTs * 1000).toISOString(),
        extendedToTs: new Date(extendedToTs * 1000).toISOString(),
        needsEarlierData,
        needsLaterData
    });

    if (needsEarlierData || needsLaterData) {
        console.log('[checkIfHistoricalDataNeeded] Visible range extends beyond current data - requesting more data');
        return true;
    }

    console.log('[checkIfHistoricalDataNeeded] Current data covers the visible range adequately');
    return false;
}

// Initialize observer for main chart
observeShapeDAttributeChanges('chart'); // Use your actual chart div ID

// Global function to test panning detection
window.testPanningDetection = function() {
    // Safe console logging for Puppeteer compatibility
    try {
        if (typeof console !== 'undefined' && console.log) {
            console.log('🧪 TESTING PANNING DETECTION 🧪');
            console.log('Current chart state:', {
                hasGd: !!window.gd,
                layout: window.gd?.layout,
                xaxisRange: window.gd?.layout?.xaxis?.range,
                yaxisRange: window.gd?.layout?.yaxis?.range
            });
        }
    } catch (e) {
        // Fallback for environments where console is not available
        alert('🧪 TESTING PANNING DETECTION 🧪\nConsole not available in this environment.');
    }

    // Listen for our custom pan event
    document.addEventListener('chartPanned', function(event) {
        try {
            if (typeof console !== 'undefined' && console.log) {
                console.log('🎯 CUSTOM PAN EVENT RECEIVED:', event.detail);
            }
        } catch (e) {
            alert('🎯 CUSTOM PAN EVENT RECEIVED: ' + JSON.stringify(event.detail));
        }
    });

    try {
        if (typeof console !== 'undefined' && console.log) {
            console.log('✅ Panning detection test setup complete. Try panning the chart now.');
            console.log('Expected console output: "🚨 CHART PANNED/ZOOMED DETECTED 🚨"');
        }
    } catch (e) {
        alert('✅ Panning detection test setup complete.\nTry panning the chart now.');
    }

    // Also trigger a manual test event
    setTimeout(() => {
        try {
            if (window.gd && window.gd.emit) {
                const testEventData = {
                    'xaxis.range[0]': new Date(Date.now() - 24 * 60 * 60 * 1000),
                    'xaxis.range[1]': new Date()
                };
                window.gd.emit('plotly_relayout', testEventData);
                if (typeof console !== 'undefined' && console.log) {
                    console.log('🧪 MANUAL TEST EVENT TRIGGERED');
                } else {
                    alert('🧪 MANUAL TEST EVENT TRIGGERED');
                }
            }
        } catch (e) {
            alert('🧪 Manual test event failed: ' + e.message);
        }
    }, 1000);
};

// Function to update the panning status indicator in the UI
function updatePanningStatus(isPanning = false) {
    const indicator = document.getElementById('panning-indicator');
    const lastPanTime = document.getElementById('last-pan-time');

    if (indicator && lastPanTime) {
        if (isPanning) {
            indicator.textContent = '🚨 Panning Detected!';
            indicator.style.color = '#28a745'; // Green
            lastPanTime.textContent = new Date().toLocaleTimeString();
        } else {
            indicator.textContent = 'Waiting for pan/zoom...';
            indicator.style.color = '#666'; // Gray
        }
    }
}

// Add additional event listeners for debugging
document.addEventListener('DOMContentLoaded', function() {
    console.log('📋 PANNING DETECTION SYSTEM INITIALIZED 📋');
    console.log('Available test functions:');
    console.log('- window.testPanningDetection() - Test panning detection');
    console.log('- window.compareClientServerRanges() - Compare client and server timestamp ranges');
    console.log('- Press "T" key - Manual test event trigger');
    console.log('- Pan/zoom the chart - Should trigger automatic detection');

    // Initialize panning status
    updatePanningStatus(false);
});

// Global function to compare client and server timestamp ranges
window.compareClientServerRanges = function() {
    try {
        if (typeof console !== 'undefined' && console.log) {
            console.log('🔍 COMPARING CLIENT AND SERVER TIMESTAMP RANGES 🔍');

            if (!window.lastClientRange) {
                console.log('❌ No client range stored. Pan the chart first to capture client range.');
                return;
            }

            console.log('📊 CLIENT RANGE (stored):', window.lastClientRange);

            // Try to get server range from WebSocket state if available
            if (window.ws && window.ws.readyState === WebSocket.OPEN) {
                console.log('🔗 WebSocket is connected. Server range should be logged in server console.');
                console.log('💡 Look for "📊 SERVER RECEIVED RANGE" in server logs for comparison.');
            } else {
                console.log('⚠️ WebSocket not connected. Cannot get current server state.');
            }

            // Manual comparison if we have both ranges
            if (window.lastServerRange) {
                console.log('📊 SERVER RANGE (stored):', window.lastServerRange);

                const clientFrom = window.lastClientRange.xMinTimestamp;
                const clientTo = window.lastClientRange.xMaxTimestamp;
                const serverFrom = window.lastServerRange.fromTs;
                const serverTo = window.lastServerRange.toTs;

                const fromDiff = Math.abs(clientFrom - serverFrom);
                const toDiff = Math.abs(clientTo - serverTo);

                console.log('⚖️ COMPARISON RESULTS:');
                console.log(`  From timestamp difference: ${fromDiff} seconds (${(fromDiff / 3600).toFixed(2)} hours)`);
                console.log(`  To timestamp difference: ${toDiff} seconds (${(toDiff / 3600).toFixed(2)} hours)`);

                if (fromDiff > 60 || toDiff > 60) {
                    console.log('🚨 SIGNIFICANT DIFFERENCE DETECTED (> 1 minute)');
                    console.log('  This could indicate a timestamp conversion issue.');
                } else {
                    console.log('✅ Ranges are within acceptable tolerance (< 1 minute)');
                }
            } else {
                console.log('❌ No server range stored. Check server logs for "📊 SERVER RECEIVED RANGE".');
            }
        } else {
            alert('🔍 COMPARING CLIENT AND SERVER TIMESTAMP RANGES 🔍\nConsole not available in this environment.');
        }
    } catch (e) {
        console.error('Error in compareClientServerRanges:', e);
        alert('Error comparing ranges: ' + e.message);
    }
};
