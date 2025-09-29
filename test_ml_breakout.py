"""
Test script for ML Breakout Strategy
Tests the decision tree enhanced breakout trading algorithm
"""

import sys
import time
from datetime import datetime
from ml_breakout_strategy import MLBreakoutTrader
from config import SUPPORTED_SYMBOLS
from logging_config import logger

def test_feature_extraction():
    """Test feature extraction functionality"""
    print("Testing feature extraction...")

    trader = MLBreakoutTrader("BTCUSDT")

    # Try to fetch some historical data
    print("Fetching historical data...")
    df = trader.fetch_historical_data("BTCUSDT", days=30)

    if df.empty:
        print("❌ No data available - check API connection")
        return False

    print(f"✅ Fetched {len(df)} candles")

    # Test feature extraction
    print("Extracting features...")
    features = trader.extract_features(df)

    if features.empty:
        print("❌ Feature extraction failed")
        return False

    print(f"✅ Extracted {len(features.columns)} features")
    print(f"Feature names: {list(features.columns)}")
    return True

def test_model_training():
    """Test model training functionality"""
    print("\nTesting model training...")

    trader = MLBreakoutTrader("BTCUSDT", training_window=60, testing_window=7)  # Shorter for testing

    # Train the model
    print("Training ML model...")
    success = trader.train_model(force_retrain=True)

    if not success:
        print("❌ Model training failed")
        return False

    # Check performance
    performance = trader.get_model_performance()
    print("✅ Model trained successfully")
    print(f"   Accuracy: {performance.get('accuracy', 0):.3f}")
    print(f"   Precision: {performance.get('precision', 0):.3f}")
    print(f"   Recall: {performance.get('recall', 0):.3f}")
    print(f"   F1-Score: {performance.get('f1_score', 0):.3f}")
    print(f"   Training samples: {performance.get('training_samples', 0)}")
    return True

def test_signal_generation():
    """Test signal generation"""
    print("\nTesting signal generation...")

    trader = MLBreakoutTrader("BTCUSDT")

    # Test breakout detection
    print("Testing breakout detection...")
    df = trader.fetch_historical_data("BTCUSDT", days=100)

    if df.empty:
        print("❌ No data for breakout test")
        return False

    current_price = df['close'].iloc[-1]
    day50_high = trader.get_50day_high(df)

    print(f"Current price: ${current_price:.2f}")
    print(f"50-day high: ${day50_high:.2f}")
    print(f"Breakout condition: {current_price > day50_high}")

    # Test ML prediction
    print("Testing ML prediction...")
    ml_signal = trader.predict_signal(df)
    print(f"ML prediction: {ml_signal} (1=buy, 0=no signal)")

    # Test complete strategy
    print("Testing complete strategy signal...")
    signal = trader.should_enter_trade()

    print(f"Strategy signal: {'BUY' if signal else 'HOLD'}")
    return True

def run_all_tests():
    """Run all test functions"""
    print("="*50)
    print("ML BREAKOUT STRATEGY TEST SUITE")
    print("="*50)

    tests = [
        ("Feature Extraction", test_feature_extraction),
        ("Model Training", test_model_training),
        ("Signal Generation", test_signal_generation)
    ]

    results = []

    for test_name, test_func in tests:
        try:
            print(f"\n{'='*20} {test_name} {'='*20}")
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} failed with exception: {e}")
            results.append((test_name, False))

    # Summary
    print("\n" + "="*50)
    print("TEST RESULTS SUMMARY")
    print("="*50)

    passed = 0
    total = len(results)

    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{test_name:20} {status}")
        if result:
            passed += 1

    print(f"\nOVERALL: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed! The ML Breakout Strategy is ready.")
        return True
    else:
        print(f"⚠️  {total - passed} test(s) failed. Check the logs above.")
        return False

if __name__ == "__main__":
    logger.info("Starting ML Breakout Strategy tests")

    success = run_all_tests()

    if success:
        print("\n🚀 ML Breakout Strategy implementation complete!")
        print("\nNext steps:")
        print("1. Integrate with trading_service.py for live signals")
        print("2. Add to trading endpoints for API access")
        print("3. Set up automated training schedule")
        print("4. Backtest across multiple crypto pairs")
