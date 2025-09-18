# Technical indicator calculations

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import time
import pandas_ta as ta  # Required for technical analysis indicators
from config import AVAILABLE_INDICATORS, session
from logging_config import logger
from datetime import datetime, timezone

def get_timeframe_seconds(timeframe: str) -> int:
    multipliers = {"1m": 60, "5m": 300, "1h": 3600, "1d": 86400, "1w": 604800}
    return multipliers.get(timeframe, 3600)

def _prepare_dataframe(klines: List[Dict[str, Any]], open_interest_data: List[Dict[str, Any]]) -> Optional[pd.DataFrame]:
    if not klines:
        return None

    logger.debug(f"_prepare_dataframe: Starting with {len(klines)} klines and {len(open_interest_data)} OI entries")

    # 🚨 CRITICAL: Check data freshness at input
    if klines:
        current_time = datetime.now(timezone.utc)
        latest_kline_timestamp = datetime.fromtimestamp(klines[-1]['time'], timezone.utc)
        earliest_kline_timestamp = datetime.fromtimestamp(klines[0]['time'], timezone.utc)
        time_diff_minutes = (current_time - latest_kline_timestamp).total_seconds() / 60

        logger.warning(f"🚨 DATA INPUT LAG: Latest kline is {time_diff_minutes:.1f} minutes old!")
        logger.warning(f"🚨 DATA INPUT LAG: Current time: {current_time.strftime('%H:%M:%S')}, Latest data: {latest_kline_timestamp.strftime('%H:%M:%S')}")
        logger.warning(f"🚨 DATA INPUT LAG: Data range: {earliest_kline_timestamp.strftime('%H:%M:%S')} to {latest_kline_timestamp.strftime('%H:%M:%S')}")

        if time_diff_minutes > 60:  # More than 1 hour lag
            logger.error(f"🚨 CRITICAL DATA LAG AT INPUT: {time_diff_minutes:.1f} minutes! Data pipeline issue detected!")

    # De-duplicate klines by time before DataFrame creation
    unique_klines_map: Dict[int, Dict[str, Any]] = {}
    for k in klines:
        unique_klines_map[k['time']] = k
    klines_deduplicated = sorted(list(unique_klines_map.values()), key=lambda x: x['time'])

    df_klines = pd.DataFrame(klines_deduplicated)
    df_klines['time'] = pd.to_datetime(df_klines['time'], unit='s')
    df_klines = df_klines.set_index('time')
    # Ensure correct column names for pandas_ta
    df_klines.rename(columns={'vol': 'volume'}, inplace=True)
    # pandas_ta expects lowercase column names for ohlcv
    df_klines.columns = [col.lower() for col in df_klines.columns]

    # Count NaN values in klines data
    nan_counts_klines = df_klines.isnull().sum()
    logger.debug(f"_prepare_dataframe: Klines DataFrame shape: {df_klines.shape}, NaN counts: {nan_counts_klines.to_dict()}")
    logger.debug(f"_prepare_dataframe: Klines timestamp range: {df_klines.index.min()} to {df_klines.index.max()}")

    # Process Open Interest data
    df_oi = pd.DataFrame()
    if open_interest_data:
        # De-duplicate OI data by time before DataFrame creation
        unique_oi_map: Dict[int, Dict[str, Any]] = {}
        for oi_entry in open_interest_data:
            unique_oi_map[oi_entry['time']] = oi_entry
        oi_data_deduplicated = sorted(list(unique_oi_map.values()), key=lambda x: x['time'])

        df_oi = pd.DataFrame(oi_data_deduplicated)
        if 'time' in df_oi.columns:
            df_oi['time'] = pd.to_datetime(df_oi['time'], unit='s')
            df_oi = df_oi.set_index('time')
            df_oi.rename(columns={'open_interest': 'open_interest'}, inplace=True)

            # Count NaN values in OI data
            nan_counts_oi = df_oi.isnull().sum()
            logger.debug(f"_prepare_dataframe: OI DataFrame shape: {df_oi.shape}, NaN counts: {nan_counts_oi.to_dict()}")
            logger.debug(f"_prepare_dataframe: OI timestamp range: {df_oi.index.min()} to {df_oi.index.max()}")

    # Merge klines and Open Interest data
    if not df_oi.empty:
        df_merged = pd.merge(df_klines, df_oi[['open_interest']], left_index=True, right_index=True, how='left')
        df_merged['open_interest'] = df_merged['open_interest'].ffill().bfill().fillna(0)

        # Count NaN values after merge
        nan_counts_merged = df_merged.isnull().sum()
        logger.debug(f"_prepare_dataframe: Merged DataFrame shape: {df_merged.shape}, NaN counts: {nan_counts_merged.to_dict()}")
        logger.debug(f"_prepare_dataframe: Merged timestamp range: {df_merged.index.min()} to {df_merged.index.max()}")

        return df_merged
    else:
        df_klines['open_interest'] = 0.0

        logger.debug(f"_prepare_dataframe: Final DataFrame shape: {df_klines.shape}, NaN counts: {nan_counts_klines.to_dict()}")
        logger.debug(f"_prepare_dataframe: Final timestamp range: {df_klines.index.min()} to {df_klines.index.max()}")

        return df_klines

