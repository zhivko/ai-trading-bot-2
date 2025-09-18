#!/usr/bin/env python3
"""
Script to bootstrap YouTube videos with fresh transcripts
"""

import asyncio
from youtube_chart_markers import YouTubeChartMarkers

async def bootstrap_videos():
    """Bootstrap YouTube videos with fresh transcripts"""
    print("🎥 Bootstrapping YouTube Videos with Fresh Transcripts")
    print("=" * 60)

    try:
        # Initialize chart markers
        chart_markers = YouTubeChartMarkers()
        await chart_markers.init_redis()

        # Run bootstrap process
        print("🔄 Starting bootstrap process...")
        await chart_markers._bootstrap_videos(count=10)  # Bootstrap with 10 latest videos

        print("✅ Bootstrap process completed successfully!")

        # Test the results
        print("\n📊 Testing results...")
        videos = await chart_markers.get_recent_videos(limit=5)

        if videos:
            print(f"✅ Found {len(videos)} videos in database:")
            for i, video in enumerate(videos, 1):
                print(f"  {i}. {video['title'][:60]}...")
                print(f"     ID: {video['video_id']}")
                print(f"     Has transcript: {'transcript' in video and len(video['transcript']) > 0}")
                print(f"     Has excerpt: {'excerpt' in video and video['excerpt'] != 'Excerpt generation failed'}")
                print()
        else:
            print("❌ No videos found after bootstrap")

    except Exception as e:
        print(f"❌ Error during bootstrap: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(bootstrap_videos())
