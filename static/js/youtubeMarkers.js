/**
 * YouTube Markers Integration for Trading Charts
 * Adds YouTube video markers with hover tooltips to Plotly charts
 * NOW WEBSOCKET-BASED: No longer loads from HTTP endpoints
 */

class YouTubeMarkersManager {
    constructor() {
        this.markers = [];
        this.updateInterval = 30 * 60 * 1000; // 30 minutes (reduced frequency)
        this.currentSymbol = null;
        this.isEnabled = true;
        this.periodicUpdatesEnabled = false; // Disabled by default - now using websocket
        this.websocketBased = true; // Use websocket instead of HTTP
    }

    /**
     * Initialize the YouTube markers for a specific symbol
     * Now uses websocket instead of HTTP loading
     */
    async initializeForSymbol(symbol) {
        this.currentSymbol = symbol;
        console.log('🎥 YouTube Markers: Initializing for', symbol, '(websocket-based)');

        // WebSocket-based: markers will come from websocket handlers
        // No need to load from HTTP endpoint

        // Set up periodic updates (disabled by default)
        this.startPeriodicUpdates();

        // Listen for chart updates to refresh markers
        this.setupChartUpdateListener();
    }

    /**
     * Load YouTube markers from the API
     */
    async loadMarkers() {
        if (!this.currentSymbol || !this.isEnabled) return;

        try {
            const response = await fetch(`/youtube/youtube_markers/${this.currentSymbol}`);
            const data = await response.json();

            if (data.status === 'success' && data.markers) {
                this.markers = data.markers;
                console.log('🎥 YouTube Markers: Loaded', data.count, 'markers');

                // Add markers to chart
                this.addMarkersToChart();
            } else {
                console.log('🎥 YouTube Markers: No markers available');
                this.markers = [];
            }
        } catch (error) {
            console.error('🎥 YouTube Markers: Error loading markers:', error);
        }
    }

    /**
     * Add markers to the Plotly chart
     */
    addMarkersToChart() {
        if (!window.gd || !this.markers || !this.markers.x || this.markers.x.length === 0) {
            console.log('🎥 YouTube Markers: No markers to add or chart not ready');
            return;
        }

        try {
            // Remove existing YouTube markers
            this.removeExistingMarkers();

            // Debug marker data
            console.log('🎥 YouTube Markers: Adding markers with data:', {
                count: this.markers.x ? this.markers.x.length : 0,
                x_range: this.markers.x ? [
                    new Date(Math.min(...this.markers.x)).toLocaleString(),
                    new Date(Math.max(...this.markers.x)).toLocaleString()
                ] : 'none',
                y_range: this.markers.y ? [Math.min(...this.markers.y), Math.max(...this.markers.y)] : 'none',
                first_marker: this.markers.x && this.markers.x.length > 0 ? {
                    timestamp: new Date(this.markers.x[0]).toLocaleString(),
                    price: this.markers.y ? this.markers.y[0] : 'undefined',
                    title: this.markers.text ? this.markers.text[0] : 'no title'
                } : 'none'
            });

            // Prepare marker data
            const markerTrace = {
                x: this.markers.x,
                y: this.markers.y,
                text: this.markers.text,
                mode: 'markers',
                type: 'scatter',
                name: 'YouTube Videos',
                marker: {
                    symbol: 'diamond',
                    size: 12,
                    color: 'red',
                    line: {
                        color: 'white',
                        width: 2
                    }
                },
                hoverinfo: 'skip',
                customdata: this.markers.customdata,
                hovertext: this.markers.hovertext,
                video_ids: this.markers.video_ids,
                transcripts: this.markers.transcripts,
                showlegend: true,
                hoverlabel: {
                    bgcolor: 'white',
                    bordercolor: 'red',
                    font: { color: 'black', size: 12 },
                    align: 'left'
                }
            };

            // Add the trace to the chart
            Plotly.addTraces(window.gd, markerTrace);

            // Set up click event handler for markers
            this.setupClickHandler();

            console.log('🎥 YouTube Markers: Added to chart successfully');
            console.log('🎥 YouTube Markers: Markers should appear as red diamonds on the price chart');

        } catch (error) {
            console.error('🎥 YouTube Markers: Error adding to chart:', error);
        }
    }

