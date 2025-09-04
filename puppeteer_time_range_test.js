const puppeteer = require('puppeteer');

async function testTimeRangeSelection() {
    console.log('🚀 Starting Puppeteer test for time range selection...');

    const browser = await puppeteer.launch({
        headless: false, // Set to true for headless mode
        args: ['--no-sandbox', '--disable-setuid-sandbox'],
        defaultViewport: {
            width: 1920,
            height: 1080
        }
    });

    const page = await browser.newPage();

    try {
        // Navigate to the trading app
        console.log('📍 Navigating to http://192.168.1.52:5000...');
        await page.goto('http://192.168.1.52:5000', {
            waitUntil: 'networkidle2',
            timeout: 30000
        });

        // Wait for the page to fully load
        await page.waitForSelector('#range-select', { timeout: 10000 });
        console.log('✅ Page loaded successfully');

        // Wait for WebSocket connection and initial data loading (deterministic approach)
        console.log('⏳ Waiting for WebSocket connection and initial data...');
        await page.waitForFunction(() => {
            return window.gd && window.gd.data && window.gd.data.length > 0 &&
                   window.gd.data.some(trace => trace.name === 'ETHUSDT' && trace.x && trace.x.length > 10);
        }, { timeout: 15000 });
        console.log('✅ WebSocket connected and initial data loaded');

        // Select some indicators to test
        console.log('🔧 Selecting indicators for testing...');
        await page.click('#indicator-macd'); // Select MACD
        await page.click('#indicator-rsi'); // Select RSI
        console.log('✅ Indicators selected: MACD and RSI');

        // Wait for indicators to be calculated and appear in chart (deterministic approach)
        console.log('⏳ Waiting for indicators to be calculated...');
        try {
            await page.waitForFunction(() => {
                return window.gd && window.gd.data && window.gd.data.length > 1 &&
                       window.gd.data.some(trace => trace.name && (
                           trace.name.toLowerCase().includes('macd') ||
                           trace.name.toLowerCase().includes('rsi')
                       ));
            }, { timeout: 15000 });
            console.log('✅ Indicators calculated and visible in chart');
        } catch (error) {
            console.log('⚠️  Indicators not found within timeout, continuing with test...');
            // Log current chart state for debugging
            const chartState = await page.evaluate(() => {
                return {
                    dataLength: window.gd ? window.gd.data.length : 0,
                    traceNames: window.gd ? window.gd.data.map(t => t.name) : [],
                    checkedIndicators: Array.from(document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value)
                };
            });
            console.log('Current chart state:', chartState);
        }

        // Take initial screenshot
        await page.screenshot({ path: 'initial_state.png', fullPage: true });
        console.log('📸 Initial screenshot saved as initial_state.png');

        // Check indicator state after selection
        console.log('\n🔍 INDICATOR STATE AFTER SELECTION:');
        const indicatorState = await page.evaluate(() => {
            const checkedIndicators = Array.from(document.querySelectorAll('#indicator-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
            const chartTraces = window.gd && window.gd.data ? window.gd.data.map(trace => ({
                name: trace.name,
                type: trace.type,
                points: trace.x ? trace.x.length : 0
            })) : [];
            const combinedIndicators = window.combinedIndicators || [];

            return {
                checkedIndicators,
                chartTraces,
                combinedIndicators
            };
        });

        console.log('Checked indicators:', indicatorState.checkedIndicators);
        console.log('Combined indicators:', indicatorState.combinedIndicators);
        console.log('Chart traces:', indicatorState.chartTraces);

        // Get initial state
        console.log('\n📊 INITIAL STATE:');
        const initialState = await page.evaluate(() => {
            const xMinDisplay = document.getElementById('x-axis-min-display')?.textContent || 'N/A';
            const xMaxDisplay = document.getElementById('x-axis-max-display')?.textContent || 'N/A';
            const rangeSelect = document.getElementById('range-select');
            const currentRange = rangeSelect ? rangeSelect.value : 'N/A';

            // Try to get the actual chart x-axis range
            let chartXRange = null;
            if (window.gd && window.gd.layout && window.gd.layout.xaxis) {
                chartXRange = window.gd.layout.xaxis.range;
            }

            // Check for indicators
            let chartTraces = [];
            let combinedIndicators = [];
            if (window.gd && window.gd.data) {
                chartTraces = window.gd.data.map(trace => ({
                    name: trace.name,
                    type: trace.type,
                    points: trace.x ? trace.x.length : 0
                }));
            }
            if (window.combinedIndicators) {
                combinedIndicators = window.combinedIndicators;
            }

            return {
                xMinDisplay,
                xMaxDisplay,
                currentRange,
                chartXRange,
                chartTraces,
                combinedIndicators
            };
        });

        console.log('X-Axis Min Display:', initialState.xMinDisplay);
        console.log('X-Axis Max Display:', initialState.xMaxDisplay);
        console.log('Current Range:', initialState.currentRange);
        console.log('Chart X-Range:', initialState.chartXRange);
        console.log('Chart Traces:', initialState.chartTraces);
        console.log('Combined Indicators:', initialState.combinedIndicators);

        // Test specific time ranges: 3M and 6M
        const timeRanges = ['3m', '6m'];

        for (const range of timeRanges) {
            console.log(`\n🔄 TESTING TIME RANGE: ${range}`);

            // Select the time range
            await page.select('#range-select', range);

            // Wait for range change to take effect (deterministic approach)
            console.log(`⏳ Waiting for range change to ${range} to complete...`);
            await page.waitForFunction((expectedRange) => {
                const currentRange = document.getElementById('range-select').value;
                return currentRange === expectedRange;
            }, { timeout: 10000 }, range);

            // Wait for chart data to update
            await page.waitForFunction(() => {
                return window.gd && window.gd.data && window.gd.data.length > 0 &&
                       window.gd.data.some(trace => trace.name === 'ETHUSDT' && trace.x && trace.x.length > 5);
            }, { timeout: 15000 });

            console.log(`✅ Range changed to ${range} and data updated`);

            // Capture the state after selection
            const stateAfterSelection = await page.evaluate(() => {
                const xMinDisplay = document.getElementById('x-axis-min-display')?.textContent || 'N/A';
                const xMaxDisplay = document.getElementById('x-axis-max-display')?.textContent || 'N/A';
                const rangeSelect = document.getElementById('range-select');
                const currentRange = rangeSelect ? rangeSelect.value : 'N/A';

                // Try to get the actual chart x-axis range
                let chartXRange = null;
                if (window.gd && window.gd.layout && window.gd.layout.xaxis) {
                    chartXRange = window.gd.layout.xaxis.range;
                }

                // Also get the window.currentXAxisRange if available
                let currentXAxisRange = null;
                if (window.currentXAxisRange) {
                    currentXAxisRange = window.currentXAxisRange;
                }

                // Check for indicators after selection
                let chartTraces = [];
                let combinedIndicators = [];
                if (window.gd && window.gd.data) {
                    chartTraces = window.gd.data.map(trace => ({
                        name: trace.name,
                        type: trace.type,
                        points: trace.x ? trace.x.length : 0
                    }));
                }
                if (window.combinedIndicators) {
                    combinedIndicators = window.combinedIndicators;
                }

                return {
                    xMinDisplay,
                    xMaxDisplay,
                    currentRange,
                    chartXRange,
                    currentXAxisRange,
                    chartTraces,
                    combinedIndicators
                };
            });

            console.log(`Range: ${stateAfterSelection.currentRange}`);
            console.log(`X-Axis Min Display: ${stateAfterSelection.xMinDisplay}`);
            console.log(`X-Axis Max Display: ${stateAfterSelection.xMaxDisplay}`);
            console.log(`Chart X-Range:`, stateAfterSelection.chartXRange);
            console.log(`Window.currentXAxisRange:`, stateAfterSelection.currentXAxisRange);
            console.log(`Chart Traces:`, stateAfterSelection.chartTraces);
            console.log(`Combined Indicators:`, stateAfterSelection.combinedIndicators);

            // Take screenshot for this range
            await page.screenshot({ path: `range_${range}_state.png`, fullPage: true });
            console.log(`📸 Screenshot saved as range_${range}_state.png`);

            // Validate data range matches selected time range
            console.log(`\n🔍 VALIDATION FOR RANGE ${range.toUpperCase()}:`);
            const validationResult = await page.evaluate((expectedRange) => {
                const currentRange = document.getElementById('range-select').value;
                const xMinDisplay = document.getElementById('x-axis-min-display').textContent;
                const xMaxDisplay = document.getElementById('x-axis-max-display').textContent;

                // Check if display shows expected range
                const expectedMonths = expectedRange === '3m' ? 3 : 6;
                const historicalBaseTime = new Date('2022-12-15T00:00:00Z').getTime();
                const expectedFromTs = expectedRange === '3m' ?
                    historicalBaseTime - 90 * 86400 * 1000 :
                    historicalBaseTime - 180 * 86400 * 1000;
                const expectedToTs = historicalBaseTime;

                const expectedMinDate = new Date(expectedFromTs);
                const expectedMaxDate = new Date(expectedToTs);

                // Get actual chart data range
                let actualMinTs = null;
                let actualMaxTs = null;
                if (window.gd && window.gd.data && window.gd.data.length > 0) {
                    const priceTrace = window.gd.data.find(trace => trace.name === 'Price' || trace.type === 'candlestick');
                    if (priceTrace && priceTrace.x && priceTrace.x.length > 0) {
                        const timestamps = priceTrace.x.map(ts => new Date(ts).getTime());
                        actualMinTs = Math.min(...timestamps);
                        actualMaxTs = Math.max(...timestamps);
                    }
                }

                // Check indicators are present
                const hasMACD = window.gd && window.gd.data ?
                    window.gd.data.some(trace => trace.name && trace.name.toLowerCase().includes('macd')) : false;
                const hasRSI = window.gd && window.gd.data ?
                    window.gd.data.some(trace => trace.name && trace.name.toLowerCase().includes('rsi')) : false;

                return {
                    currentRange,
                    expectedRange,
                    xMinDisplay,
                    xMaxDisplay,
                    expectedMinDate: expectedMinDate.toISOString(),
                    expectedMaxDate: expectedMaxDate.toISOString(),
                    actualMinTs,
                    actualMaxTs,
                    actualMinDate: actualMinTs ? new Date(actualMinTs).toISOString() : null,
                    actualMaxDate: actualMaxTs ? new Date(actualMaxTs).toISOString() : null,
                    hasMACD,
                    hasRSI,
                    indicatorsPresent: hasMACD && hasRSI,
                    rangeMatches: currentRange === expectedRange
                };
            }, range);

            console.log('Range validation:', {
                'Selected Range': validationResult.currentRange,
                'Expected Range': validationResult.expectedRange,
                'Range Matches': validationResult.rangeMatches ? '✅' : '❌',
                'Expected Min Date': validationResult.expectedMinDate,
                'Expected Max Date': validationResult.expectedMaxDate,
                'Actual Min Date': validationResult.actualMinDate,
                'Actual Max Date': validationResult.actualMaxDate,
                'MACD Indicator': validationResult.hasMACD ? '✅' : '❌',
                'RSI Indicator': validationResult.hasRSI ? '✅' : '❌',
                'Indicators Present': validationResult.indicatorsPresent ? '✅' : '❌'
            });

            // Check for potential issues
            if (!validationResult.rangeMatches) {
                console.log(`⚠️  WARNING: Selected range (${validationResult.currentRange}) does not match expected range (${validationResult.expectedRange})`);
            }
            if (!validationResult.indicatorsPresent) {
                console.log(`⚠️  WARNING: Expected indicators (MACD, RSI) are not present in chart`);
            }
            if (validationResult.actualMinTs && validationResult.actualMaxTs) {
                const expectedMinTs = new Date(validationResult.expectedMinDate).getTime();
                const expectedMaxTs = new Date(validationResult.expectedMaxDate).getTime();
                const actualMinTs = new Date(validationResult.actualMinDate).getTime();
                const actualMaxTs = new Date(validationResult.actualMaxDate).getTime();
                const minDiff = Math.abs(actualMinTs - expectedMinTs);
                const maxDiff = Math.abs(actualMaxTs - expectedMaxTs);

                console.log(`Data range difference - Min: ${minDiff}ms (${(minDiff / (1000 * 60 * 60 * 24)).toFixed(1)} days), Max: ${maxDiff}ms (${(maxDiff / (1000 * 60 * 60 * 24)).toFixed(1)} days)`);

                if (minDiff > 86400 * 1000 || maxDiff > 86400 * 1000) { // More than 1 day difference
                    console.log('⚠️  SIGNIFICANT DATA RANGE MISMATCH (> 1 day difference)');
                } else {
                    console.log('✅ Data range is within acceptable tolerance');
                }
            }

            // Check for discrepancies
            if (stateAfterSelection.chartXRange && stateAfterSelection.currentXAxisRange) {
                const chartMin = new Date(stateAfterSelection.chartXRange[0]).getTime();
                const chartMax = new Date(stateAfterSelection.chartXRange[1]).getTime();
                const displayMin = stateAfterSelection.currentXAxisRange[0];
                const displayMax = stateAfterSelection.currentXAxisRange[1];

                const minDiff = Math.abs(chartMin - displayMin);
                const maxDiff = Math.abs(chartMax - displayMax);

                console.log(`Min difference: ${minDiff}ms (${(minDiff / 1000).toFixed(2)}s)`);
                console.log(`Max difference: ${maxDiff}ms (${(maxDiff / 1000).toFixed(2)}s)`);

                if (minDiff > 1000 || maxDiff > 1000) {
                    console.log('⚠️  SIGNIFICANT DISCREPANCY DETECTED (> 1 second)');
                } else {
                    console.log('✅ Ranges are consistent');
                }
            }

            // Brief pause before next test
            await new Promise(resolve => setTimeout(resolve, 500));
        }

        console.log('\n🎯 TEST COMPLETED');

    } catch (error) {
        console.error('❌ Test failed:', error);
    } finally {
        await browser.close();
    }
}

// Run the test
testTimeRangeSelection().catch(console.error);