#!/usr/bin/env python3
"""
Quick-Flip Strategy v10 for Polymarket

CORE STRATEGY: Buy winner @ $0.55, sell @ $0.70, exit with profit.

  1. ENTRY: Buy the winning side (price >= $0.55) for $5.
     Immediately place a limit sell @ $0.70 on those shares.

  2. PIVOT: If the market flips (other side now winning), buy
     enough of the new winner @ $0.55 that selling @ $0.70
     yields +$3 net profit (covering all accumulated losses).
     Previous sell orders remain active.

  3. EXIT: If ANY sell order fills -> market is complete. Profit taken.
     All remaining positions are abandoned (sell orders still active).

  4. CUTOFF: No new trades within 12 minutes of market close.
     If cutoff reached with open positions, hold to resolution.

  5. MAX 5 PIVOTS: After 5 pivots, stop trading. Hold to resolution.

Math per pivot round (n >= 2):
  T_n = T_{n-1} + X_{n-1} x 0.10     (accumulated unrealized loss)
  X_n = (3 + T_n) / 0.15              (shares needed for +$3 net)
  C_n = X_n x 0.55                    (cost of this round)

Total exposure after 5 pivots: ~$149.55
"""

import math
import time
from typing import Optional, Dict, Tuple, List
from collections import deque
from datetime import datetime, timezone
from dataclasses import dataclass

from spread_engine import (
    SpreadEngine,
    SIGNAL_NONE,
    SIGNAL_SHORT_UP_LONG_DOWN,
    SIGNAL_LONG_UP_SHORT_DOWN,
    SIGNAL_EXIT_ALL,
)
from execution_simulator import ExecutionSimulator

# -- Constants --
FEE_RATE = 0.015
FEE_MULT = 1.0 + FEE_RATE       # 1.015
BREAK_EVEN = 1.0 / FEE_MULT     # ~0.9852


@dataclass
class PendingSell:
    """A pending limit sell order waiting to be filled."""
    side: str          # 'UP' or 'DOWN'
    qty: float         # Shares to sell
    min_price: float   # Minimum sell price (limit)
    cost_basis: float  # What we paid for these shares
    round_num: int     # Which pivot round placed this
    placed_at: str     # Timestamp when placed
    filled: bool = False
    fill_price: float = 0.0
    fill_qty: float = 0.0
    fill_time: str = ''
    proceeds: float = 0.0


