# AI Trading Bot - Project Brief

This is a comprehensive cryptocurrency trading system built using Python, FastAPI, and machine learning technologies. The system provides both real-time trading interface with technical analysis capabilities and algorithmic trading strategies with reinforcement learning.

## Core Components

1. **Web Trading Interface** (`AppTradingView.py`):
   - Real-time charting with Plotly
   - Multi-symbol and multi-timeframe support (BTCUSDT, XMRUSDT, etc.)
   - Technical indicators (MACD, RSI, Stochastic RSI, Bollinger Bands)
   - Drawing tools for traders to mark support/resistance levels
   - Integration with Bybit API for live data streaming
   - AI-powered trading suggestions using Gemini and DeepSeek APIs

2. **Algorithmic Trading** (`algoTrade1.py`):
   - Dash-based simulation environment
   - Multi-level high/low detection (levels 0-4)
   - Trading strategies based on detected support/resistance levels
   - Position management with stop-loss/take-profit logic

3. **Reinforcement Learning Agent** (`gemini_RL.py`):
   - DQN-based trading agent trained on historical data
   - Technical indicators and Open Interest integration
   - Risk management with stop-loss and take-profit
   - Episode logging to CSV files for analysis

4. **Technical Analysis Tools**:
   - Bullish divergence detection (`detectBulishDivergence.py`)
   - Strategy optimization and visualization (`strategy_optimizer.py`)
   - Trend range detection (`trend_range_detector.py`)

## Key Features

- Real-time data streaming from Bybit
- Multi-level support/resistance detection
- Technical indicator calculations using pandas-ta
- AI-powered trading suggestions
- Reinforcement learning agent for automated trading
- Redis-based data storage and caching
- Web-based trading interface with interactive charts
- Backtesting capabilities