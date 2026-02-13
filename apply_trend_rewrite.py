#!/usr/bin/env python3
"""
Apply trend-following rewrite to arbitrage_strategy.py
Changes:
1. max_core_trades 6 -> 8
2. Update docstring to reflect trend-following strategy
3. Update detect_momentum() to also detect sustained dominance (not just rising)
4. Replace Phases 1-4 with trend-following logic
"""

import re
import sys

filepath = '/workspaces/cdpm/arbitrage_strategy.py'

with open(filepath, 'r') as f:
    content = f.read()

original = content  # backup

# ═══════════════════════════════════════════════════
# CHANGE 1: max_core_trades 6 -> 8
# ═══════════════════════════════════════════════════
old = "self.max_core_trades = 6  # Max trades to build core position (entry + hedge + balance)"
new = "self.max_core_trades = 8  # Max trades per market (entry + hedge + trend follows)"
if old not in content:
    print("ERROR: Could not find max_core_trades = 6")
    sys.exit(1)
content = content.replace(old, new, 1)
print("✅ Changed max_core_trades to 8")

# ═══════════════════════════════════════════════════
# CHANGE 2: Update docstring
# ═══════════════════════════════════════════════════
old_doc = '''        """
        Hybrid Arbitrage + Momentum Strategy
        
        Core idea: Combine paired arbitrage (guaranteed profit from pair < 1.0)
        with directional momentum (extra shares on the likely winning side).
        
        Phases:
          1. SCOUT   - No position. Enter cheap side OR trending side.
          2. HEDGE   - One side owned. Complete pair when favorable.
          3. BALANCE - Both sides owned. Equalize, then improve pair cost.
          4. MOMENTUM- Both sides owned + balanced. Tilt toward winning side.
          5. ENDGAME - Near close. Force hedge if one-sided, stop if profitable.
        """'''
new_doc = '''        """
        Trend-Following Strategy with Hedged Downside
        
        Core idea: Follow the market trend (buy the winning side) while keeping
        insurance on the other side for reversal protection. DON'T fight the trend
        by repeatedly buying the cheap/losing side.
        
        Phases:
          1. OBSERVE & ENTER - Detect trend → enter on trending side ($5).
                               No trend yet → grab cheap side as insurance ($3).
          2. COMPLETE PAIR   - Trend-aware hedging. Trending side gets MORE,
                               insurance side gets LESS. Relaxed pair limits.
          3. TREND FOLLOW    - Buy more of trending side (up to 1.4:1 tilt).
                               Handle trend reversals. NO forced balancing.
                               Opportunistic improve only when no trend + 5%+ discount.
          4. ENDGAME         - Force hedge if one-sided < 45s. Stop if profitable.
        """'''
if old_doc not in content:
    print("ERROR: Could not find old docstring")
    sys.exit(1)
content = content.replace(old_doc, new_doc, 1)
print("✅ Updated docstring")

# ═══════════════════════════════════════════════════
# CHANGE 3: Update detect_momentum() - sustained dominance
# ═══════════════════════════════════════════════════
old_momentum = '''            if trend < self.momentum_trend_strength:
                return None, 0, 0  # Not enough trend'''
new_momentum = '''            # Two ways to detect momentum:
            # 1. RISING: price is actively going up (trend >= threshold)
            # 2. SUSTAINED: price has been consistently high for 70%+ of window
            is_rising = trend >= self.momentum_trend_strength
            above_count = sum(1 for p in recent if p > (0.50 + self.momentum_threshold))
            is_sustained = above_count >= len(recent) * 0.7 and favored_prob > (0.50 + self.momentum_threshold)
            
            if not is_rising and not is_sustained:
                return None, 0, 0  # Neither rising nor sustained'''
if old_momentum not in content:
    print("ERROR: Could not find old momentum check")
    sys.exit(1)
content = content.replace(old_momentum, new_momentum, 1)
print("✅ Updated detect_momentum() for sustained dominance")

# ═══════════════════════════════════════════════════
# CHANGE 4: Replace Phases 1-4 with trend-following logic
# ═══════════════════════════════════════════════════

# Find start marker (Phase 1 header)
start_marker = "        # ══════════════════════════════════════════════════════════\n        #  PHASE 1: SCOUT - No position yet\n        # ══════════════════════════════════════════════════════════"
start_idx = content.find(start_marker)
if start_idx == -1:
    print("ERROR: Could not find Phase 1 header")
    sys.exit(1)

