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

# Fee rate (Polymarket ~1.5 % effective)
FEE_RATE = 0.015
FEE_MULT = 1.0 + FEE_RATE   # 1.015


class ArbitrageStrategy:
    """MGP-Optimised Delta Neutral Arbitrage for Polymarket binary markets."""

    def __init__(self, market_budget: float, starting_balance: float):
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
        self.max_single_trade = 15.0     # Smaller trades = less risk
        self.cooldown_seconds = 15       # 15s between trades — reduce overtrading
        self.last_trade_time = 0

        # ── Delta Neutral parameters ──
        self.target_delta_pct = 0.0
        self.max_allowed_delta_pct = 5.0
        self.critical_delta_pct = 10.0
        self.emergency_delta_pct = 20.0
        self.rebalance_target_delta_pct = 2.0

        # ── Entry / Price limits ──
        self.max_entry_price = 0.48      # Max price for ONE side on sequential entry
        self.preferred_entry_price = 0.43
        self.ideal_entry_price = 0.38

        # ── Paired entry ── (buy both sides simultaneously)
        # Polymarket UP+DOWN always sums to ~$1.00 due to market efficiency.
        # We profit when combined < $1.00 minus fees (~1.5%).
        # So max_combined = $0.985 gives ~1.5 cent profit per matched share.
        self.max_combined_entry = 0.985  # Realistic: UP+DOWN < this for paired entry
        self.min_time_to_enter = 420     # Need 7 min (420s) left for new entries

        # ── MGP-specific limits ──
        self.mgp_max_price = 0.55        # Max price when MGP-balancing
        self.mgp_budget_fraction = 0.15  # Budget fraction for MGP lock trades

        # ── Risk management ──
        self.max_position_pct = 0.35     # Limit exposure per market
        self.min_reserve_cash = 20.0
        self.max_loss_per_market = 20.0  # Tighter stop-loss

        # ── Pair cost limits ──
        # pair_cost = avg_up + avg_down; must stay < $1.00 for profit
        # After ~1.5% Polymarket fees, need pair_cost < ~0.985 to break even
        self.max_pair_cost = 0.99        # Hard ceiling for hedge pair_cost
        self.warning_pair_cost = 0.96
        self.profitable_pair_cost = 0.98 # Below this = likely profit after fees
        # Accumulation cooldown
        self.accumulate_cooldown = 60    # Seconds between accumulate trades
        self._last_accumulate_time = 0

        # ── Profit lock threshold ──
        self.profit_lock_threshold = 0.50   # MGP must exceed this to lock
        self.min_invested_to_lock = 0.10   # Must have spent 10% of budget before locking

        # ── Hedge bypass cooldown ──
        self.hedge_cooldown_seconds = 3   # Hedge allowed faster than normal trades

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
        # Normal cooldown — but Phase 2 (hedge) has its own shorter cooldown
        is_hedge_candidate = (my_qty == 0 and other_qty > 0)
        if not is_hedge_candidate:
            if now - self.last_trade_time < self.cooldown_seconds and delta <= self.critical_delta_pct:
                return False, 0, "Cooldown active"

        total_cost = self.cost_up + self.cost_down
        budget_limit = self.starting_balance * self.max_position_pct
        remaining_budget = max(0, budget_limit - total_cost)
        current_mgp = self.calculate_locked_profit()
        combined_price = price + other_price

        # ──────────────────────────────────────────────────────────
        #  GLOBAL GUARD: If profit is locked with meaningful position, STOP.
        # ──────────────────────────────────────────────────────────
        invested_pct = total_cost / (self.starting_balance * self.max_position_pct) if self.starting_balance > 0 else 0
        if self.both_scenarios_positive() and current_mgp > self.profit_lock_threshold and invested_pct >= self.min_invested_to_lock:
            return False, 0, f"Profit locked ${current_mgp:.2f} — holding"

        # ──────────────────────────────────────────────────────────
        #  PHASE 0 – EMERGENCY REBALANCE
        #  Only for TWO-SIDED positions where delta drifted high.
        #  ONE-SIDED positions (one side has 0 qty) go to Phase 2.
        # ──────────────────────────────────────────────────────────
        has_both_sides = self.qty_up > 0 and self.qty_down > 0
        if delta > self.max_allowed_delta_pct and has_both_sides:
            smaller = self.smaller_side()
            if side != smaller:
                return False, 0, f"Rebal: need {smaller}"

            # Don't rebalance if it would create terrible pair_cost
            potential_pair = price + other_price
            if potential_pair > 0.98:
                return False, 0, f"Rebalance pair ${potential_pair:.3f} too expensive"

            if price > 0.60:
                return False, 0, f"Rebalance price ${price:.2f} too high"

            target_qty = self.deficit()
            budget_cap = remaining_budget * 0.20
            max_by_budget = budget_cap / price if price > 0 else 0
            qty = min(target_qty, max_by_budget, self.max_single_trade / price)
            qty = max(0, qty)

            if qty * price < self.min_trade_size:
                return False, 0, "Budget too low for rebalance"

            new_mgp = self.mgp_after_buy(side, price, qty)
            self.current_mode = 'rebalancing'
            self.mode_reason = f'⚖️ Δ {delta:.1f}% → balance | MGP ${current_mgp:.2f}→${new_mgp:.2f}'
            return True, qty, f"⚖️ REBALANCE {side} {qty:.1f}×${price:.3f} | MGP ${current_mgp:.2f}→${new_mgp:.2f}"

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
                spend = min(12.0, remaining_budget * 0.06)
            elif price <= self.preferred_entry_price:
                spend = min(8.0, remaining_budget * 0.04)
            else:
                spend = min(5.0, remaining_budget * 0.03)

            if spend < self.min_trade_size:
                return False, 0, "Insufficient budget"

            qty = spend / price
            self.current_mode = 'entry'
            self.mode_reason = f'Initial entry {side} @ ${price:.3f}'
            return True, qty, f"🎯 ENTRY {side} {qty:.1f}×${price:.3f}"

        # ──────────────────────────────────────────────────────────
        #  PHASE 2 – HEDGE / MGP LOCK
        #  Buy the other side to create a hedged position.
        #  Hedge is EXEMPT from normal cooldown (uses hedge_cooldown).
        # ──────────────────────────────────────────────────────────
        if my_qty == 0 and other_qty > 0:
            # Override cooldown for hedge — we must hedge quickly
            if now - self.last_trade_time < self.hedge_cooldown_seconds:
                return False, 0, "Hedge cooldown active"

            # This side has no position — we need to hedge
            other_avg = other_cost / other_qty if other_qty > 0 else 0
            potential_pair = price + other_avg

            if potential_pair > self.max_pair_cost:
                return False, 0, f"Hedge pair ${potential_pair:.3f} > max ${self.max_pair_cost}"

            # Match the other side's quantity for perfect balance
            target_qty = other_qty
            cost_needed = target_qty * price
            max_spend = min(cost_needed, remaining_budget * 0.50, self.cash * 0.30)
            qty = max_spend / price if price > 0 else 0

            if qty * price < self.min_trade_size:
                return False, 0, "Budget too low for hedge"

            new_mgp = self.mgp_after_buy(side, price, qty)
            self.current_mode = 'hedge'
            self.mode_reason = f'🔒 Hedging @ pair ${potential_pair:.3f} | MGP ${new_mgp:.2f}'
            return True, qty, f"🔒 HEDGE {side} {qty:.1f}×${price:.3f} | pair ${potential_pair:.3f} | MGP ${new_mgp:.2f}"

        # ──────────────────────────────────────────────────────────
        #  PHASE 2b – MGP LOCK  (both sides exist, but MGP < 0)
        #  Buy smaller side to move toward positive MGP.
        #  Only if price is low enough to actually help.
        # ──────────────────────────────────────────────────────────
        if not self.both_scenarios_positive() and self.deficit() > 0.5:
            smaller = self.smaller_side()
            if side != smaller:
                return False, 0, f"MGP Lock: need {smaller}, not {side}"

            p_max = self.max_price_for_positive_mgp()

            if price > min(p_max, self.mgp_max_price):
                return False, 0, f"MGP Lock: ${price:.3f} > p_max ${p_max:.3f}"

            # Don't push pair_cost above threshold
            my_avg = my_cost / my_qty if my_qty > 0 else price
            other_avg = other_cost / other_qty if other_qty > 0 else 0
            # Estimate new pair_cost: buying smaller side brings avg down
            if my_qty > 0:
                est_new_avg = (my_cost + price * self.deficit()) / (my_qty + self.deficit())
            else:
                est_new_avg = price
            est_pair = est_new_avg + other_avg if side == 'UP' else other_avg + est_new_avg
            if est_pair > self.max_pair_cost:
                return False, 0, f"MGP Lock would push pair to ${est_pair:.3f}"

            target_qty = self.deficit()
            budget_for_lock = remaining_budget * self.mgp_budget_fraction
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

            self.current_mode = 'mgp_lock'
            self.mode_reason = f'🔒 Locking MGP: ${current_mgp:.2f}→${new_mgp:.2f}'
            return True, qty, f"🔒 MGP LOCK {side} {qty:.1f}×${price:.3f} | MGP ${current_mgp:.2f}→${new_mgp:.2f}"

        # ──────────────────────────────────────────────────────────
        #  PHASE 3 – SELECTIVE IMPROVEMENT
        #  Only buy if ALL conditions met:
        #    1. Price significantly below avg (>8% discount)
        #    2. It improves locked profit
        #    3. Pair cost stays under threshold
        #    4. Side is the smaller (or equal) side
        # ──────────────────────────────────────────────────────────
        if my_qty > 0 and my_cost > 0 and (self.qty_up + self.qty_down) > 0:
            my_avg = my_cost / my_qty
            discount_pct = (my_avg - price) / my_avg if my_avg > 0 else 0

            # Only improve if significant discount AND it's the smaller/equal side
            if discount_pct > 0.08:
                # Don't improve the larger side (makes delta worse)
                if side == self.position_delta_direction and delta > 3.0:
                    return False, 0, "Larger side – skip improvement"

                spend = min(5.0, remaining_budget * 0.03)
                if spend < self.min_trade_size:
                    return False, 0, "Budget too low"

                qty = spend / price
                new_mgp = self.mgp_after_buy(side, price, qty)
                if new_mgp <= current_mgp:
                    return False, 0, "Improvement would not raise MGP"

                new_avg = (my_cost + spend) / (my_qty + qty)
                self.current_mode = 'improving'
                self.mode_reason = f'Avg ${my_avg:.3f}→${new_avg:.3f} (+{discount_pct*100:.0f}% discount)'
                return True, qty, f"📉 IMPROVE {side} avg ${my_avg:.3f}→${new_avg:.3f} | MGP ${current_mgp:.2f}→${new_mgp:.2f}"

        self.current_mode = 'seeking_arb'
        self.mode_reason = f'Monitoring | z={z:.2f} MGP=${current_mgp:.2f} pair=${combined_price:.3f}'
        return False, 0, "No signal"

    # ═══════════════════════════════════════════════════════════════
    #  EXECUTION
    # ═══════════════════════════════════════════════════════════════

    def execute_buy(self, side: str, price: float, qty: float,
                    timestamp: str = None) -> bool:
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).strftime('%H:%M:%S')
        cost = price * qty
        if cost > self.cash:
            return False

        self.cash -= cost
        self.trade_count += 1
        self.last_trade_time = time.time()

        if side == 'UP':
            self.qty_up += qty
            self.cost_up += cost
        else:
            self.qty_down += qty
            self.cost_down += cost

        self.trade_log.append({
            'time': timestamp, 'side': 'BUY', 'token': side,
            'price': price, 'qty': qty, 'cost': cost
        })
        if len(self.trade_log) > 50:
            self.trade_log = self.trade_log[-50:]
        return True

    # ═══════════════════════════════════════════════════════════════
    #  MAIN TRADING LOOP
    # ═══════════════════════════════════════════════════════════════

    def check_and_trade(self, up_price: float, down_price: float,
                        timestamp: str,
                        time_to_close: float = None,
                        up_bid: Optional[float] = None,
                        down_bid: Optional[float] = None) -> List[Tuple[str, float, float]]:
        trades_made: List[Tuple[str, float, float]] = []

        if up_price <= 0 or down_price <= 0:
            return trades_made

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
        invested_pct = total_invested / (self.starting_balance * self.max_position_pct) if self.starting_balance > 0 else 0
        budget_limit = self.starting_balance * self.max_position_pct
        remaining_budget = max(0, budget_limit - total_invested)

        # ════════════════════════════════════════════════════════
        #  PROFIT LOCKED → Only do paired compounding
        #  Don't give back gains — but keep growing via safe pairs.
        # ════════════════════════════════════════════════════════
        position_is_locked = (
            self.both_scenarios_positive()
            and mgp > self.profit_lock_threshold
            and invested_pct >= self.min_invested_to_lock
        )
        if position_is_locked:
            # Still allow paired compounding if combined price is good
            if combined_price <= self.max_combined_entry:
                budget = min(self.market_budget * 0.10, self.cash * 0.10, remaining_budget * 0.20)
                cost_per_share = combined_price
                qty = budget / cost_per_share if cost_per_share > 0 else 0
                total_cost = qty * cost_per_share
                # Only compound if it actually improves MGP
                if qty > 0.5 and total_cost >= self.min_trade_size and total_cost <= self.cash:
                    # Simulate buying DOWN too
                    down_cost = down_price * qty
                    new_qty_down = self.qty_down + qty
                    new_total = self.cost_up + up_price * qty + self.cost_down + down_cost
                    new_mgp_full = min(self.qty_up + qty, new_qty_down) - new_total * FEE_MULT
                    if new_mgp_full > mgp:
                        if self.execute_buy('UP', up_price, qty, timestamp):
                            trades_made.append(('UP', up_price, qty))
                        if self.execute_buy('DOWN', down_price, qty, timestamp):
                            trades_made.append(('DOWN', down_price, qty))
                        print(f"📈 LOCKED COMPOUND: {qty:.1f} shares | MGP ${mgp:.2f}→${new_mgp_full:.2f}")

            self.current_mode = 'arbitrage_locked'
            self.mode_reason = f'🔒 Profit locked ${mgp:.2f} (invested {invested_pct*100:.0f}%)'
            if self.qty_up + self.qty_down > 0:
                self.mgp_history.append(self.calculate_locked_profit())
                self.pnl_up_history.append(self.calculate_pnl_if_up_wins())
                self.pnl_down_history.append(self.calculate_pnl_if_down_wins())
            return trades_made

        # ════════════════════════════════════════════════════════
        #  PAIRED ENTRY — Buy both sides simultaneously
        #  This is the BEST way to enter: guarantees pair_cost.
        # ════════════════════════════════════════════════════════
        if self.qty_up == 0 and self.qty_down == 0:
            # Time filter: don't start new positions too late
            if time_to_close is not None and time_to_close < self.min_time_to_enter:
                self.current_mode = 'too_late'
                self.mode_reason = f'Only {time_to_close:.0f}s left — skipping market'
                return trades_made

            if combined_price <= self.max_combined_entry:
                # Paired entry: buy equal SHARE quantities of both sides
                budget = min(self.market_budget * 0.20, self.cash * 0.20, remaining_budget * 0.40)
                # Equal shares so that min(qty_up, qty_down) is maximized
                cost_per_share = up_price + down_price
                qty = budget / cost_per_share
                total_cost = qty * cost_per_share

                if total_cost >= self.min_trade_size and total_cost <= self.cash:
                    if self.execute_buy('UP', up_price, qty, timestamp):
                        trades_made.append(('UP', up_price, qty))
                    if self.execute_buy('DOWN', down_price, qty, timestamp):
                        trades_made.append(('DOWN', down_price, qty))
                    self.current_mode = 'paired_entry'
                    self.mode_reason = f'Paired entry @ combined ${combined_price:.3f}'
                    print(f"🎯 PAIRED ENTRY: {qty:.1f} shares each | combined ${combined_price:.3f}")
                    return trades_made

        # ════════════════════════════════════════════════════════
        #  PAIRED GROWTH — Compound position with paired buys
        #  Both sides exist, MGP ≥ 0, but not yet locked.
        #  Only buy more pairs at BETTER combined price than avg.
        # ════════════════════════════════════════════════════════
        if self.qty_up > 0 and self.qty_down > 0 and not position_is_locked:
            avg_pair_cost = (self.cost_up + self.cost_down) / min(self.qty_up, self.qty_down) if min(self.qty_up, self.qty_down) > 0 else 99
            # Only compound at combined price cheaper than our current avg pair cost
            if combined_price < avg_pair_cost and combined_price <= self.max_combined_entry:
                now = time.time()
                if now - self.last_trade_time >= self.cooldown_seconds:
                    budget = min(self.market_budget * 0.10, self.cash * 0.10, remaining_budget * 0.25)
                    cost_per_share = combined_price
                    qty = budget / cost_per_share if cost_per_share > 0 else 0
                    total_cost = qty * cost_per_share
                if qty > 0.5 and total_cost >= self.min_trade_size and total_cost <= self.cash:
                        # Verify it actually improves MGP
                        new_qty_up = self.qty_up + qty
                        new_qty_down = self.qty_down + qty
                        new_total_cost = total_invested + total_cost
                        new_mgp = min(new_qty_up, new_qty_down) - new_total_cost * FEE_MULT
                        if new_mgp > mgp:
                            if self.execute_buy('UP', up_price, qty, timestamp):
                                trades_made.append(('UP', up_price, qty))
                            if self.execute_buy('DOWN', down_price, qty, timestamp):
                                trades_made.append(('DOWN', down_price, qty))
                            self.current_mode = 'paired_growth'
                            self.mode_reason = f'📈 Growing @ combined ${combined_price:.3f} (avg ${avg_pair_cost:.3f}) | MGP ${mgp:.2f}→${new_mgp:.2f}'
                            print(f"📈 PAIRED GROWTH: {qty:.1f} shares | combined ${combined_price:.3f} < avg ${avg_pair_cost:.3f} | MGP ${mgp:.2f}→${new_mgp:.2f}")
                            # Record and return
                            if self.qty_up + self.qty_down > 0:
                                self.mgp_history.append(self.calculate_locked_profit())
                                self.pnl_up_history.append(self.calculate_pnl_if_up_wins())
                                self.pnl_down_history.append(self.calculate_pnl_if_down_wins())
                            return trades_made

        # ════════════════════════════════════════════════════════
        #  SEQUENTIAL LOGIC (one side at a time)
        # ════════════════════════════════════════════════════════
        delta = self.position_delta_pct
        smaller = self.smaller_side()

        # Determine which side to try first
        if delta > self.max_allowed_delta_pct:
            first_side = smaller
        elif not self.both_scenarios_positive() and self.deficit() > 0.5:
            first_side = smaller
        else:
            first_side = 'UP' if up_price <= down_price else 'DOWN'

        # Try first side
        price_1 = up_price if first_side == 'UP' else down_price
        other_1 = down_price if first_side == 'UP' else up_price
        ok, qty, reason = self.should_buy(first_side, price_1, other_1, se_info, time_to_close=time_to_close)
        if ok and qty > 0:
            if self.execute_buy(first_side, price_1, qty, timestamp):
                trades_made.append((first_side, price_1, qty))
                print(f"✅ {reason}")

        # Try other side (only if first didn't trade)
        if not trades_made:
            second_side = 'DOWN' if first_side == 'UP' else 'UP'
            price_2 = up_price if second_side == 'UP' else down_price
            other_2 = down_price if second_side == 'UP' else up_price
            ok2, qty2, reason2 = self.should_buy(second_side, price_2, other_2, se_info, time_to_close=time_to_close)
            if ok2 and qty2 > 0:
                if self.execute_buy(second_side, price_2, qty2, timestamp):
                    trades_made.append((second_side, price_2, qty2))
                    print(f"✅ {reason2}")

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
