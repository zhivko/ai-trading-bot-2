# Trade History API endpoints

import random
import requests
from datetime import datetime, timezone
from fastapi.responses import JSONResponse
from config import SUPPORTED_SYMBOLS, TRADING_SERVICE_URL
from logging_config import logger


async def trade_history_endpoint(symbol: str = "BTCUSDT", limit: int = 20):
    """
    Get recent trade history for a symbol with volume profile and trade visualization.
    Supports filtering by trade size.
    """
    try:
        logger.info(f"/trade-history request: symbol={symbol}, limit={limit}")

        if symbol not in SUPPORTED_SYMBOLS:
            # Normalize symbol format (BTC-USDT becomes BTCUSDT, BTCUSDT stays BTCUSDT)
            normalized_symbol = symbol.replace("-", "")
            if normalized_symbol not in SUPPORTED_SYMBOLS:
                return JSONResponse({"s": "error", "errmsg": f"Unsupported symbol: {symbol}"}, status_code=400)
            symbol = normalized_symbol

        # Validate and clamp limit
        limit = max(1, min(limit, 100))

        # Fetch real trade data from trading service
        try:
            # Convert symbol format for trading service (BTCUSDT -> BTC-USDT)
            if not symbol.endswith('-USDT'):
                api_symbol = f"{symbol}-USDT"

            response = requests.get(
                f"{TRADING_SERVICE_URL}/trade-history",
                params={'symbol': api_symbol, 'limit': limit},
                timeout=10
            )

            if response.status_code == 200:
                trade_data = response.json()

                # Check if the response has the expected structure from trading service
                if 'status' in trade_data and trade_data['status'] == 'success':
                    # Extract trade history and transform to expected format
                    trades = trade_data.get('trade_history', [])

                    # Transform trades to match the JS expected format
                    # The JS code expects: price, qty, isBuyerMaker (true for sell, false for buy), time
                    transformed_trades = []
                    for trade in trades:
                        # Convert timestamp format if needed
                        timestamp = trade.get('createdAt', 0)
                        if isinstance(timestamp, str):
                            # Convert ISO string to milliseconds if needed
                            try:
                                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                                timestamp_ms = int(dt.timestamp() * 1000)
                            except:
                                timestamp_ms = 0
                        else:
                            timestamp_ms = int(timestamp)

                        # Determine side: true if isBuyerMaker (sell order), false if buy order
                        side = trade.get('side', 'BUY').upper()
                        is_buyer_maker = side == 'SELL'  # True for sell orders (Bybit convention)

                        transformed_trade = {
                            "time": timestamp_ms,  # Unix timestamp in milliseconds
                            "price": float(trade.get('price', 0)),
                            "qty": float(trade.get('size', 0)),  # Use size as qty
                            "isBuyerMaker": is_buyer_maker,  # True for sell orders
                            "id": trade.get('id', ''),
                            "symbol": symbol
                        }
                        transformed_trades.append(transformed_trade)

                    logger.info(f"Fetched {len(transformed_trades)} real trades for {symbol}")
                    return JSONResponse({
                        "status": "success",
                        "data": transformed_trades
                    })
                else:
                    logger.warning(f"Unexpected response from trading service - no trade data available")
                    return JSONResponse({"s": "error", "errmsg": "Trading service returned invalid response"}, status_code=502)
            else:
                logger.error(f"Trading service returned status {response.status_code}: {response.text}")
                return JSONResponse({"s": "error", "errmsg": f"Trading service unavailable: {response.status_code}"}, status_code=502)

        except requests.RequestException as req_error:
            logger.error(f"Error connecting to trading service: {req_error}")
            return JSONResponse({"s": "error", "errmsg": "Unable to connect to trading service"}, status_code=503)

    except Exception as e:
        logger.error(f"Error in /trade-history endpoint: {e}", exc_info=True)
        return JSONResponse({"s": "error", "errmsg": str(e)}, status_code=500)


# Removed generate_trade_data function - only using real data from trading service
