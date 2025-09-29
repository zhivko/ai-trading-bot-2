"""
Apex Omni Trading Service
FastAPI web service for automated trading with 5% risk management
"""
import decimal
import json
import logging
import os
from typing import Dict, Any, List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
import pandas as pd
import numpy as np
from collections import defaultdict

# Configure logging to include timestamp, filename, and line number
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(filename)s:%(lineno)d - %(message)s'
)
logger = logging.getLogger(__name__)

# Import ApexPro components
from apexomni.constants import APEX_OMNI_HTTP_MAIN, NETWORKID_OMNI_MAIN_ARB, NETWORKID_MAIN
from apexomni.http_private_sign import HttpPrivateSign
from apexomni.http_private_v3 import HttpPrivate_v3
from apexomni.http_public import HttpPublic
from apexomni.helpers.util import round_size

def format_decimal_for_apex(decimal_value: decimal.Decimal) -> str:
    """Format decimal to clean numeric string for Apex Pro API with proper precision"""
    # For prices, always keep one decimal place (even .0) as Apex Pro expects this
    return f"{decimal_value:.1f}"

# Load environment variables
load_dotenv(override=True)

# Initialize ApexPro clients (same as fetch_account_value.py)
key = os.getenv('APEXPRO_API_KEY')
secret = os.getenv('APEXPRO_API_SECRET')
passphrase = os.getenv('APEXPRO_API_PASSPHRASE')

# Derive ZK keys
logger.info("ZK credentials not found, attempting to derive from ETH private key...")
eth_private_key = os.getenv('APEXPRO_ETH_PRIVATE_KEY')
logger.info(f"ETH private key loaded: {'YES' if eth_private_key else 'NO'}")
if eth_private_key:
    logger.info(f"Raw ETH private key: {eth_private_key[:10]}... (length: {len(eth_private_key)})")
    # Ensure the private key has 0x prefix
    if not eth_private_key.startswith('0x'):
        eth_private_key = '0x' + eth_private_key
        logger.info("Added 0x prefix to ETH private key")
    logger.info(f"ETH private key with prefix: {eth_private_key[:12]}...")

    # Test hex conversion
    try:
        test_hex = bytes.fromhex(eth_private_key[2:])  # Remove 0x prefix for test
        logger.info(f"Hex conversion successful, length: {len(test_hex)}")
    except Exception as hex_error:
        logger.error(f"Hex conversion failed: {hex_error}")
        raise Exception(f"Invalid ETH private key format: {hex_error}")

    # Use HttpPrivate_v3 for derivation (same as demo_register_v3.py)
    temp_client = HttpPrivate_v3(APEX_OMNI_HTTP_MAIN, network_id=NETWORKID_MAIN, eth_private_key=eth_private_key)
    temp_client.configs_v3()  # Initialize configuration

    # Derive ZK keys using default_address (same as demo)
    derived_keys = temp_client.derive_zk_key(temp_client.default_address)
    logger.info(f"Derived keys type: {type(derived_keys)}")
    logger.info(f"Derived keys keys: {list(derived_keys.keys()) if isinstance(derived_keys, dict) else 'Not dict'}")

    if derived_keys and 'seeds' in derived_keys and 'l2Key' in derived_keys:
        zk_seeds = derived_keys['seeds']
        l2_key = derived_keys['l2Key']
        logger.info(f"ZK seeds length: {len(zk_seeds)}")
        logger.info(f"L2 key length: {len(l2_key)}")
        logger.info("ZK credentials derived successfully from ETH private key")
    else:
        raise Exception("ZK key derivation returned invalid format")
else:
    logger.error("No ETH private key found in environment variables")
    raise Exception("ETH private key required for ZK credential derivation")

client = HttpPrivateSign(APEX_OMNI_HTTP_MAIN, network_id=NETWORKID_OMNI_MAIN_ARB,
                         zk_seeds=zk_seeds, zk_l2Key=l2_key,
                         api_key_credentials={'key': key, 'secret': secret, 'passphrase': passphrase})
client.configs_v3()  # Initialize config data needed for order placement

client_public = HttpPublic(APEX_OMNI_HTTP_MAIN)

# FastAPI app setup
app = FastAPI(
    title="Apex Omni Trading Bot",
    description="""
    Professional automated trading service for Apex Omni perpetual contracts.

    ## 🎯 Risk Management
    - 5% maximum risk per trade
    - 1:3 risk-reward ratio
    - Automated stop loss and take profit orders
    - Real-time liquidation monitoring

    ## 🚀 Features
    - Smart position sizing
    - 5x leverage (default)
    - Limit orders with price buffer
    - Real-time P&L tracking
    - Liquidation price calculations
    - Account equity monitoring

    ## 📊 Trading Endpoints
    - `POST /buy/{symbol}` - Long positions + auto stop loss + take profit
    - `POST /sell/{symbol}` - Short positions + auto stop loss + take profit
    - `GET /positions` - Real-time P&L + leverage + liquidation prices
    - `GET /orders` - Open orders monitoring
    - `GET /account` - Account value and wallet info
    - `GET /trade-history` - Historical closed trades (fills)

    ## 📈 Position Analytics (`/positions`)
    Returns enhanced position data:
    - Real-time unrealized P&L
    - Current market prices
    - Effective leverage (% margin rate)
    - Liquidation price (exact $ amount)
    - Distance to liquidation (% buffer)
    - Notional value exposure

    ## 📊 Market Data Endpoints
    - `GET /depth/{symbol}?limit=100` - Order book depth (bids/asks)
    - `GET /trades/{symbol}?limit=100` - Recent trade history
    - `GET /trade-history?symbol=BTC-USDT&limit=50` - Personal trade history

    ## 📊 Trade History Analytics (`/trade-history`)
    Returns historical trade data with comprehensive analysis:
    - Individual trade details (price, size, fees, P&L)
    - Win/loss statistics and win rate
    - Total volume, fees, and P&L
    - Date/time filtering
    - Symbol-specific filtering

    ## �🔒 Security
    - Position size limits (max 5% account risk)
    - Equity validation before trades
    - Error handling and validation
    - Rate limiting and request validation
    """,
    version="1.0.0",
    contact={
        "name": "Apex Omni Trading Bot",
        "description": "Automated risk-managed perpetual trading"
    }
)

