import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from datetime import datetime
import asyncio
import json
from typing import Dict, List, Optional
from dataclasses import dataclass
import logging
from redis.asyncio import Redis
from pathlib import Path
from AppTradingView import get_redis_connection, SUPPORTED_SYMBOLS, _calculate_and_return_indicators, get_timeframe_seconds, BybitCredentials, fetch_klines_from_bybit, cache_klines, get_cached_klines
import plotly.graph_objects as go
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

    async def generate_alert_chart(self, symbol: str, resolution: str, cross_time: int, cross_price: float, drawing: Dict, klines: List[Dict]) -> Optional[bytes]:
        """Generate a chart image for the alert."""
        if not klines:
            return None

        df = pd.DataFrame(klines)
        df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)

        fig = go.Figure()

        # Add candlestick trace
        fig.add_trace(go.Candlestick(x=df['time'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'))

        # Add trendline by projecting it onto the chart's visible time range
        t1_ts = drawing['start_time']
        p1 = drawing['start_price']
        t2_ts = drawing['end_time']
        p2 = drawing['end_price']

        chart_start_dt = df['time'].iloc[0]
        chart_end_dt = df['time'].iloc[-1]

        # Handle vertical line case
        if t1_ts == t2_ts:
            line_dt = datetime.fromtimestamp(t1_ts, tz=timezone.utc)
            # Only draw if the line is within the chart's time range
            if chart_start_dt <= line_dt <= chart_end_dt:
                fig.add_trace(go.Scatter(x=[line_dt, line_dt], y=[p1, p2], mode='lines', name='Trendline', line=dict(color='blue', width=2)))
        else:
            # Calculate slope and project the line onto the chart's x-axis
            slope = (p2 - p1) / (t2_ts - t1_ts)
            
            chart_start_ts = int(chart_start_dt.timestamp())
            chart_end_ts = int(chart_end_dt.timestamp())

            projected_start_price = slope * (chart_start_ts - t1_ts) + p1
            projected_end_price = slope * (chart_end_ts - t1_ts) + p1
            
            fig.add_trace(go.Scatter(x=[chart_start_dt, chart_end_dt], y=[projected_start_price, projected_end_price], mode='lines', name='Trendline', line=dict(color='blue', width=2)))

        # Add circle for crossing point
        cross_dt = datetime.fromtimestamp(cross_time, tz=timezone.utc)
        fig.add_trace(go.Scatter(x=[cross_dt], y=[cross_price], mode='markers', name='Cross Event', marker=dict(color='red', size=10, symbol='circle')))

        fig.update_layout(title=f'{symbol} Price Chart', xaxis_title='Time', yaxis_title='Price', xaxis_rangeslider_visible=False)

        try:
            img_bytes = fig.to_image(format="png")
            return img_bytes
        except Exception as e:
            logger.error(f"Failed to generate chart image: {e}", exc_info=True)
            return None

    async def detect_cross(self, redis: Redis, symbol: str, resolution: str, line_id: str,
                           current_value: float, line_start: float, line_end: float,
                           bar_low: float, bar_high: float,
                           indicator_name: Optional[str] = None,
                           prev_price: Optional[float] = None) -> bool:
        """Detect if value or indicator crosses a trend line over time"""
        prev_value = None
        if indicator_name:
            from datetime import datetime, timezone
            try:
                to_ts = int(datetime.now(timezone.utc).timestamp())
                timeframe_sec = get_timeframe_seconds(resolution)
                from_ts = to_ts - (100 * timeframe_sec)
                indicator_data_response = await _calculate_and_return_indicators(symbol, resolution, from_ts, to_ts, [indicator_name])
                if hasattr(indicator_data_response, 'body'):
                    response_data = json.loads(indicator_data_response.body)
                    if response_data.get('s') == 'ok':
                        data = response_data.get('data', {})
                        if indicator_name in data:
                            indicator_result = data[indicator_name]
                            value_key = None
                            if indicator_result.get('s') == 'ok':
                                value_keys = [k for k, v in indicator_result.items() if isinstance(v, list) and k != 't']
                                if value_keys:
                                    value_key = value_keys[0]
                            if value_key and indicator_result.get(value_key):
                                values = [v for v in indicator_result[value_key] if v is not None]
                                if len(values) >= 2:
                                    current_value = values[-1]
                                    prev_value = values[-2]
            except Exception as e:
                logger.error(f"Error calculating indicator {indicator_name} for cross detection: {str(e)}", exc_info=True)
        else:
            prev_value = prev_price

        if prev_value is None:
            return False

        if indicator_name:
            line_min = min(line_start, line_end)
            line_max = max(line_start, line_end)
            return ((prev_value < line_min and current_value > line_max) or (prev_value > line_max and current_value < line_min))

        def line_intersects_bar(x1, y1, x2, y2, bar_low, bar_high):
            if x2 == x1:
                return min(bar_low, bar_high) <= y1 <= max(bar_low, bar_high)
            m = (y2 - y1) / (x2 - x1)
            y_at_bar_low = m * (bar_low - x1) + y1
            y_at_bar_high = m * (bar_high - x1) + y1
            return ((bar_low <= y_at_bar_low <= bar_high) or (bar_low <= y_at_bar_high <= bar_high) or (min(y_at_bar_low, y_at_bar_high) <= bar_low <= max(y_at_bar_low, y_at_bar_high)) or (min(y_at_bar_low, y_at_bar_high) <= bar_high <= max(y_at_bar_low, y_at_bar_high)))

        return line_intersects_bar(line_start, line_start, line_end, line_end, bar_low, bar_high)

    async def check_price_alerts(self):
        redis = await get_redis_connection()
        drawings = await self.get_all_drawings(redis)
        logger.info(f"🔄 Starting price alert check for {len(drawings)} drawings")
        
        alerts_by_user = {}

        for idx, drawing in enumerate(drawings, 1):
            symbol = drawing.get('symbol')
            if symbol not in SUPPORTED_SYMBOLS:
                logger.debug(f"⏩ Skipping unsupported symbol: {symbol} ({idx}/{len(drawings)})")
                continue

            timeframe_for_price = "1m"
            kline_zset_key = f"zset:kline:{symbol}:{timeframe_for_price}"
            latest_kline_list = await redis.zrevrange(kline_zset_key, 0, 1)

            current_price, current_low, current_high, prev_price, cross_time = None, None, None, None, None
            if latest_kline_list:
                try:
                    if len(latest_kline_list) >= 1:
                        latest_kline = json.loads(latest_kline_list[0])
                        current_price = float(latest_kline['close'])
                        current_low = float(latest_kline['low'])
                        current_high = float(latest_kline['high'])
                        cross_time = latest_kline['time']
                    if len(latest_kline_list) >= 2:
                        prev_kline = json.loads(latest_kline_list[1])
                        prev_price = float(prev_kline['close'])
                except (json.JSONDecodeError, KeyError, IndexError) as e:
                    logger.error(f"Error parsing kline from Redis for {symbol}: {e}")
            
            if current_price is None:
                logger.warning(f"⚠️ No valid kline data for {symbol} in Redis. Fetching from Bybit.")
                try:
                    end_ts = int(datetime.now(timezone.utc).timestamp())
                    timeframe_seconds = get_timeframe_seconds(timeframe_for_price)
                    start_ts = end_ts - (3 * timeframe_seconds)
                    bybit_klines = fetch_klines_from_bybit(symbol, timeframe_for_price, start_ts, end_ts)
                    if bybit_klines:
                        await cache_klines(symbol, timeframe_for_price, bybit_klines)
                        if len(bybit_klines) >= 1:
                            current_price = float(bybit_klines[-1]['close'])
                            current_low = float(bybit_klines[-1]['low'])
                            current_high = float(bybit_klines[-1]['high'])
                            cross_time = bybit_klines[-1]['time']
                        if len(bybit_klines) >= 2:
                            prev_price = float(bybit_klines[-2]['close'])
                        logger.info(f"Successfully fetched price for {symbol} from Bybit: {current_price}")
                except Exception as e:
                    logger.error(f"Error during Bybit fallback fetch for {symbol}: {e}", exc_info=True)
                    continue

            if current_price is None:
                logger.warning(f"⚠️ Could not determine current price for {symbol}. Skipping.")
                continue

            line_start, line_end, resolution, line_id = drawing.get('start_price'), drawing.get('end_price'), drawing.get('resolution', '1h'), drawing.get('id')
            if None in (line_start, line_end, line_id):
                logger.debug(f"❌ Incomplete data for {symbol} drawing {line_id or 'unknown'}")
                continue

            subplot_name = drawing.get('subplot_name')
            indicator_name = None
            if subplot_name and subplot_name.startswith(f"{symbol}-"):
                indicator_name = subplot_name.split('-', 1)[1]
            
            crossed = await self.detect_cross(redis, symbol, resolution, line_id, current_price, line_start, line_end, current_low, current_high, indicator_name=indicator_name, prev_price=prev_price)
            
            if crossed:
                logger.info(f"Price cross detected for {symbol} line {line_id} at {current_price}")
                user_email = drawing.get('user_email')
                if user_email:
                    cross_time_str = datetime.fromtimestamp(cross_time, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
                    alert_details = {
                        'symbol': symbol,
                        'resolution': resolution,
                        'line_id': line_id,
                        'cross_price': current_price,
                        'cross_time': cross_time,
                        'cross_time_str': cross_time_str,
                        'drawing': drawing
                    }
                    if user_email not in alerts_by_user:
                        alerts_by_user[user_email] = []
                    alerts_by_user[user_email].append(alert_details)

        for user_email, alerts in alerts_by_user.items():
            if not alerts:
                continue
            
            message_body = "<h2>Price Alerts Triggered</h2>"
            images = []
            for alert in alerts:
                cross_time_str = datetime.fromtimestamp(alert['cross_time']).strftime('%Y-%m-%d %H:%M:%S UTC')
                message_body += f"<p><b>{alert['symbol']}</b> crossed a trendline at <b>{alert['cross_price']}</b> on {cross_time_str}.</p>"
                
                # Generate chart
                end_ts = alert['cross_time']
                start_ts = end_ts - (100 * get_timeframe_seconds(alert['resolution']))
                klines = await get_cached_klines(alert['symbol'], alert['resolution'], start_ts, end_ts)
                chart_image = await self.generate_alert_chart(alert['symbol'], alert['resolution'], alert['cross_time'], alert['cross_price'], alert['drawing'], klines)
                if chart_image:
                    images.append((f"{alert['symbol']}_chart.png", chart_image))

            try:
                await self.send_alert_email(user_email, f"Price Alerts for {', '.join(set(a['symbol'] for a in alerts))}", message_body, images)
                logger.info(f"Sent cumulative alert email to {user_email} for {len(alerts)} events.")
            except Exception as e:
                logger.error(f"Failed to send cumulative alert email to {user_email}: {str(e)}")

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
            await asyncio.sleep(60)

def get_smtp_config() -> SMTPConfig:
    try:
        creds = BybitCredentials.from_file(Path("c:/git/VidWebServer/authcreds.json"))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Failed to load credentials: {e}")
        raise
    return SMTPConfig(server=creds.SMTP_SERVER, port=creds.SMTP_PORT, username=creds.gmailEmail, password=creds.gmailPwd, from_email=creds.gmailEmail)

smtp_config = get_smtp_config()
alert_service = EmailAlertService(smtp_config)