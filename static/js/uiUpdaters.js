function updateSelectedShapeInfoPanel(activeShape) {
    console.log('[DEBUG] updateSelectedShapeInfoPanel called with activeShape:', activeShape);
    // Assumes selectedShapeInfoDiv is globally available or passed as an argument
    if (!window.selectedShapeInfoDiv) {
        console.log('[DEBUG] updateSelectedShapeInfoPanel - selectedShapeInfoDiv not found');
        return;
    }

    const selectedCount = window.getSelectedShapeCount();
    const selectedIds = window.getSelectedShapeIds();
    console.log('[DEBUG] updateSelectedShapeInfoPanel - selectedCount:', selectedCount, 'selectedIds:', selectedIds);
    console.log('[DEBUG] updateSelectedShapeInfoPanel - activeShape exists:', !!activeShape, 'activeShape.id:', activeShape?.id);
    console.log('[DEBUG] updateSelectedShapeInfoPanel - hoveredShapeBackendId:', window.hoveredShapeBackendId);

    // Determine what to display based on selection and hover state
    const isHovering = activeShape && activeShape.id;
    const hasSelection = selectedCount > 0;

    console.log('[DEBUG] updateSelectedShapeInfoPanel - Logic check: isHovering:', isHovering, 'hasSelection:', hasSelection, 'selectedCount:', selectedCount);

    if (hasSelection || isHovering) {
        let infoHtml = '';

        if (hasSelection) {
            infoHtml += `<p><strong>${selectedCount} shape${selectedCount > 1 ? 's' : ''} selected</strong></p>`;

            if (selectedCount === 1 && activeShape && activeShape.id) {
                infoHtml += `<p><strong>ID:</strong> ${activeShape.id}</p>`;
            } else if (selectedCount > 1) {
                infoHtml += '<p><strong>IDs:</strong></p><ul>';
                selectedIds.forEach(id => {
                    const isLastSelected = id === window.lastSelectedShapeId;
                    infoHtml += `<li${isLastSelected ? ' style="font-weight: bold; color: #00FF00;"' : ''}>${id}${isLastSelected ? ' (last selected)' : ''}</li>`;
                });
                infoHtml += '</ul>';
            }
        } else if (isHovering) {
            // Handle hovered shape (no shapes selected but hovering over one)
            console.log('[DEBUG] updateSelectedShapeInfoPanel - handling hovered shape:', activeShape.id);
            infoHtml = `<p><strong>ID:</strong> ${activeShape.id}</p>`;
        }

        window.selectedShapeInfoDiv.innerHTML = infoHtml;
        window.activeShapeForPotentialDeletion = activeShape;

        // Show the "Delete line" and "Edit line" buttons when shapes are selected OR hovered
        console.log('[DEBUG] updateSelectedShapeInfoPanel - SHOWING buttons (selected:', hasSelection, 'hovered:', isHovering, ')');
        if (window.deleteShapeBtn) {
            window.deleteShapeBtn.style.display = 'inline-block';
            console.log('[DEBUG] updateSelectedShapeInfoPanel - deleteShapeBtn set to inline-block');
        } else {
            console.log('[DEBUG] updateSelectedShapeInfoPanel - deleteShapeBtn not found');
        }
        if (window.editShapeBtn) {
            window.editShapeBtn.style.display = 'inline-block';
            console.log('[DEBUG] updateSelectedShapeInfoPanel - editShapeBtn set to inline-block');
        } else {
            console.log('[DEBUG] updateSelectedShapeInfoPanel - editShapeBtn not found');
        }
    } else {
        console.log('[DEBUG] updateSelectedShapeInfoPanel - no shapes selected or hovered');
        window.selectedShapeInfoDiv.innerHTML = '<p>No shape selected.</p>';

        // Hide the "Delete line" and "Edit line" buttons when no shape is selected
        console.log('[DEBUG] updateSelectedShapeInfoPanel - HIDING buttons for no selection');
        if (window.deleteShapeBtn) {
            window.deleteShapeBtn.style.display = 'none';
        }
        if (window.editShapeBtn) {
            window.editShapeBtn.style.display = 'none';
        }
    }
}