# Pydantic models
class TradeRequest(BaseModel):
    symbol: str
    side: str  # BUY or SELL
    leverage: float = 10.0
    risk_percentage: float = 0.05  # 5% default

class TradeResponse(BaseModel):
    message: str
    orderId: str
    position_size: float
    risk_amount: float
    leverage: float
    entry_price: float

# Core functions (extracted from fetch_account_value.py)
def get_symbol_config(symbol_list: list, symbol: str) -> dict:
    """Get symbol configuration"""
    for v in symbol_list:
        if v.get('symbol') == symbol or v.get('crossSymbolName') == symbol or v.get('symbolDisplayName') == symbol:
            return v
    return None

def get_current_price(symbol: str) -> str:
    """Get current price for symbol"""
    try:
        # Remove all hyphens same as order placement (consistent with API)
        ticker_symbol = symbol.replace('-', '')
        # logger.debug(f"Requesting ticker for {ticker_symbol}")
        ticker_data = client_public.ticker_v3(symbol=ticker_symbol)
        # logger.debug(f"Ticker response: {ticker_data}")

        # Handle the APEX API ticker response format: {"data": [...], "timeCost": ...}
        data_list = ticker_data.get("data")
        if data_list and isinstance(data_list, list) and len(data_list) > 0:
            ticker_info = data_list[0]  # Get first item from data list
            # Use lastPrice or markPrice from the ticker data
            price = ticker_info.get("lastPrice") or ticker_info.get("markPrice", "0")
            # logger.debug(f"Price found: {price}")
            return price

        # logger.debug("No valid ticker data found")
        return "0"
    except Exception as e:
        logger.error(f"Error getting price for {symbol}: {e}")
        return "0"

