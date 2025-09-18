"""
YouTube endpoints for the trading application
"""

from fastapi import APIRouter, HTTPException
from typing import Optional, Dict
import json
from datetime import datetime
from youtube_chart_markers import get_youtube_markers
from logging_config import logger

router = APIRouter()

@router.get("/youtube_markers/{symbol}")
async def get_youtube_markers_endpoint(symbol: str, limit: int = 20):
    """
    Get YouTube video markers for chart display
    """
    try:
        logger.info(f"YouTube Markers: Request for {symbol} with limit {limit}")

        markers = await get_youtube_markers(symbol, limit)

        if markers is None:
            return {
                "status": "success",
                "markers": None,
                "message": "No YouTube markers available"
            }

        return {
            "status": "success",
            "markers": markers,
            "count": len(markers.get("x", []))
        }

    except Exception as e:
        logger.error(f"YouTube Markers: Error getting markers for {symbol}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get YouTube markers: {str(e)}"
        )

@router.get("/youtube_videos")
async def get_youtube_videos_endpoint(limit: int = 10):
    """
    Get recent YouTube videos with excerpts
    """
    try:
        from youtube_chart_markers import YouTubeChartMarkers
        import asyncio

        # Initialize markers service
        markers_service = YouTubeChartMarkers()
        await markers_service.init_redis()

        # Get recent videos
        videos = await markers_service.get_recent_videos(limit)

        # Format for response
        formatted_videos = []
        for video in videos:
            formatted_videos.append({
                "video_id": video["video_id"],
                "title": video["title"],
                "published_at": video["published_at"],
                "excerpt": video.get("excerpt", "No excerpt available"),
                "thumbnail": video.get("thumbnail", ""),
                "url": f"https://www.youtube.com/watch?v={video['video_id']}"
            })

        return {
            "status": "success",
            "videos": formatted_videos,
            "count": len(formatted_videos)
        }

    except Exception as e:
        logger.error(f"YouTube Videos: Error getting videos: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get YouTube videos: {str(e)}"
        )
