"""
YouTube Monitor for Aaron Dishner's Crypto Channel
Monitors for new videos, downloads transcripts (with proxy support), generates excerpts with LM Studio, and stores in Redis
"""

import os
import json
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import redis.asyncio as redis
from config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD, YOUTUBE_API_KEY
from logging_config import logger
import subprocess
import sys

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("YouTube Monitor: Environment variables loaded from .env file")
except ImportError:
    print("⚠️ YouTube Monitor: python-dotenv not installed. Environment variables must be set manually.")

class YouTubeMonitor:
    def __init__(self, channel_handle: str = None):
        # Use configuration system for flexibility
        from youtube_config import config

        # Use provided handle or default from config
        if channel_handle:
            self.channel_handle = channel_handle
        else:
            # Use first channel from config as default
            channels = config.get_channels()
            self.channel_handle = channels[0] if channels else "@MooninPapa"

        self.channel_id = None  # Will be resolved dynamically
        self.api_key = os.getenv("YOUTUBE_API_KEY")
        self.redis_client = None
        self.youtube = None  # YouTube API service object
        self.last_check_time = None
        self.check_interval = 300  # 5 minutes

        # Configuration settings
        self.enable_transcript_processing = config.enable_transcript_processing
        self.enable_ai_excerpts = config.enable_ai_excerpts
        self.lm_studio_url = config.lm_studio_url
        self.transcript_delay = config.transcript_delay

        # Proxy settings
        self.use_proxy = config.use_proxy
        self.proxy_url = config.proxy_url
        self.proxy_username = config.proxy_username
        self.proxy_password = config.proxy_password

    async def init_redis(self):
        """Initialize Redis connection"""
        try:
            self.redis_client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                password=REDIS_PASSWORD,
                decode_responses=True
            )
            await self.redis_client.ping()
            logger.info("YouTube Monitor: Redis connection established")
        except Exception as e:
            logger.error(f"YouTube Monitor: Failed to connect to Redis: {e}")
            raise

    async def resolve_channel_handle(self) -> bool:
        """Resolve channel handle to channel ID dynamically"""
        if not self.api_key:
            logger.error("YouTube Monitor: YOUTUBE_API_KEY not set")
            return False

        try:
            from googleapiclient.discovery import build
            from googleapiclient.errors import HttpError

            if self.youtube is None:
                self.youtube = build('youtube', 'v3', developerKey=self.api_key)
            youtube = self.youtube

            # If it's already a channel ID (starts with UC), use it directly
            if self.channel_handle.startswith('UC') and len(self.channel_handle) == 24:
                logger.info(f"YouTube Monitor: Using channel ID directly: {self.channel_handle}")
                self.channel_id = self.channel_handle
                return True

            # If it's a handle (starts with @), search for it
            if self.channel_handle.startswith('@'):
                logger.info(f"YouTube Monitor: Resolving handle {self.channel_handle} to channel ID...")

                search_response = youtube.search().list(
                    q=self.channel_handle,
                    part='snippet',
                    type='channel',
                    maxResults=5  # Try more results
                ).execute()

                items = search_response.get('items', [])
                logger.info(f"YouTube Monitor: Search returned {len(items)} results for {self.channel_handle}")

                for i, item in enumerate(items):
                    channel_id = item['snippet']['channelId']
                    channel_title = item['snippet']['title']
                    logger.info(f"YouTube Monitor: Result {i+1}: {channel_title} (ID: {channel_id})")

                    # Check if this looks like the right channel
                    if 'moonin' in channel_title.lower() or 'dishner' in channel_title.lower():
                        logger.info(f"YouTube Monitor: Found matching channel: {channel_title}")
                        self.channel_id = channel_id
                        return True

                # If no exact match found, use the first result
                if items:
                    first_channel_id = items[0]['snippet']['channelId']
                    first_channel_title = items[0]['snippet']['title']
                    logger.info(f"YouTube Monitor: Using first result: {first_channel_title} ({first_channel_id})")
                    self.channel_id = first_channel_id
                    return True
                else:
                    logger.error(f"YouTube Monitor: No channels found for handle {self.channel_handle}")
                    return False

            # If it's a username, try to find it
            else:
                logger.info(f"YouTube Monitor: Resolving username {self.channel_handle} to channel ID...")

                search_response = youtube.search().list(
                    q=self.channel_handle,
                    part='snippet',
                    type='channel',
                    maxResults=1
                ).execute()

                if search_response.get('items'):
                    found_channel_id = search_response['items'][0]['snippet']['channelId']
                    channel_title = search_response['items'][0]['snippet']['title']
                    logger.info(f"YouTube Monitor: Resolved {self.channel_handle} to {found_channel_id} ({channel_title})")
                    self.channel_id = found_channel_id
                    return True
                else:
                    logger.error(f"YouTube Monitor: Could not find channel for username {self.channel_handle}")
                    return False

        except HttpError as e:
            logger.error(f"YouTube Monitor: Google API error resolving channel: {e}")
            # If we get an API error, try to use a known working channel ID as fallback
            if self.channel_handle == "@MooninPapa":
                logger.info("YouTube Monitor: Using known fallback channel ID for MooninPapa")
                self.channel_id = "UC1BCNwXAHuCWKzRlwv72DHQ"
                return True
            return False
        except Exception as e:
            logger.error(f"YouTube Monitor: Error resolving channel handle: {e}")
            # Fallback for known channels
            if self.channel_handle == "@MooninPapa":
                logger.info("YouTube Monitor: Using fallback channel ID for MooninPapa")
                self.channel_id = "UC1BCNwXAHuCWKzRlwv72DHQ"
                return True
            return False

    async def get_channel_videos(self, max_results: int = 10) -> List[Dict]:
        """Fetch recent videos from the channel using official Google API client"""
        if not self.api_key:
            logger.error("YouTube Monitor: YOUTUBE_API_KEY not set")
            return []

        # Ensure we have a resolved channel ID
        if not self.channel_id:
            logger.info("YouTube Monitor: Channel ID not resolved, attempting to resolve...")
            if not await self.resolve_channel_handle():
                logger.error("YouTube Monitor: Failed to resolve channel handle")
                return []

        try:
            # Import Google API client
            from googleapiclient.discovery import build
            from googleapiclient.errors import HttpError

            # Build the YouTube service
            if self.youtube is None:
                self.youtube = build('youtube', 'v3', developerKey=self.api_key)
            youtube = self.youtube

            logger.info(f"YouTube Monitor: Searching for videos in channel {self.channel_id} (handle: {self.channel_handle})")

            # First, let's check if the channel actually has videos by getting channel stats
            try:
                if self.channel_id:
                    channel_response = youtube.channels().list(
                        part='statistics',
                        id=self.channel_id
                    ).execute()

                    if channel_response.get('items'):
                        video_count = channel_response['items'][0]['statistics'].get('videoCount', '0')
                        logger.info(f"YouTube Monitor: Channel has {video_count} total videos")
                    else:
                        logger.warning("YouTube Monitor: Could not get channel statistics")
                else:
                    logger.warning("YouTube Monitor: No channel_id available for statistics")
            except Exception as e:
                logger.warning(f"YouTube Monitor: Error getting channel stats: {e}")

            # Try multiple search approaches
            videos = []

            # Method 1: Search by channel ID
            logger.info("YouTube Monitor: Trying search method 1 (channelId)...")
            try:
                search_response = youtube.search().list(
                    channelId=self.channel_id,
                    part='snippet',
                    order='date',
                    maxResults=max_results,
                    type='video'
                ).execute()

                items = search_response.get("items", [])
                logger.info(f"YouTube Monitor: Method 1 found {len(items)} videos")

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
                logger.error(f"YouTube Monitor: Method 1 failed: {e}")

            # Method 2: If no videos found, try searching by channel handle
            if not videos and self.channel_handle:
                logger.info("YouTube Monitor: Trying search method 2 (channel handle search)...")
                try:
                    search_response = youtube.search().list(
                        q=self.channel_handle,
                        part='snippet',
                        order='date',
                        maxResults=max_results,
                        type='video'
                    ).execute()

                    items = search_response.get("items", [])
                    logger.info(f"YouTube Monitor: Method 2 found {len(items)} videos")

                    for item in items:
                        if item.get("id", {}).get("kind") == "youtube#video":
                            # If we have a channel_id, filter by it; otherwise accept all
                            if self.channel_id and item.get("snippet", {}).get("channelId") == self.channel_id:
                                video_info = {
                                    "video_id": item["id"]["videoId"],
                                    "title": item["snippet"]["title"],
                                    "description": item["snippet"]["description"],
                                    "published_at": item["snippet"]["publishedAt"],
                                    "thumbnail": item["snippet"]["thumbnails"]["default"]["url"]
                                }
                                videos.append(video_info)
                            elif not self.channel_id:
                                # If no channel_id filter, accept all videos from search
                                video_info = {
                                    "video_id": item["id"]["videoId"],
                                    "title": item["snippet"]["title"],
                                    "description": item["snippet"]["description"],
                                    "published_at": item["snippet"]["publishedAt"],
                                    "thumbnail": item["snippet"]["thumbnails"]["default"]["url"]
                                }
                                videos.append(video_info)

                except Exception as e:
                    logger.error(f"YouTube Monitor: Method 2 failed: {e}")

            # Method 3: Try playlist items (uploads playlist)
            if not videos and self.channel_id:
                logger.info("YouTube Monitor: Trying search method 3 (uploads playlist)...")
                try:
                    # Get the uploads playlist ID from channel
                    channel_response = youtube.channels().list(
                        part='contentDetails',
                        id=self.channel_id
                    ).execute()

                    if channel_response.get('items'):
                        uploads_playlist_id = channel_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']

                        # Get videos from uploads playlist
                        playlist_response = youtube.playlistItems().list(
                            playlistId=uploads_playlist_id,
                            part='snippet',
                            maxResults=max_results
                        ).execute()

                        items = playlist_response.get("items", [])
                        logger.info(f"YouTube Monitor: Method 3 found {len(items)} videos")

                        for item in items:
                            video_info = {
                                "video_id": item["snippet"]["resourceId"]["videoId"],
                                "title": item["snippet"]["title"],
                                "description": item["snippet"]["description"],
                                "published_at": item["snippet"]["publishedAt"],
                                "thumbnail": item["snippet"]["thumbnails"]["default"]["url"]
                            }
                            videos.append(video_info)

                except Exception as e:
                    logger.error(f"YouTube Monitor: Method 3 failed: {e}")

            logger.info(f"YouTube Monitor: Total videos found across all methods: {len(videos)}")

            # Log first few videos for debugging
            for i, video in enumerate(videos[:3]):
                logger.info(f"YouTube Monitor: Video {i+1}: {video['title'][:50]}...")

            return videos

        except HttpError as e:
            logger.error(f"YouTube Monitor: Google API error: {e}")
            return []
        except Exception as e:
            logger.error(f"YouTube Monitor: Error fetching videos: {e}")
            return []

    async def get_video_transcript(self, video_id: str) -> Optional[str]:
        """Download transcript for a video using youtube-transcript-api with proper Session approach"""
        # Check if transcript processing is enabled
        if not self.enable_transcript_processing:
            logger.info(f"YouTube Monitor: Transcript processing disabled, skipping {video_id}")
            return "Transcript processing disabled"

        try:
            # Import here to avoid dependency issues if not installed
            from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
            from youtube_transcript_api._errors import RequestBlocked
            from requests import Session

            # Add configurable delay to avoid rate limiting
            await asyncio.sleep(self.transcript_delay)

            # Create a proper Session object as per YouTubeTranscriptApi documentation
            http_client = Session()

            # Set custom headers to mimic a real browser
            http_client.headers.update({
                "Accept-Encoding": "gzip, deflate",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1"
            })

            # Set up proxy if enabled
            if self.use_proxy and self.proxy_url and self.proxy_username and self.proxy_password:
                # Create rotating proxy configuration
                proxy_config = {
                    "http": f"http://{self.proxy_username}:{self.proxy_password}@{self.proxy_url}/",
                    "https": f"http://{self.proxy_username}:{self.proxy_password}@{self.proxy_url}/"
                }

                http_client.proxies.update(proxy_config)
                logger.info(f"YouTube Monitor: Using rotating Webshare proxy {self.proxy_url} for transcript {video_id}")
            else:
                logger.info(f"YouTube Monitor: Downloading transcript for {video_id} without proxy")

            try:
                # Create YouTubeTranscriptApi instance with our custom session
                yt = YouTubeTranscriptApi(http_client=http_client)

                # Get list of available transcripts
                transcript_list = yt.list(video_id)

                # Try to get English transcript first, then any available
                transcript = None
                try:
                    # Try English first
                    transcript = transcript_list.find_transcript(['en'])
                except:
                    # If English not available, get the first available
                    if transcript_list:
                        transcript = list(transcript_list)[0]

                if transcript:
                    # Fetch the actual transcript data
                    transcript_data = transcript.fetch()
                    text = ' '.join([entry['text'] for entry in transcript_data])

                    logger.info(f"YouTube Monitor: Downloaded transcript for video {video_id} ({len(text)} chars)")
                    return text
                else:
                    logger.warning(f"YouTube Monitor: No transcripts available for video {video_id}")
                    return None

            finally:
                # Always close the session
                http_client.close()

        except RequestBlocked as e:
            logger.warning(f"YouTube Monitor: IP blocked for transcript {video_id}: {e}")
            if self.use_proxy:
                logger.warning("YouTube Monitor: Webshare proxy might be blocked too, consider rotating proxy")
            else:
                logger.warning("YouTube Monitor: Consider enabling proxy with USE_YOUTUBE_PROXY=true")
            return None
        except TranscriptsDisabled as e:
            logger.warning(f"YouTube Monitor: Transcripts disabled for video {video_id}: {e}")
            return None
        except NoTranscriptFound as e:
            logger.warning(f"YouTube Monitor: No transcript found for video {video_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"YouTube Monitor: Failed to get transcript for {video_id}: {e}")
            return None

    async def generate_excerpt_with_lm_studio(self, transcript: str, video_title: str) -> Optional[str]:
        """Generate excerpt using local LM Studio with fallback"""
        # Check if AI excerpts are enabled
        if not self.enable_ai_excerpts:
            logger.info("YouTube Monitor: AI excerpts disabled, using fallback")
            return self._generate_fallback_excerpt(transcript, video_title)

        try:
            prompt = f"""
Please analyze this YouTube video description from "{video_title}" and create a concise excerpt (2-3 sentences) highlighting the key crypto trading insights, market predictions, or important information mentioned. Focus on actionable insights for traders.

Video Description:
{transcript[:4000]}  # Limit description length

Excerpt:"""

            # Call LM Studio API (OpenAI-compatible)
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.lm_studio_url}/v1/chat/completions",
                    json={
                        "model": "local-model",  # LM Studio uses this for local models
                        "messages": [
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        "temperature": 0.7,
                        "max_tokens": 300,
                        "stream": False
                    }
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        excerpt = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                        logger.info(f"YouTube Monitor: Generated excerpt with LM Studio ({len(excerpt)} chars)")
                        return excerpt
                    else:
                        logger.warning(f"YouTube Monitor: LM Studio API returned status {response.status}")
                        return self._generate_fallback_excerpt(transcript, video_title)

        except aiohttp.ClientConnectorError as e:
            logger.warning(f"YouTube Monitor: LM Studio not available: {e}")
            return self._generate_fallback_excerpt(transcript, video_title)
        except Exception as e:
            logger.error(f"YouTube Monitor: Error generating excerpt with LM Studio: {e}")
            return self._generate_fallback_excerpt(transcript, video_title)

    def _generate_fallback_excerpt(self, transcript: str, video_title: str) -> Optional[str]:
        """Generate a simple fallback excerpt when AI is not available"""
        try:
            # Extract first 200 characters as a simple summary
            if len(transcript) > 200:
                excerpt = transcript[:200] + "..."
            else:
                excerpt = transcript

            logger.info(f"YouTube Monitor: Generated fallback excerpt ({len(excerpt)} chars)")
            return f"Fallback excerpt: {excerpt}"
        except Exception as e:
            logger.error(f"YouTube Monitor: Error generating fallback excerpt: {e}")
            return "Excerpt generation failed"

    async def store_video_data(self, video_data: Dict):
        """Store video data in Redis"""
        try:
            key = f"youtube_video:{video_data['video_id']}"
            await self.redis_client.set(key, json.dumps(video_data))

            # Also store in a sorted set for time-based queries
            timestamp = datetime.fromisoformat(video_data['published_at'].replace('Z', '+00:00')).timestamp()
            await self.redis_client.zadd("youtube_videos", {video_data['video_id']: timestamp})

            logger.info(f"YouTube Monitor: Stored video data for {video_data['video_id']}")
        except Exception as e:
            logger.error(f"YouTube Monitor: Error storing video data: {e}")

    async def is_video_processed(self, video_id: str) -> bool:
        """Check if video has already been processed"""
        try:
            key = f"youtube_video:{video_id}"
            exists = await self.redis_client.exists(key)
            return exists
        except Exception as e:
            logger.error(f"YouTube Monitor: Error checking if video processed: {e}")
            return False

    async def process_new_videos(self):
        """Main processing function"""
        logger.info("YouTube Monitor: Starting video processing...")

        # Resolve channel handle to ID if not already done
        if not self.channel_id:
            logger.info("YouTube Monitor: Resolving channel handle...")
            if not await self.resolve_channel_handle():
                logger.error("YouTube Monitor: Failed to resolve channel handle, skipping processing")
                return

        # Get recent videos
        videos = await self.get_channel_videos()

        if not videos:
            logger.warning("YouTube Monitor: No videos found")
            return

        new_videos_count = 0

        for video in videos:
            video_id = video['video_id']

            # Skip if already processed
            if await self.is_video_processed(video_id):
                logger.debug(f"YouTube Monitor: Video {video_id} already processed, skipping")
                continue

            logger.info(f"YouTube Monitor: Processing new video: {video['title']}")

            # Use video description instead of transcript (much more reliable)
            transcript = video.get('description', f"Video: {video['title']}")
            if not transcript or len(transcript.strip()) < 10:
                transcript = f"Video: {video['title']} - No description available"
            logger.info(f"YouTube Monitor: Using video description for {video_id} ({len(transcript)} chars)")

            # Generate excerpt
            excerpt = await self.generate_excerpt_with_lm_studio(transcript, video['title'])
            if not excerpt:
                logger.warning(f"YouTube Monitor: Failed to generate excerpt for {video_id}")
                continue

            # Store video data
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

            await self.store_video_data(video_data)
            new_videos_count += 1

            logger.info(f"YouTube Monitor: Successfully processed video {video_id}")

        logger.info(f"YouTube Monitor: Processing complete. Processed {new_videos_count} new videos")

    async def run_monitoring_loop(self):
        """Main monitoring loop"""
        logger.info("YouTube Monitor: Starting monitoring loop...")

        while True:
            try:
                await self.process_new_videos()
                self.last_check_time = datetime.now()
            except Exception as e:
                logger.error(f"YouTube Monitor: Error in monitoring loop: {e}")

            # Wait before next check
            await asyncio.sleep(self.check_interval)

async def start_youtube_monitor():
    """Start the YouTube monitoring service"""
    monitor = YouTubeMonitor()
    await monitor.init_redis()

    # Resolve channel handle to ID at startup
    logger.info("YouTube Monitor: Resolving channel handle at startup...")
    if not await monitor.resolve_channel_handle():
        logger.error("YouTube Monitor: Failed to resolve channel handle, cannot start monitoring")
        return

    logger.info(f"YouTube Monitor: Successfully resolved channel {monitor.channel_handle} to {monitor.channel_id}")
    await monitor.run_monitoring_loop()

if __name__ == "__main__":
    # For testing
    asyncio.run(start_youtube_monitor())
