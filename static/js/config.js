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

// Function to detect mobile devices
function isMobileDevice() {
    // Check user agent for mobile devices
    const userAgentMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);

    // Check screen dimensions (with fallback for when window is not fully loaded)
    const screenMobile = (window.innerWidth && window.innerWidth <= 768) ||
                        (window.innerHeight && window.innerHeight <= 1024) ||
                        (screen.width && screen.width <= 768) ||
                        (screen.height && screen.height <= 1024);

    // Check for touch capability
    const hasTouch = 'ontouchstart' in window || navigator.maxTouchPoints > 0;

    return userAgentMobile || screenMobile || hasTouch;
}

const layout = {
    hovermode: isMobileDevice() ? false : 'x unified', // Disable hover popups on mobile devices
    hoverdistance: isMobileDevice() ? 0 : 20, // Set hover distance to 0 on mobile to prevent accidental hovers
    title: {
        text: ''
    },
   xaxis: {
        title: {
            text: ""
        },
        rangeslider: { visible: false },
        type: 'date',
        tickformat: '%Y-%m-%d<br>%H:%M',
        showgrid: false,
        gridcolor: '#e5e7eb',
        linecolor: '#6b7280',
        automargin: true,
        tickvals: [],
        ticktext: [],
        autorange: false
    },
    yaxis: {
        title: {
            text: 'Price (USDT)',
            font: { size: 10 }
        },
        side: 'left',
        fixedrange: false,
        autorange: false
    },
    dragmode: 'pan',
    showlegend: false,
    margin: { l: 50, r: 50, b: 60, t: 40, pad: 0 }
};

const config = {
    responsive: true,
    displayModeBar: true,
    scrollZoom: true,
    modeBarButtonsToRemove: ['autoscale2d'], // Remove the default Plotly autoscale button
    modeBarButtonsToAdd: [
        {
            name: 'Autoscale Data', // Tooltip for the button
            icon: Plotly.Icons.autoscale, // Use Plotly's standard autoscale icon
            click: function(gd) {
                // Call your global applyAutoscale function
                if (typeof window.applyAutoscale === 'function') {
                    window.applyAutoscale(gd); // Pass the graph div (gd) to your function
                } else {
                    console.error('Custom Autoscale: window.applyAutoscale function not found. Falling back to default.');
                    Plotly.relayout(gd, {'xaxis.autorange': true, 'yaxis.autorange': true}); // Fallback
                }
            }
        },
        'zoomIn2d', 'zoomOut2d', 'drawline', 'select2d', 'lasso2d' // Keep other buttons from your original config
    ],
    editable: false,
    autosize: true, // Recommended for handling dynamic content
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

// Function to get mobile-optimized layout
function getMobileOptimizedLayout() {
    const baseLayout = { ...layout }; // Clone the base layout

    if (isMobileDevice()) {
        baseLayout.hovermode = false;
        baseLayout.hoverdistance = 0;
        console.log('Mobile-optimized layout applied');
    }

    return baseLayout;
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
window.getMobileOptimizedLayout = getMobileOptimizedLayout;
window.forceHideHoverElements = forceHideHoverElements;
