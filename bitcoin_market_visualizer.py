"""
Bitcoin Market Visualizer
Visualizes Bitcoin price and filled market orders from centralized exchanges and DEXs
"""
import asyncio
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import requests
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import websockets
import redis.asyncio as redis


class BitcoinMarketVisualizer:
    """
    Main class for visualizing Bitcoin price and filled market orders from various exchanges
    """
    
    def __init__(self):
        # Set up logger
        self.logger = logging.getLogger(__name__)
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)
        
        self.redis_client = None
        self.btc_price_data = []
        self.cex_order_data = []
        self.dex_order_data = []
        self.supported_symbols = ["BTCUSDT", "BTCUSD", "XBTUSDT", "XBTUSD"]
        self.cex_exchanges = ["bybit", "binance", "coinbase", "kraken"]
        self.dex_exchanges = ["uniswap", "sushiswap", "pancakeswap"]
        
    async def init_redis(self):
        """Initialize Redis connection for caching"""
        try:
            self.redis_client = redis.Redis(
                host='localhost',
                port=6379,
                db=0,
                decode_responses=True
            )
            await self.redis_client.ping()
            self.logger.info("Successfully connected to Redis")
        except Exception as e:
            self.logger.error(f"Failed to connect to Redis: {e}")
            self.redis_client = None
    
    async def fetch_btc_price_bybit(self, symbol: str = "BTCUSDT", interval: str = "1m", limit: int = 200) -> List[Dict]:
        """
        Fetch Bitcoin price data from Bybit
        """
        try:
            url = "https://api.bybit.com/v5/market/kline"
            params = {
                "category": "spot",
                "symbol": symbol,
                "interval": interval,
                "limit": limit
            }
            
            response = requests.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            if data.get("retCode") != 0:
                self.logger.error(f"Bybit API error: {data.get('retMsg')}")
                return []
            
            klines = []
            for kline in data.get("result", {}).get("list", []):
                klines.append({
                    "timestamp": int(kline[0]) / 1000,  # Convert to seconds
                    "open": float(kline[1]),
                    "high": float(kline[2]),
                    "low": float(kline[3]),
                    "close": float(kline[4]),
                    "volume": float(kline[5]),
                    "turnover": float(kline[6]) if len(kline) > 6 else 0
                })
            
            # Sort by timestamp
            klines.sort(key=lambda x: x["timestamp"])
            self.logger.info(f"Fetched {len(klines)} price data points from Bybit")
            return klines
            
        except Exception as e:
            self.logger.error(f"Error fetching BTC price from Bybit: {e}")
            return []
    
    async def fetch_btc_price_binance(self, symbol: str = "BTCUSDT", interval: str = "1m", limit: int = 200) -> List[Dict]:
        """
        Fetch Bitcoin price data from Binance
        """
        try:
            url = "https://api.binance.com/api/v3/klines"
            params = {
                "symbol": symbol,
                "interval": interval,
                "limit": limit
            }
            
            response = requests.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            klines = []
            for kline in data:
                klines.append({
                    "timestamp": kline[0] / 1000,  # Convert to seconds
                    "open": float(kline[1]),
                    "high": float(kline[2]),
                    "low": float(kline[3]),
                    "close": float(kline[4]),
                    "volume": float(kline[5]),
                })
            
            # Sort by timestamp
            klines.sort(key=lambda x: x["timestamp"])
            self.logger.info(f"Fetched {len(klines)} price data points from Binance")
            return klines
            
        except Exception as e:
            self.logger.error(f"Error fetching BTC price from Binance: {e}")
            return []
    
    async def fetch_filled_orders_bybit(self, symbol: str = "BTCUSDT") -> List[Dict]:
        """
        Fetch filled market orders from Bybit using public endpoints
        """
        try:
            self.logger.info(f"Fetching recent trades for {symbol} from Bybit")
            
            # Use Bybit's public endpoint to get recent trades
            url = "https://api.bybit.com/v5/market/recent-trade"
            params = {
                "category": "spot",
                "symbol": symbol,
                "limit": 50  # Get last 50 trades
            }
            
            response = requests.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            if data.get("retCode") != 0:
                self.logger.error(f"Bybit API error: {data.get('retMsg')}")
                return []
            
            # Process the trade data
            trades = []
            for trade in data.get("result", {}).get("list", []):
                trades.append({
                    "exchange": "bybit",
                    "symbol": trade.get("symbol", symbol),
                    "side": trade.get("side", "unknown").lower(),
                    "price": float(trade.get("price", 0)),
                    "quantity": float(trade.get("size", 0)),
                    "timestamp": int(trade.get("time", 0)) / 1000,  # Convert to seconds
                    "order_type": "market",
                    "trade_id": trade.get("execId")
                })
            
            self.logger.info(f"Fetched {len(trades)} recent trades from Bybit")
            return trades
            
        except Exception as e:
            self.logger.error(f"Error fetching filled orders from Bybit: {e}")
            # Return mock data in case of error for demonstration purposes
            return await self.generate_mock_filled_orders("bybit", symbol, 10)
    
    async def fetch_filled_orders_binance(self, symbol: str = "BTCUSDT") -> List[Dict]:
        """
        Fetch filled market orders from Binance using public endpoints
        """
        try:
            self.logger.info(f"Fetching recent trades for {symbol} from Binance")
            
            # Use Binance's public endpoint to get recent trades
            url = "https://api.binance.com/api/v3/trades"
            params = {
                "symbol": symbol,
                "limit": 50  # Get last 50 trades
            }
            
            response = requests.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            # Process the trade data
            trades = []
            for trade in data:
                # Determine side based on whether buyer is market maker
                # In practice, we might use additional logic to determine buy/sell
                side = "buy" if trade.get("isBuyerMaker", True) else "sell"
                
                trades.append({
                    "exchange": "binance",
                    "symbol": symbol,
                    "side": side,
                    "price": float(trade.get("price", 0)),
                    "quantity": float(trade.get("qty", 0)),
                    "timestamp": int(trade.get("time", 0)) / 1000,  # Convert to seconds
                    "order_type": "market",
                    "trade_id": trade.get("id")
                })
            
            self.logger.info(f"Fetched {len(trades)} recent trades from Binance")
            return trades
            
        except Exception as e:
            self.logger.error(f"Error fetching filled orders from Binance: {e}")
            # Return mock data in case of error for demonstration purposes
            return await self.generate_mock_filled_orders("binance", symbol, 10)
    
    async def fetch_filled_orders_uniswap(self, token_pair: str = "WBTC/WETH") -> List[Dict]:
        """
        Fetch filled market orders from Uniswap V3 using The Graph API
        Note: Direct Uniswap API doesn't provide trade history without subgraph
        """
        try:
            self.logger.info(f"Fetching filled orders for {token_pair} from Uniswap via The Graph")
            
            # Using Uniswap V3 subgraph to get swaps
            # This is a public endpoint that doesn't require authentication
            url = "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v3"
            
            # Define the GraphQL query to get recent swaps
            # We'll query for WBTC/WETH swaps as an example
            query = """
            query swaps($first: Int, $skip: Int) {
              swaps(
                first: $first,
                skip: $skip,
                orderBy: timestamp,
                orderDirection: desc
              ) {
                id
                transaction {
                  timestamp
                }
                token0 {
                  symbol
                  name
                }
                token1 {
                  symbol
                  name
                }
                amount0
                amount1
                sqrtPriceX96
                liquidity
                tick
                recipient
                sender
              }
            }
            """
            
            variables = {
                "first": 20,
                "skip": 0
            }
            
            payload = {
                "query": query,
                "variables": variables
            }
            
            response = requests.post(url, json=payload)
            response.raise_for_status()
            
            data = response.json()
            
            # Process the swap data
            swaps = []
            for swap in data.get("data", {}).get("swaps", []):
                # Filter for WBTC/WETH pairs for BTC proxy
                token0_symbol = swap["token0"]["symbol"]
                token1_symbol = swap["token1"]["symbol"]
                
                # Check if the swap involves WBTC (Bitcoin proxy)
                if "WBTC" in [token0_symbol, token1_symbol]:
                    # Calculate price based on amounts
                    amount0 = float(swap["amount0"])
                    amount1 = float(swap["amount1"])
                    
                    # Determine if it's a buy or sell based on which token is being swapped
                    # If WBTC amount is negative, someone sold WBTC (sold BTC)
                    # If WBTC amount is positive, someone bought WBTC (bought BTC)
                    wbtc_amount = amount0 if token0_symbol == "WBTC" else amount1
                    other_amount = amount1 if token0_symbol == "WBTC" else amount0
                    
                    # Calculate a proxy price based on the amounts swapped
                    if abs(wbtc_amount) > 0:
                        price = abs(other_amount) / abs(wbtc_amount) if "WETH" in [token0_symbol, token1_symbol] else 60000
                    
                    side = "sell" if wbtc_amount < 0 else "buy"
                    
                    swaps.append({
                        "exchange": "uniswap",
                        "symbol": "WBTC",
                        "side": side,
                        "price": price,
                        "quantity": abs(wbtc_amount),
                        "timestamp": int(swap["transaction"]["timestamp"]),
                        "order_type": "swap",
                        "trade_id": swap["id"]
                    })
            
            self.logger.info(f"Fetched {len(swaps)} swaps from Uniswap V3")
            return swaps
            
        except Exception as e:
            self.logger.error(f"Error fetching filled orders from Uniswap: {e}")
            # Return mock data in case of error for demonstration purposes
            return await self.generate_mock_filled_orders("uniswap", "WBTC", 5, is_dex=True)
    
    async def aggregate_all_data(self):
        """
        Aggregate price and order data from all sources
        """
        self.logger.info("Aggregating data from all sources...")
        
        # Fetch price data from multiple exchanges
        bybit_price_data = await self.fetch_btc_price_bybit()
        binance_price_data = await self.fetch_btc_price_binance()
        
        # For visualization, we'll use the Bybit data as reference
        # In a real application, we would merge data from multiple exchanges
        if bybit_price_data:
            self.btc_price_data = bybit_price_data
        elif binance_price_data:
            self.btc_price_data = binance_price_data
        
        # Fetch order data from centralized exchanges
        bybit_orders = await self.fetch_filled_orders_bybit()
        binance_orders = await self.fetch_filled_orders_binance()
        
        # Fetch order data from decentralized exchanges
        uniswap_orders = await self.fetch_filled_orders_uniswap()
        
        # Combine all order data
        self.cex_order_data = bybit_orders + binance_orders
        self.dex_order_data = uniswap_orders
        
        self.logger.info(f"Aggregated {len(self.btc_price_data)} price points, "
                   f"{len(self.cex_order_data)} CEX orders, "
                   f"{len(self.dex_order_data)} DEX orders")
    
    async def generate_mock_filled_orders(self, exchange: str, symbol: str, count: int, is_dex: bool = False) -> List[Dict]:
        """
        Generate mock filled orders for demonstration purposes when API fails
        """
        try:
            self.logger.info(f"Generating {count} mock filled orders for {exchange}")
            
            mock_orders = []
            current_time = int(time.time())
            
            for i in range(count):
                timestamp = current_time - (i * 180)  # Every 3 minutes
                order_type = "buy" if i % 2 == 0 else "sell"
                
                # Base price around current levels with some volatility
                base_price = 60000  # Approximate BTC price
                if is_dex:
                    price = base_price + np.random.normal(0, 1000)  # Higher volatility for DEX
                else:
                    price = base_price + np.random.normal(0, 500)   # Lower volatility for CEX
                
                # Different quantity patterns for CEX vs DEX
                if is_dex:
                    quantity = np.random.uniform(0.001, 0.1)  # Typically smaller DEX trades
                else:
                    quantity = np.random.uniform(0.01, 1.0)   # Larger CEX trades
                
                mock_orders.append({
                    "exchange": exchange,
                    "symbol": symbol,
                    "side": order_type,
                    "price": float(price),
                    "quantity": float(quantity),
                    "timestamp": timestamp,
                    "order_type": "market" if not is_dex else "swap",
                    "trade_id": f"mock_{exchange}_{i}"
                })
            
            self.logger.info(f"Generated {len(mock_orders)} mock filled orders for {exchange}")
            return mock_orders
            
        except Exception as e:
            self.logger.error(f"Error generating mock filled orders for {exchange}: {e}")
            return []
    
    def create_visualization(self):
        """
        Create an interactive visualization of Bitcoin price and filled orders
        """
        self.logger.info("Creating visualization...")
        
        if not self.btc_price_data:
            self.logger.warning("No price data available for visualization")
            return
        
        # Create subplots: price chart on top, volume and orders info below
        fig = make_subplots(
            rows=2, 
            cols=1, 
            shared_xaxes=True,
            vertical_spacing=0.1,
            row_heights=[0.7, 0.3],
            subplot_titles=('Bitcoin Price (USD)', 'Trading Volume & Market Activity')
        )
        
        # Convert timestamps to datetime for plotting
        timestamps = [datetime.fromtimestamp(int(point['timestamp'])) for point in self.btc_price_data]
        
        # Add candlestick chart for price
        fig.add_trace(
            go.Candlestick(
                x=timestamps,
                open=[float(point['open']) for point in self.btc_price_data],
                high=[float(point['high']) for point in self.btc_price_data],
                low=[float(point['low']) for point in self.btc_price_data],
                close=[float(point['close']) for point in self.btc_price_data],
                name="BTC Price",
                increasing_line_color='green',
                decreasing_line_color='red'
            ),
            row=1, col=1
        )
        
        # Add volume bars to the second subplot
        volumes = [float(point['volume']) for point in self.btc_price_data]
        fig.add_trace(
            go.Bar(
                x=timestamps,
                y=volumes,
                name="Trading Volume",
                marker_color='rgba(50, 150, 200, 0.6)',
                showlegend=True
            ),
            row=2, col=1
        )
        
        # Process and add CEX orders to the price chart
        if self.cex_order_data:
            # Separate buy and sell orders
            cex_buy_orders = [order for order in self.cex_order_data if order['side'] == 'buy']
            cex_sell_orders = [order for order in self.cex_order_data if order['side'] == 'sell']
            
            # Add buy orders (green triangles)
            if cex_buy_orders:
                buy_times = [datetime.fromtimestamp(order['timestamp']) for order in cex_buy_orders]
                buy_prices = [order['price'] for order in cex_buy_orders]
                buy_sizes = [min(30, max(5, order['quantity'] * 10)) for order in cex_buy_orders]  # Scale size for visibility
                
                fig.add_trace(
                    go.Scatter(
                        x=buy_times,
                        y=buy_prices,
                        mode='markers',
                        marker=dict(
                            symbol='triangle-up',
                            size=buy_sizes,
                            color='rgba(0, 255, 0, 0.7)',
                            line=dict(width=1, color='DarkSlateGrey')
                        ),
                        name='CEX Buy Orders',
                        text=[f"Quantity: {order['quantity']:.4f}<br>Price: ${order['price']:.2f}" for order in cex_buy_orders],
                        hovertemplate='<b>CEX Buy Order</b><br>' +
                                     'Price: %{y:.2f}<br>' +
                                     'Time: %{x}<br>' +
                                     'Quantity: %{text}<extra></extra>',
                        showlegend=True
                    ),
                    row=1, col=1
                )
                
            # Add sell orders (red triangles)
            if cex_sell_orders:
                sell_times = [datetime.fromtimestamp(order['timestamp']) for order in cex_sell_orders]
                sell_prices = [order['price'] for order in cex_sell_orders]
                sell_sizes = [min(30, max(5, order['quantity'] * 10)) for order in cex_sell_orders]  # Scale size for visibility
                
                fig.add_trace(
                    go.Scatter(
                        x=sell_times,
                        y=sell_prices,
                        mode='markers',
                        marker=dict(
                            symbol='triangle-down',
                            size=sell_sizes,
                            color='rgba(255, 0, 0, 0.7)',
                            line=dict(width=1, color='DarkSlateGrey')
                        ),
                        name='CEX Sell Orders',
                        text=[f"Quantity: {order['quantity']:.4f}<br>Price: ${order['price']:.2f}" for order in cex_sell_orders],
                        hovertemplate='<b>CEX Sell Order</b><br>' +
                                     'Price: %{y:.2f}<br>' +
                                     'Time: %{x}<br>' +
                                     'Quantity: %{text}<extra></extra>',
                        showlegend=True
                    ),
                    row=1, col=1
                )
        
        # Process and add DEX orders to the price chart
        if self.dex_order_data:
            # Separate buy and sell orders
            dex_buy_orders = [order for order in self.dex_order_data if order['side'] == 'buy']
            dex_sell_orders = [order for order in self.dex_order_data if order['side'] == 'sell']
            
            # Add DEX buy orders (light green circles)
            if dex_buy_orders:
                buy_times = [datetime.fromtimestamp(order['timestamp']) for order in dex_buy_orders]
                buy_prices = [order['price'] for order in dex_buy_orders]
                buy_sizes = [min(25, max(5, order['quantity'] * 15)) for order in dex_buy_orders]  # Scale size for visibility
                
                fig.add_trace(
                    go.Scatter(
                        x=buy_times,
                        y=buy_prices,
                        mode='markers',
                        marker=dict(
                            symbol='circle',
                            size=buy_sizes,
                            color='rgba(144, 238, 144, 0.7)',  # Light green
                            line=dict(width=1, color='DarkSlateGrey')
                        ),
                        name='DEX Buy Orders',
                        text=[f"Quantity: {order['quantity']:.4f}<br>Price: ${order['price']:.2f}" for order in dex_buy_orders],
                        hovertemplate='<b>DEX Buy Order</b><br>' +
                                     'Price: %{y:.2f}<br>' +
                                     'Time: %{x}<br>' +
                                     'Quantity: %{text}<extra></extra>',
                        showlegend=True
                    ),
                    row=1, col=1
                )
                
            # Add DEX sell orders (pink circles)
            if dex_sell_orders:
                sell_times = [datetime.fromtimestamp(order['timestamp']) for order in dex_sell_orders]
                sell_prices = [order['price'] for order in dex_sell_orders]
                sell_sizes = [min(25, max(5, order['quantity'] * 15)) for order in dex_sell_orders]  # Scale size for visibility
                
                fig.add_trace(
                    go.Scatter(
                        x=sell_times,
                        y=sell_prices,
                        mode='markers',
                        marker=dict(
                            symbol='circle',
                            size=sell_sizes,
                            color='rgba(255, 182, 193, 0.7)',  # Light pink
                            line=dict(width=1, color='DarkSlateGrey')
                        ),
                        name='DEX Sell Orders',
                        text=[f"Quantity: {order['quantity']:.4f}<br>Price: ${order['price']:.2f}" for order in dex_sell_orders],
                        hovertemplate='<b>DEX Sell Order</b><br>' +
                                     'Price: %{y:.2f}<br>' +
                                     'Time: %{x}<br>' +
                                     'Quantity: %{text}<extra></extra>',
                        showlegend=True
                    ),
                    row=1, col=1
                )
        
        # Update layout
        fig.update_layout(
            title={
                'text': 'Bitcoin Price and Filled Market Orders from Centralized & Decentralized Exchanges',
                'x': 0.5,
                'xanchor': 'center'
            },
            xaxis_title='Time',
            yaxis_title='Price (USD)',
            height=900,
            showlegend=True,
            hovermode='x unified',
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )
        
        # Update x-axis for subplots
        fig.update_xaxes(title_text="Time", row=2, col=1)
        fig.update_yaxes(title_text="Volume", row=2, col=1)
        
        # Add range selector buttons for easier navigation
        fig.update_layout(
            xaxis=dict(
                rangeselector=dict(
                    buttons=list([
                        dict(count=1, label="1h", step="hour", stepmode="backward"),
                        dict(count=6, label="6h", step="hour", stepmode="backward"),
                        dict(count=12, label="12h", step="hour", stepmode="backward"),
                        dict(count=1, label="1d", step="day", stepmode="backward"),
                        dict(step="all", label="All")
                    ])
                ),
                rangeslider=dict(visible=True),
                type="date"
            )
        )
        
        self.logger.info("Visualization created successfully")
        return fig
    
    async def run_visualization(self):
        """
        Main method to run the entire visualization process
        """
        self.logger.info("Starting Bitcoin Market Visualizer...")
        
        # Initialize Redis connection
        await self.init_redis()
        
        # Aggregate all data
        await self.aggregate_all_data()
        
        # Create visualization
        fig = self.create_visualization()
        
        if fig:
            # Show the plot
            fig.show()
            self.logger.info("Visualization displayed successfully")
        else:
            self.logger.error("Failed to create visualization")
    
    async def run_continuous_visualization(self):
        """
        Run the visualization in continuous mode, updating every few minutes
        """
        self.logger.info("Starting continuous Bitcoin Market Visualization...")
        
        while True:
            try:
                await self.run_visualization()
                
                # Wait for 5 minutes before updating
                self.logger.info("Waiting 5 minutes before next update...")
                await asyncio.sleep(300)
                
            except KeyboardInterrupt:
                self.logger.info("Visualization interrupted by user")
                break
            except Exception as e:
                self.logger.error(f"Error in continuous visualization: {e}")
                # Wait for 1 minute before retrying
                await asyncio.sleep(60)


def main():
    """
    Main function to run the Bitcoin Market Visualizer
    """
    import argparse
    
    parser = argparse.ArgumentParser(description='Bitcoin Market Visualizer')
    parser.add_argument('--continuous', action='store_true', 
                       help='Run visualization continuously with updates')
    
    args = parser.parse_args()
    
    visualizer = BitcoinMarketVisualizer()
    
    if args.continuous:
        asyncio.run(visualizer.run_continuous_visualization())
    else:
        asyncio.run(visualizer.run_visualization())


if __name__ == "__main__":
    main()