function updateSelectedShapeInfoPanel(activeShape) {
    // Assumes selectedShapeInfoDiv is globally available or passed as an argument
    if (!window.selectedShapeInfoDiv) return;
    if (activeShape && activeShape.id && typeof activeShape.index !== 'undefined') {
        window.selectedShapeInfoDiv.innerHTML = `
            <p><strong>ID:</strong> ${activeShape.id}</p>
        `;
        window.activeShapeForPotentialDeletion = activeShape;
        
        // Show the "Delete line" and "Edit line" buttons when a shape is selected
        if (window.deleteShapeBtn) {
            window.deleteShapeBtn.style.display = 'inline-block';
        }
        if (window.editShapeBtn) {
            window.editShapeBtn.style.display = 'inline-block';
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
    if (!window.gd || !window.gd.layout) return;
    const currentShapes = window.gd.layout.shapes || [];
    const newShapes = currentShapes.map(s => {
        const newShape = { ...s };
        if (s.line) {
            newShape.line = { ...s.line };
        } else if (s.type === 'line') {
            newShape.line = {};
        }

        // Ensure markers are present on line shapes
        if (s.type === 'line' && s.backendId && !s.isSystemShape) {
            // Add markers for user-drawn lines if not already present
            if (!newShape.marker) {
                newShape.marker = {
                    size: isMobileDevice() ? 24 : 16,
                    color: DEFAULT_DRAWING_COLOR,
                    symbol: 'diamond',
                    line: { width: 3, color: 'white' },
                    opacity: 0.95
                };
            } else {
                // Ensure marker properties are complete
                newShape.marker = { ...newShape.marker };
                if (newShape.marker.size === undefined) newShape.marker.size = isMobileDevice() ? 24 : 16;
                if (newShape.marker.color === undefined) newShape.marker.color = DEFAULT_DRAWING_COLOR;
                if (newShape.marker.symbol === undefined) newShape.marker.symbol = 'diamond';
                if (!newShape.marker.line) newShape.marker.line = { width: 3, color: 'white' };
                if (newShape.marker.opacity === undefined) newShape.marker.opacity = 0.95;
            }
        }

        if (s.backendId) {
            const isSelected = window.activeShapeForPotentialDeletion && s.backendId === window.activeShapeForPotentialDeletion.id;
            const isHovered = s.backendId === window.hoveredShapeBackendId;

            newShape.editable = isSelected;
            if (newShape.line) {
                // Priority: Selected > Hovered > Default
                if (isSelected) {
                    newShape.line.color = SELECTED_DRAWING_COLOR;
                } else if (isHovered) {
                    newShape.line.color = HOVER_DRAWING_COLOR;
                } else {
                    newShape.line.color = DEFAULT_DRAWING_COLOR;
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
    }
}
// debouncedUpdateShapeVisuals will be defined in main.js after this function is loaded

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

