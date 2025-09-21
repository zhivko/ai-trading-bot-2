# AI features and suggestion functionality

import json
import asyncio
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import httpx
from openai import OpenAI, APIError, APIStatusError, APIConnectionError
import google.generativeai as genai
from config import (
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_API_MODEL_NAME,
    LOCAL_OLLAMA_BASE_URL, LOCAL_OLLAMA_MODEL_NAME,
    LM_STUDIO_BASE_URL, LM_STUDIO_MODEL_NAME,
    MAX_DATA_POINTS_FOR_LLM, AVAILABLE_INDICATORS, SUPPORTED_SYMBOLS
)
from auth import creds
from redis_utils import get_redis_connection, fetch_klines_from_bybit, get_cached_klines, cache_klines, get_cached_open_interest, cache_open_interest
from indicators import (
    _prepare_dataframe, calculate_macd, calculate_rsi, calculate_stoch_rsi,
    calculate_open_interest, calculate_jma_indicator, format_indicator_data_for_llm_as_dict,
    fetch_open_interest_from_bybit, get_timeframe_seconds
)
from logging_config import logger

# Configure Gemini API key globally
genai.configure(api_key=creds.GEMINI_API_KEY)

# Initialize AI clients
deepseek_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL, timeout=120.0)
local_ollama_client = OpenAI(base_url=LOCAL_OLLAMA_BASE_URL, api_key="ollama", timeout=120.0)
lm_studio_client = OpenAI(base_url=LM_STUDIO_BASE_URL, api_key="lm-studio", timeout=120.0)

class AIRequest(BaseModel):
    symbol: str
    resolution: str
    xAxisMin: int  # timestamp
    xAxisMax: int  # timestamp
    activeIndicatorIds: List[str]  # List of indicator IDs like "macd", "rsi"
    question: str
    use_local_ollama: bool = False
    local_ollama_model_name: Optional[str] = None
    use_gemini: bool = False  # New field for Gemini

class IndicatorConfigRequest(BaseModel):
    id: str
    # Params are fixed in AVAILABLE_INDICATORS, client only needs to send id

