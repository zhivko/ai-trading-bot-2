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
    console.log('[DEBUG] Plotly event handlers initialized');

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
        // and it won't have a backendId yet.
        const currentLayoutShapes = gd.layout.shapes || [];
        let newlyAddedShapeInLayout = null;

        if (currentLayoutShapes.length > 0) {
            const lastShapeInLayout = currentLayoutShapes[currentLayoutShapes.length - 1];
            // Basic check: if it's a line, has no backendId, and isn't already being processed.
            // A more robust match would compare coordinates if Plotly guarantees eventShapeData matches.
            if (lastShapeInLayout.type === eventShapeData.type &&
                !lastShapeInLayout.backendId &&
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
                newlyAddedShapeInLayout.backendId = backendId;
                // editable is already true
                window.activeShapeForPotentialDeletion = { id: backendId, index: currentLayoutShapes.indexOf(newlyAddedShapeInLayout), shape: newlyAddedShapeInLayout };
                updateSelectedShapeInfoPanel(window.activeShapeForPotentialDeletion);
                await updateShapeVisuals();
                console.log(`[plotly_shapedrawn] Shape processed and updated in layout with backendId: ${backendId}`);
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
                if (shape.type === 'line' && shape.backendId && !shape.isSystemShape) {
                    console.log(`[DEBUG] Found clickable shape ${i}: ID=${shape.backendId}, x0=${shape.x0}, y0=${shape.y0}, x1=${shape.x1}, y1=${shape.y1}`);

                    // For now, let's just assume any line shape that exists is clickable
                    // This is a simplified approach to test if the event handling works
                    const clickedShapeId = shape.backendId;
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
        for (const key in eventData) {
            if (key.startsWith('shapes[') && key.includes('].x')) {
                const match = key.match(/shapes\[(\d+)\]/);
                if (match && match[1]) {
                    interactedShapeIndex = parseInt(match[1], 10);
                    break;
                }
            }
        }

        if (interactedShapeIndex !== -1 && gd.layout.shapes && gd.layout.shapes[interactedShapeIndex]) {
            const interactedShape = gd.layout.shapes[interactedShapeIndex];
            if (interactedShape.backendId && !interactedShape.isSystemShape) {
                
                // --- Visual feedback on drag start (Temporarily disabled to fix line disappearing)---
                // if (interactedShape.line.color !== 'rgba(255, 0, 255, 0.5)') {
                //     const currentShapes = [...gd.layout.shapes];
                //     currentShapes[interactedShapeIndex].line.color = 'rgba(255, 0, 255, 0.5)'; // Temporary color
                //     Plotly.relayout(gd, { shapes: currentShapes });
                //     }
                // --- Debounced save on drag end ---
                clearTimeout(shapeDragEndTimer);
                shapeDragEndTimer = setTimeout(async () => {
                    console.log(`[plotly_relayout] Drag end detected for shape ${interactedShape.backendId}, attempting to save.`);
                    
                    // It's possible the shape was deleted or changed, so we get the latest version
                    const finalShapeState = gd.layout.shapes[interactedShapeIndex];
                    if (finalShapeState && finalShapeState.backendId === interactedShape.backendId) {
                        
                        const saveSuccess = await sendShapeUpdateToServer(finalShapeState, window.symbolSelect.value);
                        if (!saveSuccess) {
                            loadDrawingsAndRedraw(window.symbolSelect.value);
                        } else {
                            // Restore original color after successful save
                            await updateShapeVisuals(); // This should handle restoring the color
                        }
                    }
                }, DEBOUNCE_DELAY);

                const selectionChanged = !window.activeShapeForPotentialDeletion || window.activeShapeForPotentialDeletion.id !== interactedShape.backendId;
                if (selectionChanged) {
                    window.activeShapeForPotentialDeletion = { id: interactedShape.backendId, index: interactedShapeIndex, shape: interactedShape };
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
            if (shapeInLayout.type === 'line' &&
                !shapeInLayout.backendId &&
                !shapeInLayout.isSystemShape && // Already correctly ignores system shapes
                !shapeInLayout._savingInProgress // Check this flag
               ) {

               // DETAILED LOGGING FOR POTENTIALLY MISIDENTIFIED NEW SHAPE
               console.warn('[plotly_relayout] Fallback: Potential new shape to save. Inspecting properties:', {
                   name: shapeInLayout.name,
                   type: shapeInLayout.type,
                   x0: shapeInLayout.x0, y0: shapeInLayout.y0,
                   x1: shapeInLayout.x1, y1: shapeInLayout.y1,
                   xref: shapeInLayout.xref, yref: shapeInLayout.yref,
                   backendId: shapeInLayout.backendId, // Should be undefined/null
                   isSystemShape: shapeInLayout.isSystemShape, // CRITICAL: Should be true for system shapes to be ignored
                   _savingInProgress: shapeInLayout._savingInProgress // Should be false or undefined
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
                    // Check if the shape still exists at this index and hasn't been processed
                    if (window.gd.layout.shapes[i] === shapeInLayout && !window.gd.layout.shapes[i].backendId) {
                        window.gd.layout.shapes[i].backendId = backendId;
                        // editable and layer already set
                        window.activeShapeForPotentialDeletion = { id: backendId, index: i, shape: window.gd.layout.shapes[i] };
                        updateSelectedShapeInfoPanel(window.activeShapeForPotentialDeletion);
                        console.log(`[plotly_relayout] Fallback: New shape (index ${i}) saved with backendId: ${backendId}`);
                        newShapesProcessedInRelayout = true;
                    } else {
                         console.warn(`[plotly_relayout] Fallback: Shape at index ${i} was already processed, changed, or removed before backendId could be assigned by relayout.`);
                    }
                } else {
                    console.warn(`[plotly_relayout] Fallback: Failed to save new shape (index ${i}). Removing from layout.`);
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

        if (eventData['xaxis.range[0]'] || eventData['xaxis.range[1]']) {
            const currentLayoutShapes = gd.layout.shapes || [];
            const xRange = gd.layout.xaxis.range;
            if (xRange && xRange.length === 2) {
                // Keep in milliseconds - Plotly already provides proper Date objects/timestamps
                const minTimestamp = (xRange[0] instanceof Date) ? xRange[0].getTime() : new Date(xRange[0]).getTime();
                const maxTimestamp = (xRange[1] instanceof Date) ? xRange[1].getTime() : new Date(xRange[1]).getTime();
        
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
        
                window.currentXAxisRange = [minTimestamp, maxTimestamp];
                window.xAxisMinDisplay.textContent = new Date(minTimestamp).toLocaleString();
                window.xAxisMaxDisplay.textContent = new Date(maxTimestamp).toLocaleString();
                rangesChangedByEvent = true;
                userModifiedRanges = true;
            }
        } else if (eventData['xaxis.autorange'] === true && window.currentXAxisRange !== null) {
            window.currentXAxisRange = null;
            window.xAxisMinDisplay.textContent = 'Auto';
            window.xAxisMaxDisplay.textContent = 'Auto';
            rangesChangedByEvent = true;
        }

        if (eventData['yaxis.range[0]'] || eventData['yaxis.range[1]']) {
            const yRange = gd.layout.yaxis.range;
            if (yRange && yRange.length === 2) {
                window.currentYAxisRange = [yRange[0], yRange[1]];
                window.yAxisMinDisplay.textContent = window.currentYAxisRange[0].toFixed(2);
                window.yAxisMaxDisplay.textContent = window.currentYAxisRange[1].toFixed(2);
                rangesChangedByEvent = true;
                userModifiedRanges = true;
            }
        } else if (eventData['yaxis.autorange'] === true && window.currentYAxisRange !== null) {
            window.currentYAxisRange = null;
            window.yAxisMinDisplay.textContent = 'Auto';
            window.yAxisMaxDisplay.textContent = 'Auto';
            rangesChangedByEvent = true;
        }

        if (rangesChangedByEvent) {
            console.log('[plotly_relayout] Ranges changed. User modified:', userModifiedRanges, 'New X-Range:', window.currentXAxisRange, 'New Y-Range:', window.currentYAxisRange);
            saveSettings(); // from settingsManager.js
            // Debounce chart update if ranges were changed by user panning/zooming,
            // or if autorange occurred (which means we need to reload based on dropdowns)
            clearTimeout(window.fetchDataDebounceTimer); // fetchDataDebounceTimer from state.js
            window.fetchDataDebounceTimer = setTimeout(() => {
                console.log('[plotly_relayout] Debounced chart update due to axis range change.');
                updateChart(); // updateChart from chartUpdater.js
            }, FETCH_DEBOUNCE_DELAY); // FETCH_DEBOUNCE_DELAY from config.js
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
            if (updatedShape.backendId) {
                console.log(`[plotly_shapeupdate] Detected update for shape ${updatedShape.backendId}, attempting to save.`);
                const saveSuccess = await sendShapeUpdateToServer(updatedShape, window.symbolSelect.value);
                if (!saveSuccess) {
                    loadDrawingsAndRedraw(window.symbolSelect.value);
                    return;
                }
                // Update active shape state if this is the one being edited
                if (!window.activeShapeForPotentialDeletion || window.activeShapeForPotentialDeletion.id !== updatedShape.backendId) {
                    window.activeShapeForPotentialDeletion = { id: updatedShape.backendId, index: shapeIndex, shape: updatedShape };
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
        if (removedShape && removedShape.backendId) {
            const symbol = window.symbolSelect.value;
            console.log(`[plotly_remove_shape] Attempting to delete shape ${removedShape.backendId} from backend.`);
            try {
                const response = await fetch(`/delete_drawing/${symbol}/${removedShape.backendId}`, { method: 'DELETE' });
                if (!response.ok) throw new Error(`Backend delete failed: ${response.status} ${await response.text()}`);
                console.log(`Drawing ${removedShape.backendId} deleted from backend via plotly_remove_shape.`);
                if (window.activeShapeForPotentialDeletion && window.activeShapeForPotentialDeletion.id === removedShape.backendId) {
                    window.activeShapeForPotentialDeletion = null;
                    updateSelectedShapeInfoPanel(null);
                }
                await updateShapeVisuals(); // Refresh visuals
            } catch (error) {
                console.error(`Error deleting drawing ${removedShape.backendId} via plotly_remove_shape:`, error);
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

// Initialize observer for main chart
observeShapeDAttributeChanges('chart'); // Use your actual chart div ID
