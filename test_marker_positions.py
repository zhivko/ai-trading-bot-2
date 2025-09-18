#!/usr/bin/env python3
"""
Test script to show YouTube marker positions and debug information
"""

import asyncio
from youtube_chart_markers import get_youtube_markers
from datetime import datetime

async def test_marker_positions():
    """Test and display marker positions for debugging"""
    print("🎯 Testing YouTube Marker Positions")
    print("=" * 50)

    # Test with BTCUSDT
    symbol = "BTCUSDT"
    print(f"\n📊 Getting markers for {symbol}...")

    markers = await get_youtube_markers(symbol, limit=5)

    if markers and markers.get("x"):
        print(f"✅ Found {len(markers['x'])} markers")
        print("\n📍 Marker Positions:")

        for i, (x, y, text) in enumerate(zip(markers["x"], markers["y"], markers["text"])):
            # Convert timestamp back to readable date
            timestamp_ms = x
            readable_date = datetime.fromtimestamp(timestamp_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')

            print(f"  {i+1}. {readable_date} | Price: {y:.2f} | Title: {text[:40]}...")

        print("\n📈 Position Summary:")
        print(f"  X-axis range: {datetime.fromtimestamp(min(markers['x']) / 1000).strftime('%Y-%m-%d %H:%M:%S')} to {datetime.fromtimestamp(max(markers['x']) / 1000).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Y-axis range: {min(markers['y']):.2f} to {max(markers['y']):.2f}")

        print("\n💡 How markers appear on chart:")
        print("  - X position: Based on video publish date/time")
        print("  - Y position: Based on current/live price + 2%")
        print("  - Shape: Red diamond symbols")
        print("  - Hover: Shows video title, publish date, and excerpt")

    else:
        print("❌ No markers found or error occurred")

    print("\n🔧 Debug Commands:")
    print("  In browser console:")
    print("    debugYouTubeMarkers()  // Show marker stats")
    print("    refreshYouTubeMarkers() // Force refresh markers")
    print("    toggleYouTubeMarkers()  // Toggle on/off")

if __name__ == "__main__":
    asyncio.run(test_marker_positions())