    /**
     * Remove existing YouTube markers from the chart
     */
    removeExistingMarkers() {
        if (!window.gd || !window.gd.data) return;

        try {
            // Find and remove YouTube marker traces
            const tracesToRemove = [];
            window.gd.data.forEach((trace, index) => {
                if (trace.name === 'YouTube Videos') {
                    tracesToRemove.push(index);
                }
            });

            // Remove traces in reverse order to maintain indices
            tracesToRemove.reverse().forEach(index => {
                Plotly.deleteTraces(window.gd, index);
            });

            if (tracesToRemove.length > 0) {
                console.log('🎥 YouTube Markers: Removed', tracesToRemove.length, 'existing markers');
            }

        } catch (error) {
            console.error('🎥 YouTube Markers: Error removing existing markers:', error);
        }
    }

    /**
     * Start periodic updates of markers
     */
    startPeriodicUpdates() {
        // Clear any existing interval
        if (this.updateTimer) {
            clearInterval(this.updateTimer);
        }

        // Only start periodic updates if enabled
        if (!this.periodicUpdatesEnabled) {
            console.log('🎥 YouTube Markers: Periodic updates disabled (markers are static)');
            return;
        }

        // Set up new interval
        this.updateTimer = setInterval(async () => {
            if (this.isEnabled && this.currentSymbol) {
                console.log('🎥 YouTube Markers: Periodic update...');
                await this.loadMarkers();
            }
        }, this.updateInterval);

        console.log(`🎥 YouTube Markers: Periodic updates started (every ${this.updateInterval / 1000 / 60} minutes)`);
    }

    /**
     * Stop periodic updates
     */
    stopPeriodicUpdates() {
        if (this.updateTimer) {
            clearInterval(this.updateTimer);
            this.updateTimer = null;
            console.log('🎥 YouTube Markers: Periodic updates stopped');
        }
    }

    /**
     * Set up listener for chart updates
     */
    setupChartUpdateListener() {
        // Listen for plotly_relayout events (when user pans/zooms)
        window.gd.on('plotly_relayout', (eventData) => {
            // Only refresh markers for user-initiated chart updates (panning/zooming)
            // Skip automatic updates like live price updates
            const isUserChartUpdate = this.isUserChartUpdate(eventData);

            if (isUserChartUpdate && this.isEnabled) {
                console.log('🎥 YouTube Markers: User chart update detected, refreshing markers...');
                setTimeout(() => {
                    if (this.isEnabled) {
                        this.addMarkersToChart();
                    }
                }, 500); // Small delay to ensure chart is updated
            } else {
                console.log('🎥 YouTube Markers: Skipping marker refresh for automatic update');
            }
        });
    }

