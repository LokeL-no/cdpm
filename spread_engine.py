#!/usr/bin/env python3
"""
SpreadEngine – Log-Spread Z-Score Engine with Beta-Weighting

Professional-grade spread analysis for delta-neutral arbitrage.

Core Concepts:
  - Log-Spread:  S = ln(Price_UP) - β·ln(Price_DOWN)
    Using log-prices ensures percentage accuracy across price levels.
  - Beta (β):    A hedge-ratio coefficient so that a 1 % move in DOWN
                 produces an equivalent dollar-P&L offset in UP.
                 Estimated via rolling OLS on log-returns.
  - Z-Score:     z = (S − μ_S) / σ_S
                 Where μ_S and σ_S are the rolling mean and std-dev
                 of the log-spread over `lookback` ticks.
  - Bollinger Bands:  upper = μ + k·σ,  lower = μ − k·σ
                 Equivalent to z-score thresholds when k equals the
                 entry z-threshold (default 2.0).

Signal Logic (evaluate_spread_entry):
  z > +entry_z  → SHORT_UP_LONG_DOWN  (spread too wide)
  z < −entry_z  → LONG_UP_SHORT_DOWN  (spread too narrow / inverted)
  z crosses 0   → EXIT_ALL            (mean reverted)
  Hysteresis prevents rapid flipping near thresholds.

Position Delta Scaling (calculate_position_delta):
  |z| ∈ [0, entry_z)        →  0 %   (no position)
  |z| = entry_z (2.0)       → 20 %
  Each +0.5 in |z|          → +20 %
  |z| ≥ max_z (4.0)         → 100 %
  Scale down symmetrically as z returns toward 0.
"""

import math
from collections import deque
from typing import Optional, Tuple


# ── Signal constants ──────────────────────────────────────────────
SIGNAL_NONE = "NONE"
SIGNAL_SHORT_UP_LONG_DOWN = "SHORT_UP_LONG_DOWN"
SIGNAL_LONG_UP_SHORT_DOWN = "LONG_UP_SHORT_DOWN"
SIGNAL_EXIT_ALL = "EXIT_ALL"


