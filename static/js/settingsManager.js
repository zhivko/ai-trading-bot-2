function saveSettings() {
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
    settings.liveDataEnabled = window.liveDataCheckbox.checked;
    settings.showAgentTrades = document.getElementById('showAgentTradesCheckbox').checked;

    // Add streamDeltaTime from the slider
    if (window.streamDeltaSlider) { // Check if the element exists (it should, from main.js)
        settings.streamDeltaTime = parseInt(window.streamDeltaSlider.value, 10);
    } else {
        console.warn("saveSettings: streamDeltaSlider element not found on window.");
        settings.streamDeltaTime = 0; // Default if slider not found
    }

    console.log('[DEBUG settingsManager] Saving settings for', currentSymbol, ':', JSON.stringify(settings, null, 2));

    fetch('/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
    })
    .then(response => {
        if (response.ok) {
            console.log('[DEBUG settingsManager] Settings saved successfully for', currentSymbol);
        } else {
            console.error('[DEBUG settingsManager] Failed to save settings for', currentSymbol, 'Status:', response.status);
        }
    })
    .catch(err => console.error("Error saving settings:", err));
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

async function loadSettings() {
    const currentSymbol = window.symbolSelect.value;
    if (!currentSymbol) {
        console.warn("loadSettings: No symbol available in dropdown yet. updateChart will use defaults.");
        window.xAxisMinDisplay.textContent = 'Auto'; window.xAxisMaxDisplay.textContent = 'Auto';
        window.yAxisMinDisplay.textContent = 'Auto'; window.yAxisMaxDisplay.textContent = 'Auto';
        updateChart(); // Assumes updateChart is globally available
        return;
    } else {
        updateSelectedShapeInfoPanel(null); // Assumes updateSelectedShapeInfoPanel is globally available
    }

    try {
        const response = await fetch(`/settings?symbol=${currentSymbol}`);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const settings = await response.json();

        console.log('[DEBUG settingsManager] Loaded settings for', currentSymbol, ':', JSON.stringify(settings, null, 2));

        if (settings.resolution && window.resolutionSelect.options.length > 0) window.resolutionSelect.value = settings.resolution;
        if (settings.range && window.rangeSelect.options.length > 0) window.rangeSelect.value = settings.range;

        if (settings.xAxisMin !== null && settings.xAxisMax !== null && typeof settings.xAxisMin !== 'undefined') {
            // Check if timestamps are in seconds or milliseconds
            let minTimestamp = settings.xAxisMin;
            let maxTimestamp = settings.xAxisMax;

            // Check for old alarm dates (before year 2000)
            const minDate = new Date(settings.xAxisMin < 1e10 ? settings.xAxisMin * 1000 : settings.xAxisMin);
            const maxDate = new Date(settings.xAxisMax < 1e10 ? settings.xAxisMax * 1000 : settings.xAxisMax);

            if (minDate.getFullYear() < 2000 || maxDate.getFullYear() < 2000) {
                const minDateStr = isNaN(minDate.getTime()) ? 'Invalid Date' : minDate.toISOString();
                const maxDateStr = isNaN(maxDate.getTime()) ? 'Invalid Date' : maxDate.toISOString();
                console.warn('🚨 OLD ALARM DETECTED: X-Axis settings contain very old dates!', {
                    symbol: currentSymbol,
                    xAxisMin: settings.xAxisMin,
                    xAxisMax: settings.xAxisMax,
                    minDate: minDateStr,
                    maxDate: maxDateStr,
                    minYear: minDate.getFullYear(),
                    maxYear: maxDate.getFullYear(),
                    action: 'Auto-scaling chart to fix corrupted timestamps'
                });

                // Auto-scale immediately to fix the corrupted timestamps
                setTimeout(() => {
                    if (typeof window.applyAutoscale === 'function') {
                        console.log('🚨 OLD ALARM: Triggering automatic autoscale to fix corrupted timestamps');
                        window.applyAutoscale();
                    } else {
                        console.warn('🚨 OLD ALARM: window.applyAutoscale function not available for auto-fix');
                    }
                }, 100); // Small delay to ensure chart is fully loaded
            }

            // If the timestamp appears to be in seconds (reasonable date range),
            // convert to milliseconds for JavaScript Date
            // If it's already in milliseconds (large numbers), use as-is
            if (settings.xAxisMin < 1e10) { // Less than 10 billion (reasonable for seconds since 1970)
                minTimestamp = settings.xAxisMin * 1000;
                maxTimestamp = settings.xAxisMax * 1000;
            }
            // Handle legacy timestamps that were incorrectly saved
            else if (settings.xAxisMin < 1e12 && new Date(settings.xAxisMin).getFullYear() < 2000) {
                minTimestamp = Math.floor(settings.xAxisMin / 1000);
                maxTimestamp = Math.floor(settings.xAxisMax / 1000);
            }

            window.currentXAxisRange = [minTimestamp, maxTimestamp];
            console.log('[DEBUG settingsManager] Set window.currentXAxisRange to:', window.currentXAxisRange);

            const minDateDisplay = new Date(minTimestamp);
            const maxDateDisplay = new Date(maxTimestamp);
            window.xAxisMinDisplay.textContent = isNaN(minDateDisplay.getTime()) ? 'Invalid Date' : minDateDisplay.toLocaleString();
            window.xAxisMaxDisplay.textContent = isNaN(maxDateDisplay.getTime()) ? 'Invalid Date' : maxDateDisplay.toLocaleString();

            console.log('[DEBUG settingsManager] X-axis display updated - Min:', window.xAxisMinDisplay.textContent, 'Max:', window.xAxisMaxDisplay.textContent);
        } else {
            window.currentXAxisRange = null;
            window.xAxisMinDisplay.textContent = 'Auto';
            window.xAxisMaxDisplay.textContent = 'Auto';
        }

       if (settings.yAxisMin !== null && settings.yAxisMax !== null && typeof settings.yAxisMin !== 'undefined') {
             // Check for unusual Y-axis ranges that might indicate old/problematic settings
             const yMin = parseFloat(settings.yAxisMin);
             const yMax = parseFloat(settings.yAxisMax);

             // Log warning for very small ranges or unusual values that might indicate old settings
             if ((yMax - yMin) < 0.1 || yMin < 0 || yMax > 100) {
                 console.warn('🚨 POTENTIAL OLD ALARM DETECTED: Y-Axis settings have unusual values!', {
                     symbol: currentSymbol,
                     yAxisMin: settings.yAxisMin,
                     yAxisMax: settings.yAxisMax,
                     range: yMax - yMin,
                     action: 'Please verify if these Y-axis values are correct'
                 });
             }

             window.currentYAxisRange = [settings.yAxisMin, settings.yAxisMax];
             window.yAxisMinDisplay.textContent = settings.yAxisMin.toFixed(2);
             window.yAxisMaxDisplay.textContent = settings.yAxisMax.toFixed(2);
         } else {
             window.currentYAxisRange = null;
             window.yAxisMinDisplay.textContent = 'Auto';
             window.yAxisMaxDisplay.textContent = 'Auto';
         }

        const allIndicatorCheckboxes = document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]');
        allIndicatorCheckboxes.forEach(checkbox => checkbox.checked = false);

        if (settings.activeIndicators && Array.isArray(settings.activeIndicators)) {
            settings.activeIndicators.forEach(indicatorValue => {
                const checkbox = document.querySelector(`#indicator-checkbox-list input[type="checkbox"][value="${indicatorValue}"]`);
                if (checkbox) {
                    checkbox.checked = true;
                }
            });
        }

        if (typeof settings.liveDataEnabled === 'boolean') {
            window.liveDataCheckbox.checked = settings.liveDataEnabled;
        } else {
            window.liveDataCheckbox.checked = false;
        }

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
        if (settings.last_selected_symbol) {
            if (window.symbolSelect.value != settings.last_selected_symbol) {
                window.isProgrammaticallySettingSymbol = true;
                window.symbolSelect.value = settings.last_selected_symbol;
            }
        }
    } catch (error) {
        console.error('Error loading settings for ' + currentSymbol + ':', error);
        window.currentXAxisRange = null; window.currentYAxisRange = null;
        window.xAxisMinDisplay.textContent = 'Auto'; window.xAxisMaxDisplay.textContent = 'Auto';
        window.yAxisMinDisplay.textContent = 'Auto'; window.yAxisMaxDisplay.textContent = 'Auto';
        window.liveDataCheckbox.checked = false;
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
    } finally {
        updateChart(); // Assumes updateChart is globally available
    }
}