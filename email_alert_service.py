import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from datetime import datetime, timezone
import pytz
import asyncio
import json
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging
from redis.asyncio import Redis
from pathlib import Path
from AppTradingView import get_redis_connection, SUPPORTED_SYMBOLS, _calculate_and_return_indicators, get_timeframe_seconds, BybitCredentials, fetch_klines_from_bybit, cache_klines, get_cached_klines
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

logger = logging.getLogger(__name__)

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
                        for drawing in user_drawings:
                            drawing['user_email'] = user_email
                        drawings.extend(user_drawings)
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
        start_time = cross_time - (timeframe_seconds * 200) # Get 200 candles of context
        klines = await get_cached_klines(symbol, resolution, start_time, cross_time + timeframe_seconds) # Fetch slightly past cross time
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
            indicator_data_response = await _calculate_and_return_indicators(symbol, resolution, start_time, cross_time + timeframe_seconds, [indicator_name])
            
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
                
                # Plot all data columns from the indicator except 't'
                for col in indicator_df.columns:
                    if col != 't':
                        trace_color = indicator_colors.get(col.lower(), 'blue')
                        fig.add_trace(go.Scatter(
                            x=indicator_df['t'], y=indicator_df[col], mode='lines', 
                            name=f"{indicator_name}-{col}", line=dict(color=trace_color, width=1.5)
                        ), row=i, col=1)
                
                # Special handling for RSI overbought/oversold lines
                if 'rsi' in indicator_name.lower():
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
        fig.update_layout(
            title_text=f'{symbol} Alert ({resolution}) - {datetime.now(pytz.timezone("America/New_York")).strftime("%Y-%m-%d %H:%M:%S")}',
            template='plotly_white',
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=70, r=70, t=100, b=80),
            xaxis_rangeslider_visible=False,
            font=dict(family="Arial, sans-serif", size=12, color="black")
        )
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

    async def check_price_alerts(self):
        logger.info("Starting check_price_alerts cycle.")
        try:
            redis = await get_redis_connection()
            drawings = await self.get_all_drawings(redis)
            logger.info(f"Found {len(drawings)} drawings to check.")
        except Exception as e:
            logger.error(f"Error connecting to Redis or getting drawings: {e}", exc_info=True)
            return

        alerts_by_user = {}

        for idx, drawing in enumerate(drawings):
            try:
                symbol = drawing.get('symbol')
                user_email = drawing.get('user_email')
                if not symbol or not user_email:
                    logger.warning(f"Skipping drawing with missing symbol or email: {drawing.get('id', 'N/A')}")
                    continue

                logger.debug(f"Checking drawing {idx+1}/{len(drawings)} for {symbol} by {user_email}")

                resolution = drawing['resolution']
                kline_zset_key = f"zset:kline:{symbol}:{resolution}"
                latest_kline_list = await redis.zrevrange(kline_zset_key, 0, 1)

                if not latest_kline_list or len(latest_kline_list) < 2:
                    logger.warning(f"Not enough kline data for {symbol} to check for crosses.")
                    continue

                latest_kline = json.loads(latest_kline_list[0])
                prev_kline = json.loads(latest_kline_list[1])

                cross_info = await self.detect_cross(redis, drawing, latest_kline, prev_kline)
                
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

        for user_email, symbol_alerts in alerts_by_user.items():
            for symbol, alerts in symbol_alerts.items():
                try:
                    logger.info(f"Processing {len(alerts)} alerts for {user_email} on {symbol}.")
                    message_body = "<h2>Price Alerts Triggered</h2>"
                    for alert in alerts:
                        cross_time_str = datetime.fromtimestamp(alert['cross_time']).strftime('%Y-%m-%d %H:%M:%S UTC')
                        if alert['trigger_type'] == 'price':
                            message_body += f"<p><b>{alert['symbol']}</b> price crossed a trendline at <b>{alert['cross_value']:.2f}</b> on {cross_time_str}.</p>"
                        else:
                            message_body += f"<p><b>{alert['symbol']}</b> indicator <b>{alert['indicator_name']}</b> crossed a trendline at <b>{alert['cross_value']:.2f}</b> on {cross_time_str}.</p>"
                    
                    chart_image = await self.generate_alert_chart(user_email, symbol, alerts[0]['resolution'], alerts)
                    images = [(f"{symbol}_alert_chart.png", chart_image)] if chart_image else []

                    await self.send_alert_email(user_email, f"Price Alerts for {symbol}", message_body, images)
                    logger.info(f"Sent cumulative alert email to {user_email} for {len(alerts)} events on {symbol}.")
                except Exception as e:
                    logger.error(f"Failed to send alert email to {user_email} for {symbol}: {e}", exc_info=True)

    def _send_email_sync(self, to_email: str, subject: str, body: str, images: List[tuple[str, bytes]] = None):
        msg = MIMEMultipart('related')
        msg['Subject'] = subject
        msg['From'] = self.smtp_config.from_email
        msg['To'] = to_email

        msg_alt = MIMEMultipart('alternative')
        msg.attach(msg_alt)
        msg_alt.attach(MIMEText(body, 'html'))

        if images:
            for cid, (filename, img_data) in enumerate(images):
                image = MIMEImage(img_data, name=filename)
                image.add_header('Content-ID', f'<{cid}>')
                image.add_header('Content-Disposition', 'inline', filename=filename)
                msg.attach(image)

        try:
            if self.smtp_config.port == 465:
                with smtplib.SMTP_SSL(self.smtp_config.server, self.smtp_config.port) as server:
                    if self.smtp_config.username and self.smtp_config.password:
                        server.login(self.smtp_config.username, self.smtp_config.password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(self.smtp_config.server, self.smtp_config.port) as server:
                    if self.smtp_config.use_tls:
                        server.starttls()
                    server.login(self.smtp_config.username, self.smtp_config.password)
                    server.send_message(msg)
            logger.info(f"Sent alert email to {to_email}")
        except Exception as e:
            logger.error(f"Failed to send email: {e}", exc_info=True)

    async def send_alert_email(self, to_email: str, subject: str, body: str, images: List[tuple[str, bytes]] = None):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._send_email_sync, to_email, subject, body, images)

    async def remove_alert_after_delay(self, symbol: str, line_id: str, delay: int = 86400):
        await asyncio.sleep(delay)
        if symbol in self.active_alerts and line_id in self.active_alerts[symbol]:
            self.active_alerts[symbol].remove(line_id)

    async def monitor_alerts(self):
        while True:
            await self.check_price_alerts()
            await asyncio.sleep(20)

def get_smtp_config() -> SMTPConfig:
    try:
        creds = BybitCredentials.from_file(Path("c:/git/VidWebServer/authcreds.json"))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Failed to load credentials: {e}")
        raise
    return SMTPConfig(server=creds.SMTP_SERVER, port=creds.SMTP_PORT, username=creds.gmailEmail, password=creds.gmailPwd, from_email=creds.gmailEmail)

smtp_config = get_smtp_config()
alert_service = EmailAlertService(smtp_config)
