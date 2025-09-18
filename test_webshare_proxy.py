#!/usr/bin/env python3
"""
Test Webshare Proxy Connection
Verifies that the Webshare proxy is working correctly
"""

import requests
import os
from youtube_config import config

def test_proxy_connection():
    """Test basic proxy connectivity"""
    print("🧪 Testing Webshare Proxy Connection")
    print("=" * 40)

    if not config.use_proxy:
        print("❌ Proxy is disabled in configuration")
        return False

    # Test proxy configuration
    proxy_config = {
        "http": f"http://{config.proxy_username}:{config.proxy_password}@{config.proxy_url}/",
        "https": f"http://{config.proxy_username}:{config.proxy_password}@{config.proxy_url}/"
    }

    print(f"🔗 Proxy URL: {config.proxy_url}")
    print(f"👤 Username: {config.proxy_username}")
    print(f"🔑 Password: {'*' * len(config.proxy_password)}")

    try:
        # Test 1: Basic connectivity
        print("\n📡 Test 1: Basic connectivity to httpbin.org")
        response = requests.get(
            "https://httpbin.org/ip",
            proxies=proxy_config,
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            print(f"✅ Success! Your IP: {data.get('origin', 'Unknown')}")
        else:
            print(f"❌ Failed with status code: {response.status_code}")
            return False

        # Test 2: YouTube connectivity
        print("\n📺 Test 2: YouTube connectivity")
        response = requests.get(
            "https://www.youtube.com",
            proxies=proxy_config,
            timeout=15
        )

        if response.status_code == 200:
            print("✅ YouTube is accessible through proxy")
        else:
            print(f"⚠️  YouTube returned status: {response.status_code}")

        # Test 3: Transcript API simulation
        print("\n🎭 Test 3: Transcript API simulation")
        # This simulates what the youtube-transcript-api does
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        response = requests.get(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",  # Test video
            proxies=proxy_config,
            headers=headers,
            timeout=15
        )

        if response.status_code == 200:
            print("✅ YouTube video pages are accessible")
            print("✅ Proxy is working correctly!")
            return True
        else:
            print(f"⚠️  YouTube video page returned: {response.status_code}")
            return False

    except requests.exceptions.ProxyError as e:
        print(f"❌ Proxy Error: {e}")
        print("💡 Check your proxy credentials and server")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"❌ Connection Error: {e}")
        print("💡 Check if proxy server is running")
        return False
    except requests.exceptions.Timeout as e:
        print(f"❌ Timeout Error: {e}")
        print("💡 Proxy might be slow, try again")
        return False
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
        return False

def test_youtube_transcript_api():
    """Test the actual YouTube transcript API with proxy"""
    print("\n🎬 Test 4: YouTube Transcript API with Proxy")

    try:
        import requests
        from youtube_transcript_api import YouTubeTranscriptApi

        # Set up proxy like in the main code
        proxy_config = {
            "http": f"http://{config.proxy_username}:{config.proxy_password}@{config.proxy_url}/",
            "https": f"http://{config.proxy_username}:{config.proxy_password}@{config.proxy_url}/"
        }

        # Monkey patch requests
        original_get = requests.get
        original_post = requests.post

        def proxied_get(url, **kwargs):
            kwargs['proxies'] = proxy_config
            return original_get(url, **kwargs)

        def proxied_post(url, **kwargs):
            kwargs['proxies'] = proxy_config
            return original_post(url, **kwargs)

        requests.get = proxied_get
        requests.post = proxied_post

        try:
            # Test with a known video that has transcripts
            test_video_id = "dQw4w9WgXcQ"  # Rick Roll - usually has transcripts

            yt = YouTubeTranscriptApi()
            transcript_list = yt.list(test_video_id)

            if transcript_list:
                print(f"✅ Transcript API working! Found {len(list(transcript_list))} transcript(s)")
                return True
            else:
                print("⚠️  No transcripts found for test video")
                return False

        finally:
            # Restore original methods
            requests.get = original_get
            requests.post = original_post

    except Exception as e:
        print(f"❌ Transcript API Error: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Webshare Proxy Test Suite")
    print("=" * 50)

    # Run tests
    proxy_ok = test_proxy_connection()
    transcript_ok = test_youtube_transcript_api() if proxy_ok else False

    print("\n" + "=" * 50)
    print("📊 TEST RESULTS:")
    print(f"🔗 Proxy Connection: {'✅ PASS' if proxy_ok else '❌ FAIL'}")
    print(f"🎬 Transcript API: {'✅ PASS' if transcript_ok else '❌ FAIL'}")

    if proxy_ok and transcript_ok:
        print("\n🎉 ALL TESTS PASSED! Your Webshare proxy is ready!")
        print("🚀 You can now run the YouTube monitor with transcript support.")
    else:
        print("\n⚠️  Some tests failed. Check your proxy configuration.")
        print("📖 See PROXY_SETUP.md for troubleshooting tips.")
