import asyncio
import logging

# Set up logging to see any messages from the email_alert_service module
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

from email_alert_service import get_smtp_config, alert_service

async def main():
    print("Testing email_alert_service import and basic functionality...")

    try:
        # Test getting SMTP config
        smtp_config = get_smtp_config()
        print(f"SMTP config loaded: server={smtp_config.server}, port={smtp_config.port}, from_email={smtp_config.from_email}")

        # Test that alert_service is initialized
        print(f"EmailAlertService instance created: {alert_service}")

        # Test calling a non-async method if available, but since most are async, just check attributes
        print(f"Active alerts: {len(alert_service.active_alerts)}")

        print("Basic tests passed! Now running functional test with real data...")

        # Run the real check_price_alerts with test=True to force fake crossover and send email
        await alert_service.check_price_alerts(test=True)

        print("Functional test completed! Email should have been sent with real BTCUSDT data and chart.")

    except Exception as e:
        print(f"Test failed with error: {e}")
        raise

if __name__ == '__main__':
    asyncio.run(main())