    /**
     * Determine if a chart update was user-initiated (panning/zooming) vs automatic
     */
    isUserChartUpdate(eventData) {
        if (!eventData) return false;

        // Check for axis range changes (user panning/zooming)
        const hasXRangeChange = eventData['xaxis.range[0]'] !== undefined || eventData['xaxis.range[1]'] !== undefined;
        const hasYRangeChange = eventData['yaxis.range[0]'] !== undefined || eventData['yaxis.range[1]'] !== undefined;
        const hasAutorange = eventData['xaxis.autorange'] === true || eventData['yaxis.autorange'] === true;

        // Check for dragmode changes (user switching modes)
        const isDragModeChange = eventData.dragmode !== undefined;

        // Check if this is a significant axis range change (not just minor live price updates)
        let isSignificantRangeChange = false;
        if (hasXRangeChange || hasYRangeChange) {
            // Get current axis ranges to compare
            const currentXRange = window.gd?.layout?.xaxis?.range;
            const currentYRange = window.gd?.layout?.yaxis?.range;

            if (hasXRangeChange && currentXRange && currentXRange.length === 2) {
                // Handle different types of data in currentXRange (Date objects, timestamps, or strings)
                let currentX0, currentX1;

                if (currentXRange[0] instanceof Date) {
                    currentX0 = currentXRange[0].getTime();
                    currentX1 = currentXRange[1].getTime();
                } else if (typeof currentXRange[0] === 'number') {
                    // Already a timestamp
                    currentX0 = currentXRange[0];
                    currentX1 = currentXRange[1];
                } else if (typeof currentXRange[0] === 'string') {
                    // String timestamp
                    currentX0 = new Date(currentXRange[0]).getTime();
                    currentX1 = new Date(currentXRange[1]).getTime();
                } else {
                    // Fallback - try to convert
                    try {
                        currentX0 = new Date(currentXRange[0]).getTime();
                        currentX1 = new Date(currentXRange[1]).getTime();
                    } catch (e) {
                        console.warn('🎥 YouTube Markers: Could not parse current X range:', currentXRange);
                        return false; // Skip this update
                    }
                }

                const currentXSpan = currentX1 - currentX0;

                // Only consider significant if X-axis span changed by more than 10%
                const newX0 = eventData['xaxis.range[0]'];
                const newX1 = eventData['xaxis.range[1]'];
                if (newX0 && newX1) {
                    const newXSpan = new Date(newX1).getTime() - new Date(newX0).getTime();
                    const spanChangeRatio = Math.abs(newXSpan - currentXSpan) / currentXSpan;
                    isSignificantRangeChange = spanChangeRatio > 0.1; // 10% change threshold
                }
            }

            if (hasYRangeChange && currentYRange && currentYRange.length === 2) {
                const currentYSpan = currentYRange[1] - currentYRange[0];
                // Only consider significant if Y-axis span changed by more than 20%
                const newY0 = eventData['yaxis.range[0]'];
                const newY1 = eventData['yaxis.range[1]'];
                if (newY0 !== undefined && newY1 !== undefined) {
                    const newYSpan = newY1 - newY0;
                    const spanChangeRatio = Math.abs(newYSpan - currentYSpan) / Math.abs(currentYSpan);
                    isSignificantRangeChange = isSignificantRangeChange || (spanChangeRatio > 0.2); // 20% change threshold
                }
            }
        }

        // User-initiated updates include:
        // - Significant axis range changes (panning/zooming)
        // - Autorange changes
        // - Drag mode changes
        const isUserUpdate = (hasXRangeChange || hasYRangeChange) ? isSignificantRangeChange : (hasAutorange || isDragModeChange);

        // Debug logging - only for actual user updates
        if (isUserUpdate) {
            console.log('🎥 YouTube Markers: Detected user chart update:', {
                hasXRangeChange,
                hasYRangeChange,
                hasAutorange,
                isDragModeChange,
                isSignificantRangeChange
            });
        }

        return isUserUpdate;
    }

    /**
     * Enable/disable YouTube markers
     * WebSocket-based: markers come from websocket, we only control display
     */
    setEnabled(enabled) {
        this.isEnabled = enabled;
        console.log('🎥 YouTube Markers:', enabled ? 'Enabled' : 'Disabled', '(websocket-based)');

        if (enabled) {
            // WebSocket-based: markers will come from websocket handlers
            // No need to load from HTTP endpoint
            this.startPeriodicUpdates();
        } else {
            this.removeExistingMarkers();
            this.stopPeriodicUpdates();
        }
    }

    /**
     * Update symbol
     * WebSocket-based: symbol change is handled by websocket handlers
     */
    updateSymbol(symbol) {
        if (this.currentSymbol !== symbol) {
            console.log('🎥 YouTube Markers: Symbol changed to', symbol, '(websocket-based)');
            this.currentSymbol = symbol;
            // WebSocket-based: markers will come from websocket handlers
            // No need to load from HTTP endpoint
        }
    }

    /**
     * Get current marker statistics
     */
    getStats() {
        return {
            enabled: this.isEnabled,
            websocketBased: this.websocketBased,
            symbol: this.currentSymbol,
            markerCount: this.markers && this.markers.x ? this.markers.x.length : 0,
            lastUpdate: new Date().toISOString(),
            updateInterval: this.updateInterval / 1000 / 60, // in minutes
            periodicUpdatesEnabled: this.periodicUpdatesEnabled
        };
    }

