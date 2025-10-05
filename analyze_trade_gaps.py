#!/usr/bin/env python3
"""
Analyze historical trade data for gaps and refetch missing data.
"""

import asyncio
import json
import os
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import sys

# Add the current directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from redis_utils import (
    get_sync_redis_connection,
    get_individual_trades,
    fetch_trades_from_ccxt,
    cache_individual_trades,
    get_sorted_set_trade_key,
    notify_clients_of_new_trade
)
from config import SUPPORTED_EXCHANGES
from logging_config import logger


class TradeGapAnalyzer:
    def __init__(self):
        self.redis = None
        self.analyzed_symbols = []

    async def initialize(self):
        """Initialize Redis connection and other resources."""
        try:
            from redis_utils import init_redis
            await init_redis()
            logger.info("✅ Redis connection initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Redis: {e}")
            raise

    def get_sync_redis(self):
        """Get synchronous Redis connection for analysis."""
        if self.redis is None:
            from redis_utils import get_sync_redis_connection
            self.redis = get_sync_redis_connection()
        return self.redis

    def get_all_trade_symbols(self) -> List[Dict[str, Any]]:
        """Get all exchange/symbol combinations that have trade data."""
        redis = self.get_sync_redis()

        logger.info("🔍 Scanning for trade keys in Redis...")

        # First, let's see what trade-related keys actually exist
        all_trade_keys = []
        total_scanned = 0

        # Scan for all possible trade-related patterns
        for key in redis.scan_iter("trade:*"):
            all_trade_keys.append(key)
            total_scanned += 1
            if total_scanned > 10000:  # Limit to prevent memory issues
                break

        logger.info(f"Scanned {len(all_trade_keys)} trade keys (limited to 10k)")

        # Categorize keys
        individual_keys = [k for k in all_trade_keys if k.startswith("trade:individual:")]
        sorted_set_keys = [k for k in all_trade_keys if k.startswith("zset:trade:")]

        logger.info(f"Individual trade keys: {len(individual_keys)}")
        logger.info(f"Sorted set keys: {len(sorted_set_keys)}")

        # Extract unique exchange/symbol combinations from individual keys
        symbol_combinations = {}
        for key in individual_keys:
            try:
                # Key format: trade:individual:{exchange}:{symbol}:{trade_id}
                parts = key.split(":")
                if len(parts) >= 5:
                    exchange = parts[2].lower()  # Normalize case
                    symbol = ":".join(parts[3:-1])  # Symbol may contain colons

                    # Skip trade_id part (last part)
                    key_for_combination = f"{exchange}:{symbol}"
                    if key_for_combination not in symbol_combinations:
                        symbol_combinations[key_for_combination] = {
                            'exchange': exchange,
                            'symbol': symbol,
                            'individual_count': 0,
                            'sorted_set_key': None
                        }
                    symbol_combinations[key_for_combination]['individual_count'] += 1
            except Exception as e:
                logger.warning(f"Error parsing individual trade key {key}: {e}")

        # Now check which symbol combinations have sorted sets
        for key in sorted_set_keys:
            try:
                # Key format: zset:trade:{exchange}:{symbol}
                parts = key.split(":")
                if len(parts) >= 4:
                    exchange = parts[2].lower()  # Normalize case
                    symbol = ":".join(parts[3:])  # Symbol may contain colons

                    key_for_combination = f"{exchange}:{symbol}"
                    if key_for_combination in symbol_combinations:
                        symbol_combinations[key_for_combination]['sorted_set_key'] = key
                        # Count items in sorted set
                        symbol_combinations[key_for_combination]['sorted_set_size'] = redis.zcard(key)
            except Exception as e:
                logger.warning(f"Error parsing sorted set key {key}: {e}")

        # Convert to list and log results
        trade_keys = list(symbol_combinations.values())
        total_individual_trades = sum(tk['individual_count'] for tk in trade_keys)
        total_sorted_sets = sum(tk.get('sorted_set_size', 0) for tk in trade_keys)

        logger.info(f"Found {len(trade_keys)} unique symbol combinations")
        logger.info(f"Total individual trades: {total_individual_trades}")
        logger.info(f"Total sorted set entries: {total_sorted_sets}")

        for tk in trade_keys:
            sorted_size = tk.get('sorted_set_size', 0)
            logger.info(f"  {tk['exchange']}:{tk['symbol']} - Individual: {tk['individual_count']}, Sorted set: {sorted_size}")

        return trade_keys

    def analyze_trade_gaps(self, exchange: str, symbol: str, max_gap_minutes: int = 60) -> List[Dict[str, Any]]:
        """
        Analyze trade data for a specific exchange/symbol for gaps.
        Args:
            exchange: Exchange name (e.g., 'bybit')
            symbol: Trading symbol (e.g., 'BTCUSDT')
            max_gap_minutes: Maximum allowed gap in minutes before considering it a data gap
        Returns:
            List of gap periods with start/end timestamps
        """
        redis = self.get_sync_redis()
        sorted_set_key = get_sorted_set_trade_key(symbol, exchange)

        # Debug: Check if the sorted set key exists and has data
        logger.info(f"🔍 Checking sorted set key: {sorted_set_key}")
        exists = redis.exists(sorted_set_key)
        card = redis.zcard(sorted_set_key) if exists else 0

        logger.info(f"   Key exists: {exists}, Cardinality: {card}")

        if not exists or card == 0:
            logger.warning(f"No trade data found for {exchange}:{symbol} (key doesn't exist or is empty)")
            return []

        # Try different ways to get the data
        trade_data = None
        try:
            logger.info(f"   Attempting zrange with withscores=True...")
            trade_data = redis.zrange(sorted_set_key, 0, -1, withscores=True)
            logger.info(f"   Retrieved {len(trade_data) if trade_data else 0} items from zrange")
        except Exception as e:
            logger.error(f"Error getting trade data for {exchange}:{symbol}: {e}")
            return []

        if not trade_data:
            logger.warning(f"zrange returned empty result for {exchange}:{symbol}")
            # Try without withscores to see if the issue is with scores
            try:
                logger.info(f"   Trying zrange without scores...")
                raw_members = redis.zrange(sorted_set_key, 0, -1, withscores=False)
                logger.info(f"   Retrieved {len(raw_members) if raw_members else 0} raw members")

                if raw_members:
                    logger.info("   Sampling first few members:")
                    for i, member in enumerate(raw_members[:3]):
                        logger.info(f"     [{i}]: {str(member)[:100]}{'...' if len(str(member)) > 100 else ''}")

                    # Try to parse timestamps from the JSON data
                    timestamps_from_json = []
                    for member in raw_members[:10]:  # Sample first 10
                        try:
                            trade_obj = json.loads(member)
                            ts = trade_obj.get('timestamp')
                            if ts:
                                timestamps_from_json.append(ts)
                        except:
                            pass

                    logger.info(f"   Extracted {len(timestamps_from_json)} timestamps from JSON")
                    if timestamps_from_json:
                        min_ts = min(timestamps_from_json)
                        max_ts = max(timestamps_from_json)
                        logger.info(f"   Timestamp range: {min_ts} to {max_ts}")
                        logger.info(f"   Date range: {datetime.fromtimestamp(min_ts, timezone.utc)} to {datetime.fromtimestamp(max_ts, timezone.utc)}")

            except Exception as e2:
                logger.error(f"Error getting raw members: {e2}")

            return []

        # Extract timestamps and sort them
        timestamps = []
        for item, score in trade_data:
            try:
                # Parse the JSON data to get timestamp
                trade_data = json.loads(item)
                timestamp = trade_data.get('timestamp', score)  # Use score as fallback
                timestamps.append(int(timestamp))
            except (json.JSONDecodeError, KeyError):
                # Use the score as timestamp if JSON parsing fails
                timestamps.append(int(score))

        timestamps.sort()

        if len(timestamps) < 2:
            logger.info(f"Insufficient data points for gap analysis: {exchange}:{symbol} ({len(timestamps)} points)")
            return []

        # Analyze for gaps
        gaps = []
        max_gap_seconds = max_gap_minutes * 60

        logger.info(f"Analyzing {len(timestamps)} trades for {exchange}:{symbol}")
        logger.info(f"Time range: {datetime.fromtimestamp(timestamps[0], timezone.utc)} to {datetime.fromtimestamp(timestamps[-1], timezone.utc)}")

        for i in range(1, len(timestamps)):
            time_diff = timestamps[i] - timestamps[i-1]

            if time_diff > max_gap_seconds:
                gap_info = {
                    'exchange': exchange,
                    'symbol': symbol,
                    'gap_start': timestamps[i-1],
                    'gap_end': timestamps[i],
                    'gap_duration_seconds': time_diff,
                    'gap_duration_hours': round(time_diff / 3600, 2),
                    'gap_start_datetime': datetime.fromtimestamp(timestamps[i-1], timezone.utc).isoformat(),
                    'gap_end_datetime': datetime.fromtimestamp(timestamps[i], timezone.utc).isoformat(),
                    'consecutive_missing_periods': time_diff // 60  # Assuming 1-minute granularity
                }
                gaps.append(gap_info)

                logger.warning(f"📊 FOUND GAP: {exchange}:{symbol} from {gap_info['gap_start_datetime']} to {gap_info['gap_end_datetime']} "
                             f"({gap_info['gap_duration_hours']} hours, {gap_info['consecutive_missing_periods']} missing periods)")

        if not gaps:
            logger.info(f"✅ No significant gaps found for {exchange}:{symbol}")

        return gaps

    async def refetch_missing_data(self, gaps: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Refetch trade data for identified gaps."""
        results = {
            'total_gaps': len(gaps),
            'successful_refetches': 0,
            'failed_refetches': 0,
            'total_trades_fetched': 0,
            'errors': []
        }

        for gap in gaps:
            try:
                exchange = gap['exchange']
                symbol = gap['symbol']
                start_ts = gap['gap_start'] + 60  # Start from the next minute after last trade
                end_ts = gap['gap_end'] - 60    # End before the next existing trade

                logger.info(f"🔄 Refetching data for {exchange}:{symbol} from {datetime.fromtimestamp(start_ts, timezone.utc)} "
                           f"to {datetime.fromtimestamp(end_ts, timezone.utc)}")

                # Find the exchange configuration
                exchange_config = SUPPORTED_EXCHANGES.get(exchange)
                if not exchange_config:
                    error_msg = f"Exchange {exchange} not found in SUPPORTED_EXCHANGES"
                    logger.error(f"❌ {error_msg}")
                    results['errors'].append(error_msg)
                    results['failed_refetches'] += 1
                    continue

                # Refetch the missing data
                try:
                    missing_bars = await fetch_trades_from_ccxt(exchange, symbol, start_ts, end_ts)

                    if missing_bars and len(missing_bars) > 0:
                        logger.info(f"✅ Successfully refetched {len(missing_bars)} trade bars for {exchange}:{symbol}")
                        results['successful_refetches'] += 1
                        results['total_trades_fetched'] += len(missing_bars)
                    else:
                        logger.warning(f"⚠️ No data retrieved for gap in {exchange}:{symbol}")
                        results['failed_refetches'] += 1

                except Exception as e:
                    error_msg = f"Failed to refetch data for {exchange}:{symbol}: {e}"
                    logger.error(f"❌ {error_msg}")
                    results['errors'].append(error_msg)
                    results['failed_refetches'] += 1

            except Exception as e:
                error_msg = f"Error processing gap for {exchange}:{symbol}: {e}"
                logger.error(f"❌ {error_msg}")
                results['errors'].append(error_msg)
                results['failed_refetches'] += 1

        return results

    async def analyze_and_fix_all_symbols(self, max_gap_minutes: int = 60) -> Dict[str, Any]:
        """Analyze all trade symbols and fix any gaps found."""
        logger.info("🚀 Starting comprehensive trade gap analysis...")

        # Get all trade symbols
        all_symbols = self.get_all_trade_symbols()

        if not all_symbols:
            logger.warning("No trade data found in Redis")
            return {'status': 'no_data', 'message': 'No trade data found'}

        total_gaps_found = 0
        all_gaps = []

        # Analyze each symbol for gaps
        for symbol_info in all_symbols:
            exchange = symbol_info['exchange']
            symbol = symbol_info['symbol']

            logger.info(f"📊 Analyzing {exchange}:{symbol}...")
            gaps = self.analyze_trade_gaps(exchange, symbol, max_gap_minutes)

            if gaps:
                total_gaps_found += len(gaps)
                all_gaps.extend(gaps)
                logger.info(f"📈 Found {len(gaps)} gaps for {exchange}:{symbol}")
            else:
                logger.info(f"✅ No gaps found for {exchange}:{symbol}")

        # Report summary
        logger.info(f"📋 ANALYSIS SUMMARY:")
        logger.info(f"   Symbols analyzed: {len(all_symbols)}")
        logger.info(f"   Total gaps found: {total_gaps_found}")

        # Refetch missing data if gaps were found
        refetch_results = {'total_trades_fetched': 0}
        if all_gaps:
            logger.info(f"🔄 Starting data refetch for {len(all_gaps)} gaps...")
            refetch_results = await self.refetch_missing_data(all_gaps)

        # Final report
        final_report = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'symbols_analyzed': len(all_symbols),
            'total_gaps_found': total_gaps_found,
            'gaps': all_gaps,
            'refetch_results': refetch_results,
            'status': 'completed'
        }

        logger.info(f"✅ ANALYSIS COMPLETE:")
        logger.info(f"   Gaps found: {total_gaps_found}")
        logger.info(f"   Successful refetches: {refetch_results.get('successful_refetches', 0)}")
        logger.info(f"   Total trades refetched: {refetch_results.get('total_trades_fetched', 0)}")

        return final_report


async def main():
    """Main function to run the trade gap analysis."""
    try:
        # Initialize the analyzer
        analyzer = TradeGapAnalyzer()
        await analyzer.initialize()

        # Parse command line arguments
        max_gap_minutes = 60  # Default 1 hour
        if len(sys.argv) > 1:
            try:
                max_gap_minutes = int(sys.argv[1])
            except ValueError:
                logger.warning(f"Invalid gap threshold '{sys.argv[1]}', using default {max_gap_minutes} minutes")

        logger.info(f"🔍 Starting trade gap analysis with gap threshold: {max_gap_minutes} minutes")

        # Run the analysis
        results = await analyzer.analyze_and_fix_all_symbols(max_gap_minutes)

        # Save results to file
        output_file = f"trade_gap_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)

        logger.info(f"💾 Results saved to {output_file}")

        # Print summary
        print("\n" + "="*80)
        print("TRADE GAP ANALYSIS RESULTS")
        print("="*80)
        print(f"Symbols analyzed: {results['symbols_analyzed']}")
        print(f"Gaps found: {results['total_gaps_found']}")
        print(f"Trades refetched: {results['refetch_results'].get('total_trades_fetched', 0)}")
        print(f"Results saved to: {output_file}")
        print("="*80)

        return results

    except Exception as e:
        logger.error(f"❌ Fatal error in trade gap analysis: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    # Run the analysis
    asyncio.run(main())
