async function debounce(func, delayMs) {
    let timeoutId;
    return function(...args) {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(async () => {
            await func.apply(this, args);
        }, delayMs);
    };
}

function getAxisLayoutKey(axisRef, axisTypePrefix) { // axisTypePrefix is 'xaxis' or 'yaxis'
    if (!axisRef) { // Undefined, null, or empty string
        return axisTypePrefix; // Default to 'xaxis' or 'yaxis'
    }
    if (axisRef === axisTypePrefix[0]) { // 'x' or 'y'
        return axisTypePrefix; // 'xaxis' or 'yaxis'
    }
    // Handles 'x2', 'y3', etc. -> 'xaxis2', 'yaxis3'
    if (axisRef.startsWith(axisTypePrefix[0]) && axisRef.length > 1 && !axisRef.startsWith(axisTypePrefix)) {
        return axisTypePrefix + axisRef.substring(1);
    }
    return axisRef;
}

function determineSubplotNameForShape(shape) {
    const currentSymbol = window.symbolSelect.value;
    if (!shape || !shape.yref) {
        return currentSymbol; // Default to main chart if no yref
    }
    const yrefFromShape = shape.yref; // e.g., 'y', 'y2', 'y3' when using layout.grid

    // Main chart is on 'y' (Plotly might also use 'y1' for the first axis in a grid context)
    if (yrefFromShape === 'y' || yrefFromShape === 'y1') {
        return currentSymbol;
    }

    // Indicators will have yAxisRef like 'y2', 'y3' in activeIndicatorsState
    // (matching the yrefFromShape directly)
    const indicator = window.activeIndicatorsState && window.activeIndicatorsState.find(ind => ind.yAxisRef === yrefFromShape);
    if (indicator) {
        return `${currentSymbol}-${indicator.id}`;
    }
    // Fallback
    return currentSymbol;
}
function distSq(p1, p2) {
    return (p1.x - p2.x)**2 + (p1.y - p2.y)**2;
}

function distToSegmentSquared(p, v, w) {
    const l2 = distSq(v, w);
    if (l2 === 0) return distSq(p, v);
    let t = ((p.x - v.x) * (w.x - v.x) + (p.y - v.y) * (w.y - v.y)) / l2;
    t = Math.max(0, Math.min(1, t));
    const projection = { x: v.x + t * (w.x - v.x), y: v.y + t * (w.y - v.y) };
    return distSq(p, projection);
}

function getTimeframeSecondsJS(resolution) {
    const multipliers = {"1m": 60, "5m": 5 * 60, "1h": 60 * 60, "1d": 24 * 60 * 60, "1w": 7 * 24 * 60 * 60 };
    return multipliers[resolution];
}

// Promise-based delay function to replace setTimeout
function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// Make delay globally available
window.delay = delay;