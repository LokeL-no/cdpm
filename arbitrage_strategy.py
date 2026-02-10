#!/usr/bin/env python3
"""
Pair-Building Arbitrage Strategy v6.5 for Polymarket

CORE INSIGHT: In prediction markets, price = probability of winning.
  A side at $0.22 has 78% chance of LOSING. Buying it just because
  it's "cheap" (low z-score) means you're accumulating shares that
  will most likely be worth $0.00 at resolution.

  v6 fixes this by treating arb as PAIR BUILDING, not single-side
  mean reversion. The bot only enters when a profitable pair can
  be constructed, and favors the likely winner.

Strategy: PAIR-BUILDING with Winner-First Entry
  1. COMBINED COST GATE:  Only enter when UP + DOWN < $0.9852 (break-even).
     If combined > break-even, there is NO arb opportunity at current prices.
     The bot waits instead of buying falling knives.

  2. WINNER-FIRST:  When entering a new market, buy the side MORE likely
     to win (price > $0.50). If the bot gets stuck without completing
     the pair, at least it holds the likely winner.

  3. QTY RATIO CAP:  The loser side can NEVER exceed 1.5× the winner
     side in quantity. This prevents the exact problem the user described:
     accumulating tons of the cheap/losing side, then getting stuck
     needing an impossibly expensive hedge.

  4. ROLE-BASED PRICE CAPS:
     - Winner (likely to win): max entry price $0.68
     - Loser (likely to lose): max entry price $0.45
     This ensures the loser side is always cheap enough for arb value.

  5. PRE-EMPTIVE HEDGING:  Small balancing trades start at just 6% delta,
     buying 40% of the deficit. This keeps positions balanced from the
     start, not after they're already critically unbalanced.

  6. MGP PROTECTION:  Every trade is checked against projected MGP.
     Trades that would worsen MGP by >$2 are blocked.
     Hedge trades that exceed max_price_for_positive_mgp are blocked.

  7. ARB MARGIN SCORING:  Entry quality is weighted by arb margin
     (combined cost below break-even). More margin = bigger position.

Binary Market Rules:
  - UP + DOWN = $1.00 at resolution
  - Bot NEVER sells — only buys
  - Break-even combined avg = 1/1.015 ≈ $0.9852
  - Profit = min(qty_up, qty_down) - total_cost × 1.015

Key Differences from v5:
  - v5 bought whichever side had lowest z-score → always bought the loser
  - v6 requires combined < break-even first, then prefers the winner
  - v5 had no qty ratio limits → got stuck with 25 UP vs 15 DOWN
  - v6 caps loser/winner ratio at 1.5:1
  - v5 used same entry price cap for both sides
  - v6 uses strict $0.45 cap for the improbable side
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
    HFT Enter-and-Work Strategy v6.2 for Polymarket binary markets.

    KEY INSIGHT: Don't wait for arb — enter the market immediately.
    Buy the likely winner, then hedge when the other side dips.

    Strategy:
      1. ENTER IMMEDIATELY: Buy winner side as soon as market opens
      2. WAIT FOR HEDGE: Watch for combined dip below break-even
      3. WINNER-FIRST: Always start with the likely winner (safer)
      4. ROLE-BASED Z-THRESHOLDS: Winner z<=+0.5, Loser z<=-1.5
      5. POST-TRADE RATIO CHECK: Prevents imbalance before it happens
      6. MGP PROTECTION: Every trade must maintain or improve MGP
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
        #  HFT PARAMETERS v6 — Pair-Building Strategy
        #
        #  Core insight: In prediction markets, price = probability.
        #  Cheap side is cheap because it's likely to LOSE.
        #  Strategy: build BALANCED PAIRS, favor the likely winner,
        #  never let qty ratio exceed 1.5:1.
        # ══════════════════════════════════════════════════════

        # ── Warmup ──
        self.warmup_ticks = 20

        # ── Z-Score thresholds ──
        self.z_entry = -0.5            # General entry threshold (fallback)
        self.z_entry_winner = 0.5      # Winner: any small dip is enough (arb margin IS the signal)
        self.z_entry_loser = -1.5      # Loser: must be deeply oversold (cheap ≠ oversold!)
        self.z_entry_first_trade = 3.0 # First trade winner: almost always OK if arb exists
        self.z_strong_entry = -1.2     # Strong signal
        self.z_hedge_relaxed = -0.2    # Relaxed threshold when hedging
        self.z_hedge_urgent = 0.5      # Buy hedge even slightly above EMA

        # ── PAIR-BUILDING: Combined Cost Gate (NEW v6) ──
        #  Only enter when combined price (up + down) < break-even.
        #  This is THE critical filter: no arb exists above this.
        self.combined_entry_threshold = BREAK_EVEN - 0.005  # ~0.9802
        self.combined_good_threshold = BREAK_EVEN - 0.015   # ~0.9702 (good margin)
        self.combined_great_threshold = BREAK_EVEN - 0.025  # ~0.9602 (great margin)

        # ── QUANTITY RATIO LIMITS (NEW v6) ──
        #  Never let one side get far ahead of the other.
        #  This prevents the "bought too much cheap side" problem.
        self.max_qty_ratio = 1.5       # Max allowed ratio between sides
        self.ideal_qty_ratio = 1.0     # Target perfect balance
        self.max_qty_ratio_no_position = 3.0  # Slightly looser for first entries

        # ── WINNER-FIRST LOGIC (NEW v6) ──
        #  When entering a new market, prefer the likely winner.
        #  If you can't complete the pair, at least you hold the winner.
        self.winner_first_enabled = True
        self.buy_price_min = 0.68           # Min price to buy (v8.5)
        self.buy_price_max = 0.73           # Max price to buy (v8.5)

        # ── MARKET-FLIP PIVOT (v7.0) ──
        #  When the market flips, buy enough of the new winner that
        #  if that side wins → $1 profit (covers all cost + fees + $1).
        #  After max_pivot_count pivots → equalize both sides and give up.
        self.pivot_enabled = True
        self.pivot_winner_threshold = 0.55  # New winner must be >= 55% probability
        self.pivot_profit_target = 5.0      # Target $5 profit per successful pivot
        self.max_pivot_count = 6            # After N pivots → equalize and stop (v8.5)
        self._pivot_mode = False
        self._pivot_target_qty = 0.0
        self._pivot_failsafe = False  # True when we executed a limited pivot due to budget
        self._pivot_count = 0              # Number of pivots executed so far
        self._equalized = False            # True after position equalized (gave up market)
        # Persistent pivot state (v8.1) — survives across ticks for partial fills
        self._pending_pivot_side = None    # Side we're pivoting TO (e.g. 'DOWN')
        self._pending_pivot_target = 0.0   # Total qty needed on that side
        self._pending_pivot_is_new = False # Is this a new pivot (vs continuation)? (v8.4.2)

        # Entry gating (v6.5: no start-delay — enter immediately when price meets threshold)
        self._first_tick_time = None
        self.min_entry_price_to_start = 0.55  # Don't enter market until one side >= this price (v8.0)
        self.initial_buy_dollars = 5.0        # Force first buy to be exactly $5
        self.reserve_pivot_price = 0.57       # Worst-case price for pivot reserve calculation (v8.0)

        # ── Momentum Filter ──
        self.require_momentum_confirm = True
        self.falling_knife_override_z = -2.5
        self.reversal_score_min = 25.0
        self.reversal_boost_multiplier = 1.3

        # ── Kelly Criterion ──
        self.risk_factor = 0.5         # Half-Kelly for safety
        self.max_kelly_fraction = 0.10 # Max 10% of remaining budget per trade
        self.min_trade_size = 1.0      # Polymarket minimum ~$1

        # ── Budget Tranches ──
        self.budget_reserve_pct = 0.30         # 30% reserved for hedging
        self.entry_budget_pct = 0.70           # Max 70% for entries
        self.max_single_side_budget_pct = 0.50 # Max 50% on a single side
        self.tranche_count = 6                 # Split entries into 6 tranches
        self._tranche_size = market_budget * self.entry_budget_pct / self.tranche_count

        # ── Timing ──
        self.cooldown_seconds = 2.0
        self.min_time_to_enter = 30

        # ── Risk / Exposure ──
        self.max_individual_price = 0.65  # General max price (v8.0 — relaxed for pivots)
        self.max_loss_per_market = 10.0   # Tight stop-loss
        self.hedge_delta_pct = 5.0        # Start hedging at 5% delta (was 12 — too slow)
        self.urgent_hedge_delta = 20.0    # Urgent hedge at 20% delta
        self.forced_hedge_delta = 40.0    # Forced hedge at 40% delta
        self.max_risk_per_leg = 5.0       # Max $ loss on one scenario

        # ── Pre-emptive Hedging ──
        self.preemptive_hedge_enabled = False  # Disabled (v8.0 — only arb-lock and pivot buy other side)
        self.preemptive_hedge_threshold = 3.0  # Start pre-hedge at 3% delta (aggressive)
        self.preemptive_hedge_fraction = 0.4   # Hedge 40% of deficit

        # ── Position limits ──
        self.max_shares_per_order = 120
        self.max_allowed_delta_pct = 5.0

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
    #  CAPITAL RESERVATION — Worst-case pivot cost (v6.5)
    # ═══════════════════════════════════════════════════════════════

    def _worst_case_pivot_cost(self, pivot_price: float = None) -> float:
        """
        Calculate the cash needed for a worst-case BE pivot.

        Uses the CORRECTED formula that accounts for existing shares
        on the pivot side. Returns the cost of the MORE EXPENSIVE
        direction (pivot to UP vs pivot to DOWN).
        """
        total_cost = self.cost_up + self.cost_down
        if total_cost == 0:
            return 0.0

        p = pivot_price or self.reserve_pivot_price
        denom = 1.0 - p * FEE_MULT
        if denom <= 0.01:
            return self.market_budget  # Price too high, reserve everything

        worst = 0.0
        for existing in (self.qty_up, self.qty_down):
            numerator = FEE_MULT * (total_cost - existing * p) + self.pivot_profit_target
            if numerator <= 0:
                continue  # Already above target on this side, no pivot needed
            target_qty = numerator / denom
            additional = max(0, target_qty - existing)
            cost = additional * p
            worst = max(worst, cost)

        return worst

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
    #  ARB-AWARE FAIR VALUE
    # ═══════════════════════════════════════════════════════════════

    def _arb_adjusted_fair(self, side: str, price: float, other_price: float,
                           tracker_fair: float) -> float:
        """
        Compute fair value that accounts for PAIR arbitrage opportunity.

        In pair trading, the "edge" isn't "this side is undervalued vs EMA" —
        it's "this side + the other side creates a profitable pair".

        arb_fair = BREAK_EVEN - other_price
        (what this side is WORTH as part of a pair)

        If arb_fair > tracker_fair, the arb opportunity gives us a bigger edge
        than the EMA alone suggests.
        """
        arb_fair = BREAK_EVEN - other_price
        # For first entry (no arb yet), at least price + small edge
        min_fair = price * 1.02  # Minimum: assume 2% edge over current price
        return max(tracker_fair, arb_fair, min_fair)

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
        Scale factor based on implied probability (v6 — aggressive).

        In prediction markets, price = probability of winning.
        Buying a side at $0.20 means 80% chance of losing your $0.20.
        The optimal zone for arb is 40-60% where both sides are uncertain.

        Scale factors:
          <15%:  0.10  (almost certainly loses, tiny position only)
          15-30%: 0.20-0.40  (long shot, small positions)
          30-50%: 0.60-1.0   (uncertain, good for arb)
          50-65%: 1.0         (sweet spot — likely winner at fair price)
          65-72%: 0.80-0.50  (expensive but likely winner)
          >72%:  0.30        (too expensive for arb value)
        """
        if implied_prob < 0.15:
            return 0.10
        elif implied_prob < 0.30:
            t = (implied_prob - 0.15) / 0.15
            return 0.20 + 0.20 * t
        elif implied_prob < 0.50:
            t = (implied_prob - 0.30) / 0.20
            return 0.60 + 0.40 * t
        elif implied_prob <= 0.65:
            return 1.0
        elif implied_prob <= 0.72:
            t = (implied_prob - 0.65) / 0.07
            return 0.80 - 0.30 * t
        else:
            return 0.30

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

        # Early arb check for stop conditions
        _early_combined = up_price + down_price
        has_arb_opportunity = (BREAK_EVEN - _early_combined) > 0

        # ════════════════════════════════════════════════════════
        #  STOP CONDITIONS
        # ════════════════════════════════════════════════════════

        if self.market_status in ('stopped', 'resolved', 'closed'):
            return trades_made

        # Skip stop-loss if arb exists (can still recover) or pivot in progress
        if mgp < -self.max_loss_per_market and has_position:
            if not has_arb_opportunity and self._pivot_mode is None:
                self.market_status = 'stopped'
                self.current_mode = 'stopped'
                self.mode_reason = f'🛑 Stop loss — MGP ${mgp:.2f}'
                self._record_history()
                return trades_made
            # else: arb exists or pivoting — skip stop-loss, let bot try to recover

        # Budget exhausted — hold
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

        # ── PRICE GATE: don't enter until one side meets threshold (v6.5: no start-delay)
        allow_initial_entry = True
        if not has_position:
            if up_price < self.min_entry_price_to_start and down_price < self.min_entry_price_to_start:
                self.current_mode = 'waiting_for_price'
                self.mode_reason = (f'⏳ Waiting for price >= ${self.min_entry_price_to_start:.2f} | '
                                    f'UP ${up_price:.2f} DOWN ${down_price:.2f}')
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
        #  COMBINED COST GATE (v6)
        #  The FUNDAMENTAL arb check: can we build profitable pairs?
        #  UP + DOWN must sum to < break-even ($0.9852) for arb to exist.
        # ════════════════════════════════════════════════════════

        combined = up_price + down_price
        arb_margin = BREAK_EVEN - combined   # Positive = arb exists
        has_arb_opportunity = arb_margin > 0

        # ════════════════════════════════════════════════════════
        #  NO-ARB HOLD (v6.2) — Skip hedge/entry when no arb exists
        #  Hedging without arb worsens MGP. Just hold and wait.
        #  EXCEPTION (v6.3): If the market FLIPPED (our primary holding
        #  is now the loser), pivot to the new winner to rebalance.
        # ════════════════════════════════════════════════════════

        self._pivot_mode = False
        self._pivot_target_qty = 0.0

        # ── Auto-reset equalization if max_pivot_count was raised (v8.5) ──
        if self._equalized and self._pivot_count < self.max_pivot_count:
            self._equalized = False
            print(f"🔓 Un-equalized: {self._pivot_count} pivots < max {self.max_pivot_count} — resuming trading")

        if has_position and not has_arb_opportunity and not self._equalized:
            # ── Market-flip detection (v8.1 Pivot) ──
            #  Uses PnL check instead of primary_side check.
            #  If the current winner side has NEGATIVE PnL, we need more shares.
            #  Persistent: if a previous pivot was partially filled, continue it.
            new_winner = 'DOWN' if down_price > up_price else 'UP'
            new_winner_price = down_price if new_winner == 'DOWN' else up_price
            qty_new = self.qty_down if new_winner == 'DOWN' else self.qty_up

            # Check PnL if the current winner wins:
            pnl_if_winner = (self.calculate_pnl_if_down_wins() if new_winner == 'DOWN'
                             else self.calculate_pnl_if_up_wins())

            # Calculate how many shares needed for $5 profit:
            total_cost_now = self.cost_up + self.cost_down
            denom = 1.0 - new_winner_price * FEE_MULT
            if denom > 0.01:
                numerator = FEE_MULT * (total_cost_now - qty_new * new_winner_price) + self.pivot_profit_target
                if numerator <= 0:
                    additional_needed = 0
                else:
                    target_qty = numerator / denom
                    additional_needed = max(0, target_qty - qty_new)
            else:
                additional_needed = 0

            # Detect pivot need: winner side has negative PnL AND we need more shares
            # v8.1: Uses PnL check — works even after partial fills
            is_continuing_pivot = (self._pending_pivot_side == new_winner and
                                   additional_needed * new_winner_price >= self.min_trade_size)
            is_new_pivot = (pnl_if_winner < -0.01 and
                           additional_needed * new_winner_price >= self.min_trade_size)

            need_pivot = (self.pivot_enabled and
                          new_winner_price >= self.pivot_winner_threshold and
                          (is_new_pivot or is_continuing_pivot))

            if need_pivot:
                actual_cash = max(0, self.starting_balance - total_cost_now)
                required_cost = additional_needed * new_winner_price

                # Continuing a partial pivot should NOT count as a new pivot
                is_truly_new = not is_continuing_pivot
                effective_pivot_count = (self._pivot_count + (1 if is_truly_new else 0))

                # ── EQUALIZE EXIT (v7.0) ──
                #  Too many pivots OR can't afford next pivot → buy cheap side
                #  to balance UP ≈ DN and minimize worst-case loss.
                should_equalize = (effective_pivot_count > self.max_pivot_count or
                                   actual_cash < required_cost)

                if should_equalize:
                    weak_side = 'UP' if self.qty_up < self.qty_down else 'DOWN'
                    weak_price = up_price if weak_side == 'UP' else down_price
                    strong_qty = max(self.qty_up, self.qty_down)
                    weak_qty = min(self.qty_up, self.qty_down)
                    eq_diff = strong_qty - weak_qty

                    max_qty = actual_cash / weak_price if weak_price > 0 else 0
                    eq_qty = min(eq_diff, max_qty, self.max_shares_per_order)

                    if eq_qty * weak_price >= self.min_trade_size:
                        ok, ap, aq = self.execute_buy(weak_side, weak_price, eq_qty, timestamp)
                        if ok:
                            trades_made.append((weak_side, ap, aq))
                            self._equalized = True
                            total_final = self.cost_up + self.cost_down
                            mgp_final = self.calculate_locked_profit()
                            eq_reason = ('max pivots reached' if self._pivot_count >= self.max_pivot_count
                                         else f'budget (need ${required_cost:.0f}, have ${actual_cash:.0f})')
                            print(f"⚖️ EQUALIZE: {weak_side} {aq:.1f}×${ap:.3f} | "
                                  f"UP={self.qty_up:.1f} DN={self.qty_down:.1f} | "
                                  f"inv=${total_final:.2f} | MGP ${mgp_final:.2f} | "
                                  f"gave up after {self._pivot_count} pivots ({eq_reason})")
                            self.current_mode = 'equalized'
                            self.mode_reason = (f'⚖️ Equalized: {weak_side} {aq:.1f}sh@${ap:.3f} | '
                                                f'MGP ${mgp_final:.2f} | {self._pivot_count} pivots used')
                            self._record_history()
                            return trades_made

                    # Can't equalize (trade too small or failed) — just hold
                    self._equalized = True  # Mark as equalized even without trade
                    self.current_mode = 'equalized'
                    self.mode_reason = (f'⚖️ Equalized (no trade needed) after {self._pivot_count} pivots')
                    self._record_history()
                    return trades_made
                else:
                    # Can afford pivot — execute it
                    self._pivot_mode = True
                    self._pivot_target_qty = additional_needed
                    # Track persistent pivot state (v8.1)
                    self._pending_pivot_side = new_winner
                    self._pending_pivot_target = qty_new + additional_needed
                    # Store if this is a new pivot (will increment count after successful buy)
                    self._pending_pivot_is_new = is_truly_new
                    other_side = 'UP' if new_winner == 'DOWN' else 'DOWN'
                    cont_tag = ' (continuing)' if is_continuing_pivot else ''
                    # Show projected pivot count in message
                    projected_count = self._pivot_count + (1 if is_truly_new else 0)
                    print(f"🔄 PIVOT #{projected_count}{cont_tag}: {other_side}→{new_winner} @ ${new_winner_price:.3f} | "
                          f"need +{additional_needed:.1f}sh (${required_cost:.2f}) | "
                          f"target ${self.pivot_profit_target:.0f} profit | "
                          f"current {new_winner} pnl=${pnl_if_winner:.2f}")
            else:
                self.current_mode = 'holding'
                self.mode_reason = (f'⏳ Holding {self.qty_up:.1f}UP+{self.qty_down:.1f}DN | '
                                    f'MGP ${mgp:.2f} | waiting for flip')
                self._record_history()
                return trades_made

        elif has_position and not has_arb_opportunity and self._equalized:
            # Already equalized at max pivots — hold
            self.current_mode = 'equalized'
            self.mode_reason = (f'⚖️ Equalized — holding ({self._pivot_count} pivots used)')
            self._record_history()
            return trades_made

        # ── EQUALIZED: block all further trading (v8.5) ──
        if self._equalized:
            self.current_mode = 'equalized'
            self.mode_reason = (f'⚖️ Equalized — holding ({self._pivot_count} pivots used)')
            self._record_history()
            return trades_made

        # ════════════════════════════════════════════════════════
        #  HOLD GATE (v8.5) — After initial entry, only pivot can buy.
        #  No hedging, no pair trades, no incremental entries.
        # ════════════════════════════════════════════════════════

        if has_position and not self._pivot_mode:
            delta_str = f' | Δ {self.position_delta_pct:.0f}%' if self.qty_up > 0 and self.qty_down > 0 else ''
            self.current_mode = 'holding'
            self.mode_reason = (f'⏳ Holding {self.qty_up:.1f}UP+{self.qty_down:.1f}DN | '
                                f'pair ${combined:.3f} | MGP ${mgp:.2f}{delta_str}')
            self._record_history()
            return trades_made

        # ════════════════════════════════════════════════════════
        #  ENTRY MODE v8.5 — Price-Range Only
        #
        #  SIMPLE RULE: Only buy the winner when price is $0.57-$0.62.
        #  No pair trades, no hedging, no loser buys.
        #  Entry → Hold → Pivot on flip → Equalize after 6 pivots.
        # ════════════════════════════════════════════════════════

        # ── Determine likely winner ──
        likely_winner = 'DOWN' if down_price > up_price else 'UP'
        winner_price = down_price if likely_winner == 'DOWN' else up_price
        winner_z = z_down if likely_winner == 'DOWN' else z_up
        winner_fair = fair_down if likely_winner == 'DOWN' else fair_up
        winner_tracker = self.down_tracker if likely_winner == 'DOWN' else self.up_tracker

        # ── v8.5 PRICE GATE: Only buy if winner price is $0.57-$0.62 ──
        price_in_range = self.buy_price_min <= winner_price <= self.buy_price_max

        candidates = []

        if price_in_range:
            if not has_position:
                # Initial entry — buy winner
                quality = 65.0
                candidates.append((likely_winner, winner_z, winner_price, winner_fair,
                                   winner_tracker, quality))
            elif self._pivot_mode:
                # Pivot entry — buy new winner to rebalance
                quality = 75.0
                candidates.append((likely_winner, winner_z, winner_price, winner_fair,
                                   winner_tracker, quality))

        if not candidates:
            # Reset pivot state if we were pivoting but price not in range
            if self._pivot_mode:
                self.current_mode = 'pivot_blocked'
                self.mode_reason = (f'🚫 Pivot blocked: price ${winner_price:.2f} not in '
                                    f'${self.buy_price_min:.2f}-${self.buy_price_max:.2f} | '
                                    f'UP ${up_price:.2f} DN ${down_price:.2f}')
                self._pivot_mode = False
                self._pending_pivot_is_new = False
                self._pending_pivot_side = None
                self._pending_pivot_target = 0.0
            else:
                self.current_mode = 'scanning'
                self.mode_reason = (f'👁 Scanning | UP ${up_price:.2f} DN ${down_price:.2f} | '
                                    f'need ${self.buy_price_min:.2f}-${self.buy_price_max:.2f}')
            self._record_history()
            return trades_made

        # ── Select best candidate ──
        candidates.sort(key=lambda c: c[5], reverse=True)
        buy_side, buy_z, buy_price, buy_fair, buy_tracker, quality = candidates[0]

        # ── Calculate trade size (v8.5) ──

        # ── INITIAL BUY: force exactly $5 ──
        if not has_position and not self._pivot_mode:
            qty = self.initial_buy_dollars / buy_price if buy_price > 0 else 0
            qty = min(qty, self.max_shares_per_order)

        # ── PIVOT sizing (v6.3) ──
        #  Buy enough that if new winner wins → profit.
        #  Full target at once to avoid sub-$1 Polymarket rejections.
        if self._pivot_mode:
            qty = self._pivot_target_qty
            # Budget constraint — use full remaining budget for pivots
            total_invested = self.cost_up + self.cost_down
            remaining = max(0, self.market_budget - total_invested)
            max_qty_budget = remaining / buy_price if buy_price > 0 else 0
            qty = min(qty, max_qty_budget, self.max_shares_per_order)

        # ── CAPITAL RESERVATION (v6.5) ──
        #  Non-pivot trades must leave enough cash for a worst-case pivot.
        #  This guarantees the fail-safe can ALWAYS reach break-even.
        if not self._pivot_mode:
            actual_cash = max(0, self.starting_balance - (self.cost_up + self.cost_down))
            pivot_reserve = self._worst_case_pivot_cost()
            max_spend = max(0, actual_cash - pivot_reserve)
            max_qty_reserve = max_spend / buy_price if buy_price > 0 else 0
            qty = min(qty, max_qty_reserve)

        # Polymarket minimum is $1 — no exceptions, even for pivots
        if qty * buy_price < self.min_trade_size:
            if self._pivot_mode:
                self.current_mode = 'pivot_done'
                self.mode_reason = (f'🔄 Pivot target reached | {buy_side} need <${self.min_trade_size:.0f} more')
                self._pivot_mode = False
                self._pending_pivot_is_new = False
                # Clear pending pivot since we couldn't execute
                self._pending_pivot_side = None
                self._pending_pivot_target = 0.0
            else:
                self.current_mode = 'scanning'
                self.mode_reason = (f'Trade too small | {buy_side} z={buy_z:+.1f} | '
                                    f'Kelly={self._kelly_fraction(buy_price, buy_fair):.3f}')
            self._record_history()
            return trades_made

        # ── Execute ──
        role_tag = "👑"
        print(f"📊 SIGNAL: {role_tag} {buy_side} z={buy_z:+.2f} | ${buy_price:.3f} | "
              f"qty={qty:.1f} | Q={quality:.0f}")

        ok, ap, aq = self.execute_buy(buy_side, buy_price, qty, timestamp)
        if ok:
            trades_made.append((buy_side, ap, aq))
            # v8.4.2: Increment pivot count AFTER successful buy (not before)
            if self._pivot_mode and hasattr(self, '_pending_pivot_is_new') and self._pending_pivot_is_new:
                self._pivot_count += 1
                self._pending_pivot_is_new = False
            # Check if this pivot fill completes the target
            if self._pivot_mode and self._pending_pivot_side:
                pivot_qty_now = (self.qty_down if self._pending_pivot_side == 'DOWN'
                                 else self.qty_up)
                if pivot_qty_now >= self._pending_pivot_target - 0.5:
                    # Pivot target reached — clear pending state
                    self._pending_pivot_side = None
                    self._pending_pivot_target = 0.0
            mgp_new = self.calculate_locked_profit()
            lock_tag = " 🔒" if self.both_scenarios_positive() else ""
            pivot_tag = f" 🔄PIVOT#{self._pivot_count}" if self._pivot_mode else ""
            self.current_mode = 'pivoting' if self._pivot_mode else 'entry'
            self.mode_reason = (f'{role_tag} BUY {buy_side} {aq:.1f}sh@${ap:.3f} | '
                                f'MGP ${mgp_new:.2f} | Q={quality:.0f}{lock_tag}{pivot_tag}')
            print(f"🎯 TRADE #{self.trade_count}: {role_tag} {buy_side} {aq:.1f}×${ap:.3f} | "
                  f"MGP ${mgp_new:.2f} | Q={quality:.0f}{lock_tag}{pivot_tag}")

            # ── POST-PIVOT EQUALIZE (v7.0) ──
            #  After the Nth pivot, immediately buy the weak side at the CHEAP
            #  price (which is still cheap because we just pivoted to the expensive side).
            #  This minimizes equalize cost vs waiting for next flip.
            if (self._pivot_mode and self._pivot_count >= self.max_pivot_count
                    and not self._equalized):
                weak_side = 'UP' if self.qty_up < self.qty_down else 'DOWN'
                weak_price = up_price if weak_side == 'UP' else down_price
                strong_qty = max(self.qty_up, self.qty_down)
                weak_qty = min(self.qty_up, self.qty_down)
                eq_diff = strong_qty - weak_qty

                actual_cash = max(0, self.starting_balance - (self.cost_up + self.cost_down))
                max_eq_qty = actual_cash / weak_price if weak_price > 0 else 0
                eq_qty = min(eq_diff, max_eq_qty, self.max_shares_per_order)

                if eq_qty * weak_price >= self.min_trade_size:
                    ok2, ap2, aq2 = self.execute_buy(weak_side, weak_price, eq_qty, timestamp)
                    if ok2:
                        trades_made.append((weak_side, ap2, aq2))
                        self._equalized = True
                        total_final = self.cost_up + self.cost_down
                        mgp_final = self.calculate_locked_profit()
                        print(f"⚖️ EQUALIZE: {weak_side} {aq2:.1f}×${ap2:.3f} | "
                              f"UP={self.qty_up:.1f} DN={self.qty_down:.1f} | "
                              f"inv=${total_final:.2f} | MGP ${mgp_final:.2f} | "
                              f"gave up after {self._pivot_count} pivots")
                        self.current_mode = 'equalized'
                        self.mode_reason = (f'⚖️ Equalized: {weak_side} {aq2:.1f}sh@${ap2:.3f} | '
                                            f'MGP ${mgp_final:.2f} | {self._pivot_count} pivots')
                else:
                    self._equalized = True  # Mark equalized even if trade too small

        self._record_history()
        return trades_made

    def _score_entry_v6(self, side: str, z: float, price: float,
                        fair: float, tracker: 'SideTracker',
                        arb_margin: float, is_likely_winner: bool) -> float:
        """
        Score an entry candidate (0-100) with pair-building awareness.

        Key difference from v5: heavily weights probability/role and
        penalizes buying the improbable side.
        """
        score = 0.0

        # Factor 1: Arb margin quality (25 pts max)
        # More margin = more room for profit
        if arb_margin > 0.025:
            score += 25.0
        elif arb_margin > 0.015:
            score += 20.0
        elif arb_margin > 0.005:
            score += 12.0
        else:
            score += 5.0

        # Factor 2: Role (20 pts)
        # Winner side gets a big bonus — if trade gets stuck, you hold the winner
        if is_likely_winner:
            score += 20.0
        else:
            # Loser side only scores if it's cheap enough to be a good pair
            if price < 0.30:
                score += 10.0  # Cheap pair leg
            elif price < 0.40:
                score += 5.0
            # Expensive loser (>0.40) gets no bonus

        # Factor 3: Z-score dip quality
        #  Winner: up to 20 pts (a dip in the winner IS a real opportunity)
        #  Loser:  up to 8 pts (the loser's low z is often just the trend, not a dip)
        z_depth = max(0, -z - 0.3)
        z_max = 20.0 if is_likely_winner else 8.0
        score += min(z_max, z_depth * 10.0)

        # Factor 4: Reversal confirmation (15 pts)
        score += min(15.0, tracker.reversal_score * 0.15)

        # Factor 5: Balance improvement (10 pts)
        if self.qty_up + self.qty_down > 0:
            if side == self.smaller_side():
                score += 10.0
            elif side == self.larger_side():
                score -= 15.0  # Strong penalty for increasing imbalance

        # Factor 6: Momentum quality (-10 to +10 pts)
        if tracker.momentum > 0.002:
            score += 10.0
        elif tracker.momentum < -0.005:
            score -= 10.0

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
            'pivot_count': self._pivot_count,
            'max_pivots': self.max_pivot_count,
            'equalized': self._equalized,
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
