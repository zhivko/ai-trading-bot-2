#!/usr/bin/env python3
"""
Test YouTube API connection and channel information
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_youtube_api():
    """Test YouTube API connection"""
    api_key = os.getenv("YOUTUBE_API_KEY")

    if not api_key:
        print("❌ YOUTUBE_API_KEY not found in environment")
        return False

    print(f"✅ API Key found: {api_key[:20]}...")

    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError

        # Build YouTube service
        youtube = build('youtube', 'v3', developerKey=api_key)
        print("✅ YouTube service built successfully")

        # Test 1: Get channel info
        print("\n🔍 Testing channel lookup...")

        # Try the channel handle (most user-friendly approach)
        channel_handle = "@MooninPapa"  # This is what users would configure

        found_channel = None
        working_channel_id = None

        # Test the handle directly
        channel_identifier = channel_handle
        print(f"   Trying: {channel_identifier}")

        try:
            if channel_identifier.startswith("@"):
                # Handle search
                search_response = youtube.search().list(
                    q=channel_identifier,
                    part='snippet',
                    type='channel',
                    maxResults=1
                ).execute()

                if search_response.get('items'):
                    found_channel_id = search_response['items'][0]['snippet']['channelId']
                    print(f"   Found channel ID from handle: {found_channel_id}")
                    channel_identifier = found_channel_id

            # Get channel info
            channel_response = youtube.channels().list(
                part='snippet,statistics',
                id=channel_identifier
            ).execute()

            if channel_response.get('items'):
                found_channel = channel_response['items'][0]
                working_channel_id = channel_identifier
                print(f"   ✅ Channel found with ID: {channel_identifier}")
            else:
                print(f"   ❌ No channel found for: {channel_identifier}")

        except Exception as e:
            print(f"   ❌ Error with {channel_identifier}: {e}")

        if not found_channel:
            print("❌ Could not find Aaron Dishner's channel with any identifier")
            print("💡 Possible issues:")
            print("   - Channel handle changed")
            print("   - Channel is private")
            print("   - API key restrictions")
            return False

        # Display channel info
        title = found_channel['snippet']['title']
        subscriber_count = found_channel['statistics'].get('subscriberCount', 'N/A')
        video_count = found_channel['statistics'].get('videoCount', 'N/A')

        print(f"✅ Channel found: {title}")
        print(f"   Channel ID: {working_channel_id}")
        print(f"   Subscribers: {subscriber_count}")
        print(f"   Videos: {video_count}")

        # Update the channel_id for subsequent tests
        channel_id = working_channel_id

        # Test 2: Search for videos using multiple methods
        print("\n🔍 Testing video search...")

        # First check channel statistics
        channel_stats = youtube.channels().list(
            part='statistics',
            id=channel_id
        ).execute()

        if channel_stats.get('items'):
            video_count = channel_stats['items'][0]['statistics'].get('videoCount', '0')
            print(f"📊 Channel statistics: {video_count} total videos")

        videos_found = []

        # Method 1: Direct channel search
        print("\n   Method 1: Direct channel search...")
        try:
            search_response = youtube.search().list(
                channelId=channel_id,
                part='snippet',
                order='date',
                maxResults=5,
                type='video'
            ).execute()

            items = search_response.get('items', [])
            print(f"   ✅ Found {len(items)} videos")

            for item in items:
                if item.get('id', {}).get('kind') == 'youtube#video':
                    video_id = item['id']['videoId']
                    title = item['snippet']['title']
                    published = item['snippet']['publishedAt']
                    videos_found.append((video_id, title, published))
                    print(f"      • {title[:50]}... ({video_id})")

        except Exception as e:
            print(f"   ❌ Method 1 failed: {e}")

        # Method 2: If no videos, try uploads playlist
        if not videos_found:
            print("\n   Method 2: Uploads playlist...")
            try:
                # Get uploads playlist
                channel_details = youtube.channels().list(
                    part='contentDetails',
                    id=channel_id
                ).execute()

                if channel_details.get('items'):
                    uploads_playlist = channel_details['items'][0]['contentDetails']['relatedPlaylists']['uploads']

                    playlist_items = youtube.playlistItems().list(
                        playlistId=uploads_playlist,
                        part='snippet',
                        maxResults=5
                    ).execute()

                    items = playlist_items.get('items', [])
                    print(f"   ✅ Found {len(items)} videos in uploads playlist")

                    for item in items:
                        video_id = item['snippet']['resourceId']['videoId']
                        title = item['snippet']['title']
                        published = item['snippet']['publishedAt']
                        videos_found.append((video_id, title, published))
                        print(f"      • {title[:50]}... ({video_id})")

            except Exception as e:
                print(f"   ❌ Method 2 failed: {e}")

        print(f"\n📈 Total videos found: {len(videos_found)}")

        # Test 3: Get specific video details
        if items:
            print("\n🔍 Testing video details...")
            first_video_id = items[0]['id']['videoId']
            video_response = youtube.videos().list(
                part='snippet,statistics',
                id=first_video_id
            ).execute()

            if video_response.get('items'):
                video = video_response['items'][0]
                title = video['snippet']['title']
                views = video['statistics'].get('viewCount', 'N/A')
                likes = video['statistics'].get('likeCount', 'N/A')
                print(f"✅ Video details: {title[:50]}...")
                print(f"   Views: {views}, Likes: {likes}")

        print("\n🎉 All YouTube API tests passed!")
        return True

    except HttpError as e:
        print(f"❌ YouTube API Error: {e}")
        if "referer" in str(e).lower():
            print("💡 This looks like a referrer restriction issue.")
            print("   Go to: https://console.cloud.google.com/apis/credentials")
            print("   Edit your API key and set 'Application restrictions' to 'None'")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Testing YouTube API Connection\n")
    success = test_youtube_api()
    sys.exit(0 if success else 1)
