let isLoadingSettings = false;
let isRestoringIndicators = false;
let isProgrammaticallySettingResolution = false;
let isProgrammaticallySettingRange = false;

// Debounce utility function
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}



async function populateDropdowns() {
    try {
        // Get symbols from symbols_list endpoint
        const symbolsResponse = await fetch('/symbols_list');
        if (!symbolsResponse.ok) {
            const errorBody = await symbolsResponse.text().catch(() => "Could not read error body");
            throw new Error(`HTTP error! status: ${symbolsResponse.status} - ${errorBody}`);
        }
        const symbols = await symbolsResponse.json();

        // Get config data from initial_chart_config endpoint
        const configResponse = await fetch('/initial_chart_config');
        if (!configResponse.ok) {
            const errorBody = await configResponse.text().catch(() => "Could not read error body");
            throw new Error(`HTTP error! status: ${configResponse.status} - ${errorBody}`);
        }
        const configData = await configResponse.json();

        // Populate symbols dropdown
        window.symbolSelect.innerHTML = '';
        symbols.forEach(symbol => {
            const option = document.createElement('option');
            option.value = symbol;
            option.textContent = symbol.replace('USDT', '/USDT');
            window.symbolSelect.appendChild(option);
        });

        // Populate resolutions dropdown
        window.resolutionSelect.innerHTML = '';
        configData.resolutions.forEach(resolution => {
            const option = document.createElement('option');
            option.value = resolution;
            option.textContent = resolution;
            window.resolutionSelect.appendChild(option);
        });

        // Populate ranges dropdown
        window.rangeSelect.innerHTML = '';
        configData.ranges.forEach(range => {
            const option = document.createElement('option');
            option.value = range.value;
            option.textContent = range.label;
            window.rangeSelect.appendChild(option);
        });

    } catch (error) {
        console.error('Error populating dropdowns:', error);
        // Fallback: populate with known symbols
        if (window.symbolSelect.options.length === 0) {
            const fallbackSymbols = ["BTCUSDT", "XMRUSDT", "ETHUSDT", "SOLUSDT", "SUIUSDT", "PAXGUSDT", "BNBUSDT", "ADAUSDT"];
            window.symbolSelect.innerHTML = '';
            fallbackSymbols.forEach(symbol => {
                const option = document.createElement('option');
                option.value = symbol;
                option.textContent = symbol.replace('USDT', '/USDT');
                window.symbolSelect.appendChild(option);
            });
        }
        if (window.resolutionSelect.options.length === 0) window.resolutionSelect.innerHTML = '<option value="1d">1 Day</option>';
        if (window.rangeSelect.options.length === 0) window.rangeSelect.innerHTML = '<option value="30d">30d</option>';
    }
}