async function updateShapeVisuals() {
    console.log('[DEBUG] updateShapeVisuals called at', new Date().toISOString(), '- HOVER COLORING SHOULD HAPPEN HERE');
    console.log('[DEBUG] updateShapeVisuals - window.gd exists:', !!window.gd);
    console.log('[DEBUG] updateShapeVisuals - window.gd.layout exists:', !!(window.gd && window.gd.layout));
    console.log('[DEBUG] updateShapeVisuals - window.hoveredShapeBackendId:', window.hoveredShapeBackendId);
    console.log('[DEBUG] updateShapeVisuals - Current selection state:', {
        selectedIds: window.getSelectedShapeIds ? window.getSelectedShapeIds() : 'N/A',
        selectedCount: window.getSelectedShapeCount ? window.getSelectedShapeCount() : 'N/A',
        lastSelected: window.lastSelectedShapeId
    });
    if (!window.gd || !window.gd.layout) {
        console.log('[DEBUG] updateShapeVisuals early return - window.gd or layout missing');
        return;
    }
    const currentShapes = window.gd.layout.shapes || [];
    console.log('[DEBUG] updateShapeVisuals - current shapes count:', currentShapes.length);

    const newShapes = currentShapes.map(s => {
        const newShape = { ...s };
        if (s.line) {
            newShape.line = { ...s.line };
        } else if (s.type === 'line') {
            newShape.line = {};
        }

        // Ensure markers are present on line shapes
        if (s.type === 'line' && s.id && !s.isSystemShape) {
            // Add markers for user-drawn lines if not already present
            if (!newShape.marker) {
                newShape.marker = {
                    size: isMobileDevice() ? 24 : 16,
                    color: window.DEFAULT_DRAWING_COLOR,
                    symbol: 'diamond',
                    line: { width: 3, color: 'white' },
                    opacity: 0.95
                };
            } else {
                // Ensure marker properties are complete
                newShape.marker = { ...newShape.marker };
                if (newShape.marker.size === undefined) newShape.marker.size = isMobileDevice() ? 24 : 16;
                if (newShape.marker.color === undefined) newShape.marker.color = window.DEFAULT_DRAWING_COLOR;
                if (newShape.marker.symbol === undefined) newShape.marker.symbol = 'diamond';
                if (!newShape.marker.line) newShape.marker.line = { width: 3, color: 'white' };
                if (newShape.marker.opacity === undefined) newShape.marker.opacity = 0.95;
            }
        }

        if (s.id) {
            const isSelected = window.isShapeSelected ? window.isShapeSelected(s.id) : false;
            const isHovered = s.id === window.hoveredShapeBackendId;
            const isLastSelected = s.id === window.lastSelectedShapeId;

            console.log(`[DEBUG] updateShapeVisuals - Processing shape ${s.id}: selected=${isSelected}, hovered=${isHovered}, lastSelected=${isLastSelected}`);

            newShape.editable = isSelected;
            if (newShape.line) {
                // Priority: Selected > Hovered > Default
                if (isSelected) {
                    // Use a different shade for the last selected shape in multi-selection
                    if ((window.getSelectedShapeCount && window.getSelectedShapeCount() > 1) && isLastSelected) {
                        newShape.line.color = '#00FF00'; // Bright green for last selected
                        newShape.line.width = 3; // Thicker line for last selected
                        console.log(`[DEBUG] updateShapeVisuals - Setting shape ${s.id} to BRIGHT GREEN (last selected)`);
                    } else {
                        newShape.line.color = window.SELECTED_DRAWING_COLOR;
                        newShape.line.width = 2.5; // Slightly thicker for selected
                        console.log(`[DEBUG] updateShapeVisuals - Setting shape ${s.id} to SELECTED color (${window.SELECTED_DRAWING_COLOR})`);
                    }
                } else if (isHovered) {
                    console.log(`[DEBUG] updateShapeVisuals - Setting shape ${s.id} to HOVER color (${window.HOVER_DRAWING_COLOR})`);
                    newShape.line.color = window.HOVER_DRAWING_COLOR;
                    newShape.line.width = 2; // Normal width for hover
                } else {
                    newShape.line.color = window.DEFAULT_DRAWING_COLOR;
                    newShape.line.width = 2; // Normal width for default
                    console.log(`[DEBUG] updateShapeVisuals - Setting shape ${s.id} to DEFAULT color (${window.DEFAULT_DRAWING_COLOR})`);
                }
                // Removed problematic onmousedown handler that was interfering with drag functionality
                // Shape properties functionality has been completely removed
            }
        }
        return newShape;
    });
    try {
        console.log('[DEBUG] updateShapeVisuals - calling Plotly.relayout with', newShapes.length, 'shapes at', new Date().toISOString());
        console.log('[DEBUG] updateShapeVisuals - newShapes sample:', newShapes.slice(0, 2));
        await Plotly.relayout(window.gd, { 'shapes': newShapes });
        console.log('[DEBUG] updateShapeVisuals - Plotly.relayout completed successfully at', new Date().toISOString());
    } catch (error) {
        console.error("Error during relayout for shape editability:", error);
        console.error("Error details:", error.message, error.stack);
    }
}

// Define debounced version of updateShapeVisuals here so it's available when chartInteractions.js loads
// This needs to be defined after updateShapeVisuals function
if (typeof VISUAL_UPDATE_DEBOUNCE_DELAY === 'undefined') {
    window.VISUAL_UPDATE_DEBOUNCE_DELAY = 30; // Default value if not defined yet
}
window.debouncedUpdateShapeVisuals = debounce(updateShapeVisuals, VISUAL_UPDATE_DEBOUNCE_DELAY);
window.updateShapeVisuals = updateShapeVisuals; // Export updateShapeVisuals to global scope
console.log('[DEBUG] debouncedUpdateShapeVisuals and updateShapeVisuals defined and available globally');

function logEventToPanel(message, type = 'INFO') {
    if (!window.eventOutput) {
        console.warn("logEventToPanel: window.eventOutput element not found.");
        return;
    }

    const timestamp = new Date().toLocaleTimeString();
    const typePrefix = type.toUpperCase();
    // Ensure message is a string, in case other types are passed
    const messageString = (typeof message === 'string' || message instanceof String) ? message : JSON.stringify(message);
    const formattedMessage = `[${timestamp} ${typePrefix}] ${messageString}`;

    let currentLog = window.eventOutput.value;
    let lines = currentLog.split('\n');
    lines.unshift(formattedMessage); // Prepend new message

    if (lines.length > 100) {
        lines = lines.slice(0, 100); // Keep the latest 100 lines
    }

    window.eventOutput.value = lines.join('\n');
    window.eventOutput.scrollTop = 0; // Scroll to top to see the latest (prepended) message
}

