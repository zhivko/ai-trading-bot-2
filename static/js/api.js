async function getDrawings(symbol) {
    try {
        const response = await fetch(`/get_drawings/${symbol}`);
        if (!response.ok) {
            const errorBody = await response.text().catch(() => "Could not read error body");
            throw new Error(`Failed to fetch drawings: ${response.status} - ${errorBody}`);
        }
        const result = await response.json();
        if (result.status === 'success' && Array.isArray(result.drawings)) {
            return result.drawings;
        } else {
            console.warn("Unexpected response format for get_drawings:", result);
            return [];
        }
    } catch (error) {
        console.error(`Error fetching drawings for ${symbol}:`, error);
        throw error;
    }
}

window.getDrawings = getDrawings; // Make getDrawings globally accessible

async function sendShapeUpdateToServer(shapeToUpdate, symbol) {
    if (!shapeToUpdate || !shapeToUpdate.backendId || !symbol) {
        console.warn("sendShapeUpdateToServer: Missing shape, backendId, or symbol.");
        return false;
    }
    const resolution = window.resolutionSelect.value;
    const start_time_ms = (shapeToUpdate.x0 instanceof Date) ? shapeToUpdate.x0.getTime() : new Date(shapeToUpdate.x0).getTime();
    const end_time_ms = (shapeToUpdate.x1 instanceof Date) ? shapeToUpdate.x1.getTime() : new Date(shapeToUpdate.x1).getTime();
    const drawingData = {
        symbol: symbol,
        type: shapeToUpdate.type,
        start_time: Math.floor(start_time_ms / 1000),
        end_time: Math.floor(end_time_ms / 1000),
        start_price: parseFloat(shapeToUpdate.y0),
        end_price: parseFloat(shapeToUpdate.y1),
        subplot_name: determineSubplotNameForShape(shapeToUpdate), // Assumes determineSubplotNameForShape is global
        resolution: resolution
    };
    try {
        const response = await fetch(`/update_drawing/${symbol}/${shapeToUpdate.backendId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(drawingData)
        });
        if (!response.ok) throw new Error(`Failed to update drawing ${shapeToUpdate.backendId} on server: ${response.status} ${await response.text()}`);
        console.log(`Drawing ${shapeToUpdate.backendId} updated successfully on server via sendShapeUpdateToServer.`);
        return true;
    } catch (error) {
        console.error(`Error in sendShapeUpdateToServer for drawing ${shapeToUpdate.backendId}:`, error);
        alert(`Failed to update drawing on server: ${error.message}`);
        return false;
    }
}

function getPlotlyRefsFromSubplotName(subplotName) {
    const currentSymbol = window.symbolSelect.value; // Assumes symbolSelect is global
    const hasActiveIndicators = window.activeIndicatorsState && window.activeIndicatorsState.length > 0;

    if (!subplotName || subplotName === currentSymbol) {
        // This is for a drawing on the main chart.
        // Price chart is on yaxis1 if indicators, else on 'y' (which becomes layout.yaxis)
        // Corresponding x-axis is xaxis1 if indicators, else 'xaxis'
        const yRefToUse = hasActiveIndicators ? 'yaxis1' : 'y';
        const xRefToUse = hasActiveIndicators ? 'xaxis1' : 'xaxis';
        return { xref: xRefToUse, yref: yRefToUse };
    }

    // Handle the temporary name used during loading if subplot_name was just the symbol
    if (subplotName === `${currentSymbol}-main`) { // This was a temporary name
        const yRefToUse = hasActiveIndicators ? 'yaxis1' : 'y';
        const xRefToUse = hasActiveIndicators ? 'xaxis1' : 'xaxis';
        return { xref: xRefToUse, yref: yRefToUse };
    }

    const parts = subplotName.split('-');
    if (parts.length >= 2) {
        const indicatorId = parts.slice(1).join('-');
        const indicator = window.activeIndicatorsState && window.activeIndicatorsState.find(ind => ind.id === indicatorId);
        console.log(`[DEBUG getPlotlyRefsFromSubplotName] For indicatorId '${indicatorId}', found in activeIndicatorsState:`, indicator ? JSON.parse(JSON.stringify(indicator)) : 'NOT FOUND');
        console.log(`[DEBUG getPlotlyRefsFromSubplotName] Current window.activeIndicatorsState:`, JSON.parse(JSON.stringify(window.activeIndicatorsState)));

        if (indicator && indicator.xAxisRef && indicator.yAxisRef) {
            return { xref: indicator.xAxisRef, yref: indicator.yAxisRef };
        } else {
             //console.warn(`[getPlotlyRefsFromSubplotName] Indicator '${indicatorId}' (from subplotName '${subplotName}') is not currently active or its refs are missing. Active state:`, JSON.parse(JSON.stringify(window.activeIndicatorsState)));
             return null; // Explicitly return null if indicator not active for this drawing
        }
    }
    // Fallback if subplotName doesn't match an indicator or if parts.length < 2
    // This should only be hit if subplotName is malformed or for a context not anticipated.
    // For the main chart without indicators, actualMainChartYAxisRef would be 'y', handled by the first 'if'.
    console.warn(`[getPlotlyRefsFromSubplotName] Fallback for subplotName '${subplotName}'. This might indicate an issue. Defaulting to x/y.`);
    return { xref: 'x', yref: 'y' }; 
}

async function getOrderHistory(symbol) {
    try {
        const response = await fetch(`/get_order_history/${symbol}`);
        if (!response.ok) {
            const errorBody = await response.text().catch(() => "Could not read error body");
            throw new Error(`Failed to fetch open trades: ${response.status} - ${errorBody}`);
        }
        const result = await response.json();
        if (result.status === 'success' && Array.isArray(result["order history"])) {
            return result["order history"];
        } else {
            console.warn("Unexpected response format for get_order_history:", result);
            return [];
        }
    } catch (error) {
        console.error(`Error fetching open trades for ${symbol}:`, error);
        throw error;
    }
}
