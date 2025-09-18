"""
YouTube Chart Markers
Adds markers to Plotly charts for YouTube videos with hovertips showing excerpts
"""

import json
from datetime import datetime
from typing import List, Dict, Optional
import redis.asyncio as redis
from config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD
from logging_config import logger

class YouTubeChartMarkers:
    def __init__(self):
        self.redis_client = None

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
            logger.info("YouTube Chart Markers: Redis connection established")
        except Exception as e:
            logger.error(f"YouTube Chart Markers: Failed to connect to Redis: {e}")
            raise

    async def get_recent_videos(self, limit: int = 20) -> List[Dict]:
        """Get recent YouTube videos from Redis, bootstrap if empty"""
        try:
            if not self.redis_client:
                await self.init_redis()

            # Get video IDs from sorted set (most recent first)
            video_ids = await self.redis_client.zrevrange("youtube_videos", 0, limit - 1)

            videos = []
            for video_id in video_ids:
                key = f"youtube_video:{video_id}"
                video_data = await self.redis_client.get(key)
                if video_data:
                    try:
                        video = json.loads(video_data)
                        videos.append(video)
                    except json.JSONDecodeError as e:
                        logger.error(f"YouTube Chart Markers: Error parsing video data for {video_id}: {e}")
                        continue

            logger.info(f"YouTube Chart Markers: Retrieved {len(videos)} recent videos")

            # If no videos found, bootstrap with latest 5 videos
            if len(videos) == 0:
                logger.info("YouTube Chart Markers: No videos in database, bootstrapping with latest videos...")
                await self._bootstrap_videos(5)
                # Try again after bootstrapping
                video_ids = await self.redis_client.zrevrange("youtube_videos", 0, limit - 1)
                videos = []
                for video_id in video_ids:
                    key = f"youtube_video:{video_id}"
                    video_data = await self.redis_client.get(key)
                    if video_data:
                        try:
                            video = json.loads(video_data)
                            videos.append(video)
                        except json.JSONDecodeError:
                            continue
                logger.info(f"YouTube Chart Markers: After bootstrap, retrieved {len(videos)} videos")

            return videos

        except Exception as e:
            logger.error(f"YouTube Chart Markers: Error getting recent videos: {e}")
            return []

    async def _bootstrap_videos(self, count: int = 5):
        """Bootstrap the database with latest videos - clears existing data first"""
        try:
            logger.info(f"YouTube Chart Markers: Bootstrapping with {count} latest videos...")

            # Import here to avoid circular imports
            from youtube_monitor import YouTubeMonitor

            monitor = YouTubeMonitor()
            await monitor.init_redis()

            # CLEAR EXISTING DATA FIRST
            logger.info("YouTube Chart Markers: Clearing existing YouTube data from Redis...")
            try:
                # Get all video IDs from the sorted set
                existing_video_ids = await self.redis_client.zrange("youtube_videos", 0, -1)

                # Delete individual video data
                for video_id in existing_video_ids:
                    key = f"youtube_video:{video_id}"
                    await self.redis_client.delete(key)
                    logger.info(f"YouTube Chart Markers: Deleted video data for {video_id}")

                # Clear the sorted set
                await self.redis_client.delete("youtube_videos")
                logger.info("YouTube Chart Markers: Cleared youtube_videos sorted set")

                # Also clear any other YouTube-related keys
                youtube_keys = await self.redis_client.keys("youtube:*")
                if youtube_keys:
                    await self.redis_client.delete(*youtube_keys)
                    logger.info(f"YouTube Chart Markers: Cleared {len(youtube_keys)} additional YouTube keys")

            except Exception as e:
                logger.warning(f"YouTube Chart Markers: Error clearing existing data: {e}")

            # Get latest videos from YouTube
            videos = await monitor.get_channel_videos(max_results=count)

            if not videos:
                logger.warning("YouTube Chart Markers: No videos found during bootstrap")
                return

            logger.info(f"YouTube Chart Markers: Found {len(videos)} videos to process")

            # Process each video
            processed_count = 0
            for video in videos:
                video_id = video['video_id']

                logger.info(f"YouTube Chart Markers: Processing video: {video['title'][:50]}...")

                # Get transcript
                transcript = await monitor.get_video_transcript(video_id)
                if not transcript:
                    logger.warning(f"YouTube Chart Markers: No transcript for {video_id}, skipping")
                    continue

                # Generate excerpt
                excerpt = await monitor.generate_excerpt_with_lm_studio(transcript, video['title'])
                if not excerpt:
                    logger.warning(f"YouTube Chart Markers: Failed to generate excerpt for {video_id}")
                    # Still store without excerpt
                    excerpt = "Excerpt generation failed"

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

                await monitor.store_video_data(video_data)
                processed_count += 1

                logger.info(f"YouTube Chart Markers: Successfully processed {processed_count}/{len(videos)} videos")

                # Small delay to avoid overwhelming the API
                await asyncio.sleep(1)

            logger.info(f"YouTube Chart Markers: Bootstrap complete, processed {processed_count} videos")

        except Exception as e:
            logger.error(f"YouTube Chart Markers: Error during bootstrap: {e}")

    def create_chart_markers(self, videos: List[Dict]) -> Dict:
        """Create Plotly markers for YouTube videos"""
        markers = {
            "x": [],
            "y": [],
            "text": [],
            "hovertext": [],
            "mode": "markers",
            "type": "scatter",
            "name": "YouTube Videos",
            "marker": {
                "symbol": "diamond",
                "size": 12,
                "color": "red",
                "line": {
                    "color": "white",
                    "width": 2
                }
            },
            "hovertemplate": (
                "<b>%{text}</b><br>" +
                "Published: %{customdata}<br>" +
                "<br>%{hovertext}<br>" +
                "<br><i>Click for full transcript</i><br>" +
                "<extra></extra>"
            ),
            "customdata": [],
            "video_ids": [],  # Store video IDs for click handling
            "transcripts": [],  # Store full transcripts
            "showlegend": True
        }

        for video in videos:
            try:
                # Convert published_at to timestamp for x-axis
                published_dt = datetime.fromisoformat(video['published_at'].replace('Z', '+00:00'))
                timestamp = published_dt.timestamp() * 1000  # Convert to milliseconds for Plotly

                # For y-axis, we'll place markers at a fixed position relative to the price data
                # This will be adjusted when we have the actual price data
                y_position = None  # Will be set when we know the price range

                markers["x"].append(timestamp)
                markers["y"].append(y_position)  # Placeholder, will be updated
                markers["text"].append(video['title'][:50] + "..." if len(video['title']) > 50 else video['title'])
                markers["hovertext"].append(video.get('excerpt', 'No excerpt available'))
                markers["customdata"].append(published_dt.strftime('%Y-%m-%d %H:%M:%S'))
                markers["video_ids"].append(video.get('video_id', ''))
                markers["transcripts"].append(video.get('transcript', 'No transcript available'))

            except Exception as e:
                logger.error(f"YouTube Chart Markers: Error processing video {video.get('video_id', 'unknown')}: {e}")
                continue

        logger.info(f"YouTube Chart Markers: Created {len(markers['x'])} markers with transcripts")
        return markers

    def adjust_marker_positions(self, markers: Dict, price_data: List[Dict]) -> Dict:
        """Adjust marker Y positions based on price data"""
        if not markers["x"] or not price_data:
            return markers

        try:
            # Find the price range from the candlestick data
            prices = []
            for candle in price_data:
                if 'ohlc' in candle:
                    prices.extend([candle['ohlc']['high'], candle['ohlc']['low']])

            if not prices:
                return markers

            min_price = min(prices)
            max_price = max(prices)
            price_range = max_price - min_price

            # Place markers at 80% of the price range from the bottom
            marker_y = min_price + (price_range * 0.8)

            # Set all markers to this Y position
            markers["y"] = [marker_y] * len(markers["x"])

            logger.info(f"YouTube Chart Markers: Adjusted marker positions to y={marker_y}")

        except Exception as e:
            logger.error(f"YouTube Chart Markers: Error adjusting marker positions: {e}")

        return markers

    async def get_markers_for_symbol(self, symbol: str, limit: int = 20) -> Optional[Dict]:
        """Get chart markers for a specific symbol"""
        try:
            videos = await self.get_recent_videos(limit)
            if not videos:
                return None

            markers = self.create_chart_markers(videos)

            # Adjust marker positions based on recent price data
            await self._adjust_markers_with_price_data(markers, symbol)

            return markers

        except Exception as e:
            logger.error(f"YouTube Chart Markers: Error getting markers for {symbol}: {e}")
            return None

    async def _adjust_markers_with_price_data(self, markers: Dict, symbol: str):
        """Adjust marker Y positions based on available price data from Redis"""
        if not markers["x"]:
            return

        try:
            # Try multiple sources for price data
            price_sources = [
                f"price_data:{symbol}",  # Historical price data
                f"live:{symbol}",        # Live price from Bybit
            ]

            marker_y = None

            # First, try to get live price
            live_price_key = f"live:{symbol}"
            live_price_raw = await self.redis_client.get(live_price_key)

            if live_price_raw:
                try:
                    live_price = float(live_price_raw)
                    # Place markers 2% above current live price
                    marker_y = live_price * 1.02
                    logger.info(f"YouTube Chart Markers: Using live price {live_price:.2f}, positioning markers at {marker_y:.2f}")
                except (ValueError, TypeError) as e:
                    logger.warning(f"YouTube Chart Markers: Error parsing live price: {e}")

            # If no live price, try historical data
            if marker_y is None:
                for price_key in price_sources:
                    price_data_raw = await self.redis_client.get(price_key)
                    if price_data_raw:
                        try:
                            price_data = json.loads(price_data_raw)

                            # Handle different data formats
                            prices = []
                            if isinstance(price_data, list) and price_data:
                                # Historical data format
                                for item in price_data[-20:]:  # Last 20 items
                                    if isinstance(item, dict):
                                        for field in ['close', 'c', 'price', 'high', 'h', 'low', 'l']:
                                            if field in item and item[field] is not None:
                                                try:
                                                    prices.append(float(item[field]))
                                                except (ValueError, TypeError):
                                                    continue
                                                break
                            elif isinstance(price_data, (int, float, str)):
                                # Single price value
                                try:
                                    prices = [float(price_data)]
                                except (ValueError, TypeError):
                                    continue

                            if prices:
                                avg_price = sum(prices) / len(prices)
                                marker_y = avg_price * 1.02  # 2% above average
                                logger.info(f"YouTube Chart Markers: Using historical data, positioned at {marker_y:.2f} (avg: {avg_price:.2f})")
                                break

                        except (json.JSONDecodeError, ValueError) as e:
                            logger.warning(f"YouTube Chart Markers: Error parsing price data from {price_key}: {e}")
                            continue

            # Final fallback: use default position
            if marker_y is None:
                marker_y = self._get_default_y_position(symbol)
                logger.warning(f"YouTube Chart Markers: Using default Y position: {marker_y}")

            # Set all markers to this Y position
            markers["y"] = [marker_y] * len(markers["x"])
            logger.info(f"YouTube Chart Markers: Successfully positioned {len(markers['x'])} markers at y={marker_y}")

        except Exception as e:
            logger.error(f"YouTube Chart Markers: Error adjusting marker positions: {e}")
            # Emergency fallback
            markers["y"] = [self._get_default_y_position(symbol)] * len(markers["x"])

    def _get_default_y_position(self, symbol: str) -> float:
        """Get default Y position for markers based on symbol"""
        # Default positions for common crypto symbols
        defaults = {
            "BTCUSDT": 60000,
            "ETHUSDT": 3000,
            "BNBUSDT": 300,
            "ADAUSDT": 0.5,
            "SOLUSDT": 50,
            "DOTUSDT": 8,
            "DOGEUSDT": 0.08,
            "AVAXUSDT": 20,
            "LTCUSDT": 70,
            "LINKUSDT": 12
        }

        # Extract base symbol (remove USDT)
        base_symbol = symbol.replace("USDT", "").replace("USD", "").replace("BTC", "")

        return defaults.get(symbol, defaults.get(base_symbol + "USDT", 100))  # Default to 100 if not found

# Global instance
chart_markers = YouTubeChartMarkers()

async def get_youtube_markers(symbol: str = "BTCUSDT", limit: int = 20) -> Optional[Dict]:
    """Get YouTube markers for chart display"""
    return await chart_markers.get_markers_for_symbol(symbol, limit)

# Initialize on import
async def init_chart_markers():
    """Initialize the chart markers service"""
    await chart_markers.init_redis()

if __name__ == "__main__":
    # For testing
    import asyncio
    asyncio.run(init_chart_markers())