class SideTracker:
    """
    Tracks EMA-5/20/50, Z-Score, ATR for one side (UP or DOWN).
    Kept for UI chart compatibility.
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
        self.momentum: float = 0.0
        self.momentum_history: deque = deque(maxlen=20)
        self.trend_strength: float = 0.0
        self.trend_direction: int = 0
        self.is_reversing: bool = False
        self.reversal_score: float = 0.0
        self._prev_ema5_above_20: Optional[bool] = None
        self._consecutive_up_ticks: int = 0
        self._consecutive_down_ticks: int = 0
        self._ticks_since_reversal: int = 999

    def update(self, price: float):
        self.tick_count += 1
        self.prices.append(price)
        self.session_low = min(self.session_low, price)
        self.session_high = max(self.session_high, price)

        a5, a20, a50 = 2.0/6.0, 2.0/21.0, 2.0/51.0
        self.ema_5 = price if self.ema_5 is None else a5 * price + (1 - a5) * self.ema_5
        self.ema_20 = price if self.ema_20 is None else a20 * price + (1 - a20) * self.ema_20
        self.ema_50 = price if self.ema_50 is None else a50 * price + (1 - a50) * self.ema_50

        if self.prev_price is not None:
            tr = abs(price - self.prev_price)
            self.tr_history.append(tr)
            if len(self.tr_history) >= 3:
                self.atr = sum(self.tr_history) / len(self.tr_history)

        if len(self.prices) >= 10:
            old = self.prices[-10]
            if old > 0:
                self.momentum = (price - old) / old
        elif self.prev_price and self.prev_price > 0:
            self.momentum = (price - self.prev_price) / self.prev_price
        self.momentum_history.append(self.momentum)

        if self.prev_price is not None:
            if price > self.prev_price:
                self._consecutive_up_ticks += 1
                self._consecutive_down_ticks = 0
            elif price < self.prev_price:
                self._consecutive_down_ticks += 1
                self._consecutive_up_ticks = 0

        self.prev_price = price

        if self.ema_5 and self.ema_20 and self.ema_50:
            if self.ema_5 > self.ema_20 > self.ema_50:
                self.trend_direction = 1
            elif self.ema_5 < self.ema_20 < self.ema_50:
                self.trend_direction = -1
            else:
                self.trend_direction = 0
            if self.ema_50 > 0:
                self.trend_strength = min(1.0, abs(self.ema_5 - self.ema_50) / max(0.001, self.ema_50) * 10)

        self._ticks_since_reversal += 1
        if self.ema_5 is not None and self.ema_20 is not None:
            above = self.ema_5 > self.ema_20
            if self._prev_ema5_above_20 is not None:
                if above and not self._prev_ema5_above_20:
                    self.is_reversing = True
                    self._ticks_since_reversal = 0
                elif not above and self._prev_ema5_above_20:
                    self.is_reversing = False
                elif self._ticks_since_reversal > 15:
                    self.is_reversing = False
            self._prev_ema5_above_20 = above

        self.reversal_score = 0.0

        if len(self.prices) >= 10:
            window = list(self.prices)[-20:]
            mean = sum(window) / len(window)
            variance = sum((x - mean) ** 2 for x in window) / len(window)
            self.std_dev = max(0.0005, math.sqrt(variance))
            self.z_score = (price - self.ema_50) / self.std_dev if self.ema_50 else 0.0
        else:
            self.z_score = 0.0

    @property
    def is_falling_knife(self) -> bool:
        return (self.trend_direction == -1 and self.trend_strength > 0.3
                and self.momentum < -0.005 and not self.is_reversing)

    @property
    def is_confirmed_dip(self) -> bool:
        return (self.z_score < -0.5 and
                (self.is_reversing or self.reversal_score > 30
                 or self._consecutive_up_ticks >= 2))


class ArbitrageStrategy:
    """
    Quick-Flip Strategy v10 for Polymarket binary markets.

    Buy winner @ $0.55, sell @ $0.70.
    On pivot: buy new winner for +$3 net profit if sold.
    Max 5 pivots. 12-minute cutoff before market close.
    """

    ENTRY_PRICE = 0.55
    SELL_TARGET = 0.70
    SPREAD = SELL_TARGET - ENTRY_PRICE
    INITIAL_BUY_DOLLARS = 5.0
    PIVOT_NET_PROFIT = 3.0
    MAX_PIVOTS = 5
    LOSS_PER_SHARE_ON_PIVOT = 0.10
    CUTOFF_SECONDS = 720
    MIN_ENTRY_PRICE = 0.53
    MAX_ENTRY_PRICE = 0.58

    def __init__(self, market_budget: float, starting_balance: float,
                 exec_sim: ExecutionSimulator = None):
        self.market_budget = market_budget
        self.starting_balance = starting_balance
        self.cash_ref = {'balance': starting_balance}

        self.qty_up = 0.0
        self.qty_down = 0.0
        self.cost_up = 0.0
        self.cost_down = 0.0

        self.up_tracker = SideTracker()
        self.down_tracker = SideTracker()

        self.spread_engine = SpreadEngine(
            lookback=60, beta_lookback=30, entry_z=2.0,
            exit_z=0.0, max_z=4.0, hysteresis=0.2, bb_k=2.0,
        )

        self._pivot_count = 0
        self._current_winner: Optional[str] = None
        self._accumulated_loss = 0.0
        self._pending_sells: List[PendingSell] = []
        self._market_complete = False
        self._total_sell_proceeds = 0.0
        self._equalized = False
        self._pivot_mode = False

        self.min_time_to_enter = 30
        self.cooldown_seconds = 0.0

        self.max_shares_per_order = 250
        self.min_trade_size = 1.0

        self.last_trade_time: float = 0
        self.market_status: str = 'open'
        self.trade_count: int = 0
        self.trade_log: List[dict] = []
        self.payout: float = 0.0
        self.last_fees_paid: float = 0.0

        self.current_mode: str = 'scanning'
        self.mode_reason: str = 'Looking for entry'
        self._exposure_priority: str = 'NEUTRAL'

        self.resolution_outcome = None
        self.final_pnl = None
        self.final_pnl_gross = None

        self._combined_history: deque = deque(maxlen=60)
        self._min_combined_seen: float = 1.0
        self._tick_count: int = 0
        self._entry_score: float = 0.0
        self.spread_history: deque = deque(maxlen=20)
        self.avg_spread: float = 0.0
        self.mgp_history: deque = deque(maxlen=120)
        self.pnl_up_history: deque = deque(maxlen=120)
        self.pnl_down_history: deque = deque(maxlen=120)

        self.exec_sim = exec_sim or ExecutionSimulator(latency_ms=25.0, max_slippage_pct=5.0)
        self._pending_orderbooks: Dict[str, dict] = {'UP': {}, 'DOWN': {}}
        self._book_depth_cap: Dict[str, float] = {'UP': 100.0, 'DOWN': 100.0}

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

    def calculate_total_fees(self, extra_cost: float = 0.0) -> float:
        return (self.cost_up + self.cost_down + extra_cost) * FEE_RATE

    def calculate_pnl_if_up_wins(self) -> float:
        if self.qty_up == 0 and self.qty_down == 0:
            return 0.0
        total_cost = self.cost_up + self.cost_down
        pnl = self.qty_up - total_cost * FEE_MULT
        pnl += self._total_sell_proceeds
        for sell in self._pending_sells:
            if sell.filled and sell.side == 'UP':
                pnl -= sell.fill_qty
        return pnl

    def calculate_pnl_if_down_wins(self) -> float:
        if self.qty_up == 0 and self.qty_down == 0:
            return 0.0
        total_cost = self.cost_up + self.cost_down
        pnl = self.qty_down - total_cost * FEE_MULT
        pnl += self._total_sell_proceeds
        for sell in self._pending_sells:
            if sell.filled and sell.side == 'DOWN':
                pnl -= sell.fill_qty
        return pnl

    def calculate_locked_profit(self) -> float:
        return min(self.calculate_pnl_if_up_wins(), self.calculate_pnl_if_down_wins())

    def calculate_max_profit(self) -> float:
        return max(self.calculate_pnl_if_up_wins(), self.calculate_pnl_if_down_wins())

    def both_scenarios_positive(self) -> bool:
        return (self.calculate_pnl_if_up_wins() >= 0 and
                self.calculate_pnl_if_down_wins() >= 0)

    def deficit(self) -> float:
        return abs(self.qty_up - self.qty_down)

    def smaller_side(self) -> str:
        return 'UP' if self.qty_up <= self.qty_down else 'DOWN'

    def larger_side(self) -> str:
        return 'UP' if self.qty_up >= self.qty_down else 'DOWN'

    def max_price_for_positive_mgp(self) -> float:
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
        cost = price * qty
        new_up = self.qty_up + (qty if side == 'UP' else 0)
        new_down = self.qty_down + (qty if side == 'DOWN' else 0)
        new_total = self.cost_up + self.cost_down + cost
        return min(new_up, new_down) - new_total * FEE_MULT

    def _calculate_pivot_shares(self) -> float:
        shares = (self.PIVOT_NET_PROFIT + self._accumulated_loss) / self.SPREAD
        return max(1.0, shares)

    def _calculate_pivot_cost(self, shares: float, price: float) -> float:
        return shares * price

    def _place_sell_order(self, side: str, qty: float, min_price: float,
                          cost_basis: float, timestamp: str):
        sell = PendingSell(
            side=side,
            qty=qty,
            min_price=min_price,
            cost_basis=cost_basis,
            round_num=self._pivot_count,
            placed_at=timestamp,
        )
        self._pending_sells.append(sell)
        print(f"SELL ORDER: {side} {qty:.1f}sh @ min ${min_price:.2f} "
              f"(round #{self._pivot_count})")

    def _check_sell_orders(self, timestamp: str) -> List[dict]:
        fills = []
        for sell in self._pending_sells:
            if sell.filled:
                continue

            orderbook = self._pending_orderbooks.get(sell.side, {})
            if not orderbook or not orderbook.get('bids'):
                continue

            bids = orderbook.get('bids', [])
            if not bids:
                continue

            try:
                best_bid = max(float(b.get('price', 0)) for b in bids if b.get('price'))
            except (ValueError, TypeError):
                continue

            if best_bid < sell.min_price:
                continue

            fill_result = self.exec_sim.simulate_sell(
                sell.side, sell.min_price, sell.qty, orderbook
            )

            if fill_result.filled:
                sell.filled = True
                sell.fill_price = fill_result.fill_price
                sell.fill_qty = fill_result.filled_qty
                sell.fill_time = timestamp
                sell.proceeds = fill_result.total_cost

                self._total_sell_proceeds += sell.proceeds

                if sell.side == 'UP':
                    self.qty_up -= sell.fill_qty
                    if self.qty_up + sell.fill_qty > 0:
                        cost_fraction = sell.fill_qty / (self.qty_up + sell.fill_qty)
                        cost_removed = self.cost_up * cost_fraction
                        self.cost_up -= cost_removed
                else:
                    self.qty_down -= sell.fill_qty
                    if self.qty_down + sell.fill_qty > 0:
                        cost_fraction = sell.fill_qty / (self.qty_down + sell.fill_qty)
                        cost_removed = self.cost_down * cost_fraction
                        self.cost_down -= cost_removed

                self.cash += sell.proceeds

                profit = sell.proceeds - sell.cost_basis
                print(f"SELL FILLED: {sell.side} {sell.fill_qty:.1f}sh @ ${sell.fill_price:.3f} "
                      f"| proceeds ${sell.proceeds:.2f} | profit ${profit:+.2f} "
                      f"(round #{sell.round_num})")

                self.trade_log.append({
                    'time': timestamp,
                    'side': 'SELL',
                    'token': sell.side,
                    'price': sell.fill_price,
                    'qty': sell.fill_qty,
                    'cost': sell.proceeds,
                    'desired_price': sell.min_price,
                    'desired_qty': sell.qty,
                    'slippage': round(fill_result.slippage, 6),
                    'slippage_pct': round(fill_result.slippage_pct, 4),
                    'slippage_cost': round(fill_result.slippage_cost, 6),
                    'partial': fill_result.partial,
                    'levels': fill_result.levels_consumed,
                    'latency_ms': fill_result.latency_ms,
                })
                if len(self.trade_log) > 100:
                    self.trade_log = self.trade_log[-100:]

                fills.append({
                    'side': sell.side,
                    'qty': sell.fill_qty,
                    'price': sell.fill_price,
                    'proceeds': sell.proceeds,
                    'profit': profit,
                    'round': sell.round_num,
                })

        return fills

    def execute_buy(self, side: str, price: float, qty: float,
                    timestamp: str = None) -> Tuple[bool, float, float]:
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).strftime('%H:%M:%S')

        depth_cap = self._book_depth_cap.get(side, self.max_shares_per_order)
        original_qty = qty
        qty = min(qty, self.max_shares_per_order, depth_cap)

        orderbook = self._pending_orderbooks.get(side, {})

        live_price = price
        if orderbook and orderbook.get('asks'):
            try:
                asks = orderbook['asks']
                best_ask = min(float(a.get('price', 99)) for a in asks if a.get('price'))
                if best_ask < 1.0:
                    if best_ask != price:
                        print(f"[{side}] Live price: ${best_ask:.4f} (decision was ${price:.4f})")
                    live_price = best_ask
            except (ValueError, TypeError):
                pass

        fill = self.exec_sim.simulate_fill(side, live_price, qty, orderbook)

        if not fill.filled:
            return False, 0.0, 0.0

        actual_price = fill.fill_price
        actual_qty = fill.filled_qty
        actual_cost = fill.total_cost

        if actual_cost > self.cash:
            return False, 0.0, 0.0

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

    def check_and_trade(self, up_price: float, down_price: float,
                        timestamp: str,
                        time_to_close: float = None,
                        up_bid: Optional[float] = None,
                        down_bid: Optional[float] = None,
                        up_orderbook: Optional[dict] = None,
                        down_orderbook: Optional[dict] = None,
                        ) -> List[Tuple[str, str, float, float]]:
        trades_made: List[Tuple[str, str, float, float]] = []

        if up_price <= 0 or down_price <= 0:
            return trades_made

        self._pending_orderbooks['UP'] = up_orderbook or {}
        self._pending_orderbooks['DOWN'] = down_orderbook or {}

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

        mid_up = (up_bid + up_price) / 2.0 if up_bid and up_bid > 0 else up_price
        mid_down = (down_bid + down_price) / 2.0 if down_bid and down_bid > 0 else down_price

        self.up_tracker.update(mid_up)
        self.down_tracker.update(mid_down)
        self._tick_count = self.up_tracker.tick_count

        self._feed_spread_engine(up_price, down_price)

        combined = up_price + down_price
        self._combined_history.append(combined)
        self._min_combined_seen = min(self._min_combined_seen, combined)

        has_position = (self.qty_up + self.qty_down) > 0

        if self.market_status in ('stopped', 'resolved', 'closed'):
            self._record_history()
            return trades_made

        if self._pending_sells:
            sell_fills = self._check_sell_orders(timestamp)
            if sell_fills:
                total_profit = sum(f['profit'] for f in sell_fills)
                sides_filled = ', '.join(f"{f['side']} #{f['round']}" for f in sell_fills)

                self._market_complete = True
                self.current_mode = 'profit_taken'
                self.mode_reason = (f'PROFIT TAKEN ${total_profit:+.2f} | '
                                    f'Sold {sides_filled}')

                for f in sell_fills:
                    trades_made.append(('SELL', f['side'], f['price'], f['qty']))

                self._record_history()
                return trades_made

        if self._market_complete:
            self.current_mode = 'profit_taken'
            active_sells = [s for s in self._pending_sells if not s.filled]
            if active_sells:
                sell_desc = ', '.join(f"{s.side}@${s.min_price:.2f}" for s in active_sells)
                self.mode_reason = f'Profit taken. Active sells: {sell_desc}'
            else:
                self.mode_reason = 'Profit taken. All done.'
            self._record_history()
            return trades_made

        if time_to_close is not None and time_to_close < self.CUTOFF_SECONDS and not has_position:
            self.current_mode = 'too_late'
            self.mode_reason = f'Only {time_to_close:.0f}s left - skipping market (cutoff {self.CUTOFF_SECONDS}s)'
            self._record_history()
            return trades_made

        if time_to_close is not None and time_to_close < self.CUTOFF_SECONDS and has_position:
            active_sells = [s for s in self._pending_sells if not s.filled]
            sell_desc = ', '.join(f"{s.side}@${s.min_price:.2f}" for s in active_sells) if active_sells else 'none'
            self.current_mode = 'cutoff_hold'
            self.mode_reason = (f'Cutoff: {time_to_close:.0f}s left | '
                                f'holding {self.qty_up:.1f}UP+{self.qty_down:.1f}DN | '
                                f'sells: {sell_desc}')
            self._record_history()
            return trades_made

        if time_to_close is not None and time_to_close < self.min_time_to_enter and not has_position:
            self.current_mode = 'too_late'
            self.mode_reason = f'Only {time_to_close:.0f}s left - skipping'
            self._record_history()
            return trades_made

        if self._pivot_count >= self.MAX_PIVOTS and has_position:
            active_sells = [s for s in self._pending_sells if not s.filled]
            sell_desc = ', '.join(f"{s.side}@${s.min_price:.2f}" for s in active_sells) if active_sells else 'none'
            self.current_mode = 'max_pivots'
            self.mode_reason = (f'Max {self.MAX_PIVOTS} pivots - holding to resolution | '
                                f'sells: {sell_desc}')
            self._record_history()
            return trades_made

        winner = 'DOWN' if down_price > up_price else 'UP'
        winner_price = down_price if winner == 'DOWN' else up_price
        loser = 'UP' if winner == 'DOWN' else 'DOWN'
        loser_price = up_price if winner == 'DOWN' else down_price

        if not has_position:
            if winner_price < self.MIN_ENTRY_PRICE:
                self.current_mode = 'scanning'
                self.mode_reason = (f'Waiting for winner >= ${self.MIN_ENTRY_PRICE:.2f} | '
                                    f'UP ${up_price:.2f} DN ${down_price:.2f}')
                self._record_history()
                return trades_made

            if winner_price > self.MAX_ENTRY_PRICE:
                self.current_mode = 'scanning'
                self.mode_reason = (f'Winner too expensive ${winner_price:.2f} > ${self.MAX_ENTRY_PRICE:.2f} | '
                                    f'UP ${up_price:.2f} DN ${down_price:.2f}')
                self._record_history()
                return trades_made

            qty = self.INITIAL_BUY_DOLLARS / winner_price
            qty = min(qty, self.max_shares_per_order)

            ok, ap, aq = self.execute_buy(winner, winner_price, qty, timestamp)
            if ok:
                trades_made.append(('BUY', winner, ap, aq))
                actual_cost = ap * aq
                self._current_winner = winner
                self._pivot_count = 0
                self._accumulated_loss = 0.0

                self._place_sell_order(winner, aq, self.SELL_TARGET, actual_cost, timestamp)
                trades_made.append(('SELL_PLACED', winner, self.SELL_TARGET, aq))

                self.current_mode = 'entry'
                self.mode_reason = (f'BOUGHT {winner} {aq:.1f}sh@${ap:.3f} | '
                                    f'SELL ORDER @ ${self.SELL_TARGET:.2f}')
            else:
                self.current_mode = 'entry_failed'
                self.mode_reason = f'Buy failed: {winner} @ ${winner_price:.3f}'

            self._record_history()
            return trades_made

        if has_position and self._current_winner and winner != self._current_winner:
            if winner_price < self.MIN_ENTRY_PRICE:
                active_sells = [s for s in self._pending_sells if not s.filled]
                sell_desc = ', '.join(f"{s.side}@${s.min_price:.2f}" for s in active_sells) if active_sells else 'none'
                self.current_mode = 'holding'
                self.mode_reason = (f'Flipped to {winner} but ${winner_price:.2f} < ${self.MIN_ENTRY_PRICE:.2f} | '
                                    f'sells: {sell_desc}')
                self._record_history()
                return trades_made

            if winner_price > self.MAX_ENTRY_PRICE:
                active_sells = [s for s in self._pending_sells if not s.filled]
                sell_desc = ', '.join(f"{s.side}@${s.min_price:.2f}" for s in active_sells) if active_sells else 'none'
                self.current_mode = 'holding'
                self.mode_reason = (f'Flipped to {winner} but ${winner_price:.2f} > ${self.MAX_ENTRY_PRICE:.2f} | '
                                    f'sells: {sell_desc}')
                self._record_history()
                return trades_made

            prev_winner_qty = (self.qty_down if self._current_winner == 'DOWN' else self.qty_up)
            actual_loss_per_share = self.ENTRY_PRICE - loser_price
            self._accumulated_loss += prev_winner_qty * max(0, actual_loss_per_share)

            pivot_shares = self._calculate_pivot_shares()
            pivot_cost = self._calculate_pivot_cost(pivot_shares, winner_price)

            total_invested = self.cost_up + self.cost_down
            actual_cash = max(0, self.starting_balance - total_invested)

            if pivot_cost > actual_cash:
                max_affordable = actual_cash / winner_price if winner_price > 0 else 0
                if max_affordable * winner_price < self.min_trade_size:
                    self.current_mode = 'budget_exhausted'
                    self.mode_reason = (f'Cannot pivot - only ${actual_cash:.0f} left '
                                        f'(need ${pivot_cost:.0f})')
                    self._record_history()
                    return trades_made
                pivot_shares = max_affordable
                pivot_cost = max_affordable * winner_price

            self._pivot_count += 1

            ok, ap, aq = self.execute_buy(winner, winner_price, pivot_shares, timestamp)
            if ok:
                trades_made.append(('BUY', winner, ap, aq))
                actual_cost = ap * aq
                self._current_winner = winner

                self._place_sell_order(winner, aq, self.SELL_TARGET, actual_cost, timestamp)
                trades_made.append(('SELL_PLACED', winner, self.SELL_TARGET, aq))

                self.current_mode = 'pivoting'
                self.mode_reason = (f'PIVOT #{self._pivot_count}: {winner} {aq:.1f}sh@${ap:.3f} | '
                                    f'SELL @ ${self.SELL_TARGET:.2f} | '
                                    f'acc.loss ${self._accumulated_loss:.2f}')
            else:
                self.current_mode = 'pivot_failed'
                self.mode_reason = f'Pivot failed: {winner} @ ${winner_price:.3f}'

            self._record_history()
            return trades_made

        active_sells = [s for s in self._pending_sells if not s.filled]
        sell_desc = ', '.join(f"{s.side} {s.qty:.0f}sh@${s.min_price:.2f}" for s in active_sells) if active_sells else 'none'
        self.current_mode = 'holding'
        self.mode_reason = (f'Holding {self.qty_up:.1f}UP+{self.qty_down:.1f}DN | '
                            f'winner={winner} ${winner_price:.2f} | '
                            f'sells: {sell_desc}')

        self._record_history()
        return trades_made

    def _feed_spread_engine(self, up_price: float, down_price: float) -> dict:
        info = self.spread_engine.update(up_price, down_price)
        simple_spread = abs(1.0 - up_price - down_price)
        self.spread_history.append(simple_spread)
        if self.spread_history:
            self.avg_spread = sum(self.spread_history) / len(self.spread_history)
        return info

    def _record_history(self):
        if self.qty_up + self.qty_down > 0:
            self.mgp_history.append(self.calculate_locked_profit())
            self.pnl_up_history.append(self.calculate_pnl_if_up_wins())
            self.pnl_down_history.append(self.calculate_pnl_if_down_wins())

    def get_balance_status(self) -> Dict:
        if self._market_complete:
            return {'delta_pct': 0, 'direction': 'BALANCED',
                    'status': 'PROFIT TAKEN', 'color': 'cyan', 'icon': '💰'}
        active_sells = [s for s in self._pending_sells if not s.filled]
        if active_sells:
            return {'delta_pct': self.position_delta_pct, 'direction': self.position_delta_direction,
                    'status': f'{len(active_sells)} SELL ORDERS', 'color': 'yellow', 'icon': '📋'}
        delta = self.position_delta_pct
        if delta <= 5:
            return {'delta_pct': delta, 'direction': self.position_delta_direction,
                    'status': 'BALANCED', 'color': 'green', 'icon': '✅'}
        return {'delta_pct': delta, 'direction': self.position_delta_direction,
                'status': 'HOLDING', 'color': 'orange', 'icon': '⏳'}

    def get_state(self) -> dict:
        locked = self.calculate_locked_profit()
        pnl_up = self.calculate_pnl_if_up_wins()
        pnl_down = self.calculate_pnl_if_down_wins()
        best_case = max(pnl_up, pnl_down)
        qty_ratio = self.qty_up / self.qty_down if self.qty_down > 0 else (999 if self.qty_up > 0 else 1.0)
        se = self.spread_engine.get_state()
        arb_locked = self.both_scenarios_positive()

        active_sells = [
            {
                'side': s.side,
                'qty': s.qty,
                'min_price': s.min_price,
                'round': s.round_num,
                'placed_at': s.placed_at,
            }
            for s in self._pending_sells if not s.filled
        ]
        filled_sells = [
            {
                'side': s.side,
                'qty': s.fill_qty,
                'fill_price': s.fill_price,
                'proceeds': s.proceeds,
                'profit': s.proceeds - s.cost_basis,
                'round': s.round_num,
                'fill_time': s.fill_time,
            }
            for s in self._pending_sells if s.filled
        ]

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
            'is_balanced': self.position_delta_pct <= 5.0,
            'trade_count': self.trade_count,
            'pivot_count': self._pivot_count,
            'max_pivots': self.MAX_PIVOTS,
            'equalized': self._equalized,
            'market_status': self.market_status,
            'resolution_outcome': self.resolution_outcome,
            'final_pnl': self.final_pnl,
            'final_pnl_gross': self.final_pnl_gross,
            'fees_paid': 0.0,
            'payout': self.payout,
            'max_hedge_up': 0.99 - self.avg_down if self.avg_down > 0 else 0.99,
            'max_hedge_down': 0.99 - self.avg_up if self.avg_up > 0 else 0.99,
            'current_mode': self.current_mode,
            'mode_reason': self.mode_reason,
            'pnl_if_up_wins': pnl_up,
            'pnl_if_down_wins': pnl_down,
            'delta_direction': self.position_delta_direction,
            'avg_spread': self.avg_spread,
            'arb_locked': arb_locked,
            'mgp': locked,
            'deficit': self.deficit(),
            'max_price_for_lock': self.max_price_for_positive_mgp() if self.deficit() > 0 else 0.0,
            'z_score': se.get('z_score', 0.0),
            'spread_signal': se.get('signal', SIGNAL_NONE),
            'spread_beta': se.get('beta', 1.0),
            'spread_delta_pct': se.get('position_delta_pct', 0.0),
            'bb_upper': se.get('bb_upper', 0.0),
            'bb_lower': se.get('bb_lower', 0.0),
            'spread_engine_ready': se.get('is_ready', False),
            'mgp_history': list(self.mgp_history),
            'pnl_up_history': list(self.pnl_up_history),
            'pnl_down_history': list(self.pnl_down_history),
            'z_history': se.get('z_history', []),
            'spread_history_arr': se.get('spread_history', []),
            'bb_upper_history': se.get('bb_upper_history', []),
            'bb_lower_history': se.get('bb_lower_history', []),
            'signal_history': se.get('signal_history', []),
            'entry_score': self._entry_score,
            'ema_fast': self.up_tracker.ema_20,
            'ema_slow': self.up_tracker.ema_50,
            'ash_bb_lower': None,
            'ash_bb_upper': None,
            'min_combined_seen': self._min_combined_seen,
            'tick_count': self._tick_count,
            'z_score_up': self.up_tracker.z_score,
            'z_score_down': self.down_tracker.z_score,
            'atr_up': self.up_tracker.atr,
            'atr_down': self.down_tracker.atr,
            'exposure_priority': self._exposure_priority,
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
            'exec_stats': self.exec_sim.get_stats(),
            'market_complete': self._market_complete,
            'accumulated_loss': self._accumulated_loss,
            'active_sells': active_sells,
            'filled_sells': filled_sells,
            'total_sell_proceeds': self._total_sell_proceeds,
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
            'momentum_up': self.up_tracker.momentum,
            'momentum_down': self.down_tracker.momentum,
            'reversal_score_up': self.up_tracker.reversal_score,
            'reversal_score_down': self.down_tracker.reversal_score,
            'falling_knife_up': self.up_tracker.is_falling_knife,
            'falling_knife_down': self.down_tracker.is_falling_knife,
            'market_complete': self._market_complete,
            'pivot_count': self._pivot_count,
            'max_pivots': self.MAX_PIVOTS,
            'active_sells': len([s for s in self._pending_sells if not s.filled]),
        }

    def resolve_market(self, outcome: str) -> float:
        self.market_status = 'resolved'
        self.resolution_outcome = outcome

        self.payout = self.qty_up if outcome == 'UP' else self.qty_down
        total_cost = self.cost_up + self.cost_down
        fees = self.calculate_total_fees()
        self.last_fees_paid = fees

        pnl = self.payout + self._total_sell_proceeds - total_cost - fees
        self.final_pnl = pnl
        self.final_pnl_gross = self.payout + self._total_sell_proceeds - total_cost
        self.cash += max(0.0, self.payout - fees)
        return pnl

    def close_market(self):
        self.market_status = 'closed'
