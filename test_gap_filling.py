#!/usr/bin/env python3
"""
Test script for automatic gap filling functionality.
This script tests the gap detection and filling logic.
"""

import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta

# Add the current directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from redis_utils import detect_gaps_in_cached_data, fill_data_gaps, init_redis
from config import SUPPORTED_SYMBOLS, timeframe_config
from logging_config import logger

async def test_gap_detection():
    """Test the gap detection functionality."""
    logger.info("🧪 TESTING GAP DETECTION FUNCTIONALITY")

    try:
        # Initialize Redis connection
        await init_redis()

        # Test parameters
        symbol = "BTCUSDT"
        resolution = "1m"  # Test with 1-minute data first
        current_time = datetime.now(timezone.utc)
        end_ts = int(current_time.timestamp())
        start_ts = end_ts - (2 * 3600)  # Last 2 hours

        logger.info(f"🔍 Testing gap detection for {symbol} {resolution}")
        logger.info(f"   Time range: {datetime.fromtimestamp(start_ts, timezone.utc)} to {datetime.fromtimestamp(end_ts, timezone.utc)}")

        # Detect gaps
        gaps = await detect_gaps_in_cached_data(symbol, resolution, start_ts, end_ts)

        if gaps:
            logger.info(f"✅ Gap detection working! Found {len(gaps)} gaps:")
            for i, gap in enumerate(gaps[:3]):  # Show first 3 gaps
                logger.info(f"   Gap {i+1}: {datetime.fromtimestamp(gap['from_ts'], timezone.utc)} to {datetime.fromtimestamp(gap['to_ts'], timezone.utc)} ({gap['missing_points']} missing points)")
        else:
            logger.info("ℹ️  No gaps detected in the test range")

        return gaps

    except Exception as e:
        logger.error(f"❌ Error during gap detection test: {e}", exc_info=True)
        return []

async def test_gap_filling(gaps):
    """Test the gap filling functionality."""
    if not gaps:
        logger.info("ℹ️  No gaps to test filling")
        return

    logger.info("🧪 TESTING GAP FILLING FUNCTIONALITY")
    logger.info(f"🔧 Attempting to fill {len(gaps)} detected gaps")

    try:
        await fill_data_gaps(gaps)
        logger.info("✅ Gap filling test completed")
    except Exception as e:
        logger.error(f"❌ Error during gap filling test: {e}", exc_info=True)

async def test_multiple_resolutions():
    """Test gap detection across multiple resolutions."""
    logger.info("🧪 TESTING MULTIPLE RESOLUTIONS")

    await init_redis()

    resolutions_to_test = ["1m", "5m", "1h"]
    current_time = datetime.now(timezone.utc)
    end_ts = int(current_time.timestamp())
    start_ts = end_ts - (24 * 3600)  # Last 24 hours

    for resolution in resolutions_to_test:
        logger.info(f"🔍 Testing {resolution} resolution...")
        try:
            gaps = await detect_gaps_in_cached_data("BTCUSDT", resolution, start_ts, end_ts)
            if gaps:
                logger.info(f"   Found {len(gaps)} gaps in {resolution} data")
            else:
                logger.info(f"   No gaps in {resolution} data")
        except Exception as e:
            logger.error(f"   Error testing {resolution}: {e}")

async def main():
    """Main test function."""
    logger.info("🚀 STARTING GAP FILLING TESTS")

    try:
        # Test 1: Basic gap detection
        logger.info("\n" + "="*50)
        logger.info("TEST 1: Basic Gap Detection")
        logger.info("="*50)
        gaps = await test_gap_detection()

        # Test 2: Gap filling
        logger.info("\n" + "="*50)
        logger.info("TEST 2: Gap Filling")
        logger.info("="*50)
        await test_gap_filling(gaps)

        # Test 3: Multiple resolutions
        logger.info("\n" + "="*50)
        logger.info("TEST 3: Multiple Resolutions")
        logger.info("="*50)
        await test_multiple_resolutions()

        logger.info("\n" + "="*50)
        logger.info("🎉 ALL TESTS COMPLETED")
        logger.info("="*50)

    except Exception as e:
        logger.error(f"💥 CRITICAL ERROR during testing: {e}", exc_info=True)
        return 1

    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