AI_SYSTEM_PROMPT_INSTRUCTIONS = """
You are an expert trading agent specializing in cryptocurrency analysis. Your primary function is to analyze textual market data (kline/candlestick and technical indicators) to suggest BUY, SELL, or HOLD actions.

You will be provided with the following textual data for a specific cryptocurrency pair and timeframe:
1.  **Open Interest**: The total number of outstanding derivative contracts. Rising OI can confirm a trend, while falling OI can signal a weakening trend.
2.  **Symbol**: The cryptocurrency pair (e.g., BTCUSDT).
3.  **Timeframe**: The chart timeframe (e.g., 1m, 5m, 1h, 1d).
4.  **Data Range (UTC)**: The start and end UTC timestamps for the provided data.

--- START KLINE DATA ---
--- END KLINE DATA ---

--- START INDICATOR DATA: INDICATOR_NAME (Indicator Full Name, Params: ...) ---
--- END INDICATOR DATA: INDICATOR_NAME ---

The market data will be provided as a JSON object embedded within this prompt, under the "--- MARKET DATA JSON ---" heading.
The JSON object will have the following structure:
{
  "kline_data": [
   {"date": "YYYY-MM-DD HH:MM:SS", "close": 0.0},
    // ... more kline data points, each with date and close price
  ],
  "indicator_data": [ // This is now a list of indicator objects
    {
      "indicator_name": "MACD",
      "params": {"short_period": 12, "long_period": 26, "signal_period": 9},
      "status": "ok" | "no_data",
      "error_message": "Optional error message if status is no_data",
      "values": [
        {"timestamp": "YYYY-MM-DD HH:MM:SS", "MACD": 0.0, "Signal": 0.0, "Histogram": 0.0},
        // ... more macd values
      ]
    },
    // ... more indicator objects if active
  ]
}

The latest data is at the end of the Kline and Indicator lists.

To generate your JSON response:
- The "price" field MUST be the 'Close' value from the LAST entry in the "--- START KLINE DATA ---" section.
- The "date" field MUST be the 'date' from the LAST entry in the "--- START KLINE DATA ---" section, formatted as YYYY-MM-DD HH:MM:SS.
- Your "trend_description" MUST be based on patterns observed in the "kline_data" array. To identify a trend, look for a series of at least 3-5 consecutive candles showing:
    - Uptrend: Higher highs and higher lows. Note the approximate start time and price.
    - Downtrend: Lower highs and lower lows. Note the approximate start time and price.
    - Consolidation/Sideways: Price trading within a relatively narrow range without clear higher highs/lows or lower highs/lows. Note the approximate range.
- Your "breakout_point_description" MUST reference specific price levels and timestamps from the "kline_data" array if a breakout is identified.
    - For an uptrend, a break might be a candle closing significantly below the recent series of higher lows, or forming a distinct lower high followed by a lower low.
    - For a downtrend, a break might be a candle closing significantly above the recent series of lower highs, or forming a distinct higher low followed by a higher high.
    - If no clear breakout is observed from kline data, state that clearly.
- Your "explanation" for "action" MUST reference specific values and timestamps from the "kline_data" array and relevant indicator objects in the "indicator_data" array. For example, if you mention MACD, state the MACD values and timestamp from its "values" array. If you mention RSI, state the RSI value and timestamp. Do not invent values; use only what is provided in the JSON.

Decision Logic to suggest trade:
Condition 1: Identify a price trend from the "kline_data" as described above.
Condition 2: Identify if the price is showing signs of breaking the current trend from the "kline_data" as described above (e.g., for an uptrend, forming a lower high then lower low; for a downtrend, forming a higher low then higher high).

Monitor the slowest Stochastic RSI (if provided, e.g., Stochastic RSI 60,10). When this indicator starts rising from an oversold condition (<20), it's a positive sign for a potential BUY. When it falls from an overbought condition (>80), it's a negative sign for a potential SELL.
Confirm with MACD (if provided): A BUY signal is strengthened when the MACD line crosses above the Signal line, ideally after price shows signs of breaking a downtrend and the slowest StochRSI is rising. A SELL signal is strengthened by a MACD line crossing below the Signal line after signs of breaking an uptrend and slowest StochRSI is falling.
RSI (if provided): RSI below 30-40 can indicate oversold (potential buy opportunity in an uptrend or reversal), and above 60-70 can indicate overbought (potential sell opportunity in a downtrend or reversal).

Decision Logic to suggest opening LONG position - BUY:
Price shows signs of breaking a prior downtrend or is in an established uptrend and rallying.
Stochastic RSI (slowest available, e.g., 60,10, or if not, then 40,4, etc.) is rising from an oversold area.
RSI (if available) is ideally below 40 or rising from oversold.
MACD (if available) shows a bullish cross (MACD line > Signal line) or is already in bullish territory and rising.
Faster Stochastic RSIs (if available) may show a 'W' pattern rising from oversold.

Decision Logic to suggest opening SHORT position - SELL:
Price shows signs of breaking a prior uptrend or is in an established downtrend.
Stochastic RSI (slowest available) is falling from an overbought area.
RSI (if available) is ideally above 60 or falling from overbought.
MACD (if available) shows a bearish cross (MACD line < Signal line) or is already in bearish territory and falling.
Faster Stochastic RSIs (if available) may show an 'M' pattern falling from overbought.

Decision Logic for HOLD:
If neither strong BUY nor strong SELL conditions are met, or if the market data indicates consolidation without clear directional momentum (e.g., price moving sideways, indicators neutral).
"""

AI_OUTPUTFORMAT_INSTRUCTIONS = """
Output Format:
Your response MUST be in the following JSON format. Do not include any explanatory text outside of this JSON structure.
{
"price": "current/latest closing price from Kline Data",
"date": "current/latest timestamp from Kline Data (YYYY-MM-DD HH:MM:SS)",
"trend_description": "A brief description of the observed price trend (e.g., 'Uptrend since YYYY-MM-DD HH:MM:SS', 'Downtrend, recently broke support at X', 'Consolidating between P1 and P2').",
"breakout_point_description": "Description of any observed trend breakout or breakdown point relevant to the decision (e.g., 'Price broke above resistance at YYYY-MM-DD HH:MM:SS at price P', 'No clear breakout observed').",
"action": "BUY" | "SELL" | "HOLD",
"explanation": "A concise explanation for your decision, referencing specific kline patterns or indicator signals from the provided textual data. Mention specific values or conditions if possible (e.g., 'MACD bullish cross at YYYY-MM-DD HH:MM:SS, RSI at 35 and rising')."
}
"""

def get_system_prompt():
    """Returns the system prompt for AI analysis."""
    return f"{AI_SYSTEM_PROMPT_INSTRUCTIONS}\n\n{AI_OUTPUTFORMAT_INSTRUCTIONS}"

def get_user_prompt_for_market_data(request_data, market_data_json_payload, start_dt_str, end_dt_str):
    """Constructs user prompt for market data analysis."""
    user_prompt_content = "--- Market Data ---\n"
    user_prompt_content += f"Symbol: {request_data.symbol}\n"
    user_prompt_content += f"Timeframe: {request_data.resolution}\n"
    user_prompt_content += f"Data Range (UTC): {start_dt_str} to {end_dt_str}\n\n"
    user_prompt_content += "--- MARKET DATA JSON ---\n" + market_data_json_payload + "\n--- END MARKET DATA JSON ---\n\n"
    user_prompt_content += "--- End Market Data ---\n\n"
    # user_prompt_content += f"User Question: {request_data.question}"
    return user_prompt_content

