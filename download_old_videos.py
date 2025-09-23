import os
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from youtube_monitor import YouTubeMonitor

async def process_channel(channel_handle: str):
    """Process videos for a single channel"""
    print(f"\n📺 Processing channel: {channel_handle}")

    # Initialize YouTubeMonitor for this channel
    monitor = YouTubeMonitor(channel_handle=channel_handle)

    try:
        # Initialize Redis connection
        await monitor.init_redis()

        # Resolve channel handle to ID
        if not await monitor.resolve_channel_handle():
            print(f"❌ Failed to resolve channel handle {channel_handle}")
            return 0

        # Calculate 30 days ago (for 1 month old videos)
        thirty_days_ago = datetime.now() - timedelta(days=60)
        published_after = thirty_days_ago.isoformat() + 'Z'

        # Get videos published in the last 30 days
        videos = []
        try:
            # Method 1: Search by channel ID with date filter
            print(f"Fetching videos published after {published_after}")
            search_response = monitor.youtube.search().list(
                channelId=monitor.channel_id,
                part='snippet',
                order='date',
                maxResults=50,
                type='video',
                publishedAfter=published_after
            ).execute()

            items = search_response.get("items", [])
            print(f"✅ Found {len(items)} videos from last 60 days")

            for item in items:
                if item.get("id", {}).get("kind") == "youtube#video":
                    video_info = {
                        "video_id": item["id"]["videoId"],
                        "title": item["snippet"]["title"],
                        "description": item["snippet"]["description"],
                        "published_at": item["snippet"]["publishedAt"],
                        "thumbnail": item["snippet"]["thumbnails"]["default"]["url"]
                    }
                    videos.append(video_info)
        except Exception as e:
            print(f"Error fetching videos: {e}")
            return 0

        # Process each video
        processed_count = 0
        for video in videos:
            video_id = video['video_id']
            print(f"\n🔄 Processing video: {video['title']} (ID: {video_id})")

            # Get transcript
            transcript = await monitor.get_video_transcript(video_id)
            if not transcript:
                print(f"❌ No transcript found for {video_id}")
                continue

            # Generate excerpt
            excerpt = await monitor.generate_excerpt_with_lm_studio(transcript, video['title'])
            if not excerpt:
                print(f"❌ Failed to generate excerpt for {video_id}")
                continue

            # Store video data in Redis
            video_data = {
                "video_id": video_id,
                "title": video['title'],
                "description": video['description'],
                "published_at": video['published_at'],
                "thumbnail": video['thumbnail'],
                "transcript": transcript,
                "excerpt": excerpt,
                "processed_at": datetime.now().isoformat()
            }

            await monitor.store_video_data(video_data)
            processed_count += 1

            print(f"✅ Processed video: {video_id} - {excerpt[:100]}...")

        print(f"\n✅ Completed processing {processed_count} videos from {channel_handle}")
        return processed_count

    finally:
        # Clean up Redis connection
        if monitor.redis_client:
            await monitor.redis_client.close()
            monitor.redis_client = None

async def main():
    # Load environment variables
    load_dotenv()

    # Get channels from environment
    from youtube_config import config
    channels = config.get_channels()

    # Allow override via environment variable for single channel
    target_channel = os.getenv("DOWNLOAD_CHANNEL")

    if target_channel:
        # Process only the specified channel
        print(f"📋 Processing single channel specified by DOWNLOAD_CHANNEL: {target_channel}")
        total_processed = await process_channel(target_channel)
    else:
        # Process all channels from config
        print(f"📋 Processing all {len(channels)} channels from configuration: {channels}")

        total_processed = 0
        for channel in channels:
            channel_processed = await process_channel(channel)
            total_processed += channel_processed

    print(f"\n🎉 Total: Successfully processed {total_processed} videos from all channels (last 60 days)")
    print("🔌 All Redis connections closed")

if __name__ == "__main__":
    asyncio.run(main())
