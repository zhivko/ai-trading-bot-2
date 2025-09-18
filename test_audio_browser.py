#!/usr/bin/env python3
"""
Browser test script for audio recording functionality using Pyppeteer.
This script tests the complete audio recording workflow from the browser.
"""

import asyncio
import json
import os
import tempfile
from pyppeteer import launch
from pyppeteer.errors import TimeoutError, PyppeteerError

class AudioRecordingTester:
    def __init__(self):
        self.browser = None
        self.page = None
        self.test_results = {
            'navigation': False,
            'authentication': False,
            'audio_interface': False,
            'recording_start': False,
            'transcription': False,
            'errors': []
        }

    async def setup_browser(self):
        """Launch browser and create new page."""
        try:
            print("🚀 Launching browser...")

            # Try to use system Chrome first
            chrome_paths = [
                r'C:\Program Files\Google\Chrome\Application\chrome.exe',
                r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
                r'C:\Users\Admin\AppData\Local\Google\Chrome\Application\chrome.exe'
            ]

            executable_path = None
            for path in chrome_paths:
                if os.path.exists(path):
                    executable_path = path
                    break

            if executable_path:
                print(f"📍 Using Chrome at: {executable_path}")
                self.browser = await launch(
                    executablePath=executable_path,
                    headless=False,  # Set to True for headless mode
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-accelerated-2d-canvas',
                        '--no-first-run',
                        '--disable-gpu',
                        '--disable-web-security',
                        '--disable-features=VizDisplayCompositor'
                    ]
                )
            else:
                print("📍 Chrome not found in standard locations, trying default Pyppeteer...")
                self.browser = await launch(
                    headless=False,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-accelerated-2d-canvas',
                        '--no-first-run',
                        '--disable-gpu'
                    ]
                )

            self.page = await self.browser.newPage()

            # Set viewport
            await self.page.setViewport({'width': 1280, 'height': 720})

            print("✅ Browser launched successfully")
            return True
        except Exception as e:
            print(f"❌ Failed to launch browser: {e}")
            self.test_results['errors'].append(f"Browser launch failed: {e}")
            return False

    async def navigate_to_site(self):
        """Navigate to the trading website."""
        try:
            print("🌐 Navigating to https://crypto.zhivko.eu...")
            await self.page.goto('https://crypto.zhivko.eu', {
                'waitUntil': 'domcontentloaded',
                'timeout': 30000
            })

            # Wait for page to load
            await self.page.waitForSelector('body', {'timeout': 10000})

            title = await self.page.title()
            print(f"✅ Page loaded: {title}")
            self.test_results['navigation'] = True
            return True
        except Exception as e:
            print(f"❌ Failed to navigate to site: {e}")
            self.test_results['errors'].append(f"Navigation failed: {e}")
            return False

    async def check_authentication(self):
        """Check if user is authenticated or needs to log in."""
        try:
            # Check for Google OAuth redirect
            current_url = self.page.url
            if 'accounts.google.com' in current_url:
                print("🔐 Google OAuth redirect detected - user needs to authenticate")
                print("📋 Please complete authentication manually in the browser window")
                print("⏳ Waiting for authentication to complete...")

                # Wait for redirect back to the main site
                try:
                    await self.page.waitForFunction(
                        '() => !window.location.href.includes("accounts.google.com")',
                        {'timeout': 120000}  # 2 minutes timeout
                    )
                    print("✅ Authentication completed")
                    self.test_results['authentication'] = True
                    return True
                except TimeoutError:
                    print("⏰ Authentication timeout - please complete login manually")
                    return False
            else:
                print("✅ User appears to be already authenticated")
                self.test_results['authentication'] = True
                return True

        except Exception as e:
            print(f"❌ Authentication check failed: {e}")
            self.test_results['errors'].append(f"Authentication check failed: {e}")
            return False

    async def check_audio_interface(self):
        """Check if audio recording interface is present."""
        try:
            print("🎤 Checking for audio recording interface...")

            # Look for audio recording elements
            record_button = await self.page.querySelector('#record-button')
            if record_button:
                print("✅ Record button found")
                self.test_results['audio_interface'] = True
                return True
            else:
                print("❌ Record button not found")
                # Try to find any audio-related elements
                audio_elements = await self.page.querySelectorAll('[id*="audio"], [id*="record"], [class*="audio"], [class*="record"]')
                if audio_elements:
                    print(f"ℹ️ Found {len(audio_elements)} audio-related elements")
                    self.test_results['audio_interface'] = True
                    return True
                else:
                    print("❌ No audio interface elements found")
                    return False

        except Exception as e:
            print(f"❌ Audio interface check failed: {e}")
            self.test_results['errors'].append(f"Audio interface check failed: {e}")
            return False

    async def test_recording_workflow(self):
        """Test the audio recording workflow."""
        try:
            print("🎙️ Testing audio recording workflow...")

            # Find record button
            record_button = await self.page.querySelector('#record-button')
            if not record_button:
                print("❌ Record button not found")
                return False

            # Check initial button state
            initial_text = await self.page.evaluate('document.querySelector("#record-button").textContent')
            print(f"📝 Initial button text: {initial_text}")

            # Click record button to start recording
            print("▶️ Starting recording...")
            await record_button.click()

            # Wait a moment for recording to start
            await asyncio.sleep(2)

            # Check if recording started
            recording_text = await self.page.evaluate('document.querySelector("#record-button").textContent')
            print(f"📝 Recording button text: {recording_text}")

            if "Stop" in recording_text or "⏹️" in recording_text:
                print("✅ Recording appears to have started")
                self.test_results['recording_start'] = True

                # Wait for a short recording (5 seconds)
                print("⏳ Recording for 5 seconds...")
                await asyncio.sleep(5)

                # Stop recording
                print("⏹️ Stopping recording...")
                await record_button.click()

                # Wait for processing
                print("⏳ Processing recording...")
                await asyncio.sleep(3)

                # Check for transcription result
                transcription_result = await self.page.querySelector('#transcription-result')
                if transcription_result:
                    result_text = await self.page.evaluate('document.querySelector("#transcription-result").textContent')
                    print(f"📝 Transcription result: {result_text}")
                    self.test_results['transcription'] = True
                    return True
                else:
                    print("❌ No transcription result found")
                    return False
            else:
                print("❌ Recording did not start properly")
                return False

        except Exception as e:
            print(f"❌ Recording workflow test failed: {e}")
            self.test_results['errors'].append(f"Recording workflow test failed: {e}")
            return False

    async def monitor_network_requests(self):
        """Monitor network requests to check for transcription API calls."""
        requests_made = []

        def log_request(request):
            if 'transcribe_audio' in request.url:
                requests_made.append({
                    'url': request.url,
                    'method': request.method,
                    'timestamp': asyncio.get_event_loop().time()
                })
                print(f"📡 Audio transcription request: {request.method} {request.url}")

        def log_response(response):
            if 'transcribe_audio' in response.url:
                print(f"📡 Audio transcription response: {response.status}")

        await self.page.setRequestInterception(True)

        self.page.on('request', log_request)
        self.page.on('response', log_response)

        return requests_made

    async def run_tests(self):
        """Run all tests."""
        print("🧪 Starting Audio Recording Browser Tests")
        print("=" * 50)

        try:
            # Setup
            if not await self.setup_browser():
                return self.test_results

            # Start monitoring network requests
            await self.monitor_network_requests()

            # Navigate to site
            if not await self.navigate_to_site():
                return self.test_results

            # Check authentication
            if not await self.check_authentication():
                return self.test_results

            # Check audio interface
            if not await self.check_audio_interface():
                return self.test_results

            # Test recording workflow
            await self.test_recording_workflow()

        except Exception as e:
            print(f"❌ Test execution failed: {e}")
            self.test_results['errors'].append(f"Test execution failed: {e}")

        finally:
            # Cleanup
            if self.browser:
                print("🧹 Closing browser...")
                await self.browser.close()

        return self.test_results

    def print_results(self):
        """Print test results."""
        print("\n" + "=" * 50)
        print("🧪 TEST RESULTS SUMMARY")
        print("=" * 50)

        for test, result in self.test_results.items():
            if test != 'errors':
                status = "✅ PASS" if result else "❌ FAIL"
                print(f"{test.replace('_', ' ').title()}: {status}")

        if self.test_results['errors']:
            print("\n❌ ERRORS ENCOUNTERED:")
            for error in self.test_results['errors']:
                print(f"  • {error}")

        # Overall assessment
        passed_tests = sum(1 for result in self.test_results.values()
                          if isinstance(result, bool) and result)
        total_tests = len([result for result in self.test_results.values()
                          if isinstance(result, bool)])

        print(f"\n📊 Overall: {passed_tests}/{total_tests} tests passed")

        if passed_tests == total_tests:
            print("🎉 All tests passed! Audio recording functionality is working correctly.")
        elif passed_tests >= total_tests - 1:
            print("⚠️ Most tests passed. Minor issues detected.")
        else:
            print("❌ Multiple test failures. Audio recording functionality needs attention.")

async def main():
    """Main test execution."""
    tester = AudioRecordingTester()
    results = await tester.run_tests()
    tester.print_results()

    return results

if __name__ == "__main__":
    print("🎤 Audio Recording Browser Test")
    print("This test will:")
    print("1. Launch a browser and navigate to crypto.zhivko.eu")
    print("2. Check authentication status")
    print("3. Verify audio recording interface")
    print("4. Test the complete recording workflow")
    print("5. Monitor network requests for transcription API calls")
    print()

    try:
        results = asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️ Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
