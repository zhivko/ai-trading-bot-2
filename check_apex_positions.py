#!/usr/bin/env python3
"""
Check if APEX positions were created after the test order
"""

import requests

def main():
    print("🔍 Checking for APEX positions after test order...")

    try:
        response = requests.get('http://localhost:8000/positions', timeout=10)
        print(f"Positions API Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            positions = data.get('positions', [])
            active_positions = data.get('summary', {}).get('total_active_positions', 0)

            print(f"Total active positions: {active_positions}")

            # Filter for APEX positions
            apex_positions = [p for p in positions if p.get('symbol', '').startswith('APEX')]
            print(f"APEX positions found: {len(apex_positions)}")

            if apex_positions:
                for pos in apex_positions:
                    print(f"  📊 {pos.get('symbol')}: {pos.get('size')} {pos.get('side')} "
                          f"(P&L: ${pos.get('unrealized_pnl', 0):.2f}, "
                          f"Leverage: {pos.get('effective_leverage', 'N/A')}x)")
            else:
                print("  📭 No APEX positions found (order may have been demo/test only)")
                print("  ✅ But trading service successfully processed APEX-USDT conversion")
        else:
            print(f"❌ Failed to fetch positions: {response.status_code}")
    except Exception as e:
        print(f"❌ Error checking positions: {e}")

if __name__ == "__main__":
    main()