class SpreadEngine:
    """Rolling log-spread Z-score engine with beta-weighting."""

    def __init__(
        self,
        lookback: int = 200,
        beta_lookback: int = 60,
        entry_z: float = 2.0,
        exit_z: float = 0.0,
        max_z: float = 4.0,
        hysteresis: float = 0.2,
        bb_k: float = 2.0,
    ):
        # ── Lookback windows ──
        self.lookback = lookback            # ticks for spread mean/std
        self.beta_lookback = beta_lookback   # ticks for beta estimation

        # ── Signal thresholds ──
        self.entry_z = entry_z               # |z| to open new position
        self.exit_z = exit_z                 # z near 0 → exit
        self.max_z = max_z                   # z for 100 % delta
        self.hysteresis = hysteresis         # dead-zone around thresholds
        self.bb_k = bb_k                     # Bollinger Band width (= entry_z)

        # ── Rolling data stores ──
        self._log_up: deque = deque(maxlen=lookback + 1)
        self._log_down: deque = deque(maxlen=lookback + 1)
        self._spreads: deque = deque(maxlen=lookback)

        # ── Rolling sums for O(1) mean / variance ──
        self._sum_s: float = 0.0            # Σ spread
        self._sum_s2: float = 0.0           # Σ spread²
        self._n: int = 0                    # count inside window

        # ── Beta estimation rolling buffers ──
        self._ret_up: deque = deque(maxlen=beta_lookback)
        self._ret_down: deque = deque(maxlen=beta_lookback)

        # ── Current state ──
        self.beta: float = 1.0              # hedge-ratio
        self.current_spread: float = 0.0
        self.z_score: float = 0.0
        self.spread_mean: float = 0.0
        self.spread_std: float = 0.0
        self.bb_upper: float = 0.0
        self.bb_lower: float = 0.0

        # ── Previous state (for hysteresis / cross detection) ──
        self._prev_z: float = 0.0
        self._prev_signal: str = SIGNAL_NONE
        self._ticks: int = 0

        # ── History for UI charting (last 60 ticks) ──
        self._z_history: deque = deque(maxlen=60)
        self._spread_history: deque = deque(maxlen=60)
        self._bb_upper_history: deque = deque(maxlen=60)
        self._bb_lower_history: deque = deque(maxlen=60)
        self._signal_history: deque = deque(maxlen=60)

    # ──────────────────────────────────────────────────────────────
    #  PUBLIC API
    # ──────────────────────────────────────────────────────────────

    def update(self, price_up: float, price_down: float) -> dict:
        """
        Feed a new price tick.  Returns a dict with all computed metrics:
          z_score, spread, spread_mean, spread_std, beta,
          bb_upper, bb_lower, signal, position_delta_pct
        """
        # Guard against invalid prices
        if price_up <= 0 or price_down <= 0:
            return self._snapshot()

        log_up = math.log(price_up)
        log_down = math.log(price_down)

        # ── 1. Update beta from log-returns ──
        if len(self._log_up) >= 1:
            r_up = log_up - self._log_up[-1]
            r_down = log_down - self._log_down[-1]
            self._ret_up.append(r_up)
            self._ret_down.append(r_down)
            self._update_beta()

        self._log_up.append(log_up)
        self._log_down.append(log_down)

        # ── 2. Compute beta-weighted log-spread ──
        spread = log_up - self.beta * log_down
        self.current_spread = spread

        # ── 3. Rolling mean / std (Welford-style) ──
        self._push_spread(spread)

        if self._n >= 2:
            self.spread_mean = self._sum_s / self._n
            variance = (self._sum_s2 / self._n) - (self.spread_mean ** 2)
            # clamp floating-point noise
            self.spread_std = math.sqrt(max(0.0, variance))
        else:
            self.spread_mean = spread
            self.spread_std = 0.0

        # ── 4. Z-Score ──
        if self.spread_std > 1e-12:
            self.z_score = (spread - self.spread_mean) / self.spread_std
        else:
            self.z_score = 0.0

        # ── 5. Bollinger Bands on the spread ──
        self.bb_upper = self.spread_mean + self.bb_k * self.spread_std
        self.bb_lower = self.spread_mean - self.bb_k * self.spread_std

        self._ticks += 1
        result = self._snapshot()
        self._prev_z = self.z_score
        return result

    def evaluate_spread_entry(self) -> str:
        """
        Generate a trading signal from the current z-score.

        Hysteresis logic:
          - To ENTER a new position the z must exceed ±entry_z.
          - Once in a position, z must cross back past
            ±(entry_z − hysteresis) before we consider the signal
            "stale" and allow EXIT_ALL near 0.
          - EXIT_ALL fires when z crosses the zero line
            (changes sign) while not beyond the entry threshold.

        Returns one of:
          SIGNAL_SHORT_UP_LONG_DOWN  (z >> 0, UP overpriced)
          SIGNAL_LONG_UP_SHORT_DOWN  (z << 0, DOWN overpriced)
          SIGNAL_EXIT_ALL            (spread normalised)
          SIGNAL_NONE                (no action)
        """
        z = self.z_score
        prev = self._prev_z

        # Need minimum data before generating signals
        if self._ticks < max(20, self.lookback // 4):
            self._prev_signal = SIGNAL_NONE
            return SIGNAL_NONE

        signal = SIGNAL_NONE

        # ── Entry signals ──
        if z > self.entry_z + self.hysteresis:
            signal = SIGNAL_SHORT_UP_LONG_DOWN
        elif z < -(self.entry_z + self.hysteresis):
            signal = SIGNAL_LONG_UP_SHORT_DOWN

        # ── Exit signal: z crossed zero ──
        elif self._prev_signal in (SIGNAL_SHORT_UP_LONG_DOWN, SIGNAL_LONG_UP_SHORT_DOWN):
            crossed_zero = (prev > 0 and z <= 0) or (prev < 0 and z >= 0)
            near_zero = abs(z) < (self.entry_z - self.hysteresis)
            if crossed_zero or near_zero:
                signal = SIGNAL_EXIT_ALL

        # ── Persist previous signal if no new one ──
        if signal == SIGNAL_NONE and self._prev_signal != SIGNAL_NONE:
            # Still in a trade – keep the direction unless exit triggered
            signal = self._prev_signal

        self._prev_signal = signal
        return signal

    def calculate_position_delta(self) -> float:
        """
        Step-wise position sizing based on z-score extremity.

        Mapping (absolute z → delta %):
          |z| < entry_z (2.0)   →   0 %
          |z| = 2.0             →  20 %
          |z| = 2.5             →  40 %
          |z| = 3.0             →  60 %
          |z| = 3.5             →  80 %
          |z| ≥ 4.0             → 100 %

        The delta is always symmetric around zero: it tells
        how big the long/short legs should be relative to
        the maximum allowed notional.
        """
        az = abs(self.z_score)
        if az < self.entry_z:
            return 0.0

        # Steps of 0.5 above entry_z, each worth 20 pp
        steps = (az - self.entry_z) / 0.5
        delta_pct = min(100.0, 20.0 + steps * 20.0)
        return round(delta_pct, 1)

    @property
    def is_ready(self) -> bool:
        """True once we have enough data for meaningful z-scores."""
        return self._ticks >= max(20, self.lookback // 4)

    @property
    def bb_width(self) -> float:
        """Bollinger Band width (upper − lower)."""
        return self.bb_upper - self.bb_lower

    # ──────────────────────────────────────────────────────────────
    #  INTERNALS
    # ──────────────────────────────────────────────────────────────

    def _push_spread(self, s: float):
        """Push a new spread value, evicting the oldest if full."""
        if self._n >= self.lookback:
            old = self._spreads[0]
            self._sum_s -= old
            self._sum_s2 -= old * old
            self._n -= 1
        self._spreads.append(s)
        self._sum_s += s
        self._sum_s2 += s * s
        self._n += 1

    def _update_beta(self):
        """
        Estimate beta via rolling OLS on log-returns.

        β = Cov(r_up, r_down) / Var(r_down)

        This ensures the hedge ratio accounts for the fact that
        UP and DOWN may not move cent-for-cent.  Without beta,
        the portfolio is NOT truly delta-neutral.
        """
        n = len(self._ret_down)
        if n < 10:
            return  # not enough data

        mean_up = sum(self._ret_up) / n
        mean_down = sum(self._ret_down) / n

        cov = 0.0
        var_down = 0.0
        for r_u, r_d in zip(self._ret_up, self._ret_down):
            d_u = r_u - mean_up
            d_d = r_d - mean_down
            cov += d_u * d_d
            var_down += d_d * d_d

        if var_down > 1e-18:
            raw_beta = cov / var_down
            # Clamp to reasonable range and smooth
            raw_beta = max(0.2, min(3.0, raw_beta))
            # Exponential smoothing (alpha = 0.05)
            self.beta = 0.95 * self.beta + 0.05 * raw_beta

    def _snapshot(self) -> dict:
        """Current state as a dict."""
        signal = self.evaluate_spread_entry()
        delta = self.calculate_position_delta()

        # Append to history buffers
        self._z_history.append(round(self.z_score, 3))
        self._spread_history.append(round(self.current_spread, 5))
        self._bb_upper_history.append(round(self.bb_upper, 5))
        self._bb_lower_history.append(round(self.bb_lower, 5))
        self._signal_history.append(signal)

        return {
            'z_score': round(self.z_score, 4),
            'spread': round(self.current_spread, 6),
            'spread_mean': round(self.spread_mean, 6),
            'spread_std': round(self.spread_std, 6),
            'beta': round(self.beta, 4),
            'bb_upper': round(self.bb_upper, 6),
            'bb_lower': round(self.bb_lower, 6),
            'bb_width': round(self.bb_width, 6),
            'signal': signal,
            'position_delta_pct': delta,
            'ticks': self._ticks,
            'is_ready': self.is_ready,
            'z_history': list(self._z_history),
            'spread_history': list(self._spread_history),
            'bb_upper_history': list(self._bb_upper_history),
            'bb_lower_history': list(self._bb_lower_history),
            'signal_history': list(self._signal_history),
        }

    def get_state(self) -> dict:
        """Alias for external callers."""
        return self._snapshot()
