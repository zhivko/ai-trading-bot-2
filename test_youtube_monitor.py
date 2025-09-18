#!/usr/bin/env python3
"""
Test script for YouTube Monitor functionality
"""

import asyncio
import os
from youtube_monitor import YouTubeMonitor
from youtube_chart_markers import YouTubeChartMarkers

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✅ Environment variables loaded from .env file")
except ImportError:
    print("⚠️ python-dotenv not installed. Environment variables must be set manually.")
    print("Install with: pip install python-dotenv")

async def test_youtube_monitor():
    """Test the YouTube monitor functionality"""
    print("🧪 Testing YouTube Monitor...")

    # Check if API key is available
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        print("❌ YOUTUBE_API_KEY not found in environment variables")
        return False

    print(f"✅ YOUTUBE_API_KEY found: {api_key[:20]}...")

    # Initialize monitor
    monitor = YouTubeMonitor()

    try:
        # Test Redis connection
        await monitor.init_redis()
        print("✅ Redis connection successful")

        # Test getting channel videos
        print("🔍 Testing channel video fetch...")
        videos = await monitor.get_channel_videos(max_results=5)

        if videos:
            print(f"✅ Found {len(videos)} videos")
            for i, video in enumerate(videos[:3]):  # Show first 3
                print(f"  {i+1}. {video['title'][:50]}...")
        else:
            print("❌ No videos found")
            return False

        # Test transcript download (first video)
        if videos:
            first_video = videos[0]
            print(f"🎙️ Testing transcript download for: {first_video['title'][:30]}...")

            transcript = await monitor.get_video_transcript(first_video['video_id'])
            if transcript:
                print(f"✅ Transcript downloaded ({len(transcript)} chars)")
                print(f"  Preview: {transcript[:100]}...")
            else:
                print("❌ Transcript download failed")
                return False

        # Test Ollama excerpt generation
        if transcript:
            print("🤖 Testing Ollama excerpt generation...")
            excerpt = await monitor.generate_excerpt_with_ollama(transcript, first_video['title'])
            if excerpt:
                print(f"✅ Excerpt generated ({len(excerpt)} chars)")
                print(f"  Excerpt: {excerpt}")
            else:
                print("❌ Excerpt generation failed")
                return False

        print("🎉 All tests passed!")
        return True

    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

async def test_chart_markers():
    """Test the chart markers functionality"""
    print("\n🧪 Testing Chart Markers...")

    try:
        markers_service = YouTubeChartMarkers()
        await markers_service.init_redis()

        # Get recent videos
        videos = await markers_service.get_recent_videos(limit=3)
        if videos:
            print(f"✅ Retrieved {len(videos)} videos from Redis")

            # Create markers
            markers = markers_service.create_chart_markers(videos)
            if markers and markers.get('x'):
                print(f"✅ Created {len(markers['x'])} chart markers")
                print(f"  Sample marker: x={markers['x'][0]}, title={markers['text'][0][:30]}...")
            else:
                print("❌ Failed to create markers")
                return False
        else:
            print("⚠️ No videos in Redis (run monitor first)")
            return True  # Not a failure, just no data yet

        return True

    except Exception as e:
        print(f"❌ Chart markers test failed: {e}")
        return False

async def main():
    """Run all tests"""
    print("🚀 Starting YouTube Monitor Tests")
    print("=" * 50)

    # Test environment variables
    print("📋 Environment Check:")
    youtube_key = os.getenv("YOUTUBE_API_KEY")
    print(f"  YOUTUBE_API_KEY: {'✅ Set' if youtube_key else '❌ Not set'}")

    # Test monitor
    monitor_success = await test_youtube_monitor()

    # Test chart markers
    markers_success = await test_chart_markers()

    # Summary
    print("\n" + "=" * 50)
    print("📊 TEST SUMMARY:")
    print(f"  Monitor Tests: {'✅ PASSED' if monitor_success else '❌ FAILED'}")
    print(f"  Chart Markers: {'✅ PASSED' if markers_success else '❌ FAILED'}")

    if monitor_success and markers_success:
        print("🎉 ALL TESTS PASSED!")
        print("\n📝 Next Steps:")
        print("  1. Run: python youtube_monitor.py (for continuous monitoring)")
        print("  2. Check API endpoints: /youtube/youtube_markers/BTCUSDT")
        print("  3. Add frontend code to display markers on charts")
    else:
        print("❌ SOME TESTS FAILED")
        print("  Check the error messages above and fix issues")

if __name__ == "__main__":
    asyncio.run(main())
