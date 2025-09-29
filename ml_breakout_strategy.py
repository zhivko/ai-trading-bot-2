"""
ML-Enhanced Breakout Strategy for Crypto Trading
Combines breakout detection with decision tree learning based on:
Decision Tree + Breakout Strategy for Improved Trading Performance
"""

import pandas as pd
import numpy as np
from sklearn.tree import DecisionTreeClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score
import redis
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import warnings
warnings.filterwarnings('ignore')

from config import get_session, SUPPORTED_SYMBOLS, REDIS_HOST, REDIS_PORT, REDIS_DB
from indicators import _prepare_dataframe
from logging_config import logger

class MLBreakoutTrader:
    """
    ML-enhanced breakout strategy implementation.
    Uses sliding window training with decision tree classifier to filter breakout signals.
    """

    def __init__(self, symbol: str = "BTCUSDT", training_window: int = 80,
                 testing_window: int = 30, max_depth: int = 5,
                 min_samples_split: int = 2, random_state: int = 42):

        self.symbol = symbol
        self.training_window = training_window  # Days for training
        self.testing_window = testing_window    # Days for testing/rebalance
        self.max_depth = max_depth
        self.min_samples_split = min_samples_split
        self.random_state = random_state

        # Redis cache for model persistence
        self.redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

        # Model components
        self.model = None
        self.scaler = None
        self.last_training_date = None
        self.model_performance = {}

        # Risk management (matches trading service: 5% per position, max 20)
        self.risk_per_position = 0.05
        self.max_positions = 20
        self.breakout_period = 50  # 50-day high for breakout

        self.session = get_session()

    def extract_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Extract features for ML model based on crypto trading patterns.
        Features: volume, price gaps, volatility, RSI, MACD, OBV, etc.
        """
        try:
            features_df = pd.DataFrame(index=df.index)

            # Price-based features
            features_df['price_change_pct'] = df['close'].pct_change()
            features_df['high_low_ratio'] = df['high'] / df['low']
            features_df['close_open_ratio'] = df['close'] / df['open']

            # Volume features
            features_df['volume_ma_10'] = df['volume'].rolling(10).mean()
            features_df['volume_ratio'] = df['volume'] / features_df['volume_ma_10']

            # Volatility features
            features_df['returns'] = df['close'].pct_change()
            features_df['volatility_10'] = features_df['returns'].rolling(10).std()
            features_df['volatility_30'] = features_df['returns'].rolling(30).std()

            # Gap features (gap up/down)
            features_df['gap'] = (df['open'] - df['close'].shift(1)) / df['close'].shift(1)

            # Moving averages
            features_df['sma_20'] = df['close'].rolling(20).mean()
            features_df['sma_50'] = df['close'].rolling(50).mean()
            features_df['price_to_sma20'] = df['close'] / features_df['sma_20']
            features_df['price_to_sma50'] = df['close'] / features_df['sma_50']

            # RSI (14-period)
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            features_df['rsi'] = 100 - (100 / (1 + rs))

            # MACD
            exp1 = df['close'].ewm(span=12, adjust=False).mean()
            exp2 = df['close'].ewm(span=26, adjust=False).mean()
            features_df['macd'] = exp1 - exp2
            features_df['macd_signal'] = features_df['macd'].ewm(span=9, adjust=False).mean()
            features_df['macd_histogram'] = features_df['macd'] - features_df['macd_signal']

            # On Balance Volume (OBV)
            obv = [0]
            for i in range(1, len(df)):
                if df['close'].iloc[i] > df['close'].iloc[i-1]:
                    obv.append(obv[-1] + df['volume'].iloc[i])
                elif df['close'].iloc[i] < df['close'].iloc[i-1]:
                    obv.append(obv[-1] - df['volume'].iloc[i])
                else:
                    obv.append(obv[-1])
            features_df['obv'] = obv

            # Momentum indicators
            features_df['momentum_10'] = df['close'] / df['close'].shift(10) - 1
            features_df['momentum_20'] = df['close'] / df['close'].shift(20) - 1

            # Rolling statistics
            features_df['rolling_max_20'] = df['close'].rolling(20).max()
            features_df['rolling_min_20'] = df['close'].rolling(20).min()
            features_df['close_to_max_20'] = df['close'] / features_df['rolling_max_20']
            features_df['close_to_min_20'] = df['close'] / features_df['rolling_min_20']

            # BTC dominance as market proxy (if available)
            try:
                # Would require BTCDOM data integration
                features_df['btc_dominance'] = 0.0  # Placeholder
            except:
                features_df['btc_dominance'] = 0.0

            # Drop NaN values and return
            features_df = features_df.dropna()
            logger.info(f"Extracted {len(features_df.columns)} features for ML model")

            return features_df

        except Exception as e:
            logger.error(f"Error extracting features: {e}")
            return pd.DataFrame()

    def create_labels(self, df: pd.DataFrame, prediction_horizon: int = 10,
                      target_return: float = 0.03) -> pd.Series:
        """
        Create binary labels: 1 if price rises >= target_return within prediction_horizon days, else 0
        """
        try:
            labels = []

            for i in range(len(df)):
                if i >= len(df) - prediction_horizon:
                    labels.append(np.nan)
                    continue

                # Check if price rises >= target_return within next prediction_horizon periods
                future_prices = df['close'].iloc[i+1:i+prediction_horizon+1]
                if len(future_prices) == 0:
                    labels.append(np.nan)
                    continue

                max_future_return = (future_prices.max() - df['close'].iloc[i]) / df['close'].iloc[i]
                label = 1 if max_future_return >= target_return else 0
                labels.append(label)

            labels_series = pd.Series(labels, index=df.index)
            logger.info(f"Created labels: {labels_series.sum()} positive signals out of {labels_series.notna().sum()} valid periods")
            return labels_series

        except Exception as e:
            logger.error(f"Error creating labels: {e}")
            return pd.Series()

    def fetch_historical_data(self, symbol: str, days: int = 180) -> pd.DataFrame:
        """
        Fetch historical crypto data from Bybit API for training/testing.
        """
        try:
            end_time = int(datetime.now().timestamp())
            start_time = end_time - (days * 24 * 60 * 60)  # Convert days to seconds

            # Use 1-hour klines for training (same as strategy source)
            response = self.session.get_kline(
                category="linear",
                symbol=symbol,
                interval="60",  # 1h timeframe
                start=start_time * 1000,
                end=end_time * 1000,
                limit=1000
            )

            if response['retCode'] != 0:
                logger.error(f"Bybit API error: {response}")
                return pd.DataFrame()

            klines_data = []
            for kline in response['result']['list']:
                klines_data.append({
                    'time': int(kline[0]) // 1000,
                    'open': float(kline[1]),
                    'high': float(kline[2]),
                    'low': float(kline[3]),
                    'close': float(kline[4]),
                    'vol': float(kline[5])
                })

            df = pd.DataFrame(klines_data)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            df = df.set_index('time').sort_index()

            # Rename columns to match expected format
            df.rename(columns={'vol': 'volume'}, inplace=True)

            logger.info(f"Fetched {len(df)} klines for {symbol} over {days} days")
            return df

        except Exception as e:
            logger.error(f"Error fetching data for {symbol}: {e}")
            return pd.DataFrame()

    def get_50day_high(self, df: pd.DataFrame) -> float:
        """Calculate current 50-day high for breakout detection"""
        try:
            if len(df) < self.breakout_period:
                return 0.0
            return df['high'].rolling(self.breakout_period).max().iloc[-1]
        except Exception as e:
            logger.error(f"Error calculating 50-day high: {e}")
            return 0.0

    def train_model(self, force_retrain: bool = False) -> bool:
        """
        Train decision tree model using sliding window approach.
        Redevelops every testing_window days.
        """
        try:
            current_date = datetime.now().date()

            # Check if retraining is needed
            if not force_retrain and self.last_training_date:
                days_since_train = (current_date - self.last_training_date).days
                if days_since_train < self.testing_window:
                    logger.info(f"Model training not needed - only {days_since_train} days since last training")
                    return True

            logger.info(f"Starting model training for {self.symbol}")

            # Fetch training data (last N days)
            training_data = self.fetch_historical_data(self.symbol, self.training_window + 30)  # Extra for features

            if training_data.empty:
                logger.error("No training data available")
                return False

            # Extract features
            features_df = self.extract_features(training_data)
            if features_df.empty:
                logger.error("No features extracted from training data")
                return False

            # Create labels
            labels = self.create_labels(training_data)
            if labels.empty:
                logger.error("No labels created from training data")
                return False

            # Align features and labels
            common_index = features_df.index.intersection(labels.index)
            features_df = features_df.loc[common_index]
            labels = labels.loc[common_index]

            # Remove any remaining NaN values
            valid_mask = ~(features_df.isna().any(axis=1) | labels.isna())
            features_df = features_df[valid_mask]
            labels = labels[valid_mask]

            if len(features_df) < 100:  # Need minimum sample size
                logger.error(f"Insufficient training data: {len(features_df)} samples")
                return False

            logger.info(f"Training with {len(features_df)} samples, {labels.sum()} positive labels")

            # Split data for validation
            X_train, X_test, y_train, y_test = train_test_split(
                features_df.values, labels.values,
                test_size=0.2, random_state=self.random_state
            )

            # Scale features
            self.scaler = StandardScaler()
            X_train_scaled = self.scaler.fit_transform(X_train)
            X_test_scaled = self.scaler.transform(X_test)

            # Train decision tree
            self.model = DecisionTreeClassifier(
                max_depth=self.max_depth,
                min_samples_split=self.min_samples_split,
                random_state=self.random_state
            )

            self.model.fit(X_train_scaled, y_train)

            # Evaluate on test set
            y_pred = self.model.predict(X_test_scaled)
            accuracy = accuracy_score(y_test, y_pred)
            report = classification_report(y_test, y_pred, output_dict=True)

            # Handle case where class '1' might not be in predictions (imbalanced data)
            class_1_metrics = report.get('1', report.get('1.0', {}))
            if not class_1_metrics:
                # If no positive class predictions, use macro averages
                class_1_metrics = {
                    'precision': report.get('macro avg', {}).get('precision', 0.0),
                    'recall': report.get('macro avg', {}).get('recall', 0.0),
                    'f1-score': report.get('macro avg', {}).get('f1-score', 0.0)
                }

            self.model_performance = {
                'accuracy': accuracy,
                'precision': class_1_metrics.get('precision', 0.0),
                'recall': class_1_metrics.get('recall', 0.0),
                'f1_score': class_1_metrics.get('f1-score', 0.0),
                'training_samples': len(X_train),
                'test_samples': len(X_test),
                'trained_at': current_date.isoformat()
            }

            # Cache model
            self._save_model_to_cache()

            # Update training timestamp
            self.last_training_date = current_date

            logger.info(f"Model trained for {self.symbol}: accuracy={accuracy:.3f}, precision={self.model_performance['precision']:.3f}, recall={self.model_performance['recall']:.3f}")
            return True

        except Exception as e:
            logger.error(f"Error training model: {e}")
            return False

    def predict_signal(self, df: pd.DataFrame) -> int:
        """
        Generate prediction for current market conditions.
        Returns 1 for buy signal, 0 for no signal.
        """
        try:
            if self.model is None or self.scaler is None:
                if not self._load_model_from_cache():
                    logger.warning("No trained model available for prediction")
                    return 0

            # Extract current features
            features_df = self.extract_features(df)
            if features_df.empty or len(features_df) == 0:
                return 0

            # Get latest feature vector
            latest_features = features_df.iloc[-1:].values

            # Scale features
            features_scaled = self.scaler.transform(latest_features)

            # Make prediction
            prediction = self.model.predict(features_scaled)[0]

            # Get prediction probability for confidence
            probabilities = self.model.predict_proba(features_scaled)[0]
            confidence = probabilities[int(prediction)]

            logger.info(f"ML prediction: {prediction}, confidence: {confidence:.3f}")

            return int(prediction)

        except Exception as e:
            logger.error(f"Error generating prediction: {e}")
            return 0

    def should_enter_trade(self, sp500_proxy_price: float = None) -> bool:
        """
        Main strategy logic: Breakout + ML filter.
        Based on: 50-day high breakout + ML prediction + market conditions.
        """
        try:
            # Get recent market data (last 100 days for features)
            recent_data = self.fetch_historical_data(self.symbol, 100)

            if recent_data.empty:
                logger.warning("No recent market data for signal generation")
                return False

            # Check breakout condition: Price > 50-day high
            current_price = recent_data['close'].iloc[-1]
            day_50_high = self.get_50day_high(recent_data)

            breakout_condition = current_price > day_50_high
            logger.info(f"Breakout check: current_price={current_price:.2f}, 50day_high={day_50_high:.2f}")

            # Market condition proxy (SPY equivalent for crypto)
            # For crypto, we use BTC dominance or simple threshold
            market_condition = sp500_proxy_price is None or sp500_proxy_price > 0.95  # Simplistic

            # ML prediction
            ml_prediction = self.predict_signal(recent_data)

            # Combined signal
            signal = breakout_condition and (ml_prediction == 1) and market_condition

            logger.info(f"Signal components - Breakout: {breakout_condition}, ML: {ml_prediction == 1}, Market: {market_condition}")
            logger.info(f"Final signal: {'BUY' if signal else 'HOLD'}")

            return signal

        except Exception as e:
            logger.error(f"Error in signal generation: {e}")
            return False

    def _save_model_to_cache(self):
        """Save trained model and scaler to Redis cache"""
        try:
            cache_key = f"ml_breakout:{self.symbol}"

            # Convert model and scaler to JSON-serializable format
            # For demo purposes - in production would use pickle/joblib
            cache_data = {
                'performance': self.model_performance,
                'last_trained': self.last_training_date.isoformat() if self.last_training_date else None,
                'symbol': self.symbol,
                'max_depth': self.max_depth,
                'training_window': self.training_window
            }

            self.redis.set(cache_key, json.dumps(cache_data))
            logger.info(f"Model cached for {self.symbol}")

        except Exception as e:
            logger.error(f"Error caching model: {e}")

    def _load_model_from_cache(self) -> bool:
        """Load model from cache if available"""
        try:
            cache_key = f"ml_breakout:{self.symbol}"
            cached_data = self.redis.get(cache_key)

            if cached_data:
                # In full implementation, would load pickled model
                # For demo, we just reload performance data
                data = json.loads(cached_data)
                self.model_performance = data.get('performance', {})

                # Force retrain for now (full implementation would load pickled model)
                return False  # Will retrain

            return False

        except Exception as e:
            logger.error(f"Error loading model from cache: {e}")
            return False

    def get_model_performance(self) -> Dict:
        """Get current model performance metrics"""
        return self.model_performance

    def reset_model(self):
        """Reset model state for fresh training"""
        self.model = None
        self.scaler = None
        self.last_training_date = None
        self.model_performance = {}

        # Clear cache
        cache_key = f"ml_breakout:{self.symbol}"
        self.redis.delete(cache_key)

        logger.info(f"Model reset for {self.symbol}")
