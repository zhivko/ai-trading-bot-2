# Technical indicator calculations

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from config import AVAILABLE_INDICATORS, session
from logging_config import logger
from datetime import datetime, timezone

def get_timeframe_seconds(timeframe: str) -> int:
    multipliers = {"1m": 60, "5m": 300, "1h": 3600, "1d": 86400, "1w": 604800}
    return multipliers.get(timeframe, 3600)

def _prepare_dataframe(klines: List[Dict[str, Any]], open_interest_data: List[Dict[str, Any]]) -> Optional[pd.DataFrame]:
    if not klines:
        return None

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

    # Merge klines and Open Interest data
    if not df_oi.empty:
        df_merged = pd.merge(df_klines, df_oi[['open_interest']], left_index=True, right_index=True, how='left')
        df_merged['open_interest'] = df_merged['open_interest'].ffill().bfill().fillna(0)
        return df_merged
    else:
        df_klines['open_interest'] = 0.0
        return df_klines

def _extract_results(df: pd.DataFrame, columns: List[str], original_time_index: pd.Series) -> Dict[str, Any]:
    """Extracts specified columns and aligns with original time index, handling NaNs by omission."""
    data_dict: Dict[str, Any] = {"t": []}

    # Create a temporary DataFrame with only the required columns and the original time index
    temp_df = df[columns].copy()
    temp_df['original_time'] = original_time_index

    # Drop rows where ALL specified indicator columns are NaN
    # This keeps rows if at least one indicator value is present
    temp_df.dropna(subset=columns, how='all', inplace=True)

    data_dict["t"] = (temp_df['original_time'].astype('int64') // 10**9).tolist()  # Convert ns to s
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
        elif "rsi" in col.lower() and "stoch" not in col.lower():
            simple_col_name = "rsi"
        elif "open_interest" in col.lower():
            simple_col_name = "open_interest"
        elif "jma_up" in col.lower():
            simple_col_name = "jma_up"
        elif "jma_down" in col.lower():
            simple_col_name = "jma_down"
        elif "jma" in col.lower() and "jma_up" not in col.lower() and "jma_down" not in col.lower():
            simple_col_name = "jma"  # Add JMA

        # Convert NaN to None for JSON compatibility
        raw_values = temp_df[col].tolist()
        processed_values = [None if pd.isna(val) else val for val in raw_values]
        data_dict[simple_col_name] = processed_values
    return data_dict

def calculate_open_interest(df_input: pd.DataFrame) -> Dict[str, Any]:
    df = df_input.copy()
    original_time_index = df.index.to_series()
    oi_col = 'open_interest'  # This column should already exist from _prepare_dataframe
    if oi_col not in df.columns:
        logger.warning(f"Open Interest column '{oi_col}' not found in DataFrame. Cannot calculate.")
        return {"t": [], "open_interest": []}
    return _extract_results(df, [oi_col], original_time_index)

def calculate_macd(df_input: pd.DataFrame, short_period: int, long_period: int, signal_period: int) -> Dict[str, Any]:
    df = df_input.copy()
    original_time_index = df.index.to_series()  # Keep original timestamps before any drops
    df.ta.macd(fast=short_period, slow=long_period, signal=signal_period, append=True)
    macd_col = f'MACD_{short_period}_{long_period}_{signal_period}'
    signal_col = f'MACDs_{short_period}_{long_period}_{signal_period}'
    hist_col = f'MACDh_{short_period}_{long_period}_{signal_period}'

    # Check if columns were actually created by pandas_ta
    if not all(col in df.columns for col in [macd_col, signal_col, hist_col]):
        logger.warning(f"MACD columns not found in DataFrame. Expected: {macd_col}, {signal_col}, {hist_col}. "
                      f"This might be due to insufficient data for the indicator periods. Available columns: {df.columns.tolist()}")
        return {"t": [], "macd": [], "signal": [], "histogram": []}  # Return empty data structure
    return _extract_results(df, [macd_col, signal_col, hist_col], original_time_index)

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

    # 1️⃣ Compute the raw RSI
    df.ta.rsi(length=period, append=True)
    rsi_col = f"RSI_{period}"
    if rsi_col not in df.columns:
        logger.warning(
            f"RSI column '{rsi_col}' not found – maybe not enough data."
        )
        return {"t": [], "rsi": [], "rsi_sma14": []}

    # 2️⃣ Compute SMA‑14 of that RSI
    sma_col = f"RSI_{period}_sma14"
    df[sma_col] = df[rsi_col].rolling(window=14).mean()

    # 3️⃣ Return both columns via _extract_results
    return _extract_results(df, [rsi_col, sma_col], original_time_index)

def calculate_stoch_rsi(df_input: pd.DataFrame, rsi_period: int, stoch_period: int, k_period: int, d_period: int) -> Dict[str, Any]:
    df = df_input.copy()
    original_time_index = df.index.to_series()
    # pandas-ta uses rsi_length, roc_length (for stoch_period), k, d
    df.ta.stochrsi(rsi_length=rsi_period, length=stoch_period, k=k_period, d=d_period, append=True)
    k_col = f'STOCHRSIk_{rsi_period}_{stoch_period}_{k_period}_{d_period}'
    d_col = f'STOCHRSId_{rsi_period}_{stoch_period}_{k_period}_{d_period}'

    # Check if columns were actually created by pandas_ta
    if k_col not in df.columns or d_col not in df.columns:
        logger.warning(f"Stochastic RSI columns '{k_col}' or '{d_col}' not found in DataFrame after calculation. "
                      f"This might be due to insufficient data for the indicator periods. "
                      f"Available columns: {df.columns.tolist()}")
        return {"t": [], "stoch_k": [], "stoch_d": []}  # Return empty data structure

    return _extract_results(df, [k_col, d_col], original_time_index)

def calculate_jma_indicator(df_input: pd.DataFrame, length: int = 7, phase: int = 50, power: int = 2) -> Dict[str, Any]:
    """Calculates the Jurik Moving Average (JMA) using the jurikIndicator.py module."""
    try:
        import jurikIndicator  # Import here to avoid circular dependency issues
        if not hasattr(jurikIndicator, 'calculate_jma'):

            logger.error("jurikIndicator.py does not have the 'calculate_jma' function.")
            return {"t": [], "jma": []}
        df = df_input.copy()
        original_time_index = df.index.to_series()
        jma_series = jurikIndicator.calculate_jma(df['close'], length, phase, power)
        df['jma'] = jma_series
        if 'jma' not in df.columns:
            return {"t": [], "jma": [], "jma_up": [], "jma_down": []}

        df['jma_up'] = np.where(df['jma'] > df['jma'].shift(1), df['jma'], np.nan)
        df['jma_down'] = np.where(df['jma'] < df['jma'].shift(1), df['jma'], np.nan)

        return _extract_results(df, ['jma', 'jma_up', 'jma_down'], original_time_index)
    except ImportError:
        logger.error("Could not import jurikIndicator.py module.")
        return {"t": [], "jma": []}

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
    Finds buy signals based on "buy the dip in a downtrend" logic, with relaxed conditions
    allowing key events to occur within a 10-bar window.

    Key events (conditions that may not happen on the same bar):
    - RSI_SMA_3 crosses above RSI_SMA_5
    - RSI_SMA_3 crosses above RSI_SMA_10
    - RSI_SMA_3 crosses above RSI_SMA_20
    - StochRSI K crosses above D
    """
    logger.debug("Starting find_buy_signals with enhanced logging for diagnosis")
    signals = []

    # Reset index for easy access
    df = df.reset_index()

    # Define the date range for focused logging (e.g., April 5th to April 7th)
    target_date_start = pd.to_datetime("2025-08-12", utc=True)
    target_date_end = pd.to_datetime("2025-08-14", utc=True)
    logger.debug(f"Enhanced logging for date range: {target_date_start} to {target_date_end}")

    # Define key event flags (crossovers)
    df['cross_3_5'] = ((df['RSI_SMA_3'] > df['RSI_SMA_5']) &
                       (df['RSI_SMA_3'].shift(1) <= df['RSI_SMA_5'].shift(1))).fillna(False)
    df['cross_3_10'] = ((df['RSI_SMA_3'] > df['RSI_SMA_10']) &
                         (df['RSI_SMA_3'].shift(1) <= df['RSI_SMA_10'].shift(1))).fillna(False)
    df['cross_3_20'] = ((df['RSI_SMA_3'] > df['RSI_SMA_20']) &
                         (df['RSI_SMA_3'].shift(1) <= df['RSI_SMA_20'].shift(1))).fillna(False)
    df['stoch_cross'] = ((df['STOCHRSIk_60_60_10_10'] > df['STOCHRSId_60_60_10_10']) &
                          (df['STOCHRSIk_60_60_10_10'].shift(1) <= df['STOCHRSId_60_60_10_10'].shift(1))).fillna(False)

    # Define state flags
    df['downtrend'] = ((df['EMA_21'] < df['EMA_50']) &
                       (df['EMA_50'] < df['EMA_200']) &
                       (df['close'] < df['EMA_200'])).fillna(False)
    df['oversold'] = ((df['RSI_14'] < 30) &
                       (df['STOCHRSIk_60_60_10_10'] < 20)).fillna(False)

    # Required events for the relaxed condition
    required_events = ['cross_3_5', 'cross_3_10', 'cross_3_20', 'stoch_cross']

    # Log counts of each condition across the entire dataset
    logger.debug(f"Total bars in DataFrame: {len(df)}")
    logger.debug(f"cross_3_5 occurrences: {df['cross_3_5'].sum()}")
    logger.debug(f"cross_3_10 occurrences: {df['cross_3_10'].sum()}")
    logger.debug(f"cross_3_20 occurrences: {df['cross_3_20'].sum()}")
    logger.debug(f"stoch_cross occurrences: {df['stoch_cross'].sum()}")
    logger.debug(f"downtrend occurrences: {df['downtrend'].sum()}")
    logger.debug(f"oversold occurrences: {df['oversold'].sum()}")

    # Save DataFrame with all indicators and conditions to CSV for inspection - DISABLED
    # debug_csv_filename = f"buy_signals_debug_df_{df['time'].iloc[0].strftime('%Y%m%d')}_to_{df['time'].iloc[-1].strftime('%Y%m%d')}.csv"
    # df.to_csv(debug_csv_filename, index=False)
    # logger.debug(f"Saved DataFrame with indicators and conditions to: {debug_csv_filename}")

    for i in range(0, len(df)):
        # Ensure current_time is timezone-aware (UTC) for comparison
        current_time = df['time'].iloc[i].tz_localize('UTC')
        # Check if the current bar is within the target date range for detailed logging
        is_target_date = target_date_start <= current_time <= target_date_end

        # Current window: max 10 bars ending at i
        win_start = max(0, i - 9)
        window = df.iloc[win_start : i + 1]

        # Check if all required events have occurred at least once in the window
        has_all_events = all(window[event].any() for event in required_events)

        # Check states in the window
        has_downtrend = window['downtrend'].any()
        has_oversold = window['oversold'].any()

        # Log details for bars around April 6th
        if is_target_date:
            logger.debug(f"Bar {i} at {current_time}:")
            logger.debug(f"  RSI_SMA_3={df['RSI_SMA_3'].iloc[i]:.2f}, RSI_SMA_5={df['RSI_SMA_5'].iloc[i]:.2f}, "
                        f"RSI_SMA_10={df['RSI_SMA_10'].iloc[i]:.2f}, RSI_SMA_20={df['RSI_SMA_20'].iloc[i]:.2f}")
            logger.debug(f"  STOCHRSIk={df['STOCHRSIk_60_60_10_10'].iloc[i]:.2f}, "
                        f"STOCHRSId={df['STOCHRSId_60_60_10_10'].iloc[i]:.2f}")
            logger.debug(f"  EMA_21={df['EMA_21'].iloc[i]:.2f}, EMA_50={df['EMA_50'].iloc[i]:.2f}, "
                        f"EMA_200={df['EMA_200'].iloc[i]:.2f}, close={df['close'].iloc[i]:.2f}")
            logger.debug(f"  Conditions: cross_3_5={df['cross_3_5'].iloc[i]}, "
                        f"cross_3_10={df['cross_3_10'].iloc[i]}, "
                        f"cross_3_20={df['cross_3_20'].iloc[i]}, "
                        f"stoch_cross={df['stoch_cross'].iloc[i]}")
            logger.debug(f"  States: downtrend={df['downtrend'].iloc[i]}, oversold={df['oversold'].iloc[i]}")
            logger.debug(f"  Window ({len(window)} bars): has_all_events={has_all_events}, "
                        f"has_downtrend={has_downtrend}, has_oversold={has_oversold}")
            logger.debug(f"  Window event counts: cross_3_5={window['cross_3_5'].sum()}, "
                        f"cross_3_10={window['cross_3_10'].sum()}, "
                        f"cross_3_20={window['cross_3_20'].sum()}, "
                        f"stoch_cross={window['stoch_cross'].sum()}")

        if has_all_events and has_downtrend and has_oversold:
            # Check previous window (up to i-1, max 10 bars)
            prev_start = max(0, i - 10)
            prev_window = df.iloc[prev_start : i]

            # If no previous bars, consider it as not having all
            if len(prev_window) == 0:
                had_all_prev = False
            else:
                had_all_prev = all(prev_window[event].any() for event in required_events)

            # Signal if this is the first bar where all events are covered in the window
            if not had_all_prev:
                timestamp = int(df['time'].iloc[i].timestamp())
                signals.append({
                    'timestamp': timestamp,
                    'price': df['close'].iloc[i],
                    'type': 'buy'
                })
                if is_target_date:
                    logger.debug(f"BUY SIGNAL DETECTED at {current_time}: timestamp={timestamp}, "
                                f"price={df['close'].iloc[i]:.2f}")

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

    logger.info(f"Fetching Open Interest for {symbol} {interval} from {datetime.fromtimestamp(start_ts, timezone.utc)} to {datetime.fromtimestamp(end_ts, timezone.utc)}")
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
        logger.debug(f"Fetching OI batch #{batch_count} for {symbol} {interval}: {datetime.fromtimestamp(current_start, timezone.utc)} to {datetime.fromtimestamp(batch_end, timezone.utc)}")

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

        logger.debug(f"Received {len(list_data)} Open Interest entries from Bybit for {symbol} {interval} batch #{batch_count}")
        total_entries_received += len(list_data)

        # Data is usually newest first, reverse to get chronological order
        batch_oi = []
        for item in reversed(list_data):
            batch_oi.append({
                "time": int(item["timestamp"]) // 1000, # Convert ms to seconds
                "open_interest": float(item["openInterest"])
            })
        all_oi_data.extend(batch_oi)

        logger.debug(f"Processed batch #{batch_count} for {symbol} {interval}: {len(batch_oi)} Open Interest entries, last timestamp: {datetime.fromtimestamp(batch_oi[-1]['time'], timezone.utc) if batch_oi else 'N/A'}")

        if not batch_oi or len(list_data) < 200: # No more data or last page
            logger.debug(f"Stopping Open Interest batch fetch for {symbol} {interval}: received {len(list_data)} entries (less than 200) or no data processed")
            break

        # Next query starts after the last fetched item's timestamp
        last_fetched_ts_in_batch = batch_oi[-1]["time"]
        current_start = last_fetched_ts_in_batch + interval_seconds

    all_oi_data.sort(key=lambda x: x["time"]) # Ensure chronological order
    logger.info(f"Completed Bybit Open Interest fetch for {symbol} {interval}: {batch_count} batches, {total_entries_received} total entries received, {len(all_oi_data)} entries processed")
    return all_oi_data