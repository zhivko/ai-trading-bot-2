# Indicator-related API endpoints

import json
from datetime import datetime, timezone
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from config import SUPPORTED_SYMBOLS, timeframe_config, AVAILABLE_INDICATORS
from redis_utils import get_cached_klines, cache_klines, get_cached_open_interest, cache_open_interest
from indicators import (
    _prepare_dataframe, calculate_macd, calculate_rsi, calculate_stoch_rsi,
    calculate_open_interest, calculate_jma_indicator, format_indicator_data_for_llm_as_dict,
    get_timeframe_seconds
)
from logging_config import logger

from redis_utils import fetch_klines_from_bybit


async def indicator_history_endpoint(symbol: str, resolution: str, from_ts: int, to_ts: int, indicator_id: str, simulation: bool = False):
    return await get_indicator_history(symbol, resolution, from_ts, to_ts, indicator_id, simulation)

async def get_indicator_history(symbol: str, resolution: str, from_ts: int, to_ts: int, indicator_id: str, simulation: bool = False):
    return await _get_indicator_history_implementation(symbol, resolution, from_ts, to_ts, indicator_id, simulation)

async def _get_indicator_history_implementation(symbol: str, resolution: str, from_ts: int, to_ts: int, indicator_id: str, simulation: bool = False):
    """
    Internal implementation for indicator history, refactored to handle JMA and other indicators.
    This version receives the indicator configuration details as a dictionary, improving flexibility.
    """

    # Split indicator_id to handle multiple indicators
    requested_indicator_ids = [id_str.strip() for id_str in indicator_id.split(',') if id_str.strip()]

    return await _calculate_and_return_indicators(symbol, resolution, from_ts, to_ts, requested_indicator_ids, simulation, indicator_id)

