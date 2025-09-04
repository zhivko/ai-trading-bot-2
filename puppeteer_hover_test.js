const puppeteer = require('puppeteer');

async function testLineHoverAndClick() {
    console.log('🚀 Starting Puppeteer test for line hover and click functionality...');

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
        await page.waitForSelector('#chart', { timeout: 10000 });
        console.log('✅ Page loaded successfully');

        // Wait for WebSocket connection and initial data loading
        console.log('⏳ Waiting for WebSocket connection and initial data...');
        await page.waitForFunction(() => {
            return window.gd && window.gd.data && window.gd.data.length > 0;
        }, { timeout: 15000 });
        console.log('✅ WebSocket connected and initial data loaded');

        // Check if there are any shapes already on the chart
        const initialShapes = await page.evaluate(() => {
            return window.gd && window.gd.layout && window.gd.layout.shapes ?
                window.gd.layout.shapes.filter(s => s.type === 'line' && s.id && !s.isSystemShape) : [];
        });

        console.log(`📊 Initial shapes on chart: ${initialShapes.length}`);

        if (initialShapes.length === 0) {
            console.log('⚠️  No shapes found on chart. Drawing a test line...');

            // Switch to draw mode
            await page.evaluate(() => {
                if (window.gd) {
                    Plotly.relayout(window.gd, { dragmode: 'drawline' });
                }
            });

            // Get chart center coordinates
            const chartRect = await page.evaluate(() => {
                const chartDiv = document.getElementById('chart');
                if (chartDiv) {
                    const rect = chartDiv.getBoundingClientRect();
                    return {
                        left: rect.left,
                        top: rect.top,
                        width: rect.width,
                        height: rect.height,
                        centerX: rect.left + rect.width / 2,
                        centerY: rect.top + rect.height / 2
                    };
                }
                return null;
            });

            if (chartRect) {
                console.log('🎨 Drawing a test line...');

                // Simulate drawing a line by clicking and dragging
                await page.mouse.move(chartRect.centerX - 100, chartRect.centerY);
                await page.mouse.down();
                await page.mouse.move(chartRect.centerX + 100, chartRect.centerY);
                await page.mouse.up();

                // Wait for the shape to be created
                await page.waitForFunction(() => {
                    return window.gd && window.gd.layout && window.gd.layout.shapes &&
                           window.gd.layout.shapes.some(s => s.type === 'line' && s.id && !s.isSystemShape);
                }, { timeout: 5000 });

                console.log('✅ Test line drawn successfully');
            }
        }

        // Get current shapes after potential drawing
        const currentShapes = await page.evaluate(() => {
            return window.gd && window.gd.layout && window.gd.layout.shapes ?
                window.gd.layout.shapes.filter(s => s.type === 'line' && s.id && !s.isSystemShape) : [];
        });

        console.log(`📊 Current shapes on chart: ${currentShapes.length}`);

        if (currentShapes.length === 0) {
            console.log('❌ No shapes available for testing. Cannot proceed with hover/click tests.');
            return;
        }

        // Test 1: Hover functionality
        console.log('\n🧪 TEST 1: HOVER FUNCTIONALITY');

        // Get the first shape for testing
        const testShape = currentShapes[0];
        console.log(`Testing with shape ID: ${testShape.id}`);

        // Get chart position and shape coordinates
        const shapeInfo = await page.evaluate((shapeId) => {
            const chartDiv = document.getElementById('chart');
            if (!chartDiv || !window.gd) return null;

            const rect = chartDiv.getBoundingClientRect();
            const shape = window.gd.layout.shapes.find(s => s.id === shapeId);
            if (!shape) return null;

            // Calculate approximate screen coordinates of the shape center
            const shapeCenterX = (shape.x0 + shape.x1) / 2;
            const shapeCenterY = (shape.y0 + shape.y1) / 2;

            // Convert to screen coordinates (approximate)
            const screenX = rect.left + rect.width / 2; // Center of chart
            const screenY = rect.top + rect.height / 2;  // Center of chart

            return {
                shapeId: shape.id,
                shapeX0: shape.x0,
                shapeY0: shape.y0,
                shapeX1: shape.x1,
                shapeY1: shape.y1,
                screenX: screenX,
                screenY: screenY,
                chartRect: {
                    left: rect.left,
                    top: rect.top,
                    width: rect.width,
                    height: rect.height
                }
            };
        }, testShape.id);

        if (shapeInfo) {
            console.log('Shape info:', {
                id: shapeInfo.shapeId,
                coordinates: `(${shapeInfo.shapeX0}, ${shapeInfo.shapeY0}) to (${shapeInfo.shapeX1}, ${shapeInfo.shapeY1})`,
                screenPos: `(${shapeInfo.screenX}, ${shapeInfo.screenY})`
            });

            // Move mouse to shape position
            console.log('🖱️  Moving mouse to shape position...');
            await page.mouse.move(shapeInfo.screenX, shapeInfo.screenY);

            // Wait a bit for hover to take effect
            await new Promise(resolve => setTimeout(resolve, 500));

            // Check if hover state changed
            const hoverState = await page.evaluate((shapeId) => {
                return {
                    hoveredShapeId: window.hoveredShapeBackendId,
                    newHoveredShapeId: window.newHoveredShapeId,
                    isShapeSelected: window.isShapeSelected ? window.isShapeSelected(shapeId) : false,
                    shapeColor: (() => {
                        const shape = window.gd.layout.shapes.find(s => s.id === shapeId);
                        return shape && shape.line ? shape.line.color : null;
                    })()
                };
            }, testShape.id);

            console.log('Hover test results:', hoverState);

            if (hoverState.hoveredShapeId === testShape.id) {
                console.log('✅ HOVER TEST PASSED: Shape is being hovered');
            } else {
                console.log('❌ HOVER TEST FAILED: Shape is not being hovered');
                console.log(`Expected hovered ID: ${testShape.id}, Actual: ${hoverState.hoveredShapeId}`);
            }

            // Check if color changed to hover color (red)
            if (hoverState.shapeColor === 'red' || hoverState.shapeColor === 'rgba(255, 0, 0, 1)') {
                console.log('✅ HOVER COLOR TEST PASSED: Shape color changed to red on hover');
            } else {
                console.log(`❌ HOVER COLOR TEST FAILED: Shape color is ${hoverState.shapeColor}, expected red`);
            }
        }

        // Test 2: Click functionality
        console.log('\n🧪 TEST 2: CLICK FUNCTIONALITY');

        // Clear any existing selection first
        await page.evaluate(() => {
            if (window.deselectAllShapes) {
                window.deselectAllShapes();
            }
        });

        // Click on the shape
        console.log('🖱️  Clicking on shape...');
        await page.mouse.click(shapeInfo.screenX, shapeInfo.screenY);

        // Wait for click to process
        await new Promise(resolve => setTimeout(resolve, 500));

        // Check if shape was selected
        const clickState = await page.evaluate((shapeId) => {
            return {
                selectedShapeIds: window.getSelectedShapeIds ? window.getSelectedShapeIds() : [],
                isShapeSelected: window.isShapeSelected ? window.isShapeSelected(shapeId) : false,
                shapeColor: (() => {
                    const shape = window.gd.layout.shapes.find(s => s.id === shapeId);
                    return shape && shape.line ? shape.line.color : null;
                })(),
                activeShapeId: window.activeShapeForPotentialDeletion ?
                    window.activeShapeForPotentialDeletion.id : null
            };
        }, testShape.id);

        console.log('Click test results:', clickState);

        if (clickState.isShapeSelected) {
            console.log('✅ CLICK SELECTION TEST PASSED: Shape is selected');
        } else {
            console.log('❌ CLICK SELECTION TEST FAILED: Shape is not selected');
        }

        // Check if color changed to selected color (green)
        if (clickState.shapeColor === 'green' || clickState.shapeColor === 'rgba(0, 128, 0, 1)' ||
            clickState.shapeColor === '#00FF00') {
            console.log('✅ CLICK COLOR TEST PASSED: Shape color changed to green on selection');
        } else {
            console.log(`❌ CLICK COLOR TEST FAILED: Shape color is ${clickState.shapeColor}, expected green`);
        }

        // Test 3: Click outside to deselect
        console.log('\n🧪 TEST 3: DESELECT FUNCTIONALITY');

        // Click outside the shape (on empty chart area)
        const emptyAreaX = shapeInfo.screenX + 200; // 200px to the right
        const emptyAreaY = shapeInfo.screenY + 100; // 100px down

        console.log('🖱️  Clicking outside shape to deselect...');
        await page.mouse.click(emptyAreaX, emptyAreaY);

        // Wait for deselection to process
        await new Promise(resolve => setTimeout(resolve, 500));

        // Check if shape was deselected
        const deselectState = await page.evaluate((shapeId) => {
            return {
                selectedShapeIds: window.getSelectedShapeIds ? window.getSelectedShapeIds() : [],
                isShapeSelected: window.isShapeSelected ? window.isShapeSelected(shapeId) : false,
                shapeColor: (() => {
                    const shape = window.gd.layout.shapes.find(s => s.id === shapeId);
                    return shape && shape.line ? shape.line.color : null;
                })(),
                activeShapeId: window.activeShapeForPotentialDeletion ?
                    window.activeShapeForPotentialDeletion.id : null
            };
        }, testShape.id);

        console.log('Deselect test results:', deselectState);

        if (!deselectState.isShapeSelected) {
            console.log('✅ DESELECT TEST PASSED: Shape is deselected');
        } else {
            console.log('❌ DESELECT TEST FAILED: Shape is still selected');
        }

        // Check if color changed back to default (blue)
        if (deselectState.shapeColor === 'blue' || deselectState.shapeColor === 'rgba(0, 0, 255, 1)') {
            console.log('✅ DESELECT COLOR TEST PASSED: Shape color changed back to blue');
        } else {
            console.log(`❌ DESELECT COLOR TEST FAILED: Shape color is ${deselectState.shapeColor}, expected blue`);
        }

        // Take final screenshot
        await page.screenshot({ path: 'hover_click_test_final.png', fullPage: true });
        console.log('📸 Final screenshot saved as hover_click_test_final.png');

        console.log('\n🎯 HOVER AND CLICK TESTS COMPLETED');

        // Summary
        console.log('\n📋 TEST SUMMARY:');
        console.log('Hover functionality:', hoverState && hoverState.hoveredShapeId === testShape.id ? '✅ PASS' : '❌ FAIL');
        console.log('Click selection:', clickState && clickState.isShapeSelected ? '✅ PASS' : '❌ FAIL');
        console.log('Deselect functionality:', deselectState && !deselectState.isShapeSelected ? '✅ PASS' : '❌ FAIL');

    } catch (error) {
        console.error('❌ Test failed:', error);
    } finally {
        await browser.close();
    }
}

// Run the test
testLineHoverAndClick().catch(console.error);