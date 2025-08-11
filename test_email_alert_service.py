

import asyncio
import json
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

from email_alert_service import EmailAlertService, SMTPConfig

class TestEmailAlertService(unittest.TestCase):

    def setUp(self):
        self.smtp_config = SMTPConfig(
            server="smtp.test.com",
            port=587,
            username="testuser",
            password="testpassword",
            from_email="test@test.com",
            use_tls=True
        )
        self.alert_service = EmailAlertService(self.smtp_config)

    @patch('email_alert_service._calculate_and_return_indicators')
    @patch('email_alert_service.get_cached_klines')
    @patch('email_alert_service.EmailAlertService.get_all_drawings')
    @patch('email_alert_service.get_redis_connection')
    def test_check_price_alerts_price_cross_and_generate_chart(self, mock_get_redis, mock_get_all_drawings, mock_get_cached_klines, mock_calculate_indicators):
        # --- Test Scenario: Price crosses a trendline and generate a chart ---

        # Mock Redis
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis

        # Mock drawing data
        mock_drawing = {
            "id": "test_drawing_1",
            "symbol": "BTCUSDT",
            "resolution": "1h",
            "user_email": "test@example.com",
            "start_time": 1672531200,  # 2023-01-01 00:00:00
            "start_price": 20000,
            "end_time": 1672617600,    # 2023-01-02 00:00:00
            "end_price": 21000,
            "subplot_name": "BTCUSDT"
        }
        mock_get_all_drawings.return_value = [mock_drawing]

        # Mock k-line data
        prev_kline = {"time": 1672574400, "low": 20400, "high": 20450, "close": 20420, "open": 20410, "volume": 100}
        latest_kline = {"time": 1672578000, "low": 20530, "high": 20550, "close": 20545, "open": 20535, "volume": 120}
        mock_redis.zrevrange.return_value = [json.dumps(latest_kline), json.dumps(prev_kline)]
        mock_get_cached_klines.return_value = [prev_kline, latest_kline]

        # Mock indicator data
        mock_calculate_indicators.return_value = {
            'data': {
                'rsi': {
                    't': [1672574400, 1672578000],
                    'rsi': [50, 60]
                }
            }
        }

        # Mock settings
        mock_redis.get.return_value = json.dumps({'activeIndicators': ['rsi']})

        # Mock the email sending
        self.alert_service.send_alert_email = AsyncMock()

        # Run the alert check
        asyncio.run(self.alert_service.check_price_alerts())

        # Assert that an email was sent
        self.alert_service.send_alert_email.assert_called_once()

        # Now, let's get the chart image
        # The call to send_alert_email has the image in its arguments
        call_args = self.alert_service.send_alert_email.call_args
        images = call_args[0][3]
        self.assertEqual(len(images), 1)
        filename, image_bytes = images[0]
        self.assertEqual(filename, "BTCUSDT_alert_chart.png")

        # Save the chart to a file
        with open("test_chart.png", "wb") as f:
            f.write(image_bytes)

    @patch('email_alert_service.EmailAlertService.get_all_drawings')
    @patch('email_alert_service.get_redis_connection')
    def test_check_price_alerts_no_cross(self, mock_get_redis, mock_get_all_drawings):
        # --- Test Scenario: Price does NOT cross a trendline ---

        # Mock Redis
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis

        # Mock drawing data
        mock_drawing = {
            "id": "test_drawing_2",
            "symbol": "ETHUSDT",
            "resolution": "1h",
            "user_email": "test2@example.com",
            "start_time": 1672531200,
            "start_price": 1200,
            "end_time": 1672617600,
            "end_price": 1300,
            "subplot_name": "ETHUSDT"
        }
        mock_get_all_drawings.return_value = [mock_drawing]

        # Mock k-line data (no cross)
        prev_kline = {"time": 1672574400, "low": 1210, "high": 1215, "close": 1212}
        latest_kline = {"time": 1672578000, "low": 1216, "high": 1220, "close": 1218}
        mock_redis.zrevrange.return_value = [json.dumps(latest_kline), json.dumps(prev_kline)]

        # Mock the email sending
        self.alert_service.send_alert_email = AsyncMock()

        # Run the alert check
        asyncio.run(self.alert_service.check_price_alerts())

        # Assert that NO email was sent
        self.alert_service.send_alert_email.assert_not_called()

if __name__ == '__main__':
    unittest.main()
