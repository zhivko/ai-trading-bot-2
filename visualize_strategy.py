"""
Trading Strategy Visualization Script
Simple visualization for ML Breakout Strategy
"""

import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from datetime import datetime
from ml_breakout_strategy import MLBreakoutTrader
from logging_config import logger

def visualize_strategy_simple(symbol: str = "BTCUSDT", days: int = 200):
    """Create simple matplotlib visualizations for the strategy"""

    print(f"📊 Visualizing {symbol} Strategy over last {days} days...")

    # Initialize trader
    trader = MLBreakoutTrader(symbol)

    # Get historical data
    df = trader.fetch_historical_data(symbol, days)
    if df.empty:
        print("❌ No data available")
        return

    print(f"✅ Loaded {len(df)} data points")

    # Extract features
    features_df = trader.extract_features(df)
    print(f"✅ Extracted {len(features_df.columns)} features")

    # Create labels
    labels = trader.create_labels(df)
    print(f"✅ Generated labels: {labels.sum()} positive signals")

    # Create analysis dataframe
    analysis_df = df.copy()
    analysis_df['labels'] = labels
    analysis_df = pd.concat([analysis_df, features_df], axis=1)

    # Calculate breakout levels
    analysis_df['breakout_level'] = analysis_df['high'].rolling(50).max()

    # Simulate ML predictions (in real scenario, this would be from trained model)
    analysis_df['ml_prediction'] = np.random.choice([0, 1], size=len(analysis_df),
                                                   p=[0.85, 0.15])  # Mostly 0s (conservative)

    # Combined strategy signal
    analysis_df['strategy_signal'] = ((analysis_df['close'] > analysis_df['breakout_level']) &
                                    (analysis_df['ml_prediction'] == 1)).astype(int)

    print(f"✅ Strategy generated {analysis_df['strategy_signal'].sum()} signals")

    # Create visualizations
    create_price_signal_chart(analysis_df, symbol)
    create_indicators_chart(analysis_df, symbol)
    create_performance_chart(analysis_df, symbol)
    print_strategy_metrics(analysis_df, symbol)

