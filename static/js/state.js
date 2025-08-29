let liveWebSocket = null;
let currentSymbolForStream = '';
let currentXAxisRange = null;
let currentYAxisRange = null;
let activeIndicatorsState = [];
let fetchDataDebounceTimer = null;
let activeShapeForPotentialDeletion = null;
let hoveredShapeBackendId = null;
let aiSuggestionAbortController = null;
let currentStreamDeltaTime = 0; // Added for live stream update interval
let isDraggingShape = false;

window.currentDataStart = null; // Will be set in updateChart
window.currentDataEnd = null;   // Will be set in updateChart
window.isDraggingShape = false;