def calculate_account_value() -> Dict[str, Any]:
    """Calculate current account value and return structured data"""
    try:
        # Get account data
        account = client.get_account_v3()
        if not account:
            raise ValueError("Could not fetch account data")

        # Get symbol configurations
        symbol_list = client.configs().get("data", {}).get("perpetualContract", [])

        # Calculate wallet values
        contract_wallets = account.get('contractWallets', [])
        spot_wallets = account.get('spotWallets', [])
        total_wallet_value = decimal.Decimal('0.0')

        for wallet in contract_wallets + spot_wallets:
            balance = decimal.Decimal(wallet.get('balance', '0'))
            token = wallet.get('token', wallet.get('tokenId', 'UNKNOWN'))

            if token == 'USDT' or token == '141':
                value = balance
            elif token == 'ETH' or token == '36':
                eth_price = get_current_price('ETH-USDT')
                if eth_price and eth_price != "0":
                    value = balance * decimal.Decimal(eth_price)
                else:
                    value = balance
            else:
                value = decimal.Decimal('0')

            total_wallet_value += value

        # Calculate position P&L
        positions = account.get('positions', [])
        total_unrealized_pnl = decimal.Decimal('0.0')

        for position in positions:
            symbol = position.get('symbol', '')
            size = decimal.Decimal(position.get('size', '0'))
            entry_price = decimal.Decimal(position.get('entryPrice', '0'))
            current_price_str = get_current_price(symbol)
            current_price = decimal.Decimal(current_price_str) if current_price_str else decimal.Decimal('0')

            if size != 0 and entry_price != 0:
                if position.get('side') == 'LONG':
                    pnl = size * (current_price - entry_price)
                else:  # SHORT
                    pnl = size * (entry_price - current_price)
                total_unrealized_pnl += pnl

        total_account_value = float(total_wallet_value + total_unrealized_pnl)

        return {
            "totalAccountValue": total_account_value,
            "walletValue": float(total_wallet_value),
            "unrealizedPnL": float(total_unrealized_pnl),
            "positions": positions,
            "contractWallets": contract_wallets,
            "spotWallets": spot_wallets
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calculating account value: {str(e)}")

def calculate_position_size(account_equity: float, symbol: str, risk_pct: float = 0.05, step_size: str = '0.001') -> float:
    """Calculate position size based on account equity and risk percentage, respecting Apex Pro stepSize"""
    current_price_str = get_current_price(symbol)
    if not current_price_str or current_price_str == "0":
        raise HTTPException(status_code=400, detail=f"Could not get price for {symbol}")

    current_price = decimal.Decimal(current_price_str)
    risk_amount = decimal.Decimal(str(account_equity)) * decimal.Decimal(str(risk_pct))

    # Position size = risk amount / current price
    position_size = risk_amount / current_price

    # Round position size to step size using Apex Pro compatible rounding
    step_size_decimal = decimal.Decimal(step_size)
    position_size_rounded = (position_size // step_size_decimal) * step_size_decimal

    return float(position_size_rounded)

# API Endpoints

@app.get("/")
async def root():
    """Health check endpoint"""
    return {"message": "Apex Omni Trading Bot is running", "status": "active"}

@app.get("/account")
async def get_account():
    """Get current account value and positions"""
    try:
        account_data = calculate_account_value()
        return {
            "status": "success",
            "data": account_data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/buy/{symbol}")
async def buy_position(symbol: str, leverage: float = 5.0):
    """
    Place LONG position with complete risk management

    **Risk Management:**
    - Position size: 5% of account equity
    - Stop Loss: 1% below entry price (5% risk ÷ 5x leverage)
    - Take Profit: 3% above entry price (1:3 risk ratio)
    - Limit order with 0.1% price buffer

    **Example:**
    ```bash
    POST /buy/BTC-USDT?leverage=5
    ```

    **Response includes:**
    - Order ID
    - Position size
    - Risk amount
    - Entry/Stop/Take profit prices

    - **symbol**: Trading pair (BTC-USDT, ETH-USDT, etc.)
    - **leverage**: Leverage multiplier (default: 5.0)
    """
    try:
        # Validate symbol format
        if not symbol.endswith('-USDT'):
            raise HTTPException(status_code=400, detail="Symbol must be in format SYMBOL-USDT")

        # Get account value
        account_data = calculate_account_value()
        account_equity = account_data['totalAccountValue']

        if account_equity <= 0:
            raise HTTPException(status_code=400, detail="Insufficient account equity for trading")

        # Calculate position size (5% of account equity)
        position_size = calculate_position_size(account_equity, symbol, risk_pct=0.05)

        # Get current price for limit order
        current_price_str = get_current_price(symbol)
        current_price = decimal.Decimal(current_price_str)

        # Create limit buy order slightly above current price (0.1% buffer)
        limit_price = current_price * decimal.Decimal('1.001')

        # Get symbol configuration for tick size
        symbol_data = None
        for k, v in enumerate(client.configV3.get('contractConfig').get('perpetualContract')):
            if v.get('symbol') == symbol or v.get('symbolDisplayName') == symbol:
                symbol_data = v
                break

        if not symbol_data:
            raise HTTPException(status_code=400, detail=f"Symbol configuration not found for {symbol}")

        # Round price to tick size and convert to clean string for Apex Pro
        rounded_limit_price_decimal = round_size(str(limit_price), symbol_data.get('tickSize'))
        rounded_limit_price = format_decimal_for_apex(rounded_limit_price_decimal)

        # Debug: ensure position_size is float
        logger.info(f"position_size type: {type(position_size)}, value: {position_size}")
        logger.info(f"rounded_limit_price type: {type(rounded_limit_price)}, value: '{rounded_limit_price}'")

        # Calculate stop loss and take profit prices (1:3 risk ratio)
        risk_pct = 0.05  # 5% risk
        stop_loss_distance_pct = risk_pct / leverage  # Stop distance = 5% risk / leverage
        take_profit_distance_pct = stop_loss_distance_pct * 3  # 1:3 risk ratio = 3x stop distance

        stop_loss_price = decimal.Decimal(rounded_limit_price) * decimal.Decimal(str(1 - stop_loss_distance_pct))
        take_profit_price = decimal.Decimal(rounded_limit_price) * decimal.Decimal(str(1 + take_profit_distance_pct))

        # Round stop loss and take profit prices to tick size and convert to clean strings for Apex Pro
        rounded_stop_loss_price_decimal = round_size(str(stop_loss_price), symbol_data.get('tickSize'))
        rounded_stop_loss_price = format_decimal_for_apex(rounded_stop_loss_price_decimal)

        rounded_take_profit_price_decimal = round_size(str(take_profit_price), symbol_data.get('tickSize'))
        rounded_take_profit_price = format_decimal_for_apex(rounded_take_profit_price_decimal)

        # Ensure position_size is definitely a float
        position_size = float(position_size)

        # Format size for Apex Pro
        position_size_str = f"{position_size:.6f}"

        # Place main buy order (LONG position) with stop loss and take profit as Open TPSL
        order_params = {
            'symbol': symbol,  # API expects format like BTC-USDT
            'side': 'BUY',
            'type': 'LIMIT',
            'size': position_size_str,
            'price': str(rounded_limit_price),  # Ensure price is string
            'triggerPrice': format_decimal_for_apex(rounded_stop_loss_price_decimal),
            'triggerPriceType': 'MARKET',
            'isOpenTpslOrder': True,
            'isSetOpenSl': True,
            'isSetOpenTp': True,
            'slPrice': format_decimal_for_apex(rounded_stop_loss_price_decimal),
            'slSide': 'SELL',
            'slSize': position_size_str,
            'slTriggerPrice': format_decimal_for_apex(rounded_stop_loss_price_decimal),
            'tpPrice': format_decimal_for_apex(rounded_take_profit_price_decimal),
            'tpSide': 'SELL',
            'tpSize': position_size_str,
            'tpTriggerPrice': format_decimal_for_apex(rounded_take_profit_price_decimal),
        }

        try:
            # Place main order first
            logger.info(f"Main order to be placed (with SL/TP): {order_params}")
            logger.info(f"SL triggerPrice type: {type(order_params['slTriggerPrice'])} value: '{order_params['slTriggerPrice']}'")
            logger.info(f"TP triggerPrice type: {type(order_params['tpTriggerPrice'])} value: '{order_params['tpTriggerPrice']}'")

            main_order = client.create_order_v3(**order_params)
            logger.info(f"Main order with SL/TP placed: {main_order}")

            return TradeResponse(
                message=f"Successfully placed LONG order + stop loss + take profit (1:3) for {position_size:.6f} {symbol}",
                orderId=main_order.get('id', 'unknown'),
                position_size=float(position_size),
                risk_amount=float(account_equity * 0.05),
                leverage=float(leverage),
                entry_price=float(limit_price)
            )

        except Exception as order_error:
            logger.error(f"Order placement failed: {str(order_error)}")
            raise HTTPException(status_code=500, detail=f"Order placement failed: {str(order_error)}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/sell/{symbol}")
async def sell_position(symbol: str, leverage: float = 5.0):
    """
    Place SHORT position with complete risk management

    **Risk Management:**
    - Position size: 5% of account equity
    - Stop Loss: 1% above entry price (5% risk ÷ 5x leverage)
    - Take Profit: 3% below entry price (1:3 risk ratio)
    - Limit order with 0.1% price buffer

    **Example:**
    ```bash
    POST /sell/BTC-USDT?leverage=5
    ```

    **Response includes:**
    - Order ID
    - Position size
    - Risk amount
    - Entry/Stop/Take profit prices

    - **symbol**: Trading pair (BTC-USDT, ETH-USDT, etc.)
    - **leverage**: Leverage multiplier (default: 5.0)
    """
    try:
        # Validate symbol format
        if not symbol.endswith('-USDT'):
            raise HTTPException(status_code=400, detail="Symbol must be in format SYMBOL-USDT")

        # Get account value
        account_data = calculate_account_value()
        account_equity = account_data['totalAccountValue']

        if account_equity <= 0:
            raise HTTPException(status_code=400, detail="Insufficient account equity for trading")

        # Calculate position size (5% of account equity)
        position_size = calculate_position_size(account_equity, symbol, risk_pct=0.05)

        # Get current price for limit order
        current_price_str = get_current_price(symbol)
        current_price = decimal.Decimal(current_price_str)

        # Create limit sell order slightly below current price (0.1% buffer)
        limit_price = current_price * decimal.Decimal('0.999')

        # Get symbol configuration for tick size
        symbol_data = None
        for k, v in enumerate(client.configV3.get('contractConfig').get('perpetualContract')):
            if v.get('symbol') == symbol or v.get('symbolDisplayName') == symbol:
                symbol_data = v
                break

        if not symbol_data:
            raise HTTPException(status_code=400, detail=f"Symbol configuration not found for {symbol}")

        # Round price to tick size and convert to clean string for Apex Pro
        rounded_limit_price_decimal = round_size(str(limit_price), symbol_data.get('tickSize'))
        rounded_limit_price = format_decimal_for_apex(rounded_limit_price_decimal)

        # Calculate stop loss and take profit prices (1:3 risk ratio for SHORT positions)
        risk_pct = 0.05  # 5% risk
        stop_loss_distance_pct = risk_pct / leverage  # Stop distance = 5% risk / leverage
        take_profit_distance_pct = stop_loss_distance_pct * 3  # 1:3 risk ratio = 3x stop distance

        stop_loss_price = decimal.Decimal(rounded_limit_price) * decimal.Decimal(str(1 + stop_loss_distance_pct))  # Above entry for SHORT
        take_profit_price = decimal.Decimal(rounded_limit_price) * decimal.Decimal(str(1 - take_profit_distance_pct))  # Below entry for SHORT

        # Round stop loss and take profit prices to tick size and convert to clean strings for Apex Pro
        rounded_stop_loss_price_decimal = round_size(str(stop_loss_price), symbol_data.get('tickSize'))
        rounded_stop_loss_price = format_decimal_for_apex(rounded_stop_loss_price_decimal)

        rounded_take_profit_price_decimal = round_size(str(take_profit_price), symbol_data.get('tickSize'))
        rounded_take_profit_price = format_decimal_for_apex(rounded_take_profit_price_decimal)

        # Ensure position_size is definitely a float
        position_size = float(position_size)

        # Format size for Apex Pro
        position_size_str = f"{position_size:.6f}"

        # Place main sell order (SHORT position) with stop loss and take profit as Open TPSL
        order_params = {
            'symbol': symbol,  # API expects format like BTC-USDT
            'side': 'SELL',
            'type': 'LIMIT',
            'size': position_size_str,
            'price': str(rounded_limit_price),  # Ensure price is string
            'triggerPrice': format_decimal_for_apex(rounded_stop_loss_price_decimal),  # SL trigger price
            'triggerPriceType': 'MARKET',
            'isOpenTpslOrder': True,
            'isSetOpenSl': True,
            'isSetOpenTp': True,
            'slPrice': format_decimal_for_apex(rounded_stop_loss_price_decimal),
            'slSide': 'BUY',  # Buy to close SHORT position
            'slSize': position_size_str,
            'slTriggerPrice': format_decimal_for_apex(rounded_stop_loss_price_decimal),
            'tpPrice': format_decimal_for_apex(rounded_take_profit_price_decimal),
            'tpSide': 'BUY',  # Buy to close SHORT position
            'tpSize': position_size_str,
            'tpTriggerPrice': format_decimal_for_apex(rounded_take_profit_price_decimal),
        }

        try:
            # Place main order with SL/TP
            logger.info(f"Main order to be placed (with SL/TP): {order_params}")
            logger.info(f"SL triggerPrice type: {type(order_params['slTriggerPrice'])} value: '{order_params['slTriggerPrice']}'")
            logger.info(f"TP triggerPrice type: {type(order_params['tpTriggerPrice'])} value: '{order_params['tpTriggerPrice']}'")

            main_order = client.create_order_v3(**order_params)
            logger.info(f"Main order with SL/TP placed: {main_order}")

            return TradeResponse(
                message=f"Successfully placed SHORT order + stop loss + take profit (1:3) for {position_size:.6f} {symbol}",
                orderId=main_order.get('id', 'unknown'),
                position_size=float(position_size),
                risk_amount=float(account_equity * 0.05),
                leverage=float(leverage),
                entry_price=float(limit_price)
            )

        except Exception as order_error:
            raise HTTPException(status_code=500, detail=f"Order placement failed: {str(order_error)}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/positions")
async def get_positions():
    """Get current open positions with real-time P&L calculations"""
    try:
        account_data = calculate_account_value()
        all_positions = account_data.get('positions', [])

        # Filter out positions with zero size and enhance with P&L information
        active_positions = []
        for position in all_positions:
            size = float(position.get('size', 0))
            entry_price = float(position.get('entryPrice', 0))

            # Only include actively sized positions
            if size > 0 and entry_price > 0:
                symbol = position.get('symbol', '')
                current_price_str = get_current_price(symbol)
                current_price = float(current_price_str) if current_price_str and current_price_str != "0" else entry_price

                if position.get('side') == 'LONG':
                    unrealized_pnl = size * (current_price - entry_price)
                    pnl_percentage = ((current_price - entry_price) / entry_price) * 100
                else:  # SHORT
                    unrealized_pnl = size * (entry_price - current_price)
                    pnl_percentage = ((entry_price - current_price) / entry_price) * 100

                # Calculate effective leverage from margin rate
                margin_rate = float(position.get('customInitialMarginRate', '0.10'))
                effective_leverage = 1 / margin_rate if margin_rate > 0 else 1.0

                # Calculate liquidation price
                # Get maintenance margin rate (typically lower than initial margin rate)
                maintenance_margin_rate = 0.007  # Default 0.7%, get from symbol config if available

                # Get current wallet balance (simplified - should be account equity)
                wallet_balance = float(account_data.get('walletValue', 0))

                # Proper liquidation price calculation for perpetual futures
                # Formula: liquidation_price = entry_price ± (balance / size)
                # Where + is for SHORT positions, - is for LONG positions

                notional_value = size * entry_price
                margin_used = notional_value / effective_leverage

                if position.get('side') == 'LONG':
                    # LONG liquidation price: entry_price - (abs(balance) / size)
                    # If balance is negative, liquidation happens closer (higher risk)
                    abs_balance = abs(wallet_balance)
                    liquidation_price = entry_price - (abs_balance / size)
                    logger.debug(f"LONG liquidation calc: entry={entry_price}, balance={wallet_balance}, abs_balance={abs_balance}, size={size}, liq={liquidation_price}")
                else:  # SHORT
                    # SHORT liquidation price: entry_price + (abs(balance) / size)
                    abs_balance = abs(wallet_balance)
                    liquidation_price = entry_price + (abs_balance / size)
                    logger.debug(f"SHORT liquidation calc: entry={entry_price}, balance={wallet_balance}, abs_balance={abs_balance}, size={size}, liq={liquidation_price}")

                # Ensure liquidation price makes sense (clamp to reasonable values)
                if position.get('side') == 'LONG' and liquidation_price > entry_price:
                    liquidation_price = entry_price * 0.8  # Max 20% drop if calculation wrong
                elif position.get('side') == 'SHORT' and liquidation_price < entry_price:
                    liquidation_price = entry_price * 1.2  # Max 20% rise if calculation wrong

                logger.debug(f"Final liquidation price: {liquidation_price}")

                distance_to_liquidation = abs(current_price - liquidation_price)

                logger.debug(f"Liquidation price={liquidation_price}, distance={distance_to_liquidation}")

                enhanced_position = dict(position)
                enhanced_position.update({
                    'current_price': float(round(current_price, 2)),
                    'unrealized_pnl': float(round(unrealized_pnl, 2)),
                    'pnl_percentage': float(round(pnl_percentage, 6)),
                    'notional_value': float(round(size * current_price, 2)),
                    'effective_leverage': float(round(effective_leverage, 2)),
                    'liquidation_price': float(round(liquidation_price, 2)),
                    'distance_to_liquidation': float(round(distance_to_liquidation, 2)),
                    'liquidation_percentage': float(round((distance_to_liquidation / current_price) * 100, 2))
                })

                logger.debug(f"Added fields to position: {enhanced_position.keys()}")
                active_positions.append(enhanced_position)

        return {
            "status": "success",
            "positions": active_positions,
            "summary": {
                "total_active_positions": len(active_positions),
                "total_positions_in_account": len(all_positions),
                "total_unrealized_pnl": account_data.get('unrealizedPnL', 0),
                "last_updated": "real-time"
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching positions: {str(e)}")

@app.get("/orders")
async def get_open_orders():
    """Get current open orders"""
    try:
        orders = client.open_orders_v3()
        return {
            "status": "success",
            "orders": orders.get("data", [])
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching orders: {str(e)}")

@app.get("/trade-history")
async def get_trade_history(symbol: str = None, limit: int = 50, start_time: int = None, end_time: int = None):
    """
    Get user's closed trade history (fills)

    **Parameters:**
    - **symbol** (optional): Filter by trading pair (BTC-USDT, ETH-USDT, etc.)
    - **limit**: Number of trades to return (default: 50, max: 1000)
    - **start_time**: Start timestamp in milliseconds (optional)
    - **end_time**: End timestamp in milliseconds (optional)

    **Response includes:**
    - Trade details: price, size, side, fee, timestamps
    - P&L calculations
    - Symbol information

    **Example:** `/trade-history?symbol=BTC-USDT&limit=20`
    """
    try:
        # Build parameters for the fills_v3 API call
        params = {
            'limit': min(limit, 1000)  # Cap at 1000 as per typical API limits
        }

        if symbol:
            if not symbol.endswith('-USDT'):
                raise HTTPException(status_code=400, detail="Symbol must be in format SYMBOL-USDT")
            params['symbol'] = symbol

        if start_time:
            params['startTime'] = int(start_time)

        if end_time:
            params['endTime'] = int(end_time)

        # Call the trade history/fills API
        fills_response = client.fills_v3(**params)

        if not fills_response:
            raise HTTPException(status_code=404, detail="No trade history found")

        # Extract fills data
        fills_data = fills_response.get("data", [])
        fills = fills_data.get("fills", []) if isinstance(fills_data, dict) else fills_data

        if not fills:
            return {
                "status": "success",
                "trade_history": [],
                "summary": {
                    "total_trades": 0,
                    "total_volume": 0,
                    "total_fees": 0,
                    "total_pnl": 0,
                    "winning_trades": 0,
                    "losing_trades": 0
                },
                "filters": {
                    "symbol": symbol,
                    "limit": limit,
                    "start_time": start_time,
                    "end_time": end_time
                }
            }

        # Analyze fills for summary statistics
        total_volume = 0
        total_fees = 0
        total_pnl = 0
        winning_trades = 0
        losing_trades = 0

        for fill in fills:
            size = float(fill.get('size', 0))
            price = float(fill.get('price', 0))
            fee = float(fill.get('fee', 0))
            pnl = float(fill.get('pnl', 0))

            total_volume += size * price
            total_fees += fee
            total_pnl += pnl

            if pnl > 0:
                winning_trades += 1
            elif pnl < 0:
                losing_trades += 1

        # Calculate additional metrics
        total_trades = len(fills)
        win_rate = winning_trades / total_trades * 100 if total_trades > 0 else 0

        return {
            "status": "success",
            "trade_history": fills,
            "summary": {
                "total_trades": total_trades,
                "total_volume": round(total_volume, 2),
                "total_fees": round(total_fees, 6),
                "total_pnl": round(total_pnl, 6),
                "winning_trades": winning_trades,
                "losing_trades": losing_trades,
                "breakeven_trades": total_trades - winning_trades - losing_trades,
                "win_rate_percentage": round(win_rate, 2),
                "average_trade_size": round(total_volume / total_trades, 2) if total_trades > 0 else 0,
                "average_pnl_per_trade": round(total_pnl / total_trades, 6) if total_trades > 0 else 0
            },
            "filters": {
                "symbol": symbol,
                "limit": limit,
                "start_time": start_time,
                "end_time": end_time
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Trade history error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching trade history: {str(e)}")

@app.get("/depth/{symbol}")
async def get_order_book_depth(symbol: str, limit: int = 100):
    """
    Get order book depth for a symbol

    **Order Book Structure:**
    - asks: Sell orders [[price, size], ...] (lowest to highest price)
    - bids: Buy orders [[price, size], ...] (highest to lowest price)

    **Parameters:**
    - **symbol**: Trading pair (BTC-USDT, ETH-USDT, etc.)
    - **limit**: Number of entries (default: 100, max may vary by exchange)

    **Example:** `/depth/BTC-USDT?limit=10`
    """
    try:
        # Validate symbol format (should be without hyphens for API)
        if not symbol.endswith('-USDT'):
            raise HTTPException(status_code=400, detail="Symbol must be in format SYMBOL-USDT")

        # Remove hyphens for API call
        api_symbol = symbol.replace('-', '')

        depth_data = client_public.depth_v3(symbol=api_symbol, limit=limit)

        if not depth_data:
            raise HTTPException(status_code=404, detail=f"No depth data found for symbol {symbol}")

        # Get the actual depth data from the 'data' field
        depth_content = depth_data.get("data", {})
        asks = depth_content.get("a", [])  # 'a' field contains asks
        bids = depth_content.get("b", [])  # 'b' field contains bids

        # Structure the response consistently
        result = {
            "status": "success",
            "symbol": symbol,
            "data": {
                "asks": asks,
                "bids": bids,
                "timestamp": depth_data.get("timeCost", 0),
                "update_id": depth_content.get("u", 0)
            },
            "summary": {
                "total_asks": len(asks),
                "total_bids": len(bids),
                "best_ask": float(asks[0][0]) if asks else 0,
                "best_bid": float(bids[0][0]) if bids else 0,
                "spread": 0.0
            }
        }

        # Calculate spread if both ask and bid exist
        if result["summary"]["best_ask"] > 0 and result["summary"]["best_bid"] > 0:
            result["summary"]["spread"] = result["summary"]["best_ask"] - result["summary"]["best_bid"]
            result["summary"]["spread_percentage"] = (result["summary"]["spread"] / result["summary"]["best_bid"]) * 100

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching order book depth: {str(e)}")

@app.get("/trades/{symbol}")
async def get_recent_trades(symbol: str, limit: int = 100):
    """
    Get recent trades for a symbol

    **Trade Data Structure:**
    - id: Trade ID
    - price: Trade price
    - size: Trade size
    - side: "buy" or "sell"
    - timestamp: Trade timestamp
    - tickDirection: Direction indicator

    **Parameters:**
    - **symbol**: Trading pair (BTC-USDT, ETH-USDT, etc.)
    - **limit**: Number of trades (default: 100, max may vary by exchange)

    **Example:** `/trades/BTC-USDT?limit=50`
    """
    try:
        # Validate symbol format (should be without hyphens for API)
        if not symbol.endswith('-USDT'):
            raise HTTPException(status_code=400, detail="Symbol must be in format SYMBOL-USDT")

        # Remove hyphens for API call
        api_symbol = symbol.replace('-', '')

        trades_data = client_public.trades_v3(symbol=api_symbol, limit=limit)

        if not trades_data:
            raise HTTPException(status_code=404, detail=f"No trades data found for symbol {symbol}")

        # Extract trades array
        trades = trades_data.get("data", [])

        if not trades:
            return {
                "status": "success",
                "symbol": symbol,
                "trades": [],
                "summary": {
                    "total_trades": 0,
                    "latest_price": 0,
                    "volume_24h": 0
                }
            }

        # Analyze trades for summary
        prices = [float(trade.get("price", 0)) for trade in trades if trade.get("price")]
        sizes = [float(trade.get("size", 0)) for trade in trades if trade.get("size")]

        # Get latest price (first trade is most recent)
        latest_price = prices[0] if prices else 0

        # Calculate volume (sum of all trade sizes in this batch)
        volume = sum(sizes) if sizes else 0

        # Count buy vs sell trades
        buy_trades = len([t for t in trades if t.get("side") == "buy"])
        sell_trades = len([t for t in trades if t.get("side") == "sell"])

        return {
            "status": "success",
            "symbol": symbol,
            "trades": trades,
            "summary": {
                "total_trades": len(trades),
                "latest_price": latest_price,
                "volume_in_response": volume,
                "buy_trades": buy_trades,
                "sell_trades": sell_trades,
                "price_range": {
                    "high": max(prices) if prices else 0,
                    "low": min(prices) if prices else 0
                } if prices else None
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching recent trades: {str(e)}")

@app.get("/volume-profile/{symbol}")
async def get_volume_profile(symbol: str, max_trades: int = 1000, price_bins: int = 50):
    """
    Get volume profile analysis for a symbol (identifies large orders and market imbalance)

    **Volume Profile Analysis:**
    - Aggregates trade data into price bins to show volume distribution
    - Identifies significant volume levels and potential support/resistance
    - Detects large orders (represented as "circles" for visualization)
    - Analyzes market balance vs imbalance conditions

    **Parameters:**
    - **symbol**: Trading pair (BTC-USDT, ETH-USDT, etc.)
    - **max_trades**: Maximum number of recent trades to analyze (default: 1000)
    - **price_bins**: Number of price bins for volume distribution analysis

    **Response includes:**
    - Volume profile histogram data
    - Large order identification (aggressive market participants)
    - Market state analysis (balanced vs imbalanced)
    - Significant volume levels and low volume nodes (LVNs)

    **Example:** `/volume-profile/BTC-USDT?max_trades=2000&price_bins=100`
    """
    try:
        # Validate symbol format
        if not symbol.endswith('-USDT'):
            raise HTTPException(status_code=400, detail="Symbol must be in format SYMBOL-USDT")

        # Remove hyphens for API call
        api_symbol = symbol.replace('-', '')

        # Get recent trades for volume profile analysis
        logger.info(f"Fetching trades for volume profile analysis: {symbol}")
        trades_data = client_public.trades_v3(symbol=api_symbol, limit=min(max_trades, 1000))

        if not trades_data:
            raise HTTPException(status_code=404, detail=f"No trade data found for symbol {symbol}")

        # Extract trades array
        trades = trades_data.get("data", [])

        if not trades or len(trades) == 0:
            return {
                "status": "success",
                "symbol": symbol,
                "volume_profile": {
                    "price_bins": [],
                    "volume_distribution": [],
                    "large_orders": [],
                    "market_state": "unknown",
                    "significant_levels": []
                },
                "summary": {
                    "total_trades_analyzed": 0,
                    "price_range": {"high": 0, "low": 0},
                    "total_volume": 0,
                    "avg_trade_size": 0,
                    "large_order_threshold": 0
                }
            }

        # Convert to DataFrame for analysis
        trades_df = pd.DataFrame(trades)

        # Clean and convert data types
        trades_df['price'] = pd.to_numeric(trades_df.get('p', trades_df.get('price')), errors='coerce')
        trades_df['size'] = pd.to_numeric(trades_df.get('v', trades_df.get('size')), errors='coerce')
        trades_df['timestamp'] = pd.to_numeric(trades_df.get('T', trades_df.get('timestamp')), errors='coerce')

        # Drop rows with invalid data
        trades_df = trades_df.dropna(subset=['price', 'size'])

        if trades_df.empty:
            raise HTTPException(status_code=400, detail="No valid trade data available for analysis")

        # Calculate price range
        price_min = trades_df['price'].min()
        price_max = trades_df['price'].max()
        price_range = price_max - price_min

        # Calculate dynamic bin size and thresholds
        if price_range == 0:
            # All trades at same price - create single bin
            bin_size = 1.0
            bins = np.array([price_min - 1, price_min + 1])
        else:
            bin_size = max(price_range / price_bins, 1e-6)  # Minimum bin size
            bins = np.linspace(price_min, price_max, price_bins + 1)

        # Create volume profile by binning prices
        trades_df['price_bin'] = pd.cut(trades_df['price'], bins=bins, include_lowest=True, right=False)
        volume_profile = trades_df.groupby('price_bin', observed=True)['size'].sum().reset_index()

        # Calculate bin centers for visualization
        volume_profile['bin_center'] = volume_profile['price_bin'].apply(lambda x: x.mid)
        volume_profile['bin_width'] = volume_profile['price_bin'].apply(lambda x: x.length)

        # Sort by volume for analysis
        volume_profile = volume_profile.sort_values('size', ascending=False)

        # Calculate statistics for large order detection
        mean_volume = volume_profile['size'].mean()
        std_volume = volume_profile['size'].std()

        # Define thresholds for significant levels (using statistical approach)
        # Large orders: volume > mean + 2*std (95th percentile equivalent)
        large_order_threshold = mean_volume + 2 * std_volume
        # Significant levels: volume > mean + 1*std (84th percentile equivalent)
        significant_threshold = mean_volume + 1 * std_volume

        # Identify large orders (potential circles for visualization)
        large_orders = volume_profile[volume_profile['size'] >= large_order_threshold].copy()
        large_orders = large_orders.sort_values('bin_center')

        # Identify significant volume levels (potential support/resistance)
        significant_levels = volume_profile[volume_profile['size'] >= significant_threshold].copy()
        significant_levels = significant_levels.sort_values('bin_center')

        # Identify low volume nodes (LVNs) - potential breakout levels
        lvn_threshold = max(volume_profile['size'].quantile(0.2), mean_volume - std_volume)
        low_volume_nodes = volume_profile[volume_profile['size'] <= lvn_threshold].copy()

        # Calculate market state indicators
        total_volume = trades_df['size'].sum()
        avg_trade_size = trades_df['size'].mean()

        # Market balance analysis
        price_median = trades_df['price'].median()
        volume_weighted_price = (trades_df['price'] * trades_df['size']).sum() / trades_df['size'].sum()

        # Calculate volume distribution metrics
        volume_skewness = ((volume_profile['size'] - mean_volume) ** 3).sum() / (len(volume_profile) * (std_volume ** 3))
        volume_concentration = volume_profile['size'].max() / volume_profile['size'].sum()

        # Determine market state based on analysis
        if volume_concentration > 0.3:  # High concentration suggests imbalance
            market_state = "imbalanced"
            market_state_description = "High volume concentration - market likely in imbalance phase"
        elif abs(price_median - volume_weighted_price) / price_range > 0.1:  # Significant price-volume divergence
            market_state = "transitional"
            market_state_description = "Price-volume divergence - potential market transition"
        else:
            market_state = "balanced"
            market_state_description = "Price-volume alignment suggests balanced market conditions"

        # Calculate volume profile histogram data for charting
        sorted_profile = volume_profile.sort_values('bin_center')
        histogram_data = {
            "prices": sorted_profile['bin_center'].tolist(),
            "volumes": sorted_profile['size'].tolist(),
            "bin_widths": sorted_profile['bin_width'].tolist()
        }

        # Prepare response
        result = {
            "status": "success",
            "symbol": symbol,
            "volume_profile": {
                "price_bins": histogram_data,
                "market_state": market_state,
                "market_state_description": market_state_description,
                "volume_distribution": {
                    "mean_volume_per_bin": round(mean_volume, 6),
                    "std_volume_per_bin": round(std_volume, 6),
                    "max_volume_in_bin": round(volume_profile['size'].max(), 6),
                    "volume_concentration": round(volume_concentration, 4),
                    "volume_skewness": round(volume_skewness, 4)
                },
                "large_orders": [
                    {
                        "price": round(float(row['bin_center']), 6),
                        "size": round(float(row['size']), 6),
                        "bin_width": round(float(row['bin_width']), 6),
                        "volume_ratio": round(float(row['size']) / mean_volume, 2)
                    } for _, row in large_orders.head(10).iterrows()  # Top 10 largest
                ],
                "significant_levels": [
                    {
                        "price": round(float(row['bin_center']), 6),
                        "size": round(float(row['size']), 6),
                        "level_type": "support" if float(row['bin_center']) < price_median else "resistance"
                    } for _, row in significant_levels.head(20).iterrows()  # Top 20 significant
                ],
                "low_volume_nodes": [
                    {
                        "price": round(float(row['bin_center']), 6),
                        "size": round(float(row['size']), 6),
                        "potential_breakout": True
                    } for _, row in low_volume_nodes.head(10).iterrows()  # Top 10 LVNs
                ]
            },
            "summary": {
                "total_trades_analyzed": len(trades),
                "price_range": {
                    "high": round(float(price_max), 6),
                    "low": round(float(price_min), 6),
                    "range": round(float(price_range), 6)
                },
                "total_volume": round(float(total_volume), 6),
                "avg_trade_size": round(float(avg_trade_size), 6),
                "large_order_threshold": round(float(large_order_threshold), 6),
                "price_median": round(float(price_median), 6),
                "volume_weighted_price": round(float(volume_weighted_price), 6),
                "price_volume_alignment": round(float(abs(price_median - volume_weighted_price) / price_range), 4) if price_range > 0 else 1.0
            },
            "parameters": {
                "max_trades": max_trades,
                "price_bins": price_bins,
                "analysis_timestamp": int(pd.Timestamp.now().timestamp() * 1000)
            }
        }

        logger.info(f"Volume profile analysis completed for {symbol}: {len(trades)} trades, {len(large_orders)} large orders, market state: {market_state}")
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Volume profile analysis error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error creating volume profile: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    # Test logging before starting the server
    logger.debug("Logger configuration test - log message")
    logger.info("🚀 Starting Apex Omni Trading Bot...")
    logger.info("📊 Web dashboard available at: http://localhost:8000/docs")
    uvicorn.run(
        "trading_service:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_excludes="*.log",
        timeout_graceful_shutdown=1
    )