def create_price_signal_chart(df, symbol):
    """Create price chart with signals"""
    plt.figure(figsize=(15, 10))

    # Price subplot
    plt.subplot(2, 1, 1)

    # Candlestick-like representation
    plt.plot(df.index, df['close'], color='blue', alpha=0.7, linewidth=1, label='Close Price')

    # Breakout level
    plt.plot(df.index, df['breakout_level'], color='orange', linestyle='--',
            alpha=0.8, linewidth=2, label='50-Day High (Breakout Level)')

    # Fill area where price is in breakout territory
    plt.fill_between(df.index,
                    df['close'],
                    df['breakout_level'],
                    where=(df['close'] > df['breakout_level']),
                    color='green', alpha=0.2, label='Breakout Zone')

    # Strategy signals
    signal_points = df[df['strategy_signal'] == 1]
    if not signal_points.empty:
        plt.scatter(signal_points.index, signal_points['close'] * 0.98,
                   marker='^', color='red', s=100, linewidth=2,
                   edgecolors='black', label='BUY SIGNAL')

    plt.title(f'{symbol} - ML Breakout Strategy Price Chart', fontsize=14, fontweight='bold')
    plt.ylabel('Price (USDT)', fontsize=12)
    plt.legend(loc='upper left')
    plt.grid(True, alpha=0.3)

    # Volume subplot
    plt.subplot(2, 1, 2)
    plt.bar(df.index, df['volume'], color='purple', alpha=0.7)
    plt.ylabel('Volume', fontsize=12)
    plt.xlabel('Date', fontsize=12)
    plt.title('Volume Chart', fontsize=12)
    plt.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(f'{symbol}_strategy_chart.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"📊 Saved price chart: {symbol}_strategy_chart.png")

def create_indicators_chart(df, symbol):
    """Create technical indicators chart"""
    fig, axes = plt.subplots(3, 1, figsize=(15, 12))
    fig.suptitle(f'{symbol} - Technical Indicators', fontsize=16, fontweight='bold')

    # RSI
    axes[0].plot(df.index, df['rsi'], color='purple', linewidth=1, label='RSI')
    axes[0].axhline(y=70, color='red', linestyle='--', alpha=0.7, label='Overbought (70)')
    axes[0].axhline(y=30, color='green', linestyle='--', alpha=0.7, label='Oversold (30)')
    axes[0].axhline(y=50, color='gray', linestyle='-', alpha=0.5, label='Neutral (50)')
    axes[0].set_ylabel('RSI', fontsize=12)
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)
    axes[0].set_title('RSI Indicator')

    # MACD
    axes[1].plot(df.index, df['macd'], color='blue', linewidth=1, label='MACD')
    axes[1].plot(df.index, df['macd_signal'], color='red', linewidth=1, label='Signal')
    axes[1].bar(df.index, df['macd_histogram'],
                color=['green' if x > 0 else 'red' for x in df['macd_histogram']],
                alpha=0.7, label='Histogram')
    axes[1].set_ylabel('MACD', fontsize=12)
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)
    axes[1].set_title('MACD Indicator')

    # Volume ratio and volatility
    axes[2].plot(df.index, df['volume_ratio'], color='orange', linewidth=1, label='Volume Ratio')
    ax2 = axes[2].twinx()
    ax2.plot(df.index, df['volatility_10'] * 100, color='purple', linewidth=1, alpha=0.7, label='10-Day Volatility (%)')
    axes[2].set_ylabel('Volume Ratio', fontsize=12)
    ax2.set_ylabel('Volatility (%)', fontsize=12)
    axes[2].set_xlabel('Date', fontsize=12)
    axes[2].legend(loc='upper left')
    ax2.legend(loc='upper right')
    axes[2].grid(True, alpha=0.3)
    axes[2].set_title('Volume Ratio & Volatility')

    plt.tight_layout()
    plt.savefig(f'{symbol}_indicators_chart.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"📊 Saved indicators chart: {symbol}_indicators_chart.png")

def create_performance_chart(df, symbol):
    """Create performance comparison chart"""
    # Calculate returns
    df = df.copy()
    df['returns'] = df['close'].pct_change()
    df['strategy_returns'] = df['returns'] * df['strategy_signal'].shift(1).fillna(0)

    # Cumulative performance
    df['cum_strategy'] = (1 + df['strategy_returns'].fillna(0)).cumprod()
    df['cum_buy_hold'] = (1 + df['returns'].fillna(0)).cumprod()

    plt.figure(figsize=(15, 8))

    plt.plot(df.index, df['cum_strategy'], color='red', linewidth=2,
            label='Strategy Performance', marker='o', markersize=3, markevery=20)

    plt.plot(df.index, df['cum_buy_hold'], color='blue', linewidth=2,
            label='Buy & Hold', marker='s', markersize=3, markevery=20)

    # Highlight strategy outperform periods
    strategy_outperforms = df[df['cum_strategy'] > df['cum_buy_hold']]
    if not strategy_outperforms.empty:
        plt.fill_between(strategy_outperforms.index,
                        strategy_outperforms['cum_strategy'],
                        strategy_outperforms['cum_buy_hold'],
                        color='green', alpha=0.3, label='Strategy Outperforms')

    plt.title(f'{symbol} - Strategy vs Buy & Hold Performance', fontsize=14, fontweight='bold')
    plt.ylabel('Cumulative Returns (x)', fontsize=12)
    plt.xlabel('Date', fontsize=12)
    plt.legend(loc='upper left')
    plt.grid(True, alpha=0.3)

    # Add performance metrics as text
    final_strategy = df['cum_strategy'].iloc[-1]
    final_buy_hold = df['cum_buy_hold'].iloc[-1]

    plt.text(0.02, 0.98, f'Strategy: {final_strategy:.1f}x', fontsize=11,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="lightcoral"),
            transform=plt.gca().transAxes, verticalalignment='top')

    plt.text(0.02, 0.90, f'Buy&Hold: {final_buy_hold:.1f}x', fontsize=11,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="lightblue"),
            transform=plt.gca().transAxes, verticalalignment='top')

    plt.tight_layout()
    plt.savefig(f'{symbol}_performance_chart.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"📊 Saved performance chart: {symbol}_performance_chart.png")

def print_strategy_metrics(df, symbol):
    """Print key strategy metrics"""
    # Calculate strategy returns
    df = df.copy()
    df['returns'] = df['close'].pct_change()
    df['strategy_returns'] = df['returns'] * df['strategy_signal'].shift(1).fillna(0)

    # Basic metrics
    strategy_returns = df['strategy_returns'].fillna(0)
    buy_hold_returns = df['returns'].fillna(0)

    cum_strategy_return = (1 + strategy_returns).prod() - 1
    cum_buy_hold_return = (1 + buy_hold_returns).prod() - 1

    # Risk metrics
    strategy_volatility = strategy_returns.std() * np.sqrt(365)
    buy_hold_volatility = buy_hold_returns.std() * np.sqrt(365)

    strategy_sharpe = (strategy_returns.mean() * 365) / strategy_volatility if strategy_volatility > 0 else 0
    buy_hold_sharpe = (buy_hold_returns.mean() * 365) / buy_hold_volatility if buy_hold_volatility > 0 else 0

    # Signals and win rate
    total_signals = df['strategy_signal'].sum()
    win_signals = ((df['strategy_signal'].shift(1) == 1) &
                  (df['returns'] > 0)).sum()
    win_rate = win_signals / total_signals if total_signals > 0 else 0

    print("\n" + "="*60)
    print(f"📊 {symbol} STRATEGY METRICS SUMMARY")
    print("="*60)

    print(f"💰 RETURNS: {cum_strategy_return:.1%}")
    print(".1%")
    print(f"💰 RETURNS: {cum_strategy_return:.1%}")

    print("⚠️ RISK METRICS:"    )
    print(f"   Volatility: {strategy_volatility:.2%}")
    print(".2f")
    print(".2f")
    print(".2f")

    print("🎯 STRATEGY STATS:")
    print(f"   Total Signals: {total_signals}")
    print(f"   Win Rate: {win_rate:.1%} ({win_signals}/{total_signals})")
    print(f"   Data Points: {len(df)}")

    print("\n📈 TOP FEATURES USED:")
    features = ['rsi', 'volume_ratio', 'macd', 'volatility_10', 'momentum_10', 'close_to_max_20']
    for i, feature in enumerate(features[:6], 1):
        avg_value = df[feature].tail(30).mean() if feature in df.columns else 0
        print(f"   {i}. {feature.upper()}: {avg_value:.3f}")

    print("\n" + "="*60)

if __name__ == "__main__":
    print("🚀 ML Breakout Strategy Visualizer")
    print("Creating charts for BTCUSDT strategy analysis...")

    try:
        visualize_strategy_simple("BTCUSDT", 200)
        print("✅ Visualization complete! Check generated PNG files:")
        print("   - BTCUSDT_strategy_chart.png (signals & prices)")
        print("   - BTCUSDT_indicators_chart.png (technical analysis)")
        print("   - BTCUSDT_performance_chart.png (returns comparison)")

    except Exception as e:
        print(f"❌ Visualization failed: {e}")
        logger.error(f"Visualization error: {e}")
