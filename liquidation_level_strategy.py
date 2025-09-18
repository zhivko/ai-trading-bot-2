import requests
import asyncio
import json
import time
import re
from datetime import datetime, timedelta
from collections import defaultdict
from pybit.unified_trading import WebSocket as BybitWS, HTTP
import logging

try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    logging.warning("OCR libraries not available. Image analysis will be limited.")

# Import credentials at module level to avoid circular imports
from auth import creds

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_youtube_thumbnail(video_id, output_filename='liquidation_levels.jpg'):
    """
    Downloads the high-resolution thumbnail image for a YouTube video.

    Args:
        video_id (str): The YouTube video ID (e.g., 'BDO-ef4n_J4')
        output_filename (str): The filename to save the image as (default: 'liquidation_levels.jpg')
    """
    thumbnail_url = f'https://img.youtube.com/vi/{video_id}/maxresdefault.jpg'

    try:
        response = requests.get(thumbnail_url)
        response.raise_for_status()  # Raise an error for bad status codes

        with open(output_filename, 'wb') as f:
            f.write(response.content)

        print(f"Thumbnail downloaded successfully and saved as {output_filename}")

    except requests.exceptions.RequestException as e:
        print(f"Error downloading thumbnail: {e}")

def extract_bitcoin_price_from_image(image_path='liquidation_levels.jpg'):
    """
    Extract Bitcoin price from the downloaded image using OCR.

    Args:
        image_path (str): Path to the image file

    Returns:
        float or None: Extracted Bitcoin price, or None if not found
    """
    if not OCR_AVAILABLE:
        logger.warning("OCR not available. Cannot extract price from image.")
        return None

    try:
        # Open the image
        image = Image.open(image_path)

        # Convert to RGB if necessary
        if image.mode != 'RGB':
            image = image.convert('RGB')

        # Extract text using OCR
        text = pytesseract.image_to_string(image)

        logger.info(f"OCR extracted text: {text[:500]}...")  # Log first 500 chars

        # Look for Bitcoin price patterns
        # Common patterns: $45,000, 45000, 45,000 BTC, etc.
        price_patterns = [
            r'\$([0-9,]+)',  # $45,000
            r'([0-9,]+)\s*BTC',  # 45000 BTC
            r'BTC\s*([0-9,]+)',  # BTC 45000
            r'([0-9,]+)\s*USD',  # 45000 USD
            r'PRICE[:\s]*([0-9,]+)',  # PRICE: 45000
        ]

        for pattern in price_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                # Clean the price string
                price_str = match.replace(',', '')
                try:
                    price = float(price_str)
                    # Validate reasonable Bitcoin price range (assume $10,000 - $200,000)
                    if 10000 <= price <= 200000:
                        logger.info(f"Found Bitcoin price: ${price}")
                        return price
                except ValueError:
                    continue

        logger.warning("No valid Bitcoin price found in image")
        return None

    except Exception as e:
        logger.error(f"Error extracting price from image: {e}")
        return None

