import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from datetime import datetime, timezone
import pytz
import asyncio
import json
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass
import logging
from redis.asyncio import Redis
from pathlib import Path
from redis_utils import get_redis_connection
from config import SUPPORTED_SYMBOLS, get_timeframe_seconds
from endpoints.indicator_endpoints import _calculate_and_return_indicators
from auth import BybitCredentials
from redis_utils import fetch_klines_from_bybit, cache_klines, get_cached_klines
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import base64
import aiohttp

logger = logging.getLogger(__name__)

# Diagnostic log to confirm module import
logger.info("Email alert service module imported successfully.")

@dataclass
class SMTPConfig:
    server: str
    port: int
    username: str
    password: str
    from_email: str
    use_tls: bool = True

class EmailAlertService:
    def __init__(self, smtp_config: SMTPConfig):
        self.smtp_config = smtp_config
        self.active_alerts: Dict[str, List[str]] = {}
        logger.info("EmailAlertService initialized.")

    async def get_all_drawings(self, redis: Redis) -> List[Dict]:
        """Retrieve all drawings from Redis, injecting user_email from the key."""
        drawings = []
        for symbol in SUPPORTED_SYMBOLS:
            pattern = f"drawings:*:{symbol}"
            async for key in redis.scan_iter(match=pattern):
                key_str = key
                prefix = f"drawings:"
                suffix = f":{symbol}"
                if not (key_str.startswith(prefix) and key_str.endswith(suffix)):
                    logger.warning(f"Skipping malformed drawing key: {key_str}")
                    continue
                user_email = key_str[len(prefix):-len(suffix)]
                if not user_email:
                    logger.warning(f"Skipping drawing key with empty user_email: {key_str}")
                    continue
                drawing_data = await redis.get(key)
                if drawing_data:
                    try:
                        user_drawings = json.loads(drawing_data)
                        # Filter out None and non-dict items before processing
                        valid_drawings = [d for d in user_drawings if isinstance(d, dict) and d is not None]
                        for drawing in valid_drawings:
                            drawing['user_email'] = user_email
                        drawings.extend(valid_drawings)
                    except json.JSONDecodeError:
                        logger.error(f"Invalid drawing data in {key_str}")
        return drawings

    async def generate_alert_chart(self, user_email: str, symbol: str, resolution: str, triggered_alerts: List[Dict]) -> Optional[bytes]:
        """Generate a comprehensive, multi-pane chart for an email alert, styled like the web portal."""
        redis = await get_redis_connection()
        settings_key = f"settings:{user_email}:{symbol}"
        settings_json = await redis.get(settings_key)
        active_indicators = json.loads(settings_json).get('activeIndicators', []) if settings_json else []

        num_subplots = 1 + len(active_indicators)
        row_heights = [0.7] + [0.3] * len(active_indicators) if active_indicators else [1.0]
        fig = make_subplots(rows=num_subplots, cols=1, shared_xaxes=True, 
                              vertical_spacing=0.04, row_heights=row_heights)

        cross_time = triggered_alerts[0]['cross_time']
        timeframe_seconds = get_timeframe_seconds(resolution)

        # Determine the full range needed for the chart
        all_trendline_start_times = [alert['drawing']['start_time'] for alert in triggered_alerts]
        chart_start_time = min(all_trendline_start_times) - (timeframe_seconds * 20) # 20 candles before the earliest trendline
        chart_end_time = cross_time + (timeframe_seconds * 20) # 20 candles after the cross

        # Fetch klines for the entire chart range
        klines = await get_cached_klines(symbol, resolution, chart_start_time, chart_end_time)
        if not klines:
            logger.error(f"Could not fetch klines for {symbol} to generate chart.")
            return None
        df = pd.DataFrame(klines)
        df['time'] = pd.to_datetime(df['time'], unit='s', utc=True).dt.tz_convert('America/New_York')

        # --- Price Candlestick Chart ---
        fig.add_trace(go.Candlestick(
            x=df['time'], open=df['open'], high=df['high'], low=df['low'], close=df['close'],
            name='Price', increasing_line_color='green', decreasing_line_color='red'
        ), row=1, col=1)

        # --- Indicators ---
        indicator_colors = {'macd': '#00E5FF', 'signal': '#FF007F', 'histogram': '#BEBEBE', 'rsi': '#FFD700', 'stoch_k': '#00E5FF', 'stoch_d': '#FF007F'}
        logger.info(f"Active indicators for chart generation: {active_indicators}")
        for i, indicator_name in enumerate(active_indicators, start=2):
            indicator_data_response = await _calculate_and_return_indicators(symbol, resolution, chart_start_time, chart_end_time, [indicator_name])
            
            logger.debug(f"Indicator response for {indicator_name}: {indicator_data_response}")

            indicator_data = None
            if hasattr(indicator_data_response, 'body'):
                try:
                    response_data = json.loads(indicator_data_response.body)
                    logger.debug(f"Response data for {indicator_name}: {response_data}")
                    indicator_data = response_data.get('data', {}).get(indicator_name, {})
                except (json.JSONDecodeError, AttributeError): 
                    indicator_data = {}
            else:
                indicator_data = indicator_data_response.get('data', {}).get(indicator_name, {})
            
            logger.debug(f"Final indicator data for {indicator_name}: {indicator_data}")

            if indicator_data and indicator_data.get('t'):
                indicator_df = pd.DataFrame(indicator_data)
                indicator_df['t'] = pd.to_datetime(indicator_df['t'], unit='s', utc=True).dt.tz_convert('America/New_York')

                # Convert all indicator value columns to numeric type to ensure correct plotting
                for col in indicator_df.columns:
                    if col != 't':
                        indicator_df[col] = pd.to_numeric(indicator_df[col], errors='coerce')

                # Plotly handles NaNs gracefully by creating gaps, so we don't drop rows.

                # Special handling for different indicators
                if 'macd' in indicator_name.lower():
                    # MACD: macd line, signal line, and histogram
                    if 'macd' in indicator_df.columns:
                        fig.add_trace(go.Scatter(
                            x=indicator_df['t'], y=indicator_df['macd'], mode='lines',
                            name='MACD', line=dict(color='blue', width=1.5)
                        ), row=i, col=1)
                    if 'signal' in indicator_df.columns:
                        fig.add_trace(go.Scatter(
                            x=indicator_df['t'], y=indicator_df['signal'], mode='lines',
                            name='Signal', line=dict(color='orange', width=1.5)
                        ), row=i, col=1)
                    if 'histogram' in indicator_df.columns:
                        colors = ['green' if v >= 0 else 'red' for v in indicator_df['histogram']]
                        fig.add_trace(go.Bar(
                            x=indicator_df['t'], y=indicator_df['histogram'],
                            name='Histogram', marker_color=colors
                        ), row=i, col=1)
                elif 'stochrsi' in indicator_name.lower():
                    # Stochastic RSI: k and d lines, with overbought/oversold zones
                    if 'stoch_k' in indicator_df.columns:
                        fig.add_trace(go.Scatter(
                            x=indicator_df['t'], y=indicator_df['stoch_k'], mode='lines',
                            name='StochK', line=dict(color='dodgerblue', width=1.5)
                        ), row=i, col=1)
                    if 'stoch_d' in indicator_df.columns:
                        fig.add_trace(go.Scatter(
                            x=indicator_df['t'], y=indicator_df['stoch_d'], mode='lines',
                            name='StochD', line=dict(color='darkorange', width=1.5)
                        ), row=i, col=1)
                    fig.add_hline(y=80, line_dash="dash", line_color="red", line_width=1, row=i, col=1)
                    fig.add_hline(y=20, line_dash="dash", line_color="green", line_width=1, row=i, col=1)
                else:
                    # Default plotting for other indicators (like RSI)
                    for col in indicator_df.columns:
                        if col != 't':
                            trace_color = indicator_colors.get(col.lower(), 'blue')
                            fig.add_trace(go.Scatter(
                                x=indicator_df['t'], y=indicator_df[col], mode='lines',
                                name=f"{indicator_name}-{col}", line=dict(color=trace_color, width=1.5)
                            ), row=i, col=1)

                # Special handling for RSI overbought/oversold lines
                if 'rsi' in indicator_name.lower() and 'stochrsi' not in indicator_name.lower():
                    fig.add_hline(y=70, line_dash="dash", line_color="red", line_width=1, row=i, col=1)
                    fig.add_hline(y=30, line_dash="dash", line_color="green", line_width=1, row=i, col=1)

            fig.update_yaxes(title_text=indicator_name.upper(), row=i, col=1)

        # --- Drawings (Trendlines) ---
        all_drawings = await self.get_all_drawings(redis)
        for drawing in all_drawings:
            if drawing['user_email'] == user_email and drawing['symbol'] == symbol:
                t1_dt = datetime.fromtimestamp(drawing['start_time'], tz=timezone.utc).astimezone(pytz.timezone('America/New_York'))
                p1 = drawing['start_price']
                t2_dt = datetime.fromtimestamp(drawing['end_time'], tz=timezone.utc).astimezone(pytz.timezone('America/New_York'))
                p2 = drawing['end_price']
                subplot_name = drawing.get('subplot_name', symbol)
                
                try:
                    row = 1 if subplot_name == symbol else active_indicators.index(subplot_name.split('-', 1)[1]) + 2
                    fig.add_trace(go.Scatter(
                        x=[t1_dt, t2_dt], y=[p1, p2], mode='lines', name='Trendline',
                        line=dict(color='blue', width=2, dash='dot')
                    ), row=row, col=1)
                except (ValueError, IndexError):
                    logger.warning(f"Could not find subplot for drawing '{subplot_name}'. Defaulting to price chart.")
                    fig.add_trace(go.Scatter(
                        x=[t1_dt, t2_dt], y=[p1, p2], mode='lines', name='Trendline',
                        line=dict(color='blue', width=2, dash='dot')
                    ), row=1, col=1)

        # --- Cross Event Markers ---
        for alert in triggered_alerts:
            cross_dt = datetime.fromtimestamp(alert['cross_time'], tz=timezone.utc).astimezone(pytz.timezone('America/New_York'))
            cross_value = alert['cross_value']
            try:
                row = 1 if alert['trigger_type'] == 'price' else active_indicators.index(alert['indicator_name']) + 2
                fig.add_trace(go.Scatter(
                    x=[cross_dt], y=[cross_value], mode='markers', name='Cross Event',
                    marker=dict(color='#FF0000', size=10, symbol='circle', line=dict(width=2, color='DarkSlateGrey'))
                ), row=row, col=1)
            except (ValueError, IndexError):
                 logger.warning(f"Could not find subplot for alert on '{alert.get('indicator_name', 'price')}'. Defaulting to price chart.")
                 fig.add_trace(go.Scatter(
                    x=[cross_dt], y=[cross_value], mode='markers', name='Cross Event',
                    marker=dict(color='#FF0000', size=10, symbol='circle', line=dict(width=2, color='DarkSlateGrey'))
                ), row=1, col=1)

        # --- Layout and Theming ---
        cross_time_dt = datetime.fromtimestamp(cross_time, tz=timezone.utc).astimezone(pytz.timezone('Europe/Ljubljana'))
        fig.update_layout(
            title={
                'text': f'{symbol} Alert ({resolution}) - {cross_time_dt.strftime("%Y-%m-%d %H:%M:%S")}',
                'y':0.95,
                'x':0.5,
                'xanchor': 'center',
                'yanchor': 'top'
            },
            template='plotly_white',
            showlegend=False,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=70, r=70, t=120, b=80), # Increased top margin
            xaxis_rangeslider_visible=False,
            font=dict(family="Arial, sans-serif", size=12, color="black")
        )

        # Calculate data ranges with some padding to avoid cramped look
        min_time = df['time'].min()
        max_time = df['time'].max()
        time_range = max_time - min_time

        # Add 5% padding on each side
        padding = time_range * 0.05
        x_range = [min_time - padding, max_time + padding]
        logger.info(f"Data time range: {min_time} to {max_time}")
        logger.info(f"Setting x-axis range with padding to: {x_range}")

        # Set explicit ranges for tight fit (shared_xaxes affects all rows)
        fig.update_xaxes(range=x_range)

        # Autoscale y-axis for price chart based on price data only
        if not df.empty:
            all_prices = df[['open', 'high', 'low', 'close']].values.flatten()
            price_min = float(all_prices.min())
            price_max = float(all_prices.max())
            price_range = price_max - price_min
            # Add 2% padding above and below
            padding = price_range * 0.02
            y_range = [price_min - padding, price_max + padding]
            fig.update_yaxes(range=y_range, row=1, col=1)

        # Enable autorange for indicator y-axes (free scaling)
        for i in range(2, num_subplots + 1):
            fig.update_yaxes(autorange=True, row=i, col=1)

        fig.update_yaxes(title_text="Price (USD)", row=1, col=1)

        try:
            img_bytes = fig.to_image(format="png", width=1200, height=600 + (len(active_indicators) * 200))
            return img_bytes
        except Exception as e:
            logger.error(f"Failed to generate chart image: {e}", exc_info=True)
            return None

    async def detect_cross(self, redis: Redis, drawing: Dict, current_kline: Dict, prev_kline: Optional[Dict]) -> Optional[Dict]:
        """Detect if a price bar or indicator crosses a trendline."""
        t1 = drawing['start_time']
        p1 = drawing['start_price']
        t2 = drawing['end_time']
        p2 = drawing['end_price']
        symbol = drawing['symbol']
        resolution = drawing['resolution']
        subplot_name = drawing.get('subplot_name', symbol)

        bar_time = current_kline['time']

        if subplot_name != symbol:
            indicator_name = subplot_name.split('-', 1)[1]
            indicator_values = await self._get_indicator_values_at_times(
                symbol, resolution, [prev_kline['time'] if prev_kline else bar_time - 3600, bar_time], indicator_name
            )

            if len(indicator_values) < 2 or indicator_values[0] is None or indicator_values[1] is None:
                return None

            prev_indicator_value, current_indicator_value = indicator_values
            slope = (p2 - p1) / (t2 - t1) if t2 != t1 else 0
            line_price_prev = p1 + slope * ((prev_kline['time'] if prev_kline else bar_time - 3600) - t1)
            line_price_current = p1 + slope * (bar_time - t1)

            if (prev_indicator_value < line_price_prev and current_indicator_value > line_price_current) or \
               (prev_indicator_value > line_price_prev and current_indicator_value < line_price_current):
                return {"type": "indicator", "value": current_indicator_value, "indicator_name": indicator_name}
        else:
            bar_low = current_kline['low']
            bar_high = current_kline['high']

            if t1 == t2:
                if bar_time == t1 and not (bar_high < min(p1, p2) or bar_low > max(p1, p2)):
                    return {"type": "price", "value": current_kline['close']}
            elif min(t1, t2) <= bar_time <= max(t1, t2):
                slope = (p2 - p1) / (t2 - t1)
                line_price_at_bar_time = p1 + slope * (bar_time - t1)
                if bar_low <= line_price_at_bar_time <= bar_high:
                    return {"type": "price", "value": line_price_at_bar_time}
        return None

    async def _get_indicator_values_at_times(self, symbol: str, resolution: str, timestamps: List[int], indicator_name: str) -> List[Optional[float]]:
        """(Helper) Fetches indicator values for a list of specific timestamps."""
        if not timestamps:
            return []
        
        start_ts = min(timestamps) - (10 * get_timeframe_seconds(resolution))
        end_ts = max(timestamps) + (10 * get_timeframe_seconds(resolution))

        indicator_data_response = await _calculate_and_return_indicators(symbol, resolution, start_ts, end_ts, [indicator_name])
        
        if hasattr(indicator_data_response, 'body'):
            response_data = json.loads(indicator_data_response.body)
            if response_data.get('s') == 'ok' and indicator_name in response_data.get('data', {}):
                indicator_result = response_data['data'][indicator_name]
                if indicator_result.get('s') == 'ok':
                    value_keys = [k for k, v in indicator_result.items() if isinstance(v, list) and k != 't']
                    if not value_keys:
                        return [None] * len(timestamps)
                    value_key = value_keys[0]
                    
                    result_values: List[Optional[float]] = []
                    for ts in timestamps:
                        closest_t = min(indicator_result['t'], key=lambda x: abs(x - ts))
                        idx = indicator_result['t'].index(closest_t)
                        result_values.append(indicator_result[value_key][idx])
                    return result_values
        return [None] * len(timestamps)

    async def check_price_alerts(self, test: bool = False):
        logger.info("Starting check_price_alerts cycle.")
        try:
            redis = await get_redis_connection()
            logger.info("Redis connection established.")
            drawings = await self.get_all_drawings(redis)
            logger.info(f"Found {len(drawings)} total drawings.")
        except Exception as e:
            logger.error(f"Error connecting to Redis or getting drawings: {e}", exc_info=True)
            return

        alerts_by_user = {}

        logger.info(f"Filtering {len(drawings)} drawings for alerts...")
        eligible_drawings = 0

        for idx, drawing in enumerate(drawings):
            # Validate that drawing is a dict
            if not isinstance(drawing, dict) or drawing is None:
                logger.warning(f"Skipping invalid drawing at index {idx}: {drawing}")
                continue

            # Filter drawings that have been sent already - check both root and properties levels
            alert_sent_value = drawing.get('alert_sent')
            properties = drawing.get('properties', {})
            if properties is None:
                logger.warning(f"Skipping drawing {drawing.get('id')} with None properties")
                continue
            properties_email_sent = properties.get('emailSent')
            already_sent = alert_sent_value is True or properties_email_sent is True

            if already_sent:
                # logger.info(f"Drawing {drawing.get('id')} already sent (alert_sent={alert_sent_value}, properties.emailSent={properties_email_sent}), skipping.")
                continue

            # Check if sendEmailOnCross is enabled (default to True if not set)
            properties = drawing.get('properties', {})
            send_email_on_cross = properties.get('sendEmailOnCross', True)
            if not send_email_on_cross:
                logger.info(f"Drawing {drawing.get('id')} has sendEmailOnCross disabled, skipping.")
                continue

            eligible_drawings += 1
            try:
                # Double-check drawing validity before processing
                if not isinstance(drawing, dict) or drawing is None:
                    logger.warning(f"Skipping invalid drawing in try block at index {idx}: {drawing}")
                    continue

                symbol = drawing.get('symbol')
                user_email = drawing.get('user_email')
                if not symbol or not user_email:
                    logger.warning(f"Skipping drawing with missing symbol or email: {drawing.get('id', 'N/A')}")
                    continue

                # logger.info(f"Checking drawing {idx+1}/{len(drawings)} for {symbol} by {user_email}")

                resolution = drawing['resolution']
                kline_zset_key = f"zset:kline:{symbol}:{resolution}"
                # logger.debug(f"Fetching klines for {symbol} from {kline_zset_key}")
                latest_kline_list = await redis.zrevrange(kline_zset_key, 0, 1)

                if not latest_kline_list or len(latest_kline_list) < 2:
                    logger.warning(f"Not enough kline data for {symbol} to check for crosses.")
                    continue

                latest_kline = json.loads(latest_kline_list[0])
                prev_kline = json.loads(latest_kline_list[1])
                # logger.debug(f"Latest kline time: {latest_kline.get('time')}, prev: {prev_kline.get('time')}")

                bar_time = latest_kline['time']
                start_time = drawing.get('start_time')
                end_time = drawing.get('end_time')

                # Filter drawings where the current bar time is not between the start and end time of the drawing
                # Handle cases where end_time might be smaller than start_time (drawings drawn right-to-left)
                line_start = min(start_time, end_time)
                line_end = max(start_time, end_time)
                if not (line_start <= bar_time <= line_end):
                    # logger.debug(f"Drawing time range {start_time}-{end_time} (normalized: {line_start}-{line_end}) not matching bar time {bar_time}")
                    continue

                logger.info(f"Calling detect_cross for drawing {drawing.get('id')}")
                cross_info = await self.detect_cross(redis, drawing, latest_kline, prev_kline)
                logger.info(f"Cross detection result: {cross_info}")

                if cross_info:
                    logger.info(f"Cross detected for {symbol} by {user_email}: {cross_info}")
                    alert_details = {
                        'symbol': symbol,
                        'resolution': drawing['resolution'],
                        'line_id': drawing['id'],
                        'cross_time': latest_kline['time'],
                        'cross_value': cross_info['value'],
                        'trigger_type': cross_info['type'],
                        'indicator_name': cross_info.get('indicator_name'),
                        'drawing': drawing
                    }
                    if user_email not in alerts_by_user:
                        alerts_by_user[user_email] = {}
                    if symbol not in alerts_by_user[user_email]:
                        alerts_by_user[user_email][symbol] = []
                    alerts_by_user[user_email][symbol].append(alert_details)
            except Exception as e:
                logger.error(f"Error processing drawing {drawing.get('id', 'N/A')}: {e}", exc_info=True)

        logger.info(f"Eligible drawings: {eligible_drawings}")
        logger.info(f"Alerts by user: {list(alerts_by_user.keys())}")

        # Test mode: fake a cross for the last drawing on BTCUSDT
        if test:
            btc_drawings = [d for d in drawings if d.get('symbol') == 'BTCUSDT' and d.get('user_email') == 'klemenzivkovic@gmail.com' and d.get('properties', {}).get('sendEmailOnCross', True)]
            # Sort by start_time and end_time descending (most recent first)
            btc_drawings.sort(key=lambda d: max(d.get('start_time', 0), d.get('end_time', 0)), reverse=True)
            if btc_drawings:
                drawing = btc_drawings[0]  # First drawing (most recent after sorting)
                logger.info(f"TEST MODE: Using drawing {drawing.get('id')} for {drawing['user_email']}")
                symbol = 'BTCUSDT'
                resolution = drawing['resolution']
                kline_zset_key = f"zset:kline:{symbol}:{resolution}"
                latest_kline_list = await redis.zrevrange(kline_zset_key, 0, 1)
                if latest_kline_list:
                    latest_kline = json.loads(latest_kline_list[0])
                    prev_kline = json.loads(latest_kline_list[1]) if len(latest_kline_list) > 1 else None
                    fake_cross_info = await self.detect_cross(redis, drawing, latest_kline, prev_kline)
                    # If no real cross, force one by overriding
                    if not fake_cross_info:
                        # Force cross at close with line value or close
                        fake_cross_info = {"type": "price", "value": latest_kline['close']}
                        logger.info(f"TEST MODE: No real cross, forcing fake cross at {fake_cross_info}")
                    else:
                        logger.info(f"TEST MODE: Used real cross detection: {fake_cross_info}")
                    user_email = drawing['user_email']
                    alert_details = {
                        'symbol': symbol,
                        'resolution': resolution,
                        'line_id': drawing['id'],
                        'cross_time': latest_kline['time'],
                        'cross_value': fake_cross_info['value'],
                        'trigger_type': fake_cross_info['type'],
                        'indicator_name': fake_cross_info.get('indicator_name'),
                        'drawing': drawing
                    }
                    if user_email not in alerts_by_user:
                        alerts_by_user[user_email] = {}
                    if symbol not in alerts_by_user[user_email]:
                        alerts_by_user[user_email][symbol] = []
                    alerts_by_user[user_email][symbol].append(alert_details)
                    logger.info(f"TEST MODE: Forced alert for {user_email} on {symbol}")

        for user_email, symbol_alerts in alerts_by_user.items():
            for symbol, alerts in symbol_alerts.items():
                try:
                    logger.info(f"Processing {len(alerts)} alerts for {user_email} on {symbol}.")
                    message_body = "<h2>Price Alerts Triggered</h2>"
                    alert_actions = []
                    for alert in alerts:

                        if(alert.get("drawing")['user_email'] == "klemenzivkovic@gmail.com"):
                            cross_time_str = datetime.fromtimestamp(alert['cross_time']).strftime('%Y-%m-%d %H:%M:%S UTC')
                            if alert['trigger_type'] == 'price':
                                message_body += f"<p><b>{alert['symbol']}</b> price crossed a trendline at <b>{alert['cross_value']:.2f}</b> on {cross_time_str}.</p>"
                            else:
                                message_body += f"<p><b>{alert['symbol']}</b> indicator <b>{alert['indicator_name']}</b> crossed a trendline at <b>{alert['cross_value']:.2f}</b> on {cross_time_str}.</p>"

                            # Check for trading flags
                            properties = alert['drawing'].get('properties', {})
                            if properties.get('buyOnCross'):
                                if(alert.get("drawing", {}).get('buy_sent') == None):
                                    logger.info(f"Buy on cross enabled for symbol {symbol}")
                                    order_id, error_message = await self.place_trading_order(symbol, 'long', alert)
                                    if order_id:
                                        alert_actions.append(f"Placed LONG order for {symbol} (ID: {order_id})")
                                        alert['drawing']['buy_sent'] = True
                                    else:
                                        alert_actions.append(f"Failed LONG order for {symbol}: {error_message}")
                            if properties.get('sellOnCross'):
                                if(alert.get("drawing", {}).get('sell_sent') == None):
                                    logger.info(f"Sell on cross enabled for symbol {symbol}")
                                    order_id, error_message = await self.place_trading_order(symbol, 'short', alert)
                                    if order_id:
                                        alert_actions.append(f"Placed SHORT order for {symbol} (ID: {order_id})")
                                        alert['drawing']['sell_sent'] = True
                                    else:
                                        alert_actions.append(f"Failed SHORT order for {symbol}: {error_message}")
                            alert['drawing']['alert_actions'] = alert_actions

                    if alert_actions:
                        message_body += "<h3>Trading Actions:</h3><ul>"
                        for action in alert_actions:
                            message_body += f"<li>{action}</li>"
                        message_body += "</ul>"

                    logger.info(f"Generating chart image for {symbol}")
                    chart_image = await self.generate_alert_chart(user_email, symbol, alerts[0]['resolution'], alerts)
                    images = [(f"{symbol}_alert_chart.png", chart_image)] if chart_image else []
                    logger.info(f"Chart generated: {'Yes' if chart_image else 'No'}")

                    logger.info(f"Sending email to {user_email} for {len(alerts)} alerts on {symbol}")
                    await self.send_alert_email(user_email, f"Price Alerts for {symbol}", message_body, images)
                    logger.info(f"Email sent successfully to {user_email}")

                    # Mark drawings as sent to avoid re-triggering
                    await self.mark_drawings_as_sent(redis, alerts)
                except Exception as e:
                    logger.error(f"Failed to send alert email to {user_email} for {symbol}: {e}", exc_info=True)

    def _send_email_sync(self, to_email: str, subject: str, body: str, images: List[tuple[str, bytes]] = None):
        logger.info(f"Attempting to send email to {to_email}, subject: {subject}")
        msg = MIMEMultipart('related')
        msg['Subject'] = subject
        msg['From'] = self.smtp_config.from_email
        msg['To'] = to_email

        msg_alt = MIMEMultipart('alternative')
        msg.attach(msg_alt)
        msg_alt.attach(MIMEText(body, 'html'))

        if images:
            logger.debug(f"Including {len(images)} image(s) in email")
            for cid, (filename, img_data) in enumerate(images):
                image = MIMEImage(img_data, name=filename)
                image.add_header('Content-ID', f'<{cid}>')
                image.add_header('Content-Disposition', 'inline', filename=filename)
                msg.attach(image)

        try:
            logger.debug(f"Connecting to SMTP server {self.smtp_config.server}:{self.smtp_config.port}, use_tls={self.smtp_config.use_tls}")
            if self.smtp_config.port == 465:
                with smtplib.SMTP_SSL(self.smtp_config.server, self.smtp_config.port) as server:
                    logger.debug("Connected with SSL")
                    if self.smtp_config.username and self.smtp_config.password:
                        logger.debug("Attempting login")
                        server.login(self.smtp_config.username, self.smtp_config.password)
                        logger.debug("Login successful")
                    logger.debug("Sending message")
                    server.send_message(msg)
            else:
                with smtplib.SMTP(self.smtp_config.server, self.smtp_config.port) as server:
                    logger.debug("Connected without SSL")
                    if self.smtp_config.use_tls:
                        logger.debug("Starting TLS")
                        server.starttls()
                    logger.debug("Attempting login")
                    server.login(self.smtp_config.username, self.smtp_config.password)
                    logger.debug("Login successful")
                    logger.debug("Sending message")
                    server.send_message(msg)
            logger.info(f"Sent alert email to {to_email}")
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}", exc_info=True)

    async def send_alert_email(self, to_email: str, subject: str, body: str, images: List[tuple[str, bytes]] = None):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._send_email_sync, to_email, subject, body, images)

    async def mark_drawings_as_sent(self, redis: Redis, alerts: List[Dict]):
        """Marks drawings that triggered an alert as 'sent' in Redis to prevent duplicates."""
        if not alerts:
            return

        drawings_to_update = {}
        for alert in alerts:
            alert_drawing = alert.get('drawing', {})
            user_email = alert_drawing.get('user_email')
            symbol = alert_drawing.get('symbol')
            drawing_id = alert_drawing.get('id')
            if not all([user_email, symbol, drawing_id]):
                logger.warning(f"Skipping marking drawing as sent due to missing info: {alert_drawing}")
                continue

            key = (user_email, symbol)
            if key not in drawings_to_update:
                drawings_to_update[key] = {}
            drawings_to_update[key][drawing_id] = alert_drawing

        for (user_email, symbol), drawing_ids in drawings_to_update.items():
            redis_key = f"drawings:{user_email}:{symbol}"
            try:
                async with redis.pipeline(transaction=True) as pipe:
                    await pipe.watch(redis_key)
                    drawing_data = await pipe.get(redis_key)
                    if not drawing_data:
                        pipe.unwatch()
                        continue

                    user_drawings = json.loads(drawing_data)
                    
                    updated = False
                    for i, drawing in enumerate(user_drawings):
                        drawing_id_str = str(drawing.get('id'))
                        if drawing_id_str in drawing_ids:
                            alert_drawing = drawing_ids[drawing_id_str]
                            user_drawings[i]['alert_sent'] = True
                            alert_sent_time = int(datetime.now(timezone.utc).timestamp())
                            user_drawings[i]['alert_sent_time'] = alert_sent_time

                            # Also update properties for UI consistency
                            if 'properties' not in user_drawings[i]:
                                user_drawings[i]['properties'] = {}
                            user_drawings[i]['properties']['emailSent'] = True
                            user_drawings[i]['properties']['emailDate'] = alert_sent_time * 1000  # milliseconds for JS

                            # Copy buy_sent and sell_sent from the alert's drawing
                            if alert_drawing.get('buy_sent') is True:
                                user_drawings[i]['buy_sent'] = True
                            if alert_drawing.get('sell_sent') is True:
                                user_drawings[i]['sell_sent'] = True

                            # Copy alert_actions to properties for UI display
                            if 'alert_actions' in alert_drawing:
                                user_drawings[i]['properties']['alert_actions'] = alert_drawing['alert_actions']

                            updated = True

                    if updated:
                        pipe.multi()
                        pipe.set(redis_key, json.dumps(user_drawings))
                        await pipe.execute()
                        logger.info(f"Marked {len(drawing_ids)} drawings as sent for {user_email} on {symbol}")

            except Exception as e:
                logger.error(f"Error marking drawings as sent for {user_email} on {symbol}: {e}", exc_info=True)

    async def place_trading_order(self, symbol: str, action: str, alert_details: Dict) -> Tuple[Optional[str], Optional[str]]:
        """Place a trading order via trading_service if enabled. Returns (order_id, error_message)."""
        try:
            # Convert symbol from BTCUSDT to BTC-USDT format
            if symbol.endswith('USDT'):
                trading_symbol = symbol[:-4] + '-USDT'
            else:
                trading_symbol = symbol

            trading_service_url = "http://localhost:8000"
            endpoint = f"{trading_service_url}/{'buy' if action == 'long' else 'sell'}/{trading_symbol}"

            logger.info(f"Attempting to place {action} order for {symbol} ({trading_symbol}) via trading service")

            async with aiohttp.ClientSession() as session:
                async with session.post(endpoint) as response:
                    if response.status == 200:
                        result = await response.json()
                        order_id = result.get('orderId', 'unknown')
                        logger.info(f"Successfully placed {action} order for {symbol}: {order_id}")
                        return order_id, None
                    else:
                        error_text = await response.text()
                        error_message = f"HTTP {response.status}: {error_text}"
                        logger.error(f"Failed to place {action} order for {symbol}: {error_message}")
                        return None, error_message
        except Exception as e:
            error_message = str(e)
            logger.error(f"Exception while placing {action} order for {symbol}: {error_message}")
            return None, error_message

    async def remove_alert_after_delay(self, symbol: str, line_id: str, delay: int = 86400):
        await asyncio.sleep(delay)
        if symbol in self.active_alerts and line_id in self.active_alerts[symbol]:
            self.active_alerts[symbol].remove(line_id)

    async def monitor_alerts(self):
        logger.info("Email alert service monitor_alerts started.")
        while True:
            # Start check_price_alerts in background to ensure exact 60-second intervals
            asyncio.create_task(self.check_price_alerts())
            await asyncio.sleep(20)

def get_smtp_config() -> SMTPConfig:
    logger.info("Loading SMTP config...")
    try:
        creds = BybitCredentials.from_file(Path("c:/git/VidWebServer/authcreds.json"))
        logger.info(f"SMTP config loaded successfully: server={creds.SMTP_SERVER}, port={creds.SMTP_PORT}, user={creds.gmailEmail}")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Failed to load credentials: {e}")
        raise
    return SMTPConfig(server=creds.SMTP_SERVER, port=creds.SMTP_PORT, username=creds.gmailEmail, password=creds.gmailPwd, from_email=creds.gmailEmail)

smtp_config = get_smtp_config()
alert_service = EmailAlertService(smtp_config)
