#!/usr/bin/env python3
"""
Test script for rotating proxy functionality
"""

import requests
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_rotating_proxy():
    """Test the rotating proxy configuration"""
    print("🔄 Testing Rotating Proxy Configuration")
    print("=" * 50)

    # Get proxy configuration from environment
    proxy_url = os.getenv("YOUTUBE_PROXY_URL", "p.webshare.io:80")
    proxy_username = os.getenv("YOUTUBE_PROXY_USERNAME", "anrygkjw-rotate")
    proxy_password = os.getenv("YOUTUBE_PROXY_PASSWORD", "h85slosiudgx")

    print(f"Proxy URL: {proxy_url}")
    print(f"Username: {proxy_username}")
    print(f"Password: {'*' * len(proxy_password) if proxy_password else 'None'}")

    # Test the proxy with a simple request
    proxy_config = {
        "http": f"http://{proxy_username}:{proxy_password}@{proxy_url}/",
        "https": f"http://{proxy_username}:{proxy_password}@{proxy_url}/"
    }

    print(f"\nProxy Configuration:")
    print(f"  HTTP: {proxy_config['http']}")
    print(f"  HTTPS: {proxy_config['https']}")

    try:
        print("\n🌐 Testing proxy connection...")
        response = requests.get("https://httpbin.org/ip", proxies=proxy_config, timeout=10)
        print("✅ Proxy test successful!")
        print(f"Response status: {response.status_code}")
        print(f"Response: {response.json()}")

        # Test with ipv4.webshare.io as in user's example
        print("\n🌐 Testing ipv4.webshare.io...")
        ipv4_response = requests.get("https://ipv4.webshare.io/", proxies=proxy_config, timeout=10)
        print("✅ IPv4 test successful!")
        print(f"Response: {ipv4_response.text[:200]}...")

    except requests.exceptions.RequestException as e:
        print(f"❌ Proxy test failed: {e}")
        return False

    print("\n✅ Rotating proxy configuration is working!")
    return True

if __name__ == "__main__":
    test_rotating_proxy()
