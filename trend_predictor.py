#!/usr/bin/env python3
"""
Advanced Trend Predictor for BTC UP/DOWN Markets.

Uses real BTC spot price from Binance to predict market outcome.
The BTC 5min UP/DOWN market resolves based on whether BTC spot price
is HIGHER (UP wins) or LOWER (DOWN wins) at close vs. open.

By tracking the actual spot price, we know which side is CURRENTLY winning
and can estimate the probability of a reversal based on:
  1. BTC spot price delta from market open
  2. Time remaining (less time = less chance of reversal)
  3. Volatility in the current window
  4. Historical market outcomes
"""

import time
import math
import logging
from collections import deque
from typing import Optional, Tuple, Dict

logger = logging.getLogger(__name__)


class TrendPredictor:
    """Predicts BTC UP/DOWN market outcome using real spot price data."""

    def __init__(self):
        # === Spot price tracking ===
        self.market_open_price: Optional[float] = None   # BTC price at market open
        self.current_spot_price: Optional[float] = None   # Latest BTC spot price
        self.spot_history: deque = deque(maxlen=600)       # (timestamp, price) tuples
        self.spot_fetch_count: int = 0
        self.last_spot_fetch_time: float = 0.0

        # === Historical market outcomes ===
        self.market_history: deque = deque(maxlen=100)    # list of dicts
        self.consecutive_up: int = 0
        self.consecutive_down: int = 0
        self.total_up: int = 0
        self.total_down: int = 0

        # === Prediction state ===
        self.current_prediction: Optional[str] = None     # 'UP' or 'DOWN'
        self.prediction_confidence: float = 0.0           # 0.0 - 1.0
        self.prediction_reason: str = ''

        # === Volatility tracking ===
        self.window_high: Optional[float] = None
        self.window_low: Optional[float] = None
        self.price_changes: deque = deque(maxlen=300)     # Recent price changes

        # === Configuration ===
        self.min_delta_for_signal = 0.5     # Min $ delta to consider significant
        self.high_confidence_delta = 15.0   # $ delta for high confidence
        self.endgame_seconds = 90           # When endgame prediction kicks in
        self.critical_seconds = 30          # When prediction is near-certain

    def reset_for_new_market(self):
        """Reset state for a new market window."""
        self.market_open_price = None
        self.current_spot_price = None
        self.spot_history.clear()
        self.price_changes.clear()
        self.window_high = None
        self.window_low = None
        self.current_prediction = None
        self.prediction_confidence = 0.0
        self.prediction_reason = ''

    def set_market_open_price(self, price: float):
        """Set the BTC spot price at market open."""
        self.market_open_price = price
        self.window_high = price
        self.window_low = price
        logger.info(f"📊 Market open BTC price: ${price:,.2f}")

    def update_spot_price(self, price: float, timestamp: Optional[float] = None):
        """Update with latest BTC spot price."""
        ts = timestamp or time.time()
        self.current_spot_price = price
        self.spot_history.append((ts, price))
        self.spot_fetch_count += 1
        self.last_spot_fetch_time = ts

        # Track window high/low
        if self.window_high is None or price > self.window_high:
            self.window_high = price
        if self.window_low is None or price < self.window_low:
            self.window_low = price

        # Track price changes for volatility
        if len(self.spot_history) >= 2:
            prev_price = self.spot_history[-2][1]
            self.price_changes.append(price - prev_price)

        # Auto-set open price if not set
        if self.market_open_price is None:
            self.set_market_open_price(price)

    def record_market_outcome(self, outcome: str, open_price: float, close_price: float):
        """Record a completed market outcome for future predictions."""
        delta = close_price - open_price
        self.market_history.append({
            'outcome': outcome,
            'open_price': open_price,
            'close_price': close_price,
            'delta': delta,
            'timestamp': time.time()
        })

        if outcome == 'UP':
            self.consecutive_up += 1
            self.consecutive_down = 0
            self.total_up += 1
        else:
            self.consecutive_down += 1
            self.consecutive_up = 0
            self.total_down += 1

    def get_volatility(self) -> float:
        """Estimate current BTC volatility (std dev of price changes in $)."""
        if len(self.price_changes) < 5:
            return 10.0  # Default assumption: BTC moves ~$10 per tick
        changes = list(self.price_changes)
        mean = sum(changes) / len(changes)
        variance = sum((c - mean) ** 2 for c in changes) / len(changes)
        return max(0.1, math.sqrt(variance))

    def get_window_range(self) -> float:
        """Get the price range (high - low) in the current window."""
        if self.window_high is not None and self.window_low is not None:
            return self.window_high - self.window_low
        return 0.0

    def predict(self, time_to_close: Optional[float] = None) -> Tuple[Optional[str], float, str]:
        """
        Predict market outcome.

        Returns:
            (predicted_side, confidence, reason)
            predicted_side: 'UP' or 'DOWN' or None
            confidence: 0.0 - 1.0
            reason: human-readable explanation
        """
        if self.market_open_price is None or self.current_spot_price is None:
            self.current_prediction = None
            self.prediction_confidence = 0.0
            self.prediction_reason = 'No spot data'
            return None, 0.0, 'No spot data'

        delta = self.current_spot_price - self.market_open_price
        abs_delta = abs(delta)
        direction = 'UP' if delta >= 0 else 'DOWN'
        volatility = self.get_volatility()

        # === BASE CONFIDENCE from price delta ===
        # Higher delta relative to volatility = higher confidence
        if abs_delta < self.min_delta_for_signal:
            # Very small delta — essentially a coin flip
            base_conf = 0.50 + (abs_delta / self.min_delta_for_signal) * 0.05
        elif abs_delta < self.high_confidence_delta:
            # Moderate delta — growing confidence
            ratio = abs_delta / self.high_confidence_delta
            base_conf = 0.55 + ratio * 0.25  # 0.55 -> 0.80
        else:
            # Large delta — high confidence
            base_conf = min(0.95, 0.80 + (abs_delta - self.high_confidence_delta) / 50.0)

        # === TIME BOOST: Less time = more certain ===
        # With 300s left, 0% boost. With 30s left, up to 15% boost.
        # With 10s left, up to 20% boost.
        time_boost = 0.0
        if time_to_close is not None:
            if time_to_close < self.critical_seconds:
                # Critical zone: price is very unlikely to reverse
                time_boost = 0.20 * (1.0 - time_to_close / self.critical_seconds)
            elif time_to_close < self.endgame_seconds:
                # Endgame zone: increasing confidence
                time_boost = 0.10 * (1.0 - time_to_close / self.endgame_seconds)

        # === VOLATILITY ADJUSTMENT ===
        # High volatility relative to delta = less confident
        if volatility > 0 and abs_delta > 0:
            # How many standard deviations is the delta?
            z_score = abs_delta / volatility
            if z_score < 1.0:
                vol_penalty = (1.0 - z_score) * 0.10  # Up to 10% penalty
            else:
                vol_penalty = 0.0
        else:
            vol_penalty = 0.0

        # === MOMENTUM CHECK ===
        # Is price moving TOWARD or AWAY from open?
        momentum_boost = 0.0
        if len(self.spot_history) >= 10:
            recent = [p for _, p in list(self.spot_history)[-10:]]
            early = [p for _, p in list(self.spot_history)[-20:-10]] if len(self.spot_history) >= 20 else recent[:5]
            recent_avg = sum(recent) / len(recent)
            early_avg = sum(early) / len(early)
            recent_move = recent_avg - early_avg

            # If recent move is in SAME direction as delta, boost confidence
            if (delta > 0 and recent_move > 0) or (delta < 0 and recent_move < 0):
                momentum_boost = min(0.05, abs(recent_move) / max(abs_delta, 1.0) * 0.05)
            elif (delta > 0 and recent_move < 0) or (delta < 0 and recent_move > 0):
                # Moving against the delta — reduce confidence
                momentum_boost = -min(0.10, abs(recent_move) / max(abs_delta, 1.0) * 0.10)

        # === HISTORICAL PATTERN ADJUSTMENT ===
        # If we've seen 3+ consecutive outcomes in one direction, slight mean-reversion bias
        history_adj = 0.0
        if self.consecutive_up >= 3 and direction == 'UP':
            history_adj = -0.02  # Slight penalty for continuing streak
        elif self.consecutive_down >= 3 and direction == 'DOWN':
            history_adj = -0.02

        # === COMBINE ALL FACTORS ===
        confidence = base_conf + time_boost - vol_penalty + momentum_boost + history_adj
        confidence = max(0.50, min(0.98, confidence))  # Clamp to [0.50, 0.98]

        # Build reason string
        reason_parts = [
            f'BTC ${self.current_spot_price:,.1f}',
            f'Δ${delta:+,.1f}',
            f'conf={confidence:.0%}'
        ]
        if time_to_close is not None:
            reason_parts.append(f'{time_to_close:.0f}s left')
        if time_boost > 0.01:
            reason_parts.append(f'time+{time_boost:.0%}')
        if momentum_boost != 0:
            reason_parts.append(f'mom{"+" if momentum_boost > 0 else ""}{momentum_boost:.0%}')

        reason = ' | '.join(reason_parts)

        self.current_prediction = direction
        self.prediction_confidence = confidence
        self.prediction_reason = reason

        return direction, confidence, reason

    def should_endgame_position(self, time_to_close: Optional[float] = None) -> Tuple[bool, Optional[str], float]:
        """
        Check if we should aggressively position for endgame.

        Returns:
            (should_act, side, confidence)
            should_act: True if we should take action
            side: 'UP' or 'DOWN'
            confidence: prediction confidence
        """
        if time_to_close is None or time_to_close > self.endgame_seconds:
            return False, None, 0.0

        direction, confidence, _ = self.predict(time_to_close)
        if direction is None:
            return False, None, 0.0

        # Endgame thresholds:
        # 90-60s: need 70%+ confidence
        # 60-30s: need 65%+ confidence  
        # <30s:   need 60%+ confidence (almost always act)
        if time_to_close < self.critical_seconds:
            threshold = 0.60
        elif time_to_close < 60:
            threshold = 0.65
        else:
            threshold = 0.70

        should_act = confidence >= threshold
        return should_act, direction, confidence

    def get_position_sizing_multiplier(self, time_to_close: Optional[float] = None) -> float:
        """
        Get a position sizing multiplier based on prediction confidence.
        Higher confidence + less time = larger positions.

        Returns: multiplier 0.5 - 3.0
        """
        if self.prediction_confidence < 0.55:
            return 0.5  # Low confidence — small positions

        # Scale from 1.0 at 55% to 3.0 at 95% confidence
        conf_factor = (self.prediction_confidence - 0.55) / 0.40  # 0 to 1
        conf_factor = min(1.0, conf_factor)

        # Time factor: closer to end = more aggressive
        time_factor = 1.0
        if time_to_close is not None and time_to_close < self.endgame_seconds:
            time_factor = 1.0 + (1.0 - time_to_close / self.endgame_seconds) * 0.5

        multiplier = 1.0 + conf_factor * 2.0 * time_factor
        return min(3.0, multiplier)

    def get_status(self) -> Dict:
        """Get current predictor status for UI/logging."""
        delta = None
        if self.market_open_price and self.current_spot_price:
            delta = self.current_spot_price - self.market_open_price

        return {
            'open_price': self.market_open_price,
            'spot_price': self.current_spot_price,
            'delta': delta,
            'prediction': self.current_prediction,
            'confidence': self.prediction_confidence,
            'reason': self.prediction_reason,
            'volatility': self.get_volatility() if len(self.price_changes) >= 5 else None,
            'window_range': self.get_window_range(),
            'history_count': len(self.market_history),
            'streak': f"UP×{self.consecutive_up}" if self.consecutive_up > 0 else f"DN×{self.consecutive_down}",
            'fetches': self.spot_fetch_count,
        }


