const puppeteer = require('puppeteer');

async function investigateDrawingSave() {
    console.log('🚀 Starting Puppeteer investigation of drawing save issue...');

    const browser = await puppeteer.launch({
        headless: false, // Set to false to see the browser
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    });

    const page = await browser.newPage();

    // Enable request interception to monitor network requests
    await page.setRequestInterception(true);

    // Track save_drawing requests
    let saveDrawingRequests = [];
    let allRequests = [];

    page.on('request', (request) => {
        const url = request.url();
        const method = request.method();

        // Log all requests for debugging
        allRequests.push({
            url: url,
            method: method,
            timestamp: new Date().toISOString(),
            resourceType: request.resourceType()
        });

        // Specifically track save_drawing requests
        if (url.includes('/save_drawing/') && method === 'POST') {
            console.log('🚨 SAVE_DRAWING REQUEST DETECTED:', {
                url: url,
                method: method,
                timestamp: new Date().toISOString(),
                headers: request.headers(),
                postData: request.postData()
            });
            saveDrawingRequests.push({
                url: url,
                method: method,
                timestamp: new Date().toISOString(),
                postData: request.postData(),
                headers: request.headers()
            });
        }

        request.continue();
    });

    // Monitor console messages
    page.on('console', (msg) => {
        const type = msg.type();
        const text = msg.text();

        // Filter for relevant console messages
        if (text.includes('save') || text.includes('drawing') || text.includes('shape') ||
            text.includes('plotly_shapedrawn') || text.includes('plotly_relayout') ||
            text.includes('handleNewShapeSave') || text.includes('loadDrawingsAndRedraw')) {
            console.log(`📝 CONSOLE [${type.toUpperCase()}]: ${text}`);
        }

        // Also log any error messages
        if (type === 'error') {
            console.log(`❌ CONSOLE ERROR: ${text}`);
        }
    });

    // Monitor page errors
    page.on('pageerror', (error) => {
        console.log('🚨 PAGE ERROR:', error.message);
    });

    try {
        console.log('🌐 Navigating to trading view page...');
        await page.goto('http://192.168.1.52:5000/BTCUSDT', {
            waitUntil: 'networkidle2',
            timeout: 30000
        });

        console.log('⏳ Waiting for page to fully load and stabilize...');
        await page.waitForTimeout(5000); // Wait 5 seconds for any automatic activity

        console.log('📊 INVESTIGATION RESULTS:');
        console.log('========================');

        console.log('\n🔍 SAVE DRAWING REQUESTS FOUND:');
        if (saveDrawingRequests.length === 0) {
            console.log('✅ No save_drawing requests detected on page load');
        } else {
            console.log(`❌ Found ${saveDrawingRequests.length} save_drawing request(s):`);
            saveDrawingRequests.forEach((req, index) => {
                console.log(`\n--- Request ${index + 1} ---`);
                console.log(`URL: ${req.url}`);
                console.log(`Method: ${req.method}`);
                console.log(`Timestamp: ${req.timestamp}`);
                console.log(`Post Data: ${req.postData}`);
            });
        }

        console.log('\n📋 ALL NETWORK REQUESTS SUMMARY:');
        const drawingRelatedRequests = allRequests.filter(req =>
            req.url.includes('drawing') || req.url.includes('shape')
        );
        console.log(`Total requests: ${allRequests.length}`);
        console.log(`Drawing-related requests: ${drawingRelatedRequests.length}`);

        if (drawingRelatedRequests.length > 0) {
            console.log('\nDrawing-related requests:');
            drawingRelatedRequests.forEach((req, index) => {
                console.log(`${index + 1}. ${req.method} ${req.url} (${req.timestamp})`);
            });
        }

        // Check for any shapes in the current layout
        console.log('\n🎨 CHECKING CURRENT CHART STATE:');
        const layoutInfo = await page.evaluate(() => {
            if (window.gd && window.gd.layout) {
                const shapes = window.gd.layout.shapes || [];
                return {
                    shapeCount: shapes.length,
                    shapes: shapes.map(shape => ({
                        type: shape.type,
                        id: shape.id,
                        x0: shape.x0,
                        y0: shape.y0,
                        x1: shape.x1,
                        y1: shape.y1,
                        name: shape.name,
                        isSystemShape: shape.isSystemShape
                    }))
                };
            }
            return { shapeCount: 0, shapes: [] };
        });

        console.log(`Current shapes in layout: ${layoutInfo.shapeCount}`);
        if (layoutInfo.shapes.length > 0) {
            console.log('Shape details:');
            layoutInfo.shapes.forEach((shape, index) => {
                console.log(`  ${index + 1}. Type: ${shape.type}, ID: ${shape.id}, System: ${shape.isSystemShape}`);
            });
        }

        // Wait a bit more to see if any delayed saves occur
        console.log('\n⏳ Waiting additional 10 seconds for any delayed activity...');
        await page.waitForTimeout(10000);

        console.log('\n📋 FINAL SUMMARY:');
        console.log('================');
        console.log(`Total save_drawing requests: ${saveDrawingRequests.length}`);
        console.log(`Total network requests: ${allRequests.length}`);
        console.log(`Current shapes in chart: ${layoutInfo.shapeCount}`);

        if (saveDrawingRequests.length > 0) {
            console.log('\n❌ ISSUE CONFIRMED: Drawings are being saved automatically on page load!');
            console.log('This suggests there are shapes in the layout that are being processed as "new" shapes.');
        } else {
            console.log('\n✅ No automatic drawing saves detected on page load.');
        }

    } catch (error) {
        console.error('❌ Investigation failed:', error);
    } finally {
        console.log('\n🔚 Closing browser...');
        await browser.close();
    }
}

// Run the investigation
investigateDrawingSave().catch(console.error);