def _extract_results(df: pd.DataFrame, columns: List[str], original_time_index: pd.Series) -> Dict[str, Any]:
    """Extracts specified columns and aligns with original time index, preserving ALL timestamps."""
    data_dict: Dict[str, Any] = {"t": []}

    # CRITICAL FIX: Ensure we preserve ALL timestamps from original_time_index
    # Create a DataFrame that maintains the exact same index as original_time_index
    aligned_df = pd.DataFrame(index=original_time_index)
    aligned_df.index.name = 'time'

    # Add the calculated columns, filling missing timestamps with NaN
    for col in columns:
        if col in df.columns:
            # Check nulls before reindexing
            before_reindex_nulls = df[col].isnull().sum()
            logger.debug(f"_extract_results: Column '{col}' has {before_reindex_nulls} nulls before reindexing (out of {len(df[col])} total)")

            # Reindex to match original_time_index exactly, filling gaps with NaN
            aligned_df[col] = df[col].reindex(original_time_index, method=None)

            # Check nulls after reindexing
            after_reindex_nulls = aligned_df[col].isnull().sum()
            logger.debug(f"_extract_results: Column '{col}' has {after_reindex_nulls} nulls after reindexing (out of {len(aligned_df[col])} total)")
            if after_reindex_nulls > before_reindex_nulls:
                logger.warning(f"_extract_results: Column '{col}' gained {after_reindex_nulls - before_reindex_nulls} nulls during reindexing!")
        else:
            # Column doesn't exist, fill with NaN
            aligned_df[col] = np.nan
            logger.warning(f"Column '{col}' not found in DataFrame, filling with NaN values")

    logger.debug(f"Indicator extraction: Original time index length: {len(original_time_index)}")
    logger.debug(f"Indicator extraction: Aligned DataFrame shape: {aligned_df.shape}")
    logger.debug(f"Indicator extraction: Columns: {columns}")

    # Count NaN values in aligned data
    nan_counts_aligned = aligned_df[columns].isnull().sum()
    logger.debug(f"Indicator extraction: NaN counts in aligned columns: {nan_counts_aligned.to_dict()}")
    logger.debug(f"Indicator extraction: Time range: {original_time_index.min()} to {original_time_index.max()}")

    # Extract timestamps - now guaranteed to be all original timestamps
    data_dict["t"] = (original_time_index.astype('int64') // 10**9).tolist()  # Convert ns to s

    # Count non-null values for each output key
    output_keys_info = {}
    for col in columns:
        # Ensure the key in data_dict is simplified (e.g., 'macd' instead of 'MACD_12_26_9')
        simple_col_name = col.lower()  # Start with the full lowercase name
        if "macdh" in col.lower():
            simple_col_name = "histogram"
        elif "macds" in col.lower():
            simple_col_name = "signal"
        elif "mac" in col.lower() and "macdh" not in col.lower() and "macds" not in col.lower():
            simple_col_name = "macd"  # Ensure 'macd' is prioritized
        elif "stochrsik" in col.lower():
            simple_col_name = "stoch_k"
        elif "stochrsid" in col.lower():
            simple_col_name = "stoch_d"
        elif "_sma14" in col.lower() and "rsi" in col.lower():
            simple_col_name = "rsi_sma14"
        elif "rsi" in col.lower() and "stoch" not in col.lower() and "_sma" not in col.lower():
            simple_col_name = "rsi"
        elif "open_interest" in col.lower():
            simple_col_name = "open_interest"
        elif "jma_up" in col.lower():
            simple_col_name = "jma_up"
        elif "jma_down" in col.lower():
            simple_col_name = "jma_down"
        elif "jma" in col.lower() and "jma_up" not in col.lower() and "jma_down" not in col.lower():
            simple_col_name = "jma"  # Add JMA

        # Convert NaN to None for JSON compatibility, but PRESERVE all values including NaN
        if col in aligned_df.columns:
            raw_values = aligned_df[col].tolist()
            processed_values = [None if pd.isna(val) else val for val in raw_values]
            non_null_count = sum(1 for v in processed_values if v is not None)
            output_keys_info[simple_col_name] = f"{len(processed_values)} total, {non_null_count} non-null"
        else:
            # This shouldn't happen with our new logic, but handle it just in case
            processed_values = [None] * len(aligned_df)
            output_keys_info[simple_col_name] = f"{len(processed_values)} total, 0 non-null"

        data_dict[simple_col_name] = processed_values

    logger.debug(f"Indicator extraction: Final output structure - timestamps: {len(data_dict['t'])}, keys: {list(output_keys_info.keys())}")
    logger.debug(f"Indicator extraction: Output data info: {output_keys_info}")

    return data_dict

def calculate_open_interest(df_input: pd.DataFrame) -> Dict[str, Any]:
    df = df_input.copy()
    original_time_index = df.index.to_series()
    oi_col = 'open_interest'  # This column should already exist from _prepare_dataframe
    if oi_col not in df.columns:
        logger.warning(f"Open Interest column '{oi_col}' not found in DataFrame. Cannot calculate. Returning aligned data with NAs.")
        # Return placeholder data aligned with ALL original timestamps with expected keys
        # Add empty column to df to ensure _extract_results includes the expected keys
        df[oi_col] = np.nan
        return _extract_results(df, [oi_col], original_time_index)
    return _extract_results(df, [oi_col], original_time_index)

def calculate_macd(df_input: pd.DataFrame, short_period: int, long_period: int, signal_period: int) -> Dict[str, Any]:
    df = df_input.copy()
    original_time_index = df.index.to_series()  # Keep original timestamps for alignment

    # Count NaN values in input data
    nan_counts_input = df.isnull().sum()
    logger.debug(f"MACD calculation: Input DataFrame shape: {df.shape}, NaN counts: {nan_counts_input.to_dict()}")
    logger.debug(f"MACD calculation: Input timestamp range: {df.index.min()} to {df.index.max()}")

    # CRITICAL: Ensure DataFrame maintains the exact same index throughout processing
    df_processed = df.copy()

    # Ensure volume is not None (replace with 0 if needed) - but keep NaN in OHLC for proper handling
    if 'volume' in df_processed.columns:
        df_processed['volume'] = df_processed['volume'].fillna(0)

    logger.debug(f"MACD calculation: Processing {len(df_processed)} points")
    logger.debug(f"MACD calculation: Processing timestamp range: {df_processed.index.min()} to {df_processed.index.max()}")

    # Check for nulls in input data before calculation
    input_nulls = df_processed.isnull().sum()
    logger.debug(f"MACD calculation: Input data null counts: {input_nulls.to_dict()}")

    if len(df_processed) < long_period + signal_period:
        logger.warning(f"🔍 MACD GAP CAUSE: Insufficient data for MACD calculation. Need at least {long_period + signal_period} points, got {len(df_processed)}. This creates a {((original_time_index.min() + pd.Timedelta(seconds=(long_period + signal_period) * get_timeframe_seconds('1h'))) - original_time_index.min()).total_seconds() / 86400:.1f} day gap.")
        # Return placeholder data aligned with ALL original timestamps with expected keys
        macd_col = f'MACD_{short_period}_{long_period}_{signal_period}'
        signal_col = f'MACDs_{short_period}_{long_period}_{signal_period}'
        hist_col = f'MACDh_{short_period}_{long_period}_{signal_period}'
        # Add empty columns to df_processed to ensure _extract_results includes the expected keys
        df_processed[macd_col] = np.nan
        df_processed[signal_col] = np.nan
        df_processed[hist_col] = np.nan
        return _extract_results(df_processed, [macd_col, signal_col, hist_col], original_time_index)

    try:
        logger.debug(f"MACD calculation: About to call pandas-ta MACD with fast={short_period}, slow={long_period}, signal={signal_period}")
        # Calculate MACD while preserving the DataFrame index
        df_processed.ta.macd(fast=short_period, slow=long_period, signal=signal_period, append=True)
        logger.debug(f"MACD calculation: pandas-ta MACD completed successfully")

        # Check for nulls immediately after pandas-ta calculation
        after_calc_nulls = df_processed.isnull().sum()
        logger.debug(f"MACD calculation: Null counts after pandas-ta: {after_calc_nulls.to_dict()}")

        # Verify the DataFrame still has the correct index after pandas-ta operation
        if not df_processed.index.equals(df.index):
            logger.warning("MACD calculation: DataFrame index changed during pandas-ta operation, realigning...")
            df_processed = df_processed.reindex(df.index)
            # Check nulls after reindexing
            after_reindex_nulls = df_processed.isnull().sum()
            logger.debug(f"MACD calculation: Null counts after reindexing: {after_reindex_nulls.to_dict()}")

    except Exception as e:
        logger.error(f"pandas-ta MACD calculation failed: {e}")
        logger.error(f"DataFrame info: shape={df_processed.shape}, columns={df_processed.columns.tolist()}")
        logger.error(f"Sample data: {df_processed.head(3).to_dict() if len(df_processed) > 0 else 'No data'}")
        # Return placeholder data aligned with ALL original timestamps with expected keys
        macd_col = f'MACD_{short_period}_{long_period}_{signal_period}'
        signal_col = f'MACDs_{short_period}_{long_period}_{signal_period}'
        hist_col = f'MACDh_{short_period}_{long_period}_{signal_period}'
        # Add empty columns to df_processed to ensure _extract_results includes the expected keys
        df_processed[macd_col] = np.nan
        df_processed[signal_col] = np.nan
        df_processed[hist_col] = np.nan
        return _extract_results(df_processed, [macd_col, signal_col, hist_col], original_time_index)

    macd_col = f'MACD_{short_period}_{long_period}_{signal_period}'
    signal_col = f'MACDs_{short_period}_{long_period}_{signal_period}'
    hist_col = f'MACDh_{short_period}_{long_period}_{signal_period}'

    # Check if columns were actually created by pandas_ta
    if not all(col in df_processed.columns for col in [macd_col, signal_col, hist_col]):
        logger.warning(f"MACD columns not found in DataFrame. Expected: {macd_col}, {signal_col}, {hist_col}. "
                      f"This might be due to insufficient data for the indicator periods. Available columns: {df_processed.columns.tolist()}")
        # Return placeholder data aligned with ALL original timestamps with expected keys
        # Add empty columns to df_processed to ensure _extract_results includes the expected keys
        df_processed[macd_col] = np.nan
        df_processed[signal_col] = np.nan
        df_processed[hist_col] = np.nan
        return _extract_results(df_processed, [macd_col, signal_col, hist_col], original_time_index)

    # DEBUG: Check DataFrame columns and lengths before extraction
    logger.debug(f"MACD DEBUG: DataFrame columns: {df_processed.columns.tolist()}")
    logger.debug(f"MACD DEBUG: MACD column '{macd_col}' exists: {macd_col in df_processed.columns}")
    logger.debug(f"MACD DEBUG: Signal column '{signal_col}' exists: {signal_col in df_processed.columns}")
    logger.debug(f"MACD DEBUG: Histogram column '{hist_col}' exists: {hist_col in df_processed.columns}")

    if macd_col in df_processed.columns:
        macd_non_null = df_processed[macd_col].notna().sum()
        logger.debug(f"MACD DEBUG: MACD column length: {len(df_processed[macd_col])}, non-null: {macd_non_null}")

    if signal_col in df_processed.columns:
        signal_non_null = df_processed[signal_col].notna().sum()
        logger.debug(f"MACD DEBUG: Signal column length: {len(df_processed[signal_col])}, non-null: {signal_non_null}")

    if hist_col in df_processed.columns:
        hist_non_null = df_processed[hist_col].notna().sum()
        logger.debug(f"MACD DEBUG: Histogram column length: {len(df_processed[hist_col])}, non-null: {hist_non_null}")

    # Check for length mismatch before extraction
    if all(col in df_processed.columns for col in [macd_col, signal_col, hist_col]):
        macd_length = len(df_processed[macd_col])
        signal_length = len(df_processed[signal_col])
        hist_length = len(df_processed[hist_col])

        lengths = [macd_length, signal_length, hist_length]
        if len(set(lengths)) > 1:  # Not all lengths are equal
            logger.warning(f"MACD LENGTH MISMATCH: MACD={macd_length}, Signal={signal_length}, Histogram={hist_length}")

            # Find the minimum length and truncate all to match
            min_length = min(lengths)
            logger.warning(f"MACD FIX: Truncating all series to {min_length} values")

            # Truncate the longer series to match the shortest one
            if macd_length > min_length:
                df_processed[macd_col] = df_processed[macd_col].iloc[:min_length]
            if signal_length > min_length:
                df_processed[signal_col] = df_processed[signal_col].iloc[:min_length]
            if hist_length > min_length:
                df_processed[hist_col] = df_processed[hist_col].iloc[:min_length]

            # Also truncate the DataFrame index to match
            df_processed = df_processed.iloc[:min_length]

    result = _extract_results(df_processed, [macd_col, signal_col, hist_col], original_time_index)

    # INFO LOGGING FOR TROUBLESHOOTING - Show actual values being returned
    logger.info(f"🔍 MACD CALCULATION RESULT: short={short_period}, long={long_period}, signal={signal_period}, total_points={len(result.get('t', []))}")
    logger.info(f"🔍 MACD VALUES SAMPLE (last 5): {[f'{v:.4f}' if v is not None else 'None' for v in result.get('macd', [])[-5:]]}")
    logger.info(f"🔍 MACD SIGNAL VALUES SAMPLE (last 5): {[f'{v:.4f}' if v is not None else 'None' for v in result.get('signal', [])[-5:]]}")
    logger.info(f"🔍 MACD HISTOGRAM VALUES SAMPLE (last 5): {[f'{v:.4f}' if v is not None else 'None' for v in result.get('histogram', [])[-5:]]}")
    logger.info(f"🔍 MACD TIMESTAMP SAMPLE (last 5): {[datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S') for ts in result.get('t', [])[-5:]]}")

    # Count non-null values
    macd_values = result.get('macd', [])
    signal_values = result.get('signal', [])
    histogram_values = result.get('histogram', [])
    macd_non_null = sum(1 for v in macd_values if v is not None)
    signal_non_null = sum(1 for v in signal_values if v is not None)
    histogram_non_null = sum(1 for v in histogram_values if v is not None)
    logger.info(f"🔍 MACD NON-NULL VALUES: macd={macd_non_null}/{len(macd_values)}, signal={signal_non_null}/{len(signal_values)}, histogram={histogram_non_null}/{len(histogram_values)}")

    return result

def calculate_rsi(df_input: pd.DataFrame, period: int = 14) -> Dict[str, Any]:
    """
    Compute RSI + SMA‑14 of RSI in the same response dictionary.

    Returns
    -------
    Dict[str, Any]
        Dictionary with keys:
            * ``t`` – timestamps
            * ``rsi`` – raw RSI values
            * ``rsi_sma14`` – 14‑period moving average of RSI
    """
    df = df_input.copy()
    original_time_index = df.index.to_series()

    # Count NaN values in input data
    nan_counts_input = df.isnull().sum()
    logger.debug(f"RSI calculation: Input DataFrame shape: {df.shape}, NaN counts: {nan_counts_input.to_dict()}")
    logger.debug(f"RSI calculation: Input timestamp range: {df.index.min()} to {df.index.max()}")

    # CRITICAL: Ensure DataFrame maintains the exact same index throughout processing
    df_processed = df.copy()

    # Ensure volume is not None (replace with 0 if needed) - but keep NaN in OHLC for proper handling
    if 'volume' in df_processed.columns:
        df_processed['volume'] = df_processed['volume'].fillna(0)

    logger.debug(f"RSI calculation: Processing {len(df_processed)} points")
    logger.debug(f"RSI calculation: Processing timestamp range: {df_processed.index.min()} to {df_processed.index.max()}")

    if len(df_processed) < period + 14:  # Need enough data for RSI + SMA
        logger.warning(f"🔍 RSI GAP CAUSE: Insufficient data for RSI calculation. Need at least {period + 14} points, got {len(df_processed)}. This creates a {((original_time_index.min() + pd.Timedelta(seconds=(period + 14) * get_timeframe_seconds('1h'))) - original_time_index.min()).total_seconds() / 86400:.1f} day gap.")
        # Return placeholder data aligned with ALL original timestamps with expected keys
        rsi_col = f"RSI_{period}"
        sma_col = f"RSI_{period}_sma14"
        # Add empty columns to df_processed to ensure _extract_results includes the expected keys
        df_processed[rsi_col] = np.nan
        df_processed[sma_col] = np.nan
        return _extract_results(df_processed, [rsi_col, sma_col], original_time_index)

    try:
        # 1️⃣ Compute the raw RSI while preserving the DataFrame index
        df_processed.ta.rsi(length=period, append=True)

        # Verify the DataFrame still has the correct index after pandas-ta operation
        if not df_processed.index.equals(df.index):
            logger.warning("RSI calculation: DataFrame index changed during pandas-ta operation, realigning...")
            df_processed = df_processed.reindex(df.index)

    except Exception as e:
        logger.error(f"pandas-ta RSI calculation failed: {e}")
        # Return placeholder data aligned with ALL original timestamps with expected keys
        rsi_col = f"RSI_{period}"
        sma_col = f"RSI_{period}_sma14"
        # Add empty columns to df_processed to ensure _extract_results includes the expected keys
        df_processed[rsi_col] = np.nan
        df_processed[sma_col] = np.nan
        return _extract_results(df_processed, [rsi_col, sma_col], original_time_index)

    rsi_col = f"RSI_{period}"
    if rsi_col not in df_processed.columns:
        logger.warning(f"RSI column '{rsi_col}' not found – maybe not enough data")
        # Return placeholder data aligned with ALL original timestamps with expected keys
        sma_col = f"RSI_{period}_sma14"
        # Add empty columns to df_processed to ensure _extract_results includes the expected keys
        df_processed[rsi_col] = np.nan
        df_processed[sma_col] = np.nan
        return _extract_results(df_processed, [rsi_col, sma_col], original_time_index)

    # 2️⃣ Compute SMA‑14 of that RSI
    sma_col = f"RSI_{period}_sma14"
    df_processed[sma_col] = df_processed[rsi_col].rolling(window=14).mean()

    # DEBUG: Check DataFrame columns and lengths before extraction
    logger.debug(f"RSI DEBUG: DataFrame columns: {df_processed.columns.tolist()}")
    logger.debug(f"RSI DEBUG: RSI column '{rsi_col}' exists: {rsi_col in df_processed.columns}")
    logger.debug(f"RSI DEBUG: SMA column '{sma_col}' exists: {sma_col in df_processed.columns}")

    if rsi_col in df_processed.columns:
        rsi_non_null = df_processed[rsi_col].notna().sum()
        logger.debug(f"RSI DEBUG: RSI column length: {len(df_processed[rsi_col])}, non-null: {rsi_non_null}")

    if sma_col in df_processed.columns:
        sma_non_null = df_processed[sma_col].notna().sum()
        logger.debug(f"RSI DEBUG: SMA column length: {len(df_processed[sma_col])}, non-null: {sma_non_null}")

    # Check for length mismatch before extraction
    if rsi_col in df_processed.columns and sma_col in df_processed.columns:
        rsi_length = len(df_processed[rsi_col])
        sma_length = len(df_processed[sma_col])
        if rsi_length != sma_length:
            logger.warning(f"RSI LENGTH MISMATCH: RSI has {rsi_length} values, SMA has {sma_length} values")

            # Find the minimum length and truncate both to match
            min_length = min(rsi_length, sma_length)
            logger.warning(f"RSI FIX: Truncating both RSI and SMA to {min_length} values")

            # Truncate the longer series to match the shorter one
            if rsi_length > min_length:
                df_processed[rsi_col] = df_processed[rsi_col].iloc[:min_length]
            if sma_length > min_length:
                df_processed[sma_col] = df_processed[sma_col].iloc[:min_length]

            # Also truncate the DataFrame index to match
            df_processed = df_processed.iloc[:min_length]

    # 3️⃣ Return both columns via _extract_results
    result = _extract_results(df_processed, [rsi_col, sma_col], original_time_index)

    # INFO LOGGING FOR TROUBLESHOOTING - Show actual values being returned
    logger.info(f"🔍 RSI CALCULATION RESULT: period={period}, total_points={len(result.get('t', []))}")
    logger.info(f"🔍 RSI VALUES SAMPLE (last 5): {[f'{v:.2f}' if v is not None else 'None' for v in result.get('rsi', [])[-5:]]}")
    logger.info(f"🔍 RSI SMA14 VALUES SAMPLE (last 5): {[f'{v:.2f}' if v is not None else 'None' for v in result.get('rsi_sma14', [])[-5:]]}")
    logger.info(f"🔍 RSI TIMESTAMP SAMPLE (last 5): {[datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S') for ts in result.get('t', [])[-5:]]}")

    # Count non-null values
    rsi_values = result.get('rsi', [])
    rsi_sma14_values = result.get('rsi_sma14', [])
    rsi_non_null = sum(1 for v in rsi_values if v is not None)
    rsi_sma14_non_null = sum(1 for v in rsi_sma14_values if v is not None)
    logger.info(f"🔍 RSI NON-NULL VALUES: rsi={rsi_non_null}/{len(rsi_values)}, rsi_sma14={rsi_sma14_non_null}/{len(rsi_sma14_values)}")

    logger.debug(f"RSI calculation completed: {len(result.get('t', []))} points")
    return result

def calculate_stoch_rsi(df_input: pd.DataFrame, rsi_period: int, stoch_period: int, k_period: int, d_period: int) -> Dict[str, Any]:
    df = df_input.copy()
    original_time_index = df.index.to_series()

    # Count NaN values before calculation
    nan_counts_before = df.isnull().sum()
    logger.debug(f"StochRSI calculation: Input DataFrame shape: {df.shape}, NaN counts: {nan_counts_before.to_dict()}")
    logger.debug(f"StochRSI calculation: Input timestamp range: {df.index.min()} to {df.index.max()}")

    # CRITICAL: Ensure DataFrame maintains the exact same index throughout processing
    df_processed = df.copy()

    # Check if we have sufficient data before attempting calculation
    min_required_points = rsi_period + stoch_period + k_period + d_period
    logger.debug(f"StochRSI validation: need {min_required_points} points, have {len(df_processed)}")

    if len(df_processed) < min_required_points:
        logger.warning(f"🔍 STOCHRSI INSUFFICIENT DATA: Need at least {min_required_points} points, got {len(df_processed)}. "
                      f"This will cause {min_required_points - len(df_processed)} NaN values at the start.")
        # Return placeholder data aligned with ALL original timestamps with expected keys
        k_col = f'STOCHRSIk_{stoch_period}_{rsi_period}_{k_period}_{d_period}'
        d_col = f'STOCHRSId_{stoch_period}_{rsi_period}_{k_period}_{d_period}'
        # Add empty columns to df_processed to ensure _extract_results includes the expected keys
        df_processed[k_col] = np.nan
        df_processed[d_col] = np.nan
        return _extract_results(df_processed, [k_col, d_col], original_time_index)

    try:
        # Calculate StochRSI while preserving the DataFrame index
        df_processed.ta.stochrsi(rsi_length=rsi_period, length=stoch_period, k=k_period, d=d_period, append=True)

        # Verify the DataFrame still has the correct index after pandas-ta operation
        if not df_processed.index.equals(df.index):
            logger.warning("StochRSI calculation: DataFrame index changed during pandas-ta operation, realigning...")
            df_processed = df_processed.reindex(df.index)

    except Exception as e:
        logger.error(f"pandas-ta StochRSI calculation failed: {e}")
        # Return placeholder data aligned with ALL original timestamps with expected keys
        k_col = f'STOCHRSIk_{stoch_period}_{rsi_period}_{k_period}_{d_period}'
        d_col = f'STOCHRSId_{stoch_period}_{rsi_period}_{k_period}_{d_period}'
        # Add empty columns to df_processed to ensure _extract_results includes the expected keys
        df_processed[k_col] = np.nan
        df_processed[d_col] = np.nan
        return _extract_results(df_processed, [k_col, d_col], original_time_index)

    # Count NaN values after calculation
    nan_counts_after = df_processed.isnull().sum()
    logger.debug(f"StochRSI calculation: After calculation NaN counts: {nan_counts_after.to_dict()}")
    logger.debug(f"StochRSI calculation: Final timestamp range: {df_processed.index.min()} to {df_processed.index.max()}")

    # pandas-ta creates columns in the format: STOCHRSIk_{stoch_period}_{rsi_period}_{k_period}_{d_period}
    # For parameters rsi_period=60, stoch_period=10, k_period=10, d_period=10
    # pandas-ta creates: STOCHRSIk_10_60_10_10
    k_col = f'STOCHRSIk_{stoch_period}_{rsi_period}_{k_period}_{d_period}'
    d_col = f'STOCHRSId_{stoch_period}_{rsi_period}_{k_period}_{d_period}'

    # Check if columns were actually created by pandas_ta
    if k_col not in df_processed.columns or d_col not in df_processed.columns:
        logger.warning(f"Stochastic RSI columns '{k_col}' or '{d_col}' not found in DataFrame after calculation. "
                      f"This might be due to insufficient data for the indicator periods. "
                      f"Available columns: {df_processed.columns.tolist()}")
        # Return placeholder data aligned with ALL original timestamps with expected keys
        # Add empty columns to df_processed to ensure _extract_results includes the expected keys
        df_processed[k_col] = np.nan
        df_processed[d_col] = np.nan
        return _extract_results(df_processed, [k_col, d_col], original_time_index)

    # DEBUG: Check DataFrame columns and lengths before extraction
    logger.debug(f"STOCHRSI DEBUG: DataFrame columns: {df_processed.columns.tolist()}")
    logger.debug(f"STOCHRSI DEBUG: K column '{k_col}' exists: {k_col in df_processed.columns}")
    logger.debug(f"STOCHRSI DEBUG: D column '{d_col}' exists: {d_col in df_processed.columns}")

    if k_col in df_processed.columns:
        k_non_null = df_processed[k_col].notna().sum()
        logger.debug(f"STOCHRSI DEBUG: K column length: {len(df_processed[k_col])}, non-null: {k_non_null}")

    if d_col in df_processed.columns:
        d_non_null = df_processed[d_col].notna().sum()
        logger.debug(f"STOCHRSI DEBUG: D column length: {len(df_processed[d_col])}, non-null: {d_non_null}")

    # Check for length mismatch before extraction
    if k_col in df_processed.columns and d_col in df_processed.columns:
        k_length = len(df_processed[k_col])
        d_length = len(df_processed[d_col])
        if k_length != d_length:
            logger.warning(f"STOCHRSI LENGTH MISMATCH: K has {k_length} values, D has {d_length} values")

            # Find the minimum length and truncate both to match
            min_length = min(k_length, d_length)
            logger.warning(f"STOCHRSI FIX: Truncating both K and D to {min_length} values")

            # Truncate the longer series to match the shorter one
            if k_length > min_length:
                df_processed[k_col] = df_processed[k_col].iloc[:min_length]
            if d_length > min_length:
                df_processed[d_col] = df_processed[d_col].iloc[:min_length]

            # Also truncate the DataFrame index to match
            df_processed = df_processed.iloc[:min_length]

    result = _extract_results(df_processed, [k_col, d_col], original_time_index)

    # INFO LOGGING FOR TROUBLESHOOTING - Show actual values being returned
    logger.info(f"🔍 STOCHRSI CALCULATION RESULT: rsi_period={rsi_period}, stoch_period={stoch_period}, k_period={k_period}, d_period={d_period}, total_points={len(result.get('t', []))}")
    logger.info(f"🔍 STOCHRSI K VALUES SAMPLE (last 5): {[f'{v:.2f}' if v is not None else 'None' for v in result.get('stoch_k', [])[-5:]]}")
    logger.info(f"🔍 STOCHRSI D VALUES SAMPLE (last 5): {[f'{v:.2f}' if v is not None else 'None' for v in result.get('stoch_d', [])[-5:]]}")
    logger.info(f"🔍 STOCHRSI TIMESTAMP SAMPLE (last 5): {[datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S') for ts in result.get('t', [])[-5:]]}")

    # Count non-null values
    stoch_k_values = result.get('stoch_k', [])
    stoch_d_values = result.get('stoch_d', [])
    stoch_k_non_null = sum(1 for v in stoch_k_values if v is not None)
    stoch_d_non_null = sum(1 for v in stoch_d_values if v is not None)
    logger.info(f"🔍 STOCHRSI NON-NULL VALUES: stoch_k={stoch_k_non_null}/{len(stoch_k_values)}, stoch_d={stoch_d_non_null}/{len(stoch_d_values)}")

    # 🚨 CRITICAL: Check for data lag
    current_time = datetime.now(timezone.utc)
    if result.get('t'):
        latest_data_timestamp = datetime.fromtimestamp(result['t'][-1], timezone.utc)
        time_diff_minutes = (current_time - latest_data_timestamp).total_seconds() / 60
        logger.warning(f"🚨 DATA LAG ALERT: Latest data is {time_diff_minutes:.1f} minutes old! Current time: {current_time.strftime('%H:%M:%S')}, Latest data: {latest_data_timestamp.strftime('%H:%M:%S')}")
        if time_diff_minutes > 60:  # More than 1 hour lag
            logger.error(f"🚨 CRITICAL DATA LAG: {time_diff_minutes:.1f} minutes! Check data source and WebSocket connection!")

    return result

def calculate_jma_indicator(df_input: pd.DataFrame, length: int = 7, phase: int = 50, power: int = 2) -> Dict[str, Any]:
    """Calculates the Jurik Moving Average (JMA) using the jurikIndicator.py module."""
    df = df_input.copy()
    original_time_index = df.index.to_series()

    # Count NaN values before calculation
    nan_counts_before = df.isnull().sum()
    logger.debug(f"JMA calculation: Input DataFrame shape: {df.shape}, NaN counts: {nan_counts_before.to_dict()}")
    logger.debug(f"JMA calculation: Input timestamp range: {df.index.min()} to {df.index.max()}")

    # CRITICAL: Ensure DataFrame maintains the exact same index throughout processing
    df_processed = df.copy()

    try:
        import jurikIndicator  # Import here to avoid circular dependency issues
        if not hasattr(jurikIndicator, 'calculate_jma'):
            logger.error("jurikIndicator.py does not have the 'calculate_jma' function. Returning empty subplots.")
            # Return placeholder data aligned with ALL original timestamps with expected keys
            # Add empty columns to df_processed to ensure _extract_results includes the expected keys
            df_processed['jma'] = np.nan
            df_processed['jma_up'] = np.nan
            df_processed['jma_down'] = np.nan
            return _extract_results(df_processed, ['jma', 'jma_up', 'jma_down'], original_time_index)

        jma_series = jurikIndicator.calculate_jma(df_processed['close'], length, phase, power)
        df_processed['jma'] = jma_series

        if 'jma' not in df_processed.columns:
            logger.warning("JMA column not found in DataFrame after calculation. Returning empty subplots.")
            # Return placeholder data aligned with ALL original timestamps with expected keys
            # Add empty columns to df_processed to ensure _extract_results includes the expected keys
            df_processed['jma'] = np.nan
            df_processed['jma_up'] = np.nan
            df_processed['jma_down'] = np.nan
            return _extract_results(df_processed, ['jma', 'jma_up', 'jma_down'], original_time_index)

        df_processed['jma_up'] = np.where(df_processed['jma'] > df_processed['jma'].shift(1), df_processed['jma'], np.nan)
        df_processed['jma_down'] = np.where(df_processed['jma'] < df_processed['jma'].shift(1), df_processed['jma'], np.nan)

        # Count NaN values after calculation
        nan_counts_after = df_processed.isnull().sum()
        logger.debug(f"JMA calculation: After calculation NaN counts: {nan_counts_after.to_dict()}")
        logger.debug(f"JMA calculation: Final timestamp range: {df_processed.index.min()} to {df_processed.index.max()}")

        return _extract_results(df_processed, ['jma', 'jma_up', 'jma_down'], original_time_index)

    except ImportError:
        logger.error("Could not import jurikIndicator.py module. Returning empty subplots.")
        # Return placeholder data aligned with ALL original timestamps with expected keys
        # Add empty columns to df_processed to ensure _extract_results includes the expected keys
        df_processed['jma'] = np.nan
        df_processed['jma_up'] = np.nan
        df_processed['jma_down'] = np.nan
        return _extract_results(df_processed, ['jma', 'jma_up', 'jma_down'], original_time_index)

def calculate_rsi_sma(df_input: pd.DataFrame, sma_period: int, rsi_values: List[float]) -> Dict[str, Any]:
    df = df_input.copy()
    original_time_index = df.index.to_series()  # Store original index

    if len(rsi_values) < len(df.index):  # RSI values are shorter, pad with NaNs
        padding = [np.nan] * (len(df.index) - len(rsi_values))
        aligned_rsi_values = rsi_values + padding
        logger.warning(f"calculate_rsi_sma: Padding rsi_values (from {len(rsi_values)} to {len(aligned_rsi_values)}) with NaNs to match DataFrame index.")
    elif len(rsi_values) > len(df.index):  # RSI values are longer, truncate
        aligned_rsi_values = rsi_values[:len(df.index)]
        logger.warning(f"calculate_rsi_sma: Truncating rsi_values (from {len(rsi_values)} to {len(aligned_rsi_values)}) to match DataFrame index.")
    else:
        aligned_rsi_values = rsi_values  # Lengths already match

    # Now, assign to the DataFrame
    df['rsi'] = aligned_rsi_values
    logger.debug(f"calculate_rsi_sma: Assigned RSI column of length {len(df['rsi'])} (index length: {len(df.index)}) to DataFrame.")

    df[f'RSI_SMA_{sma_period}'] = df['rsi'].rolling(window=sma_period).mean()
    return _extract_results(df, [f'RSI_SMA_{sma_period}'], original_time_index)

def find_buy_signals(df: pd.DataFrame) -> list:
    """
    Finds buy signals based on RSI + StochRSI conditions.
    Signal conditions:
    - RSI below 40
    - All StochRSI K below 20 in a 10-bar range that includes the RSI point
    """
    logger.debug("Starting find_buy_signals with RSI + StochRSI detection")
    signals = []

    # Reset index for easy access
    df = df.reset_index()

    # Define the date range for focused logging (timezone-naive to match DataFrame index)
    target_date_start = pd.to_datetime("2025-09-15 00:00:00")
    target_date_end = pd.to_datetime("2025-09-16 23:59:59")
    logger.debug(f"Enhanced logging for September 15-16, 2025: {target_date_start} to {target_date_end}")

    # Debug: Check what dates are actually in the DataFrame
    df_dates = df['time'].dt.date.unique()
    logger.debug(f"DataFrame contains dates: {sorted(df_dates)[:5]} ... {sorted(df_dates)[-5:]}")
    logger.debug(f"Total unique dates in DataFrame: {len(df_dates)}")

    # Check if September 15th is in the data
    sept_15_data = df[df['time'].dt.date == pd.to_datetime("2025-09-15").date()]
    logger.debug(f"Bars on September 15, 2025: {len(sept_15_data)}")
    if len(sept_15_data) > 0:
        logger.debug(f"September 15 time range: {sept_15_data['time'].min()} to {sept_15_data['time'].max()}")
        sept_15_22 = sept_15_data[(sept_15_data['time'].dt.hour == 22)]
        logger.debug(f"Bars at 22:00 on September 15: {len(sept_15_22)}")
        if len(sept_15_22) > 0:
            logger.debug(f"22:00 bar timestamp: {sept_15_22['time'].iloc[0]}")

    for i in range(len(df)):
        # Ensure current_time is timezone-aware (UTC) for comparison
        current_time = df['time'].iloc[i]
        is_target_date = target_date_start <= current_time <= target_date_end

        # Check if RSI is below 40 (condition 1)
        rsi_value = df['RSI_14'].iloc[i] if 'RSI_14' in df.columns else None
        rsi_below_40 = rsi_value is not None and rsi_value < 40

        if rsi_below_40:
            # Define range for StochRSI check: 10 bars including current (i-9 to i)
            win_start = max(0, i - 9)
            window = df.iloc[win_start : i + 1]

            # Check ALL StochRSI indicators (4 different parameter sets)
            stoch_indicators = [
                ('STOCHRSIk_9_9_3_3', 'STOCHRSId_9_9_3_3'),      # stochrsi_9_3
                ('STOCHRSIk_14_14_3_3', 'STOCHRSId_14_14_3_3'),  # stochrsi_14_3
                ('STOCHRSIk_40_40_4_4', 'STOCHRSId_40_40_4_4'),  # stochrsi_40_4
                ('STOCHRSIk_10_60_10_10', 'STOCHRSId_10_60_10_10') # stochrsi_60_10
            ]

            # Check if ALL StochRSI K indicators have ANY value below 20 in the SAME window
            all_stoch_k_below_10 = True
            stoch_k_details = []  # For debugging
            for k_col, d_col in stoch_indicators:
                if k_col in window.columns:
                    stoch_k_values = window[k_col]

                    # Check for NaN values
                    stoch_k_has_nan = stoch_k_values.isna().any()

                    # K must have ANY value below 10
                    k_below_10 = (stoch_k_values < 10).any() if not stoch_k_has_nan else False

                    # Store details for debugging
                    stoch_k_details.append({
                        'indicator': k_col,
                        'values': stoch_k_values.tolist(),
                        'has_nan': stoch_k_has_nan,
                        'below_10': k_below_10,
                        'min_value': stoch_k_values.min() if not stoch_k_has_nan else None
                    })

                    # This indicator's K must be below 10
                    if not k_below_10:
                        all_stoch_k_below_10 = False
                        break
                else:
                    # If any indicator K column is missing, condition fails
                    stoch_k_details.append({
                        'indicator': k_col,
                        'values': None,
                        'has_nan': None,
                        'below_10': False,
                        'min_value': None
                    })
                    all_stoch_k_below_10 = False
                    break

            # Print StochRSI values for debugging when RSI < 40
            if is_target_date:
                print(f"\n🔍 STOCHRSI DEBUG at {current_time}:")
                print(f"  RSI: {rsi_value:.2f} (< 40: {rsi_below_40})")
                for detail in stoch_k_details:
                    if detail['values'] is not None:
                        values_str = [f"{v:.2f}" if v is not None and not pd.isna(v) else "NaN" for v in detail['values']]
                        print(f"  {detail['indicator']}: [{', '.join(values_str)}] | Min: {detail['min_value']:.2f if detail['min_value'] is not None else 'NaN'} | <10: {detail['below_10']}")
                    else:
                        print(f"  {detail['indicator']}: MISSING")
                print(f"  ALL StochRSI K < 10: {all_stoch_k_below_10}")
                print(f"  SIGNAL CONDITION MET: {signal_condition_met}")

            # Signal condition: RSI < 40 AND all StochRSI K < 20 in 10-bar window
            signal_condition_met = rsi_below_40 and all_stoch_k_below_10

            if signal_condition_met:
                # Check if this is the first signal for this oversold period
                # (i.e., previous bar with RSI < 40 didn't generate a signal)
                prev_signal_generated = False
                if i > 0:
                    # Look back up to 10 bars to see if we already signaled recently
                    for j in range(max(0, i-10), i):
                        prev_rsi = df['RSI_14'].iloc[j] if 'RSI_14' in df.columns else None
                        if prev_rsi is not None and prev_rsi < 40:
                            prev_win_start = max(0, j - 9)
                            prev_window = df.iloc[prev_win_start : j + 1]
                            prev_all_stoch_k_below_10 = True
                            for k_col, d_col in stoch_indicators:
                                if k_col in prev_window.columns:
                                    prev_stoch_k_values = prev_window[k_col]
                                    prev_stoch_k_has_nan = prev_stoch_k_values.isna().any()
                                    prev_k_below_10 = (prev_stoch_k_values < 10).any() if not prev_stoch_k_has_nan else False
                                    if not prev_k_below_10:
                                        prev_all_stoch_k_below_10 = False
                                        break
                                else:
                                    prev_all_stoch_k_below_10 = False
                                    break
                            if prev_all_stoch_k_below_10:
                                prev_signal_generated = True
                                break

                # Only generate signal if no recent signal was generated
                if not prev_signal_generated:
                    timestamp = int(df['time'].iloc[i].timestamp())
                    signals.append({
                        'timestamp': timestamp,
                        'price': df['close'].iloc[i],
                        'type': 'buy'
                    })
                    logger.info(f"BUY SIGNAL DETECTED at {current_time}: timestamp={timestamp}, "
                               f"price={df['close'].iloc[i]:.2f}, RSI={rsi_value:.2f}")
                    logger.info(f"  RSI < 40 and all StochRSI K < 10 in 10-bar window")
                else:
                    if is_target_date:
                        logger.debug(f"Bar {i} at {current_time}: Signal conditions met but recent signal already generated")
            else:
                if is_target_date:
                    # Show StochRSI details for debugging
                    stoch_debug_info = []
                    for detail in stoch_k_details:
                        if detail['values'] is not None:
                            values_str = [f"{v:.2f}" if v is not None and not pd.isna(v) else "NaN" for v in detail['values']]
                            stoch_debug_info.append(f"{detail['indicator'].split('_')[1]}: [{', '.join(values_str[-3:])}] min={detail['min_value']:.2f if detail['min_value'] is not None else 'NaN'}")
                        else:
                            stoch_debug_info.append(f"{detail['indicator']}: MISSING")

                    rsi_display = f"{rsi_value:.2f}" if rsi_value is not None else "N/A"
                    logger.debug(f"Bar {i} at {current_time}: RSI={rsi_display}, rsi_below_40={rsi_below_40}, all_stoch_k_below_20={all_stoch_k_below_10}")
                    logger.debug(f"  StochRSI details: {' | '.join(stoch_debug_info)}")
        else:
            if is_target_date:
                rsi_display = f"{rsi_value:.2f}" if rsi_value is not None else "N/A"
                logger.debug(f"Bar {i} at {current_time}: RSI={rsi_display}, rsi_below_40={rsi_below_40}")

    logger.debug(f"Total buy signals detected: {len(signals)}")
    return signals

def format_indicator_data_for_llm_as_dict(indicator_id: str, indicator_config_details: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Formats indicator data into a dictionary structure suitable for JSON embedding.
    data is like {'t': [...], 'value1': [...], 'value2': [...], 's': 'ok'}
    indicator_config_details is from AVAILABLE_INDICATORS
    """

    if not data or not data.get('t') or data.get('s') != 'ok':
        return {
            "indicator_name": indicator_config_details['name'],
            "params": indicator_config_details['params'],
            "status": "no_data",
            "error_message": "No valid data available for the selected range.",
            "values": []
        }

    # Determine column names from data keys, excluding 't', 's', 'errmsg'
    value_keys = [k for k in data.keys() if k not in ['t', 's', 'errmsg']]

    # Map internal keys to more readable names
    column_names_map = {
        "macd": "MACD", "signal": "Signal", "histogram": "Histogram",
        "rsi": "RSI",
        "rsi_sma14": "RSI SMA14",
        "open_interest": "OpenInterest",
        "jma": "JMA",  # Add JMA
        "stoch_k": "StochK", "stoch_d": "StochD"
    }

    timestamps = data['t']
    values_by_key = {key: data[key] for key in value_keys}

    formatted_values = []
    for i, ts in enumerate(timestamps):
        dt_object = datetime.fromtimestamp(ts, timezone.utc)
        record: Dict[str, Any] = {"timestamp": dt_object.strftime('%Y-%m-%d %H:%M:%S')}
        for current_key in value_keys:
            value = values_by_key[current_key][i] if i < len(values_by_key[current_key]) else None  # Use None for N/A
            record[column_names_map.get(current_key, current_key.capitalize())] = value
        formatted_values.append(record)

    return {
        "indicator_name": indicator_config_details['name'],
        "params": indicator_config_details['params'],
        "status": "ok",
        "values": formatted_values
    }


def fetch_open_interest_from_bybit(symbol: str, interval: str, start_ts: int, end_ts: int) -> list[Dict[str, Any]]:
    """Fetches Open Interest data from Bybit."""

    #logger.info(f"Fetching Open Interest for {symbol} {interval} from {datetime.fromtimestamp(start_ts, timezone.utc)} to {datetime.fromtimestamp(end_ts, timezone.utc)}")
    all_oi_data: list[Dict[str, Any]] = []
    current_start = start_ts
    batch_count = 0
    total_entries_received = 0

    # Bybit's get_open_interest intervalTime parameter has specific values.
    # We assume TRADING_TIMEFRAME (e.g., "5m") maps to a valid intervalTime like "5min".
    # This mapping needs to be consistent with what Bybit's API expects for `intervalTime`.
    oi_interval_map = {"1m": "5min", "5m": "5min", "1h": "1h", "1d": "1d", "1w": "1d"} # "1w" might need "1d" OI
    bybit_oi_interval = oi_interval_map.get(interval, "5min") # Default to 5min if not found

    # Convert interval string to seconds for calculation (e.g., "5min" -> 300 seconds)
    oi_interval_seconds_map = {"5min": 300, "15min": 900, "30min": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
    interval_seconds = oi_interval_seconds_map.get(bybit_oi_interval)
    if not interval_seconds:
        logger.error(f"Unsupported Open Interest interval for calculation: {bybit_oi_interval}")
        return []

    while current_start < end_ts:
        batch_count += 1
        # Bybit get_open_interest limit is 200 per request
        batch_end = min(current_start + (200 * interval_seconds) - 1, end_ts)

        try:
            response = session.get_open_interest(
                category="linear", # Assuming linear perpetuals
                symbol=symbol,
                intervalTime=bybit_oi_interval, # Use the string interval like "5min"
                start=current_start * 1000, # Bybit expects milliseconds
                end=batch_end * 1000,       # Bybit expects milliseconds
                limit=200
            )
        except Exception as e:
            logger.error(f"Bybit API request for Open Interest failed for {symbol} {interval} batch #{batch_count}: {e}")
            break

        if response.get("retCode") != 0:
            logger.error(f"Bybit API error for Open Interest {symbol} {interval} batch #{batch_count}: {response.get('retMsg', 'Unknown error')} (retCode: {response.get('retCode')})")
            break

        list_data = response.get("result", {}).get("list", [])
        if not list_data:
            logger.info(f"No more Open Interest data available from Bybit for {symbol} {interval} at batch #{batch_count}")
            break

        total_entries_received += len(list_data)

        # Data is usually newest first, reverse to get chronological order
        batch_oi = []
        for item in reversed(list_data):
            batch_oi.append({
                "time": int(item["timestamp"]) // 1000, # Convert ms to seconds
                "open_interest": float(item["openInterest"])
            })
        all_oi_data.extend(batch_oi)

        if not batch_oi or len(list_data) < 200: # No more data or last page
            logger.debug(f"Stopping Open Interest batch fetch for {symbol} {interval}: received {len(list_data)} entries (less than 200) or no data processed")
            break

        # Next query starts after the last fetched item's timestamp
        last_fetched_ts_in_batch = batch_oi[-1]["time"]
        current_start = last_fetched_ts_in_batch + interval_seconds

    all_oi_data.sort(key=lambda x: x["time"]) # Ensure chronological order
    #logger.info(f"Completed Bybit Open Interest fetch for {symbol} {interval}: {batch_count} batches, {total_entries_received} total entries received, {len(all_oi_data)} entries processed")
    return all_oi_data

def validate_indicator_data_alignment(test_result: Dict[str, Any], original_ohlc_length: int, indicator_name: str) -> bool:
    """
    Validates that indicator data has NO null values.

    Args:
        test_result: The indicator calculation result dictionary
        original_ohlc_length: The length of the original OHLC data (unused - no alignment check)
        indicator_name: Name of the indicator for logging

    Returns:
        bool: True if validation passes (no null values), False otherwise
    """
    if not test_result or not isinstance(test_result, dict):
        logger.error(f"❌ VALIDATION FAILED: {indicator_name} - Invalid result format")
        return False

    # Get all data series (excluding timestamps and status fields)
    data_keys = [k for k in test_result.keys() if k not in ['t', 's', 'errmsg']]

    if not data_keys:
        logger.error(f"❌ VALIDATION FAILED: {indicator_name} - No data series found")
        return False

    total_nulls = 0
    total_points = 0

    for key in data_keys:
        data_series = test_result.get(key, [])

        # Count null values
        null_count = sum(1 for v in data_series if v is None)
        total_nulls += null_count
        total_points += len(data_series)

        if null_count > 0:
            logger.warning(f"⚠️ VALIDATION WARNING: {indicator_name} - Data series '{key}' has {null_count} null values out of {len(data_series)} total")

    # Strict validation: NO null values allowed
    if total_nulls > 0:
        logger.error(f"❌ VALIDATION FAILED: {indicator_name} - Found {total_nulls} null values out of {total_points} total data points. All indicators must have 0 null values.")
        return False

    logger.info(f"✅ VALIDATION PASSED: {indicator_name} - All {total_points} data points are non-null across {len(data_keys)} series")
    return True
