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

        # ── SpreadEngine ──
        self.spread_engine = SpreadEngine(
            lookback=200,
            beta_lookback=60,
            entry_z=2.0,
            exit_z=0.0,
            max_z=4.0,
            hysteresis=0.2,
            bb_k=2.0,
        )

        # ── Trading parameters ──
        self.min_trade_size = 2.0
        self.max_single_trade = 40.0     # Raised for MGP-optimal sizing
        self.cooldown_seconds = 2        # Faster: 2s between trades
        self.last_trade_time = 0

        # ── Delta Neutral parameters ──
        self.target_delta_pct = 0.0
        self.max_allowed_delta_pct = 5.0
        self.critical_delta_pct = 10.0
        self.emergency_delta_pct = 20.0
        self.rebalance_target_delta_pct = 2.0

        # ── Entry / Price limits ──
        self.max_entry_price = 0.65
        self.preferred_entry_price = 0.55
        self.ideal_entry_price = 0.45

        # ── MGP-specific limits ──
        # Maximum price we'll ever pay when MGP-balancing (absolute ceiling)
        self.mgp_max_price = 0.75
        # Budget fraction we're willing to spend in one MGP-lock trade
        self.mgp_budget_fraction = 0.35

        # ── Risk management ──
        self.max_position_pct = 0.80     # Use max 80 % of budget
        self.min_reserve_cash = 20.0
        self.max_loss_per_market = 80.0  # Wider stop for MGP recovery

        # ── Pair cost limits ──
        self.max_pair_cost = 0.98
        self.warning_pair_cost = 0.92
        # Pair cost below this = guaranteed profit per matched pair
        self.profitable_pair_cost = 1.0 / FEE_MULT  # ~0.9852
        # Accumulation cooldown (slower than rebalance)
        self.accumulate_cooldown = 8  # seconds between accumulate trades
        self._last_accumulate_time = 0

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
                   se_info: dict = None) -> Tuple[bool, float, str]:
        if self.market_status != 'open':
            return False, 0, "Market not open"

        if se_info is None:
            if side == 'UP':
                se_info = self._feed_spread_engine(price, other_price)
            else:
                se_info = self._feed_spread_engine(other_price, price)

        delta = self.position_delta_pct
        signal = se_info.get('signal', SIGNAL_NONE)
        z = se_info.get('z_score', 0.0)
        beta = se_info.get('beta', 1.0)

        now = time.time()
        if now - self.last_trade_time < self.cooldown_seconds and delta <= self.critical_delta_pct:
            return False, 0, "Cooldown active"

        my_qty = self.qty_up if side == 'UP' else self.qty_down
        my_cost = self.cost_up if side == 'UP' else self.cost_down
        other_qty = self.qty_down if side == 'UP' else self.qty_up
        other_cost = self.cost_down if side == 'UP' else self.cost_up

        total_cost = self.cost_up + self.cost_down
        budget_limit = self.starting_balance * self.max_position_pct
        remaining_budget = max(0, budget_limit - total_cost)
        current_mgp = self.calculate_locked_profit()

        # ──────────────────────────────────────────────────────────
        #  PHASE 0 – EMERGENCY REBALANCE
        #
        #  In binary markets, having 100% delta means total loss
        #  if the wrong side wins.  Rebalance aggressively even if
        #  pair_cost > 1.0 — accept small MGP hit for risk control.
        # ──────────────────────────────────────────────────────────
        if delta > self.max_allowed_delta_pct and (self.qty_up + self.qty_down) > 0:
            smaller = self.smaller_side()
            if side != smaller:
                return False, 0, f"Rebal: need {smaller}"

            pair_cost = price + other_price

            # Dynamic price cap — more aggressive when delta is extreme
            if delta > self.emergency_delta_pct:
                # EMERGENCY: accept up to $0.96 to avoid total wipeout
                price_cap = 0.96
                budget_cap = remaining_budget * 0.50
            elif delta > self.critical_delta_pct:
                price_cap = 0.90
                budget_cap = remaining_budget * 0.35
            else:
                price_cap = self.mgp_max_price
                budget_cap = remaining_budget * 0.25

            if price > price_cap:
                return False, 0, f"Rebalance price ${price:.2f} > cap ${price_cap:.2f}"

            target_qty = self.deficit()

            # When pair_cost > profitable threshold, buy less to limit MGP damage
            if pair_cost > self.profitable_pair_cost:
                # Scale down: at pair_cost=1.00 buy 60%, at 1.02 buy 30%
                overpay_pct = (pair_cost - self.profitable_pair_cost) / 0.04
                scale = max(0.30, 1.0 - overpay_pct * 0.35)
                target_qty = target_qty * scale

            max_by_budget = budget_cap / price if price > 0 else 0
            qty = min(target_qty, max_by_budget, self.max_single_trade * 2 / price)
            qty = max(0, qty)

            if qty * price < self.min_trade_size:
                return False, 0, "Budget too low for rebalance"

            new_mgp = self.mgp_after_buy(side, price, qty)
            self.current_mode = 'rebalancing'
            self.mode_reason = f'⚖️ Δ {delta:.1f}% → balance | MGP ${current_mgp:.2f}→${new_mgp:.2f}'
            return True, qty, f"⚖️ REBALANCE {side} {qty:.1f}×${price:.3f} | MGP ${current_mgp:.2f}→${new_mgp:.2f}"

        # ──────────────────────────────────────────────────────────
        #  PHASE 1 – INITIAL ENTRY  (no position)
        # ──────────────────────────────────────────────────────────
        if my_qty == 0 and other_qty == 0:
            if price > self.max_entry_price:
                return False, 0, f"Price ${price:.2f} > max entry ${self.max_entry_price}"

            # Enter with the cheaper side first
            if price <= self.ideal_entry_price:
                spend = min(25.0, remaining_budget * 0.12)
            elif price <= self.preferred_entry_price:
                spend = min(18.0, remaining_budget * 0.08)
            else:
                spend = min(12.0, remaining_budget * 0.06)

            if spend < self.min_trade_size:
                return False, 0, "Insufficient budget"

            qty = spend / price
            self.current_mode = 'entry'
            self.mode_reason = f'Initial entry {side} @ ${price:.3f}'
            return True, qty, f"🎯 ENTRY {side} {qty:.1f}×${price:.3f}"

        # ──────────────────────────────────────────────────────────
        #  PHASE 2 – MGP LOCK  (make both scenarios ≥ 0 ASAP)
        #
        #  "Prioritise making both outcomes positive as early as
        #   possible in the trading period."  – Gemini
        #
        #  Buy the SMALLER side to close the deficit.
        #  Exact qty = deficit, capped by budget.
        # ──────────────────────────────────────────────────────────
        if not self.both_scenarios_positive() and self.deficit() > 0.5:
            smaller = self.smaller_side()
            if side != smaller:
                return False, 0, f"MGP Lock: need {smaller}, not {side}"

            p_max = self.max_price_for_positive_mgp()

            if price > min(p_max, self.mgp_max_price):
                return False, 0, f"MGP Lock: ${price:.3f} > p_max ${p_max:.3f}"

            target_qty = self.deficit()
            budget_for_lock = remaining_budget * self.mgp_budget_fraction
            max_by_budget = budget_for_lock / price if price > 0 else 0
            qty = min(target_qty, max_by_budget)

            if qty * price < self.min_trade_size:
                # Try a partial fill
                qty = self.min_trade_size / price
                if qty * price > remaining_budget:
                    return False, 0, "Budget too low for MGP lock"

            new_mgp = self.mgp_after_buy(side, price, qty)
            delta_mgp = new_mgp - current_mgp

            if delta_mgp <= 0:
                return False, 0, f"MGP Lock: no improvement (ΔMGP=${delta_mgp:.3f})"

            pct_locked = qty / target_qty * 100 if target_qty > 0 else 100
            self.current_mode = 'mgp_lock'
            self.mode_reason = f'🔒 Locking MGP: ${current_mgp:.2f}→${new_mgp:.2f} ({pct_locked:.0f}% of deficit)'
            return True, qty, f"🔒 MGP LOCK {side} {qty:.1f}×${price:.3f} | MGP ${current_mgp:.2f}→${new_mgp:.2f}"

        # ──────────────────────────────────────────────────────────
        #  PHASE 3 – PAIR ACCUMULATE + MGP MAXIMIZE
        #
        #  When positions exist and delta is OK:
        #  3a) If pair_cost < 1/FEE_MULT (~$0.985), buy the cheaper
        #      side.  Phase 0 will rebalance the other side next tick,
        #      creating a matched pair with guaranteed profit.
        #  3b) If smaller side is cheap, keep buying it to raise
        #      the MGP floor.
        #
        #  This keeps the bot actively trading price moves!
        # ──────────────────────────────────────────────────────────
        if (self.qty_up + self.qty_down) > 0 and delta <= self.max_allowed_delta_pct:
            pair_cost = price + other_price
            now_acc = time.time()

            # Sub-phase 3a: Pair Accumulate — pair_cost is profitable
            if pair_cost < self.profitable_pair_cost and now_acc - self._last_accumulate_time >= self.accumulate_cooldown:
                # Buy the CHEAPER side; rebalance will buy the other
                cheaper_side = 'UP' if price <= other_price else 'DOWN'
                if side == cheaper_side:
                    # Don't let delta blow up — skip if already heavy this side
                    if not (side == self.position_delta_direction and delta > 3.0):
                        # Size: enough to be meaningful but controlled
                        profit_per_share = 1.0 - pair_cost * FEE_MULT
                        spend = min(15.0, remaining_budget * 0.08)
                        if spend >= self.min_trade_size:
                            qty = spend / price
                            new_mgp = self.mgp_after_buy(side, price, qty)
                            expected_pair_profit = qty * profit_per_share
                            self._last_accumulate_time = now_acc
                            self.current_mode = 'accumulate'
                            self.mode_reason = f'Pair ${pair_cost:.3f} < ${self.profitable_pair_cost:.3f} | +${expected_pair_profit:.2f}/pair'
                            return True, qty, f"ACCUMULATE {side} {qty:.1f} x ${price:.3f} | pair=${pair_cost:.3f} +${expected_pair_profit:.2f}"

            # Sub-phase 3b: MGP Maximize — smaller side is cheap
            if self.deficit() > 0.1:
                smaller = self.smaller_side()
                if side == smaller and price <= self.preferred_entry_price:
                    target_qty = self.deficit()
                    budget_max = remaining_budget * 0.15
                    max_by_budget = budget_max / price if price > 0 else 0
                    qty = min(target_qty, max_by_budget, self.max_single_trade / price)

                    if qty * price >= self.min_trade_size:
                        new_mgp = self.mgp_after_buy(side, price, qty)
                        delta_mgp = new_mgp - current_mgp

                        if delta_mgp >= 0.05:  # Worth at least 5 cents
                            self.current_mode = 'mgp_maximize'
                            self.mode_reason = f'Floor raise: ${current_mgp:.2f} -> ${new_mgp:.2f}'
                            return True, qty, f"MGP MAX {side} {qty:.1f} x ${price:.3f} | Floor ${current_mgp:.2f} -> ${new_mgp:.2f}"

        # ──────────────────────────────────────────────────────────
        #  PHASE 4 – SPREAD SIGNAL  (SpreadEngine z-score driven)
        # ──────────────────────────────────────────────────────────
        if signal == SIGNAL_EXIT_ALL:
            self.current_mode = 'exit_wait'
            self.mode_reason = f'Spread normalised (z={z:.2f}) – holding'
            return False, 0, "EXIT_ALL"

        if signal == SIGNAL_SHORT_UP_LONG_DOWN:
            signal_side = 'DOWN'
        elif signal == SIGNAL_LONG_UP_SHORT_DOWN:
            signal_side = 'UP'
        else:
            signal_side = None

        if signal_side is not None and side == signal_side:
            if price > self.max_entry_price:
                return False, 0, f"Signal price ${price:.2f} too high"

            # Don't buy if it worsens delta significantly
            if side == self.position_delta_direction and delta > self.max_allowed_delta_pct * 0.5:
                return False, 0, f"Signal would worsen Δ ({delta:.1f}%)"

            se_delta = se_info.get('position_delta_pct', 0.0)
            if se_delta <= 0:
                return False, 0, "No z-score conviction"

            fraction = se_delta / 100.0
            spend = self.min_trade_size + fraction * (self.max_single_trade - self.min_trade_size)
            spend = min(spend, remaining_budget * 0.20, self.max_single_trade)

            if spend < self.min_trade_size:
                return False, 0, "Spread delta too low"

            qty = spend / price

            # Check MGP doesn't degrade
            new_mgp = self.mgp_after_buy(side, price, qty)
            if new_mgp < current_mgp - 1.0:  # Allow $1 tolerance
                return False, 0, f"Signal trade would drop MGP by ${current_mgp - new_mgp:.2f}"

            direction_label = "↓UP ↑DN" if signal == SIGNAL_SHORT_UP_LONG_DOWN else "↑UP ↓DN"
            self.current_mode = 'seeking_arb'
            self.mode_reason = f'Signal {direction_label} | z={z:.2f} β={beta:.3f}'
            return True, qty, f"💰 ARB {side} {qty:.1f}×${price:.3f} | z={z:.2f}"

        # ──────────────────────────────────────────────────────────
        #  PHASE 5 – AVG IMPROVEMENT  (lower cost basis)
        # ──────────────────────────────────────────────────────────
        if my_qty > 0 and my_cost > 0:
            my_avg = my_cost / my_qty
            if price < my_avg * 0.95:  # 5% cheaper than avg
                if side == self.position_delta_direction and delta > 3.0:
                    return False, 0, "Larger side – skip improvement"

                spend = min(8.0, remaining_budget * 0.04)
                if spend < self.min_trade_size:
                    return False, 0, "Budget too low"

                qty = spend / price
                new_mgp = self.mgp_after_buy(side, price, qty)
                if new_mgp < current_mgp:
                    return False, 0, "Improvement would lower MGP"

                new_avg = (my_cost + spend) / (my_qty + qty)
                self.current_mode = 'improving'
                self.mode_reason = f'Avg ${my_avg:.3f}→${new_avg:.3f}'
                return True, qty, f"📉 IMPROVE {side} avg ${my_avg:.3f}→${new_avg:.3f}"

        self.current_mode = 'seeking_arb'
        self.mode_reason = f'Monitoring | z={z:.2f} β={beta:.3f} MGP=${current_mgp:.2f}'
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

        # 3. Reactive priority:
        #    "Every time UP price rises → buy DOWN to neutralise delta"
        #    The SMALLER side is always the priority for MGP.
        delta = self.position_delta_pct
        smaller = self.smaller_side()

        # Determine which side to try first
        if delta > self.max_allowed_delta_pct:
            # Rebalance: always try smaller side first
            first_side = smaller
        elif not self.both_scenarios_positive() and self.deficit() > 0.5:
            # MGP Lock: always buy smaller side
            first_side = smaller
        elif se_info.get('signal') == SIGNAL_SHORT_UP_LONG_DOWN:
            first_side = 'DOWN'
        elif se_info.get('signal') == SIGNAL_LONG_UP_SHORT_DOWN:
            first_side = 'UP'
        else:
            # Default: try cheaper side (more MGP-efficient)
            first_side = 'UP' if up_price <= down_price else 'DOWN'

        # 4. Try first side
        price_1 = up_price if first_side == 'UP' else down_price
        other_1 = down_price if first_side == 'UP' else up_price
        ok, qty, reason = self.should_buy(first_side, price_1, other_1, se_info)
        if ok and qty > 0:
            if self.execute_buy(first_side, price_1, qty, timestamp):
                trades_made.append((first_side, price_1, qty))
                print(f"✅ {reason}")

        # 5. Try other side
        if not trades_made:
            second_side = 'DOWN' if first_side == 'UP' else 'UP'
            price_2 = up_price if second_side == 'UP' else down_price
            other_2 = down_price if second_side == 'UP' else up_price
            ok2, qty2, reason2 = self.should_buy(second_side, price_2, other_2, se_info)
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