async function loadSettings(symbolOverride = null) {
    isLoadingSettings = true; // Prevent saveSettings from running during load

    // Use provided symbol override (e.g., from URL) or fall back to dropdown value
    const currentSymbol = symbolOverride || window.symbolSelect.value;
    if (!currentSymbol) {
        console.error("loadSettings: No symbol available. This should not happen - dropdown should be populated first.");
        isLoadingSettings = false;
        return;
    }

    updateSelectedShapeInfoPanel(null); // Assumes updateSelectedShapeInfoPanel is globally available

    try {
        const response = await fetch(`/settings?symbol=${currentSymbol}`);

        if (!response.ok) {
            const errorText = await response.text();
            console.error('[DEBUG settingsManager] Settings load failed:', response.status, errorText);
            throw new Error(`HTTP error! status: ${response.status} - ${errorText}`);
        }

        const settings = await response.json();

        // Always apply saved settings to UI controls - this is the expected behavior

        // Set resolution programmatically (without triggering change event)
        if (settings.resolution && window.resolutionSelect.options.length > 0) {
            isProgrammaticallySettingResolution = true;
            window.resolutionSelect.value = settings.resolution;
            // Reset flag after a short delay to allow any event processing
            delay(10).then(() => {
                isProgrammaticallySettingResolution = false;
            });
        }

        // Set range programmatically (without triggering change event)
        if (settings.range && window.rangeSelect.options.length > 0) {
            isProgrammaticallySettingRange = true;
            window.rangeSelect.value = settings.range;
            // Reset flag after a short delay to allow any event processing
            delay(10).then(() => {
                isProgrammaticallySettingRange = false;
            });
        }

        if (settings.xAxisMin !== null && settings.xAxisMax !== null && typeof settings.xAxisMin !== 'undefined') {
            // Check if timestamps are in seconds or milliseconds
            let minTimestamp = settings.xAxisMin;
            let maxTimestamp = settings.xAxisMax;

            // Check for old alarm dates (before year 2000)
            const minDate = new Date(settings.xAxisMin < 1e10 ? settings.xAxisMin * 1000 : settings.xAxisMin);
            const maxDate = new Date(settings.xAxisMax < 1e10 ? settings.xAxisMax * 1000 : settings.xAxisMax);

            // Handle timestamp format detection and conversion
            // Current system uses seconds (1.75e9 range), but we need milliseconds for JavaScript Date objects
            if (settings.xAxisMin < 1e10) { // Less than 10 billion (reasonable for seconds since 1970)
                // Convert seconds to milliseconds for JavaScript Date objects
                minTimestamp = settings.xAxisMin * 1000;
                maxTimestamp = settings.xAxisMax * 1000;
            }
            // Handle legacy timestamps that were incorrectly saved as milliseconds but represent old dates
            else if (settings.xAxisMin < 1e12 && new Date(settings.xAxisMin).getFullYear() < 2000) {
                // These are old millisecond timestamps that need to be converted to proper milliseconds
                minTimestamp = Math.floor(settings.xAxisMin / 1000);
                maxTimestamp = Math.floor(settings.xAxisMax / 1000);
            }
            // Handle current millisecond timestamps (1.75e12 range for 2025 dates)
            else {
                // Already in milliseconds, use as-is
                minTimestamp = settings.xAxisMin;
                maxTimestamp = settings.xAxisMax;
            }

            // Only set currentXAxisRange if it's not already set (preserves user's current panning)
            if (!window.currentXAxisRange) {
                window.currentXAxisRange = [minTimestamp, maxTimestamp];
            } else {
            }

            const minDateDisplay = new Date(minTimestamp);
            const maxDateDisplay = new Date(maxTimestamp);
            window.xAxisMinDisplay.textContent = isNaN(minDateDisplay.getTime()) ? 'Invalid Date' : minDateDisplay.toISOString();
            window.xAxisMaxDisplay.textContent = isNaN(maxDateDisplay.getTime()) ? 'Invalid Date' : maxDateDisplay.toISOString();

        } else {
            window.currentXAxisRange = null;
            window.xAxisMinDisplay.textContent = 'Auto';
            window.xAxisMaxDisplay.textContent = 'Auto';
        }

       if (settings.yAxisMin !== null && settings.yAxisMax !== null && typeof settings.yAxisMin !== 'undefined') {
             // Check for unusual Y-axis ranges that might indicate old/problematic settings
             const yMin = parseFloat(settings.yAxisMin);
             const yMax = parseFloat(settings.yAxisMax);

             // Only set currentYAxisRange if it's not already set (preserves user's current zoom)
             if (!window.currentYAxisRange) {
                 window.currentYAxisRange = [settings.yAxisMin, settings.yAxisMax];
                 window.yAxisMinDisplay.textContent = settings.yAxisMin.toFixed(2);
                 window.yAxisMaxDisplay.textContent = settings.yAxisMax.toFixed(2);
             } else {
             }
         } else {
             // Only clear if not already set by user
             if (!window.currentYAxisRange) {
                 window.currentYAxisRange = null;
                 window.yAxisMinDisplay.textContent = 'Auto';
                 window.yAxisMaxDisplay.textContent = 'Auto';
             }
         }

        // Restore active indicators - ensure DOM is ready
        const restoreIndicators = () => {
            const allIndicatorCheckboxes = document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]');

            if (allIndicatorCheckboxes.length === 0) {
                console.warn('[DEBUG settingsManager] No indicator checkboxes found, will retry in 100ms');
                setTimeout(restoreIndicators, 100);
                return;
            }

            // Set flag to prevent saves during restoration
            isRestoringIndicators = true;

            // First uncheck all
            allIndicatorCheckboxes.forEach(checkbox => checkbox.checked = false);

            // Then check the active ones
            if (settings.activeIndicators && Array.isArray(settings.activeIndicators) && settings.activeIndicators.length > 0) {
                settings.activeIndicators.forEach(indicatorValue => {
                    const checkbox = document.querySelector(`#indicator-checkbox-list input[type="checkbox"][value="${indicatorValue}"]`);
                    if (checkbox) {
                        checkbox.checked = true;
                    } else {
                        console.warn('[DEBUG settingsManager] Indicator checkbox not found for:', indicatorValue);
                    }
                });
            }
            isRestoringIndicators = false;
        };

        // Try to restore indicators immediately, or retry if DOM not ready
        restoreIndicators();

        // Live data is always enabled now

        // Load Agent Trades checkbox state
        if (typeof settings.showAgentTrades === 'boolean') {
            document.getElementById('showAgentTradesCheckbox').checked = settings.showAgentTrades;
        } else {
            document.getElementById('showAgentTradesCheckbox').checked = false;
        }
                
        // Load replay controls
        const replayFromInput = document.getElementById('replay-from');
        const replayToInput = document.getElementById('replay-to');
        const replaySpeedInput = document.getElementById('replay-speed');

        if (settings.replayFrom) replayFromInput.value = settings.replayFrom;
        else replayFromInput.value = '';
        if (settings.replayTo) replayToInput.value = settings.replayTo;
        else replayToInput.value = '';
        if (settings.replaySpeed) replaySpeedInput.value = settings.replaySpeed;
        else replaySpeedInput.value = '1';

        // Load Ollama settings
        if (typeof settings.useLocalOllama === 'boolean') {
            window.useLocalOllamaCheckbox.checked = settings.useLocalOllama;
        } else {
            window.useLocalOllamaCheckbox.checked = false;
        }
        window.useLocalOllamaCheckbox.dispatchEvent(new Event('change')); // Trigger UI update

        if (settings.localOllamaModelName) {
            setTimeout(() => { window.localOllamaModelSelect.value = settings.localOllamaModelName; }, 500); // Delay to allow dropdown to populate
        }

        // Load streamDeltaTime
        if (typeof settings.streamDeltaTime === 'number' && window.streamDeltaSlider && window.streamDeltaValueDisplay) {
            window.streamDeltaSlider.value = settings.streamDeltaTime;
            window.streamDeltaValueDisplay.textContent = settings.streamDeltaTime;
            window.currentStreamDeltaTime = settings.streamDeltaTime; // Update global state
        } else if (window.streamDeltaSlider && window.streamDeltaValueDisplay) { // Default if not in settings
            window.streamDeltaSlider.value = 0; // Default value
            window.streamDeltaValueDisplay.textContent = '0';
            window.currentStreamDeltaTime = 0; // Update global state
        }

        // Load min volume filter
        if (typeof settings.minVolumeFilter === 'number' && window.minValueSlider && window.minValueDisplay) {
            window.minValueSlider.value = settings.minVolumeFilter;
            window.minValueDisplay.textContent = settings.minVolumeFilter.toLocaleString();
        } else if (window.minValueSlider && window.minValueDisplay) { // Default if not in settings
            window.minValueSlider.value = 0; // Default value - show all trades
            window.minValueDisplay.textContent = '0';
        }
        if (settings.last_selected_symbol) {
            const currentUrlSymbol = window.location.pathname.substring(1).toUpperCase() || null;
            if (window.symbolSelect.value != settings.last_selected_symbol) {
                // Only set programmatic flag if this is NOT the symbol from the URL
                // (URL symbols should be allowed to trigger change events)
                if (settings.last_selected_symbol !== currentUrlSymbol) {
                    window.isProgrammaticallySettingSymbol = true;
                } else {
                }
                window.symbolSelect.value = settings.last_selected_symbol;
                // Reset the flag after a short delay to allow the change event to be processed
                setTimeout(() => {
                    window.isProgrammaticallySettingSymbol = false;
                }, 100);
            }
        }

        // Apply loaded ranges to the chart if it exists
        if (window.gd && (window.currentXAxisRange || window.currentYAxisRange)) {
            const layoutUpdate = {};

            if (window.currentXAxisRange) {
                layoutUpdate['xaxis.range'] = [new Date(window.currentXAxisRange[0]), new Date(window.currentXAxisRange[1])];
                layoutUpdate['xaxis.autorange'] = false;
            }

            if (window.currentYAxisRange) {
                layoutUpdate['yaxis.range'] = window.currentYAxisRange;
                layoutUpdate['yaxis.autorange'] = false;
            }

            if (Object.keys(layoutUpdate).length > 0) {
                Plotly.relayout(window.gd, layoutUpdate).then(() => {
                }).catch(error => {
                    console.error('[DEBUG settingsManager] Error applying loaded ranges to chart:', error);
                });
            }
        }
    } catch (error) {
        console.error('Error loading settings for ' + currentSymbol + ':', error);
        window.currentXAxisRange = null; window.currentYAxisRange = null;
        window.xAxisMinDisplay.textContent = 'Auto'; window.xAxisMaxDisplay.textContent = 'Auto';
        window.yAxisMinDisplay.textContent = 'Auto'; window.yAxisMaxDisplay.textContent = 'Auto';
        // Live data is always enabled now
        document.getElementById('replay-from').value = '';
        document.getElementById('replay-to').value = '';
        document.getElementById('replay-speed').value = '1';
        window.useLocalOllamaCheckbox.checked = false;
        window.useLocalOllamaCheckbox.dispatchEvent(new Event('change'));
        if (window.streamDeltaSlider && window.streamDeltaValueDisplay) {
            window.streamDeltaSlider.value = 0;
            window.streamDeltaValueDisplay.textContent = '0';
            window.currentStreamDeltaTime = 0;
        }
        if (window.minValueSlider && window.minValueDisplay) {
            window.minValueSlider.value = 0; // Default value - show all trades
            window.minValueDisplay.textContent = '0';
        }
    } finally {
        isLoadingSettings = false; // Allow saves again
        isRestoringIndicators = false; // Ensure indicator restoration flag is also reset

        // WebSocket will be initialized by main.js after all initialization is complete
    }
}

// Apply debouncing to saveSettings to prevent rapid calls from spamming the API
function saveSettingsInner() {
    // Prevent saving settings while they're still being loaded
    if (isLoadingSettings) {
        return;
    }

    // Prevent saving settings while indicators are still being restored
    if (isRestoringIndicators) {
        return;
    }

    const currentSymbol = window.symbolSelect.value;
    if (!currentSymbol) {
        console.warn("saveSettings: No symbol selected. Cannot save settings.");
        return;
    }
    const settings = {
        symbol: currentSymbol,
        resolution: window.resolutionSelect.value,
        range: window.rangeSelect.value
    };

    if (window.currentXAxisRange) {
        settings.xAxisMin = window.currentXAxisRange[0];
        settings.xAxisMax = window.currentXAxisRange[1];
    } else {
        settings.xAxisMin = null;
        settings.xAxisMax = null;
    }
    if (window.currentYAxisRange) {
        settings.yAxisMin = window.currentYAxisRange[0];
        settings.yAxisMax = window.currentYAxisRange[1];
    } else {
        settings.yAxisMin = null;
        settings.yAxisMax = null;
    }

    settings.replayFrom = document.getElementById('replay-from').value;
    settings.replayTo = document.getElementById('replay-to').value;
    settings.replaySpeed = document.getElementById('replay-speed').value;
    settings.useLocalOllama = document.getElementById('use-local-ollama-checkbox').checked;
    settings.localOllamaModelName = document.getElementById('local-ollama-model-select').value;

    const indicatorCheckboxes = document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]');
    const activeIndicators = [];
    indicatorCheckboxes.forEach(checkbox => {
        if (checkbox.checked) {
            activeIndicators.push(checkbox.value);
        }
    });
    settings.activeIndicators = activeIndicators;
    settings.liveDataEnabled = true; // Always enabled now
    settings.showAgentTrades = document.getElementById('showAgentTradesCheckbox').checked;

    // Add streamDeltaTime from the slider
    if (window.streamDeltaSlider) { // Check if the element exists (it should, from main.js)
        settings.streamDeltaTime = parseInt(window.streamDeltaSlider.value, 10);
    } else {
        console.warn("saveSettings: streamDeltaSlider element not found on window.");
        settings.streamDeltaTime = 0; // Default if slider not found
    }

    // Include the last selected symbol in settings
    settings.last_selected_symbol = currentSymbol;

    // Include min volume filter setting
    if (window.minValueSlider && window.minValueSlider.value !== undefined) {
        settings.minVolumeFilter = parseFloat(window.minValueSlider.value);
    } else {
        settings.minVolumeFilter = 0; // Default to showing all trades
    }

    fetch('/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
    })
    .then(response => {
        if (response.ok) {
        } else {
            console.error('[DEBUG settingsManager] Failed to save settings for', currentSymbol, 'Status:', response.status);
        }
    })
    .catch(err => console.error("Error saving settings:", err));
}

// Debounced version of saveSettings (500ms delay)
const saveSettings = debounce(saveSettingsInner, 500);
