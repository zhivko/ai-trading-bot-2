function updateSelectedShapeInfoPanel(activeShape) {
    // Assumes selectedShapeInfoDiv is globally available or passed as an argument
    if (!window.selectedShapeInfoDiv) {
        return;
    }

    const selectedCount = window.getSelectedShapeCount();
    const selectedIds = window.getSelectedShapeIds();

    // Determine what to display based on selection and hover state
    const isHovering = activeShape && activeShape.id;
    const hasSelection = selectedCount > 0;


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
            infoHtml = `<p><strong>ID:</strong> ${activeShape.id}</p>`;
        }

        window.selectedShapeInfoDiv.innerHTML = infoHtml;
        window.activeShapeForPotentialDeletion = activeShape;

        // Show the "Delete line" and "Edit line" buttons when shapes are selected OR hovered
        if (window.deleteShapeBtn) {
            window.deleteShapeBtn.style.display = 'inline-block';
        } else {
        }
        if (window.editShapeBtn) {
            window.editShapeBtn.style.display = 'inline-block';
        } else {
        }
    } else {
        window.selectedShapeInfoDiv.innerHTML = '<p>No shape selected.</p>';

        // Hide the "Delete line" and "Edit line" buttons when no shape is selected
        if (window.deleteShapeBtn) {
            window.deleteShapeBtn.style.display = 'none';
        }
        if (window.editShapeBtn) {
            window.editShapeBtn.style.display = 'none';
        }
    }
}

async function updateShapeVisuals() {
    if (!window.gd || !window.gd.layout) {
        return;
    }
    const currentShapes = window.gd.layout.shapes || [];

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


            newShape.editable = isSelected;
            if (newShape.line) {
                // Priority: Selected > Hovered > Default
                if (isSelected) {
                    // Use a different shade for the last selected shape in multi-selection
                    if ((window.getSelectedShapeCount && window.getSelectedShapeCount() > 1) && isLastSelected) {
                        newShape.line.color = '#00FF00'; // Bright green for last selected
                        newShape.line.width = 3; // Thicker line for last selected
                    } else {
                        newShape.line.color = window.SELECTED_DRAWING_COLOR;
                        newShape.line.width = 2.5; // Slightly thicker for selected
                    }
                } else if (isHovered) {
                    newShape.line.color = window.HOVER_DRAWING_COLOR;
                    newShape.line.width = 2; // Normal width for hover
                } else {
                    newShape.line.color = window.DEFAULT_DRAWING_COLOR;
                    newShape.line.width = 2; // Normal width for default
                }
                // Removed problematic onmousedown handler that was interfering with drag functionality
                // Shape properties functionality has been completely removed
            }
        }
        return newShape;
    });
    try {
        await Plotly.relayout(window.gd, { 'shapes': newShapes });
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