    /**
     * Set up click event handler for markers
     */
    setupClickHandler() {
        if (!window.gd) {
            console.error('🎥 YouTube Markers: Chart not available for click handler');
            return;
        }

        // Store reference to the click handler function
        if (!this.clickHandler) {
            this.clickHandler = (data) => {
                console.log('🎥 YouTube Markers: Click detected', data);

                // Check if clicked point is from YouTube markers
                if (data.points && data.points.length > 0) {
                    const point = data.points[0];
                    console.log('🎥 YouTube Markers: Clicked point:', point);

                    // Find the trace that was clicked
                    if (point.fullData && point.fullData.name === 'YouTube Videos') {
                        console.log('🎥 YouTube Markers: YouTube marker clicked!');
                        const pointIndex = point.pointIndex;

                        // Get description data
                        const transcript = point.fullData.transcripts ?
                            point.fullData.transcripts[pointIndex] : 'No description available';
                        const title = point.fullData.text ?
                            point.fullData.text[pointIndex] : 'Unknown title';
                        const videoId = point.fullData.video_ids ?
                            point.fullData.video_ids[pointIndex] : '';
                        const publishedDate = point.fullData.customdata ?
                            point.fullData.customdata[pointIndex] : '';

                        console.log('🎥 YouTube Markers: Opening modal for:', title);

                        // Show description modal
                        this.showTranscriptModal(title, transcript, videoId, publishedDate);
                    } else {
                        console.log('🎥 YouTube Markers: Clicked non-YouTube marker:', point.fullData ? point.fullData.name : 'unknown');
                    }
                } else {
                    console.log('🎥 YouTube Markers: No points in click data');
                }
            };
        }

        // Remove existing click handler if it exists
        if (window.gd.removeListener && this.existingClickHandler) {
            try {
                window.gd.removeListener('plotly_click', this.existingClickHandler);
            } catch (e) {
                console.warn('🎥 YouTube Markers: Could not remove existing click handler:', e);
            }
        }

        // Add the click event handler
        window.gd.on('plotly_click', this.clickHandler);

        // Store reference for cleanup
        this.existingClickHandler = this.clickHandler;

        console.log('🎥 YouTube Markers: Click handler set up successfully');
    }

