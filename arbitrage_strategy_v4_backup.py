#!/usr/bin/env python3
"""
HFT Mean-Reversion Strategy with Kelly Criterion for Polymarket

Core Principle:  NEVER buy UP and DOWN simultaneously.
  Instead, buy one side when it's cheap (oversold), then hedge by
  buying the other side when IT becomes cheap. This works because
  prices fluctuate within a 15-minute window — buying at different
  dip points gives a combined cost well below break-even.

Binary Market Rules:
  - UP + DOWN = $1.00 at resolution
  - Bot NEVER sells — only buys
  - Break-even combined avg = 1/1.015 ≈ $0.9852
  - Profit = min(qty_up, qty_down) - total_cost × 1.015

Indicators:
  1. Z-Score (Mean Reversion):
     - Per-side EMA-20 / EMA-50
     - Z = (price - EMA_50) / std_dev
     - Z < -0.8 → oversold → BUY signal
     - Z > +0.8 → overbought → avoid

  2. ATR (Average True Range):
     - Measures volatility per tick
     - Used for dynamic entry thresholds
     - High ATR = wider grid, more opportunity

  3. Kelly Criterion (Position Sizing):
     - f* = (p·b − q) / b
     - p = fair_value (EMA-50), b = (1−price)/price
     - Scaled by risk_factor (half-Kelly default)
     - Exposure = balance × risk_factor × probability_from_model

  4. Exposure / Risk Module:
     - Runs every tick
     - Checks pnl_if_up vs pnl_if_down
     - Prioritizes hedging when one scenario is losing
     - Delta > 25% → lower hedge threshold
     - Delta > 50% → hedge at market

Algorithm:
  1. WARMUP (20 ticks): Build EMA/ATR baselines
  2. Each tick:
     a. Update per-side indicators (EMA-20, EMA-50, Z-score, ATR)
     b. Run exposure check → determine priority
     c. If HEDGING needed: buy deficit side with relaxed threshold
     d. Else: buy oversold side via Kelly sizing
     e. Scale in with small tranches (grid effect)
  3. Cooldown: 2s between trades (true HFT pacing)
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
    Tracks EMA-20, EMA-50, Z-Score, and ATR for one side (UP or DOWN).
    Uses mid-price (bid+ask)/2 for indicator accuracy.
    """

    def __init__(self):
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

    def update(self, price: float):
        """Update all indicators with new price tick."""
        self.tick_count += 1
        self.prices.append(price)
        self.session_low = min(self.session_low, price)
        self.session_high = max(self.session_high, price)

        # ── EMA-20 and EMA-50 ──
        a20 = 2.0 / 21.0
        a50 = 2.0 / 51.0
        self.ema_20 = price if self.ema_20 is None else a20 * price + (1 - a20) * self.ema_20
        self.ema_50 = price if self.ema_50 is None else a50 * price + (1 - a50) * self.ema_50

        # ── ATR (simplified: |price change| per tick) ──
        if self.prev_price is not None:
            tr = abs(price - self.prev_price)
            self.tr_history.append(tr)
            if len(self.tr_history) >= 3:
                self.atr = sum(self.tr_history) / len(self.tr_history)
        self.prev_price = price

        # ── Z-Score relative to EMA-50 ──
        if len(self.prices) >= 10:
            window = list(self.prices)[-20:]
            mean = sum(window) / len(window)
            variance = sum((x - mean) ** 2 for x in window) / len(window)
            self.std_dev = max(0.0005, math.sqrt(variance))
            self.z_score = (price - self.ema_50) / self.std_dev if self.ema_50 else 0.0
        else:
            self.z_score = 0.0


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
        #  HFT PARAMETERS
        # ══════════════════════════════════════════════════════

        # ── Warmup ──
        self.warmup_ticks = 20

        # ── Z-Score thresholds ──
        self.z_entry = -0.8            # Normal entry: oversold
        self.z_strong_entry = -1.5     # Strong signal: heavily oversold
        self.z_hedge_relaxed = -0.3    # Relaxed threshold when hedging
        self.z_hedge_urgent = 0.5      # Buy hedge even slightly above EMA

        # ── Kelly Criterion ──
        self.risk_factor = 0.5         # Half-Kelly for safety
        self.max_kelly_fraction = 0.12 # Max 12% of remaining budget per trade
        self.min_trade_size = 1.0      # Polymarket minimum ~$1

        # ── Timing ──
        self.cooldown_seconds = 2.0    # HFT: 2s between trades
        self.min_time_to_enter = 30    # Don't open new positions in last 30s

        # ── Risk / Exposure ──
        self.max_individual_price = 0.78  # Don't buy expensive sides
        self.max_loss_per_market = 15.0   # Stop-loss
        self.hedge_delta_pct = 25.0       # Start hedging at 25% delta
        self.urgent_hedge_delta = 50.0    # Urgent hedge at 50% delta
        self.forced_hedge_delta = 70.0    # Forced hedge at 70% delta
        self.max_risk_per_leg = 8.0       # Max $ loss on one scenario

        # ── Position limits ──
        self.max_shares_per_order = 200
        self.max_allowed_delta_pct = 5.0  # Considered "balanced" under this

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
              b = (1 − price) / price (net payout odds).

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
        return min(f, self.max_kelly_fraction)

    def _calculate_trade_size(self, side: str, price: float,
                              fair_value: float, urgency: float = 1.0) -> float:
        """
        Calculate trade size using Kelly Criterion.

        Exposure = (remaining_budget × kelly_fraction) × urgency
        Urgency > 1.0 for hedge trades, < 1.0 for speculative trades.

        Returns quantity (shares).
        """
        total_invested = self.cost_up + self.cost_down
        remaining_budget = max(0, self.market_budget - total_invested)

        if remaining_budget < self.min_trade_size:
            return 0.0

        kelly = self._kelly_fraction(price, fair_value)
        if kelly <= 0:
            return 0.0

        # Base dollar amount from Kelly
        dollars = remaining_budget * kelly * urgency

        # Account balance constraint
        # Exposure = balance × risk_factor × probability_from_model
        model_prob = fair_value
        account_limit = self.cash * self.risk_factor * model_prob
        dollars = min(dollars, account_limit)

        # Enforce bounds
        dollars = max(self.min_trade_size, min(dollars, remaining_budget, self.cash))

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
        #  HEDGE MODE — Position is unbalanced, prioritize hedging
        # ════════════════════════════════════════════════════════

        if priority != 'NEUTRAL':
            hedge_side = 'UP' if priority == 'PRIORITIZE_UP' else 'DOWN'
            hedge_price = up_price if hedge_side == 'UP' else down_price
            hedge_fair = fair_up if hedge_side == 'UP' else fair_down
            hedge_z = z_up if hedge_side == 'UP' else z_down
            z_threshold = self._get_hedge_z_threshold()

            delta = self.position_delta_pct
            pnl_up = self.calculate_pnl_if_up_wins()
            pnl_down = self.calculate_pnl_if_down_wins()
            worst_pnl = min(pnl_up, pnl_down)

            # Forced hedge: delta is critical — buy at market
            if delta >= self.forced_hedge_delta:
                urgency = 2.0
                # Use a generous fair value to ensure Kelly gives a size
                adjusted_fair = max(hedge_fair, hedge_price * 1.05)
                qty = self._calculate_trade_size(hedge_side, hedge_price, adjusted_fair, urgency)
                if qty * hedge_price >= self.min_trade_size:
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

            # Hedge if z-score is below threshold (relaxed for urgency)
            if hedge_z <= z_threshold and hedge_price <= self.max_individual_price:
                urgency = 1.5 if delta > self.urgent_hedge_delta else 1.2
                qty = self._calculate_trade_size(hedge_side, hedge_price, hedge_fair, urgency)

                if qty * hedge_price >= self.min_trade_size:
                    # Verify hedge improves worst-case scenario
                    new_mgp = self.mgp_after_buy(hedge_side, hedge_price, qty)

                    ok, ap, aq = self.execute_buy(hedge_side, hedge_price, qty, timestamp)
                    if ok:
                        trades_made.append((hedge_side, ap, aq))
                        actual_mgp = self.calculate_locked_profit()
                        lock_tag = " 🔒" if self.both_scenarios_positive() else ""
                        self.current_mode = 'hedging'
                        self.mode_reason = (f'⚖️ HEDGE {hedge_side} {aq:.1f}sh@${ap:.3f} | '
                                            f'z={hedge_z:+.1f} | Δ {self.position_delta_pct:.0f}% | '
                                            f'MGP ${actual_mgp:.2f}{lock_tag}')
                        print(f"⚖️ HEDGE: {hedge_side} {aq:.1f}×${ap:.3f} | z={hedge_z:+.1f} | "
                              f"delta {self.position_delta_pct:.0f}% | MGP ${actual_mgp:.2f}{lock_tag}")
                        self._record_history()
                        return trades_made

            # Hedge signal not triggered yet
            self.current_mode = 'waiting_hedge'
            self.mode_reason = (f'⏳ Need {hedge_side} hedge | z={hedge_z:+.1f} (need <{z_threshold:+.1f}) | '
                                f'Δ {self.position_delta_pct:.0f}% | PnL worst ${worst_pnl:.2f}')
            self._record_history()
            return trades_made

        # ════════════════════════════════════════════════════════
        #  ENTRY MODE — Look for oversold side to buy
        # ════════════════════════════════════════════════════════

        # Find the best entry signal
        up_signal = z_up <= self.z_entry and up_price <= self.max_individual_price
        down_signal = z_down <= self.z_entry and down_price <= self.max_individual_price

        # Time pressure: in final quarter, slightly relax threshold
        if time_to_close is not None and time_to_close < 225:  # Last 25%
            relaxed_z = self.z_entry + 0.3
            if not up_signal:
                up_signal = z_up <= relaxed_z and up_price <= self.max_individual_price
            if not down_signal:
                down_signal = z_down <= relaxed_z and down_price <= self.max_individual_price

        if not up_signal and not down_signal:
            self.current_mode = 'scanning'
            self.mode_reason = (f'👁 Scanning | UP z={z_up:+.1f} DOWN z={z_down:+.1f} | '
                                f'thres {self.z_entry:+.1f}')
            self._record_history()
            return trades_made

        # Choose which side to buy: the MORE oversold one
        if up_signal and down_signal:
            buy_side = 'UP' if z_up < z_down else 'DOWN'
        elif up_signal:
            buy_side = 'UP'
        else:
            buy_side = 'DOWN'

        buy_price = up_price if buy_side == 'UP' else down_price
        buy_fair = fair_up if buy_side == 'UP' else fair_down
        buy_z = z_up if buy_side == 'UP' else z_down

        # Urgency scaling: stronger signal → larger trade
        urgency = 1.0
        if buy_z <= self.z_strong_entry:
            urgency = 1.5  # Heavily oversold → bigger position

        qty = self._calculate_trade_size(buy_side, buy_price, buy_fair, urgency)

        if qty * buy_price < self.min_trade_size:
            self.current_mode = 'scanning'
            self.mode_reason = f'Trade too small | {buy_side} z={buy_z:+.1f} | Kelly={self._kelly_fraction(buy_price, buy_fair):.3f}'
            self._record_history()
            return trades_made

        # ── Execute single-side buy ──
        kelly_f = self._kelly_fraction(buy_price, buy_fair)
        print(f"📊 SIGNAL: {buy_side} z={buy_z:+.2f} | ${buy_price:.3f} vs fair ${buy_fair:.3f} | "
              f"Kelly={kelly_f:.3f} | qty={qty:.1f} (${qty*buy_price:.2f})")

        ok, ap, aq = self.execute_buy(buy_side, buy_price, qty, timestamp)
        if ok:
            trades_made.append((buy_side, ap, aq))
            mgp_new = self.calculate_locked_profit()
            lock_tag = " 🔒" if self.both_scenarios_positive() else ""
            self.current_mode = 'accumulating'
            self.mode_reason = (f'📈 BUY {buy_side} {aq:.1f}sh@${ap:.3f} | z={buy_z:+.1f} | '
                                f'Kelly={kelly_f:.3f} | MGP ${mgp_new:.2f}{lock_tag}')
            print(f"🎯 TRADE #{self.trade_count}: {buy_side} {aq:.1f}×${ap:.3f} | "
                  f"z={buy_z:+.1f} | Kelly={kelly_f:.3f} | MGP ${mgp_new:.2f}{lock_tag}")

        self._record_history()
        return trades_made

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
