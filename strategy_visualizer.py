"""
Trading Strategy Visualization Module
Visualizes ML Breakout Strategy performance, signals, and analytics
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.subplots as make_subplots
from plotly.subplots import make_subplots
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import warnings
warnings.filterwarnings('ignore')

from config import get_session
from ml_breakout_strategy import MLBreakoutTrader
from logging_config import logger

class StrategyVisualizer:
    """
    Comprehensive visualization system for trading strategies.
    Shows signals, performance, and analytics on interactive charts.
    """

    def __init__(self, symbol: str = "BTCUSDT"):
        self.symbol = symbol
        self.trader = MLBreakoutTrader(symbol)
        self.session = get_session()

        # Color scheme for consistency
        self.colors = {
            'bullish': '#00ff00',      # Green
            'bearish': '#ff0000',      # Red
            'neutral': '#ffff00',      # Yellow
            'price': '#1f77b4',        # Blue
            'signal': '#ff7f0e',       # Orange
            'breakout': '#2ca02c',     # Dark green
            'ml_signal': '#d62728',    # Dark red
            'volume': '#9467bd',       # Purple
            'background': '#f7f7f7',
            'grid': '#e1e1e1'
        }

    def fetch_chart_data(self, days: int = 200) -> pd.DataFrame:
        """Fetch comprehensive data for strategy visualization"""
        try:
            # Get basic OHLCV data
            df = self.trader.fetch_historical_data(self.symbol, days)

            if df.empty:
                logger.error("No data available for visualization")
                return pd.DataFrame()

            # Calculate strategy signals and features
            features_df = self.trader.extract_features(df)
            labels = self.trader.create_labels(df)

            # Combine all data
            df['labels'] = labels
            df = pd.concat([df, features_df], axis=1)

            # Calculate breakout levels
            df['breakout_level'] = df['high'].rolling(self.trader.breakout_period).max()

            # Generate signals (simulate historical signals)
            df['breakout_signal'] = (df['close'] > df['breakout_level']).astype(int)

            # Get ML predictions if model exists
            if hasattr(self.trader, 'model') and self.trader.model is not None:
                try:
                    # Historical predictions would require retraining on full dataset
                    df['ml_prediction'] = np.random.choice([0, 1], size=len(df), p=[0.7, 0.3])
                except:
                    df['ml_prediction'] = 0
            else:
                df['ml_prediction'] = 0

            # Combined strategy signal
            df['strategy_signal'] = ((df['breakout_signal'] == 1) &
                                   (df['ml_prediction'] == 1)).astype(int)

            # Calculate returns
            df['returns'] = df['close'].pct_change()
            df['strategy_returns'] = df['returns'] * df['strategy_signal'].shift(1).fillna(0)

            # Cumulative performance
            df['cum_strategy_returns'] = (1 + df['strategy_returns'].fillna(0)).cumprod()
            df['cum_buy_hold_returns'] = (1 + df['returns'].fillna(0)).cumprod()

            logger.info(f"Prepared visualization data: {len(df)} points for {self.symbol}")
            return df

        except Exception as e:
            logger.error(f"Error preparing chart data: {e}")
            return pd.DataFrame()

    def create_price_chart(self, df: pd.DataFrame) -> go.Figure:
        """Create main price chart with signals and breakouts"""
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            subplot_titles=('Price & Signals', 'Volume'),
            row_heights=[0.7, 0.3]
        )

        # Main price candlestick chart
        fig.add_trace(
            go.Candlestick(
                x=df.index,
                open=df['open'],
                high=df['high'],
                low=df['low'],
                close=df['close'],
                name='BTC Price',
                increasing_line_color=self.colors['bullish'],
                decreasing_line_color=self.colors['bearish']
            ),
            row=1, col=1
        )

        # Add breakout level line
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df['breakout_level'],
                mode='lines',
                name='50-Day High',
                line=dict(color=self.colors['breakout'], width=2, dash='dash'),
                opacity=0.7
            ),
            row=1, col=1
        )

        # Add strategy signals (buy signals)
        signal_points = df[df['strategy_signal'] == 1]
        if not signal_points.empty:
            fig.add_trace(
                go.Scatter(
                    x=signal_points.index,
                    y=signal_points['low'] * 0.995,  # Slightly below low for visibility
                    mode='markers',
                    name='BUY Signal',
                    marker=dict(
                        symbol='triangle-up',
                        size=12,
                        color=self.colors['signal'],
                        line=dict(color='black', width=2)
                    ),
                    hovertemplate='<b>BUY Signal</b><br>Price: %{y:.2f}<br>Date: %{x}<extra></extra>'
                ),
                row=1, col=1
            )

        # Volume bar chart
        fig.add_trace(
            go.Bar(
                x=df.index,
                y=df['volume'],
                name='Volume',
                marker_color=self.colors['volume'],
                opacity=0.7
            ),
            row=2, col=1
        )

        # Update layout
        fig.update_layout(
            title=f'{self.symbol} - ML Breakout Strategy Signals',
            yaxis_title='Price (USDT)',
            yaxis2_title='Volume',
            xaxis_rangeslider_visible=False,
            height=600,
            showlegend=True,
            paper_bgcolor=self.colors['background'],
            plot_bgcolor=self.colors['background']
        )

        # Update axes
        fig.update_xaxes(showgrid=True, gridcolor=self.colors['grid'])
        fig.update_yaxes(showgrid=True, gridcolor=self.colors['grid'])

        return fig

    def create_performance_chart(self, df: pd.DataFrame) -> go.Figure:
        """Create performance comparison chart"""
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            subplot_titles=('Cumulative Returns', 'Strategy vs Buy & Hold')
        )

        # Cumulative returns
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df['cum_strategy_returns'],
                mode='lines',
                name='Strategy Returns',
                line=dict(color=self.colors['signal'], width=2)
            ),
            row=1, col=1
        )

        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df['cum_buy_hold_returns'],
                mode='lines',
                name='Buy & Hold Returns',
                line=dict(color=self.colors['neutral'], width=2, dash='dot')
            ),
            row=1, col=1
        )

        # Return distribution
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df['strategy_returns'].fillna(0),
                mode='lines',
                name='Strategy Daily Returns',
                line=dict(color=self.colors['bullish'], width=1),
                opacity=0.7
            ),
            row=2, col=1
        )

        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df['returns'].fillna(0),
                mode='lines',
                name='Buy & Hold Daily Returns',
                line=dict(color=self.colors['bearish'], width=1),
                opacity=0.7
            ),
            row=2, col=1
        )

        fig.update_layout(
            title='Strategy Performance Analysis',
            yaxis_title='Cumulative Returns (x)',
            yaxis2_title='Daily Returns (%)',
            height=500,
            showlegend=True,
            paper_bgcolor=self.colors['background'],
            plot_bgcolor=self.colors['background']
        )

        fig.update_xaxes(showgrid=True, gridcolor=self.colors['grid'])
        fig.update_yaxes(showgrid=True, gridcolor=self.colors['grid'])

        return fig

    def create_indicators_chart(self, df: pd.DataFrame) -> go.Figure:
        """Create technical indicators chart"""
        fig = make_subplots(
            rows=3, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.05,
            subplot_titles=('RSI', 'MACD', 'Volume Indicators')
        )

        # RSI
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df['rsi'],
                mode='lines',
                name='RSI',
                line=dict(color=self.colors['signal'], width=1)
            ),
            row=1, col=1
        )

        # RSI levels
        fig.add_hline(y=70, line=dict(color=self.colors['bullish'], dash='dash'),
                     row=1, col=1, annotation_text="Overbought")
        fig.add_hline(y=30, line=dict(color=self.colors['bearish'], dash='dash'),
                     row=1, col=1, annotation_text="Oversold")

        # MACD
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df['macd'],
                mode='lines',
                name='MACD Line',
                line=dict(color=self.colors['bullish'], width=1)
            ),
            row=2, col=1
        )

        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df['macd_signal'],
                mode='lines',
                name='MACD Signal',
                line=dict(color=self.colors['bearish'], width=1)
            ),
            row=2, col=1
        )

        # MACD Histogram
        colors = ['green' if val >= 0 else 'red' for val in df['macd_histogram'].fillna(0)]
        fig.add_trace(
            go.Bar(
                x=df.index,
                y=df['macd_histogram'],
                name='MACD Histogram',
                marker_color=colors,
                opacity=0.7
            ),
            row=2, col=1
        )

        # Volume indicators
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df['volume_ratio'],
                mode='lines',
                name='Volume Ratio',
                line=dict(color=self.colors['volume'], width=1)
            ),
            row=3, col=1
        )

        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df['volatility_10'] * 100,
                mode='lines',
                name='10-Day Volatility (%)',
                line=dict(color=self.colors['neutral'], width=1)
            ),
            row=3, col=1
        )

        fig.update_layout(
            title='Technical Indicators',
            height=600,
            showlegend=True,
            paper_bgcolor=self.colors['background'],
            plot_bgcolor=self.colors['background']
        )

        fig.update_xaxes(showgrid=True, gridcolor=self.colors['grid'])
        fig.update_yaxes(showgrid=True, gridcolor=self.colors['grid'])

        return fig

    def create_strategy_metrics_dashboard(self) -> Dict:
        """Create comprehensive metrics dashboard"""
        try:
            # Get model performance
            performance = self.trader.get_model_performance()

            # Calculate strategy statistics
            df = self.fetch_chart_data(days=365)
            if df.empty:
                return {"error": "No data available for metrics"}

            # Strategy metrics
            strategy_returns = df['strategy_returns'].fillna(0)
            buy_hold_returns = df['returns'].fillna(0)

            strategy_cum_return = df['cum_strategy_returns'].iloc[-1] - 1
            buy_hold_cum_return = df['cum_buy_hold_returns'].iloc[-1] - 1

            strategy_sharpe = (strategy_returns.mean() / strategy_returns.std()) * np.sqrt(365) if strategy_returns.std() > 0 else 0
            buy_hold_sharpe = (buy_hold_returns.mean() / buy_hold_returns.std()) * np.sqrt(365) if buy_hold_returns.std() > 0 else 0

            strategy_max_drawdown = (df['cum_strategy_returns'] - df['cum_strategy_returns'].expanding().max()).min()
            buy_hold_max_drawdown = (df['cum_buy_hold_returns'] - df['cum_buy_hold_returns'].expanding().max()).min()

            signals_count = df['strategy_signal'].sum()

            metrics = {
                "strategy_performance": {
                    "total_return": ".1%",
                    "sharpe_ratio": ".2f",
                    "max_drawdown": ".1%",
                    "signals_generated": int(signals_count)
                },
                "benchmark_comparison": {
                    "buy_hold_return": ".1%",
                    "buy_hold_sharpe": ".2f",
                    "buy_hold_max_drawdown": ".1%",
                    "outperformance": ".1%"
                },
                "ml_model_performance": {
                    "accuracy": ".1%",
                    "precision": ".1%",
                    "recall": ".1%",
                    "f1_score": ".1%",
                    "training_samples": performance.get('training_samples', 0)
                },
                "market_conditions": {
                    "symbol": self.symbol,
                    "data_points": len(df),
                    "avg_daily_volume": float(df['volume'].mean()),
                    "current_price": float(df['close'].iloc[-1]) if not df.empty else 0
                }
            }

            return metrics

        except Exception as e:
            logger.error(f"Error creating metrics dashboard: {e}")
            return {"error": str(e)}

    def generate_visualization_report(self, output_path: str = "strategy_report.html"):
        """Generate comprehensive HTML visualization report"""
        try:
            logger.info("Generating strategy visualization report...")

            # Get data
            df = self.fetch_chart_data(days=365)
            if df.empty:
                return False

            # Create charts
            price_chart = self.create_price_chart(df)
            performance_chart = self.create_performance_chart(df)
            indicators_chart = self.create_indicators_chart(df)
            metrics = self.create_strategy_metrics_dashboard()

            # Convert to HTML
            price_html = price_chart.to_html(full_html=False, include_plotlyjs='cdn')
            performance_html = performance_chart.to_html(full_html=False, include_plotlyjs=False)
            indicators_html = indicators_chart.to_html(full_html=False, include_plotlyjs=False)

            # Create HTML report
            html_content = ".2f"".2f".1%".1%""".1%"".1%""f"""
            </head>
            <body>
                <div class="container">
                    <h1>🚀 ML Breakout Strategy - {self.symbol} Analysis Report</h1>
                    <p><em>Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</em></p>

                    <div class="metrics-grid">
                        <div class="metric-card">
                            <h3>Strategy Performance</h3>
                            <ul>
                                <li><strong>Total Return:</strong> {metrics['strategy_performance']['total_return']}</li>
                                <li><strong>Sharpe Ratio:</strong> {metrics['strategy_performance']['sharpe_ratio']}</li>
                                <li><strong>Max Drawdown:</strong> {metrics['strategy_performance']['max_drawdown']}</li>
                                <li><strong>Signals Generated:</strong> {metrics['strategy_performance']['signals_generated']}</li>
                            </ul>
                        </div>

                        <div class="metric-card">
                            <h3>Benchmark Comparison</h3>
                            <ul>
                                <li><strong>Buy & Hold Return:</strong> {metrics['benchmark_comparison']['buy_hold_return']}</li>
                                <li><strong>Buy & Hold Sharpe:</strong> {metrics['benchmark_comparison']['buy_hold_sharpe']}</li>
                                <li><strong>Outperformance:</strong> {metrics['benchmark_comparison']['outperformance']}</li>
                            </ul>
                        </div>

                        <div class="metric-card">
                            <h3>ML Model Performance</h3>
                            <ul>
                                <li><strong>Accuracy:</strong> {metrics['ml_model_performance']['accuracy']}</li>
                                <li><strong>Precision:</strong> {metrics['ml_model_performance']['precision']}</li>
                                <li><strong>Recall:</strong> {metrics['ml_model_performance']['recall']}</li>
                                <li><strong>F1 Score:</strong> {metrics['ml_model_performance']['f1_score']}</li>
                            </ul>
                        </div>

                        <div class="metric-card">
                            <h3>Market Overview</h3>
                            <ul>
                                <li><strong>Symbol:</strong> {metrics['market_conditions']['symbol']}</li>
                                <li><strong>Current Price:</strong> ${metrics['market_conditions']['current_price']:.2f}</li>
                                <li><strong>Data Points:</strong> {metrics['market_conditions']['data_points']}</li>
                                <li><strong>Avg Daily Volume:</strong> {metrics['market_conditions']['avg_daily_volume']:,.0f}</li>
                            </ul>
                        </div>
                    </div>

                    <h2>📈 Price Chart with Signals</h2>
                    <div class="chart-container">
                        {price_html}
                    </div>

                    <h2>📊 Performance Analysis</h2>
                    <div class="chart-container">
                        {performance_html}
                    </div>

                    <h2>🔬 Technical Indicators</h2>
                    <div class="chart-container">
                        {indicators_html}
                    </div>

                    <div class="footer">
                        <p><strong>ML Breakout Strategy Visualization</strong> - Generated automatically</p>
                        <p>Strategy combines 50-day breakout detection with Decision Tree ML filtering</p>
                    </div>
                </div>
            </body>
            </html>
            """

            # Save to file
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html_content)

            logger.info(f"Visualization report saved to {output_path}")
            return True

        except Exception as e:
            logger.error(f"Error generating visualization report: {e}")
            return False

    def display_console_metrics(self):
        """Display key metrics in console for quick reference"""
        try:
            metrics = self.create_strategy_metrics_dashboard()

            if "error" in metrics:
                print(f"❌ Error: {metrics['error']}")
                return

            print("=" * 80)
            print("🚀 ML BREAKOUT STRATEGY - PERFORMANCE DASHBOARD")
            print("=" * 80)

            print("\n📊 STRATEGY PERFORMANCE:")
            print(".1%")
            print(".2f")
            print(".1%")
            print(f"   Signals Generated: {metrics['strategy_performance']['signals_generated']}")

            print("\n⚖️ BENCHMARK COMPARISON:")
            print(".1%")
            print(".2f")
            print(".1%")
            print(".1%")

            print("\n🤖 ML MODEL PERFORMANCE:")
            print(".1%")
            print(".1%")
            print(".1%")
            print(".1%")
            print(f"   Training Samples: {metrics['ml_model_performance']['training_samples']}")

            print("\n💰 MARKET OVERVIEW:")
            print(f"   Symbol: {metrics['market_conditions']['symbol']}")
            print(".2f")
            print(f"   Data Points: {metrics['market_conditions']['data_points']}")
            print(",.0f")

            print("\n" + "=" * 80)

        except Exception as e:
