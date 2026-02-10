#!/usr/bin/env python3
"""
HFT Mean-Reversion Strategy v5 — Smart Position Weighting for Polymarket

Core Principle:  NEVER buy UP and DOWN simultaneously.
  Instead, buy one side when it's cheap (oversold), then hedge by
  buying the other side when IT becomes cheap. This works because
  prices fluctuate within a 15-minute window — buying at different
  dip points gives a combined cost well below break-even.

v5 Upgrades:
  1. MOMENTUM FILTER:  Don't buy falling knives. A side that's in a
     sustained downtrend (negative momentum + trend_direction=-1) is
     blocked from entry unless Z-score is extreme (<-2.5) or a
     reversal is confirmed (EMA-5 crossing above EMA-20).

  2. REVERSAL DETECTION:  Composite reversal_score (0-100) based on:
     - EMA-5 crossing above EMA-20 (30 pts, fades over 15 ticks)
     - Positive momentum after negative period (25 pts)
     - Price near session low but bouncing (25 pts)
     - Consecutive up ticks (20 pts)
     Confirmed reversals get position size boost (1.5x).

  3. PROBABILITY-AWARE SIZING:  Binary market price ≈ probability.
     Kelly fraction is scaled by probability zone:
     - <20% (longshot): 30% of Kelly — cheap but likely to lose
     - 35-65% (uncertain): 100% Kelly — best arb zone
     - >75% (expensive): 40% of Kelly — poor value
     Prevents over-committing to extreme probabilities.

  4. BUDGET TRANCHES & RESERVE:
     - 35% of budget always reserved for hedging
     - Entries capped to 65% of budget, in 5 tranches
     - Max 45% budget on any single side
     This prevents budget exhaustion before hedge positions are built.

  5. PRE-EMPTIVE HEDGING:  Small hedge trades start at 8% delta
     (not 25%). Buys 30% of the deficit at good prices before
     the position becomes critically unbalanced.

  6. ENTRY QUALITY SCORING:  Multi-factor quality score (0-100):
     - Z-score depth (40 pts)
     - Reversal confirmation (25 pts)
     - Probability zone (20 pts)
     - Balance improvement (15 pts)
     - Momentum quality (±10 pts)
     Best candidate wins when both sides signal.

  7. MGP PROTECTION:  Entries that would drop MGP by >$3 are blocked.
     Hedge prices checked against max_price_for_positive_mgp to
     prevent buying hedges that make the overall position worse.

Binary Market Rules:
  - UP + DOWN = $1.00 at resolution
  - Bot NEVER sells — only buys
  - Break-even combined avg = 1/1.015 ≈ $0.9852
  - Profit = min(qty_up, qty_down) - total_cost × 1.015

Indicators:
  1. Z-Score (Mean Reversion):
     - Per-side EMA-5 / EMA-20 / EMA-50
     - Z = (price - EMA_50) / std_dev
     - Z < -0.8 → oversold → BUY signal (IF momentum confirms)
     - Z > +0.8 → overbought → avoid

  2. ATR (Average True Range):
     - Measures volatility per tick
     - Used for dynamic entry thresholds

  3. Momentum (Rate of Change):
     - 10-tick rate of change
     - Negative + strong trend = falling knife (blocked)
     - Positive after negative = potential reversal

  4. Kelly Criterion (Position Sizing):
     - f* = (p·b − q) / b
     - Scaled by risk_factor × probability_zone_scale
     - Capped by budget tranche size

  5. Exposure / Risk Module:
     - Pre-emptive hedging at 8% delta
     - Standard hedging at 15% delta
     - Urgent hedging at 35% delta
     - Forced hedging at 55% delta

Algorithm:
  1. WARMUP (20 ticks): Build EMA/ATR/momentum baselines
  2. Each tick:
     a. Update per-side indicators (EMA-5/20/50, Z-score, ATR, momentum, reversal)
     b. Run pre-emptive hedge check → small balancing trades early
     c. Run exposure check → determine priority
     d. If HEDGING needed: buy deficit side with smart pricing
     e. Else: score entry candidates, filter falling knives
     f. Execute best candidate with urgency scaling
     g. Verify MGP impact before committing
  3. Cooldown: 2s between trades
"""

import math
import time
from typing import Optional, Dict, Tuple, List
from collections import deque
from datetime import datetime, timezone

from spread_engine import (
    SpreadEngine,
    SIGNAL_NONE,
    SIGNAL_SHORT_UP_LONG_DOWN,
    SIGNAL_LONG_UP_SHORT_DOWN,
    SIGNAL_EXIT_ALL,
)
from execution_simulator import ExecutionSimulator, FillResult

# ── Constants ──
FEE_RATE = 0.015
FEE_MULT = 1.0 + FEE_RATE       # 1.015
BREAK_EVEN = 1.0 / FEE_MULT     # ~0.9852


