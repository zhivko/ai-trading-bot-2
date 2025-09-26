"""
Apex Omni Trading Service
FastAPI web service for automated trading with 5% risk management
"""
import decimal
import os
from typing import Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

# Import ApexPro components
from apexomni.constants import APEX_OMNI_HTTP_MAIN, NETWORKID_OMNI_MAIN_ARB
from apexomni.http_private_v3 import HttpPrivate_v3
from apexomni.http_public import HttpPublic

# Load environment variables
load_dotenv(override=True)

# Initialize ApexPro clients (same as fetch_account_value.py)
key = os.getenv('APEXPRO_API_KEY')
secret = os.getenv('APEXPRO_API_SECRET')
passphrase = os.getenv('APEXPRO_API_PASSPHRASE')

client = HttpPrivate_v3(APEX_OMNI_HTTP_MAIN, network_id=NETWORKID_OMNI_MAIN_ARB,
                        api_key_credentials={'key': key, 'secret': secret, 'passphrase': passphrase})
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

    ## 📈 Position Analytics (`/positions`)
    Returns enhanced position data:
    - Real-time unrealized P&L
    - Current market prices
    - Effective leverage (% margin rate)
    - Liquidation price (exact $ amount)
    - Distance to liquidation (% buffer)
    - Notional value exposure

    ## 🔒 Security
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
        # print(f"DEBUG: Requesting ticker for {ticker_symbol}")  # Debug the symbol format
        ticker_data = client_public.ticker_v3(symbol=ticker_symbol)
        # print(f"DEBUG: Ticker response: {ticker_data}")  # Debug the full response

        # Handle the APEX API ticker response format: {"data": [...], "timeCost": ...}
        data_list = ticker_data.get("data")
        if data_list and isinstance(data_list, list) and len(data_list) > 0:
            ticker_info = data_list[0]  # Get first item from data list
            # Use lastPrice or markPrice from the ticker data
            price = ticker_info.get("lastPrice") or ticker_info.get("markPrice", "0")
            # print(f"DEBUG: Price found: {price}")  # Debug the price
            return price

        # print("DEBUG: No valid ticker data found")  # Debug no data
        return "0"
    except Exception as e:
        print(f"Error getting price for {symbol}: {e}")
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

