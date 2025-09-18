const REALTIME_PRICE_LINE_NAME = 'realtimePriceLine';
const CROSSHAIR_VLINE_NAME = 'crosshair-vline';
const DEFAULT_DRAWING_COLOR = 'blue';
const HOVER_DRAWING_COLOR = 'red';
const SELECTED_DRAWING_COLOR = 'green';
const MAX_LIVE_CANDLES = 1000; // Maximum number of candles to keep in memory for live chart
const VISUAL_UPDATE_DEBOUNCE_DELAY = 30;
const FETCH_DEBOUNCE_DELAY = 2500;
const INDICATOR_OB_LINE_NAME = 'indicator_ob_line';
const INDICATOR_OS_LINE_NAME = 'indicator_os_line';
const BUY_EVENT_MARKER_COLOR = 'green';
const SELL_EVENT_MARKER_COLOR = 'red';
const BUY_EVENT_MARKER_SYMBOL = 'triangle-up';
const SELL_EVENT_MARKER_SYMBOL = 'triangle-down';
const REALTIME_PRICE_TEXT_ANNOTATION_NAME = 'realtimePriceTextAnnotation';

// Function to detect mobile devices using modern browser APIs
function isMobileDevice() {
    // Log client resolution information
    console.log('[DEBUG] Mobile Detection Info:');
    console.log('  window.innerWidth:', window.innerWidth);
    console.log('  window.innerHeight:', window.innerHeight);
    console.log('  screen.width:', screen.width);
    console.log('  screen.height:', screen.height);
    console.log('  devicePixelRatio:', window.devicePixelRatio);
    console.log('  navigator.userAgent:', navigator.userAgent);

    // Use the modern User-Agent Client Hints API if available
    if (navigator.userAgentData && typeof navigator.userAgentData.mobile === 'boolean') {
        console.log('  navigator.userAgentData.mobile:', navigator.userAgentData.mobile);
        return navigator.userAgentData.mobile;
    }

    // Fallback: Check for coarse pointer (typical of touch devices)
    if (window.matchMedia && window.matchMedia('(pointer: coarse)').matches) {
        console.log('  pointer coarse detected: true');
        return true;
    }

    // Final fallback: Check user agent for mobile devices (legacy method)
    const userAgentMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
    console.log('  userAgent mobile pattern match:', userAgentMobile);

    const isMobile = userAgentMobile;
    console.log('[DEBUG] Final mobile detection result:', isMobile);
    return isMobile;
}


const config = {
    responsive: true,
    displayModeBar: true,
    scrollZoom: true, // Keep scroll zoom enabled for mouse wheel zooming
    modeBarButtonsToRemove: ['zoom2d', 'zoomIn2d', 'zoomOut2d', 'autoscale'], // Remove zoom buttons
    modeBarButtonsToAdd: [
        {
            name: 'Draw Line', // Tooltip for the button
            icon: Plotly.Icons.drawline, // Use Plotly's standard drawline icon
            click: function(gd) {
                // Switch to drawline mode
                Plotly.relayout(gd, { dragmode: 'drawline' });
                console.log('Switched to drawline mode');
            }
        }
    ],
    displaylogo: false, // Hide Plotly logo to save space
    showTips: false, // Disable tips that might interfere on mobile
    editable: false,
    autosize: true, // Keep autosize for responsive behavior, but grid rowheights should take precedence
    edits: {
        shapePosition: true,
        annotationPosition: false,
        annotationText: false,
        axisTitleText: false,
        legendText: false,
        titleText: false
    }
};

// Function to disable hover on mobile devices
function disableMobileHover(gd) {
    if (isMobileDevice() && gd) {
        Plotly.relayout(gd, {
            hovermode: false,
            hoverdistance: 0
        });
        console.log('Mobile hover disabled via Plotly.relayout');
    }
}

// Function to force hide hover elements via CSS
function forceHideHoverElements() {
    if (isMobileDevice()) {
        // Create a style element to hide hover elements
        const style = document.createElement('style');
        style.id = 'mobile-hover-blocker';
        style.textContent = `
            .js-plotly-plot .hoverlayer,
            .js-plotly-plot .hovertext,
            .js-plotly-plot g.hoverlayer,
            .js-plotly-plot .hoverlayer text,
            .js-plotly-plot [class*="hover"] {
                display: none !important;
                visibility: hidden !important;
                opacity: 0 !important;
            }
        `;
        document.head.appendChild(style);
        console.log('Mobile hover elements hidden via CSS injection');
    }
}


// Make them available globally for other scripts, or consider a module system later
window.REALTIME_PRICE_LINE_NAME = REALTIME_PRICE_LINE_NAME;
window.DEFAULT_DRAWING_COLOR = DEFAULT_DRAWING_COLOR;
window.HOVER_DRAWING_COLOR = HOVER_DRAWING_COLOR;
window.SELECTED_DRAWING_COLOR = SELECTED_DRAWING_COLOR;
window.REALTIME_PRICE_TEXT_ANNOTATION_NAME = REALTIME_PRICE_TEXT_ANNOTATION_NAME;
window.BUY_EVENT_MARKER_COLOR = BUY_EVENT_MARKER_COLOR;
window.SELL_EVENT_MARKER_COLOR = SELL_EVENT_MARKER_COLOR;
window.BUY_EVENT_MARKER_SYMBOL = BUY_EVENT_MARKER_SYMBOL;
window.SELL_EVENT_MARKER_SYMBOL = SELL_EVENT_MARKER_SYMBOL;
window.isMobileDevice = isMobileDevice;
window.disableMobileHover = disableMobileHover;
window.forceHideHoverElements = forceHideHoverElements;

// Make config globally available
window.config = config;