class SideTracker:
    """
    Tracks EMA-5/20/50, Z-Score, ATR, Momentum, Trend, and Reversal
    for one side (UP or DOWN). Uses mid-price (bid+ask)/2.
    """

    def __init__(self):
        self.ema_5: Optional[float] = None
        self.ema_20: Optional[float] = None
        self.ema_50: Optional[float] = None
        self.prices: deque = deque(maxlen=60)
        self.tr_history: deque = deque(maxlen=14)
        self.atr: float = 0.0
        self.z_score: float = 0.0
        self.std_dev: float = 0.001
        self.prev_price: Optional[float] = None
        self.tick_count: int = 0
        self.session_low: float = 999.0
        self.session_high: float = 0.0

        # ── Momentum & Trend tracking ──
        self.momentum: float = 0.0           # Rate of change over last N ticks
        self.momentum_history: deque = deque(maxlen=20)
        self.trend_strength: float = 0.0     # 0=no trend, 1=strong trend
        self.trend_direction: int = 0         # +1 up, -1 down, 0 neutral
        self.is_reversing: bool = False       # EMA-5 crossing EMA-20
        self.reversal_score: float = 0.0      # 0-100 reversal confidence
        self._prev_ema5_above_20: Optional[bool] = None
        self._consecutive_up_ticks: int = 0
        self._consecutive_down_ticks: int = 0
        self._ticks_since_reversal: int = 999

    def update(self, price: float):
        """Update all indicators with new price tick."""
        self.tick_count += 1
        self.prices.append(price)
        self.session_low = min(self.session_low, price)
        self.session_high = max(self.session_high, price)

        # ── EMA-5, EMA-20, EMA-50 ──
        a5 = 2.0 / 6.0
        a20 = 2.0 / 21.0
        a50 = 2.0 / 51.0
        self.ema_5 = price if self.ema_5 is None else a5 * price + (1 - a5) * self.ema_5
        self.ema_20 = price if self.ema_20 is None else a20 * price + (1 - a20) * self.ema_20
        self.ema_50 = price if self.ema_50 is None else a50 * price + (1 - a50) * self.ema_50

        # ── ATR (simplified: |price change| per tick) ──
        if self.prev_price is not None:
            tr = abs(price - self.prev_price)
            self.tr_history.append(tr)
            if len(self.tr_history) >= 3:
                self.atr = sum(self.tr_history) / len(self.tr_history)

        # ── Momentum: rate of change over 10 ticks ──
        if len(self.prices) >= 10:
            old_price = self.prices[-10]
            if old_price > 0:
                self.momentum = (price - old_price) / old_price
        elif self.prev_price and self.prev_price > 0:
            self.momentum = (price - self.prev_price) / self.prev_price
        self.momentum_history.append(self.momentum)

        # ── Consecutive tick direction ──
        if self.prev_price is not None:
            if price > self.prev_price:
                self._consecutive_up_ticks += 1
                self._consecutive_down_ticks = 0
            elif price < self.prev_price:
                self._consecutive_down_ticks += 1
                self._consecutive_up_ticks = 0

        self.prev_price = price

        # ── Trend Strength & Direction ──
        if self.ema_5 and self.ema_20 and self.ema_50:
            # Trend direction: EMA alignment
            if self.ema_5 > self.ema_20 > self.ema_50:
                self.trend_direction = 1   # Strong uptrend
            elif self.ema_5 < self.ema_20 < self.ema_50:
                self.trend_direction = -1  # Strong downtrend
            else:
                self.trend_direction = 0   # Mixed / ranging

            # Trend strength: how far EMA-5 is from EMA-50
            if self.ema_50 > 0:
                self.trend_strength = min(1.0, abs(self.ema_5 - self.ema_50) / max(0.001, self.ema_50) * 10)

        # ── Reversal Detection: EMA-5 crossing EMA-20 ──
        self._ticks_since_reversal += 1
        if self.ema_5 is not None and self.ema_20 is not None:
            ema5_above_20 = self.ema_5 > self.ema_20
            if self._prev_ema5_above_20 is not None:
                # EMA-5 just crossed above EMA-20 = bullish reversal for this side
                if ema5_above_20 and not self._prev_ema5_above_20:
                    self.is_reversing = True
                    self._ticks_since_reversal = 0
                elif not ema5_above_20 and self._prev_ema5_above_20:
                    # EMA-5 crossed below EMA-20 = bearish turn
                    self.is_reversing = False
                elif self._ticks_since_reversal > 15:
                    self.is_reversing = False
            self._prev_ema5_above_20 = ema5_above_20

        # ── Reversal Score (0-100): composite confidence ──
        self._compute_reversal_score(price)

        # ── Z-Score relative to EMA-50 ──
        if len(self.prices) >= 10:
            window = list(self.prices)[-20:]
            mean = sum(window) / len(window)
            variance = sum((x - mean) ** 2 for x in window) / len(window)
            self.std_dev = max(0.0005, math.sqrt(variance))
            self.z_score = (price - self.ema_50) / self.std_dev if self.ema_50 else 0.0
        else:
            self.z_score = 0.0

    def _compute_reversal_score(self, price: float):
        """Compute a 0-100 reversal confidence score."""
        score = 0.0

        # Factor 1: EMA-5 crossed above EMA-20 recently (30 pts)
        if self.is_reversing:
            freshness = max(0, 1.0 - self._ticks_since_reversal / 15.0)
            score += 30.0 * freshness

        # Factor 2: Positive momentum after negative period (25 pts)
        if len(self.momentum_history) >= 5:
            recent_mom = list(self.momentum_history)[-5:]
            older_mom = list(self.momentum_history)[-10:-5] if len(self.momentum_history) >= 10 else []
            if older_mom:
                avg_recent = sum(recent_mom) / len(recent_mom)
                avg_older = sum(older_mom) / len(older_mom)
                if avg_older < -0.001 and avg_recent > 0:
                    score += 25.0 * min(1.0, avg_recent / 0.01)

        # Factor 3: Price near session low but bouncing (25 pts)
        if self.session_high > self.session_low and self.session_high > 0:
            price_range = self.session_high - self.session_low
            if price_range > 0:
                position_in_range = (price - self.session_low) / price_range
                if position_in_range < 0.3 and self._consecutive_up_ticks >= 2:
                    score += 25.0 * (1.0 - position_in_range / 0.3)

        # Factor 4: Consecutive up ticks (20 pts)
        if self._consecutive_up_ticks >= 3:
            score += min(20.0, self._consecutive_up_ticks * 5.0)

        self.reversal_score = min(100.0, score)

    @property
    def is_falling_knife(self) -> bool:
        """True if side is in strong sustained downtrend — avoid buying."""
        return (self.trend_direction == -1 and
                self.trend_strength > 0.3 and
                self.momentum < -0.005 and
                not self.is_reversing)

    @property
    def is_confirmed_dip(self) -> bool:
        """True if price dipped but shows signs of recovery."""
        return (self.z_score < -0.5 and
                (self.is_reversing or
                 self.reversal_score > 30 or
                 self._consecutive_up_ticks >= 2))