    /**
     * Show modal with full description
     */
    showTranscriptModal(title, transcript, videoId, publishedDate) {
        // Remove existing modal if present
        const existingModal = document.getElementById('youtube-transcript-modal');
        if (existingModal) {
            existingModal.remove();
        }

        // Create modal HTML
        const modalHTML = `
            <div id="youtube-transcript-modal" style="
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.8);
                display: flex;
                justify-content: center;
                align-items: center;
                z-index: 10000;
                font-family: Arial, sans-serif;
            ">
                <div style="
                    background: white;
                    border-radius: 8px;
                    padding: 20px;
                    max-width: 800px;
                    max-height: 80vh;
                    overflow-y: auto;
                    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
                    position: relative;
                ">
                    <div style="
                        display: flex;
                        justify-content: space-between;
                        align-items: center;
                        margin-bottom: 15px;
                        border-bottom: 1px solid #eee;
                        padding-bottom: 10px;
                    ">
                        <h3 style="margin: 0; color: #333; font-size: 18px;">${title}</h3>
                        <button id="close-transcript-modal" style="
                            background: #f44336;
                            color: white;
                            border: none;
                            border-radius: 4px;
                            padding: 8px 12px;
                            cursor: pointer;
                            font-size: 14px;
                        ">✕ Close</button>
                    </div>

                    <div style="margin-bottom: 15px; color: #666; font-size: 14px;">
                        <strong>Published:</strong> ${publishedDate}
                        ${videoId ? `<br><strong>Video ID:</strong> ${videoId}` : ''}
                    </div>

                    <div style="
                        background: #f9f9f9;
                        border: 1px solid #ddd;
                        border-radius: 4px;
                        padding: 15px;
                        max-height: 400px;
                        overflow-y: auto;
                        font-size: 14px;
                        line-height: 1.5;
                        white-space: pre-wrap;
                    ">
                        ${transcript}
                    </div>

                    <div style="margin-top: 15px; text-align: right;">
                        <button id="copy-transcript" style="
                            background: #2196F3;
                            color: white;
                            border: none;
                            border-radius: 4px;
                            padding: 8px 16px;
                            cursor: pointer;
                            font-size: 14px;
                            margin-right: 10px;
                        ">📋 Copy Description</button>
                        ${videoId ? `<a href="https://www.youtube.com/watch?v=${videoId}" target="_blank" style="
                            background: #FF0000;
                            color: white;
                            text-decoration: none;
                            border-radius: 4px;
                            padding: 8px 16px;
                            font-size: 14px;
                            display: inline-block;
                        ">🎥 Watch Video</a>` : ''}
                    </div>
                </div>
            </div>
        `;

        // Add modal to page
        document.body.insertAdjacentHTML('beforeend', modalHTML);

        // Set up event handlers
        const modal = document.getElementById('youtube-transcript-modal');
        const closeBtn = document.getElementById('close-transcript-modal');
        const copyBtn = document.getElementById('copy-transcript');

        // Close modal when clicking close button
        closeBtn.addEventListener('click', () => {
            modal.remove();
        });

        // Close modal when clicking outside
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.remove();
            }
        });

        // Copy transcript to clipboard
        copyBtn.addEventListener('click', async () => {
            try {
                await navigator.clipboard.writeText(transcript);
                copyBtn.textContent = '✅ Copied!';
                copyBtn.style.background = '#4CAF50';
                setTimeout(() => {
                    copyBtn.textContent = '📋 Copy Description';
                    copyBtn.style.background = '#2196F3';
                }, 2000);
            } catch (err) {
                console.error('Failed to copy transcript:', err);
                copyBtn.textContent = '❌ Copy Failed';
                copyBtn.style.background = '#f44336';
                setTimeout(() => {
                    copyBtn.textContent = '📋 Copy Description';
                    copyBtn.style.background = '#2196F3';
                }, 2000);
            }
        });

        console.log('🎥 YouTube Markers: Description modal displayed');
    }

    /**
     * Force refresh markers
     * WebSocket-based: markers come from websocket, manual refresh not needed
     */
    async refresh() {
        console.log('🎥 YouTube Markers: Manual refresh requested (websocket-based - no action needed)');
        // WebSocket-based: markers come from websocket handlers
        // No need to manually load from HTTP endpoint
    }
}

// Global instance
window.youtubeMarkersManager = new YouTubeMarkersManager();

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    console.log('🎥 YouTube Markers: DOM ready, waiting for chart initialization...');

    // Wait for chart to be initialized
    const checkChartReady = setInterval(() => {
        if (window.gd && window.symbolSelect) {
            clearInterval(checkChartReady);

            // Get current symbol
            const currentSymbol = window.symbolSelect.value;
            if (currentSymbol) {
                window.youtubeMarkersManager.initializeForSymbol(currentSymbol);
            }

            // Listen for symbol changes
            window.symbolSelect.addEventListener('change', function() {
                const newSymbol = window.symbolSelect.value;
                window.youtubeMarkersManager.updateSymbol(newSymbol);
            });

            console.log('🎥 YouTube Markers: Fully initialized');
        }
    }, 1000);
});

// Export for debugging
window.debugYouTubeMarkers = function() {
    console.log('🎥 YouTube Markers Debug Info:');
    console.log(window.youtubeMarkersManager.getStats());
    return window.youtubeMarkersManager.getStats();
};

// Add to global scope for easy access
window.refreshYouTubeMarkers = function() {
    return window.youtubeMarkersManager.refresh();
};

window.toggleYouTubeMarkers = function(enabled) {
    window.youtubeMarkersManager.setEnabled(enabled !== undefined ? enabled : !window.youtubeMarkersManager.isEnabled);
    return window.youtubeMarkersManager.isEnabled;
};

window.toggleYouTubeMarkerUpdates = function(enabled) {
    window.youtubeMarkersManager.periodicUpdatesEnabled = enabled !== undefined ? enabled : !window.youtubeMarkersManager.periodicUpdatesEnabled;
    console.log('🎥 YouTube Markers: Periodic updates', window.youtubeMarkersManager.periodicUpdatesEnabled ? 'enabled' : 'disabled');

    if (window.youtubeMarkersManager.periodicUpdatesEnabled) {
        window.youtubeMarkersManager.startPeriodicUpdates();
    } else {
        window.youtubeMarkersManager.stopPeriodicUpdates();
    }

    return window.youtubeMarkersManager.periodicUpdatesEnabled;
};