async def fetch_btc_spot_binance(session) -> Optional[float]:
    """Fetch BTC spot price from Binance (free, no API key, fast)."""
    try:
        url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
        async with session.get(url, timeout=2.0) as resp:
            if resp.status == 200:
                data = await resp.json()
                return float(data['price'])
    except Exception as e:
        logger.debug(f"Binance fetch error: {e}")
    return None


async def fetch_btc_spot_coingecko(session) -> Optional[float]:
    """Fetch BTC spot price from CoinGecko (backup, rate-limited)."""
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        async with session.get(url, timeout=3.0) as resp:
            if resp.status == 200:
                data = await resp.json()
                return float(data['bitcoin']['usd'])
    except Exception as e:
        logger.debug(f"CoinGecko fetch error: {e}")
    return None


async def fetch_btc_spot_coinbase(session) -> Optional[float]:
    """Fetch BTC spot price from Coinbase (backup)."""
    try:
        url = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
        async with session.get(url, timeout=3.0) as resp:
            if resp.status == 200:
                data = await resp.json()
                return float(data['data']['amount'])
    except Exception as e:
        logger.debug(f"Coinbase fetch error: {e}")
    return None


async def fetch_btc_spot(session) -> Optional[float]:
    """
    Fetch BTC spot price with fallback chain:
    1. Binance (fastest, most reliable)
    2. Coinbase (backup)
    3. CoinGecko (last resort)
    """
    price = await fetch_btc_spot_binance(session)
    if price:
        return price

    price = await fetch_btc_spot_coinbase(session)
    if price:
        return price

    price = await fetch_btc_spot_coingecko(session)
    if price:
        return price

    return None


def fetch_btc_spot_sync() -> Optional[float]:
    """Synchronous version of BTC spot price fetch (for testing)."""
    import urllib.request
    import json

    try:
        url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            return float(data['price'])
    except Exception:
        pass

    try:
        url = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            return float(data['data']['amount'])
    except Exception:
        pass

    return None
