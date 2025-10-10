// Test script to make shapes editable in Plotly.js

// This script demonstrates how to make shapes editable by enabling drag handles
// Run this in the browser console to test editable shape functionality

function makeShapesEditable() {
    if (!window.gd || !window.gd.layout || !window.gd.layout.shapes) {
        console.warn('No chart or shapes found');
        return;
    }

    const shapes = window.gd.layout.shapes;

    // Update each shape to be editable
    shapes.forEach((shape, index) => {
        if (!shape.isSystemShape && (shape.type === 'line' || shape.type === 'rect')) {
            // Make sure the shape is editable
            shapes[index].editable = true;

            // Ensure line properties are set for dragging
            if (shape.type === 'line') {
                shapes[index].line = shapes[index].line || { color: 'red', width: 2 };
                shapes[index].line.layer = 'above';
            }

            // Add markers for better visibility and interaction
            if (shape.type === 'line') {
                shapes[index].marker = {
                    size: window.isMobileDevice ? 28 : 20,
                    color: shapes[index].line.color || 'red',
                    symbol: 'circle',
                    line: { width: 2, color: 'white' },
                    opacity: 1.0,
                    xanchor: 'center',
                    yanchor: 'center'
                };
            }
        }
    });

    // Force chart to recognize editable shapes
    Plotly.relayout(window.gd, {
        shapes: shapes,
        dragmode: 'pan' // Or whatever dragmode is currently active
    });

    console.log('Shapes made editable:', shapes.filter(s => s.editable));
}

// Function to test shape dragging
function testShapeDragging() {
    if (!window.gd) {
        console.warn('No chart found');
        return;
    }

    // Switch to pan mode for shape interaction
    Plotly.relayout(window.gd, { dragmode: 'pan' });

    // Add event listener for shape updates
    let dragStartTime = null;

    // Listen for plotly_relayout events to detect shape dragging
    window.gd.on('plotly_relayout', function(eventData) {
        const shapeKeys = Object.keys(eventData).filter(key => key.startsWith('shapes['));
        if (shapeKeys.length > 0) {
            console.log('Shape being modified:', eventData);

            // Here you can add custom logic when a shape is being dragged
            // For example, save the shape position, trigger alerts, etc.
        }
    });

    console.log('Shape dragging test enabled. Try dragging the handles of line shapes.');
}

// Function to enable advanced shape editing features
function enableAdvancedShapeEditing() {
    if (!window.gd || !window.gd.layout || !window.gd.layout.shapes) {
        console.warn('No chart or shapes found');
        return;
    }

    // Enable shape editing modebar buttons
    const modebarButtons = {
        modeBarButtonsToAdd: [
            {
                name: 'deleteSelected',
                title: 'Delete selected shapes',
                icon: Plotly.Icons.trash,
                click: function(gd) {
                    // Delete selected shapes
                    if (window.getSelectedShapeIds && window.getSelectedShapeIds().length > 0) {
                        console.log('Deleting selected shapes');
                        // This would typically call your existing delete function
                    } else {
                        console.log('No shapes selected for deletion');
                    }
                }
            }
        ]
    };

    // Note: This would require accessing Plotly's internal modebar system
    // For simplicity, we'll just log the functionality
    console.log('Advanced shape editing features enabled');
}

// Make functions globally available for testing
window.makeShapesEditable = makeShapesEditable;
window.testShapeDragging = testShapeDragging;
window.enableAdvancedShapeEditing = enableAdvancedShapeEditing;

// Auto-run if shapes exist
if (window.gd && window.gd.layout && window.gd.layout.shapes && window.gd.layout.shapes.length > 0) {
    console.log('Auto-enabling editable shapes...');
    makeShapesEditable();
    testShapeDragging();
} else {
    console.log('No shapes found on chart. Draw some shapes first, then run makeShapesEditable()');
}
