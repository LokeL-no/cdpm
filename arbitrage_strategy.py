#!/usr/bin/env python3
"""
Balanced Spread Capture Strategy for Polymarket binary markets.

This strategy focuses on quoting both sides of the book (UP/DOWN) with
small, neutral exposures. It only engages when spreads are wide enough
and there is sufficient time left in the 15‑minute window. Inventory is
kept balanced via automated hedging rules, and exposure is reduced as
the market approaches expiry.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from execution_simulator import ExecutionSimulator

FEE_RATE = 0.015
FEE_MULT = 1.0 + FEE_RATE


@dataclass
class BookMetrics:
    token: str
    best_bid: float = 0.0
    best_ask: float = 0.0
    bid_size: float = 0.0
    ask_size: float = 0.0
    spread: float = 0.0
    mid: float = 0.0
    valid: bool = False


@dataclass
class QuotePlan:
    token: str
    side: str  # "bid" or "ask"
    price: float
    qty: float
    usd: float
    aggressive: bool
    placed_at: float = field(default_factory=time.time)
    cooldown: float = 1.5


class ArbitrageStrategy:
    STRATEGY_NAME = "Balanced Spread Capture"

    def __init__(self, market_budget: float, starting_balance: float,
                 exec_sim: ExecutionSimulator = None):
        self.market_budget = market_budget
        self.starting_balance = starting_balance
        self.cash_ref = {'balance': starting_balance}

        self.exec_sim = exec_sim or ExecutionSimulator(
            latency_ms=25.0,
            max_slippage_pct=2.0,
        )

        # Inventory tracking – clean cash_out / cash_in model
        self.qty_up = 0.0
        self.qty_down = 0.0
        self.cost_up = 0.0
        self.cost_down = 0.0
        self.cash_out = 0.0        # all money spent (buys + fees)
        self.cash_in = 0.0         # all money received (sells - fees)
        self.total_fees_paid = 0.0
        # kept for backward compat in UI:
        self.total_sell_proceeds = 0.0
        self.net_invested = 0.0

        # State
        self.trade_count = 0
        self.trade_log: List[dict] = []
        self.market_status = 'open'
        self.current_mode = 'standby'
        self.entry_spread = 0.020
        self.maintain_spread = 0.016
        self.mode_reason = f'Waiting for spread >= {self.entry_spread:.3f}'
        self.resolution_outcome = None
        self.final_pnl = None
        self.final_pnl_gross = None
        self.payout = 0.0
        self.last_fees_paid = 0.0
        self.window_start: Optional[datetime] = None
        self.window_end: Optional[datetime] = None

        # Quote management
        self.quote_targets: Dict[str, Dict[str, Optional[QuotePlan]]] = {
            'UP': {'bid': None, 'ask': None},
            'DOWN': {'bid': None, 'ask': None},
        }
        self.last_quote_refresh = 0.0
        self.last_fill_time = 0.0
        self.quotes_paused_reason = ''

        # Strategy tuning
        self.fill_tolerance = 0.0012
        self.base_quote_usd = 18.0
        self.aggressive_quote_usd = 32.0
        self.min_trade_size = 1.0
        self.max_shares_per_order = 250.0
        self.min_time_to_quote = 120.0  # seconds
        self.exit_time = 75.0          # seconds
        self.spread_floor = self.entry_spread
        self.exit_spread = 0.018
        self._quoting_allowed = False
        self.min_budget_ratio = 0.15
        self.max_inventory_usd = 80.0
        self.loss_limit = -15.0
        self.mid_bounds = (0.15, 0.85)

        # Telemetry / history for UI compatibility
        self.mgp_history = deque(maxlen=180)
        self.pnl_up_history = deque(maxlen=180)
        self.pnl_down_history = deque(maxlen=180)
        self.z_history = deque(maxlen=60)
        self.spread_history = deque(maxlen=60)
        self.signal_history = deque(maxlen=60)
        self.bb_upper_history = deque(maxlen=60)
        self.bb_lower_history = deque(maxlen=60)

        self.active_sells: List[dict] = []
        self.filled_sells: List[dict] = []
        self.last_status_time = 0.0
        self.order_activity = self._init_order_activity()
        self.order_events = deque(maxlen=40)
        self.last_quotes = self._init_quote_memory()
        self.pending_recovery = self._init_quote_memory()
        self.quote_modifiers = self._init_quote_modifiers()
        self.recovery_window = 15.0
        self._last_cancel_ts = 0.0
        self._last_cancel_spreads: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Order tracking helpers
    # ------------------------------------------------------------------
    def _init_order_activity(self) -> Dict[str, Dict[str, dict]]:
        return {
            'UP': {'bid': self._new_order_status(), 'ask': self._new_order_status()},
            'DOWN': {'bid': self._new_order_status(), 'ask': self._new_order_status()},
        }

    @staticmethod
    def _new_order_status() -> Dict[str, Optional[float]]:
        return {
            'state': 'IDLE',
            'price': None,
            'qty': None,
            'fill_price': None,
            'fill_qty': None,
            'placed_at': None,
            'filled_at': None,
            'updated_at': None,
            'aggressive': False,
        }

    def _update_order_status(self, token: str, side: str, state: str,
                              price: Optional[float], qty: Optional[float],
                              aggressive: bool = False):
        token_state = self.order_activity.get(token)
        if not token_state:
            return
        status = token_state.get(side)
        if not status:
            return

        now_str = datetime.now(timezone.utc).strftime('%H:%M:%S')
        state_upper = state.upper()
        status['state'] = state_upper
        status['updated_at'] = now_str

        if state_upper == 'PLACED':
            status['price'] = price
            status['qty'] = qty
            status['placed_at'] = now_str
            status['fill_price'] = None
            status['fill_qty'] = None
            status['filled_at'] = None
            status['aggressive'] = aggressive
        elif state_upper == 'FILLED':
            status['fill_price'] = price
            status['fill_qty'] = qty
            status['filled_at'] = now_str
            status['aggressive'] = aggressive
        elif state_upper == 'CANCELLED':
            if price is not None:
                status['price'] = price
            if qty is not None:
                status['qty'] = qty
            status['fill_price'] = None
            status['fill_qty'] = None
            status['filled_at'] = None
            status['aggressive'] = False
        elif state_upper == 'IDLE':
            status.update({
                'price': None,
                'qty': None,
                'fill_price': None,
                'fill_qty': None,
                'placed_at': None,
                'filled_at': None,
                'aggressive': False,
            })

    def _record_order_event(self, event_type: str, token: str, side: str,
                             price: Optional[float], qty: Optional[float],
                             aggressive: bool = False, reason: Optional[str] = None):
        event = {
            'time': datetime.now(timezone.utc).strftime('%H:%M:%S'),
            'type': event_type,
            'token': token,
            'side': side.upper(),
            'price': price,
            'qty': qty,
            'aggressive': aggressive,
        }
        if reason:
            event['reason'] = reason
        self.order_events.append(event)

    def _init_quote_memory(self) -> Dict[str, Dict[str, Optional[dict]]]:
        return {
            'UP': {'bid': None, 'ask': None},
            'DOWN': {'bid': None, 'ask': None},
        }

    def _init_quote_modifiers(self) -> Dict[str, Dict[str, float]]:
        return {
            'UP': {'size_scale': 1.0, 'offset_scale': 1.0},
            'DOWN': {'size_scale': 1.0, 'offset_scale': 1.0},
        }

    def _capture_last_quote(self, token: str, side: str, plan: QuotePlan, skew: float):
        self.last_quotes[token][side] = {
            'price': plan.price,
            'qty': plan.qty,
            'skew': skew,
            'timestamp': time.time(),
            'aggressive': plan.aggressive,
        }

    def _record_recovery_candidate(self, token: str, side: str,
                                   plan: QuotePlan, reason: Optional[str]):
        if not plan or not reason:
            return
        if 'spread' not in reason.lower():
            # Only recover when spread guard forced the cancel.
            return
        snapshot = self.last_quotes[token][side] or {
            'price': plan.price,
            'qty': plan.qty,
            'aggressive': plan.aggressive,
        }
        current_skew = self._inventory_skew()
        self.pending_recovery[token][side] = {
            'price': snapshot['price'],
            'qty': snapshot['qty'],
            'skew': current_skew,
            'expires_at': time.time() + self.recovery_window,
            'aggressive': snapshot.get('aggressive', False),
        }

    def _apply_recovery_overrides(self, token: str, metrics: BookMetrics,
                                  plans: Dict[str, Optional[QuotePlan]],
                                  skew: float, now: float):
        for side in ('bid', 'ask'):
            recovery = self.pending_recovery[token][side]
            if not recovery:
                continue
            if now > recovery['expires_at']:
                self.pending_recovery[token][side] = None
                continue
            if metrics.spread < self.entry_spread:
                continue
            if abs(skew - recovery['skew']) > 0.10:
                self.pending_recovery[token][side] = None
                continue

            price = recovery['price']
            qty = recovery['qty']
            if price is None or qty is None or qty < self.min_trade_size:
                self.pending_recovery[token][side] = None
                continue

            if side == 'bid':
                price = min(price, metrics.best_ask - 0.001)
                price = max(price, metrics.best_bid)
                qty = min(qty, self._max_affordable_qty(price))
            else:
                price = max(price, metrics.best_bid + 0.001)
                price = min(price, metrics.best_ask)
                if token == 'UP':
                    qty = min(qty, self.qty_up)
                else:
                    qty = min(qty, self.qty_down)

            price = max(0.02, min(0.98, price))
            qty = min(qty, self.max_shares_per_order)
            if qty < self.min_trade_size:
                self.pending_recovery[token][side] = None
                continue

            plans[side] = QuotePlan(
                token, side, price, qty, price * qty,
                recovery.get('aggressive', False), placed_at=now,
            )
            self.pending_recovery[token][side] = None

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------
    @property
    def cash(self) -> float:
        return self.cash_ref['balance']

    @cash.setter
    def cash(self, value: float):
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def check_and_trade(
        self,
        up_price: float,
        down_price: float,
        timestamp: str,
        time_to_close: Optional[float] = None,
        up_bid: Optional[float] = None,
        down_bid: Optional[float] = None,
        up_orderbook: Optional[dict] = None,
        down_orderbook: Optional[dict] = None,
    ) -> List[Tuple[str, str, float, float]]:
        trades: List[Tuple[str, str, float, float]] = []

        if self.market_status != 'open':
            self.current_mode = 'closed'
            self.mode_reason = 'Market not open'
            return trades

        up_metrics = self._extract_metrics('UP', up_orderbook)
        down_metrics = self._extract_metrics('DOWN', down_orderbook)
        metrics_map = {'UP': up_metrics, 'DOWN': down_metrics}

        if not up_metrics.valid or not down_metrics.valid:
            self.current_mode = 'waiting'
            self.mode_reason = 'Awaiting liquid orderbooks'
            self._cancel_all_quotes('stale book')
            self._record_histories(up_metrics, down_metrics)
            return trades

        quoting_enabled = self._should_quote(metrics_map, time_to_close)

        # Process fills first so we react to price moves immediately.
        trades.extend(
            self._process_quote_fill(
                'UP', up_metrics, up_orderbook, timestamp,
            )
        )
        trades.extend(
            self._process_quote_fill(
                'DOWN', down_metrics, down_orderbook, timestamp,
            )
        )

        now = time.time()
        if quoting_enabled:
            trades.extend(
                self._refresh_quotes(metrics_map, now, timestamp)
            )
            self.current_mode = 'quoting'
            self.mode_reason = self._describe_quote_state(metrics_map, time_to_close)
        else:
            self._cancel_all_quotes(self.quotes_paused_reason or 'conditions')
            self.current_mode = 'standby'
            self.mode_reason = self.quotes_paused_reason or 'Conditions not met'

        trades.extend(
            self._rebalance_if_needed(metrics_map, up_orderbook, down_orderbook, timestamp)
        )

        if time_to_close is not None and time_to_close < self.exit_time:
            trades.extend(
                self._flatten_positions(up_orderbook, down_orderbook, timestamp, time_to_close)
            )
            self.current_mode = 'exit'
            self.mode_reason = 'Window closing'
            self._quoting_allowed = False

        if self.calculate_locked_profit() <= self.loss_limit:
            self.current_mode = 'halt'
            self.mode_reason = 'Loss limit reached'
            self._cancel_all_quotes('loss')

        self._record_histories(up_metrics, down_metrics)
        return trades

    def resolve_market(self, outcome: str) -> float:
        self.market_status = 'resolved'
        self.resolution_outcome = outcome

        self.payout = self.qty_up if outcome == 'UP' else self.qty_down
        fees = self.calculate_total_fees()
        self.last_fees_paid = fees

        self.cash += self.payout
        self.cash_in += self.payout
        pnl = self.cash_in - self.cash_out
        self.final_pnl = pnl
        self.final_pnl_gross = pnl + fees
        return pnl

    def close_market(self):
        self.market_status = 'closed'

    def set_market_start_time(self, start_time: Optional[datetime]):
        self.window_start = start_time

    # ------------------------------------------------------------------
    # Quote management
    # ------------------------------------------------------------------
    def _should_quote(self, metrics_map: Dict[str, BookMetrics],
                      time_to_close: Optional[float]) -> bool:
        gate_threshold = self.maintain_spread if self._quoting_allowed else self.entry_spread
        spreads_snapshot = {token: metrics.spread for token, metrics in metrics_map.items() if metrics}
        for token in ('UP', 'DOWN'):
            metrics = metrics_map[token]
            size_scale = 1.0
            offset_scale = 1.0
            if not metrics.valid:
                self.quotes_paused_reason = f"{token} book invalid"
                self._quoting_allowed = False
                self._last_cancel_spreads = spreads_snapshot
                return False
            if metrics.spread < gate_threshold:
                self.quotes_paused_reason = (f"{token} spread {metrics.spread:.3f} < "
                                             f"{gate_threshold:.3f}")
                self._quoting_allowed = False
                self._last_cancel_spreads = spreads_snapshot
                return False
            if metrics.mid <= 0.10 or metrics.mid >= 0.90:
                self.quotes_paused_reason = f"{token} mid {metrics.mid:.3f} outside hard bounds"
                self._quoting_allowed = False
                self._last_cancel_spreads = spreads_snapshot
                return False
            if not (self.mid_bounds[0] <= metrics.mid <= self.mid_bounds[1]):
                # Soft guard: keep quoting but scale down size and widen offset.
                size_scale = 0.5
                offset_scale = 1.5

            self.quote_modifiers[token]['size_scale'] = size_scale
            self.quote_modifiers[token]['offset_scale'] = offset_scale

        if time_to_close is not None and time_to_close < self.min_time_to_quote:
            self.quotes_paused_reason = 'Less than 2 minutes remaining'
            self._quoting_allowed = False
            self._last_cancel_spreads = spreads_snapshot
            return False

        if self.remaining_budget() < self.market_budget * self.min_budget_ratio:
            self.quotes_paused_reason = 'Reserve < 15%'
            self._quoting_allowed = False
            self._last_cancel_spreads = spreads_snapshot
            return False

        if self._current_exposure_usd() > self.max_inventory_usd:
            self.quotes_paused_reason = 'Inventory cap reached'
            self._quoting_allowed = False
            self._last_cancel_spreads = spreads_snapshot
            return False

        self.quotes_paused_reason = ''
        self._quoting_allowed = True
        return True

    def _refresh_quotes(self, metrics_map: Dict[str, BookMetrics], now: float,
                         timestamp: str) -> List[Tuple[str, str, float, float]]:
        trades: List[Tuple[str, str, float, float]] = []
        skew = self._inventory_skew()

        for token in ('UP', 'DOWN'):
            metrics = metrics_map[token]
            plans = self._build_quote_plan(metrics, skew, now)
            self._apply_recovery_overrides(token, metrics, plans, skew, now)

            for side in ('bid', 'ask'):
                plan = plans.get(side)
                current_plan = self.quote_targets[token][side]

                if plan is None:
                    if current_plan is not None:
                        self._update_order_status(token, side, 'CANCELLED',
                                                  current_plan.price, current_plan.qty,
                                                  current_plan.aggressive)
                        self._record_order_event('QUOTE_CANCELLED', token, side,
                                                 current_plan.price, current_plan.qty,
                                                 current_plan.aggressive, reason='plan_removed')
                    self.quote_targets[token][side] = None
                    continue

                needs_refresh = (
                    current_plan is None or
                    abs(current_plan.price - plan.price) > 0.002 or
                    abs(current_plan.qty - plan.qty) > max(1.0, plan.qty * 0.2)
                )

                if needs_refresh:
                    self.quote_targets[token][side] = plan
                    trades.append((f'QUOTE_{side.upper()}', token, plan.price, plan.qty))
                    self.last_quote_refresh = now
                    self._update_order_status(token, side, 'PLACED',
                                              plan.price, plan.qty, plan.aggressive)
                    self._record_order_event('QUOTE_PLACED', token, side,
                                             plan.price, plan.qty, plan.aggressive)
                    self._capture_last_quote(token, side, plan, skew)

        return trades

    def _build_quote_plan(self, metrics: BookMetrics, skew: float,
                          now: float) -> Dict[str, Optional[QuotePlan]]:
        if not metrics.valid:
            return {'bid': None, 'ask': None}

        aggressive = metrics.spread >= 0.05
        mods = self.quote_modifiers.get(metrics.token, {'size_scale': 1.0, 'offset_scale': 1.0})
        offset_scale = mods.get('offset_scale', 1.0)
        size_scale = mods.get('size_scale', 1.0)
        quote_spread = max(0.008, metrics.spread * 0.5) * offset_scale
        base_usd = (self.aggressive_quote_usd if aggressive else self.base_quote_usd) * size_scale

        token_skew = skew if metrics.token == 'UP' else -skew
        bid_scale = max(0.25, 1.0 - max(0.0, token_skew) * 1.2)
        ask_scale = min(1.8, 1.0 + max(0.0, token_skew) * 1.5)

        bid_price = metrics.mid - quote_spread
        ask_price = metrics.mid + quote_spread

        bid_price = min(bid_price, metrics.best_ask - 0.001)
        bid_price = max(bid_price, metrics.best_bid)
        ask_price = max(ask_price, metrics.best_bid + 0.001)
        ask_price = min(ask_price, metrics.best_ask)

        bid_price = max(0.02, min(0.98, bid_price))
        ask_price = max(bid_price + 0.001, min(0.98, ask_price))

        bid_qty = (base_usd * bid_scale) / max(bid_price, 0.05)
        ask_qty = (base_usd * ask_scale) / max(ask_price, 0.05)

        bid_qty = min(self.max_shares_per_order, bid_qty)
        ask_qty = min(self.max_shares_per_order, ask_qty)

        bid_qty = min(bid_qty, self._max_affordable_qty(bid_price))
        if metrics.token == 'UP':
            ask_qty = min(ask_qty, self.qty_up)
        else:
            ask_qty = min(ask_qty, self.qty_down)

        plans: Dict[str, Optional[QuotePlan]] = {'bid': None, 'ask': None}
        if bid_qty >= self.min_trade_size:
            plans['bid'] = QuotePlan(metrics.token, 'bid', bid_price, bid_qty,
                                     bid_price * bid_qty, aggressive,
                                     placed_at=now)
        if ask_qty >= self.min_trade_size:
            plans['ask'] = QuotePlan(metrics.token, 'ask', ask_price, ask_qty,
                                     ask_price * ask_qty, aggressive,
                                     placed_at=now)
        return plans

    def _process_quote_fill(self, token: str, metrics: BookMetrics,
                            orderbook: Optional[dict], timestamp: str
                            ) -> List[Tuple[str, str, float, float]]:
        trades: List[Tuple[str, str, float, float]] = []
        quote_info = self.quote_targets[token]

        bid_plan = quote_info.get('bid')
        if bid_plan and metrics.best_ask <= bid_plan.price + self.fill_tolerance:
            trade = self._execute_buy(token, bid_plan.price, bid_plan.qty,
                                      orderbook, timestamp, reason='quote_bid_fill')
            if trade:
                trades.append(trade)
                _, _, fill_price, fill_qty = trade
                self._update_order_status(token, 'bid', 'FILLED', fill_price, fill_qty,
                                          bid_plan.aggressive)
                self._record_order_event('FILL', token, 'bid', fill_price, fill_qty,
                                         bid_plan.aggressive, reason='quote_bid_fill')
            else:
                self._update_order_status(token, 'bid', 'CANCELLED',
                                          bid_plan.price, bid_plan.qty,
                                          bid_plan.aggressive)
                self._record_order_event('QUOTE_CANCELLED', token, 'bid',
                                         bid_plan.price, bid_plan.qty,
                                         bid_plan.aggressive, reason='fill_rejected')
            self.quote_targets[token]['bid'] = None

        ask_plan = quote_info.get('ask')
        if ask_plan and metrics.best_bid >= ask_plan.price - self.fill_tolerance:
            trade = self._execute_sell(token, ask_plan.price, ask_plan.qty,
                                       orderbook, timestamp, reason='quote_ask_fill')
            if trade:
                trades.append(trade)
                _, _, fill_price, fill_qty = trade
                self._update_order_status(token, 'ask', 'FILLED', fill_price, fill_qty,
                                          ask_plan.aggressive)
                self._record_order_event('FILL', token, 'ask', fill_price, fill_qty,
                                         ask_plan.aggressive, reason='quote_ask_fill')
            else:
                self._update_order_status(token, 'ask', 'CANCELLED',
                                          ask_plan.price, ask_plan.qty,
                                          ask_plan.aggressive)
                self._record_order_event('QUOTE_CANCELLED', token, 'ask',
                                         ask_plan.price, ask_plan.qty,
                                         ask_plan.aggressive, reason='fill_rejected')
            self.quote_targets[token]['ask'] = None

        return trades

    def _cancel_all_quotes(self, reason: str):
        for token, sides in self.quote_targets.items():
            for side in ('bid', 'ask'):
                plan = sides.get(side)
                if plan is not None:
                    self._record_recovery_candidate(token, side, plan, reason)
                    self._update_order_status(token, side, 'CANCELLED',
                                              plan.price, plan.qty, plan.aggressive)
                    self._record_order_event('QUOTE_CANCELLED', token, side,
                                             plan.price, plan.qty, plan.aggressive,
                                             reason=reason or 'cancel_all')
                sides[side] = None
        if reason:
            self.mode_reason = f'Paused quotes ({reason})'
            now_ts = time.time()
            elapsed = now_ts - self._last_cancel_ts if self._last_cancel_ts else 0.0
            spread_info = ''
            if self._last_cancel_spreads:
                parts = [f"{tok}:{spread:.4f}" for tok, spread in self._last_cancel_spreads.items()]
                spread_info = f" | spreads {', '.join(parts)}"
            print(f"⚠️ Cancelled quotes - reason: {reason} | elapsed {elapsed:.1f}s since last cancel{spread_info}")
            self._last_cancel_ts = now_ts
        self._quoting_allowed = False

    # ------------------------------------------------------------------
    # Execution helpers
    # ------------------------------------------------------------------
    def _execute_buy(self, token: str, price: float, qty: float,
                     orderbook: Optional[dict], timestamp: str,
                     reason: str) -> Optional[Tuple[str, str, float, float]]:
        affordable = self._max_affordable_qty(price)
        qty = min(qty, affordable, self.max_shares_per_order)
        if qty < self.min_trade_size or price <= 0:
            return None

        fill = self.exec_sim.simulate_buy(token, price, qty, orderbook)
        if not fill.filled:
            return None

        total_cost = fill.total_cost
        fee = total_cost * FEE_RATE
        total_with_fee = total_cost + fee
        if total_with_fee > self.cash:
            return None

        self.cash -= total_with_fee
        self.cash_out += total_with_fee
        self.total_fees_paid += fee
        self.net_invested = self.cash_out - self.cash_in  # compat
        self.trade_count += 1
        self.last_fill_time = time.time()

        if token == 'UP':
            self.qty_up += fill.filled_qty
            self.cost_up += total_cost
        else:
            self.qty_down += fill.filled_qty
            self.cost_down += total_cost

        self._log_trade('BUY', token, fill.fill_price, fill.filled_qty,
                        total_cost, reason, fill)
        return ('BUY', token, fill.fill_price, fill.filled_qty)

    def _execute_sell(self, token: str, price: float, qty: float,
                      orderbook: Optional[dict], timestamp: str,
                      reason: str) -> Optional[Tuple[str, str, float, float]]:
        if token == 'UP':
            qty = min(qty, self.qty_up)
        else:
            qty = min(qty, self.qty_down)

        qty = min(qty, self.max_shares_per_order)
        if qty < self.min_trade_size or price <= 0:
            return None

        fill = self.exec_sim.simulate_sell(token, price, qty, orderbook)
        if not fill.filled:
            return None

        proceeds = fill.total_cost
        fee = proceeds * FEE_RATE
        net_proceeds = proceeds - fee
        self.cash += net_proceeds
        self.cash_in += net_proceeds
        self.total_sell_proceeds += net_proceeds
        self.total_fees_paid += fee
        self.net_invested = self.cash_out - self.cash_in  # compat
        self.trade_count += 1
        self.last_fill_time = time.time()

        if token == 'UP':
            if self.qty_up > 0:
                avg_cost = self.cost_up / self.qty_up if self.qty_up > 0 else 0.0
                cost_removed = avg_cost * fill.filled_qty
                self.cost_up = max(0.0, self.cost_up - cost_removed)
            self.qty_up = max(0.0, self.qty_up - fill.filled_qty)
        else:
            if self.qty_down > 0:
                avg_cost = self.cost_down / self.qty_down if self.qty_down > 0 else 0.0
                cost_removed = avg_cost * fill.filled_qty
                self.cost_down = max(0.0, self.cost_down - cost_removed)
            self.qty_down = max(0.0, self.qty_down - fill.filled_qty)

        self._log_trade('SELL', token, fill.fill_price, fill.filled_qty,
                        proceeds, reason, fill)
        return ('SELL', token, fill.fill_price, fill.filled_qty)

    def _rebalance_if_needed(self, metrics_map: Dict[str, BookMetrics],
                             up_orderbook: Optional[dict], down_orderbook: Optional[dict],
                             timestamp: str) -> List[Tuple[str, str, float, float]]:
        trades: List[Tuple[str, str, float, float]] = []
        skew = self._inventory_skew()
        if abs(skew) < 0.35:
            return trades

        target_skew = 0.2 * (1 if skew > 0 else -1)
        total_qty = self.qty_up + self.qty_down
        desired_delta = (abs(skew) - abs(target_skew)) * total_qty
        hedge_qty = max(self.min_trade_size, desired_delta)

        if skew > 0:
            # Too much UP – buy DOWN to hedge
            trade = self._execute_buy('DOWN', metrics_map['DOWN'].best_ask,
                                      hedge_qty, down_orderbook, timestamp,
                                      reason='hedge_down')
        else:
            trade = self._execute_buy('UP', metrics_map['UP'].best_ask,
                                      hedge_qty, up_orderbook, timestamp,
                                      reason='hedge_up')
        if trade:
            trades.append(trade)
        return trades

    def _flatten_positions(self, up_orderbook: Optional[dict],
                           down_orderbook: Optional[dict], timestamp: str,
                           time_to_close: float) -> List[Tuple[str, str, float, float]]:
        trades: List[Tuple[str, str, float, float]] = []
        if self.qty_up > 0:
            trade = self._execute_sell('UP',
                                       max(0.02, self.avg_up * 0.98),
                                       self.qty_up, up_orderbook, timestamp,
                                       reason='exit_up')
            if trade:
                trades.append(trade)
        if self.qty_down > 0:
            trade = self._execute_sell('DOWN',
                                       max(0.02, self.avg_down * 0.98),
                                       self.qty_down, down_orderbook, timestamp,
                                       reason='exit_down')
            if trade:
                trades.append(trade)
        return trades

    # ------------------------------------------------------------------
    # Reporting helpers
    # ------------------------------------------------------------------
    def calculate_total_fees(self, extra_cost: float = 0.0) -> float:
        return self.total_fees_paid + max(0.0, extra_cost)

    def calculate_pnl_if_up_wins(self) -> float:
        return self.cash_in - self.cash_out + self.qty_up

    def calculate_pnl_if_down_wins(self) -> float:
        return self.cash_in - self.cash_out + self.qty_down

    def calculate_locked_profit(self) -> float:
        return min(self.calculate_pnl_if_up_wins(), self.calculate_pnl_if_down_wins())

    def calculate_max_profit(self) -> float:
        return max(self.calculate_pnl_if_up_wins(), self.calculate_pnl_if_down_wins())

    @property
    def locked_profit(self) -> float:
        return self.calculate_locked_profit()

    def remaining_budget(self) -> float:
        spent = self.cost_up + self.cost_down
        return max(0.0, self.market_budget - spent)

    def get_balance_status(self) -> Dict[str, str]:
        delta = self._inventory_skew()
        pct = abs(delta) * 100
        if pct <= 5:
            return {'status': 'balanced', 'icon': '✅'}
        if pct <= 15:
            return {'status': 'ok', 'icon': '⚠️'}
        return {'status': 'imbalanced', 'icon': '🔴'}

    def get_state(self) -> Dict:
        locked = self.calculate_locked_profit()
        pnl_up = self.calculate_pnl_if_up_wins()
        pnl_down = self.calculate_pnl_if_down_wins()
        best_case = self.calculate_max_profit()
        qty_ratio = (self.qty_up / self.qty_down) if self.qty_down > 0 else (999 if self.qty_up > 0 else 1.0)
        arb_locked = locked >= 0 and self.qty_up > 0 and self.qty_down > 0

        state = {
            'strategy': self.STRATEGY_NAME,
            'starting_balance': self.starting_balance,
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
            'balance_pct': abs(self._inventory_skew()) * 100,
            'is_balanced': abs(self._inventory_skew()) * 100 <= 5.0,
            'trade_count': self.trade_count,
            'pivot_count': 0,
            'max_pivots': 0,
            'equalized': False,
            'market_status': self.market_status,
            'resolution_outcome': self.resolution_outcome,
            'final_pnl': self.final_pnl,
            'final_pnl_gross': self.final_pnl_gross,
            'fees_paid': self.total_fees_paid,
            'payout': self.payout,
            'max_hedge_up': 0.99 - self.avg_down if self.avg_down > 0 else 0.99,
            'max_hedge_down': 0.99 - self.avg_up if self.avg_up > 0 else 0.99,
            'current_mode': self.current_mode,
            'mode_reason': self.mode_reason,
            'pnl_if_up_wins': pnl_up,
            'pnl_if_down_wins': pnl_down,
            'delta_direction': 'UP' if self.qty_up > self.qty_down else ('DOWN' if self.qty_down > self.qty_up else 'BALANCED'),
            'avg_spread': (self.spread_history[-1] if self.spread_history else 0.0),
            'arb_locked': arb_locked,
            'mgp': locked,
            'deficit': abs(self.qty_up - self.qty_down),
            'max_price_for_lock': self._max_price_for_positive_mgp() if self.deficit() > 0 else 0.0,
            'z_score': 0.0,
            'spread_signal': 'NONE',
            'spread_beta': 1.0,
            'spread_delta_pct': abs(self._inventory_skew()) * 100,
            'bb_upper': 0.0,
            'bb_lower': 0.0,
            'spread_engine_ready': False,
            'mgp_history': list(self.mgp_history),
            'pnl_up_history': list(self.pnl_up_history),
            'pnl_down_history': list(self.pnl_down_history),
            'z_history': list(self.z_history),
            'spread_history_arr': list(self.spread_history),
            'bb_upper_history': list(self.bb_upper_history),
            'bb_lower_history': list(self.bb_lower_history),
            'signal_history': list(self.signal_history),
            'entry_score': 0.0,
            'ema_fast': None,
            'ema_slow': None,
            'ash_bb_lower': None,
            'ash_bb_upper': None,
            'min_combined_seen': 0.0,
            'tick_count': len(self.spread_history),
            'z_score_up': 0.0,
            'z_score_down': 0.0,
            'atr_up': 0.0,
            'atr_down': 0.0,
            'exposure_priority': 'NEUTRAL',
            'momentum_up': 0.0,
            'momentum_down': 0.0,
            'reversal_score_up': 0.0,
            'reversal_score_down': 0.0,
            'trend_dir_up': 0,
            'trend_dir_down': 0,
            'is_reversing_up': False,
            'is_reversing_down': False,
            'falling_knife_up': False,
            'falling_knife_down': False,
            'exec_stats': self.exec_sim.get_stats(),
            'market_complete': False,
            'accumulated_loss': 0.0,
            'active_sells': self.active_sells,
            'filled_sells': self.filled_sells,
            'total_sell_proceeds': self.total_sell_proceeds,
            'net_invested': self.net_invested,
            'cash_out': self.cash_out,
            'cash_in': self.cash_in,
            'order_activity': {
                token: {side: dict(info) for side, info in sides.items()}
                for token, sides in self.order_activity.items()
            },
            'recent_order_events': [dict(evt) for evt in self.order_events],
            'spread_thresholds': {
                'entry': self.entry_spread,
                'maintain': self.maintain_spread,
            },
        }
        return state

    def get_status_summary(self) -> Dict:
        balance = self.get_balance_status()
        return {
            'cash': self.cash,
            'qty_up': self.qty_up,
            'qty_down': self.qty_down,
            'avg_up': self.avg_up,
            'avg_down': self.avg_down,
            'cost_up': self.cost_up,
            'cost_down': self.cost_down,
            'pair_cost': self.pair_cost,
            'position_delta_pct': abs(self._inventory_skew()) * 100,
            'balance_status': balance['status'],
            'balance_icon': balance['icon'],
            'locked_profit': self.calculate_locked_profit(),
            'pnl_if_up_wins': self.calculate_pnl_if_up_wins(),
            'pnl_if_down_wins': self.calculate_pnl_if_down_wins(),
            'max_profit': self.calculate_max_profit(),
            'trade_count': self.trade_count,
            'current_mode': self.current_mode,
            'mode_reason': self.mode_reason,
            'avg_spread': (self.spread_history[-1] if self.spread_history else 0.0),
            'market_status': self.market_status,
            'z_score': 0.0,
            'beta': 1.0,
            'signal': 'NONE',
            'arb_locked': self.calculate_locked_profit() >= 0,
            'z_score_up': 0.0,
            'z_score_down': 0.0,
            'exposure_priority': 'NEUTRAL',
            'momentum_up': 0.0,
            'momentum_down': 0.0,
            'reversal_score_up': 0.0,
            'reversal_score_down': 0.0,
            'falling_knife_up': False,
            'falling_knife_down': False,
            'market_complete': False,
            'pivot_count': 0,
            'max_pivots': 0,
            'active_sells': len(self.active_sells),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _extract_metrics(self, token: str, orderbook: Optional[dict]) -> BookMetrics:
        metrics = BookMetrics(token=token)
        if not orderbook:
            return metrics

        bids = orderbook.get('bids') or []
        asks = orderbook.get('asks') or []
        if not bids or not asks:
            return metrics

        try:
            best_bid = max(bids, key=lambda x: float(x.get('price', 0.0)))
            best_ask = min(asks, key=lambda x: float(x.get('price', 1.0)))
        except (ValueError, TypeError):
            return metrics

        try:
            metrics.best_bid = float(best_bid.get('price', 0.0))
            metrics.bid_size = float(best_bid.get('size', 0.0))
            metrics.best_ask = float(best_ask.get('price', 0.0))
            metrics.ask_size = float(best_ask.get('size', 0.0))
        except (TypeError, ValueError):
            return metrics

        if metrics.best_bid <= 0 or metrics.best_ask <= 0 or metrics.best_ask <= metrics.best_bid:
            return metrics

        metrics.spread = metrics.best_ask - metrics.best_bid
        metrics.mid = (metrics.best_bid + metrics.best_ask) / 2.0
        metrics.valid = True
        return metrics

    def _max_affordable_qty(self, price: float) -> float:
        if price <= 0:
            return 0.0
        budget_qty = self.remaining_budget() / price if price > 0 else 0.0
        cash_qty = self.cash / (price * FEE_MULT) if price > 0 else 0.0
        return min(self.max_shares_per_order, budget_qty, cash_qty)

    def _current_exposure_usd(self) -> float:
        return self.cost_up + self.cost_down

    def _inventory_skew(self) -> float:
        total = self.qty_up + self.qty_down
        if total == 0:
            return 0.0
        return (self.qty_up - self.qty_down) / total

    def deficit(self) -> float:
        return abs(self.qty_up - self.qty_down)

    def _max_price_for_positive_mgp(self) -> float:
        d = self.deficit()
        if d <= 0:
            return 0.99
        larger_qty = max(self.qty_up, self.qty_down)
        total_cost = self.cost_up + self.cost_down
        numerator = larger_qty / FEE_MULT - total_cost
        if numerator <= 0:
            return 0.0
        return min(0.99, numerator / d)

    def _record_histories(self, up_metrics: BookMetrics, down_metrics: BookMetrics):
        locked = self.calculate_locked_profit()
        self.mgp_history.append(locked)
        self.pnl_up_history.append(self.calculate_pnl_if_up_wins())
        self.pnl_down_history.append(self.calculate_pnl_if_down_wins())

        avg_spread = (up_metrics.spread + down_metrics.spread) / 2.0
        self.spread_history.append(avg_spread)
        self.z_history.append(0.0)
        self.bb_upper_history.append(0.0)
        self.bb_lower_history.append(0.0)
        self.signal_history.append('NONE')

    def _describe_quote_state(self, metrics_map: Dict[str, BookMetrics],
                              time_to_close: Optional[float]) -> str:
        up = metrics_map['UP']
        down = metrics_map['DOWN']
        ttc = f"{time_to_close:.0f}s" if time_to_close is not None else '∞'
        return (f"Spread OK (UP {up.spread:.3f} | DOWN {down.spread:.3f}) | "
                f"Mid {up.mid:.3f}/{down.mid:.3f} | TTL {ttc}")

    def _log_trade(self, action: str, token: str, price: float, qty: float,
                   cost: float, reason: str, fill) -> None:
        self.trade_log.append({
            'time': datetime.now(timezone.utc).strftime('%H:%M:%S'),
            'side': token,
            'action': action,
            'price': price,
            'qty': qty,
            'cost': cost,
            'reason': reason,
            'slippage': getattr(fill, 'slippage', 0.0),
            'slippage_pct': getattr(fill, 'slippage_pct', 0.0),
            'slippage_cost': getattr(fill, 'slippage_cost', 0.0),
            'levels': getattr(fill, 'levels_consumed', 0),
            'partial': getattr(fill, 'partial', False),
            'pair_cost': self.pair_cost,
        })
        if len(self.trade_log) > 500:
            self.trade_log = self.trade_log[-500:]
