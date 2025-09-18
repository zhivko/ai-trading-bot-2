#!/usr/bin/env python3
"""
Test script to verify the indicator validation logic works correctly.
"""

from indicators import validate_indicator_data_alignment

def test_validation_with_nulls():
    """Test that validation fails when null values are present."""
    print("Testing validation with null values...")

    # Create test data with null values
    test_result = {
        't': [1000, 2000, 3000, 4000, 5000],
        'macd': [1.0, 2.0, None, 4.0, None],  # Contains nulls
        'signal': [0.5, 1.0, 1.5, None, 2.5],  # Contains nulls
        'histogram': [0.5, 1.0, None, 1.5, None]  # Contains nulls
    }

    original_ohlc_length = 5
    indicator_name = "test_macd"

    result = validate_indicator_data_alignment(test_result, original_ohlc_length, indicator_name)

    if result:
        print("❌ FAIL: Validation should have failed with null values present")
        return False
    else:
        print("✅ PASS: Validation correctly failed with null values")
        return True

def test_validation_without_nulls():
    """Test that validation passes when no null values are present."""
    print("Testing validation without null values...")

    # Create test data without null values
    test_result = {
        't': [1000, 2000, 3000, 4000, 5000],
        'macd': [1.0, 2.0, 3.0, 4.0, 5.0],  # No nulls
        'signal': [0.5, 1.0, 1.5, 2.0, 2.5],  # No nulls
        'histogram': [0.5, 1.0, 1.5, 2.0, 2.5]  # No nulls
    }

    original_ohlc_length = 5
    indicator_name = "test_macd"

    result = validate_indicator_data_alignment(test_result, original_ohlc_length, indicator_name)

    if result:
        print("✅ PASS: Validation correctly passed with no null values")
        return True
    else:
        print("❌ FAIL: Validation should have passed with no null values")
        return False

def test_validation_length_mismatch():
    """Test that validation fails when lengths don't match."""
    print("Testing validation with length mismatch...")

    # Create test data with wrong length
    test_result = {
        't': [1000, 2000, 3000, 4000],  # 4 timestamps
        'macd': [1.0, 2.0, 3.0, 4.0, 5.0],  # 5 values - mismatch
        'signal': [0.5, 1.0, 1.5, 2.0, 2.5],  # 5 values - mismatch
        'histogram': [0.5, 1.0, 1.5, 2.0, 2.5]  # 5 values - mismatch
    }

    original_ohlc_length = 5
    indicator_name = "test_macd"

    result = validate_indicator_data_alignment(test_result, original_ohlc_length, indicator_name)

    if result:
        print("❌ FAIL: Validation should have failed with length mismatch")
        return False
    else:
        print("✅ PASS: Validation correctly failed with length mismatch")
        return True

if __name__ == "__main__":
    print("Running indicator validation tests...\n")

    test1_pass = test_validation_with_nulls()
    print()

    test2_pass = test_validation_without_nulls()
    print()

    test3_pass = test_validation_length_mismatch()
    print()

    all_passed = test1_pass and test2_pass and test3_pass

    if all_passed:
        print("🎉 All tests passed!")
    else:
        print("💥 Some tests failed!")

    print("Test completed.")