async def _calculate_and_return_indicators(symbol: str, resolution: str, from_ts: int, to_ts: int, requested_indicator_ids: list[str], simulation: bool = False, indicator_id: str = None):
    """
    Core logic to fetch klines, calculate indicators (including JMA), and return the results.
    """

    # indicator_id is now expected to be a comma-separated string of IDs
    logger.info(f"/indicatorHistory request: symbol={symbol}, resolution={resolution}, from_ts={from_ts}, to_ts={to_ts}, requested_ids={requested_indicator_ids}, simulation={simulation}")

    # Log from_ts and to_ts in human-readable format
    from_dt_str = datetime.fromtimestamp(from_ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    to_dt_str = datetime.fromtimestamp(to_ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    logger.info(f"Time range: from_ts={from_ts} ({from_dt_str}), to_ts={to_ts} ({to_dt_str})")

    if symbol not in SUPPORTED_SYMBOLS:
        return JSONResponse({"s": "error", "errmsg": f"Unsupported symbol: {symbol}"}, status_code=400)
    if resolution not in timeframe_config.supported_resolutions:
        return JSONResponse({"s": "error", "errmsg": f"Unsupported resolution: {resolution}"}, status_code=400)

    if not requested_indicator_ids:
        # Log from_ts and to_ts in human-readable format
        from_dt_str = datetime.fromtimestamp(from_ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        to_dt_str = datetime.fromtimestamp(to_ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        logger.info(f"Time range: from_ts={from_ts} ({from_dt_str}), to_ts={to_ts} ({to_dt_str})")

    # Validate all requested indicator IDs
    for req_id in requested_indicator_ids:
        if not next((item for item in AVAILABLE_INDICATORS if item["id"] == req_id), None):
            print(req_id)
            return JSONResponse({"s": "error", "errmsg": f"Unsupported indicator ID found: {req_id}"}, status_code=400)

    # Unconditionally calculate lookback needed for accurate indicator calculation
    max_lookback_periods = 0
    for req_id in requested_indicator_ids:
        config = next((item for item in AVAILABLE_INDICATORS if item["id"] == req_id), None)
        if config:
            current_indicator_lookback = 0
            if config["id"] == "macd":
                current_indicator_lookback = config["params"]["long_period"] + config["params"]["signal_period"]
            elif config["id"] == "rsi":
                current_indicator_lookback = config["params"]["period"]
            elif config["id"] == "open_interest":
                current_indicator_lookback = 0 # No specific lookback for OI itself
            elif config["id"].startswith("stochrsi"):
                current_indicator_lookback = config["params"]["rsi_period"] + config["params"]["stoch_period"] + config["params"]["d_period"]
            elif config["id"] == "jma":
                current_indicator_lookback = config["params"]["length"]  # JMA Length
            if current_indicator_lookback > max_lookback_periods:
                max_lookback_periods = current_indicator_lookback

    buffer_candles = 1
    min_overall_candles = 1
    lookback_candles_needed = max(max_lookback_periods + buffer_candles, min_overall_candles)
    timeframe_secs = get_timeframe_seconds(resolution)

    # Determine the kline fetch window based on lookback and original request's to_ts
    # The data for calculation must extend up to the original 'to_ts'.
    # The start of this data window needs to be early enough to satisfy 'lookback_candles_needed'
    # for the indicators to be valid at the original 'from_ts' (for non-simulation) or the target candle (for simulation).
    kline_fetch_start_ts = from_ts - (lookback_candles_needed * timeframe_secs)
    kline_fetch_end_ts = to_ts # This is the original 'to_ts' from the request

    logger.info(f"Mode (sim={simulation}): Original request from_ts={from_ts}, to_ts={to_ts}. Max lookback: {max_lookback_periods}, Candles needed: {lookback_candles_needed}. Effective kline fetch range for calculation: {kline_fetch_start_ts} to {kline_fetch_end_ts}")

    current_time_sec = int(datetime.now(timezone.utc).timestamp())
    # Clamp the fetch window
    final_fetch_from_ts = max(0, kline_fetch_start_ts)
    final_fetch_to_ts = max(0, min(kline_fetch_end_ts, current_time_sec if not simulation else kline_fetch_end_ts))

    if final_fetch_from_ts >= final_fetch_to_ts:
         logger.warning(f"Invalid effective time range after lookback adjustment and clamping: {final_fetch_from_ts} >= {final_fetch_to_ts}")
         return JSONResponse({"s": "no_data", "errmsg": "Invalid time range"})

    # Fetch klines and Open Interest (base data for indicators) using the final clamped fetch window
    klines = await get_cached_klines(symbol, resolution, final_fetch_from_ts, final_fetch_to_ts)
    if not klines or klines[0]['time'] > final_fetch_from_ts or klines[-1]['time'] < final_fetch_to_ts:
        bybit_klines = fetch_klines_from_bybit(symbol, resolution, final_fetch_from_ts, final_fetch_to_ts)
        if bybit_klines:
            await cache_klines(symbol, resolution, bybit_klines)
            klines = await get_cached_klines(symbol, resolution, final_fetch_from_ts, final_fetch_to_ts)

    # Filter klines to the exact final fetch window (should be redundant if cache/bybit fetch is precise)

    oi_data = await get_cached_open_interest(symbol, resolution, final_fetch_from_ts, final_fetch_to_ts)
    if not oi_data or oi_data[0]['time'] > final_fetch_from_ts or oi_data[-1]['time'] < final_fetch_to_ts:
        from indicators import fetch_open_interest_from_bybit
        bybit_oi_data = fetch_open_interest_from_bybit(symbol, resolution, final_fetch_from_ts, final_fetch_to_ts)
        if bybit_oi_data:
            await cache_open_interest(symbol, resolution, bybit_oi_data)
            oi_data = await get_cached_open_interest(symbol, resolution, final_fetch_from_ts, final_fetch_to_ts)

    # Filter klines to the exact final fetch window (should be redundant if cache/bybit fetch is precise)
    # And filter OI data
    oi_data = [oi for oi in oi_data if final_fetch_from_ts <= oi['time'] <= final_fetch_to_ts]
    oi_data.sort(key=lambda x: x['time'])

    klines = [k for k in klines if final_fetch_from_ts <= k['time'] <= final_fetch_to_ts]
    klines.sort(key=lambda x: x['time'])

    if not klines:
        logger.warning(f"No klines found for symbol {symbol} resolution {resolution} in effective fetch range {final_fetch_from_ts} to {final_fetch_to_ts} after fetching and filtering.")
        all_indicator_results_empty: dict[str, dict[str, any]] = {}
        for current_indicator_id_str_empty in requested_indicator_ids:
            errmsg = f"No base kline data for calc range for {current_indicator_id_str_empty}"
            if simulation:
                errmsg += f" (sim target: {from_ts})" # Original from_ts is the sim target
            all_indicator_results_empty[current_indicator_id_str_empty] = {"s": "no_data", "errmsg": errmsg}
        return JSONResponse({"s": "ok", "data": all_indicator_results_empty})

    df_ohlcv = _prepare_dataframe(klines, oi_data)
    if df_ohlcv is None or df_ohlcv.empty:
        all_indicator_results_empty_df: dict[str, dict[str, any]] = {}
        for current_indicator_id_str_empty_df in requested_indicator_ids:
             all_indicator_results_empty_df[current_indicator_id_str_empty_df] = {"s": "no_data", "errmsg": f"Failed to prepare DataFrame for {current_indicator_id_str_empty_df}"}
        logger.warning(f"DataFrame preparation failed for {symbol} {resolution} in effective fetch range {final_fetch_from_ts} to {final_fetch_to_ts}. Kline count: {len(klines)}, OI count: {len(oi_data)}")
        return JSONResponse({"s": "ok", "data": all_indicator_results_empty_df})

    logger.info(f"Prepared DataFrame for {symbol} {resolution} with {len(df_ohlcv)} rows for calculation range {final_fetch_from_ts} to {final_fetch_to_ts}.")

    all_indicator_results: dict[str, dict[str, any]] = {}
    for current_indicator_id_str in requested_indicator_ids:
        indicator_config = next((item for item in AVAILABLE_INDICATORS if item["id"] == current_indicator_id_str), None)
        if not indicator_config:
            all_indicator_results[current_indicator_id_str] = {"s": "error", "errmsg": f"Config not found for {current_indicator_id_str}"}
            continue

        try:
            indicator_data_full_calc_range: dict[str, any] | None = None
            params = indicator_config["params"]
            calc_id = indicator_config["id"]

            if calc_id == "macd": indicator_data_full_calc_range = calculate_macd(df_ohlcv.copy(), **params)
            elif calc_id == "rsi": indicator_data_full_calc_range = calculate_rsi(df_ohlcv.copy(), **params)
            elif calc_id.startswith("stochrsi"): indicator_data_full_calc_range = calculate_stoch_rsi(df_ohlcv.copy(), **params)
            elif calc_id == "open_interest": indicator_data_full_calc_range = calculate_open_interest(df_ohlcv.copy())
            elif calc_id == "jma": indicator_data_full_calc_range = calculate_jma_indicator(df_ohlcv.copy(), **params) # Add JMA
            elif calc_id == "rsi_sma_3":  # New: Handle rsi_sma_3 calculation
                # We'll compute RSI for the entire range if it wasn't already part of the request:
                if "rsi" not in requested_indicator_ids:
                    # Re-use calculate_rsi, but for the full range; avoids re-calculation later
                    rsi_data = calculate_rsi(df_ohlcv.copy(), period=14)
                    # To ensure alignment with our core calculations, re-attach to df_ohlcv
                    df_ohlcv['rsi'] = rsi_data['rsi']
                else:  # If RSI was requested, we can assume it's already been calculated
                    rsi_data = calculate_rsi(df_ohlcv.copy(), period=14) # Ensure you are using a standard RSI period
                from indicators import calculate_rsi_sma
                indicator_data_full_calc_range = calculate_rsi_sma(df_ohlcv.copy(), 3, rsi_data.get("rsi"))
            else: # Existing logic for unrecognized indicator
                all_indicator_results[current_indicator_id_str] = {"s": "error", "errmsg": f"Calc logic not implemented for {calc_id}"}
                continue

            final_processed_data: dict[str, any] | None = None

            if indicator_data_full_calc_range and indicator_data_full_calc_range.get("t"):
                if simulation:
                    temp_signal_data = {}
                    original_t_series = indicator_data_full_calc_range.get("t", [])

                    if calc_id == "macd":
                        signal_values = indicator_data_full_calc_range.get("signal")
                        temp_signal_data = {"t": original_t_series, "signal": signal_values} if signal_values is not None else {"t": [], "signal": []}
                    elif calc_id == "rsi":
                        rsi_values = indicator_data_full_calc_range.get("rsi")
                        temp_signal_data = {"t": original_t_series, "rsi": rsi_values} if rsi_values is not None else {"t": [], "rsi": []}
                    elif calc_id.startswith("stochrsi"):
                        stoch_d_values = indicator_data_full_calc_range.get("stoch_d")
                        temp_signal_data = {"t": original_t_series, "stoch_d": stoch_d_values} if stoch_d_values is not None else {"t": [], "stoch_d": []}
                    elif calc_id == "open_interest":
                        oi_values = indicator_data_full_calc_range.get("open_interest")
                        temp_signal_data = {"t": original_t_series, "open_interest": oi_values} if oi_values is not None else {"t": [], "open_interest": []}
                    else:
                        temp_signal_data = indicator_data_full_calc_range # Should not happen if calc_id is valid

                    if temp_signal_data.get("t") and len(temp_signal_data["t"]) > 0 and \
                       any(val_list for key, val_list in temp_signal_data.items() if key != "t" and val_list is not None and len(val_list) > 0):
                        temp_signal_data["s"] = "ok"
                    else:
                        temp_signal_data = {"s": "no_data", "errmsg": f"No signal line data for {current_indicator_id_str} after filtering for simulation", "t": []}

                    original_status_str = temp_signal_data.get("s", "error")
                    original_errmsg_str = temp_signal_data.get("errmsg")
                    filtered_t_sim = []
                    data_series_keys = [key for key in temp_signal_data if key not in ["t", "s", "errmsg"]]
                    filtered_values_dict_sim: dict[str, list[any]] = {key: [] for key in data_series_keys}
                    found_target_candle_sim = False

                    for i, t_val_sim in enumerate(temp_signal_data.get("t", [])):
                        if t_val_sim == from_ts: # Original from_ts is the target for simulation
                            filtered_t_sim.append(t_val_sim)
                            for data_key in data_series_keys:
                                if data_key in temp_signal_data and i < len(temp_signal_data[data_key]):
                                    filtered_values_dict_sim[data_key].append(temp_signal_data[data_key][i])
                                else:
                                    filtered_values_dict_sim[data_key].append(None)
                            found_target_candle_sim = True
                            break

                    if found_target_candle_sim and filtered_t_sim:
                        final_processed_data = {"t": filtered_t_sim, "s": original_status_str}
                        if original_errmsg_str: final_processed_data["errmsg"] = original_errmsg_str
                        for data_key in data_series_keys: final_processed_data[data_key] = filtered_values_dict_sim[data_key]
                    else:
                        logger.warning(f"Simulation: Target candle ts {from_ts} not found for {current_indicator_id_str}.")
                        final_processed_data = {"s": "no_data", "errmsg": f"Target candle {from_ts} not found for {current_indicator_id_str}", "t": []}

                else: # Not simulation - filter to original requested range [from_ts, to_ts]
                    original_status_str = "ok" # Assume 'ok' if calculation succeeded and data is present
                    original_errmsg_str = None # No error message by default for non-simulation success

                    # If _extract_results put an 's' key, respect it, otherwise assume 'ok'
                    if "s" in indicator_data_full_calc_range:
                        original_status_str = indicator_data_full_calc_range["s"]
                        original_errmsg_str = indicator_data_full_calc_range.get("errmsg")

                    filtered_t_range = []
                    data_series_keys_range = [key for key in indicator_data_full_calc_range if key not in ["t", "s", "errmsg"]]
                    filtered_values_dict_range: dict[str, list[any]] = {key: [] for key in data_series_keys_range}
                    data_found_in_range = False

                    for i, t_val_range in enumerate(indicator_data_full_calc_range.get("t", [])):
                        if from_ts <= t_val_range <= to_ts: # Original request range
                            filtered_t_range.append(t_val_range)
                            for data_key in data_series_keys_range:
                                if data_key in indicator_data_full_calc_range and i < len(indicator_data_full_calc_range[data_key]):
                                    filtered_values_dict_range[data_key].append(indicator_data_full_calc_range[data_key][i])
                                else:
                                    filtered_values_dict_range[data_key].append(None)
                            data_found_in_range = True

                    if data_found_in_range and filtered_t_range:
                        final_processed_data = {"t": filtered_t_range, "s": original_status_str}
                        if original_errmsg_str: final_processed_data["errmsg"] = original_errmsg_str
                        for data_key in data_series_keys_range: final_processed_data[data_key] = filtered_values_dict_range[data_key]
                    else:
                        logger.warning(f"Non-Simulation: No data found in range {from_ts}-{to_ts} for {current_indicator_id_str} after calculation and filtering.")
                        final_processed_data = {"s": "no_data", "errmsg": f"No data in range {from_ts}-{to_ts} for {current_indicator_id_str}", "t": []}
            else:
                final_processed_data = {"s": "no_data", "errmsg": f"Initial calculation for {current_indicator_id_str} yielded no data", "t": []}

            if final_processed_data and final_processed_data.get("t") and len(final_processed_data["t"]) > 0 and final_processed_data.get("s") == "ok":
                status_to_set = final_processed_data.get("s", "error")
                errmsg_to_set = final_processed_data.get("errmsg")
                payload_data = {k: v for k, v in final_processed_data.items() if k not in ["s", "errmsg"]}

                result_entry = {"s": status_to_set, **payload_data}
                if errmsg_to_set: result_entry["errmsg"] = errmsg_to_set
                all_indicator_results[current_indicator_id_str] = result_entry
            else:
                logger.warning(f"Indicator data for {current_indicator_id_str} (target_ts: {from_ts if simulation else f'{from_ts}-{to_ts}'}) resulted in no valid data points after all processing.")
                all_indicator_results[current_indicator_id_str] = {
                    "s": final_processed_data.get("s") if final_processed_data else "no_data",
                    "errmsg": final_processed_data.get("errmsg") if final_processed_data else f"No data for {current_indicator_id_str} after processing"
                }

        except Exception as e:
            logger.error(f"Error processing indicator {current_indicator_id_str}: {e}", exc_info=True)
            all_indicator_results[current_indicator_id_str] = {"s": "error", "errmsg": f"Error processing indicator {current_indicator_id_str}: {str(e)}"}

    return JSONResponse({"s": "ok", "data": all_indicator_results})