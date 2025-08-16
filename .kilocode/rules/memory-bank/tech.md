# AI Trading Bot - Technologies

## Overview
This document outlines the technologies, frameworks, and tools used in the AI Trading Bot project.

## Core Technologies

### Programming Languages
- Python 3.x - Main application language
- JavaScript - Frontend interactivity and UI logic
- HTML/CSS - Web interface structure and styling

### Web Frameworks and Libraries
- FastAPI - Web application framework for API endpoints and real-time data streaming
- Dash - For algorithmic trading simulation interface
- Plotly - Interactive charting library for financial data visualization
- pandas-ta - Technical indicator calculations using pandas

### Data Management
- Redis - In-memory data structure store for caching klines and Open Interest data
- Bybit API - Real-time and historical cryptocurrency market data
- CSV files - For logging trading episodes and strategy results

### Machine Learning and AI
- PyTorch - Deep learning framework for reinforcement learning agent
- DQN (Deep Q-Network) - Algorithm for the reinforcement learning trading agent
- Gemini API - AI-powered trading suggestions and analysis
- DeepSeek API - Alternative AI-powered trading suggestions and analysis

### Development Tools
- Git - Version control system
- pip - Python package manager
- Virtual environments - For dependency isolation

## Key Dependencies (from requirements.txt)
- fastapi - Web framework
- uvicorn - ASGI server
- redis - Redis client
- pandas - Data manipulation
- numpy - Numerical computing
- requests - HTTP library
- python-dotenv - Environment variable management
- plotly - Charting library
- dash - Web application framework
- pandas-ta - Technical analysis indicators
- torch - PyTorch library for deep learning

## Development Setup
- Python 3.8+ environment
- Virtual environment setup recommended
- Redis server running locally or remotely
- Bybit API credentials configured in .env file
- Gemini and DeepSeek API keys configured in .env file

## Technical Constraints
- Real-time data processing requirements
- Integration with external APIs (Bybit, Gemini, DeepSeek)
- Performance constraints for chart rendering and AI inference
- Data storage and caching limitations with Redis
- Security considerations for API key management

## Tool Usage Patterns
- Continuous integration of technical indicators using pandas-ta
- Event-driven architecture for real-time data updates
- Modular component design for maintainability
- Asynchronous processing for handling multiple concurrent data streams