# Find end marker (return trades before resolve_market)
end_pattern = re.compile(r"        return trades\n\n    def resolve_market")
match = end_pattern.search(content, start_idx)
if not match:
    print("ERROR: Could not find 'return trades' before resolve_market")
    sys.exit(1)

# Replace from Phase 1 header to just after final 'return trades'
end_idx = match.start() + len("        return trades")

old_phases = content[start_idx:end_idx]
print(f"Found old phases: {len(old_phases)} chars, {old_phases.count(chr(10))} lines")

new_phases = """        # ══════════════════════════════════════════════════════════
        #  PHASE 1: OBSERVE & ENTER
        #  Priority: Enter on TRENDING side (profit from direction)
        #  Fallback: Enter on cheap side as insurance (reversal protection)
        # ══════════════════════════════════════════════════════════
        if self.qty_up == 0 and self.qty_down == 0:
            # Don't start new positions with < 2 min left
            if time_to_close is not None and time_to_close < 120:
                self.current_mode = 'too_late'
                self.mode_reason = f'⏰ No position, <2min left ({time_to_close:.0f}s) - skipping'
                return trades

            # Check for trend first (need enough data)
            trending_token, trend_strength, trend_confidence = detect_momentum()

            if trending_token and trend_confidence >= 0.6:
                # TREND DETECTED: Enter on trending side (main profit play)
                trending_price = up_price if trending_token == 'UP' else down_price
                if trending_price <= self.momentum_max_price:
                    spend = self.entry_trade_usd + 2.0  # $5 trend entry (bigger bet)
                    trade = buy_with_spend(trending_token, trending_price, spend, 'trend_entry')
                    if trade:
                        trades.append(trade)
                        self.core_trade_count += 1
                        self.current_mode = 'trend_entry'
                        self.mode_reason = f'📈 TREND {trending_token} @ ${trending_price:.3f} | conf {trend_confidence:.0%} str {trend_strength:.0%}'
                    return trades

            # No trend yet: grab cheap insurance if available
            cheap_token = 'UP' if up_price <= down_price else 'DOWN'
            cheap_price = min(up_price, down_price)

            if cheap_price <= self.single_entry_price:
                spend = self.entry_trade_usd  # $3 insurance entry (smaller)
                trade = buy_with_spend(cheap_token, cheap_price, spend, 'insurance_entry')
                if trade:
                    trades.append(trade)
                    self.core_trade_count += 1
                    self.current_mode = 'insurance_entry'
                    self.mode_reason = f'🛡️ Insurance {cheap_token} @ ${cheap_price:.3f} (< ${self.single_entry_price:.2f}) | waiting for trend'
                return trades

            self.current_mode = 'scouting'
            tick_count = len(self.price_history_up)
            self.mode_reason = f'🔍 Waiting ({tick_count} ticks) | UP ${up_price:.3f} DOWN ${down_price:.3f}'
            return trades

        # ══════════════════════════════════════════════════════════
        #  PHASE 2: COMPLETE PAIR - Build the other side
        #  Trend-aware: trending side gets MORE, insurance gets LESS
        #  Relaxed pair limits for directional bets
        # ══════════════════════════════════════════════════════════
        if self.qty_up == 0 or self.qty_down == 0:
            owned_token = 'UP' if self.qty_up > 0 else 'DOWN'
            other_token = 'DOWN' if owned_token == 'UP' else 'UP'
            owned_avg = self.avg_up if owned_token == 'UP' else self.avg_down
            owned_cost = self.cost_up if owned_token == 'UP' else self.cost_down
            other_price = down_price if other_token == 'DOWN' else up_price

            potential_pair = owned_avg + other_price
            trending_token, trend_strength, trend_confidence = detect_momentum()

            if trending_token and trend_confidence >= 0.5:
                # ── TREND-AWARE hedging ──
                if other_token == trending_token:
                    # We own insurance side → need TRENDING side (spend MORE)
                    # Accept higher pair cost for directional position
                    max_pair_trend = 1.05  # Accept up to 5% spread for trend bet
                    if potential_pair < max_pair_trend and other_price <= self.momentum_max_price:
                        spend = owned_cost * 1.5  # 50% more on trending side
                        trade = buy_with_spend(other_token, other_price, spend, 'trend_build')
                        if trade:
                            trades.append(trade)
                            self.core_trade_count += 1
                            self.current_mode = 'trend_build'
                            self.mode_reason = f'📈 Build {other_token} (TREND) @ ${other_price:.3f} | pair ${potential_pair:.3f} | conf {trend_confidence:.0%}'
                        return trades
                else:
                    # We own trending side → need INSURANCE (spend LESS)
                    if potential_pair < MAX_PAIR_FOR_HEDGE:
                        spend = owned_cost * 0.5  # Half spend on insurance
                        trade = buy_with_spend(other_token, other_price, spend, 'add_insurance')
                        if trade:
                            trades.append(trade)
                            self.core_trade_count += 1
                            self.current_mode = 'insuring'
                            self.mode_reason = f'🛡️ Insurance {other_token} @ ${other_price:.3f} | pair ${potential_pair:.3f} | trend={trending_token}'
                        return trades

            # ── No trend - standard hedging ──
            if potential_pair < MAX_PAIR_FOR_PROFIT:
                # pair < 0.97: guaranteed profit after fees
                spend = owned_cost
                trade = buy_with_spend(other_token, other_price, spend, 'hedge_profit')
                if trade:
                    trades.append(trade)
                    self.core_trade_count += 1
                    self.current_mode = 'hedging'
                    self.mode_reason = f'🔀 PROFIT hedge {other_token} @ ${other_price:.3f} | pair ${potential_pair:.3f} < ${MAX_PAIR_FOR_PROFIT} ✅'
                return trades

            if potential_pair < MAX_PAIR_FOR_HEDGE:
                # pair < 1.00: caps risk with partial hedge
                spend = owned_cost * 0.5
                trade = buy_with_spend(other_token, other_price, spend, 'hedge_risk')
                if trade:
                    trades.append(trade)
                    self.core_trade_count += 1
                    self.current_mode = 'partial_hedge'
                    self.mode_reason = f'🔀 Risk hedge {other_token} @ ${other_price:.3f} | pair ${potential_pair:.3f} | 50% size'
                return trades

            # Time-pressure hedge: accept worse pair if running low on time
            if time_to_close is not None and time_to_close < 180 and potential_pair < 1.05:
                spend = owned_cost * 0.5
                trade = buy_with_spend(other_token, other_price, spend, 'time_hedge')
                if trade:
                    trades.append(trade)
                    self.core_trade_count += 1
                    self.current_mode = 'time_hedge'
                    self.mode_reason = f'⏰ Time hedge {other_token} @ ${other_price:.3f} | pair ${potential_pair:.3f} | {time_to_close:.0f}s left'
                return trades

            target_other = MAX_PAIR_FOR_PROFIT - owned_avg
            self.current_mode = 'waiting'
            self.mode_reason = f'⏳ {other_token} @ ${other_price:.3f} (need < ${target_other:.3f}) | pair ${potential_pair:.3f}'
            return trades

        # ══════════════════════════════════════════════════════════
        #  PHASE 3: TREND FOLLOW & MANAGE
        #  Both sides owned. Follow the trend, DON'T fight it.
        #  The cheap side we already own IS our insurance.
        #  Buy the trending side to maximize profit if trend continues.
        # ══════════════════════════════════════════════════════════
        ratio = (self.qty_up / self.qty_down) if self.qty_down > 0 else 999.0
        pnl_up = self.calculate_pnl_if_up_wins()
        pnl_down = self.calculate_pnl_if_down_wins()

        # ── PROFIT SECURED? Stop trading. ──
        if locked_profit >= self.min_profit_target:
            self.current_mode = 'profit_secured'
            self.mode_reason = f'💰 Locked ${locked_profit:.2f} ≥ ${self.min_profit_target:.2f} | pair ${current_pair:.3f} | ratio {ratio:.2f}'
            return trades

        # ── Trade cap reached? Position is set. ──
        if self.core_trade_count >= self.max_core_trades:
            trending_token, trend_strength, trend_confidence = detect_momentum()
            momentum_info = f' | 🧭 {trending_token} {trend_strength:.0%}/{trend_confidence:.0%}' if trending_token else ' | 🧭 no trend'
            self.current_mode = 'position_set'
            self.mode_reason = f'✅ {self.core_trade_count}/{self.max_core_trades} trades | locked ${locked_profit:+.2f} | ratio {ratio:.2f}{momentum_info}'
            return trades

        trending_token, trend_strength, trend_confidence = detect_momentum()

        # ── TREND FOLLOW: Buy more of the trending side ──
        if (trending_token and trend_confidence >= 0.6
            and time_to_close is not None and time_to_close > self.momentum_min_time):

            trending_price = up_price if trending_token == 'UP' else down_price
            trending_qty = self.qty_up if trending_token == 'UP' else self.qty_down
            other_qty = self.qty_down if trending_token == 'UP' else self.qty_up
            current_tilt = trending_qty / other_qty if other_qty > 0 else 999

            if (trending_price <= self.momentum_max_price
                and current_tilt < self.max_tilt_ratio):

                # Scale spend: stronger trend = bigger bet
                spend = self.momentum_trade_usd * (0.5 + 0.5 * trend_strength)
                trade = buy_with_spend(trending_token, trending_price, spend, 'trend_follow')
                if trade:
                    trades.append(trade)
                    self.core_trade_count += 1
                    self.current_mode = 'trend_follow'
                    self.mode_reason = (f'📈 Follow {trending_token} @ ${trending_price:.3f} | '
                                      f'conf {trend_confidence:.0%} str {trend_strength:.0%} | '
                                      f'tilt {current_tilt:.2f} | locked ${locked_profit:+.2f}')
                return trades

        # ── TREND REVERSAL: Tilted AGAINST the current trend? Adjust. ──
        if trending_token and trend_confidence >= 0.7:
            trending_price = up_price if trending_token == 'UP' else down_price
            tilted_against = (
                (trending_token == 'UP' and ratio < 0.80) or
                (trending_token == 'DOWN' and ratio > 1.25)
            )
            if tilted_against and trending_price <= self.momentum_max_price:
                spend = self.momentum_trade_usd
                trade = buy_with_spend(trending_token, trending_price, spend, 'trend_reversal')
                if trade:
                    trades.append(trade)
                    self.core_trade_count += 1
                    self.current_mode = 'trend_reversal'
                    self.mode_reason = (f'🔄 Reversal → {trending_token} @ ${trending_price:.3f} | '
                                      f'ratio {ratio:.2f} | conf {trend_confidence:.0%}')
                return trades

        # ── OPPORTUNISTIC IMPROVE: Only when no trend and significant discount ──
        if not trending_token:
            for token, price in [('UP', up_price), ('DOWN', down_price)]:
                disc = discount_to_avg(token, price)
                if disc < 0.05:  # Need 5%+ discount (strict)
                    continue
                my_qty = self.qty_up if token == 'UP' else self.qty_down
                other_q = self.qty_down if token == 'UP' else self.qty_up
                if other_q > 0 and my_qty / other_q > 1.15:
                    continue
                test_spend = self.improve_trade_usd
                test_qty = test_spend / price if price > 0 else 0
                if test_qty < self.min_trade_size:
                    continue
                new_pair = pair_cost_after_buy(token, price, test_qty)
                if new_pair < current_pair - 0.002 and new_pair < MAX_PAIR_FOR_BALANCE:
                    trade = buy_with_spend(token, price, test_spend, 'improve')
                    if trade:
                        trades.append(trade)
                        self.core_trade_count += 1
                        self.current_mode = 'improving'
                        self.mode_reason = f'⚡ {token} @ ${price:.3f} ({disc*100:.0f}%↓) | pair ${current_pair:.3f}→${new_pair:.3f}'
                    return trades

        # ── Position set, watching ──
        momentum_info = f' | 🧭 {trending_token} {trend_strength:.0%}/{trend_confidence:.0%}' if trending_token else ' | 🧭 no trend'
        self.current_mode = 'watching'
        self.mode_reason = f'👀 Set | pair ${current_pair:.3f} | locked ${locked_profit:+.2f} | ratio {ratio:.2f} | UP:{pnl_up:+.1f} DOWN:{pnl_down:+.1f}{momentum_info}'
        return trades"""

content = content[:start_idx] + new_phases + content[end_idx:]
print(f"✅ Replaced phases: {len(old_phases)} → {len(new_phases)} chars")

# ═══════════════════════════════════════════════════
# Verify and save
# ═══════════════════════════════════════════════════

# Quick syntax check
try:
    compile(content, filepath, 'exec')
    print("✅ Syntax check passed")
except SyntaxError as e:
    print(f"❌ SYNTAX ERROR: {e}")
    print("NOT saving file. Rolling back.")
    sys.exit(1)

# Save
with open(filepath, 'w') as f:
    f.write(content)

print(f"\n✅ All changes applied successfully!")
print(f"   File size: {len(content)} chars")
print(f"   Lines: {content.count(chr(10)) + 1}")
