#!/usr/bin/env python3
"""
YouTube Monitor Configuration
Easy configuration for which channels to monitor
"""

import os
from typing import List

class YouTubeConfig:
    """Configuration for YouTube monitoring"""

    def __init__(self):
        # Default channels to monitor
        self.channels_to_monitor = [
            "@MooninPapa",  # Aaron Dishner
            # Add more channels here as needed
            # "@OtherChannel",
            # "@AnotherChannel",
        ]

        # AI and processing settings
        self.enable_transcript_processing = os.getenv("ENABLE_TRANSCRIPT_PROCESSING", "true").lower() == "true"
        self.enable_ai_excerpts = os.getenv("ENABLE_AI_EXCERPTS", "true").lower() == "true"
        self.lm_studio_url = os.getenv("LM_STUDIO_URL", "http://localhost:1234")
        self.transcript_delay = int(os.getenv("TRANSCRIPT_DELAY", "5"))  # seconds between requests

        # Proxy settings for YouTube API - using rotating proxy
        self.use_proxy = os.getenv("USE_YOUTUBE_PROXY", "true").lower() == "true"  # Enable rotating proxy
        self.proxy_url = os.getenv("YOUTUBE_PROXY_URL", "p.webshare.io:80")
        self.proxy_username = os.getenv("YOUTUBE_PROXY_USERNAME", "anrygkjw-rotate")
        self.proxy_password = os.getenv("YOUTUBE_PROXY_PASSWORD", "h85slosiudgx")

        # Load from environment variables if available
        env_channels = os.getenv("YOUTUBE_CHANNELS")
        if env_channels:
            # Support comma-separated list
            self.channels_to_monitor = [ch.strip() for ch in env_channels.split(",")]
            print(f"📋 Loaded channels from environment: {self.channels_to_monitor}")

        print(f"🎛️  YouTube Config: Transcripts={'✅' if self.enable_transcript_processing else '❌'}, AI={'✅' if self.enable_ai_excerpts else '❌'}")
        print(f"🔗 LM Studio URL: {self.lm_studio_url}")

    def get_channels(self) -> List[str]:
        """Get list of channels to monitor"""
        return self.channels_to_monitor

    def add_channel(self, channel_handle: str):
        """Add a channel to monitor"""
        if channel_handle not in self.channels_to_monitor:
            self.channels_to_monitor.append(channel_handle)
            print(f"➕ Added channel: {channel_handle}")

    def remove_channel(self, channel_handle: str):
        """Remove a channel from monitoring"""
        if channel_handle in self.channels_to_monitor:
            self.channels_to_monitor.remove(channel_handle)
            print(f"➖ Removed channel: {channel_handle}")

    def list_channels(self):
        """List all configured channels"""
        print("📺 Configured YouTube Channels:")
        for i, channel in enumerate(self.channels_to_monitor, 1):
            print(f"   {i}. {channel}")

# Global configuration instance
config = YouTubeConfig()

if __name__ == "__main__":
    print("🎛️  YouTube Monitor Configuration")
    print("=" * 40)

    config.list_channels()

    print("\n💡 To add channels, use environment variable:")
    print("   export YOUTUBE_CHANNELS='@MooninPapa,@OtherChannel'")
    print("\n💡 Or modify the channels_to_monitor list in this file")
