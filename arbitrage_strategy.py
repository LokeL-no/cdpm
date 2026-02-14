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
from trend_predictor import TrendPredictor

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
    STRATEGY_NAME = "Pair Cost Arbitrage"

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
        self.last_buy_fill: Optional[dict] = None
        self.last_sell_fill: Optional[dict] = None
        self.fill_history = deque(maxlen=240)
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

        # Pair-cost targeting strategy
        self.target_pair_cost = 0.970
        self.pair_cost_safety_margin = 1.000
        self.pair_cost_max_limit = 1.020
        self.balance_ratio_max = 1.10
        self.entry_trade_usd = 5.0    # Base entry size (faster base building)
        self.balance_trade_usd = 8.0   # Base balance/hedge size (pair completion priority)
        self.improve_trade_usd = 3.0   # Base improvement size
        self.max_imbalance_ratio = 1.4
        self.max_overexposure = 1.5    # Strict: never go beyond 1.5:1 ratio
        self.balanced_ratio_range = (0.85, 1.15)
        self.enable_sell_to_balance = False
        self.aggressive_balance_mode = False
        
        # Temporal arbitrage parameters
        self.combined_entry_threshold = 1.02  # Enter when combined < this (real markets ~1.01-1.03)
        self.max_entry_spread = 0.40          # Don't enter if spread > this (market already decided)
        self.min_entry_price = 0.20           # Don't enter if either side < this (certain loser)
        self.single_entry_price = 0.50        # Enter one side if this cheap
        self.hedge_target_pair = 0.98         # Target pair cost when completing hedge
        self.min_discount_to_avg_down = 0.05  # 5% below avg to average down
        self.aggressive_discount = 0.15       # 15%+ discount = bigger position
        self.extreme_discount = 0.30          # 30%+ discount = maximum position
        self.price_history_up: deque = deque(maxlen=60)
        self.price_history_down: deque = deque(maxlen=60)
        self.combined_history: deque = deque(maxlen=60)
        
        # Momentum / directional tilt parameters
        self.momentum_trade_usd = 6.0          # Trend follow size (protected by locked profit guard)
        self.momentum_min_samples = 5          # Need 5+ price samples before detecting trend
        self.momentum_threshold = 0.03         # Side must be >3 cents above 0.50 to be "trending"
        self.momentum_trend_strength = 0.015   # Price must have risen 1.5+ cents over window
        self.max_tilt_ratio = 2.50             # Allow tilt before rebalancing
        self.momentum_min_time = 120.0         # Need >2 min left to take momentum bet
        self.momentum_max_price = 0.92         # Don't buy momentum side above $0.92
        
        # Budget management
        self.max_market_spend_pct = 1.0   # Can use full budget in a market
        self.reserve_budget_pct = 0.05    # Keep 5% reserve ($20) as safety buffer
        self.emergency_mode_threshold = 0.10
        self.max_position_per_market = 9999.0  # No hard cap per market
        self.min_trade_interval = 5.0  # 5 seconds cooldown PER SIDE (faster trend reaction)
        
        # Time-based parameters
        self.min_time_to_enter = 60.0  # Don't enter if < 1 minute left (unless fixing negative profit)
        self.time_scale_threshold = 240.0  # Start reducing size when < 4 min left
        self.enable_time_scaling = True  # Scale position size based on time remaining
        
        # Profit-securing parameters
        self.min_profit_target = 99.00  # Effectively disabled — don't stop on locked profit
        self.excellent_pair_threshold = 0.900  # Lower threshold for excellent
        self.good_pair_threshold = 0.940  # Lower threshold for good
        self.size_multiplier_excellent = 4.0  # 4x size for excellent opportunities (pair < 0.90)
        self.size_multiplier_good = 2.5  # 2.5x size for good opportunities (pair < 0.94)
        self.max_pair_deterioration = 0.050  # More tolerant
        self.enable_profit_scaling = True  # Scale position size based on opportunity quality
        self.balance_first_mode = False  # Focus on low pair cost first
        
        # Defensive hedge parameters (NOT arb lock — just reversal insurance)
        self.defensive_hedge_ratio = 0.25    # Keep ~25% of main position as hedge
        self.max_defensive_hedge_ratio = 0.35 # Never exceed 35% hedge
        self.defensive_hedge_usd = 4.0       # Pair completion hedge trades
        self.defensive_max_price = 0.55      # Only hedge when other side is cheap
        
        # Awareness Mode parameters (150-60s: detect reversals and catch up)
        self.awareness_time_start = 150.0    # Enter awareness mode at 2:30 left
        self.awareness_time_end = 60.0       # Exit awareness mode at 1:00 left
        self.awareness_max_price = 0.90      # Don't chase above $0.90 in awareness mode

        # Flip parameters (market shift when losing side crosses this)
        self.flip_trigger_price = 0.53       # Losing side >= this means trend has flipped (faster detection)
        self.flip_target_profit = 3.0        # Buy enough for $3 profit on flip side (capped by locked buffer)
        
        # Locked profit protection — the core 100% win rate guarantee
        self.min_locked_buffer = 0.50        # NEVER let locked profit drop below this when buying strong side
        
        # Tracking for profit security
        self.best_pair_cost_seen = float('inf')  # Track best pair cost achieved
        self.highest_locked_profit = -float('inf')  # Track peak locked profit
        self.market_spent = 0.0  # Track total spent in current market
        self.emergency_mode = False  # Emergency mode when budget critical
        self._last_trade_time_up = 0.0    # Per-side cooldown: last UP trade time
        self._last_trade_time_down = 0.0  # Per-side cooldown: last DOWN trade time
        self._prev_trend_token = None     # Track previous trend for logging

        # Spot-based trend predictor (BTC spot price from Binance)
        self.trend_predictor = TrendPredictor()
        self._spot_prediction: Optional[str] = None
        self._spot_confidence: float = 0.0
        self._spot_reason: str = ''
        self._endgame_total_spent: float = 0.0
        self._endgame_max_total: float = 30.0  # Max total endgame spend per market

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
    
    def _dynamic_safety_margin(self, current_ratio: float) -> float:
        """Calculate dynamic safety margin - prioritize balance over pair cost."""
        locked = self.calculate_locked_profit()
        base_margin = self.pair_cost_safety_margin
        
        # For severe imbalances, allow much higher pair cost to achieve balance
        imbalance_severity = abs(current_ratio - 1.0)
        if imbalance_severity > 0.3:  # Significantly imbalanced
            # Allow more room based on severity
            imbalance_bonus = min(0.040, imbalance_severity * 0.05)  # Up to +4¢
            base_margin += imbalance_bonus
        
        # If profit is locked and positive, allow higher margin
        if locked >= 0:
            profit_bonus = min(0.020, locked * 0.003)  # Up to +2¢ for locked profit
            base_margin += profit_bonus
        
        # Never exceed absolute maximum
        return min(base_margin, self.pair_cost_max_limit)

    def _get_opportunity_size_multiplier(self, pair_cost: float) -> float:
        """Calculate position size multiplier based on opportunity quality."""
        if not self.enable_profit_scaling:
            return 1.0
        
        if pair_cost < self.excellent_pair_threshold:
            return self.size_multiplier_excellent
        elif pair_cost < self.good_pair_threshold:
            return self.size_multiplier_good
        else:
            return 1.0
    
    def _check_deterioration_stop(self, current_pair: float) -> Tuple[bool, str]:
        """Check if position has deteriorated and should be exited early."""
        # Track best pair cost
        if current_pair < self.best_pair_cost_seen:
            self.best_pair_cost_seen = current_pair
        
        # If pair has worsened significantly from best, consider stop
        deterioration = current_pair - self.best_pair_cost_seen
        if deterioration > self.max_pair_deterioration:
            return True, f'Pair deteriorated ${deterioration:.3f} from best ${self.best_pair_cost_seen:.3f}'
        
        return False, ''
    
    def _check_profit_target_reached(self, locked_profit: float, ratio: float) -> Tuple[bool, str]:
        """Check if we should stop trading because profit target is reached."""
        # Track highest locked profit
        if locked_profit > self.highest_locked_profit:
            self.highest_locked_profit = locked_profit
        
        # CRITICAL: Never stop if locked profit is negative!
        if locked_profit < 0:
            return False, ''
        
        # Only stop if:
        # 1. Locked profit >= minimum target
        # 2. Position is reasonably balanced
        if locked_profit >= self.min_profit_target:
            if self.balanced_ratio_range[0] <= ratio <= self.balanced_ratio_range[1]:
                return True, f'💰 Profit target reached: ${locked_profit:.2f} >= ${self.min_profit_target:.2f}'
        
        return False, ''
    
    def _get_time_scale_factor(self, time_to_close: Optional[float]) -> float:
        """Calculate position size scaling based on time remaining."""
        if not self.enable_time_scaling or time_to_close is None:
            return 1.0
        
        # Don't scale if plenty of time
        if time_to_close >= self.time_scale_threshold:
            return 1.0
        
        # Linear scale down from 1.0 to 0.3 as time decreases
        if time_to_close < 60:  # Less than 1 min
            return 0.2
        elif time_to_close < 120:  # Less than 2 min
            return 0.4
        elif time_to_close < 180:  # Less than 3 min
            return 0.6
        else:  # 3-4 minutes
            return 0.8
    
    def _check_budget_limits(self, proposed_spend: float) -> Tuple[bool, float, str]:
        """Check if proposed spend is within budget limits."""
        # Check emergency mode
        budget_remaining = self.remaining_budget()
        budget_remaining_pct = budget_remaining / self.market_budget
        
        if budget_remaining_pct < self.emergency_mode_threshold:
            if not self.emergency_mode:
                self.emergency_mode = True
            # In emergency, only allow tiny trades
            max_spend = min(proposed_spend, budget_remaining * 0.1)
            return True, max_spend, f'EMERGENCY MODE: {budget_remaining_pct*100:.0f}% budget left'
        
        # Check per-market spending limit
        max_market_spend = self.market_budget * self.max_market_spend_pct
        if self.market_spent >= max_market_spend:
            return False, 0, f'Market limit reached: ${self.market_spent:.0f}/${max_market_spend:.0f}'
        
        # Check reserve budget
        min_reserve = self.market_budget * self.reserve_budget_pct
        available = max(0, budget_remaining - min_reserve)
        
        if available < proposed_spend:
            if available < self.min_trade_size:
                return False, 0, f'Reserve protected: need ${min_reserve:.0f} reserve'
            return True, available, f'Reserve limited to ${available:.2f}'
        
        # Check against market limit
        remaining_market_budget = max_market_spend - self.market_spent
        capped_spend = min(proposed_spend, remaining_market_budget)
        
        return True, capped_spend, ''
    
    def reset_market_tracking(self):
        """Reset per-market tracking variables."""
        self.market_spent = 0.0
        self.emergency_mode = False
        self.best_pair_cost_seen = float('inf')
        self._last_trade_time_up = 0.0
        self._last_trade_time_down = 0.0
        self._prev_trend_token = None
        self.price_history_up.clear()
        self.price_history_down.clear()
        self.combined_history.clear()
    def _should_take_profit_now(self, locked_profit: float, ratio: float, current_pair: float) -> Tuple[bool, str]:
        """Determine if we should take profit and stop trading now."""
        # NEVER stop if locked profit is negative
        if locked_profit < 0:
            return False, ''
        
        # Check profit target
        target_reached, reason = self._check_profit_target_reached(locked_profit, ratio)
        if target_reached:
            return True, reason
        
        # Check deterioration (only if we have profit to protect)
        if locked_profit > 0.50:  # Only protect if we have meaningful profit
            should_stop, reason = self._check_deterioration_stop(current_pair)
            if should_stop:
                return True, f'⚠️ Stop: {reason}'
        
        return False, ''

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def update_spot_price(self, btc_price: float, timestamp: Optional[float] = None):
        """Update the strategy with the latest BTC spot price from Binance."""
        self.trend_predictor.update_spot_price(btc_price, timestamp)
        # Update prediction
        self._spot_prediction, self._spot_confidence, self._spot_reason = (
            self.trend_predictor.predict()
        )

    def set_market_open_spot(self, btc_price: float):
        """Set the BTC spot price at market open (reference price)."""
        self.trend_predictor.set_market_open_price(btc_price)

    def reset_predictor_for_new_market(self):
        """Reset predictor state for a new market window."""
        self.trend_predictor.reset_for_new_market()
        self._spot_prediction = None
        self._spot_confidence = 0.0
        self._spot_reason = ''
        self._endgame_total_spent = 0.0

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

        if any(
            plan is not None
            for sides in self.quote_targets.values()
            for plan in sides.values()
        ):
            self._cancel_all_quotes('pair_cost_mode')

        trades.extend(
            self._pair_cost_trade(metrics_map, up_orderbook, down_orderbook, timestamp, time_to_close)
        )

        self._record_histories(up_metrics, down_metrics)
        return trades

    def _pair_cost_trade(
        self,
        metrics_map: Dict[str, BookMetrics],
        up_orderbook: Optional[dict],
        down_orderbook: Optional[dict],
        timestamp: str,
        time_to_close: Optional[float] = None,
    ) -> List[Tuple[str, str, float, float]]:
        """
        Directional Trend Strategy with Defensive Hedge
        
        Core idea: Follow directional trends for maximum profit. Maintain a small
        defensive hedge (~25-30% of main position) on the opposite side so we can
        pivot quickly if the market reverses — NOT to lock arb profit.
        
        Phases:
          1. ENTRY     - Buy the cheap side first (base position / reversal insurance).
          2. DEVELOP   - Follow directional trend (primary). Add small defensive
                         hedge on opposite side (~25%) for reversal protection.
          3. MANAGE    - Both sides owned. Continuously:
                         a) Follow trend — buy more of trending side (main driver)
                         b) Maintain defensive hedge — keep ~25-30% on opposite side
                         c) On reversal — pivot: existing hedge becomes new base
          4. PROTECT   - 120-60s left: ensure defensive hedge exists, don't lock profit.
          5. ENDGAME   - <60s: stop if profitable. Only deeply discounted buys allowed.
        """
        import time as _time
        trades: List[Tuple[str, str, float, float]] = []

        # Fee-adjusted pair cost limit: pair_cost tracks raw price,
        # but actual cost = price * (1 + FEE_RATE). For profitable arbitrage,
        # pair_cost must be < 1.0 / (1+FEE_RATE) ≈ 0.985
        # We use 0.97 to leave a healthy margin for profit.
        MAX_PAIR_FOR_PROFIT = 0.985  # Pair must be below this for guaranteed profit after fees
        MAX_PAIR_FOR_HEDGE = 1.03    # Pair must be below this for risk reduction (real markets ~1.01-1.03)
        MAX_PAIR_FOR_BALANCE = 1.01  # When balancing existing position, don't push pair above this

        # ── TIME-DECAY MAX PRICE ──
        # As market close approaches, lower the max price we'll pay.
        # This prevents buying expensive shares that can reverse hard.
        effective_max_price = self.momentum_max_price  # 0.85 default
        late_game_scale = 1.0  # Trade size multiplier (shrinks near close)
        if time_to_close is not None:
            if time_to_close < 90:
                # 90s→60s: max price drops 0.92→0.75, size drops to 50%
                t_factor = max(0, (time_to_close - 60) / 30)  # 1.0→0.0
                effective_max_price = 0.75 + (self.momentum_max_price - 0.75) * t_factor
                late_game_scale = 0.5 + 0.5 * t_factor
            elif time_to_close < 120:
                # 120s→90s: max price drops 0.92→0.85, size drops to 80%
                t_factor = max(0, (time_to_close - 90) / 30)  # 1.0→0.0
                effective_max_price = 0.85 + (self.momentum_max_price - 0.85) * t_factor
                late_game_scale = 0.8 + 0.2 * t_factor

        up_price = metrics_map['UP'].best_ask
        down_price = metrics_map['DOWN'].best_ask
        if up_price <= 0 or down_price <= 0:
            self.current_mode = 'waiting'
            self.mode_reason = 'Missing best asks'
            return trades

        # Per-side trade cooldown: each side (UP/DOWN) has independent cooldown
        # Normal: 12s per side. Profit seed bypasses cooldown directly.
        now = _time.time()
        up_cd = self.min_trade_interval
        down_cd = self.min_trade_interval
        up_on_cooldown = self._last_trade_time_up > 0 and (now - self._last_trade_time_up) < up_cd
        down_on_cooldown = self._last_trade_time_down > 0 and (now - self._last_trade_time_down) < down_cd
        if up_on_cooldown and down_on_cooldown:
            # Both sides on cooldown — still collect price data
            combined = up_price + down_price
            self.price_history_up.append(up_price)
            self.price_history_down.append(down_price)
            self.combined_history.append(combined)
            return trades

        # Track price history for trend analysis
        combined = up_price + down_price
        self.price_history_up.append(up_price)
        self.price_history_down.append(down_price)
        self.combined_history.append(combined)

        remaining_budget = self.remaining_budget()
        if remaining_budget < self.min_trade_size:
            self.current_mode = 'standby'
            self.mode_reason = 'No budget left'
            return trades

        locked_profit = self.calculate_locked_profit()
        current_pair = self.pair_cost

        # ── Helper functions (defined before endgame so they're available) ──
        def cap_spend(spend: float) -> float:
            # Keep a small safety reserve
            min_reserve = self.market_budget * self.reserve_budget_pct
            available_cash = max(0, self.cash - min_reserve)
            final = min(spend, remaining_budget, available_cash)
            if final < 1.0:  # Polymarket minimum
                return 0
            return final

        def buy_with_spend(token: str, price: float, spend: float, reason: str) -> Optional[Tuple[str, str, float, float]]:
            # Per-side cooldown check
            if token == 'UP' and up_on_cooldown:
                return None
            if token == 'DOWN' and down_on_cooldown:
                return None
            
            # ── SPOT GUARD: Block wrong-side buys when spot is confident ──
            # BTC spot price is the settlement source — if spot says DOWN at 70%+,
            # don't accumulate more UP shares (except emergency fix and endgame).
            if (self._spot_prediction is not None 
                and self._spot_confidence >= 0.70
                and token != self._spot_prediction
                and reason not in ('emergency_fix', 'endgame_spot')):
                return None
            
            # ── DIRECTIONAL EXPOSURE CAP ──
            # Prevent extreme one-sided exposure that can't be recovered on reversal.
            # Max profit on any side should not exceed $15 (prevents $50+ runaway positions).
            max_directional_profit = 15.0
            if self.qty_up > 0 or self.qty_down > 0:
                pnl_if_this_wins = (self.calculate_pnl_if_up_wins() if token == 'UP'
                                   else self.calculate_pnl_if_down_wins())
                if pnl_if_this_wins > max_directional_profit and reason not in ('emergency_fix', 'endgame_spot'):
                    return None  # Already heavily positioned this side
            
            # ── LOCKED PROFIT PROTECTION ──
            # In real markets combined > 1.0, so locked is usually slightly negative
            # after pair entry (~-$0.50). This is normal and recovered through trend.
            # Guard levels:
            #  locked >= 0: profitable — cap buys to protect profit
            #  locked > -$2: mildly underwater — allow trend following, cap to prevent worsening
            #  locked < -$2: severely underwater — emergency, only weak-side buys
            if self.qty_up > 0 and self.qty_down > 0:
                pnl_up_now = self.calculate_pnl_if_up_wins()
                pnl_down_now = self.calculate_pnl_if_down_wins()
                locked_now = min(pnl_up_now, pnl_down_now)
                
                if locked_now >= 0:
                    # Position is profitable — protect it universally
                    other_pnl = pnl_down_now if token == 'UP' else pnl_up_now
                    max_spend_safe = max(0, (other_pnl - self.min_locked_buffer) / FEE_MULT)
                    if max_spend_safe < 1.0:
                        return None  # Would breach locked profit protection
                    spend = min(spend, max_spend_safe)
                elif locked_now > -2.00:
                    # Mildly underwater (normal market spread) — allow trading
                    # but cap spend so locked doesn't fall below -$2
                    other_pnl = pnl_down_now if token == 'UP' else pnl_up_now
                    max_spend_safe = max(0, (other_pnl + 2.00) / FEE_MULT)
                    if max_spend_safe < 1.0:
                        return None
                    spend = min(spend, max_spend_safe)
                else:
                    # Severely underwater — only allow WEAK SIDE buys
                    pnl_this = pnl_up_now if token == 'UP' else pnl_down_now
                    pnl_other = pnl_down_now if token == 'UP' else pnl_up_now
                    is_weak_side = pnl_this <= pnl_other
                    
                    if not is_weak_side:
                        return None  # Block strong-side buys when severely underwater
                    if price * FEE_MULT > 0.985:
                        return None  # Too expensive to improve position
            
            spend = cap_spend(spend)
            if spend <= 0 or price <= 0:
                return None
            qty = min(spend / price, self._max_affordable_qty(price))
            if qty < self.min_trade_size:
                return None
            orderbook = up_orderbook if token == 'UP' else down_orderbook
            return self._execute_buy(token, price, qty, orderbook, timestamp, reason)

        def pair_cost_after_buy(token: str, price: float, qty: float) -> float:
            if qty <= 0:
                return self.pair_cost
            if token == 'UP':
                new_cost_up = self.cost_up + price * qty
                new_qty_up = self.qty_up + qty
                new_avg_up = new_cost_up / new_qty_up if new_qty_up > 0 else 0.0
                if self.qty_down <= 0:
                    return float('inf')
                return new_avg_up + self.avg_down
            new_cost_down = self.cost_down + price * qty
            new_qty_down = self.qty_down + qty
            new_avg_down = new_cost_down / new_qty_down if new_qty_down > 0 else 0.0
            if self.qty_up <= 0:
                return float('inf')
            return self.avg_up + new_avg_down

        def discount_to_avg(token: str, price: float) -> float:
            """How much cheaper is current price vs our average? (0.20 = 20% discount)"""
            avg = self.avg_up if token == 'UP' else self.avg_down
            if avg <= 0:
                return 0
            return max(0, (avg - price) / avg)

        def size_for_discount(discount: float) -> float:
            """Scale position size based on discount quality (conservative)."""
            if discount >= self.extreme_discount:   # 30%+
                return 2.0
            elif discount >= self.aggressive_discount:  # 15%+
                return 1.5
            elif discount >= self.min_discount_to_avg_down:  # 5%+
                return 1.2
            else:
                return 1.0

        # ── ENDGAME: <60s left — minimize risk, stop most activity ──
        has_position = self.qty_up > 0 or self.qty_down > 0
        if time_to_close is not None and time_to_close < 60 and has_position:
            if locked_profit >= 0:
                self.current_mode = 'profit_secured'
                self.mode_reason = f'⏰ Endgame: profit secured ${locked_profit:.2f} | {time_to_close:.0f}s left'
                return trades
            
            # NO forced hedge — buying at any price during late volatility causes big losses.
            # Only allow deeply discounted buys that genuinely improve our position.
            has_one_side_only = (self.qty_up > 0) != (self.qty_down > 0)
            if has_one_side_only:
                owned_token = 'UP' if self.qty_up > 0 else 'DOWN'
                other_token = 'DOWN' if owned_token == 'UP' else 'UP'
                other_price = down_price if other_token == 'DOWN' else up_price
                owned_avg = self.avg_up if owned_token == 'UP' else self.avg_down
                potential_pair = owned_avg + other_price
                
                # Only hedge if it's genuinely cheap (pair < 1.00 = breakeven or better)
                if potential_pair < MAX_PAIR_FOR_HEDGE:
                    owned_cost = self.cost_up if owned_token == 'UP' else self.cost_down
                    spend = min(owned_cost, 3.0)  # Cap at $3 in endgame
                    trade = buy_with_spend(other_token, other_price, spend, 'endgame_hedge')
                    if trade:
                        trades.append(trade)
                        self.current_mode = 'endgame_hedge'
                        self.mode_reason = f'🛡️ Endgame hedge {other_token} @ ${other_price:.3f} | pair ${potential_pair:.3f} | {time_to_close:.0f}s left'
                    return trades
                
                self.current_mode = 'endgame_hold'
                self.mode_reason = f'⏰ Holding {owned_token} | hedge too expensive (pair ${potential_pair:.3f}) | {time_to_close:.0f}s left'
                return trades
            
            # Both sides owned in endgame
            if current_pair <= 1.00:
                # Breakeven or profitable — hold
                self.current_mode = 'endgame_hold'
                self.mode_reason = f'⏰ Holding pair ${current_pair:.3f} | locked ${locked_profit:+.2f} | {time_to_close:.0f}s left'
                return trades
            
            # Losing pair — only allow arb improve at deep discount in last minute
            # Fall through but effective_max_price is already very low (0.55 or less)
            self.current_mode = 'endgame_risk'
            self.mode_reason = f'⏰ Endgame risk: pair ${current_pair:.3f} | {time_to_close:.0f}s left'
            # Fall through to Phase 3 arb improve only (trend follow blocked by time gate)

        # ── Additional helper functions ──

        def is_price_at_local_low(token: str) -> bool:
            """Check if current price is near recent low (good entry timing)."""
            history = self.price_history_up if token == 'UP' else self.price_history_down
            if len(history) < 5:
                return True  # Not enough data, assume OK
            current = history[-1]
            recent_min = min(list(history)[-10:]) if len(history) >= 10 else min(history)
            recent_max = max(list(history)[-10:]) if len(history) >= 10 else max(history)
            price_range = recent_max - recent_min
            if price_range < 0.01:
                return True  # No volatility, OK to trade
            # Price is "at low" if within 30% of range from bottom
            return (current - recent_min) < price_range * 0.3

        def orderbook_liquidity(token: str) -> float:
            """Check available liquidity at best ask."""
            ob = up_orderbook if token == 'UP' else down_orderbook
            if not ob or not ob.get('asks'):
                return 0
            asks = ob['asks']
            total = 0
            for ask in asks[:3]:  # Top 3 levels
                try:
                    total += float(ask.get('size', ask.get('s', 0)))
                except (ValueError, TypeError):
                    pass
            return total

        def detect_momentum() -> tuple:
            """
            Detect which side has momentum (trending toward winning).
            Returns: (trending_token, strength, confidence)
              - trending_token: 'UP' or 'DOWN' or None
              - strength: float 0-1 (how strong the trend is)
              - confidence: float 0-1 (how reliable the signal is)
            """
            if len(self.price_history_up) < self.momentum_min_samples:
                return None, 0, 0
            
            # Current prices as probability signal
            # UP at $0.60 = 60% chance UP wins
            up_prob = up_price
            down_prob = down_price
            
            # Check if one side is clearly favored (>56%)
            if up_prob <= (0.50 + self.momentum_threshold) and down_prob <= (0.50 + self.momentum_threshold):
                return None, 0, 0  # Market is ~50/50, no clear momentum
            
            # Determine favored side
            if up_prob > down_prob:
                favored = 'UP'
                favored_prob = up_prob
                history = list(self.price_history_up)
            else:
                favored = 'DOWN'
                favored_prob = down_prob
                history = list(self.price_history_down)
            
            # Check trend: is price rising over recent samples?
            recent = history[-min(len(history), 10):]
            if len(recent) < 3:
                return None, 0, 0
            
            early_avg = sum(recent[:len(recent)//2]) / (len(recent)//2)
            late_avg = sum(recent[len(recent)//2:]) / len(recent[len(recent)//2:])
            trend = late_avg - early_avg  # positive = price rising = momentum
            
            # Two ways to detect momentum:
            # 1. RISING: price is actively going up (trend >= threshold)
            # 2. SUSTAINED: price has been consistently high for 70%+ of window
            is_rising = trend >= self.momentum_trend_strength
            above_count = sum(1 for p in recent if p > (0.50 + self.momentum_threshold))
            is_sustained = above_count >= len(recent) * 0.7 and favored_prob > (0.50 + self.momentum_threshold)
            
            if not is_rising and not is_sustained:
                return None, 0, 0  # Neither rising nor sustained
            
            # Strength: how far above 0.50 (capped at 1.0)
            strength = min(1.0, (favored_prob - 0.50) / 0.30)  # 0.50=0, 0.80=1.0
            
            # Confidence: based on consistency of trend
            # Count how many of the last 5 samples showed this side leading
            last_5_up = list(self.price_history_up)[-5:]
            last_5_down = list(self.price_history_down)[-5:]
            leading_count = sum(1 for u, d in zip(last_5_up, last_5_down) 
                              if (u > d) == (favored == 'UP'))
            confidence = leading_count / max(len(last_5_up), 1)
            
            return favored, strength, confidence

        # ══════════════════════════════════════════════════════════
        #  PHASE 1: ENTRY - Buy the CHEAPER side first
        #  Enter when: combined ask < threshold AND enough time left.
        #  Buy the cheaper side to get best cost basis, then Phase 2
        #  will complete the pair on the next tick.
        # ══════════════════════════════════════════════════════════
        if self.qty_up == 0 and self.qty_down == 0:
            # Don't start new positions with < 2 min left
            if time_to_close is not None and time_to_close < 120:
                self.current_mode = 'too_late'
                self.mode_reason = f'⏰ No position, <2min left ({time_to_close:.0f}s) - skipping'
                return trades

            combined_ask_entry = up_price + down_price
            entry_spread = abs(up_price - down_price)
            cheap_token = 'UP' if up_price <= down_price else 'DOWN'
            cheap_price = min(up_price, down_price)

            # SPREAD GUARD: Don't enter decided markets.
            # If spread > 0.40 (e.g., UP=$0.72 DOWN=$0.30), the market is
            # already heavily tilted — buying the cheap side is buying the loser.
            if entry_spread > self.max_entry_spread:
                self.current_mode = 'scouting'
                self.mode_reason = f'🔍 Spread ${entry_spread:.3f} > ${self.max_entry_spread:.3f} — market too decided | UP ${up_price:.3f} DOWN ${down_price:.3f}'
                return trades
            
            # PRICE FLOOR GUARD: Don't enter if either side is near-zero
            if cheap_price < self.min_entry_price:
                self.current_mode = 'scouting'
                self.mode_reason = f'🔍 Cheap side ${cheap_price:.3f} < ${self.min_entry_price:.3f} — side near-zero | UP ${up_price:.3f} DOWN ${down_price:.3f}'
                return trades

            if combined_ask_entry <= self.combined_entry_threshold:
                spend = self.entry_trade_usd
                # Bigger entry for better arb opportunities
                if combined_ask_entry < 0.98:
                    spend = self.entry_trade_usd * 2.0
                trade = buy_with_spend(cheap_token, cheap_price, spend, 'base_entry')
                if trade:
                    trades.append(trade)
                    self.current_mode = 'entry'
                    self.mode_reason = f'🎯 Entry {cheap_token} @ ${cheap_price:.3f} | combined ${combined_ask_entry:.3f} | spread ${entry_spread:.3f}'
                return trades

            self.current_mode = 'scouting'
            self.mode_reason = f'🔍 Combined ${combined_ask_entry:.3f} > ${self.combined_entry_threshold:.3f} | UP ${up_price:.3f} DOWN ${down_price:.3f}'
            return trades

        # ══════════════════════════════════════════════════════════
        #  PHASE 2: COMPLETE PAIR - One side owned.
        #  PRIORITY #1: Buy the other side to form a pair.
        #  A complete pair reduces risk — even if pair cost > 1.0, trend
        #  following in Phase 3 can recover the difference.
        # ══════════════════════════════════════════════════════════
        if self.qty_up == 0 or self.qty_down == 0:
            owned_token = 'UP' if self.qty_up > 0 else 'DOWN'
            other_token = 'DOWN' if owned_token == 'UP' else 'UP'
            owned_qty = self.qty_up if owned_token == 'UP' else self.qty_down
            other_price = down_price if other_token == 'DOWN' else up_price
            owned_price = up_price if owned_token == 'UP' else down_price
            owned_avg = self.avg_up if owned_token == 'UP' else self.avg_down
            potential_pair = owned_avg + other_price

            # ── A) COMPLETE THE PAIR (PRIORITY #1) ──
            # Always pair-complete when one-sided. Holding one side with no hedge
            # is the MAXIMUM risk scenario. Even an expensive pair (cost > 1.03)
            # is safer than a naked one-sided position that can lose $5+.
            # Only skip if pair would be absurdly expensive (> 1.10).
            if potential_pair < 1.10:
                # Scale spend by pair quality
                if potential_pair < 0.985:  # True arb
                    spend = self.balance_trade_usd * 2.0
                elif potential_pair < 1.00:  # Near breakeven
                    spend = self.balance_trade_usd
                else:  # Slightly above breakeven — small hedge
                    spend = self.balance_trade_usd * 0.5
                
                # Cap to balanced amount
                balanced_spend = owned_qty * other_price * FEE_MULT
                spend = min(spend, balanced_spend * 1.1 + 1.0)
                
                trade = buy_with_spend(other_token, other_price, spend, 'pair_complete')
                if trade:
                    trades.append(trade)
                    new_pair = self.pair_cost
                    self.current_mode = 'pair_complete'
                    self.mode_reason = f'🔗 Completing pair: {other_token} @ ${other_price:.3f} | pair ${new_pair:.3f}'
                return trades

            # ── B) PAIR TOO EXPENSIVE — build owned side if trending ──
            trending_token, trend_strength, trend_confidence = detect_momentum()
            if (trending_token == owned_token and trend_confidence >= 0.6
                and owned_price <= effective_max_price
                and time_to_close is not None and time_to_close > 120):
                spend = self.entry_trade_usd * (0.5 + 0.5 * trend_strength)
                trade = buy_with_spend(owned_token, owned_price, spend, 'trend_buildup_solo')
                if trade:
                    trades.append(trade)
                    self.current_mode = 'trend_buildup'
                    self.mode_reason = f'📈 Building {owned_token} @ ${owned_price:.3f} (pair too expensive: ${potential_pair:.3f})'
                return trades

            self.current_mode = 'waiting_pair'
            self.mode_reason = f'⏳ Waiting: {other_token} @ ${other_price:.3f} too expensive (pair ${potential_pair:.3f})'
            return trades

        # ══════════════════════════════════════════════════════════
        #  PHASE 3: MANAGE - Both sides owned
        #  Priority order:
        #   1) EMERGENCY FIX:   locked_profit < 0 → buy weak side urgently
        #   2) ARB ACCUMULATE:  combined ask < threshold → free money
        #   3) PROFIT SEED:     ensure winning side has min profit (capped)
        #   4) TREND FOLLOW:    follow winning side (auto-capped by buy_with_spend)
        #   5) ARB IMPROVE:     buy at discount to lower pair cost
        #  All buys protected by locked_profit guard in buy_with_spend.
        # ══════════════════════════════════════════════════════════
        ratio = (self.qty_up / self.qty_down) if self.qty_down > 0 else 999.0
        pnl_up = self.calculate_pnl_if_up_wins()
        pnl_down = self.calculate_pnl_if_down_wins()
        combined_ask = up_price + down_price

        trending_token, trend_strength, trend_confidence = detect_momentum()

        # SPOT OVERRIDE: If spot predictor has high confidence, ALWAYS override.
        # BTC spot price is the ground truth — market prices lag and can mislead.
        # Only override if spot disagrees with market momentum OR market has no signal.
        if self._spot_prediction is not None and self._spot_confidence >= 0.60:
            # If spot and market agree, boost confidence
            if trending_token == self._spot_prediction:
                trend_strength = max(trend_strength if trend_strength else 0, self._spot_confidence - 0.50)
                trend_confidence = max(trend_confidence if trend_confidence else 0, self._spot_confidence)
            else:
                # Spot DISAGREES with market — trust spot (it's the settlement source)
                trending_token = self._spot_prediction
                trend_strength = self._spot_confidence - 0.50
                trend_confidence = self._spot_confidence

        # Track trend direction for logging
        if trending_token and trend_confidence >= 0.6:
            self._prev_trend_token = trending_token

        # ── PRIORITY 1: EMERGENCY FIX — locked profit SEVERELY negative ──
        # Only trigger for significant imbalances (> $2 deficit), NOT for normal
        # pair cost overhead from market spread (~$0.50 at combined 1.02).
        # Small negative locked is expected in real markets and is recovered
        # through trend following in Priority 3/4.
        # NEVER emergency fix in last 30 seconds — prices go extreme, buys are wasteful.
        emergency_time_ok = time_to_close is None or time_to_close > 30
        if locked_profit < -2.00 and emergency_time_ok:
            weak_token = 'UP' if pnl_up < pnl_down else 'DOWN'
            strong_pnl = max(pnl_up, pnl_down)
            weak_pnl = min(pnl_up, pnl_down)
            weak_price = up_price if weak_token == 'UP' else down_price
            pnl_gap = strong_pnl - weak_pnl

            # If combined > 1.04, buying weak side at these prices wastes cash.
            # Hold position and accept the gap.
            if combined_ask > 1.04:
                self.current_mode = 'emergency_hold'
                self.mode_reason = (f'🚨 Locked ${locked_profit:+.2f} | combined ${combined_ask:.3f} > 1.005 '
                                   f'— no arb, holding to preserve cash')
                return trades

            per_share_gain = 1.0 - weak_price * FEE_MULT  # PnL improvement per share
            if per_share_gain > 0.01:  # Only if price allows profit (< ~$0.97)
                # Dead zone: if gap is tiny (< $0.50), don't bother equalizing
                if pnl_gap < 0.50:
                    self.current_mode = 'emergency_hold'
                    self.mode_reason = (f'🚨 Locked ${locked_profit:+.2f} | gap ${pnl_gap:.2f} '
                                       f'too small to fix efficiently')
                    return trades

                # Exact equalization: buy pnl_gap shares of weak side.
                # buy_with_spend gets shares = spend / (price * FEE_MULT),
                # so to get X shares, spend = X * price * FEE_MULT.
                equalize_shares = pnl_gap
                equalize_spend = equalize_shares * weak_price * FEE_MULT
                
                # Use exact equalize amount — no min, no overshoot.
                # Cap at 15% of remaining budget per fix to limit damage.
                spend = min(equalize_spend, remaining_budget * 0.15)
                if spend < 0.50:
                    self.current_mode = 'emergency_hold'
                    self.mode_reason = f'🚨 Locked ${locked_profit:+.2f} | insufficient budget for fix'
                    return trades
                
                # Bypass cooldown for emergency fixes
                if weak_token == 'UP':
                    self._last_trade_time_up = 0.0
                    up_on_cooldown = False
                else:
                    self._last_trade_time_down = 0.0
                    down_on_cooldown = False
                trade = buy_with_spend(weak_token, weak_price, spend, 'emergency_fix')
                if trade:
                    trades.append(trade)
                    new_locked = self.calculate_locked_profit()
                    self.current_mode = 'emergency_fix'
                    self.mode_reason = (f'🚨 Fix: buy {weak_token} @ ${weak_price:.3f} | '
                                      f'locked ${locked_profit:+.2f}→${new_locked:+.2f}')
                return trades

            self.current_mode = 'emergency_hold'
            self.mode_reason = f'🚨 Locked ${locked_profit:+.2f} | weak side ${weak_token} @ ${weak_price:.3f} too expensive to fix'
            return trades

        # ── PRIORITY 2: ARB ACCUMULATE — combined ask < 0.985 (true arb) ──
        # Buy BALANCED PAIRS: equal shares of both UP and DOWN simultaneously.
        # This ALWAYS increases locked_profit since combined < 1/FEE_MULT means
        # each pair costs less than $1 payout after fees.
        # Only triggers when true arb exists (combined < 0.985), NOT at normal spreads.
        if combined_ask < MAX_PAIR_FOR_PROFIT:
            arb_margin = 1.0 / FEE_MULT - combined_ask
            if arb_margin > 0:
                # Budget for each side
                per_side_budget = self.balance_trade_usd * (1.0 + min(arb_margin * 15, 1.0))
                # Reserve 15% of market budget for trend following after arb building
                trend_reserve = self.market_budget * 0.15
                available = max(0, self.cash - trend_reserve)
                per_side_budget = min(per_side_budget, available / (2.0 * FEE_MULT),
                                     remaining_budget / 2.0)
                
                if per_side_budget >= 1.0:
                    # Equal shares on both sides (balanced)
                    up_qty = per_side_budget / up_price
                    down_qty = per_side_budget / down_price
                    qty = min(up_qty, down_qty, self.max_shares_per_order)
                    
                    if qty >= self.min_trade_size:
                        # Execute both buys directly (safe: balanced pair always improves locked)
                        t1 = self._execute_buy('UP', up_price, qty, up_orderbook, timestamp, 'arb_pair')
                        t2 = self._execute_buy('DOWN', down_price, qty, down_orderbook, timestamp, 'arb_pair')
                        if t1:
                            trades.append(t1)
                        if t2:
                            trades.append(t2)
                        if t1 or t2:
                            new_locked = self.calculate_locked_profit()
                            self.current_mode = 'arb_accumulate'
                            self.mode_reason = (f'💰 Paired arb: {qty:.0f} shares each | '
                                              f'combined ${combined_ask:.3f} | margin ${arb_margin:.3f} | '
                                              f'locked ${locked_profit:+.2f}→${new_locked:+.2f}')
                        return trades

        # ── PRIORITY 3: PROFIT SEED — ensure winning side has min profit ──
        # Buy currently winning side to build profit potential.
        # CAPPED by locked profit guard in buy_with_spend — can never push locked < buffer.
        winning_token = 'UP' if up_price >= down_price else 'DOWN'
        winning_price = up_price if winning_token == 'UP' else down_price
        winning_qty = self.qty_up if winning_token == 'UP' else self.qty_down
        winning_cost = self.cost_up if winning_token == 'UP' else self.cost_down
        
        pnl_if_winning_wins = winning_qty - winning_cost
        
        needs_seed = (winning_price >= self.flip_trigger_price and
                      pnl_if_winning_wins < self.flip_target_profit and
                      winning_price < 0.88 and
                      time_to_close is not None and time_to_close > self.awareness_time_end)
        
        if needs_seed:
            additional_needed = self.flip_target_profit - pnl_if_winning_wins
            if additional_needed > 0.50:
                profit_per_share = 1.0 - winning_price
                if profit_per_share > 0.05:
                    shares_needed = additional_needed / profit_per_share
                    seed_spend = shares_needed * winning_price
                    seed_spend = max(2.0, min(seed_spend, 20.0))  # $20 cap (locked guard will cap further)
                    
                    # Reduced cooldown for seed buys
                    if winning_token == 'UP':
                        self._last_trade_time_up = 0.0
                        up_on_cooldown = False
                    else:
                        self._last_trade_time_down = 0.0
                        down_on_cooldown = False
                    
                    # buy_with_spend caps this to keep locked_profit >= min_locked_buffer
                    trade = buy_with_spend(winning_token, winning_price, seed_spend, 'profit_seed')
                    if trade:
                        trades.append(trade)
                        new_qty = self.qty_up if winning_token == 'UP' else self.qty_down
                        new_cost = self.cost_up if winning_token == 'UP' else self.cost_down
                        new_pnl = new_qty - new_cost
                        new_locked = self.calculate_locked_profit()
                        self.current_mode = 'profit_seed'
                        self.mode_reason = (f'🔄 SEED {winning_token} @ ${winning_price:.3f} | '
                                          f'pnl_if_win {pnl_if_winning_wins:+.1f}→{new_pnl:+.1f} | '
                                          f'locked ${new_locked:+.2f}')
                    return trades

        # ══════════════════════════════════════════════════════════
        #  AWARENESS MODE: 150s-60s left — ensure defensive position
        #  Buy weak side if severely underweight. Protected by buy_with_spend.
        # ══════════════════════════════════════════════════════════
        if time_to_close is not None and self.awareness_time_end <= time_to_close <= self.awareness_time_start:
            weak_token = 'DOWN' if self.qty_up > self.qty_down else 'UP'
            strong_token = 'UP' if weak_token == 'DOWN' else 'DOWN'
            weak_qty = self.qty_down if weak_token == 'DOWN' else self.qty_up
            strong_qty = self.qty_up if strong_token == 'UP' else self.qty_down
            weak_price = down_price if weak_token == 'DOWN' else up_price
            
            # Awareness profit seed: ensure weak side has min profit target
            weak_cost = self.cost_down if weak_token == 'DOWN' else self.cost_up
            weak_pnl_if_wins = weak_qty - weak_cost
            
            if (weak_price >= self.flip_trigger_price and
                weak_pnl_if_wins < self.flip_target_profit and
                weak_price <= self.awareness_max_price and weak_price < 0.90):
                
                additional_needed = self.flip_target_profit - weak_pnl_if_wins
                if additional_needed > 0.50:
                    profit_per_share = 1.0 - weak_price
                    if profit_per_share > 0.05:
                        shares_needed = additional_needed / profit_per_share
                        seed_spend = shares_needed * weak_price
                        seed_spend = max(2.0, min(seed_spend, 20.0))  # $20 cap
                        
                        if weak_token == 'UP':
                            self._last_trade_time_up = 0.0
                            up_on_cooldown = False
                        else:
                            self._last_trade_time_down = 0.0
                            down_on_cooldown = False
                        
                        trade = buy_with_spend(weak_token, weak_price, seed_spend, 'awareness_seed')
                        if trade:
                            trades.append(trade)
                            new_locked = self.calculate_locked_profit()
                            self.current_mode = 'awareness_seed'
                            self.mode_reason = (f'🚨 Awareness SEED {weak_token} @ ${weak_price:.3f} | '
                                               f'locked ${new_locked:+.2f} | '
                                               f'{time_to_close:.0f}s left')
                        return trades
            
            # Baseline hedge: ensure minimum defensive position
            hedge_ratio = weak_qty / strong_qty if strong_qty > 0 else 0
            if hedge_ratio < 0.20 and weak_price <= self.defensive_max_price:
                hedge_spend = self.defensive_hedge_usd
                trade = buy_with_spend(weak_token, weak_price, hedge_spend, 'awareness_hedge')
                if trade:
                    trades.append(trade)
                    new_ratio = (self.qty_down if weak_token == 'DOWN' else self.qty_up) / strong_qty if strong_qty > 0 else 0
                    self.current_mode = 'awareness'
                    self.mode_reason = (f'🛡️ Awareness hedge {weak_token} @ ${weak_price:.3f} | '
                                       f'ratio {hedge_ratio:.0%}→{new_ratio:.0%} | '
                                       f'{time_to_close:.0f}s left')
                return trades
            
            # Fall through to trend follow — keep riding the trend in awareness mode

        # ══════════════════════════════════════════════════════════
        #  SPOT-BASED ENDGAME POSITIONING
        #  When we have BTC spot price data AND the market is nearing close,
        #  use the spot-based prediction to aggressively position on the
        #  likely winning side. This overrides market-price-based trend detection
        #  because spot price is the GROUND TRUTH for UP/DOWN resolution.
        #
        #  Phases:
        #   90-60s: Moderate positioning (conf >= 70%, spend up to $8)
        #   60-30s: Aggressive positioning (conf >= 65%, spend up to $12)
        #   <30s:   Maximum positioning (conf >= 60%, bypass cooldowns, spend up to $16)
        # ══════════════════════════════════════════════════════════
        if (time_to_close is not None and time_to_close <= 90
            and self._spot_prediction is not None and self._spot_confidence > 0.55):

            # Get endgame recommendation
            should_act, predicted_side, spot_conf = self.trend_predictor.should_endgame_position(time_to_close)
            
            if should_act and predicted_side:
                predicted_price = up_price if predicted_side == 'UP' else down_price
                predicted_qty = self.qty_up if predicted_side == 'UP' else self.qty_down
                other_side = 'DOWN' if predicted_side == 'UP' else 'UP'
                other_qty = self.qty_down if predicted_side == 'UP' else self.qty_up
                other_price = down_price if predicted_side == 'UP' else up_price

                # Calculate PnL if predicted side wins
                pnl_if_predicted = (self.calculate_pnl_if_up_wins() if predicted_side == 'UP'
                                   else self.calculate_pnl_if_down_wins())
                pnl_if_wrong = (self.calculate_pnl_if_down_wins() if predicted_side == 'UP'
                               else self.calculate_pnl_if_up_wins())

                # Already profitable on predicted side? Hold but keep buying
                # to increase profit — especially if other side is losing big.
                if pnl_if_predicted >= 2.0:
                    self.current_mode = 'endgame_hold'
                    self.mode_reason = (f'🎯 Endgame HOLD — ${pnl_if_predicted:+.2f} if {predicted_side} wins | '
                                       f'conf {spot_conf:.0%} | {self._spot_reason}')
                    return trades

                # Need to build position on predicted side
                # Don't buy if price is too high (>$0.94) — risk/reward too poor
                if predicted_price < 0.94:
                    # Sizing based on confidence and urgency
                    sizing_mult = self.trend_predictor.get_position_sizing_multiplier(time_to_close)
                    base_spend = self.momentum_trade_usd * sizing_mult
                    
                    # Scale spend based on urgency
                    if time_to_close < 30:
                        # Critical zone: bypass cooldowns, max spend
                        if predicted_side == 'UP':
                            self._last_trade_time_up = 0.0
                            up_on_cooldown = False
                        else:
                            self._last_trade_time_down = 0.0
                            down_on_cooldown = False
                        max_endgame_spend = 16.0
                    elif time_to_close < 60:
                        max_endgame_spend = 12.0
                    else:
                        max_endgame_spend = 8.0

                    # If we're on the WRONG side (predicted side has worse PnL),
                    # be even more aggressive
                    if pnl_if_predicted < pnl_if_wrong - 1.0:
                        base_spend *= 1.5  # 50% more to catch up
                    
                    spend = min(base_spend, max_endgame_spend)
                    spend = max(spend, 2.0)  # Minimum $2

                    # Cap by remaining endgame budget
                    remaining_endgame = self._endgame_max_total - self._endgame_total_spent
                    if remaining_endgame <= 0:
                        self.current_mode = 'endgame_capped'
                        self.mode_reason = f'🎯 Endgame CAPPED — spent ${self._endgame_total_spent:.2f} total'
                        return trades
                    spend = min(spend, remaining_endgame)

                    trade = buy_with_spend(predicted_side, predicted_price, spend, 'endgame_spot')
                    if trade:
                        self._endgame_total_spent += spend
                        trades.append(trade)
                        new_pnl = (self.calculate_pnl_if_up_wins() if predicted_side == 'UP'
                                  else self.calculate_pnl_if_down_wins())
                        new_locked = self.calculate_locked_profit()
                        self.current_mode = 'endgame_position'
                        self.mode_reason = (f'🎯 Endgame BUY {predicted_side} @ ${predicted_price:.3f} | '
                                           f'conf {spot_conf:.0%} | pnl ${new_pnl:+.2f} | '
                                           f'locked ${new_locked:+.2f} | {self._spot_reason}')
                    return trades

        # ── A) TREND FOLLOW: Buy more of the trending side (priority) ──
        # This is the main profit driver — follow the market direction.
        # Keep following even in awareness window (down to 60s).
        # BUT: enforce imbalance limits so we don't go 5:1 on one side.
        if (trending_token and trend_confidence >= 0.6
            and time_to_close is not None and time_to_close > self.awareness_time_end):

            trending_price = up_price if trending_token == 'UP' else down_price
            trending_qty = self.qty_up if trending_token == 'UP' else self.qty_down
            other_token_t = 'DOWN' if trending_token == 'UP' else 'UP'
            other_qty_t = self.qty_down if trending_token == 'UP' else self.qty_up
            other_price_t = down_price if trending_token == 'UP' else up_price

            # IMBALANCE GUARD: If we're already tilted > max_tilt_ratio on the
            # trending side, DON'T buy more trending — buy the weak side instead
            # (it's cheap and reduces risk).
            current_tilt = (trending_qty / other_qty_t) if other_qty_t > 0 else 999.0
            if current_tilt > self.max_tilt_ratio and other_price_t <= self.defensive_max_price:
                # We're over-tilted. Buy weak side to rebalance.
                rebal_spend = self.balance_trade_usd * late_game_scale
                trade = buy_with_spend(other_token_t, other_price_t, rebal_spend, 'rebalance_weak')
                if trade:
                    trades.append(trade)
                    new_ratio_t = (self.qty_up / self.qty_down) if self.qty_down > 0 else 999.0
                    self.current_mode = 'rebalancing'
                    self.mode_reason = (f'⚖️ Rebalance: buy {other_token_t} @ ${other_price_t:.3f} | '
                                      f'tilt was {current_tilt:.1f}:1 (max {self.max_tilt_ratio:.1f}) | '
                                      f'ratio now {new_ratio_t:.2f}')
                return trades
            elif current_tilt > self.max_tilt_ratio:
                # Over-tilted but weak side too expensive — just wait
                self.current_mode = 'tilt_wait'
                self.mode_reason = (f'⚖️ Tilted {current_tilt:.1f}:1 on {trending_token} | '
                                  f'{other_token_t} @ ${other_price_t:.3f} too expensive to rebalance')
                return trades

            if trending_price <= effective_max_price:
                # Scale spend by trend strength AND time remaining
                spend = self.momentum_trade_usd * (0.5 + 0.5 * trend_strength) * late_game_scale

                # PAIR COST GUARD: Don't buy more trending side if pair cost is
                # already deep underwater (> 1.05). Each buy just digs the hole deeper.
                if current_pair > 1.05 and current_tilt > 1.0:
                    spend = min(spend, 1.5)  # Limit to $1.50 when pair is bad

                # HIGH-PRICE GUARD: At 0.80+, limit to $1 on dominant side
                # But allow full spend if buying the WEAKER side (market reversal rescue)
                if trending_price >= 0.80:
                    if trending_qty >= other_qty_t:
                        spend = min(spend, 1.0)
                    # else: buying weaker side (reversal rescue) → keep full spend

                trade = buy_with_spend(trending_token, trending_price, spend, 'trend_follow')
                if trade:
                    trades.append(trade)
                    new_pnl = self.calculate_pnl_if_up_wins() if trending_token == 'UP' else self.calculate_pnl_if_down_wins()
                    self.current_mode = 'trend_follow'
                    self.mode_reason = (f'📈 Follow {trending_token} @ ${trending_price:.3f} | '
                                      f'conf {trend_confidence:.0%} str {trend_strength:.0%} | '
                                      f'tilt {current_tilt:.1f}:1 | '
                                      f'pnl_if_{trending_token.lower()}: ${new_pnl:+.2f}')
                return trades

        # ── B) ARB IMPROVE: Buy at discount to lower pair cost ──
        # Only when no clear trend. Guards against extreme imbalance.
        if not trending_token or trend_confidence < 0.5:
            for token, price in [('UP', up_price), ('DOWN', down_price)]:
                disc = discount_to_avg(token, price)
                if disc < 0.05:  # Need 5%+ discount (strict)
                    continue
                # IMBALANCE GUARD: don't stack more than 3:1 on one side
                my_qty = self.qty_up if token == 'UP' else self.qty_down
                other_q = self.qty_down if token == 'UP' else self.qty_up
                if other_q > 0 and my_qty / other_q > 3.0:
                    continue  # Already too heavy on this side
                if my_qty > 0 and other_q / my_qty > 3.0:
                    pass  # This side is light — OK to buy more (rebalances)
                test_spend = self.improve_trade_usd * size_for_discount(disc)
                test_qty = test_spend / price if price > 0 else 0
                if test_qty < self.min_trade_size:
                    continue
                new_pair = pair_cost_after_buy(token, price, test_qty)
                if new_pair < current_pair - 0.005 and new_pair < MAX_PAIR_FOR_BALANCE:
                    trade = buy_with_spend(token, price, test_spend, 'arb_improve')
                    if trade:
                        trades.append(trade)
                        new_locked = self.calculate_locked_profit()
                        self.current_mode = 'improving'
                        self.mode_reason = f'⚡ {token} @ ${price:.3f} ({disc*100:.0f}%↓) | pair ${current_pair:.3f}→${new_pair:.3f} | locked ${locked_profit:+.2f}→${new_locked:+.2f}'
                    return trades

        # ── C) WATCHING: No discount, no trend ──
        momentum_info = f' | 🧭 {trending_token} {trend_strength:.0%}/{trend_confidence:.0%}' if trending_token else ' | 🧭 no trend'
        self.current_mode = 'watching'
        self.mode_reason = f'👀 pair ${current_pair:.3f} | locked ${locked_profit:+.2f} | combined ${combined_ask:.3f} | ratio {ratio:.2f}{momentum_info}'
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
        
        # Reset market-specific tracking for next market
        self.reset_market_tracking()
        
        return pnl

    def close_market(self):
        self.market_status = 'closed'

    def set_market_start_time(self, start_time: Optional[datetime]):
        if start_time != self.window_start:
            self._reset_fill_history()
            self.reset_market_tracking()  # Reset per-market budget tracking
        self.window_start = start_time

    def _reset_fill_history(self) -> None:
        self.fill_history.clear()
        self.last_buy_fill = None
        self.last_sell_fill = None
        self.last_fill_time = 0.0

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
        
        # Polymarket minimum order size is $1
        if total_with_fee < 1.0:
            return None
            
        if total_with_fee > self.cash:
            return None

        self.cash -= total_with_fee
        self.cash_out += total_with_fee
        self.total_fees_paid += fee
        self.net_invested = self.cash_out - self.cash_in  # compat
        self.trade_count += 1
        self.market_spent += total_with_fee  # Track spending per market
        self.last_fill_time = time.time()
        # Update per-side cooldown timer
        if token == 'UP':
            self._last_trade_time_up = time.time()
        else:
            self._last_trade_time_down = time.time()
        
        # Simulate realistic trade execution time (25ms latency per trade)
        # This ensures trades are sequential and see fresh orderbooks
        time.sleep(0.025)
        
        self.last_buy_fill = {
            'time': datetime.now(timezone.utc).strftime('%H:%M:%S.%f')[:-3],  # Include milliseconds
            'token': token,
            'price': fill.fill_price,
            'qty': fill.filled_qty,
            'reason': reason,
        }
        self.fill_history.append({
            'time': self.last_buy_fill['time'],
            'action': 'BUY',
            'token': token,
            'price': fill.fill_price,
            'qty': fill.filled_qty,
            'reason': reason,
            'fee': fee,
            'total_cost': total_with_fee,
        })

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
        avg_cost = self.avg_up if token == 'UP' else self.avg_down
        cost_removed = avg_cost * fill.filled_qty
        realized_pnl = net_proceeds - cost_removed
        self.cash += net_proceeds
        self.cash_in += net_proceeds
        self.total_sell_proceeds += net_proceeds
        self.total_fees_paid += fee
        self.net_invested = self.cash_out - self.cash_in  # compat
        self.trade_count += 1
        self.last_fill_time = time.time()
        
        # Simulate realistic trade execution time
        time.sleep(0.025)
        
        self.last_sell_fill = {
            'time': datetime.now(timezone.utc).strftime('%H:%M:%S.%f')[:-3],  # Include milliseconds
            'token': token,
            'price': fill.fill_price,
            'qty': fill.filled_qty,
            'reason': reason,
        }
        self.fill_history.append({
            'time': self.last_sell_fill['time'],
            'action': 'SELL',
            'token': token,
            'price': fill.fill_price,
            'qty': fill.filled_qty,
            'reason': reason,
            'fee': fee,
            'gross_proceeds': proceeds,
            'net_proceeds': net_proceeds,
            'avg_cost': avg_cost,
            'cost_removed': cost_removed,
            'realized_pnl': realized_pnl,
        })

        if token == 'UP':
            if self.qty_up > 0:
                self.cost_up = max(0.0, self.cost_up - cost_removed)
            self.qty_up = max(0.0, self.qty_up - fill.filled_qty)
        else:
            if self.qty_down > 0:
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
            'last_buy_fill': dict(self.last_buy_fill) if self.last_buy_fill else None,
            'last_sell_fill': dict(self.last_sell_fill) if self.last_sell_fill else None,
            'last_fill_time': self.last_fill_time,
            'fill_history': list(self.fill_history),
            # Spot predictor data
            'spot_predictor': {
                'open_price': self.trend_predictor.market_open_price,
                'current_price': self.trend_predictor.current_spot_price,
                'delta': (self.trend_predictor.current_spot_price - self.trend_predictor.market_open_price) if (self.trend_predictor.current_spot_price and self.trend_predictor.market_open_price) else None,
                'prediction': self._spot_prediction,
                'confidence': self._spot_confidence,
                'reason': self._spot_reason,
                'volatility': self.trend_predictor.get_volatility(),
                'window_high': self.trend_predictor.window_high,
                'window_low': self.trend_predictor.window_low,
                'window_range': self.trend_predictor.get_window_range(),
                'fetch_count': self.trend_predictor.spot_fetch_count,
                'history_up': self.trend_predictor.total_up,
                'history_down': self.trend_predictor.total_down,
                'consecutive_up': self.trend_predictor.consecutive_up,
                'consecutive_down': self.trend_predictor.consecutive_down,
                'endgame_total_spent': self._endgame_total_spent,
                'spot_history': [(t, p) for t, p in list(self.trend_predictor.spot_history)[-60:]],
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
            'last_buy_fill': dict(self.last_buy_fill) if self.last_buy_fill else None,
            'last_sell_fill': dict(self.last_sell_fill) if self.last_sell_fill else None,
            'last_fill_time': self.last_fill_time,
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
