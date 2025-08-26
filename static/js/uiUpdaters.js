function updateSelectedShapeInfoPanel(activeShape) {
    // Assumes selectedShapeInfoDiv is globally available or passed as an argument
    if (!window.selectedShapeInfoDiv) return;
    if (activeShape && activeShape.id && typeof activeShape.index !== 'undefined') {
        window.selectedShapeInfoDiv.innerHTML = `
            <p><strong>ID:</strong> ${activeShape.id}<button onclick="openShapePropertiesDialog('${activeShape.id}')">Edit Properties</button></p>
        `;
        activeShapeForPotentialDeletion = activeShape;
    } else {
        window.selectedShapeInfoDiv.innerHTML = '<p>No shape selected.</p>';
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

        if (s.backendId) {
            const isSelected = activeShapeForPotentialDeletion && s.backendId === activeShapeForPotentialDeletion.id;
            const isHovered = s.backendId === hoveredShapeBackendId;

            newShape.editable = isSelected;
            if (newShape.line) {
                newShape.line.color = isHovered ? HOVER_DRAWING_COLOR : DEFAULT_DRAWING_COLOR;
                //if (isHovered) {
                    newShape.onmousedown = () => openShapePropertiesDialog(s.backendId);
                //}
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

let currentShapeId = null; // To store the ID of the shape currently being edited

async function openShapePropertiesDialog(shapeId) {
    currentShapeId = shapeId;
    console.log("Opening dialog for shape ID:", shapeId);
    const dialog = document.getElementById('shape-properties-dialog');
    
    if (dialog) {
        dialog.style.display = 'block';
        // Initialize dialog with shape properties from Redis
        try {
            const symbolSelect = document.getElementById('symbol-select');
            const symbol = symbolSelect ? symbolSelect.value : 'default_symbol';
            const response = await fetch(`/get_shape_properties/${symbol}/${currentShapeId}`);
            if (!response.ok) throw new Error("Failed to fetch shape properties");
            const respJson = await response.json();
            const props = respJson.properties;

            
            document.getElementById('buy-on-cross').checked = props.buyOnCross || false;
            document.getElementById('sell-on-cross').checked = props.sellOnCross || false;
            document.getElementById('send-email-on-cross').checked = props.sendEmailOnCross || false;
            document.getElementById('amount').value = props.amount || '';

            
        } catch (error) {
            console.error("Error fetching shape properties:", error);
            alert("Failed to load shape properties. Please ensure a symbol is selected and try again.");
            
            // Fallback to local state if available
            if (window.activeShapeForPotentialDeletion && window.activeShapeForPotentialDeletion.id === shapeId) {
                const props = window.activeShapeForPotentialDeletion.properties || {};
                document.getElementById('buy-on-cross').checked = props.buyOnCross || false;
                document.getElementById('sell-on-cross').checked = props.sellOnCross || false;
                document.getElementById('send-email-on-cross').checked = props.sendEmailOnCross || false;
                document.getElementById('amount').value = props.amount || '';
            }
        }
        // Fallback to local state if available
        if (window.activeShapeForPotentialDeletion && window.activeShapeForPotentialDeletion.id === shapeId) {
            const props = window.activeShapeForPotentialDeletion.properties || {};
            document.getElementById('buy-on-cross').checked = props.buyOnCross || false;
            document.getElementById('sell-on-cross').checked = props.sellOnCross || false;
            document.getElementById('send-email-on-cross').checked = props.sendEmailOnCross || false;
            document.getElementById('amount').value = props.amount || '';
        }
    }
        // Fallback to local state if available
        if (window.activeShapeForPotentialDeletion && window.activeShapeForPotentialDeletion.id === shapeId) {
            const props = window.activeShapeForPotentialDeletion.properties || {};
            document.getElementById('buy-on-cross').checked = props.buyOnCross || false;
            document.getElementById('sell-on-cross').checked = props.sellOnCross || false;
            document.getElementById('send-email-on-cross').checked = props.sendEmailOnCross || false;
            document.getElementById('amount').value = props.amount || '';
        }
    }


function closeShapePropertiesDialog() {
    const dialog = document.getElementById('shape-properties-dialog');
    if (dialog) dialog.style.display = 'none';
}

async function saveShapeProperties() {
    if (!currentShapeId) {
        console.error("No shape ID selected for saving properties.");
        return;
    }

    // Sync with dropdown selection
    const symbolSelect = document.getElementById('symbol-select');
    if (!symbolSelect || !symbolSelect.value) {
        console.error("No symbol selected - please select a symbol from the dropdown first.");
        alert("Please select a symbol from the dropdown first");
        return;
    }
    const symbol = symbolSelect.value;

    const properties = {
        buyOnCross: document.getElementById('buy-on-cross').checked,
        sellOnCross: document.getElementById('sell-on-cross').checked,
        sendEmailOnCross: document.getElementById('send-email-on-cross').checked,
        amount: parseFloat(document.getElementById('amount').value) || 0
    };

    try {
        // Validate symbol before making request
        if (!symbol) {
            throw new Error("Symbol is required but not set in application state");
        }
        const response = await fetch(`/save_shape_properties/${symbol}/${currentShapeId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(properties),
        });

        const result = await response.json();
        if (response.ok) {
            console.log("Shape properties saved successfully:", result);
            logEventToPanel(`Properties for shape ${currentShapeId} saved.`, 'SUCCESS');
            closeShapePropertiesDialog();
            // Update the active shape properties in memory
            if (window.activeShapeForPotentialDeletion && window.activeShapeForPotentialDeletion.id === currentShapeId) {
                window.activeShapeForPotentialDeletion.properties = properties;
            }
        } else {
            console.error("Failed to save shape properties:", result);
            logEventToPanel(`Failed to save properties for shape ${currentShapeId}: ${result.message}`, 'ERROR');
            alert(`Error saving properties: ${result.message}`);
        }
    } catch (error) {
        console.error("Network error while saving shape properties:", error);
        logEventToPanel(`Network error saving properties for shape ${currentShapeId}: ${error.message}`, 'ERROR');
        alert("Network error while saving properties. See console for details.");
    }
}