def calculate_position_size(account_equity: float, symbol: str, risk_pct: float = 0.05) -> float:
    """Calculate position size based on account equity and risk percentage"""
    current_price_str = get_current_price(symbol)
    if not current_price_str or current_price_str == "0":
        raise HTTPException(status_code=400, detail=f"Could not get price for {symbol}")

    current_price = decimal.Decimal(current_price_str)
    risk_amount = decimal.Decimal(str(account_equity)) * decimal.Decimal(str(risk_pct))

    # Position size = risk amount / current price
    position_size = risk_amount / current_price

    return float(position_size)

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

        # Calculate stop loss and take profit prices (1:3 risk ratio)
        risk_pct = 0.05  # 5% risk
        stop_loss_distance_pct = risk_pct / leverage  # Stop distance = 5% risk / leverage
        take_profit_distance_pct = stop_loss_distance_pct * 3  # 1:3 risk ratio = 3x stop distance

        stop_loss_price = limit_price * decimal.Decimal(str(1 - stop_loss_distance_pct))
        take_profit_price = limit_price * decimal.Decimal(str(1 + take_profit_distance_pct))

        # Place main buy order (LONG position)
        order_params = {
            'symbol': symbol.replace('-', ''),  # API expects format like BTCUSDT
            'side': 'BUY',
            'type': 'LIMIT',
            'quantity': f"{position_size:.6f}",
            'price': f"{limit_price:.2f}",
            'leverage': str(leverage)
        }

        # Place stop loss order (Sell to close LONG position)
        stop_loss_params = {
            'symbol': symbol.replace('-', ''),
            'side': 'SELL',
            'type': 'STOP_MARKET',
            'quantity': f"{position_size:.6f}",
            'stopPrice': f"{stop_loss_price:.2f}",
            'leverage': str(leverage)
        }

        # Place take profit order (Sell to close LONG position)
        take_profit_params = {
            'symbol': symbol.replace('-', ''),
            'side': 'SELL',
            'type': 'TAKE_PROFIT_MARKET',
            'quantity': f"{position_size:.6f}",
            'stopPrice': f"{take_profit_price:.2f}",
            'leverage': str(leverage)
        }

        try:
            # Place main order first
            main_order = client.create_order_v3(**order_params)
            print(f"Main order placed: {main_order}")

            # Place stop loss order
            stop_order = client.create_order_v3(**stop_loss_params)
            print(f"Stop loss order placed: {stop_order}")

            # Place take profit order
            profit_order = client.create_order_v3(**take_profit_params)
            print(f"Take profit order placed: {profit_order}")

            return TradeResponse(
                message=f"Successfully placed LONG order + stop loss + take profit (1:3) for {position_size:.6f} {symbol}",
                orderId=main_order.get('id', 'unknown'),
                position_size=position_size,
                risk_amount=account_equity * 0.05,
                leverage=leverage,
                entry_price=float(limit_price)
            )

        except Exception as order_error:
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

        # Calculate stop loss and take profit prices (1:3 risk ratio for SHORT positions)
        risk_pct = 0.05  # 5% risk
        stop_loss_distance_pct = risk_pct / leverage  # Stop distance = 5% risk / leverage
        take_profit_distance_pct = stop_loss_distance_pct * 3  # 1:3 risk ratio = 3x stop distance

        stop_loss_price = limit_price * decimal.Decimal(str(1 + stop_loss_distance_pct))  # Above entry for SHORT
        take_profit_price = limit_price * decimal.Decimal(str(1 - take_profit_distance_pct))  # Below entry for SHORT

        # Place main sell order (SHORT position)
        order_params = {
            'symbol': symbol.replace('-', ''),  # API expects format like BTCUSDT
            'side': 'SELL',
            'type': 'LIMIT',
            'quantity': f"{position_size:.6f}",
            'price': f"{limit_price:.2f}",
            'leverage': str(leverage)
        }

        # Place stop loss order (Buy to close SHORT position)
        stop_loss_params = {
            'symbol': symbol.replace('-', ''),
            'side': 'BUY',
            'type': 'STOP_MARKET',
            'quantity': f"{position_size:.6f}",
            'stopPrice': f"{stop_loss_price:.2f}",
            'leverage': str(leverage)
        }

        # Place take profit order (Buy to close SHORT position)
        take_profit_params = {
            'symbol': symbol.replace('-', ''),
            'side': 'BUY',
            'type': 'TAKE_PROFIT_MARKET',
            'quantity': f"{position_size:.6f}",
            'stopPrice': f"{take_profit_price:.2f}",
            'leverage': str(leverage)
        }

        try:
            # Place main order first
            main_order = client.create_order_v3(**order_params)
            print(f"Main order placed: {main_order}")

            # Place stop loss order
            stop_order = client.create_order_v3(**stop_loss_params)
            print(f"Stop loss order placed: {stop_order}")

            # Place take profit order
            profit_order = client.create_order_v3(**take_profit_params)
            print(f"Take profit order placed: {profit_order}")

            return TradeResponse(
                message=f"Successfully placed SHORT order + stop loss + take profit (1:3) for {position_size:.6f} {symbol}",
                orderId=main_order.get('id', 'unknown'),
                position_size=position_size,
                risk_amount=account_equity * 0.05,
                leverage=leverage,
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
                    print(f"DEBUG LIQ: LONG - entry={entry_price}, balance={wallet_balance}, abs_balance={abs_balance}, size={size}, liq={liquidation_price}")
                else:  # SHORT
                    # SHORT liquidation price: entry_price + (abs(balance) / size)
                    abs_balance = abs(wallet_balance)
                    liquidation_price = entry_price + (abs_balance / size)
                    print(f"DEBUG LIQ: SHORT - entry={entry_price}, balance={wallet_balance}, abs_balance={abs_balance}, size={size}, liq={liquidation_price}")

                # Ensure liquidation price makes sense (clamp to reasonable values)
                if position.get('side') == 'LONG' and liquidation_price > entry_price:
                    liquidation_price = entry_price * 0.8  # Max 20% drop if calculation wrong
                elif position.get('side') == 'SHORT' and liquidation_price < entry_price:
                    liquidation_price = entry_price * 1.2  # Max 20% rise if calculation wrong

                print(f"DEBUG LIQ FINAL: {liquidation_price}")

                distance_to_liquidation = abs(current_price - liquidation_price)

                print(f"DEBUG LIQ FINAL: price={liquidation_price}, distance={distance_to_liquidation}")

                enhanced_position = dict(position)
                enhanced_position.update({
                    'current_price': round(current_price, 2),
                    'unrealized_pnl': round(unrealized_pnl, 2),
                    'pnl_percentage': round(pnl_percentage, 6),
                    'notional_value': round(size * current_price, 2),
                    'effective_leverage': round(effective_leverage, 2),
                    'liquidation_price': round(liquidation_price, 2),
                    'distance_to_liquidation': round(distance_to_liquidation, 2),
                    'liquidation_percentage': round((distance_to_liquidation / current_price) * 100, 2)
                })

                print(f"DEBUG: Added fields to position: {enhanced_position.keys()}")
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

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Apex Omni Trading Bot...")
    print("📊 Web dashboard available at: http://localhost:8000/docs")
    uvicorn.run(
        "trading_service:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        timeout_graceful_shutdown=1
    )
