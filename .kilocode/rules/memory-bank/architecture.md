# AI Trading Bot - System Architecture

## Overview
This is a comprehensive cryptocurrency trading system built using Python, FastAPI, and machine learning technologies. The system provides both real-time trading interface with technical analysis capabilities and algorithmic trading strategies with reinforcement learning.

## Source Code Paths

### Main Web Application
- `AppTradingView.py` - Main FastAPI application with web interface, real-time data streaming, and AI integration
- `templates/index.html` - Main HTML template for the trading interface
- `static/` - Static files including CSS, JavaScript, and Plotly library
  - `static/styles.css` - Styling for the web interface
  - `static/js/` - JavaScript files for UI interactions and data handling:
    - `main.js` - Main application logic
    - `chartUpdater.js` - Chart update functionality
    - `plotlyEventHandlers.js` - Plotly event handling
    - `uiUpdaters.js` - UI update functions
    - `liveData.js` - Real-time data handling
    - `aiFeatures.js` - AI-powered features integration

### Algorithmic Trading Components
- `algoTrade1.py` - Dash-based algorithmic trading simulation with multi-level detection
- `strategy_optimizer.py` - Strategy optimization and visualization tool
- `strategy_tester.py` - Strategy testing framework
- `multilevel_high_low.html` - HTML output for multilevel high/low detection

### Reinforcement Learning Agent
- `gemini_RL.py` - DQN-based reinforcement learning agent for automated trading
- `gemini_RL_model.pth` - Trained model weights
- `gemini_RL_log.txt` - Training logs

### Technical Analysis Tools
- `detectBulishDivergence.py` - Bullish divergence detection
- `detectBulishDivergence2.py` - Additional bullish divergence detection implementation
- `trend_range_detector.py` - Trend range detection
- `jurikIndicator.py` - Jurik indicator implementation

### Data Management
- `redis_cleanup.py` - Redis data cleanup utilities
- `print_redis_data.py` - Utilities for printing Redis data
- `trading_log.txt` - Trading activity logs
- `algotrade.md` - Algorithmic trading documentation

### Configuration and Utilities
- `requirements.txt` - Python dependencies
- `start_app.bat` and `start_app.sh` - Startup scripts
- `.env` - Environment configuration
- `email_alert_service.py` - Email alert system
- `test_email_alert_service.py` - Test for email alert service

## Key Technical Decisions

### Frameworks and Technologies
- FastAPI for web application framework
- Dash for algorithmic trading simulation interface
- Redis for data caching and storage of klines and Open Interest
- Bybit API for real-time and historical cryptocurrency data
- Plotly for interactive charting
- pandas-ta for technical indicator calculations

### Design Patterns
- Component-based architecture with modular Python files
- Event-driven UI updates using JavaScript
- Real-time data streaming from external APIs
- Multi-level support/resistance detection algorithm
- Reinforcement learning agent with DQN architecture

## Component Relationships

1. **Web Interface** (`AppTradingView.py`) 
   - Connects to Bybit API for live data
   - Integrates with Redis for caching
   - Uses AI features through API calls to Gemini and DeepSeek
   - Renders charts using Plotly and JavaScript components

2. **Algorithmic Trading** (`algoTrade1.py`)
   - Uses the same Redis data as web interface
   - Processes multi-level high/low detection
   - Implements trading strategies based on detected levels
   - Generates visualizations for strategy testing

3. **Reinforcement Learning Agent** (`gemini_RL.py`)
   - Trains on historical data from Redis
   - Integrates technical indicators and Open Interest
   - Uses DQN architecture for decision making
   - Logs trading episodes to CSV files

4. **Technical Analysis Tools**
   - Provide supporting functions for all other components
   - Generate insights used by both web interface and algorithmic trading