class LiquidationLevelStrategy:
    """
    Trading strategy based on liquidation levels from Bybit.

    The strategy identifies liquidation levels by analyzing recent liquidation data
    and trades based on the setups described in the YouTube video.
    """

    def __init__(self, symbol='BTCUSDT'):
        self.symbol = symbol
        self.liquidation_data = []
        self.levels = {
            'red': [],    # 100x+ leverage
            'yellow': [], # 50-100x leverage
            'blue': []    # 25-50x leverage
        }
        self._session = None  # Lazy initialization

    @property
    def session(self):
        """Lazy initialization of Bybit session."""
        if self._session is None:
            self._session = HTTP(
                api_key=creds.api_key,
                api_secret=creds.api_secret,
                testnet=False,
                recv_window=20000,
                max_retries=1
            )
        return self._session

    def collect_liquidation_data(self, duration_hours=24):
        """
        Collect liquidation data from Bybit for the specified duration.
        """
        try:
            # Get liquidation orders from Bybit
            # Note: Bybit API may have limitations on historical liquidation data
            # This is a placeholder - actual implementation may need websocket streaming
            end_time = int(time.time() * 1000)
            start_time = end_time - (duration_hours * 60 * 60 * 1000)

            # Bybit doesn't have direct REST API for historical liquidations
            # We would need to use websocket to collect real-time data
            # For now, we'll simulate with some sample data
            logger.info(f"Collecting liquidation data for {self.symbol} over {duration_hours} hours")

            # In real implementation, this would connect to websocket and collect data
            # For demonstration, we'll create sample data
            self._simulate_liquidation_data()

        except Exception as e:
            logger.error(f"Error collecting liquidation data: {e}")

    def get_current_price(self):
        """
        Get the current price for the symbol from Bybit.

        Returns:
            float: Current price, or None if unable to fetch
        """
        try:
            # Use Bybit REST API to get current ticker price
            response = self.session.get_tickers(
                category="linear",
                symbol=self.symbol
            )

            if response.get("retCode") == 0:
                ticker_data = response.get("result", {}).get("list", [])
                if ticker_data:
                    current_price = float(ticker_data[0].get("lastPrice", 0))
                    logger.info(f"Current {self.symbol} price from Bybit: ${current_price}")
                    return current_price
                else:
                    logger.error("No ticker data received from Bybit")
                    return None
            else:
                logger.error(f"Bybit API error: {response.get('retMsg')}")
                return None

        except Exception as e:
            logger.error(f"Error fetching current price: {e}")
            return None

    def _simulate_liquidation_data(self):
        """
        Simulate liquidation data for testing purposes.
        In real implementation, this would be replaced with actual websocket data collection.
        Using realistic price levels around current Bitcoin price.
        """
        # Get current price to create realistic liquidation levels
        current_price = self.get_current_price() or 116000  # Fallback if API fails

        # Create liquidation levels around current price +/- 10%
        base_price = current_price

        # Sample liquidation data with realistic leverage distribution
        sample_data = [
            # High leverage liquidations (red) - above current price
            {'price': base_price + 2000, 'side': 'long', 'leverage': 120, 'quantity': 8},
            {'price': base_price + 1500, 'side': 'long', 'leverage': 150, 'quantity': 5},
            {'price': base_price + 1800, 'side': 'short', 'leverage': 110, 'quantity': 6},

            # Medium leverage liquidations (yellow) - around current price
            {'price': base_price + 500, 'side': 'long', 'leverage': 80, 'quantity': 12},
            {'price': base_price - 300, 'side': 'short', 'leverage': 65, 'quantity': 9},
            {'price': base_price + 200, 'side': 'long', 'leverage': 75, 'quantity': 7},

            # Low leverage liquidations (blue) - below current price
            {'price': base_price - 800, 'side': 'long', 'leverage': 30, 'quantity': 15},
            {'price': base_price - 1200, 'side': 'short', 'leverage': 40, 'quantity': 11},
            {'price': base_price - 600, 'side': 'long', 'leverage': 25, 'quantity': 18},
            {'price': base_price - 1000, 'side': 'short', 'leverage': 35, 'quantity': 13},
        ]
        self.liquidation_data = sample_data
        logger.info(f"Simulated {len(sample_data)} liquidation events around price ${base_price:,.0f}")

    def analyze_levels(self):
        """
        Analyze liquidation data to identify levels based on leverage tiers.
        """
        if not self.liquidation_data:
            logger.warning("No liquidation data to analyze")
            return

        # Group liquidations by price ranges and leverage
        price_groups = defaultdict(lambda: {'red': 0, 'yellow': 0, 'blue': 0, 'total_qty': 0})

        for liq in self.liquidation_data:
            price = liq['price']
            leverage = liq['leverage']
            quantity = liq['quantity']

            # Round price to nearest 100 for grouping
            price_group = round(price / 100) * 100

            if leverage >= 100:
                price_groups[price_group]['red'] += quantity
            elif 50 <= leverage < 100:
                price_groups[price_group]['yellow'] += quantity
            elif 25 <= leverage < 50:
                price_groups[price_group]['blue'] += quantity

            price_groups[price_group]['total_qty'] += quantity

        # Identify significant levels (where liquidation quantity is above threshold)
        threshold = max([g['total_qty'] for g in price_groups.values()]) * 0.1  # Top 10%

        for price, data in price_groups.items():
            if data['total_qty'] >= threshold:
                if data['red'] > data['yellow'] and data['red'] > data['blue']:
                    self.levels['red'].append(price)
                elif data['yellow'] > data['blue']:
                    self.levels['yellow'].append(price)
                else:
                    self.levels['blue'].append(price)

        # Sort levels
        for color in self.levels:
            self.levels[color].sort()

        logger.info(f"Identified levels: Red={len(self.levels['red'])}, Yellow={len(self.levels['yellow'])}, Blue={len(self.levels['blue'])}")

    def identify_setups(self, current_price):
        """
        Identify trading setups based on current price and liquidation levels.

        Returns:
            dict: Setup information with entry signals
        """
        setups = {
            'short_setup_A': None,
            'short_setup_B': None,
            'short_setup_C': None,
            'long_setup_A': None,
            'long_setup_B': None,
            'long_setup_C': None
        }

        # Short Setup A: where the top blue lines end
        if self.levels['blue']:
            top_blue = max(self.levels['blue'])
            if current_price > top_blue:
                setups['short_setup_A'] = top_blue

        # Short Setup B: where upper yellow meets upper blue
        if self.levels['yellow'] and self.levels['blue']:
            upper_yellow = max(self.levels['yellow'])
            upper_blue = max(self.levels['blue'])
            if abs(upper_yellow - upper_blue) < 100:  # Within 100 price units
                setups['short_setup_B'] = (upper_yellow + upper_blue) / 2

        # Short Setup C: where upper red meets upper yellow
        if self.levels['red'] and self.levels['yellow']:
            upper_red = max(self.levels['red'])
            upper_yellow = max(self.levels['yellow'])
            if abs(upper_red - upper_yellow) < 100:
                setups['short_setup_C'] = (upper_red + upper_yellow) / 2

        # Long Setup A: where lower blue lines end
        if self.levels['blue']:
            lower_blue = min(self.levels['blue'])
            if current_price < lower_blue:
                setups['long_setup_A'] = lower_blue

        # Long Setup B: where lower yellow meets lower blue
        if self.levels['yellow'] and self.levels['blue']:
            lower_yellow = min(self.levels['yellow'])
            lower_blue = min(self.levels['blue'])
            if abs(lower_yellow - lower_blue) < 100:
                setups['long_setup_B'] = (lower_yellow + lower_blue) / 2

        # Long Setup C: where lower red meets lower yellow
        if self.levels['red'] and self.levels['yellow']:
            lower_red = min(self.levels['red'])
            lower_yellow = min(self.levels['yellow'])
            if abs(lower_red - lower_yellow) < 100:
                setups['long_setup_C'] = (lower_red + lower_yellow) / 2

        return setups

    def execute_trade(self, setup_type, entry_price, stop_loss=None):
        """
        Execute a trade based on the identified setup.

        Args:
            setup_type (str): Type of setup (e.g., 'short_setup_A')
            entry_price (float): Entry price for the trade
            stop_loss (float, optional): Stop loss price
        """
        try:
            # Determine side based on setup type
            if 'short' in setup_type:
                side = 'Sell'
                qty = 0.001  # Small test quantity
            elif 'long' in setup_type:
                side = 'Buy'
                qty = 0.001
            else:
                logger.error(f"Unknown setup type: {setup_type}")
                return

            # Place order
            order = self.session.place_order(
                category="linear",
                symbol=self.symbol,
                side=side,
                orderType="Market",
                qty=qty
            )

            if order.get('retCode') == 0:
                logger.info(f"Successfully placed {setup_type} order at {entry_price}")
                return order
            else:
                logger.error(f"Failed to place order: {order.get('retMsg')}")
                return None

        except Exception as e:
            logger.error(f"Error executing trade: {e}")
            return None

if __name__ == "__main__":
    # First, get the YouTube thumbnail
    video_id = 'BDO-ef4n_J4'
    get_youtube_thumbnail(video_id)

    # Initialize the strategy
    strategy = LiquidationLevelStrategy('BTCUSDT')

    # Get real current price from Bybit
    current_price = strategy.get_current_price()
    if current_price is None:
        logger.error("Failed to get current price from Bybit. Cannot proceed.")
        exit(1)

    # Collect and analyze liquidation data
    strategy.collect_liquidation_data()
    strategy.analyze_levels()

    # Check setups for current price
    setups = strategy.identify_setups(current_price)

    logger.info(f"Current {strategy.symbol} price: ${current_price}")
    logger.info(f"Available setups: {setups}")

    # Example trade execution (commented out for safety)
    # for setup_type, price in setups.items():
    #     if price is not None:
    #         strategy.execute_trade(setup_type, price)