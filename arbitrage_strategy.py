#!/usr/bin/env python3
"""
Dynamic Delta Neutral Arbitrage Strategy v3 – MGP-First Logic

Binary Outcome Market Rules:
  - Asset_UP + Asset_DOWN = $1.00 at resolution
  - Bot NEVER sells, only buys to balance the portfolio
  - Goal: Arbitrage Locked state where total_cost < settlement_value

Core Principle – Minimum Guaranteed Profit (MGP):
  settlement_value = min(qty_up, qty_down) × $1.00
  total_cost       = cost_up + cost_down
  fees             = total_cost × 1.5 %
  MGP              = settlement_value − total_cost − fees

  When buying x shares of the SMALLER side at price p:
    ΔMGP = x × (1 − 1.015 × p)
  This is ALWAYS positive when p < $0.985 (i.e. almost always).
  ⇒ Buying the smaller side at any reasonable price raises the floor.
  ⇒ Optimal qty = qty_larger − qty_smaller  (perfect balance)

Decision Flow (every tick):
  1. SpreadEngine.update(up, down) → z-score, signal, position_delta
  2. MGP Calculator decides:
     a. ENTRY       – first trade, buy cheaper side
     b. MGP_LOCK    – buy smaller side to make BOTH scenarios ≥ 0 ASAP
     c. MGP_MAX     – once locked, keep improving the floor
     d. REBALANCE   – emergency if delta drifts too far
  3. Size is the EXACT qty that maximises MGP within budget/risk limits
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

# Fee rate (Polymarket ~1.5 % effective)
FEE_RATE = 0.015
FEE_MULT = 1.0 + FEE_RATE   # 1.015


class ArbitrageStrategy:
    """MGP-Optimised Delta Neutral Arbitrage for Polymarket binary markets."""

    def __init__(self, market_budget: float, starting_balance: float, exec_sim: ExecutionSimulator = None):
        self.market_budget = market_budget
        self.starting_balance = starting_balance
        self.cash_ref = {'balance': starting_balance}

        # ── Position tracking ──
        self.qty_up = 0.0
        self.qty_down = 0.0
        self.cost_up = 0.0
        self.cost_down = 0.0

        # ── SpreadEngine ── (shorter lookback for 15-min markets)
        self.spread_engine = SpreadEngine(
            lookback=60,
            beta_lookback=30,
            entry_z=2.0,
            exit_z=0.0,
            max_z=4.0,
            hysteresis=0.2,
            bb_k=2.0,
        )

        # ── Trading parameters ──
        self.min_trade_size = 1.0        # Polymarket minimum ~$1
        self.max_single_trade = 5.0      # Default for incremental trades
        self.max_shares_per_order = 200  # Allow large fills for profit-locking
        self.api_rate_limit = 0.5        # 0.5s — only to avoid API throttle, NOT a trading cooldown
        self.last_trade_time = 0

        # ── Delta Neutral parameters ──
        self.target_delta_pct = 0.0
        self.max_allowed_delta_pct = 5.0
        self.critical_delta_pct = 10.0
        self.emergency_delta_pct = 20.0
        self.rebalance_target_delta_pct = 2.0

        # ── Entry / Price limits ──
        self.max_entry_price = 0.60      # Allow entry up to $0.60 per side
        self.preferred_entry_price = 0.50
        self.ideal_entry_price = 0.45

        # ── Paired entry ── (buy both sides simultaneously)
        # Polymarket UP+DOWN always sums to ~$1.00 due to market efficiency.
        # We profit when combined < $1.00 minus fees (~1.5%).
        # So max_combined = $0.985 gives ~1.5 cent profit per matched share.
        self.max_combined_entry = 0.995  # Enter as long as combined < $0.995
        self.min_time_to_enter = 120     # Enter up to 2 min before close

        # ── MGP-specific limits ──
        self.mgp_max_price = 0.65        # Max price when MGP-balancing (raised for aggressive recovery)
        self.mgp_budget_fraction = 0.40  # Budget fraction for MGP lock trades (doubled)

        # ── Risk management ──
        self.max_position_pct = 1.00     # Full budget available when locking profit
        self.min_reserve_cash = 0.0      # No reserve — profit-locking uses everything
        self.max_loss_per_market = 10.0  # Max $10 loss per market

        # ── Pair cost limits ──
        # pair_cost = avg_up + avg_down; must stay < $1.00 for profit
        # After ~1.5% Polymarket fees, need pair_cost < ~0.985 to break even
        self.max_pair_cost = 0.995       # Hard ceiling for hedge pair_cost
        self.warning_pair_cost = 0.97
        self.profitable_pair_cost = 0.99 # Below this = likely profit after fees
        # Accumulation cooldown
        self.accumulate_cooldown = 60    # Seconds between accumulate trades
        self._last_accumulate_time = 0

        # ── Profit lock threshold ──
        self.profit_lock_threshold = 0.50   # Only stop trading when MGP > $0.50
        self.min_invested_to_lock = 0.10   # Need 10% invested before we stop

        # (Hedge uses same api_rate_limit — no separate cooldown needed)

        # ── Paired buy limit ──
        # Max 2 paired buys per market, ~$50 each
        self.paired_buy_count = 0
        self.max_paired_buys = 2
        self.paired_buy_budget = 50.0  # $50 per paired buy

        # ── State ──
        self.market_status = 'open'
        self.trade_count = 0
        self.trade_log: List[dict] = []
        self.payout = 0.0
        self.last_fees_paid = 0.0

        # ── Mode tracking ──
        self.current_mode = 'seeking_arb'
        self.mode_reason = 'Warming up SpreadEngine'

        # ── Price tracking for reactive logic ──
        self._prev_up_price = 0.0
        self._prev_down_price = 0.0

        # ── Legacy spread (UI compat) ──
        self.spread_history: deque = deque(maxlen=20)
        self.avg_spread = 0.0

        # ── MGP history for UI charting ──
        self.mgp_history: deque = deque(maxlen=120)  # ~2 min at 1s ticks
        self.pnl_up_history: deque = deque(maxlen=120)
        self.pnl_down_history: deque = deque(maxlen=120)

        # ── Execution Simulator (realistic fills) ──
        # Use shared instance if provided, so stats persist across markets
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
    #  MGP CALCULATOR  –  The Heart of the Strategy
    # ═══════════════════════════════════════════════════════════════

    def mgp_after_buy(self, side: str, price: float, qty: float) -> float:
        """
        Compute MGP AFTER a hypothetical buy of `qty` shares of `side` at `price`.

        Uses the MGP formula:
          new_mgp = min(new_qty_up, new_qty_down) − (new_total_cost) × FEE_MULT
        """
        cost = price * qty
        new_qty_up = self.qty_up + (qty if side == 'UP' else 0)
        new_qty_down = self.qty_down + (qty if side == 'DOWN' else 0)
        new_total_cost = self.cost_up + self.cost_down + cost
        return min(new_qty_up, new_qty_down) - new_total_cost * FEE_MULT

    def mgp_improvement(self, side: str, price: float, qty: float) -> float:
        """How much does MGP improve if we buy `qty` of `side` at `price`?"""
        current_mgp = self.calculate_locked_profit()
        new_mgp = self.mgp_after_buy(side, price, qty)
        return new_mgp - current_mgp

    def deficit(self) -> float:
        """Qty gap between larger and smaller side."""
        return abs(self.qty_up - self.qty_down)

    def smaller_side(self) -> str:
        """Which side has fewer shares?"""
        if self.qty_up <= self.qty_down:
            return 'UP'
        return 'DOWN'

    def larger_side(self) -> str:
        if self.qty_up >= self.qty_down:
            return 'UP'
        return 'DOWN'

    def mgp_optimal_qty(self, side: str, price: float, budget: float) -> float:
        """
        Compute the MGP-optimal number of shares to buy.

        For the SMALLER side:
          Each share bought increases MGP by (1 − FEE_MULT × p).
          Optimal qty = deficit (to reach perfect balance), capped by budget.
          Buying PAST balance still doesn't help MGP (other side becomes min).

        For the LARGER side:
          Buying increases cost but NOT settlement_value.
          MGP decreases.  Only buy if needed for avg-cost improvement.
          ⇒ return 0
        """
        if side == self.larger_side() and self.deficit() > 0.5:
            return 0.0  # Never buy the larger side for MGP

        # MGP benefit per share
        benefit_per_share = 1.0 - FEE_MULT * price
        if benefit_per_share <= 0:
            return 0.0  # Price too high, buying hurts MGP

        # Target qty: close the deficit
        target = self.deficit() if side == self.smaller_side() else 0.0

        # Also consider fractional fills when budget is limited
        max_qty_by_budget = budget / price if price > 0 else 0
        max_qty_by_trade = self.max_single_trade / price if price > 0 else 0

        qty = min(target, max_qty_by_budget, max_qty_by_trade)
        return max(0.0, qty)

    def max_price_for_positive_mgp(self) -> float:
        """
        Maximum price we can pay for the smaller side such that
        after buying enough to balance, MGP ≥ 0.

        Derivation:
          MGP_balanced = qty_larger − (total_cost + deficit × p) × FEE_MULT ≥ 0
          qty_larger ≥ (total_cost + deficit × p) × FEE_MULT
          p ≤ (qty_larger / FEE_MULT − total_cost) / deficit
        """
        d = self.deficit()
        if d <= 0:
            return 0.99  # Already balanced

        larger_qty = max(self.qty_up, self.qty_down)
        total_cost = self.cost_up + self.cost_down

        numerator = larger_qty / FEE_MULT - total_cost
        if numerator <= 0:
            return 0.0  # Can't achieve positive MGP

        p_max = numerator / d
        return min(p_max, 0.99)

    def both_scenarios_positive(self) -> bool:
        """Are BOTH pnl_if_up and pnl_if_down ≥ 0?  ⇒ Arbitrage Locked!"""
        return (self.calculate_pnl_if_up_wins() >= 0 and
                self.calculate_pnl_if_down_wins() >= 0)

    # ═══════════════════════════════════════════════════════════════
    #  BALANCE STATUS
    # ═══════════════════════════════════════════════════════════════

    def get_balance_status(self) -> Dict:
        delta = self.position_delta_pct
        direction = self.position_delta_direction
        if self.both_scenarios_positive():
            status, color, icon = "ARB LOCKED", "cyan", "🔒"
        elif delta <= self.max_allowed_delta_pct:
            status, color, icon = "BALANCED", "green", "✅"
        elif delta <= self.critical_delta_pct:
            status, color, icon = "OK", "yellow", "⚠️"
        elif delta <= self.emergency_delta_pct:
            status, color, icon = "MUST REBALANCE", "orange", "🔴"
        else:
            status, color, icon = "CRITICAL", "red", "🚨"
        return {'delta_pct': delta, 'direction': direction,
                'status': status, 'color': color, 'icon': icon}

    def _qty_needed_to_rebalance(self, target_delta_pct: float, side: str) -> float:
        if side == 'UP':
            smaller, larger = self.qty_up, self.qty_down
        else:
            smaller, larger = self.qty_down, self.qty_up
        if larger <= 0:
            return 0.0
        t = max(0.0, target_delta_pct) / 100.0
        needed = (larger - smaller - t * (larger + smaller)) / (1.0 + t)
        return max(0.0, needed)

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

    # Legacy compat
    def calculate_spread(self, up_price: float, down_price: float) -> float:
        spread = abs(1.0 - up_price - down_price)
        self.spread_history.append(spread)
        if self.spread_history:
            self.avg_spread = sum(self.spread_history) / len(self.spread_history)
        return spread

    def is_spread_favorable(self, spread: float) -> bool:
        return spread > 0.15

    def is_spread_extreme(self, spread: float) -> bool:
        return spread > 0.25

    # ═══════════════════════════════════════════════════════════════
    #  TRADING DECISION – should_buy()
    #
    #  Priority order (Gemini prompt):
    #   0. EMERGENCY REBALANCE  (delta > threshold)
    #   1. ENTRY                (no position)
    #   2. MGP LOCK             (make both scenarios ≥ 0 ASAP)
    #   3. MGP MAXIMIZE         (improve the floor)
    #   4. SPREAD SIGNAL        (SpreadEngine z-score)
    #   5. AVG IMPROVEMENT      (lower cost basis)
    # ═══════════════════════════════════════════════════════════════

    def should_buy(self, side: str, price: float, other_price: float,
                   se_info: dict = None, time_to_close: float = None) -> Tuple[bool, float, str]:
        if self.market_status != 'open':
            return False, 0, "Market not open"

        if se_info is None:
            if side == 'UP':
                se_info = self._feed_spread_engine(price, other_price)
            else:
                se_info = self._feed_spread_engine(other_price, price)

        delta = self.position_delta_pct
        z = se_info.get('z_score', 0.0)
        beta = se_info.get('beta', 1.0)

        my_qty = self.qty_up if side == 'UP' else self.qty_down
        my_cost = self.cost_up if side == 'UP' else self.cost_down
        other_qty = self.qty_down if side == 'UP' else self.qty_up
        other_cost = self.cost_down if side == 'UP' else self.cost_up

        now = time.time()
        # Minimal API rate-limit guard — NOT a trading cooldown
        if now - self.last_trade_time < self.api_rate_limit:
            return False, 0, "API rate limit (0.5s)"
        is_hedge_candidate = (my_qty == 0 and other_qty > 0)

        total_cost = self.cost_up + self.cost_down
        remaining_budget = max(0, self.market_budget - total_cost)
        current_mgp = self.calculate_locked_profit()
        combined_price = price + other_price

        # ──────────────────────────────────────────────────────────
        #  BUDGET RULE: If a trade would lock profit (MGP > 0),
        #  the bot may spend up to the FULL $100 market budget.
        #  No sub-limits, no fractions — just lock the profit.
        # ──────────────────────────────────────────────────────────

        # ──────────────────────────────────────────────────────────
        #  PHASE 0 – EMERGENCY REBALANCE
        #  Only for TWO-SIDED positions where delta drifted high.
        #  ONE-SIDED positions (one side has 0 qty) go to Phase 2.
        #  KEY: Use MGP improvement check, NOT combined price gate.
        #  Combined price is irrelevant — we only care if buying
        #  the smaller side improves MGP (it almost always does).
        # ──────────────────────────────────────────────────────────
        has_both_sides = self.qty_up > 0 and self.qty_down > 0
        if delta > self.max_allowed_delta_pct and has_both_sides:
            smaller = self.smaller_side()
            if side != smaller:
                return False, 0, f"Rebal: need {smaller}"

            # Price sanity — don't buy if price is very high
            p_max = self.max_price_for_positive_mgp()
            if price > p_max:
                return False, 0, f"Rebalance: ${price:.3f} > max lock price ${p_max:.3f}"

            target_qty = self.deficit()

            # Check if buying full deficit would lock profit
            full_mgp = self.mgp_after_buy(side, price, target_qty)
            full_cost = target_qty * price

            if full_mgp >= 0 and full_cost <= remaining_budget and full_cost <= self.cash:
                # PROFIT LOCK — use full budget, no sub-limits
                qty = target_qty
            elif current_mgp < 0:
                # MGP NEGATIVE — aggressive rebalance, scale by how negative
                urgency = min(1.0, abs(current_mgp) / 5.0)  # 0..1 scale
                budget_pct = 0.30 + 0.50 * urgency  # 30%..80% of remaining
                budget_cap = remaining_budget * budget_pct
                max_by_budget = budget_cap / price if price > 0 else 0
                qty = min(target_qty, max_by_budget)
            else:
                # Conservative — fractional budget
                budget_cap = remaining_budget * 0.30
                max_by_budget = budget_cap / price if price > 0 else 0
                qty = min(target_qty, max_by_budget, self.max_single_trade / price)

            qty = max(0, qty)

            # Ensure minimum trade size
            if qty * price < self.min_trade_size:
                qty = self.min_trade_size / price
                if qty * price > remaining_budget:
                    return False, 0, "Budget too low for rebalance"

            new_mgp = self.mgp_after_buy(side, price, qty)
            if new_mgp <= current_mgp:
                return False, 0, f"Rebalance would not improve MGP"

            lock_tag = ' 🔒 PROFIT LOCKED' if new_mgp >= 0 else ''
            self.current_mode = 'rebalancing'
            self.mode_reason = f'⚖️ Δ {delta:.1f}% → balance | MGP ${current_mgp:.2f}→${new_mgp:.2f}{lock_tag}'
            return True, qty, f"⚖️ REBALANCE {side} {qty:.1f}×${price:.3f} | MGP ${current_mgp:.2f}→${new_mgp:.2f}{lock_tag}"

        # ──────────────────────────────────────────────────────────
        #  PHASE 1 – INITIAL ENTRY  (no position)
        #  Sequential entry: only buy cheap side IF the other side
        #  is hedgeable (combined < max_pair_cost).
        #  Paired entry in check_and_trade handles the better case.
        # ──────────────────────────────────────────────────────────
        if my_qty == 0 and other_qty == 0:
            # Time filter — don't enter late
            if time_to_close is not None and time_to_close < self.min_time_to_enter:
                return False, 0, f"Too late ({time_to_close:.0f}s left)"

            if price > self.max_entry_price:
                return False, 0, f"Price ${price:.2f} > max entry ${self.max_entry_price}"

            # CRITICAL: Don't buy one side if hedge would be too expensive
            if combined_price > self.max_pair_cost:
                return False, 0, f"Combined ${combined_price:.3f} > max pair ${self.max_pair_cost} — can't hedge"

            # Smaller initial position — less risk
            if price <= self.ideal_entry_price:
                spend = min(8.0, remaining_budget * 0.04)
            elif price <= self.preferred_entry_price:
                spend = min(6.0, remaining_budget * 0.03)
            else:
                spend = min(4.0, remaining_budget * 0.02)

            if spend < self.min_trade_size:
                return False, 0, "Insufficient budget"

            qty = spend / price
            self.current_mode = 'entry'
            self.mode_reason = f'Initial entry {side} @ ${price:.3f}'
            return True, qty, f"🎯 ENTRY {side} {qty:.1f}×${price:.3f}"

        # ──────────────────────────────────────────────────────────
        #  PHASE 2 – HEDGE / MGP LOCK
        #  Buy the other side to create a hedged position.
        #  Hedge — same API rate limit, no extra delay.
        # ──────────────────────────────────────────────────────────
        if my_qty == 0 and other_qty > 0:

            # This side has no position — we need to hedge
            other_avg = other_cost / other_qty if other_qty > 0 else 0
            potential_pair = price + other_avg

            if potential_pair > self.max_pair_cost:
                return False, 0, f"Hedge pair ${potential_pair:.3f} > max ${self.max_pair_cost}"

            # Match the other side's quantity — aggressive hedge to lock profit fast
            target_qty = other_qty
            cost_needed = target_qty * price

            # Check if full hedge would lock profit
            full_mgp = self.mgp_after_buy(side, price, target_qty)

            if full_mgp >= 0 and cost_needed <= remaining_budget and cost_needed <= self.cash:
                # PROFIT LOCK — buy full hedge, no sub-limits
                qty = target_qty
            else:
                # Conservative — fractional budget
                max_spend = min(cost_needed, remaining_budget * 0.50, self.cash * 0.25, self.max_single_trade)
                qty = max_spend / price if price > 0 else 0

            if qty * price < self.min_trade_size:
                return False, 0, "Budget too low for hedge"

            new_mgp = self.mgp_after_buy(side, price, qty)
            lock_tag = ' 🔒 PROFIT LOCKED' if new_mgp >= 0 else ''
            self.current_mode = 'hedge'
            self.mode_reason = f'🔒 Hedging @ pair ${potential_pair:.3f} | MGP ${new_mgp:.2f}{lock_tag}'
            return True, qty, f"🔒 HEDGE {side} {qty:.1f}×${price:.3f} | pair ${potential_pair:.3f} | MGP ${new_mgp:.2f}{lock_tag}"

        # ──────────────────────────────────────────────────────────
        #  PHASE 2b – MGP LOCK  (both sides exist, but MGP < 0)
        #  Buy smaller side to move toward positive MGP.
        #  AGGRESSIVE: No deficit gate, scale budget by MGP negativity.
        # ──────────────────────────────────────────────────────────
        if not self.both_scenarios_positive() and has_both_sides:
            smaller = self.smaller_side()
            if side != smaller:
                return False, 0, f"MGP Lock: need {smaller}, not {side}"

            p_max = self.max_price_for_positive_mgp()

            if price > min(p_max, self.mgp_max_price):
                return False, 0, f"MGP Lock: ${price:.3f} > p_max ${p_max:.3f}"

            # Don't push pair_cost above threshold
            my_avg = my_cost / my_qty if my_qty > 0 else price
            other_avg = other_cost / other_qty if other_qty > 0 else 0
            target_qty = max(self.deficit(), 1.0)  # At least 1 share even if balanced
            if my_qty > 0:
                est_new_avg = (my_cost + price * target_qty) / (my_qty + target_qty)
            else:
                est_new_avg = price
            est_pair = est_new_avg + other_avg if side == 'UP' else other_avg + est_new_avg
            if est_pair > self.max_pair_cost:
                return False, 0, f"MGP Lock would push pair to ${est_pair:.3f}"

            full_cost = target_qty * price

            # Check if buying full deficit would lock profit
            full_mgp = self.mgp_after_buy(side, price, target_qty)

            if full_mgp >= 0 and full_cost <= remaining_budget and full_cost <= self.cash:
                # PROFIT LOCK — buy full deficit in one go
                qty = target_qty
            else:
                # Scale budget by how negative MGP is — more urgent = bigger trades
                urgency = min(1.0, abs(current_mgp) / 3.0)  # 0..1
                budget_pct = self.mgp_budget_fraction + 0.40 * urgency  # 40%..80%
                budget_for_lock = remaining_budget * budget_pct
                max_by_budget = budget_for_lock / price if price > 0 else 0
                qty = min(target_qty, max_by_budget)

            if qty * price < self.min_trade_size:
                qty = self.min_trade_size / price
                if qty * price > remaining_budget:
                    return False, 0, "Budget too low for MGP lock"

            new_mgp = self.mgp_after_buy(side, price, qty)
            delta_mgp = new_mgp - current_mgp

            if delta_mgp <= 0:
                return False, 0, f"MGP Lock: no improvement (ΔMGP=${delta_mgp:.3f})"

            lock_tag = ' 🔒 PROFIT LOCKED' if new_mgp >= 0 else ''
            self.current_mode = 'mgp_lock'
            self.mode_reason = f'🔒 Locking MGP: ${current_mgp:.2f}→${new_mgp:.2f}{lock_tag}'
            return True, qty, f"🔒 MGP LOCK {side} {qty:.1f}×${price:.3f} | MGP ${current_mgp:.2f}→${new_mgp:.2f}{lock_tag}"

        # ──────────────────────────────────────────────────────────
        #  PHASE 2c – MGP RECOVERY (both sides, MGP < 0, balanced)
        #  When deficit is small but MGP is still negative, buy
        #  PAIRED to dilute avg cost and push MGP toward zero.
        #  Uses spread + position % to optimise size.
        # ──────────────────────────────────────────────────────────
        if has_both_sides and current_mgp < 0 and self.deficit() < 2.0:
            # Evaluate: is buying a pair at current price beneficial?
            pair_benefit = 1.0 - FEE_MULT * (price + other_price)
            if pair_benefit > 0 and price < 0.985:  # Each paired share adds this to MGP
                # Scale budget by MGP negativity and position utilisation
                invested_ratio = total_cost / self.market_budget if self.market_budget > 0 else 1
                room_left = max(0, 1.0 - invested_ratio)  # 0..1 how much budget remains
                urgency = min(1.0, abs(current_mgp) / 3.0)
                spend = remaining_budget * (0.10 + 0.25 * urgency) * min(1.0, room_left + 0.3)
                spend = min(spend, self.cash * 0.15, remaining_budget * 0.50)
                spend = max(spend, self.min_trade_size) if remaining_budget >= self.min_trade_size else 0

                if spend >= self.min_trade_size:
                    cost_per_share = price + other_price
                    qty = spend / cost_per_share if cost_per_share > 0 else 0
                    # Verify paired buy improves MGP
                    new_qty_min = min(my_qty + qty, other_qty + qty)
                    new_total = total_cost + qty * cost_per_share
                    new_mgp = new_qty_min - new_total * FEE_MULT
                    if new_mgp > current_mgp:
                        lock_tag = ' 🔒' if new_mgp >= 0 else ''
                        self.current_mode = 'mgp_recovery'
                        self.mode_reason = f'🔄 Recovery: paired buy @ ${cost_per_share:.3f} | MGP ${current_mgp:.2f}→${new_mgp:.2f}{lock_tag}'
                        # Return signal for BOTH sides — check_and_trade will use this
                        return True, qty, f"🔄 MGP RECOVERY {side} {qty:.1f}×${price:.3f} (paired) | MGP ${current_mgp:.2f}→${new_mgp:.2f}{lock_tag}"

        # ──────────────────────────────────────────────────────────
        #  PHASE 3 – Z-SCORE GUIDED IMPROVEMENT
        #  Buy the SMALLER side when z-score says it's cheap
        #  OR when MGP is negative and any purchase improves it.
        #  EVERY trade MUST improve MGP — no exceptions.
        # ──────────────────────────────────────────────────────────
        if my_qty > 0 and (self.qty_up + self.qty_down) > 0:
            my_avg = my_cost / my_qty if my_qty > 0 else price

            # CRITICAL: Only buy the SMALLER side (or equal side at low delta)
            is_smaller = side == self.smaller_side()
            is_balanced = self.deficit() < 1.0

            if not is_smaller and not is_balanced:
                # This is the larger side — skip
                pass
            else:
                # Z-score tells us if this side is cheap right now
                z_threshold = 1.5
                z_side_is_cheap = (
                    (side == 'UP' and z < -z_threshold) or
                    (side == 'DOWN' and z > z_threshold)
                )

                # Also buy if price is below our average (any discount helps)
                price_below_avg = price < my_avg * 0.97  # 3% discount (was 5%)

                # WHEN MGP < 0: buy smaller side at ANY price < 0.985
                # Every share of smaller side at p < 0.985 improves MGP
                mgp_negative_buy = (
                    current_mgp < 0
                    and is_smaller
                    and price < 0.985 / FEE_MULT  # price where benefit > 0
                )

                if z_side_is_cheap or price_below_avg or mgp_negative_buy:
                    # Scale spend: more aggressive when MGP is negative
                    if current_mgp < 0:
                        urgency = min(1.0, abs(current_mgp) / 3.0)
                        spend = min(remaining_budget * (0.08 + 0.15 * urgency), self.cash * 0.10)
                    else:
                        az = abs(z)
                        if az > 3.0:
                            spend = min(5.0, remaining_budget * 0.08)
                        elif az > 2.0:
                            spend = min(4.0, remaining_budget * 0.06)
                        else:
                            spend = min(3.0, remaining_budget * 0.04)

                    if spend < self.min_trade_size:
                        return False, 0, "Budget too low"

                    qty = spend / price if price > 0 else 0
                    new_mgp = self.mgp_after_buy(side, price, qty)

                    # HARD RULE: Every trade MUST improve MGP
                    if new_mgp > current_mgp:
                        new_avg = (my_cost + spend) / (my_qty + qty)
                        reason_tag = f"z={z:.1f}" if z_side_is_cheap else ("mgp_neg" if mgp_negative_buy else "discount")
                        self.current_mode = 'z_rebalance' if z_side_is_cheap else 'mgp_recovery'
                        self.mode_reason = f'📊 Buy {side} ({reason_tag}) avg ${my_avg:.3f}→${new_avg:.3f} | MGP ${current_mgp:.2f}→${new_mgp:.2f}'
                        return True, qty, f"📊 IMPROVE {side} {qty:.1f}×${price:.3f} ({reason_tag}) | avg ${my_avg:.3f}→${new_avg:.3f} | MGP ${current_mgp:.2f}→${new_mgp:.2f}"

        self.current_mode = 'seeking_arb'
        self.mode_reason = f'Monitoring | z={z:.2f} MGP=${current_mgp:.2f} pair=${combined_price:.3f}'
        return False, 0, "No signal"

    # ═══════════════════════════════════════════════════════════════
    #  EXECUTION
    # ═══════════════════════════════════════════════════════════════

    def execute_buy(self, side: str, price: float, qty: float,
                    timestamp: str = None) -> Tuple[bool, float, float]:
        """Returns (success, actual_fill_price, actual_fill_qty)"""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).strftime('%H:%M:%S')

        # ── Cap qty to order book depth to minimize slippage ──
        depth_cap = self._book_depth_cap.get(side, self.max_shares_per_order)
        original_qty = qty
        qty = min(qty, self.max_shares_per_order, depth_cap)
        if qty < original_qty:
            print(f"📏 [{side}] Size capped: {original_qty:.1f} → {qty:.1f} shares (book depth cap {depth_cap:.0f}, max {self.max_shares_per_order})")

        # ── Simulate realistic fill against order book ──
        orderbook = self._pending_orderbooks.get(side, {})
        fill = self.exec_sim.simulate_fill(side, price, qty, orderbook)

        if not fill.filled:
            print(f"❌ [{side}] ORDER REJECTED: {fill.reason}")
            return False, 0.0, 0.0

        # Use actual fill price and qty from simulator
        actual_price = fill.fill_price
        actual_qty = fill.filled_qty
        actual_cost = fill.total_cost

        if actual_cost > self.cash:
            return False, 0.0, 0.0

        # Log slippage if it occurred
        if fill.slippage > 0.00001:
            slip_dir = "WORSE" if fill.slippage > 0 else "BETTER"
            print(
                f"⚡ [{side}] SLIPPAGE: wanted ${price:.4f} → got ${actual_price:.4f} "
                f"({slip_dir} {fill.slippage_pct:+.3f}%, cost +${fill.slippage_cost:.4f}) "
                f"| {fill.levels_consumed} level(s) | latency {fill.latency_ms:.0f}ms"
            )
        if fill.partial:
            print(
                f"⚠️ [{side}] PARTIAL FILL: {actual_qty:.1f}/{qty:.1f} shares "
                f"({actual_qty/qty*100:.0f}%)"
            )

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
        if len(self.trade_log) > 50:
            self.trade_log = self.trade_log[-50:]
        return True, actual_price, actual_qty

    # ═══════════════════════════════════════════════════════════════
    #  MAIN TRADING LOOP
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

        # Store orderbooks for execute_buy() to use
        self._pending_orderbooks['UP'] = up_orderbook or {}
        self._pending_orderbooks['DOWN'] = down_orderbook or {}

        # Dynamically cap order sizes based on order book depth
        for ob_side, ob in [('UP', up_orderbook), ('DOWN', down_orderbook)]:
            if ob and ob.get('asks'):
                best_ask_size = 0
                try:
                    asks_sorted = sorted(ob['asks'], key=lambda a: float(a.get('price', 99)))
                    # Use liquidity within 1% of best ask as safe fill zone
                    best_price = float(asks_sorted[0].get('price', 0))
                    for a in asks_sorted:
                        p = float(a.get('price', 0))
                        if p <= best_price * 1.01:  # within 1% of best
                            best_ask_size += float(a.get('size', 0))
                except (ValueError, IndexError):
                    pass
                if best_ask_size > 0:
                    # Cap at 50% of near-touch liquidity to avoid walking the book
                    self._book_depth_cap[ob_side] = best_ask_size * 0.50
                else:
                    self._book_depth_cap[ob_side] = self.max_shares_per_order

        # 1. Feed SpreadEngine
        se_info = self._feed_spread_engine(up_price, down_price)

        # 2. Stop-loss (based on MGP)
        mgp = self.calculate_locked_profit()
        if mgp < -self.max_loss_per_market and (self.qty_up + self.qty_down) > 0:
            print(f"🛑 STOP LOSS: MGP ${mgp:.2f} < -${self.max_loss_per_market:.2f}")
            self.market_status = 'stopped'
            return trades_made

        combined_price = up_price + down_price
        total_invested = self.cost_up + self.cost_down
        remaining_budget = max(0, self.market_budget - total_invested)

        # ════════════════════════════════════════════════════════
        #  MAX 2 PAIRED BUYS PER MARKET
        #  Each buy uses ~$50 when pair cost < $1.00.
        #  After 2 buys, just hold until resolution.
        # ════════════════════════════════════════════════════════
        if self.paired_buy_count >= self.max_paired_buys:
            self.current_mode = 'holding'
            self.mode_reason = f'🔒 {self.paired_buy_count}/{self.max_paired_buys} paired buys done | MGP ${mgp:.2f}'
            if self.qty_up + self.qty_down > 0:
                self.mgp_history.append(self.calculate_locked_profit())
                self.pnl_up_history.append(self.calculate_pnl_if_up_wins())
                self.pnl_down_history.append(self.calculate_pnl_if_down_wins())
            return trades_made

        # ════════════════════════════════════════════════════════
        #  PAIRED BUY — Buy both sides simultaneously
        #  ~$50 per buy, only when combined < max_combined_entry.
        #  Works for both initial entry and second buy.
        # ════════════════════════════════════════════════════════
        if combined_price <= self.max_combined_entry:
            # Time filter: don't start new positions too late
            if time_to_close is not None and time_to_close < self.min_time_to_enter:
                self.current_mode = 'too_late'
                self.mode_reason = f'Only {time_to_close:.0f}s left — skipping market'
                return trades_made

            # Use $50 (or remaining budget/cash, whichever is less)
            budget = min(self.paired_buy_budget, remaining_budget, self.cash)
            cost_per_share = up_price + down_price
            qty = budget / cost_per_share if cost_per_share > 0 else 0
            total_cost = qty * cost_per_share

            if total_cost >= self.min_trade_size and total_cost <= self.cash:
                # ── Check book depth on BOTH sides before buying ──
                # Ensure we buy EQUAL qty on both sides for balanced position.
                # Cap qty to the minimum available liquidity across both books.
                up_depth = self._book_depth_cap.get('UP', self.max_shares_per_order)
                down_depth = self._book_depth_cap.get('DOWN', self.max_shares_per_order)
                max_balanced_qty = min(up_depth, down_depth, self.max_shares_per_order)

                if qty > max_balanced_qty:
                    print(f"📏 BALANCED CAP: {qty:.1f} → {max_balanced_qty:.1f} shares (UP depth {up_depth:.0f}, DOWN depth {down_depth:.0f})")
                    qty = max_balanced_qty
                    total_cost = qty * cost_per_share

                if qty < self.min_trade_size / cost_per_share:
                    print(f"⚠️ SKIPPED: insufficient balanced liquidity (UP={up_depth:.0f}, DOWN={down_depth:.0f})")
                elif total_cost > self.cash:
                    print(f"⚠️ SKIPPED: balanced qty cost ${total_cost:.2f} > cash ${self.cash:.2f}")
                else:
                    # Verify it improves MGP (or is first entry)
                    new_qty_up = self.qty_up + qty
                    new_qty_down = self.qty_down + qty
                    new_total_cost = total_invested + total_cost
                    new_mgp = min(new_qty_up, new_qty_down) - new_total_cost * FEE_MULT

                    if new_mgp > mgp or (self.qty_up == 0 and self.qty_down == 0):
                        buy_num = self.paired_buy_count + 1
                        print(f"🎯 PAIRED BUY #{buy_num}: budget=${budget:.2f} qty={qty:.1f} combined=${combined_price:.3f} cash=${self.cash:.2f}")
                        ok_u, ap_u, aq_u = self.execute_buy('UP', up_price, qty, timestamp)
                        if ok_u:
                            trades_made.append(('UP', ap_u, aq_u))
                            # Cap DOWN qty to what UP actually filled for perfect balance
                            balanced_qty = min(qty, aq_u)
                        else:
                            balanced_qty = 0

                        if balanced_qty > 0:
                            ok_d, ap_d, aq_d = self.execute_buy('DOWN', down_price, balanced_qty, timestamp)
                            if ok_d:
                                trades_made.append(('DOWN', ap_d, aq_d))
                        else:
                            print(f"⚠️ UP fill failed — skipping DOWN to stay balanced")

                        self.paired_buy_count += 1
                        actual_mgp = self.calculate_locked_profit()
                        self.current_mode = 'paired_entry' if buy_num == 1 else 'paired_growth'
                        self.mode_reason = f'Paired buy #{buy_num}/{self.max_paired_buys} @ combined ${combined_price:.3f} | MGP ${actual_mgp:.2f}'
                        print(f"🎯 PAIRED BUY #{buy_num}: {qty:.1f} shares each | combined ${combined_price:.3f} | MGP ${actual_mgp:.2f}")
            else:
                print(f"⚠️ ENTRY BLOCKED: budget=${budget:.2f} total_cost=${total_cost:.2f} cash=${self.cash:.2f} min_trade=${self.min_trade_size}")
        else:
            self.current_mode = 'waiting'
            self.mode_reason = f'Combined ${combined_price:.3f} > max ${self.max_combined_entry} — waiting'

        # Track prices for reactive logic
        self._prev_up_price = up_price
        self._prev_down_price = down_price

        # Record MGP history for UI charting
        if self.qty_up + self.qty_down > 0:
            self.mgp_history.append(self.calculate_locked_profit())
            self.pnl_up_history.append(self.calculate_pnl_if_up_wins())
            self.pnl_down_history.append(self.calculate_pnl_if_down_wins())

        return trades_made

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
            # SpreadEngine history arrays for UI charting
            'z_history': se.get('z_history', []),
            'spread_history_arr': se.get('spread_history', []),
            'bb_upper_history': se.get('bb_upper_history', []),
            'bb_lower_history': se.get('bb_lower_history', []),
            'signal_history': se.get('signal_history', []),
            # Execution simulator stats (slippage, latency, fill quality)
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