def get_user_prompt_for_audio(transcribed_text, request_data=None, market_data_json_payload=None, start_dt_str=None, end_dt_str=None):
    """Constructs user prompt for audio transcription analysis.
    Can optionally include market data context if provided."""
    user_prompt = f"--- AUDIO TRANSCRIPT ---\n{transcribed_text}\n--- END AUDIO TRANSCRIPT ---\n"

    # Add market data context if provided
    if request_data and market_data_json_payload and start_dt_str and end_dt_str:
        user_prompt += "\n--- MARKET CONTEXT ---\n"
        user_prompt += f"Symbol: {request_data.symbol}\n"
        user_prompt += f"Timeframe: {request_data.resolution}\n"
        user_prompt += f"Data Range (UTC): {start_dt_str} to {end_dt_str}\n\n"
        user_prompt += "--- MARKET DATA JSON ---\n" + market_data_json_payload + "\n--- END MARKET DATA JSON ---\n"
        user_prompt += "--- End Market Context ---\n\n"

        user_prompt += "Please analyze this transcribed audio content in the context of the provided market data and provide insights, patterns, or recommendations."
    else:
        user_prompt += "\nPlease analyze this transcribed audio content and provide insights, patterns, or recommendations based on the content."

    return user_prompt

async def get_ai_suggestion(request_data: AIRequest):
    logger.info(f"Received /AI request: Symbol={request_data.symbol}, Res={request_data.resolution}, "
                f"Range=[{request_data.xAxisMin}, {request_data.xAxisMax}], "
                f"Indicators={request_data.activeIndicatorIds}, "
                f"LocalModel={request_data.local_ollama_model_name if request_data.use_local_ollama else 'N/A'}, "
                f"UseLocalOllama: {request_data.use_local_ollama}")

    # Determine api_source early for logging and error handling
    if request_data.use_local_ollama:
        api_source = "Local Ollama"
    else:
        api_source = "Gemini"

    current_time_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    # 1. Determine kline fetch window (considering lookback for indicators)
    max_lookback_periods = 0
    for ind_id in request_data.activeIndicatorIds:
        config = next((item for item in AVAILABLE_INDICATORS if item["id"] == ind_id), None)
        if config:
            current_indicator_lookback = 0
            if config["id"] == "macd":
                current_indicator_lookback = config["params"]["long_period"] + config["params"]["signal_period"]
            elif config["id"] == "rsi":
                current_indicator_lookback = config["params"]["period"]
            elif config["id"].startswith("stochrsi"):
                current_indicator_lookback = config["params"]["rsi_period"] + config["params"]["stoch_period"] + config["params"]["d_period"]
            if current_indicator_lookback > max_lookback_periods:
                max_lookback_periods = current_indicator_lookback
            elif config["id"] == "open_interest":
                current_indicator_lookback = 0  # No specific lookback for OI itself

    buffer_candles = 30
    min_overall_candles = 50
    lookback_candles_needed = max(max_lookback_periods + buffer_candles, min_overall_candles)
    timeframe_secs = get_timeframe_seconds(request_data.resolution)

    kline_fetch_start_ts = request_data.xAxisMin - (lookback_candles_needed * timeframe_secs)
    kline_fetch_end_ts = request_data.xAxisMax

    # Clamp fetch window
    current_time_sec_utc = int(datetime.now(timezone.utc).timestamp())
    final_fetch_from_ts = max(0, kline_fetch_start_ts)
    final_fetch_to_ts = max(0, min(kline_fetch_end_ts, current_time_sec_utc))

    if final_fetch_from_ts >= final_fetch_to_ts:
        logger.warning(f"AI: Invalid effective time range for kline fetch: {final_fetch_from_ts} >= {final_fetch_to_ts}")
        return JSONResponse({"error": "Invalid time range for fetching data."}, status_code=400)

    # 2. Fetch klines and Open Interest for calculation
    klines_for_calc = await get_cached_klines(request_data.symbol, request_data.resolution, final_fetch_from_ts, final_fetch_to_ts)
    if not klines_for_calc or klines_for_calc[0]['time'] > final_fetch_from_ts or klines_for_calc[-1]['time'] < final_fetch_to_ts:
        bybit_klines = fetch_klines_from_bybit(request_data.symbol, request_data.resolution, final_fetch_from_ts, final_fetch_to_ts)
        if bybit_klines:
            await cache_klines(request_data.symbol, request_data.resolution, bybit_klines)
            klines_for_calc = await get_cached_klines(request_data.symbol, request_data.resolution, final_fetch_from_ts, final_fetch_to_ts)

    oi_data_for_calc = await get_cached_open_interest(request_data.symbol, request_data.resolution, final_fetch_from_ts, final_fetch_to_ts)

    if not oi_data_for_calc or oi_data_for_calc[0]['time'] > final_fetch_from_ts or oi_data_for_calc[-1]['time'] < final_fetch_to_ts:
        bybit_oi_data = fetch_open_interest_from_bybit(request_data.symbol, request_data.resolution, final_fetch_from_ts, final_fetch_to_ts)
        if bybit_oi_data:
            await cache_open_interest(request_data.symbol, request_data.resolution, bybit_oi_data)
            oi_data_for_calc = await get_cached_open_interest(request_data.symbol, request_data.resolution, final_fetch_from_ts, final_fetch_to_ts)

    # Filter klines and OI to the exact final fetch window
    klines_for_calc = [k for k in klines_for_calc if final_fetch_from_ts <= k['time'] <= final_fetch_to_ts]
    klines_for_calc.sort(key=lambda x: x['time'])

    if not klines_for_calc:
        logger.warning(f"AI: No kline data found for {request_data.symbol} {request_data.resolution} in range {final_fetch_from_ts}-{final_fetch_to_ts}")
        return JSONResponse({"error": "No kline data available for analysis."}, status_code=404)

    # 3. Prepare DataFrame
    oi_data_for_calc = [oi for oi in oi_data_for_calc if final_fetch_from_ts <= oi['time'] <= final_fetch_to_ts]
    oi_data_for_calc.sort(key=lambda x: x['time'])
    if not klines_for_calc:  # OI data without klines is not useful for the AI prompt as constructed
        logger.warning(f"AI: No kline data found for {request_data.symbol} {request_data.resolution} in range {final_fetch_from_ts}-{final_fetch_to_ts}")
        return JSONResponse({"error": "No kline data available for analysis."}, status_code=404)

    # 3. Prepare DataFrame (merge klines and OI)
    df_ohlcv = _prepare_dataframe(klines_for_calc, oi_data_for_calc)

    if df_ohlcv is None or df_ohlcv.empty:
        logger.warning(f"AI: DataFrame preparation failed for {request_data.symbol} {request_data.resolution}.")
        return JSONResponse({"error": "Failed to prepare data for analysis."}, status_code=500)

    # 4. Calculate all requested indicators using the full df_ohlcv
    calculated_indicators_data_full_range: Dict[str, Dict[str, Any]] = {}
    for ind_id_str in request_data.activeIndicatorIds:
        indicator_config = next((item for item in AVAILABLE_INDICATORS if item["id"] == ind_id_str), None)
        if indicator_config:
            params = indicator_config["params"]
            calc_id = indicator_config["id"]
            temp_data: Optional[Dict[str, Any]] = None
            if calc_id == "macd":
                temp_data = calculate_macd(df_ohlcv.copy(), **params)
            elif calc_id == "rsi":
                temp_data = calculate_rsi(df_ohlcv.copy(), **params)
            elif calc_id.startswith("stochrsi"):
                temp_data = calculate_stoch_rsi(df_ohlcv.copy(), **params)
            elif calc_id == "open_interest":
                temp_data = calculate_open_interest(df_ohlcv.copy())

            if temp_data and temp_data.get("t"):  # Ensure 't' exists for filtering
                calculated_indicators_data_full_range[ind_id_str] = temp_data
            else:
                logger.warning(f"AI: Calculation for indicator {ind_id_str} yielded no data.")
                calculated_indicators_data_full_range[ind_id_str] = {"t": [], "s": "no_data", "errmsg": f"No data from {ind_id_str} calc"}

    # 5. Filter klines and indicators to the visible range (xAxisMin, xAxisMax)
    visible_klines = [k for k in klines_for_calc if request_data.xAxisMin <= k['time'] <= request_data.xAxisMax]
    visible_klines.sort(key=lambda x: x['time'])  # Ensure sorted

    # Truncate visible klines if they exceed the limit
    klines_to_send_for_json_payload = visible_klines[-MAX_DATA_POINTS_FOR_LLM:] if len(visible_klines) > MAX_DATA_POINTS_FOR_LLM else visible_klines
    if len(visible_klines) > MAX_DATA_POINTS_FOR_LLM:
        logger.info(f"AI: Truncating visible klines from {len(visible_klines)} to {len(klines_to_send_for_json_payload)} for LLM.")

    visible_indicators_data: Dict[str, Dict[str, Any]] = {}
    for ind_id, ind_data_full in calculated_indicators_data_full_range.items():
        if not ind_data_full or not ind_data_full.get("t"):
            visible_indicators_data[ind_id] = {"t": [], "s": "no_data", "errmsg": f"No initial data for {ind_id}"}
            continue

        filtered_t: List[int] = []
        # Initialize lists for all potential data series in the indicator
        data_series_keys = [key for key in ind_data_full if key not in ["t", "s", "errmsg"]]
        filtered_values_dict: Dict[str, List[Any]] = {key: [] for key in data_series_keys}

        data_found_in_visible_range = False
        for i, ts_val in enumerate(ind_data_full["t"]):
            if request_data.xAxisMin <= ts_val <= request_data.xAxisMax:
                filtered_t.append(ts_val)
                for data_key in data_series_keys:
                    if data_key in ind_data_full and i < len(ind_data_full[data_key]):
                        filtered_values_dict[data_key].append(ind_data_full[data_key][i])
                    else:  # Should not happen if data is consistent
                        filtered_values_dict[data_key].append(None)
                data_found_in_visible_range = True

        if data_found_in_visible_range and filtered_t:
            # Truncate indicator data if necessary
            if len(filtered_t) > MAX_DATA_POINTS_FOR_LLM:
                logger.info(f"AI: Truncating indicator {ind_id} data from {len(filtered_t)} to {MAX_DATA_POINTS_FOR_LLM} points for LLM.")
                truncated_indicator_t = filtered_t[-MAX_DATA_POINTS_FOR_LLM:]
                truncated_indicator_values = {}
                for key, values_list in filtered_values_dict.items():
                    if isinstance(values_list, list) and len(values_list) == len(filtered_t):
                        truncated_indicator_values[key] = values_list[-MAX_DATA_POINTS_FOR_LLM:]
                    else:  # Should not happen if data is consistent
                        truncated_indicator_values[key] = values_list
                visible_indicators_data[ind_id] = {"t": truncated_indicator_t, "s": "ok", **truncated_indicator_values}
            else:
                visible_indicators_data[ind_id] = {"t": filtered_t, "s": "ok", "maxTime": final_fetch_to_ts, "maxLookBack": lookback_candles_needed, **filtered_values_dict}
        else:
            visible_indicators_data[ind_id] = {"t": [], "s": "no_data", "errmsg": f"No data for {ind_id} in visible range"}

    # 6. Format data for LLM
    # Prepare Kline data for JSON
    kline_data_for_json = []
    if not klines_to_send_for_json_payload:  # Check the (potentially truncated) list
        logger.info("No visible klines to send to AI.")
    else:
        logger.info(f"AI: Preparing {len(klines_to_send_for_json_payload)} klines for JSON payload.")
        for k in klines_to_send_for_json_payload:
            dt_object = datetime.fromtimestamp(k['time'], timezone.utc)
            kline_data_for_json.append({
                "date": dt_object.strftime('%Y-%m-%d %H:%M:%S'),  # Renamed from timestamp to date
                "close": k['close']
            })

    indicator_data_for_json_list = []

    if not request_data.activeIndicatorIds:
        logger.info("No active indicators to send to AI.")
    else:
        for ind_id in request_data.activeIndicatorIds:
            indicator_config_details = next((item for item in AVAILABLE_INDICATORS if item["id"] == ind_id), None)
            if indicator_config_details:
                data_to_format = visible_indicators_data.get(ind_id, {"t": [], "s": "no_data", "errmsg": f"Data for {ind_id} not found post-filter"})
                # format_indicator_data_for_llm_as_dict no longer needs max_points as data is pre-truncated
                indicator_dict = format_indicator_data_for_llm_as_dict(ind_id, indicator_config_details, data_to_format)
                indicator_data_for_json_list.append(indicator_dict)
            else:
                indicator_data_for_json_list.append({
                    "indicator_name": ind_id, "status": "error", "error_message": "Configuration not found."
                })

    start_dt_str = datetime.fromtimestamp(request_data.xAxisMin, timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    # Determine end_dt_str from the latest kline in klines_for_calc, which represents the true end of data fetched from Redis
    if klines_for_calc:
        end_dt_str = datetime.fromtimestamp(klines_for_calc[-1]['time'], timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    else:  # Fallback if klines_for_calc is somehow empty (should be caught earlier)
        end_dt_str = datetime.fromtimestamp(request_data.xAxisMax, timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    market_data_json_payload = {
        "kline_data": kline_data_for_json,
        "indicator_data": indicator_data_for_json_list
    }
    market_data_json_str = json.dumps(market_data_json_payload, indent=2)

    # --- Construct System and User Prompts ---
    system_prompt_content = get_system_prompt()
    user_prompt_content = get_user_prompt_for_market_data(request_data, market_data_json_str, start_dt_str, end_dt_str)

    # --- DUMP PROMPT TO FILE ---
    try:
        temp_dir = Path("./")  # Changed from c:/temp to current directory for broader compatibility
        temp_dir.mkdir(parents=True, exist_ok=True)

        prompt_filename = "ai_prompt_deepseek.txt"
        if request_data.use_local_ollama:
            prompt_filename = "ai_prompt_local_ollama.txt"
        elif request_data.use_gemini:
            prompt_filename = "ai_prompt_gemini.txt"

        prompt_file_path = temp_dir / prompt_filename

        prompt_content_to_dump = f"--- SYSTEM PROMPT ---\n{system_prompt_content}\n\n--- USER PROMPT ---\n{user_prompt_content}"
        prompt_file_path.write_text(prompt_content_to_dump, encoding='utf-8')
        logger.info(f"AI prompt ({api_source}) successfully dumped to {prompt_file_path}")
    except Exception as e:
        logger.error(f"Error dumping AI prompt ({api_source}) to file: {e}", exc_info=True)
    # --- END DUMP PROMPT ---

    messages_for_ai = [
        {"role": "system", "content": system_prompt_content},
        {"role": "user", "content": user_prompt_content}
    ]

    logger.info(f"AI: Sending request to {api_source} with model {request_data.local_ollama_model_name or LOCAL_OLLAMA_MODEL_NAME if request_data.use_local_ollama else DEEPSEEK_API_MODEL_NAME}.")
    try:
        if request_data.use_local_ollama:
            selected_local_model = request_data.local_ollama_model_name or LOCAL_OLLAMA_MODEL_NAME
            logger.info(f"Using Local Ollama model for streaming: {selected_local_model}")
            generator = ollama_response_generator(
                selected_local_model, messages_for_ai, local_ollama_client, request_data
            )
            return StreamingResponse(generator, media_type="application/x-ndjson")
        else:
            selected_gemini_model = "models/gemini-2.5-flash-lite-preview-06-17"  # Or "gemini-pro"
            logger.info(f"Using Gemini model: {selected_gemini_model}")

            # Gemini uses a 'system_instruction' for the system prompt, separate from the message history.
            model = genai.GenerativeModel(
                model_name=selected_gemini_model,
                system_instruction=system_prompt_content
            )
            gemini_response = await asyncio.to_thread(
                model.generate_content,
                user_prompt_content,  # Pass just the user prompt string
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    response_mime_type="application/json"  # Explicitly ask for JSON output
                )
            )
            ai_message_content_str = gemini_response.text
            logger.info(f"Gemini raw response text: {ai_message_content_str[:500]}...")

        if not ai_message_content_str:
            logger.error(f"{api_source} API response content is empty.")
            return JSONResponse({"error": f"AI model ({api_source}) returned empty content."}, status_code=500)

        # Try to parse the JSON content from the AI
        try:
            # The AI should return a JSON string, so we parse it.
            ai_suggestion_json = json.loads(ai_message_content_str)
            # Ensure the date is current if the AI didn't set it, or standardize format
            if "date" not in ai_suggestion_json or not ai_suggestion_json["date"]:
                if visible_klines and kline_data_for_json:  # Ensure kline_data_for_json is not empty
                    ai_suggestion_json["date"] = kline_data_for_json[-1]["timestamp"]
                elif visible_klines:  # Fallback if kline_data_for_json was empty but visible_klines was not
                    ai_suggestion_json["date"] = datetime.fromtimestamp(visible_klines[-1]['time'], timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
                else:
                    ai_suggestion_json["date"] = current_time_str
            logger.info(f"AI Suggestion ({api_source}): {ai_suggestion_json}")
            return JSONResponse(ai_suggestion_json)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse AI suggestion JSON from {api_source}: {ai_message_content_str}")
            # Return the raw string if it's not valid JSON, but wrap it in your expected structure
            return JSONResponse({
                "action": "ERROR",
                "date": current_time_str,
                "explanation": f"AI model returned non-JSON content: {ai_message_content_str}"
            })

    except APIStatusError as e:  # Handles HTTP status errors from DeepSeek API
        logger.error(f"{api_source} API error (status {e.status_code}): {e.response.text if e.response else 'No response body'}")
        error_details = e.response.text if e.response else 'No response body'
        return JSONResponse({"error": f"AI API error ({api_source}): {e.status_code}", "details": error_details}, status_code=e.status_code)
    except APIConnectionError as e:  # Handles connection errors
        logger.error(f"Failed to connect to {api_source} API: {e}")
        return JSONResponse({"error": f"Could not connect to AI service ({api_source})."}, status_code=503)
    except APIError as e:  # Catch-all for other API errors from the openai library
        logger.error(f"{api_source} API returned an error: {e}")
        return JSONResponse({"error": f"AI API error ({api_source}): {str(e)}"}, status_code=500)  # Generic 500 or more specific if possible
    except Exception as e:
        logger.error(f"Unexpected error in /AI endpoint with {api_source}: {e}", exc_info=True)
        return JSONResponse({"error": "An unexpected error occurred processing the AI request."}, status_code=500)

# --- Helper for Ollama Streaming ---
async def ollama_response_generator(
    model_name: str,
    messages_list: list,
    client: OpenAI,
    request_data_for_log: AIRequest  # For logging context
):
    queue = asyncio.Queue()
    # Get the event loop of the context where this async generator is running
    main_event_loop = asyncio.get_running_loop()

    def ollama_thread_worker():
        try:
            logger.info(f"Ollama stream worker started for model {model_name}. Symbol: {request_data_for_log.symbol}, Res: {request_data_for_log.resolution}")
            stream = client.chat.completions.create(
                model=model_name,
                messages=messages_list,
                stream=True
            )
            for chunk_count, chunk in enumerate(stream):
                if chunk.choices[0].delta and chunk.choices[0].delta.content:
                    response_payload = {"response": chunk.choices[0].delta.content}
                    # logger.debug(f"Ollama stream chunk {chunk_count} for {model_name}: {response_payload['response'][:50]}...")
                    main_event_loop.call_soon_threadsafe(queue.put_nowait, json.dumps(response_payload) + "\n")
                elif chunk.choices[0].finish_reason:
                    logger.info(f"Ollama stream finished for model {model_name}. Reason: {chunk.choices[0].finish_reason}")

            main_event_loop.call_soon_threadsafe(queue.put_nowait, None)  # Signal end of stream
            logger.info(f"Ollama stream worker finished successfully for model {model_name}. Symbol: {request_data_for_log.symbol}")
        except (APIConnectionError, APIStatusError, APIError) as api_e:  # Catch specific OpenAI client errors
            logger.error(f"Ollama stream worker: API-related error for model {model_name}: {api_e}", exc_info=True)
            error_response = {"error": f"Ollama API error: {type(api_e).__name__}", "details": str(api_e)}
            main_event_loop.call_soon_threadsafe(queue.put_nowait, json.dumps(error_response) + "\n")
            main_event_loop.call_soon_threadsafe(queue.put_nowait, None)
        except Exception as e:
            logger.error(f"Ollama stream worker: Unexpected error for model {model_name}: {e}", exc_info=True)
            error_response = {"error": "Unexpected error streaming from Ollama", "details": str(e)}
            main_event_loop.call_soon_threadsafe(queue.put_nowait, json.dumps(error_response) + "\n")
            main_event_loop.call_soon_threadsafe(queue.put_nowait, None)

    asyncio.create_task(asyncio.to_thread(ollama_thread_worker))

    while True:
        item = await queue.get()
        if item is None:
            break
        yield item

async def process_audio_with_llm(request_data: AIRequest):
    """
    Process transcribed audio text with local LLM via LM Studio using the same trading analysis prompt.
    Includes market context for richer analysis.
    Returns the LLM response.
    """
    try:
        logger.info(f"Received audio analysis request: Symbol={request_data.symbol}, Res={request_data.resolution}, "
                    f"Range=[{request_data.xAxisMin}, {request_data.xAxisMax}], "
                    f"Indicators={request_data.activeIndicatorIds}")

        # Extract transcribed_text from request_data (assuming it's in question field for now)
        transcribed_text = request_data.question if hasattr(request_data, 'question') and request_data.question else ""
        if not transcribed_text:
            logger.warning("No transcribed text provided for audio analysis")
            return "Error: No transcribed text provided"

        logger.info(f"Processing transcribed text with LM Studio. Text length: {len(transcribed_text)}")

        # Prepare market data context similar to get_ai_suggestion
        max_lookback_periods = 0
        for ind_id in request_data.activeIndicatorIds:
            config = next((item for item in AVAILABLE_INDICATORS if item["id"] == ind_id), None)
            if config:
                current_indicator_lookback = 0
                if config["id"] == "macd":
                    current_indicator_lookback = config["params"]["long_period"] + config["params"]["signal_period"]
                elif config["id"] == "rsi":
                    current_indicator_lookback = config["params"]["period"]
                elif config["id"].startswith("stochrsi"):
                    current_indicator_lookback = config["params"]["rsi_period"] + config["params"]["stoch_period"] + config["params"]["d_period"]
                if current_indicator_lookback > max_lookback_periods:
                    max_lookback_periods = current_indicator_lookback

        buffer_candles = 30
        lookback_candles_needed = max(max_lookback_periods + buffer_candles, 50)
        timeframe_secs = get_timeframe_seconds(request_data.resolution)

        kline_fetch_start_ts = request_data.xAxisMin - (lookback_candles_needed * timeframe_secs)
        kline_fetch_end_ts = request_data.xAxisMax

        current_time_sec_utc = int(datetime.now(timezone.utc).timestamp())
        final_fetch_from_ts = max(0, kline_fetch_start_ts)
        final_fetch_to_ts = max(0, min(kline_fetch_end_ts, current_time_sec_utc))

        # Fetch simplified market data for context (less detailed than full AI analysis)
        klines_for_context = await get_cached_klines(request_data.symbol, request_data.resolution, final_fetch_from_ts, final_fetch_to_ts)
        if not klines_for_context:
            klines_for_context = []

        # Create simplified market context JSON
        visible_klines = [k for k in klines_for_context if request_data.xAxisMin <= k['time'] <= request_data.xAxisMax]
        visible_klines.sort(key=lambda x: x['time'])

        # Truncate for context (smaller than full AI analysis)
        klines_for_json = visible_klines[-50:] if len(visible_klines) > 50 else visible_klines

        kline_data_for_json = []
        for k in klines_for_json:
            dt_object = datetime.fromtimestamp(k['time'], timezone.utc)
            kline_data_for_json.append({
                "date": dt_object.strftime('%Y-%m-%d %H:%M:%S'),
                "close": k['close']
            })

        indicator_data_for_json = []
        # Add basic indicator data if available
        for ind_id in request_data.activeIndicatorIds[:2]:  # Limit to first 2 indicators for brevity
            indicator_data_for_json.append({
                "indicator_name": ind_id.upper(),
                "status": "available",
                "params": next((item["params"] for item in AVAILABLE_INDICATORS if item["id"] == ind_id), {}),
                "values": [{"timestamp": k["date"], "value": k["close"]} for k in kline_data_for_json]
            })

        market_data_json_payload = {
            "kline_data": kline_data_for_json[-20:],  # Last 20 points for context
            "indicator_data": indicator_data_for_json
        }
        market_data_json_str = json.dumps(market_data_json_payload, indent=2)

        start_dt_str = datetime.fromtimestamp(request_data.xAxisMin, timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        end_dt_str = datetime.fromtimestamp(request_data.xAxisMax, timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

        # Use the same system prompt as trading analysis with audio-specific instructions
        system_prompt = f"{get_system_prompt()}\n\n"

        # Use the dedicated audio prompt function with market context
        user_prompt = get_user_prompt_for_audio(transcribed_text, request_data, market_data_json_str, start_dt_str, end_dt_str)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        # Call LM Studio API
        response = await asyncio.to_thread(
            lm_studio_client.chat.completions.create,
            model=LM_STUDIO_MODEL_NAME,
            messages=messages,
            temperature=0.7,
            max_tokens=500
        )

        analysis = response.choices[0].message.content.strip()
        logger.info(f"LM Studio analysis completed. Response length: {len(analysis)}")
        return analysis

    except APIConnectionError as e:
        logger.error(f"Failed to connect to LM Studio: {e}")
        return f"Error: Could not connect to LM Studio service. {str(e)}"
    except APIError as e:
        logger.error(f"LM Studio API error: {e}")
        return f"Error: LM Studio API error. {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error processing audio with LLM: {e}", exc_info=True)
        return f"Error: Unexpected error occurred. {str(e)}"

async def get_local_ollama_models():
    try:
        logger.info("Fetching local Ollama models list...")
        models_response = await asyncio.to_thread(local_ollama_client.models.list)
        # The response object might be a Pydantic model, access its 'data' attribute
        # which should be a list of model objects.
        models_list = [model.id for model in models_response.data if hasattr(model, 'id')]
        logger.info(f"Successfully fetched {len(models_list)} local Ollama models: {models_list}")
        return JSONResponse({"models": models_list})
    except APIConnectionError as e:
        logger.error(f"Failed to connect to local Ollama to get models: {e}")
        return JSONResponse({"error": "Could not connect to local Ollama service."}, status_code=503)
    except Exception as e:
        logger.error(f"Error fetching local Ollama models: {e}", exc_info=True)
        return JSONResponse({"error": f"An unexpected error occurred: {str(e)}"}, status_code=500)
