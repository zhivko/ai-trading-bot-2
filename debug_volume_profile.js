// Debug script to test volume profile functionality
const puppeteer = require('puppeteer');

async function debugVolumeProfile() {
    console.log('🔍 Starting volume profile debug...');

    const browser = await puppeteer.launch({
        headless: false,
        args: ['--no-sandbox', '--disable-setuid-sandbox'],
        defaultViewport: null
    });

    const page = await browser.newPage();

    // Enable console logging
    page.on('console', msg => {
        if (msg.text().includes('TRADE_HISTORY')) {
            console.log(`🟢 CONSOLE: ${msg.text()}`);
        }
    });

    try {
        // Navigate to the trading app
        console.log('🌐 Navigating to 192.168.1.52:5000...');
        await page.goto('http://192.168.1.52:5000/BTCUSDT', {
            waitUntil: 'domcontentloaded',  // Changed to faster load condition
            timeout: 30000  // Increased timeout
        });

        console.log('✅ Page loaded successfully');

        // Wait for chart to initialize
        await page.waitForSelector('#chart', { timeout: 10000 });
        console.log('📊 Chart element found');

        // Wait for volume profile checkbox
        await page.waitForSelector('#show-volume-profile-checkbox', { timeout: 5000 });
        console.log('✅ Volume profile checkbox found');

        // Check if checkbox is present
        const checkbox = await page.$('#show-volume-profile-checkbox');
        if (!checkbox) {
            console.log('❌ Volume profile checkbox not found');
            return;
        }

        // Get initial checkbox state
        const initialState = await page.evaluate(() => {
            const cb = document.getElementById('show-volume-profile-checkbox');
            return cb ? cb.checked : false;
        });
        console.log(`📋 Initial volume profile checkbox state: ${initialState}`);

        // Wait for WebSocket messages (trade history)
        console.log('⏳ Waiting for trade history WebSocket messages...');

        let tradeHistoryReceived = false;
        page.on('response', interceptedResponse => {
            if (interceptedResponse.url().includes('trade-history') ||
                interceptedResponse.request().method() === 'WebSocket') {
                tradeHistoryReceived = true;
                console.log('📡 Trade history WebSocket activity detected');
            }
        });

        // Wait for WebSocket to connect and initialize
        console.log('⏳ Waiting for WebSocket initialization and data...');
        await page.waitForTimeout(5000);

        // Try triggering volume profile update manually if needed
        console.log('🔄 Triggering volume profile update manually...');
        await page.evaluate(() => {
            if (window.updateTradeHistoryVisualizations) {
                window.updateTradeHistoryVisualizations();
            }
        });

        // Wait for update to complete
        await page.waitForTimeout(2000);

        // Checkboxes should already be checked from HTML template
        console.log('🔍 Checking that checkboxes are enabled by default...');
        const checkboxStates = await page.evaluate(() => {
            const vpf = document.getElementById('show-volume-profile-checkbox');
            const tmf = document.getElementById('show-trade-markers-checkbox');
            return {
                volumeProfile: vpf ? vpf.checked : false,
                tradeMarkers: tmf ? tmf.checked : false
            };
        });
        console.log('📋 Checkbox states:', checkboxStates);

        // Check console logs for volume profile creation attempts
        console.log('🔍 Checking for volume profile creation logs...');

        const volumeProfileStatus = await page.evaluate(() => {
            // Check if volume profile data exists
            if (window.tradeHistoryData && window.volumeProfileData) {
                return {
                    hasTradeHistory: true,
                    tradeHistoryCount: window.tradeHistoryData.length,
                    hasVolumeProfile: true,
                    volumeProfileCount: window.volumeProfileData.length,
                    volumeProfileCheckbox: document.getElementById('show-volume-profile-checkbox')?.checked,
                    minVolumeValue: document.getElementById('min-value-slider')?.value
                };
            }
            return {
                hasTradeHistory: false,
                tradeHistoryCount: 0,
                hasVolumeProfile: false,
                volumeProfileCount: 0
            };
        });

        console.log('📊 Volume profile status:', volumeProfileStatus);

        // Check if volume profile traces exist on the chart
        const chartTraces = await page.evaluate(() => {
            if (window.gd && window.gd.data) {
                const volumeProfileTraces = window.gd.data.filter(trace =>
                    trace.name && (trace.name.includes('Vol @') || trace.name.includes('Volume Profile'))
                );
                console.log('📊 VOLUME PROFILE TRACES FOUND:', volumeProfileTraces.length);
                volumeProfileTraces.forEach((trace, i) => {
                    console.log(`   Trace ${i}: ${trace.name}, xaxis: ${trace.xaxis}, yaxis: ${trace.yaxis}, type: ${trace.type}`);
                    if (trace.x && trace.x.length > 0) {
                        console.log(`   X range: ${Math.min(...trace.x)} to ${Math.max(...trace.x)}`);
                    }
                    if (trace.y && trace.y.length > 0) {
                        console.log(`   Y range: ${Math.min(...trace.y)} to ${Math.max(...trace.y)}`);
                    }
                });
                return window.gd.data.map(trace => ({
                    name: trace.name,
                    type: trace.type,
                    xLength: trace.x ? trace.x.length : 0,
                    yLength: trace.y ? trace.y.length : 0,
                    xaxis: trace.xaxis,
                    yaxis: trace.yaxis
                }));
            }
            return [];
        });

        console.log('📈 Chart traces:', chartTraces);

        const volumeProfileTrace = chartTraces.find(trace => trace.name === 'Volume Profile');
        if (volumeProfileTrace) {
            console.log('✅ Volume Profile trace found on chart!');
            console.log('📊 Volume Profile trace details:', volumeProfileTrace);
        } else {
            console.log('❌ Volume Profile trace NOT found on chart');

            // Check why it might not be created
            const debugInfo = await page.evaluate(() => {
                const checkbox = document.getElementById('show-volume-profile-checkbox');
                const minValueSlider = document.getElementById('min-value-slider');

                return {
                    checkboxChecked: checkbox ? checkbox.checked : false,
                    minVolumeValue: minValueSlider ? parseFloat(minValueSlider.value) : 0,
                    volumeProfileDataLength: window.volumeProfileData ? window.volumeProfileData.length : 0,
                    tradeHistoryDataLength: window.tradeHistoryData ? window.tradeHistoryData.length : 0,
                    windowGdData: window.gd?.data?.length || 0
                };
            });

            console.log('🔍 Debug info:', debugInfo);
        }

    } catch (error) {
        console.error('❌ Error during debug:', error);
    } finally {
        // Keep browser open for manual inspection
        console.log('🔚 Debug completed. Browser will remain open.');
        console.log('👀 Manually check browser console and chart for volume profile.');
        // await browser.close();
    }
}

debugVolumeProfile().catch(console.error);
