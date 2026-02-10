#!/usr/bin/env python3
"""
Adaptive Spread Harvester (ASH) – High-Frequency Arbitrage for Polymarket

Based on the Bregman Divergence framework for prediction market arbitrage:
  The guaranteed profit from moving market state θ to optimal θ* is at least
  D(μ*‖θ), the Bregman divergence between the cost function's conjugate
  evaluated at the optimal distribution μ* and the current state θ.

Binary Outcome Market Rules:
  - Asset_UP + Asset_DOWN = $1.00 at resolution (always)
  - Bot NEVER sells — only accumulates balanced pairs
  - Guaranteed Return per share = 1 − combined_price × 1.015
  - Break-even combined price = 1/1.015 ≈ $0.9852

Algorithm — Continuous Spread Harvesting:
  1. WARMUP (first 10 ticks): Collect price data, build EMA baselines
  2. SCORE each tick:
     a) Spread Quality    — guaranteed return per dollar spent (0–50 pts)
     b) Dip Detection     — price below slow EMA = buying opportunity (0–25 pts)
     c) Bollinger Signal  — price at/below lower band (0–15 pts)
     d) Session Low Bonus — new best price seen (0–10 pts)
     e) Time Pressure     — slight urgency in final quarter (0–10 pts)
  3. DYNAMIC SIZING based on score and budget pacing:
     - Higher score → larger fraction of remaining budget
     - TWAP-inspired pacing prevents front-loading
     - Book depth caps ensure balanced fills
  4. BALANCED EXECUTION: Always buy equal UP and DOWN
     - DOWN qty capped to actual UP fill for perfect balance
     - Imbalance correction buys smaller side first
  5. Every trade MUST improve MGP — no exceptions

Risk Management:
  - MGP stop-loss at –$10 per market
  - Dynamic cooldown (3–12s) between trades based on score
  - Never buy when combined > $0.995
  - Book depth awareness prevents walking the book
  - Partial fill handling preserves balance
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

# Fee rate (Polymarket ~1.5% effective)
FEE_RATE = 0.015
FEE_MULT = 1.0 + FEE_RATE       # 1.015
BREAK_EVEN = 1.0 / FEE_MULT     # ~0.9852 — combined must be below this to profit


class ArbitrageStrategy:
    """
    High-Frequency Adaptive Spread Harvester for Polymarket binary markets.

    Instead of a fixed number of large buys, this strategy continuously
    monitors the spread and makes many small, optimally-timed trades.
    """

    def __init__(self, market_budget: float, starting_balance: float, exec_sim: ExecutionSimulator = None):
        self.market_budget = market_budget
        self.starting_balance = starting_balance
        self.cash_ref = {'balance': starting_balance}

        # ── Position tracking ──
        self.qty_up = 0.0
        self.qty_down = 0.0
        self.cost_up = 0.0
        self.cost_down = 0.0

        # ── SpreadEngine (z-score analysis for UI + signals) ──
        self.spread_engine = SpreadEngine(
            lookback=60,
            beta_lookback=30,
            entry_z=2.0,
            exit_z=0.0,
            max_z=4.0,
            hysteresis=0.2,
            bb_k=2.0,
        )

        # ══════════════════════════════════════════════════════
        #  HFT PARAMETERS
        # ══════════════════════════════════════════════════════

        # ── Timing ──
        self.warmup_ticks = 10          # Observe before first trade
        self.min_cooldown = 3.0         # Minimum seconds between trades
        self.max_cooldown = 12.0        # Maximum seconds between trades
        self.min_time_to_enter = 30     # Don't enter in last 30 seconds

        # ── Entry thresholds ──
        self.max_combined = 0.995       # Absolute max combined price
        self.min_entry_score = 15       # Minimum score to trigger a trade

        # ── EMA parameters ──
        self.ema_fast_period = 5        # Fast EMA (5 ticks)
        self.ema_slow_period = 20       # Slow EMA (20 ticks)

        # ── Bollinger Band parameters ──
        self.bb_period = 30             # Lookback for BB
        self.bb_width = 1.5             # Standard deviations

        # ── Position sizing ──
        self.min_trade_size = 1.0       # Polymarket minimum ~$1
        self.max_budget_fraction = 0.25 # Max 25% of remaining budget per trade
        self.max_shares_per_order = 200 # Hard cap per order

        # ── Risk management ──
        self.max_loss_per_market = 10.0 # Stop-loss at MGP < -$10
        self.max_allowed_delta_pct = 5.0 # Max position imbalance
        self.rebalance_delta_pct = 3.0  # Rebalance threshold

        # ── Indicator state ──
        self._ema_fast: Optional[float] = None
        self._ema_slow: Optional[float] = None
        self._bb_mid: Optional[float] = None
        self._bb_upper: Optional[float] = None
        self._bb_lower: Optional[float] = None
        self._combined_history: deque = deque(maxlen=60)
        self._min_combined_seen: float = 1.0
        self._max_combined_seen: float = 0.0
        self._tick_count: int = 0
        self._entry_score: float = 0.0

        # ── Score history (for UI) ──
        self._score_history: deque = deque(maxlen=120)

        # ── Trading state ──
        self.last_trade_time: float = 0
        self.market_status: str = 'open'
        self.trade_count: int = 0
        self.trade_log: List[dict] = []
        self.payout: float = 0.0
        self.last_fees_paid: float = 0.0

        # ── Mode tracking ──
        self.current_mode: str = 'warmup'
        self.mode_reason: str = 'Collecting price data'

        # ── Price tracking ──
        self._prev_up_price: float = 0.0
        self._prev_down_price: float = 0.0

        # ── Legacy spread (UI compat) ──
        self.spread_history: deque = deque(maxlen=20)
        self.avg_spread: float = 0.0

        # ── MGP history for UI charting ──
        self.mgp_history: deque = deque(maxlen=120)
        self.pnl_up_history: deque = deque(maxlen=120)
        self.pnl_down_history: deque = deque(maxlen=120)

        # ── Execution Simulator (realistic fills) ──
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
    #  SCENARIO ANALYSIS
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
        """MGP = min(pnl_if_up, pnl_if_down)"""
        return min(self.calculate_pnl_if_up_wins(), self.calculate_pnl_if_down_wins())

    def calculate_max_profit(self) -> float:
        return max(self.calculate_pnl_if_up_wins(), self.calculate_pnl_if_down_wins())

    # ═══════════════════════════════════════════════════════════════
    #  MGP CALCULATOR
    # ═══════════════════════════════════════════════════════════════

    def mgp_after_buy(self, side: str, price: float, qty: float) -> float:
        """MGP after hypothetical buy of qty shares of side at price."""
        cost = price * qty
        new_qty_up = self.qty_up + (qty if side == 'UP' else 0)
        new_qty_down = self.qty_down + (qty if side == 'DOWN' else 0)
        new_total_cost = self.cost_up + self.cost_down + cost
        return min(new_qty_up, new_qty_down) - new_total_cost * FEE_MULT

    def mgp_after_paired_buy(self, up_price: float, down_price: float, qty: float) -> float:
        """MGP after buying qty shares of BOTH sides."""
        cost = (up_price + down_price) * qty
        new_qty_up = self.qty_up + qty
        new_qty_down = self.qty_down + qty
        new_total_cost = self.cost_up + self.cost_down + cost
        return min(new_qty_up, new_qty_down) - new_total_cost * FEE_MULT

    def deficit(self) -> float:
        """Qty gap between larger and smaller side."""
        return abs(self.qty_up - self.qty_down)

    def smaller_side(self) -> str:
        return 'UP' if self.qty_up <= self.qty_down else 'DOWN'

    def larger_side(self) -> str:
        return 'UP' if self.qty_up >= self.qty_down else 'DOWN'

    def max_price_for_positive_mgp(self) -> float:
        """Max price for smaller side such that MGP >= 0 after balancing."""
        d = self.deficit()
        if d <= 0:
            return 0.99
        larger_qty = max(self.qty_up, self.qty_down)
        total_cost = self.cost_up + self.cost_down
        numerator = larger_qty / FEE_MULT - total_cost
        if numerator <= 0:
            return 0.0
        return min(numerator / d, 0.99)

    def both_scenarios_positive(self) -> bool:
        """Are BOTH pnl_if_up and pnl_if_down >= 0? -> Arbitrage Locked!"""
        return (self.calculate_pnl_if_up_wins() >= 0 and
                self.calculate_pnl_if_down_wins() >= 0)

    # ═══════════════════════════════════════════════════════════════
    #  BALANCE STATUS (UI)
    # ═══════════════════════════════════════════════════════════════

    def get_balance_status(self) -> Dict:
        delta = self.position_delta_pct
        if self.both_scenarios_positive():
            status, color, icon = "ARB LOCKED", "cyan", "🔒"
        elif delta <= self.max_allowed_delta_pct:
            status, color, icon = "BALANCED", "green", "✅"
        elif delta <= 10.0:
            status, color, icon = "OK", "yellow", "⚠️"
        elif delta <= 20.0:
            status, color, icon = "MUST REBALANCE", "orange", "🔴"
        else:
            status, color, icon = "CRITICAL", "red", "🚨"
        return {'delta_pct': delta, 'direction': self.position_delta_direction,
                'status': status, 'color': color, 'icon': icon}

    # ═══════════════════════════════════════════════════════════════
    #  INDICATORS — EMA, Bollinger Bands, Entry Score
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _ema(value: float, prev: Optional[float], period: int) -> float:
        """Exponential Moving Average update."""
        if prev is None:
            return value
        alpha = 2.0 / (period + 1.0)
        return alpha * value + (1.0 - alpha) * prev

    def _update_indicators(self, combined: float):
        """Update all indicators with new combined price tick."""
        self._tick_count += 1
        self._combined_history.append(combined)
        self._min_combined_seen = min(self._min_combined_seen, combined)
        self._max_combined_seen = max(self._max_combined_seen, combined)

        # EMAs
        self._ema_fast = self._ema(combined, self._ema_fast, self.ema_fast_period)
        self._ema_slow = self._ema(combined, self._ema_slow, self.ema_slow_period)

        # Bollinger Bands (need enough data)
        if len(self._combined_history) >= self.bb_period:
            window = list(self._combined_history)[-self.bb_period:]
            mean = sum(window) / len(window)
            variance = sum((x - mean) ** 2 for x in window) / len(window)
            std = math.sqrt(variance) if variance > 0 else 0.0001
            self._bb_mid = mean
            self._bb_upper = mean + self.bb_width * std
            self._bb_lower = mean - self.bb_width * std

    def _calculate_entry_score(self, combined: float, time_remaining: Optional[float]) -> float:
        """
        Calculate composite entry score (0–110).

        Components:
          1. Spread Quality    (0–50): How profitable is this combined price?
          2. Dip Detection     (0–25): Is price below slow EMA? (mean-reversion)
          3. Bollinger Signal  (0–15): At/below lower Bollinger Band?
          4. Session Low Bonus (0–10): New best price seen this market?
          5. Time Pressure     (0–10): Urgency in final quarter.

        Score >= 15 triggers a trade.
        """
        # ── Component 1: Spread Quality (0–50) ──
        guaranteed_return = 1.0 - combined * FEE_MULT
        if guaranteed_return <= 0:
            return -1.0  # Would lose money

        quality_score = min(50.0, guaranteed_return * 1000.0)

        # ── Component 2: Dip Detection (0–25) ──
        dip_score = 0.0
        if self._ema_slow is not None and combined < self._ema_slow:
            dip = self._ema_slow - combined
            dip_score = min(25.0, dip * 2500.0)

        # ── Component 3: Bollinger Band Signal (0–15) ──
        bb_score = 0.0
        if self._bb_lower is not None and self._bb_mid is not None:
            if combined <= self._bb_lower:
                bb_score = 15.0
            elif combined < self._bb_mid:
                band_range = max(0.0001, self._bb_mid - self._bb_lower)
                bb_score = 15.0 * (self._bb_mid - combined) / band_range

        # ── Component 4: Session Low Bonus (0–10) ──
        low_score = 10.0 if combined <= self._min_combined_seen * 1.001 else 0.0

        # ── Component 5: Time Pressure (0–10) ──
        time_score = 0.0
        if time_remaining is not None:
            time_pct = time_remaining / 900.0
            if time_pct < 0.25 and guaranteed_return > 0.003:
                time_score = 5.0
            if time_pct < 0.10 and guaranteed_return > 0.005:
                time_score = 10.0

        total = quality_score + dip_score + bb_score + low_score + time_score
        self._entry_score = total
        self._score_history.append(total)
        return total

    def _calculate_trade_size(self, score: float, combined: float,
                              time_remaining: Optional[float]) -> float:
        """
        Determine trade size based on entry score and budget pacing.

        Higher score → larger fraction of remaining budget.
        TWAP pacing prevents spending all budget early.
        """
        total_invested = self.cost_up + self.cost_down
        remaining_budget = max(0, self.market_budget - total_invested)

        if remaining_budget < self.min_trade_size:
            return 0.0

        # Score-based fraction: score 15 → 3%, score 50 → 13.5%, score 100 → 28.5%
        fraction = min(self.max_budget_fraction, 0.01 + (score - 15) * 0.003)
        trade_dollars = remaining_budget * fraction

        # TWAP pacing: don't spend more than ~1.3× the time-proportional budget
        if time_remaining is not None and time_remaining > 30:
            elapsed_pct = max(0.05, 1.0 - (time_remaining / 900.0))
            time_budget = self.market_budget * elapsed_pct * 1.3
            if total_invested > time_budget:
                trade_dollars *= 0.5  # Ahead of pace — slow down

        # Cash cap
        trade_dollars = min(trade_dollars, self.cash * 0.15)

        # Min/max bounds
        trade_dollars = max(trade_dollars, self.min_trade_size)
        trade_dollars = min(trade_dollars, remaining_budget, self.cash)

        # Convert to shares
        qty = trade_dollars / combined if combined > 0 else 0
        return qty

    def _dynamic_cooldown(self, score: float) -> float:
        """
        Higher entry score → shorter cooldown (trade faster when conditions are great).
        score 15 → 12s, score 100 → 3s
        """
        if score <= 0:
            return self.max_cooldown
        cd = self.max_cooldown - (score - 15) * ((self.max_cooldown - self.min_cooldown) / 85.0)
        return max(self.min_cooldown, min(self.max_cooldown, cd))

    # ═══════════════════════════════════════════════════════════════
    #  SPREAD ENGINE HELPERS
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
        """Execute a buy via the execution simulator. Returns (success, fill_price, fill_qty)."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).strftime('%H:%M:%S')

        # Cap qty to order book depth
        depth_cap = self._book_depth_cap.get(side, self.max_shares_per_order)
        original_qty = qty
        qty = min(qty, self.max_shares_per_order, depth_cap)
        if qty < original_qty:
            print(f"📏 [{side}] Size capped: {original_qty:.1f} → {qty:.1f} shares "
                  f"(depth cap {depth_cap:.0f}, max {self.max_shares_per_order})")

        # Simulate realistic fill against order book
        orderbook = self._pending_orderbooks.get(side, {})
        fill = self.exec_sim.simulate_fill(side, price, qty, orderbook)

        if not fill.filled:
            print(f"❌ [{side}] ORDER REJECTED: {fill.reason}")
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
                  f"({slip_dir} {fill.slippage_pct:+.3f}% +${fill.slippage_cost:.4f}) "
                  f"| {fill.levels_consumed} lvl | {fill.latency_ms:.0f}ms")
        if fill.partial:
            print(f"⚠️ [{side}] PARTIAL: {actual_qty:.1f}/{qty:.1f} ({actual_qty/qty*100:.0f}%)")

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
            'desired_price': price, 'desired_qty': qty,
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

        # ── Store orderbooks for execute_buy() ──
        self._pending_orderbooks['UP'] = up_orderbook or {}
        self._pending_orderbooks['DOWN'] = down_orderbook or {}

        # ── Dynamically cap order sizes based on book depth ──
        for ob_side, ob in [('UP', up_orderbook), ('DOWN', down_orderbook)]:
            if ob and ob.get('asks'):
                best_ask_size = 0
                try:
                    asks_sorted = sorted(ob['asks'], key=lambda a: float(a.get('price', 99)))
                    best_price = float(asks_sorted[0].get('price', 0))
                    for a in asks_sorted:
                        p = float(a.get('price', 0))
                        if p <= best_price * 1.01:
                            best_ask_size += float(a.get('size', 0))
                except (ValueError, IndexError):
                    pass
                self._book_depth_cap[ob_side] = best_ask_size * 0.50 if best_ask_size > 0 else self.max_shares_per_order
            else:
                self._book_depth_cap[ob_side] = self.max_shares_per_order

        combined = up_price + down_price

        # ── Update indicators ──
        self._update_indicators(combined)

        # ── Feed SpreadEngine (for UI z-score charts) ──
        se_info = self._feed_spread_engine(up_price, down_price)

        # ── Calculate MGP ──
        mgp = self.calculate_locked_profit()
        total_invested = self.cost_up + self.cost_down
        remaining_budget = max(0, self.market_budget - total_invested)
        has_position = (self.qty_up + self.qty_down) > 0

        # ════════════════════════════════════════════════════════
        #  STOP CONDITIONS
        # ════════════════════════════════════════════════════════

        # Stop-loss
        if mgp < -self.max_loss_per_market and has_position:
            print(f"🛑 STOP LOSS: MGP ${mgp:.2f} < -${self.max_loss_per_market:.2f}")
            self.market_status = 'stopped'
            self.current_mode = 'stopped'
            self.mode_reason = f'🛑 Stop loss — MGP ${mgp:.2f}'
            self._record_history()
            return trades_made

        # Budget exhausted
        if remaining_budget < self.min_trade_size and has_position:
            self.current_mode = 'holding'
            self.mode_reason = f'💰 Budget spent ${total_invested:.0f}/${self.market_budget:.0f} | MGP ${mgp:.2f}'
            self._record_history()
            return trades_made

        # Too late to enter new position
        if time_to_close is not None and time_to_close < self.min_time_to_enter and not has_position:
            self.current_mode = 'too_late'
            self.mode_reason = f'Only {time_to_close:.0f}s left — skipping'
            return trades_made

        # ════════════════════════════════════════════════════════
        #  WARMUP PHASE (first N ticks)
        # ════════════════════════════════════════════════════════
        if self._tick_count <= self.warmup_ticks:
            self.current_mode = 'warmup'
            self.mode_reason = f'📊 Observing ({self._tick_count}/{self.warmup_ticks}) | combined ${combined:.3f}'
            self._record_history()
            return trades_made

        # ════════════════════════════════════════════════════════
        #  ENTRY SCORING (always compute, needed for cooldown)
        # ════════════════════════════════════════════════════════
        score = self._calculate_entry_score(combined, time_to_close)

        # ════════════════════════════════════════════════════════
        #  COOLDOWN CHECK
        # ════════════════════════════════════════════════════════
        now = time.time()
        cooldown = self._dynamic_cooldown(max(0, score))

        if now - self.last_trade_time < cooldown:
            self.current_mode = 'cooldown'
            remaining_cd = cooldown - (now - self.last_trade_time)
            self.mode_reason = f'⏱ Cooldown {remaining_cd:.0f}s | score {score:.0f} | combined ${combined:.3f}'
            self._record_history()
            return trades_made

        # ════════════════════════════════════════════════════════
        #  IMBALANCE CORRECTION
        #  If position is unbalanced (from partial fills), buy
        #  the smaller side to restore balance before doing pairs.
        # ════════════════════════════════════════════════════════
        if has_position and self.position_delta_pct > self.rebalance_delta_pct:
            smaller = self.smaller_side()
            smaller_price = up_price if smaller == 'UP' else down_price
            gap = self.deficit()

            p_max = self.max_price_for_positive_mgp()
            if smaller_price <= min(p_max, 0.65):
                rebal_qty = min(gap, remaining_budget / smaller_price if smaller_price > 0 else 0)
                depth = self._book_depth_cap.get(smaller, self.max_shares_per_order)
                rebal_qty = min(rebal_qty, depth)

                if rebal_qty * smaller_price >= self.min_trade_size:
                    new_mgp = self.mgp_after_buy(smaller, smaller_price, rebal_qty)
                    if new_mgp > mgp:
                        ok, ap, aq = self.execute_buy(smaller, smaller_price, rebal_qty, timestamp)
                        if ok:
                            trades_made.append((smaller, ap, aq))
                            actual_mgp = self.calculate_locked_profit()
                            self.current_mode = 'rebalancing'
                            self.mode_reason = (f'⚖️ Rebalance {smaller} {aq:.1f}sh | '
                                                f'Δ {self.position_delta_pct:.1f}% | MGP ${actual_mgp:.2f}')
                            print(f"⚖️ REBALANCE: {smaller} {aq:.1f}×${ap:.3f} | "
                                  f"delta {self.position_delta_pct:.1f}% | MGP ${actual_mgp:.2f}")
                            self._record_history()
                            return trades_made

        # ════════════════════════════════════════════════════════
        #  ENTRY DECISION
        # ════════════════════════════════════════════════════════

        if score < 0:
            self.current_mode = 'unprofitable'
            self.mode_reason = f'📉 Combined ${combined:.3f} > break-even ${BREAK_EVEN:.4f}'
            self._record_history()
            return trades_made

        if score < self.min_entry_score:
            ema_str = f' | EMA ${self._ema_slow:.3f}' if self._ema_slow else ''
            self.current_mode = 'monitoring'
            self.mode_reason = f'👁 Score {score:.0f} < {self.min_entry_score} | combined ${combined:.3f}{ema_str}'
            self._record_history()
            return trades_made

        if combined > self.max_combined:
            self.current_mode = 'waiting'
            self.mode_reason = f'Combined ${combined:.3f} > max ${self.max_combined}'
            self._record_history()
            return trades_made

        # ════════════════════════════════════════════════════════
        #  EXECUTE BALANCED PAIRED BUY
        # ════════════════════════════════════════════════════════
        qty = self._calculate_trade_size(score, combined, time_to_close)

        if qty <= 0 or qty * combined < self.min_trade_size:
            self.current_mode = 'monitoring'
            self.mode_reason = f'Trade too small (${qty * combined:.2f}) | score {score:.0f}'
            self._record_history()
            return trades_made

        # Check book depth on BOTH sides
        up_depth = self._book_depth_cap.get('UP', self.max_shares_per_order)
        down_depth = self._book_depth_cap.get('DOWN', self.max_shares_per_order)
        max_balanced = min(up_depth, down_depth, self.max_shares_per_order)

        if qty > max_balanced:
            qty = max_balanced

        if qty * combined < self.min_trade_size:
            self.current_mode = 'low_liquidity'
            self.mode_reason = f'📉 Low balanced depth (UP={up_depth:.0f}, DOWN={down_depth:.0f})'
            self._record_history()
            return trades_made

        # Verify MGP improvement
        new_mgp = self.mgp_after_paired_buy(up_price, down_price, qty)
        if new_mgp <= mgp and has_position:
            self.current_mode = 'monitoring'
            self.mode_reason = f'No MGP gain (${mgp:.2f} → ${new_mgp:.2f}) | score {score:.0f}'
            self._record_history()
            return trades_made

        # ── Execute UP side ──
        guaranteed_return_pct = (1.0 - combined * FEE_MULT) * 100
        trade_cost = qty * combined
        print(f"📊 SCORE {score:.0f} | combined ${combined:.3f} | return {guaranteed_return_pct:.2f}% | "
              f"qty {qty:.1f} (${trade_cost:.2f}) | budget ${remaining_budget:.0f} left")

        ok_u, ap_u, aq_u = self.execute_buy('UP', up_price, qty, timestamp)
        if ok_u:
            trades_made.append(('UP', ap_u, aq_u))
            balanced_qty = min(qty, aq_u)
        else:
            balanced_qty = 0

        # ── Execute DOWN side (matched to UP fill) ──
        if balanced_qty > 0:
            ok_d, ap_d, aq_d = self.execute_buy('DOWN', down_price, balanced_qty, timestamp)
            if ok_d:
                trades_made.append(('DOWN', ap_d, aq_d))
        else:
            print(f"⚠️ UP fill failed — skipping DOWN to stay balanced")

        # ── Update mode ──
        actual_mgp = self.calculate_locked_profit()
        lock_tag = " 🔒 ARB LOCKED" if self.both_scenarios_positive() else ""

        self.current_mode = 'trading'
        self.mode_reason = (f'📈 Score {score:.0f} | ${trade_cost:.1f} @ ${combined:.3f} | '
                            f'MGP ${actual_mgp:.2f}{lock_tag}')
        print(f"🎯 TRADE #{self.trade_count}: {qty:.1f}sh × ${combined:.3f} = ${trade_cost:.2f} | "
              f"score {score:.0f} | MGP ${actual_mgp:.2f}{lock_tag}")

        self._prev_up_price = up_price
        self._prev_down_price = down_price
        self._record_history()

        return trades_made

    def _record_history(self):
        """Record MGP history for UI charting."""
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
            'resolution_outcome': None,
            'final_pnl': None,
            'final_pnl_gross': None,
            'fees_paid': 0.0,
            'payout': 0.0,
            'max_hedge_up': max_hedge_up,
            'max_hedge_down': max_hedge_down,
            'current_mode': self.current_mode,
            'mode_reason': self.mode_reason,
            # Scenario & arb metrics
            'pnl_if_up_wins': pnl_up,
            'pnl_if_down_wins': pnl_down,
            'delta_direction': self.position_delta_direction,
            'avg_spread': self.avg_spread,
            'arb_locked': arb_locked,
            'mgp': locked,
            'deficit': self.deficit(),
            'max_price_for_lock': self.max_price_for_positive_mgp() if self.deficit() > 0 else 0.0,
            # SpreadEngine metrics
            'z_score': se.get('z_score', 0.0),
            'spread_signal': se.get('signal', SIGNAL_NONE),
            'spread_beta': se.get('beta', 1.0),
            'spread_delta_pct': se.get('position_delta_pct', 0.0),
            'bb_upper': se.get('bb_upper', 0.0),
            'bb_lower': se.get('bb_lower', 0.0),
            'spread_engine_ready': se.get('is_ready', False),
            # MGP history for UI charting
            'mgp_history': list(self.mgp_history),
            'pnl_up_history': list(self.pnl_up_history),
            'pnl_down_history': list(self.pnl_down_history),
            # SpreadEngine history for UI charting
            'z_history': se.get('z_history', []),
            'spread_history_arr': se.get('spread_history', []),
            'bb_upper_history': se.get('bb_upper_history', []),
            'bb_lower_history': se.get('bb_lower_history', []),
            'signal_history': se.get('signal_history', []),
            # HFT indicators
            'entry_score': self._entry_score,
            'ema_fast': self._ema_fast,
            'ema_slow': self._ema_slow,
            'ash_bb_lower': self._bb_lower,
            'ash_bb_upper': self._bb_upper,
            'min_combined_seen': self._min_combined_seen,
            'tick_count': self._tick_count,
            # Execution simulator stats
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
        }

    # ═══════════════════════════════════════════════════════════════
    #  RESOLUTION
    # ═══════════════════════════════════════════════════════════════

    def resolve_market(self, outcome: str) -> float:
        self.market_status = 'resolved'
        self.payout = self.qty_up if outcome == 'UP' else self.qty_down
        total_cost = self.cost_up + self.cost_down
        fees = self.calculate_total_fees()
        self.last_fees_paid = fees
        pnl = self.payout - total_cost - fees
        self.cash += max(0.0, self.payout - fees)
        return pnl

    def close_market(self):
        self.market_status = 'closed'