class ArbitrageStrategy:
    """
    HFT Mean-Reversion Strategy for Polymarket binary markets.

    Buys each side independently when oversold, hedges to lock profit.
    Uses Kelly Criterion for position sizing and Z-Score for signals.
    """

    def __init__(self, market_budget: float, starting_balance: float,
                 exec_sim: ExecutionSimulator = None):
        self.market_budget = market_budget
        self.starting_balance = starting_balance
        self.cash_ref = {'balance': starting_balance}

        # ── Position tracking ──
        self.qty_up = 0.0
        self.qty_down = 0.0
        self.cost_up = 0.0
        self.cost_down = 0.0

        # ── Per-side indicators ──
        self.up_tracker = SideTracker()
        self.down_tracker = SideTracker()

        # ── SpreadEngine (for UI z-score charts) ──
        self.spread_engine = SpreadEngine(
            lookback=60, beta_lookback=30, entry_z=2.0,
            exit_z=0.0, max_z=4.0, hysteresis=0.2, bb_k=2.0,
        )

        # ══════════════════════════════════════════════════════
        #  HFT PARAMETERS v5 — Smart Position Weighting
        # ══════════════════════════════════════════════════════

        # ── Warmup ──
        self.warmup_ticks = 20

        # ── Z-Score thresholds ──
        self.z_entry = -0.8            # Normal entry: oversold
        self.z_strong_entry = -1.5     # Strong signal: heavily oversold
        self.z_hedge_relaxed = -0.3    # Relaxed threshold when hedging
        self.z_hedge_urgent = 0.5      # Buy hedge even slightly above EMA

        # ── Momentum Filter (NEW) ──
        self.require_momentum_confirm = True   # Don't buy falling knives
        self.falling_knife_override_z = -2.5   # Override momentum filter at extreme Z
        self.reversal_score_min = 25.0          # Min reversal confidence to enter
        self.reversal_boost_multiplier = 1.5    # Boost position size on confirmed reversal

        # ── Kelly Criterion ──
        self.risk_factor = 0.5         # Half-Kelly for safety
        self.max_kelly_fraction = 0.10 # Max 10% of remaining budget per trade (was 12%)
        self.min_trade_size = 1.0      # Polymarket minimum ~$1

        # ── Budget Tranches (NEW) ──
        self.budget_reserve_pct = 0.35         # Always reserve 35% for hedging
        self.entry_budget_pct = 0.65           # Max 65% for entries
        self.max_single_side_budget_pct = 0.45 # Max 45% on a single side
        self.tranche_count = 5                 # Split entries into 5 tranches
        self._tranche_size = market_budget * self.entry_budget_pct / self.tranche_count

        # ── Probability-Aware Sizing (NEW) ──
        self.prob_low_threshold = 0.20         # Below 20%: tiny positions only
        self.prob_uncertain_range = (0.35, 0.65)  # Uncertain range: best for arb
        self.prob_high_threshold = 0.75        # Above 75%: very expensive, small

        # ── Timing ──
        self.cooldown_seconds = 2.0    # HFT: 2s between trades
        self.min_time_to_enter = 30    # Don't open new positions in last 30s

        # ── Risk / Exposure ──
        self.max_individual_price = 0.72  # Don't buy expensive sides (was 0.78)
        self.max_loss_per_market = 12.0   # Tighter stop-loss (was 15.0)
        self.hedge_delta_pct = 15.0       # Start hedging at 15% delta (was 25%)
        self.urgent_hedge_delta = 35.0    # Urgent hedge at 35% delta (was 50%)
        self.forced_hedge_delta = 55.0    # Forced hedge at 55% delta (was 70%)
        self.max_risk_per_leg = 6.0       # Max $ loss on one scenario (was 8.0)

        # ── Pre-emptive Hedging (NEW) ──
        self.preemptive_hedge_enabled = True    # Start small hedges early
        self.preemptive_hedge_threshold = 8.0   # Start pre-hedge at 8% delta
        self.preemptive_hedge_fraction = 0.3    # Hedge 30% of deficit

        # ── Position limits ──
        self.max_shares_per_order = 150         # Smaller max orders (was 200)
        self.max_allowed_delta_pct = 5.0        # Considered "balanced" under this

        # ── State ──
        self.last_trade_time: float = 0
        self.market_status: str = 'open'
        self.trade_count: int = 0
        self.trade_log: List[dict] = []
        self.payout: float = 0.0
        self.last_fees_paid: float = 0.0

        # ── Mode tracking ──
        self.current_mode: str = 'warmup'
        self.mode_reason: str = 'Collecting price data'
        self._exposure_priority: str = 'NEUTRAL'

        # ── Resolution (written externally by web_bot_multi) ──
        self.resolution_outcome = None
        self.final_pnl = None
        self.final_pnl_gross = None

        # ── Combined tracking (for UI compat) ──
        self._combined_history: deque = deque(maxlen=60)
        self._min_combined_seen: float = 1.0
        self._tick_count: int = 0
        self._entry_score: float = 0.0

        # ── Legacy spread (UI compat) ──
        self.spread_history: deque = deque(maxlen=20)
        self.avg_spread: float = 0.0

        # ── MGP / PnL history for UI charting ──
        self.mgp_history: deque = deque(maxlen=120)
        self.pnl_up_history: deque = deque(maxlen=120)
        self.pnl_down_history: deque = deque(maxlen=120)

        # ── Execution Simulator ──
        self.exec_sim = exec_sim or ExecutionSimulator(latency_ms=25.0, max_slippage_pct=5.0)
        self._pending_orderbooks: Dict[str, dict] = {'UP': {}, 'DOWN': {}}
        self._book_depth_cap: Dict[str, float] = {'UP': 100.0, 'DOWN': 100.0}

    # ═══════════════════════════════════════════════════════════════
    #  PROPERTIES
    # ═══════════════════════════════════════════════════════════════

    @property
    def cash(self):
        return self.cash_ref['balance']

    @cash.setter
    def cash(self, value):
        self.cash_ref['balance'] = value

    @property
    def avg_up(self) -> float:
        return self.cost_up / self.qty_up if self.qty_up > 0 else 0.0

    @property
    def avg_down(self) -> float:
        return self.cost_down / self.qty_down if self.qty_down > 0 else 0.0

    @property
    def pair_cost(self) -> float:
        return self.avg_up + self.avg_down

    @property
    def position_delta_pct(self) -> float:
        total = self.qty_up + self.qty_down
        if total == 0:
            return 0.0
        return abs(self.qty_up - self.qty_down) / total * 100.0

    @property
    def position_delta_direction(self) -> str:
        if self.qty_up > self.qty_down:
            return "UP"
        elif self.qty_down > self.qty_up:
            return "DOWN"
        return "BALANCED"

    @property
    def qty_ratio(self) -> float:
        if self.qty_down == 0:
            return 999.0 if self.qty_up > 0 else 1.0
        return self.qty_up / self.qty_down

    @property
    def locked_profit(self) -> float:
        return self.calculate_locked_profit()

    @property
    def best_case_profit(self) -> float:
        return self.calculate_max_profit()

    # ═══════════════════════════════════════════════════════════════
    #  PNL / SCENARIO ANALYSIS
    # ═══════════════════════════════════════════════════════════════

    def calculate_total_fees(self, extra_cost: float = 0.0) -> float:
        return (self.cost_up + self.cost_down + extra_cost) * FEE_RATE

    def calculate_pnl_if_up_wins(self) -> float:
        if self.qty_up == 0 and self.qty_down == 0:
            return 0.0
        return self.qty_up - (self.cost_up + self.cost_down) * FEE_MULT

    def calculate_pnl_if_down_wins(self) -> float:
        if self.qty_up == 0 and self.qty_down == 0:
            return 0.0
        return self.qty_down - (self.cost_up + self.cost_down) * FEE_MULT

    def calculate_locked_profit(self) -> float:
        """MGP = min(pnl_if_up, pnl_if_down) — guaranteed minimum."""
        return min(self.calculate_pnl_if_up_wins(), self.calculate_pnl_if_down_wins())

    def calculate_max_profit(self) -> float:
        return max(self.calculate_pnl_if_up_wins(), self.calculate_pnl_if_down_wins())

    def both_scenarios_positive(self) -> bool:
        """Both pnl_if_up and pnl_if_down >= 0 → Arbitrage Locked!"""
        return (self.calculate_pnl_if_up_wins() >= 0 and
                self.calculate_pnl_if_down_wins() >= 0)

    def deficit(self) -> float:
        return abs(self.qty_up - self.qty_down)

    def smaller_side(self) -> str:
        return 'UP' if self.qty_up <= self.qty_down else 'DOWN'

    def larger_side(self) -> str:
        return 'UP' if self.qty_up >= self.qty_down else 'DOWN'

    def max_price_for_positive_mgp(self) -> float:
        """Max price for smaller side that keeps MGP >= 0 after hedging."""
        d = self.deficit()
        if d <= 0:
            return 0.99
        larger_qty = max(self.qty_up, self.qty_down)
        total_cost = self.cost_up + self.cost_down
        numerator = larger_qty / FEE_MULT - total_cost
        if numerator <= 0:
            return 0.0
        return min(numerator / d, 0.99)

    def mgp_after_buy(self, side: str, price: float, qty: float) -> float:
        """MGP after hypothetical buy of qty shares on one side."""
        cost = price * qty
        new_qty_up = self.qty_up + (qty if side == 'UP' else 0)
        new_qty_down = self.qty_down + (qty if side == 'DOWN' else 0)
        new_total_cost = self.cost_up + self.cost_down + cost
        return min(new_qty_up, new_qty_down) - new_total_cost * FEE_MULT

    # ═══════════════════════════════════════════════════════════════
    #  KELLY CRITERION — Position Sizing
    # ═══════════════════════════════════════════════════════════════

    def _kelly_fraction(self, price: float, fair_value: float) -> float:
        """
        Kelly Criterion for a binary outcome paying $1.00.

        f* = (p·b − q) / b
        where p = fair_value (estimated win probability from EMA-50),
              q = 1 − p,
              b = (1−price)/price (net payout odds).

        Enhanced with probability-aware scaling:
          - Low probability (<20%): scale down to 30% of Kelly
          - Uncertain range (35-65%): full Kelly (best arb zone)
          - High probability (>75%): scale down to 40% (expensive)

        Returns the fraction of remaining budget to bet.
        """
        if price <= 0.01 or price >= 0.99 or fair_value <= price:
            return 0.0

        p = min(0.95, max(0.05, fair_value))
        q = 1.0 - p
        b = (1.0 - price) / price

        if b <= 0:
            return 0.0

        f = (p * b - q) / b
        if f <= 0:
            return 0.0

        # Scale by risk factor (0.5 = half-Kelly)
        f *= self.risk_factor

        # Probability-aware scaling: reduce size outside optimal zone
        implied_prob = price  # In binary markets, price ≈ probability
        prob_scale = self._probability_scale(implied_prob)
        f *= prob_scale

        return min(f, self.max_kelly_fraction)

    def _probability_scale(self, implied_prob: float) -> float:
        """
        Scale factor based on implied probability.
        Best zone for arb is 35-65% (uncertain markets).
        Extreme probabilities mean expensive or near-worthless sides.
        """
        low = self.prob_low_threshold      # 0.20
        unc_lo, unc_hi = self.prob_uncertain_range  # (0.35, 0.65)
        high = self.prob_high_threshold    # 0.75

        if implied_prob < low:
            return 0.3   # Very cheap but likely to lose
        elif implied_prob < unc_lo:
            # Gradual ramp from 0.3 to 1.0
            t = (implied_prob - low) / (unc_lo - low)
            return 0.3 + 0.7 * t
        elif implied_prob <= unc_hi:
            return 1.0   # Optimal zone
        elif implied_prob <= high:
            # Gradual ramp from 1.0 to 0.4
            t = (implied_prob - unc_hi) / (high - unc_hi)
            return 1.0 - 0.6 * t
        else:
            return 0.4   # Very expensive, likely to win but poor arb value

    def _budget_available_for_side(self, side: str, is_hedge: bool = False) -> float:
        """
        Calculate available budget for a given side, respecting:
        1. Budget reserve for hedging (35% always available for hedges)
        2. Max single-side budget cap (45%)
        3. Tranche sizing
        """
        total_invested = self.cost_up + self.cost_down
        remaining_total = max(0, self.market_budget - total_invested)

        if is_hedge:
            # Hedges can use the full remaining budget including reserve
            return remaining_total

        # Entries are capped to entry_budget_pct of total market budget
        entry_budget = self.market_budget * self.entry_budget_pct
        entry_used = total_invested  # Simplified: all invested counts
        entry_remaining = max(0, entry_budget - entry_used)

        # Single side cap
        side_cost = self.cost_up if side == 'UP' else self.cost_down
        side_cap = self.market_budget * self.max_single_side_budget_pct
        side_remaining = max(0, side_cap - side_cost)

        return min(remaining_total, entry_remaining, side_remaining)

    def _calculate_trade_size(self, side: str, price: float,
                              fair_value: float, urgency: float = 1.0,
                              is_hedge: bool = False) -> float:
        """
        Calculate trade size using Kelly Criterion + budget controls.

        Exposure = (available_budget × kelly_fraction) × urgency
        Available budget respects tranche sizing and reserve.
        Urgency > 1.0 for hedge trades, < 1.0 for speculative trades.

        Returns quantity (shares).
        """
        available = self._budget_available_for_side(side, is_hedge=is_hedge)

        if available < self.min_trade_size:
            return 0.0

        kelly = self._kelly_fraction(price, fair_value)
        if kelly <= 0:
            return 0.0

        # Base dollar amount from Kelly
        dollars = available * kelly * urgency

        # Tranche cap: don't exceed one tranche for normal entries
        if not is_hedge:
            dollars = min(dollars, self._tranche_size)

        # Account balance constraint
        model_prob = fair_value
        account_limit = self.cash * self.risk_factor * model_prob
        dollars = min(dollars, account_limit)

        # Enforce bounds
        dollars = max(self.min_trade_size, min(dollars, available, self.cash))

        # Convert to shares
        qty = dollars / price if price > 0 else 0
        qty = min(qty, self.max_shares_per_order)

        # Cap to book depth
        depth = self._book_depth_cap.get(side, self.max_shares_per_order)
        qty = min(qty, depth)

        return qty

    # ═══════════════════════════════════════════════════════════════
    #  EXPOSURE / RISK MODULE — Runs every tick
    # ═══════════════════════════════════════════════════════════════

    def _check_exposure(self) -> str:
        """
        Risk module: determine if we need to prioritize hedging.

        Returns: 'NEUTRAL', 'PRIORITIZE_UP', or 'PRIORITIZE_DOWN'
        """
        if self.qty_up == 0 and self.qty_down == 0:
            return 'NEUTRAL'

        pnl_up = self.calculate_pnl_if_up_wins()
        pnl_down = self.calculate_pnl_if_down_wins()

        # Check PnL scenarios — if one is very negative, prioritize that side
        if pnl_down < -self.max_risk_per_leg:
            return 'PRIORITIZE_DOWN'  # Too much UP exposure, need DOWN hedge
        if pnl_up < -self.max_risk_per_leg:
            return 'PRIORITIZE_UP'    # Too much DOWN exposure, need UP hedge

        # Check position delta
        delta = self.position_delta_pct
        if delta > self.hedge_delta_pct:
            if self.qty_up > self.qty_down:
                return 'PRIORITIZE_DOWN'
            else:
                return 'PRIORITIZE_UP'

        return 'NEUTRAL'

    def _get_hedge_z_threshold(self) -> float:
        """
        Dynamic Z-score threshold for hedge trades.
        More unbalanced → more aggressive hedging (higher z threshold).
        """
        delta = self.position_delta_pct

        if delta >= self.forced_hedge_delta:
            return 1.0  # Buy hedge at almost any price
        elif delta >= self.urgent_hedge_delta:
            return self.z_hedge_urgent  # Buy even slightly above EMA
        elif delta >= self.hedge_delta_pct:
            return self.z_hedge_relaxed  # Buy at mild dips
        else:
            return self.z_entry  # Normal threshold

    # ═══════════════════════════════════════════════════════════════
    #  BALANCE STATUS (UI)
    # ═══════════════════════════════════════════════════════════════

    def get_balance_status(self) -> Dict:
        delta = self.position_delta_pct
        if self.both_scenarios_positive():
            status, color, icon = "ARB LOCKED", "cyan", "🔒"
        elif delta <= self.max_allowed_delta_pct:
            status, color, icon = "BALANCED", "green", "✅"
        elif delta <= 25.0:
            status, color, icon = "HEDGING", "yellow", "⚠️"
        elif delta <= 50.0:
            status, color, icon = "MUST HEDGE", "orange", "🔴"
        else:
            status, color, icon = "CRITICAL", "red", "🚨"
        return {'delta_pct': delta, 'direction': self.position_delta_direction,
                'status': status, 'color': color, 'icon': icon}

    # ═══════════════════════════════════════════════════════════════
    #  SPREAD ENGINE HELPERS (for UI charts)
    # ═══════════════════════════════════════════════════════════════

    def _feed_spread_engine(self, up_price: float, down_price: float) -> dict:
        info = self.spread_engine.update(up_price, down_price)
        simple_spread = abs(1.0 - up_price - down_price)
        self.spread_history.append(simple_spread)
        if self.spread_history:
            self.avg_spread = sum(self.spread_history) / len(self.spread_history)
        return info

    # ═══════════════════════════════════════════════════════════════
    #  EXECUTION
    # ═══════════════════════════════════════════════════════════════

    def execute_buy(self, side: str, price: float, qty: float,
                    timestamp: str = None) -> Tuple[bool, float, float]:
        """Execute a buy via the execution simulator. Returns (ok, fill_price, fill_qty)."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).strftime('%H:%M:%S')

        depth_cap = self._book_depth_cap.get(side, self.max_shares_per_order)
        original_qty = qty
        qty = min(qty, self.max_shares_per_order, depth_cap)

        orderbook = self._pending_orderbooks.get(side, {})
        fill = self.exec_sim.simulate_fill(side, price, qty, orderbook)

        if not fill.filled:
            return False, 0.0, 0.0

        actual_price = fill.fill_price
        actual_qty = fill.filled_qty
        actual_cost = fill.total_cost

        if actual_cost > self.cash:
            return False, 0.0, 0.0

        # Log slippage
        if fill.slippage > 0.00001:
            slip_dir = "WORSE" if fill.slippage > 0 else "BETTER"
            print(f"⚡ [{side}] SLIP: ${price:.4f}→${actual_price:.4f} "
                  f"({slip_dir} {fill.slippage_pct:+.3f}%) "
                  f"| {fill.levels_consumed} lvl | {fill.latency_ms:.0f}ms")
        if fill.partial:
            print(f"⚠️ [{side}] PARTIAL: {actual_qty:.1f}/{qty:.1f}")

        self.cash -= actual_cost
        self.trade_count += 1
        self.last_trade_time = time.time()

        if side == 'UP':
            self.qty_up += actual_qty
            self.cost_up += actual_cost
        else:
            self.qty_down += actual_qty
            self.cost_down += actual_cost

        self.trade_log.append({
            'time': timestamp, 'side': 'BUY', 'token': side,
            'price': actual_price, 'qty': actual_qty, 'cost': actual_cost,
            'desired_price': price, 'desired_qty': original_qty,
            'slippage': round(fill.slippage, 6),
            'slippage_pct': round(fill.slippage_pct, 4),
            'slippage_cost': round(fill.slippage_cost, 6),
            'partial': fill.partial,
            'levels': fill.levels_consumed,
            'latency_ms': fill.latency_ms,
        })
        if len(self.trade_log) > 100:
            self.trade_log = self.trade_log[-100:]

        return True, actual_price, actual_qty

    # ═══════════════════════════════════════════════════════════════
    #  MAIN TRADING LOOP — check_and_trade()
    # ═══════════════════════════════════════════════════════════════

    def check_and_trade(self, up_price: float, down_price: float,
                        timestamp: str,
                        time_to_close: float = None,
                        up_bid: Optional[float] = None,
                        down_bid: Optional[float] = None,
                        up_orderbook: Optional[dict] = None,
                        down_orderbook: Optional[dict] = None) -> List[Tuple[str, float, float]]:
        trades_made: List[Tuple[str, float, float]] = []

        if up_price <= 0 or down_price <= 0:
            return trades_made

        # ── Store orderbooks ──
        self._pending_orderbooks['UP'] = up_orderbook or {}
        self._pending_orderbooks['DOWN'] = down_orderbook or {}

        # ── Update book depth caps ──
        for ob_side, ob in [('UP', up_orderbook), ('DOWN', down_orderbook)]:
            if ob and ob.get('asks'):
                best_ask_size = 0
                try:
                    asks_sorted = sorted(ob['asks'], key=lambda a: float(a.get('price', 99)))
                    best_price = float(asks_sorted[0].get('price', 0))
                    for a in asks_sorted:
                        p = float(a.get('price', 0))
                        if p <= best_price * 1.02:
                            best_ask_size += float(a.get('size', 0))
                except (ValueError, IndexError):
                    pass
                self._book_depth_cap[ob_side] = max(10, best_ask_size * 0.5) if best_ask_size > 0 else self.max_shares_per_order
            else:
                self._book_depth_cap[ob_side] = self.max_shares_per_order

        # ── Calculate mid-prices for indicators ──
        mid_up = (up_bid + up_price) / 2.0 if up_bid and up_bid > 0 else up_price
        mid_down = (down_bid + down_price) / 2.0 if down_bid and down_bid > 0 else down_price

        # ── Update per-side indicators ──
        self.up_tracker.update(mid_up)
        self.down_tracker.update(mid_down)
        self._tick_count = self.up_tracker.tick_count

        # ── Feed SpreadEngine (UI charts) ──
        se_info = self._feed_spread_engine(up_price, down_price)

        # ── Track combined (UI) ──
        combined = up_price + down_price
        self._combined_history.append(combined)
        self._min_combined_seen = min(self._min_combined_seen, combined)

        # ── Current state ──
        mgp = self.calculate_locked_profit()
        total_invested = self.cost_up + self.cost_down
        remaining_budget = max(0, self.market_budget - total_invested)
        has_position = (self.qty_up + self.qty_down) > 0

        # z-scores
        z_up = self.up_tracker.z_score
        z_down = self.down_tracker.z_score
        fair_up = self.up_tracker.ema_50 or up_price
        fair_down = self.down_tracker.ema_50 or down_price

        # Combined entry score (for UI display)
        self._entry_score = max(0, -min(z_up, z_down) * 25)

        # ════════════════════════════════════════════════════════
        #  STOP CONDITIONS
        # ════════════════════════════════════════════════════════

        if self.market_status in ('stopped', 'resolved', 'closed'):
            return trades_made

        if mgp < -self.max_loss_per_market and has_position:
            self.market_status = 'stopped'
            self.current_mode = 'stopped'
            self.mode_reason = f'🛑 Stop loss — MGP ${mgp:.2f}'
            self._record_history()
            return trades_made

        if remaining_budget < self.min_trade_size and has_position:
            self.current_mode = 'holding'
            self.mode_reason = (f'💰 Budget used ${total_invested:.0f}/${self.market_budget:.0f} | '
                                f'MGP ${mgp:.2f} | Δ {self.position_delta_pct:.0f}%')
            self._record_history()
            return trades_made

        if time_to_close is not None and time_to_close < self.min_time_to_enter and not has_position:
            self.current_mode = 'too_late'
            self.mode_reason = f'⏰ Only {time_to_close:.0f}s left — skipping market'
            return trades_made

        # ════════════════════════════════════════════════════════
        #  WARMUP — Build indicator baselines
        # ════════════════════════════════════════════════════════

        if self._tick_count <= self.warmup_ticks:
            self.current_mode = 'warmup'
            self.mode_reason = (f'📊 Warmup ({self._tick_count}/{self.warmup_ticks}) | '
                                f'UP z={z_up:+.1f} DOWN z={z_down:+.1f}')
            self._record_history()
            return trades_made

        # ════════════════════════════════════════════════════════
        #  COOLDOWN
        # ════════════════════════════════════════════════════════

        now = time.time()
        if now - self.last_trade_time < self.cooldown_seconds:
            cd_left = self.cooldown_seconds - (now - self.last_trade_time)
            self.current_mode = 'cooldown'
            self.mode_reason = (f'⏱ CD {cd_left:.0f}s | '
                                f'UP z={z_up:+.1f} DOWN z={z_down:+.1f} | '
                                f'Δ {self.position_delta_pct:.0f}%')
            self._record_history()
            return trades_made

        # ════════════════════════════════════════════════════════
        #  EXPOSURE CHECK — Risk Module
        # ════════════════════════════════════════════════════════

        self._exposure_priority = self._check_exposure()
        priority = self._exposure_priority

        # ════════════════════════════════════════════════════════
        #  PRE-EMPTIVE HEDGE — Start hedging early at small deltas
        #  (NEW: don't wait until delta is 25%+, start at 8%)
        # ════════════════════════════════════════════════════════

        if (priority == 'NEUTRAL' and has_position and
                self.preemptive_hedge_enabled and
                self.position_delta_pct >= self.preemptive_hedge_threshold):

            ph_side = self.smaller_side()
            ph_price = up_price if ph_side == 'UP' else down_price
            ph_fair = fair_up if ph_side == 'UP' else fair_down
            ph_z = z_up if ph_side == 'UP' else z_down
            ph_tracker = self.up_tracker if ph_side == 'UP' else self.down_tracker

            # Only pre-hedge if price is reasonable and not a falling knife
            if (ph_price <= self.max_individual_price and
                    ph_z <= self.z_hedge_relaxed and
                    not ph_tracker.is_falling_knife):

                # Calculate deficit and buy a fraction of it
                deficit = self.deficit()
                target_qty = deficit * self.preemptive_hedge_fraction
                max_hedge_price = self.max_price_for_positive_mgp()

                if ph_price <= max_hedge_price and target_qty * ph_price >= self.min_trade_size:
                    qty = self._calculate_trade_size(ph_side, ph_price, ph_fair, 1.0, is_hedge=True)
                    qty = min(qty, target_qty)

                    if qty * ph_price >= self.min_trade_size:
                        # Verify hedge improves MGP
                        projected_mgp = self.mgp_after_buy(ph_side, ph_price, qty)
                        if projected_mgp > mgp:
                            ok, ap, aq = self.execute_buy(ph_side, ph_price, qty, timestamp)
                            if ok:
                                trades_made.append((ph_side, ap, aq))
                                actual_mgp = self.calculate_locked_profit()
                                self.current_mode = 'pre_hedge'
                                self.mode_reason = (f'🔄 PRE-HEDGE {ph_side} {aq:.1f}sh@${ap:.3f} | '
                                                    f'Δ {self.position_delta_pct:.0f}% | MGP ${actual_mgp:.2f}')
                                print(f"🔄 PRE-HEDGE: {ph_side} {aq:.1f}×${ap:.3f} | "
                                      f"Δ {self.position_delta_pct:.0f}% | MGP ${actual_mgp:.2f}")
                                self._record_history()
                                return trades_made

        # ════════════════════════════════════════════════════════
        #  HEDGE MODE — Position is unbalanced, prioritize hedging
        # ════════════════════════════════════════════════════════

        if priority != 'NEUTRAL':
            hedge_side = 'UP' if priority == 'PRIORITIZE_UP' else 'DOWN'
            hedge_price = up_price if hedge_side == 'UP' else down_price
            hedge_fair = fair_up if hedge_side == 'UP' else fair_down
            hedge_z = z_up if hedge_side == 'UP' else z_down
            hedge_tracker = self.up_tracker if hedge_side == 'UP' else self.down_tracker
            z_threshold = self._get_hedge_z_threshold()

            delta = self.position_delta_pct
            pnl_up = self.calculate_pnl_if_up_wins()
            pnl_down = self.calculate_pnl_if_down_wins()
            worst_pnl = min(pnl_up, pnl_down)

            # Check max price for positive MGP — don't overpay for hedges
            max_hedge_price = self.max_price_for_positive_mgp()

            # Forced hedge: delta is critical — buy at market
            if delta >= self.forced_hedge_delta:
                urgency = 2.0
                adjusted_fair = max(hedge_fair, hedge_price * 1.05)
                qty = self._calculate_trade_size(hedge_side, hedge_price, adjusted_fair, urgency, is_hedge=True)

                # Even forced hedge respects max price (but with some slack)
                price_ok = hedge_price <= min(max_hedge_price * 1.15, 0.85)

                if qty * hedge_price >= self.min_trade_size and price_ok:
                    ok, ap, aq = self.execute_buy(hedge_side, hedge_price, qty, timestamp)
                    if ok:
                        trades_made.append((hedge_side, ap, aq))
                        new_mgp = self.calculate_locked_profit()
                        self.current_mode = 'forced_hedge'
                        self.mode_reason = (f'🚨 FORCED HEDGE {hedge_side} {aq:.1f}sh@${ap:.3f} | '
                                            f'Δ {self.position_delta_pct:.0f}% | MGP ${new_mgp:.2f}')
                        print(f"🚨 FORCED HEDGE: {hedge_side} {aq:.1f}×${ap:.3f} | "
                              f"delta {delta:.0f}%→{self.position_delta_pct:.0f}% | MGP ${new_mgp:.2f}")
                        self._record_history()
                        return trades_made

            # Smart hedge: check if the hedge side is showing a reversal
            # If reversing, boost urgency and relax threshold
            hedge_is_reversing = hedge_tracker.is_reversing or hedge_tracker.reversal_score > 30
            if hedge_is_reversing:
                z_threshold = max(z_threshold, 0.0)  # Very relaxed
                hedge_urgency_boost = 1.3
            else:
                hedge_urgency_boost = 1.0

            if hedge_z <= z_threshold and hedge_price <= self.max_individual_price:
                # Verify hedge price won't blow MGP
                if hedge_price <= max_hedge_price * 1.05:
                    urgency = (1.5 if delta > self.urgent_hedge_delta else 1.2) * hedge_urgency_boost
                    qty = self._calculate_trade_size(hedge_side, hedge_price, hedge_fair, urgency, is_hedge=True)

                    if qty * hedge_price >= self.min_trade_size:
                        new_mgp = self.mgp_after_buy(hedge_side, hedge_price, qty)

                        ok, ap, aq = self.execute_buy(hedge_side, hedge_price, qty, timestamp)
                        if ok:
                            trades_made.append((hedge_side, ap, aq))
                            actual_mgp = self.calculate_locked_profit()
                            lock_tag = " 🔒" if self.both_scenarios_positive() else ""
                            rev_tag = " 🔄" if hedge_is_reversing else ""
                            self.current_mode = 'hedging'
                            self.mode_reason = (f'⚖️ HEDGE {hedge_side} {aq:.1f}sh@${ap:.3f} | '
                                                f'z={hedge_z:+.1f} | Δ {self.position_delta_pct:.0f}% | '
                                                f'MGP ${actual_mgp:.2f}{lock_tag}{rev_tag}')
                            print(f"⚖️ HEDGE: {hedge_side} {aq:.1f}×${ap:.3f} | z={hedge_z:+.1f} | "
                                  f"delta {self.position_delta_pct:.0f}% | MGP ${actual_mgp:.2f}{lock_tag}{rev_tag}")
                            self._record_history()
                            return trades_made

            # Hedge signal not triggered yet
            rev_info = f" | rev={hedge_tracker.reversal_score:.0f}" if hedge_tracker.reversal_score > 0 else ""
            self.current_mode = 'waiting_hedge'
            self.mode_reason = (f'⏳ Need {hedge_side} hedge | z={hedge_z:+.1f} (need <{z_threshold:+.1f}) | '
                                f'Δ {self.position_delta_pct:.0f}% | PnL worst ${worst_pnl:.2f}{rev_info}')
            self._record_history()
            return trades_made

        # ════════════════════════════════════════════════════════
        #  ENTRY MODE — Smart Oversold Detection
        #  (NEW: momentum filter + reversal confirmation)
        # ════════════════════════════════════════════════════════

        # Build entry candidates with quality scoring
        candidates = []
        for side, z, price, fair, tracker in [
            ('UP', z_up, up_price, fair_up, self.up_tracker),
            ('DOWN', z_down, down_price, fair_down, self.down_tracker),
        ]:
            if price > self.max_individual_price:
                continue
            if z > self.z_entry:
                # Time pressure: in final quarter, slightly relax threshold
                if time_to_close is not None and time_to_close < 225:
                    if z > self.z_entry + 0.3:
                        continue
                else:
                    continue

            # ── MOMENTUM FILTER: Don't buy falling knives ──
            if self.require_momentum_confirm:
                if tracker.is_falling_knife:
                    # Exception: extreme Z-score overrides momentum filter
                    if z > self.falling_knife_override_z:
                        print(f"🔪 FALLING KNIFE blocked: {side} z={z:+.1f} | "
                              f"mom={tracker.momentum:.4f} | trend={tracker.trend_direction}")
                        continue

            # ── Calculate entry quality score ──
            entry_quality = self._score_entry(side, z, price, fair, tracker)
            candidates.append((side, z, price, fair, tracker, entry_quality))

        if not candidates:
            # Show why no entries
            up_knife = "🔪" if self.up_tracker.is_falling_knife else ""
            dn_knife = "🔪" if self.down_tracker.is_falling_knife else ""
            self.current_mode = 'scanning'
            self.mode_reason = (f'👁 Scanning | UP z={z_up:+.1f}{up_knife} DOWN z={z_down:+.1f}{dn_knife} | '
                                f'thres {self.z_entry:+.1f}')
            self._record_history()
            return trades_made

        # ── Choose best candidate by quality score ──
        candidates.sort(key=lambda c: c[5], reverse=True)
        buy_side, buy_z, buy_price, buy_fair, buy_tracker, quality = candidates[0]

        # ── Urgency scaling based on multiple factors ──
        urgency = 1.0

        # Strong z-score oversold → bigger position
        if buy_z <= self.z_strong_entry:
            urgency *= 1.3

        # Confirmed reversal → boost
        if buy_tracker.is_reversing or buy_tracker.reversal_score > self.reversal_score_min:
            urgency *= self.reversal_boost_multiplier
            print(f"🔄 REVERSAL BOOST: {buy_side} | rev_score={buy_tracker.reversal_score:.0f}")

        # Confirmed dip (not falling knife + recovery signs) → mild boost
        elif buy_tracker.is_confirmed_dip:
            urgency *= 1.15

        # Consider balance: if buying this side increases delta, reduce urgency
        if has_position:
            if ((buy_side == 'UP' and self.qty_up > self.qty_down) or
                    (buy_side == 'DOWN' and self.qty_down > self.qty_up)):
                urgency *= 0.6  # Reduce size — would worsen balance

        qty = self._calculate_trade_size(buy_side, buy_price, buy_fair, urgency)

        if qty * buy_price < self.min_trade_size:
            self.current_mode = 'scanning'
            self.mode_reason = (f'Trade too small | {buy_side} z={buy_z:+.1f} | '
                                f'Kelly={self._kelly_fraction(buy_price, buy_fair):.3f}')
            self._record_history()
            return trades_made

        # ── Verify entry doesn't wreck MGP ──
        if has_position:
            projected_mgp = self.mgp_after_buy(buy_side, buy_price, qty)
            if projected_mgp < mgp - 3.0:  # Don't enter if it worsens MGP by >$3
                self.current_mode = 'scanning'
                self.mode_reason = (f'⚠️ Skipped {buy_side} — would drop MGP by ${mgp - projected_mgp:.2f}')
                self._record_history()
                return trades_made

        # ── Execute single-side buy ──
        kelly_f = self._kelly_fraction(buy_price, buy_fair)
        rev_tag = f" REV={buy_tracker.reversal_score:.0f}" if buy_tracker.reversal_score > 15 else ""
        mom_tag = f" mom={buy_tracker.momentum:+.3f}" if abs(buy_tracker.momentum) > 0.001 else ""
        print(f"📊 SIGNAL: {buy_side} z={buy_z:+.2f} | ${buy_price:.3f} vs fair ${buy_fair:.3f} | "
              f"Kelly={kelly_f:.3f} | qty={qty:.1f} (${qty*buy_price:.2f}) | Q={quality:.0f}{rev_tag}{mom_tag}")

        ok, ap, aq = self.execute_buy(buy_side, buy_price, qty, timestamp)
        if ok:
            trades_made.append((buy_side, ap, aq))
            mgp_new = self.calculate_locked_profit()
            lock_tag = " 🔒" if self.both_scenarios_positive() else ""
            self.current_mode = 'accumulating'
            self.mode_reason = (f'📈 BUY {buy_side} {aq:.1f}sh@${ap:.3f} | z={buy_z:+.1f} | '
                                f'Kelly={kelly_f:.3f} | MGP ${mgp_new:.2f} | Q={quality:.0f}{lock_tag}')
            print(f"🎯 TRADE #{self.trade_count}: {buy_side} {aq:.1f}×${ap:.3f} | "
                  f"z={buy_z:+.1f} | Kelly={kelly_f:.3f} | MGP ${mgp_new:.2f} | Q={quality:.0f}{lock_tag}")

        self._record_history()
        return trades_made

    def _score_entry(self, side: str, z: float, price: float,
                     fair: float, tracker: 'SideTracker') -> float:
        """
        Score an entry candidate (0-100) based on multiple factors.
        Higher score = better entry opportunity.
        """
        score = 0.0

        # Factor 1: Z-score depth (40 pts max)
        # More oversold = higher score
        z_depth = max(0, -z - 0.5)  # How far below -0.5
        score += min(40.0, z_depth * 20.0)

        # Factor 2: Reversal confirmation (25 pts max)
        score += tracker.reversal_score * 0.25

        # Factor 3: Price in optimal probability zone (20 pts)
        prob_scale = self._probability_scale(price)
        score += prob_scale * 20.0

        # Factor 4: Balance improvement (15 pts)
        # Buying the smaller side should be rewarded
        if self.qty_up + self.qty_down > 0:
            if side == self.smaller_side():
                score += 15.0
            elif side == self.larger_side():
                score -= 10.0  # Penalize increasing imbalance

        # Factor 5: Momentum quality (-10 to +10 pts)
        if tracker.momentum > 0.002:
            score += 10.0  # Positive momentum confirms dip recovery
        elif tracker.momentum < -0.005:
            score -= 10.0  # Strong negative momentum is risky

        return max(0, min(100, score))

    def _record_history(self):
        if self.qty_up + self.qty_down > 0:
            self.mgp_history.append(self.calculate_locked_profit())
            self.pnl_up_history.append(self.calculate_pnl_if_up_wins())
            self.pnl_down_history.append(self.calculate_pnl_if_down_wins())

    # ═══════════════════════════════════════════════════════════════
    #  STATE FOR WEB UI
    # ═══════════════════════════════════════════════════════════════

    def get_state(self) -> dict:
        locked = self.calculate_locked_profit()
        pnl_up = self.calculate_pnl_if_up_wins()
        pnl_down = self.calculate_pnl_if_down_wins()
        best_case = max(pnl_up, pnl_down)

        max_hedge_up = 0.99 - self.avg_down if self.avg_down > 0 else 0.99
        max_hedge_down = 0.99 - self.avg_up if self.avg_up > 0 else 0.99
        qty_ratio = self.qty_up / self.qty_down if self.qty_down > 0 else (999 if self.qty_up > 0 else 1.0)

        se = self.spread_engine.get_state()
        arb_locked = self.both_scenarios_positive()

        return {
            'qty_up': self.qty_up,
            'qty_down': self.qty_down,
            'cost_up': self.cost_up,
            'cost_down': self.cost_down,
            'avg_up': self.avg_up,
            'avg_down': self.avg_down,
            'pair_cost': self.pair_cost,
            'locked_profit': locked,
            'best_case_profit': best_case,
            'qty_ratio': qty_ratio,
            'balance_pct': self.position_delta_pct,
            'is_balanced': self.position_delta_pct <= self.max_allowed_delta_pct,
            'trade_count': self.trade_count,
            'market_status': self.market_status,
            'resolution_outcome': self.resolution_outcome,
            'final_pnl': self.final_pnl,
            'final_pnl_gross': self.final_pnl_gross,
            'fees_paid': 0.0,
            'payout': self.payout,
            'max_hedge_up': max_hedge_up,
            'max_hedge_down': max_hedge_down,
            'current_mode': self.current_mode,
            'mode_reason': self.mode_reason,
            # Scenario & arb
            'pnl_if_up_wins': pnl_up,
            'pnl_if_down_wins': pnl_down,
            'delta_direction': self.position_delta_direction,
            'avg_spread': self.avg_spread,
            'arb_locked': arb_locked,
            'mgp': locked,
            'deficit': self.deficit(),
            'max_price_for_lock': self.max_price_for_positive_mgp() if self.deficit() > 0 else 0.0,
            # SpreadEngine (UI charts)
            'z_score': se.get('z_score', 0.0),
            'spread_signal': se.get('signal', SIGNAL_NONE),
            'spread_beta': se.get('beta', 1.0),
            'spread_delta_pct': se.get('position_delta_pct', 0.0),
            'bb_upper': se.get('bb_upper', 0.0),
            'bb_lower': se.get('bb_lower', 0.0),
            'spread_engine_ready': se.get('is_ready', False),
            # History arrays for UI charts
            'mgp_history': list(self.mgp_history),
            'pnl_up_history': list(self.pnl_up_history),
            'pnl_down_history': list(self.pnl_down_history),
            'z_history': se.get('z_history', []),
            'spread_history_arr': se.get('spread_history', []),
            'bb_upper_history': se.get('bb_upper_history', []),
            'bb_lower_history': se.get('bb_lower_history', []),
            'signal_history': se.get('signal_history', []),
            # HFT-specific indicators
            'entry_score': self._entry_score,
            'ema_fast': self.up_tracker.ema_20,
            'ema_slow': self.up_tracker.ema_50,
            'ash_bb_lower': None,
            'ash_bb_upper': None,
            'min_combined_seen': self._min_combined_seen,
            'tick_count': self._tick_count,
            # Per-side z-scores
            'z_score_up': self.up_tracker.z_score,
            'z_score_down': self.down_tracker.z_score,
            'atr_up': self.up_tracker.atr,
            'atr_down': self.down_tracker.atr,
            'exposure_priority': self._exposure_priority,
            # Momentum & Reversal indicators (v5)
            'momentum_up': self.up_tracker.momentum,
            'momentum_down': self.down_tracker.momentum,
            'reversal_score_up': self.up_tracker.reversal_score,
            'reversal_score_down': self.down_tracker.reversal_score,
            'trend_dir_up': self.up_tracker.trend_direction,
            'trend_dir_down': self.down_tracker.trend_direction,
            'is_reversing_up': self.up_tracker.is_reversing,
            'is_reversing_down': self.down_tracker.is_reversing,
            'falling_knife_up': self.up_tracker.is_falling_knife,
            'falling_knife_down': self.down_tracker.is_falling_knife,
            # Execution stats
            'exec_stats': self.exec_sim.get_stats(),
        }

    def get_status_summary(self) -> Dict:
        balance = self.get_balance_status()
        locked = self.calculate_locked_profit()
        pnl_up = self.calculate_pnl_if_up_wins()
        pnl_down = self.calculate_pnl_if_down_wins()
        se = self.spread_engine.get_state()
        return {
            'cash': self.cash,
            'qty_up': self.qty_up,
            'qty_down': self.qty_down,
            'avg_up': self.avg_up,
            'avg_down': self.avg_down,
            'cost_up': self.cost_up,
            'cost_down': self.cost_down,
            'pair_cost': self.pair_cost,
            'position_delta_pct': self.position_delta_pct,
            'balance_status': balance['status'],
            'balance_icon': balance['icon'],
            'locked_profit': locked,
            'pnl_if_up_wins': pnl_up,
            'pnl_if_down_wins': pnl_down,
            'max_profit': self.calculate_max_profit(),
            'trade_count': self.trade_count,
            'current_mode': self.current_mode,
            'mode_reason': self.mode_reason,
            'avg_spread': self.avg_spread,
            'market_status': self.market_status,
            'z_score': se.get('z_score', 0.0),
            'beta': se.get('beta', 1.0),
            'signal': se.get('signal', SIGNAL_NONE),
            'arb_locked': self.both_scenarios_positive(),
            'z_score_up': self.up_tracker.z_score,
            'z_score_down': self.down_tracker.z_score,
            'exposure_priority': self._exposure_priority,
            # v5 indicators
            'momentum_up': self.up_tracker.momentum,
            'momentum_down': self.down_tracker.momentum,
            'reversal_score_up': self.up_tracker.reversal_score,
            'reversal_score_down': self.down_tracker.reversal_score,
            'falling_knife_up': self.up_tracker.is_falling_knife,
            'falling_knife_down': self.down_tracker.is_falling_knife,
        }

    # ═══════════════════════════════════════════════════════════════
    #  RESOLUTION
    # ═══════════════════════════════════════════════════════════════

    def resolve_market(self, outcome: str) -> float:
        self.market_status = 'resolved'
        self.resolution_outcome = outcome
        self.payout = self.qty_up if outcome == 'UP' else self.qty_down
        total_cost = self.cost_up + self.cost_down
        fees = self.calculate_total_fees()
        self.last_fees_paid = fees
        pnl = self.payout - total_cost - fees
        self.final_pnl = pnl
        self.final_pnl_gross = self.payout - total_cost
        self.cash += max(0.0, self.payout - fees)
        return pnl

    def close_market(self):
        self.market_status = 'closed'
