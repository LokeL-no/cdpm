#!/usr/bin/env python3
"""
Market Simulation: 10 diverse scenarios testing the current strategy.

Each scenario simulates a 15-minute Polymarket binary market with:
  - Realistic price movements (random walk with drift/volatility)
  - Synthetic orderbooks with varying depth/liquidity
  - Resolution (UP wins or DOWN wins)
  - Full execution simulator (25ms latency, VWAP fills)

Budget: $100/market, $200 starting balance (matching current config)
"""

import random
import math
import time
import sys
import os

# Patch time.time for fast simulation
_sim_clock = [0.0]
_original_time = time.time
def _fake_time():
    return _sim_clock[0]

time.time = _fake_time

from arbitrage_strategy import ArbitrageStrategy
from execution_simulator import ExecutionSimulator

# Restore real time after import
time.time = _original_time


# ═══════════════════════════════════════════════════════════════
#  SYNTHETIC ORDERBOOK GENERATOR
# ═══════════════════════════════════════════════════════════════

def make_orderbook(best_ask: float, depth_shares: float = 200, levels: int = 5, thin: bool = False):
    """Generate a synthetic orderbook with asks at best_ask and above."""
    asks = []
    base_size = depth_shares / levels
    for i in range(levels):
        price = round(best_ask + i * 0.01, 3)
        if price > 0.99:
            break
        size_mult = 1.0 if not thin else 0.3
        size = max(5, base_size * size_mult * random.uniform(0.5, 1.5))
        asks.append({'price': str(price), 'size': str(round(size, 1))})
    return {'asks': asks}


# ═══════════════════════════════════════════════════════════════
#  PRICE PATH GENERATOR
# ═══════════════════════════════════════════════════════════════

def generate_price_path(
    start_up: float,
    duration_ticks: int = 900,  # 15 min at 1s ticks
    volatility: float = 0.003,
    drift: float = 0.0,        # positive = UP tends to win
    mean_revert_strength: float = 0.01,
    shock_prob: float = 0.02,
    shock_size: float = 0.05,
):
    """Generate correlated UP/DOWN price paths for a binary market."""
    prices = []
    up = start_up
    
    for t in range(duration_ticks):
        # Mean reversion toward 0.50
        mr = mean_revert_strength * (0.50 - up)
        
        # Random walk
        noise = random.gauss(0, volatility)
        
        # Occasional shock
        shock = 0
        if random.random() < shock_prob:
            shock = random.choice([-1, 1]) * shock_size * random.uniform(0.5, 1.5)
        
        up = up + drift + mr + noise + shock
        up = max(0.02, min(0.98, up))
        
        # DOWN = 1 - UP + small spread noise
        spread_noise = random.uniform(-0.02, 0.02)
        down = 1.0 - up + spread_noise
        down = max(0.02, min(0.98, down))
        
        prices.append((round(up, 3), round(down, 3)))
    
    return prices


# ═══════════════════════════════════════════════════════════════
#  SCENARIO DEFINITIONS
# ═══════════════════════════════════════════════════════════════

SCENARIOS = [
    {
        'name': '1. Tight Spread – UP wins',
        'start_up': 0.50, 'volatility': 0.002, 'drift': 0.0001,
        'shock_prob': 0.01, 'shock_size': 0.03,
        'outcome': 'UP', 'depth': 300, 'thin': False,
        'description': 'Balanced market, low vol, UP drifts up slightly'
    },
    {
        'name': '2. Tight Spread – DOWN wins',
        'start_up': 0.50, 'volatility': 0.002, 'drift': -0.0001,
        'shock_prob': 0.01, 'shock_size': 0.03,
        'outcome': 'DOWN', 'depth': 300, 'thin': False,
        'description': 'Balanced market, low vol, DOWN drifts up'
    },
    {
        'name': '3. Volatile – UP wins',
        'start_up': 0.45, 'volatility': 0.008, 'drift': 0.0002,
        'shock_prob': 0.05, 'shock_size': 0.08,
        'outcome': 'UP', 'depth': 200, 'thin': False,
        'description': 'High volatility with frequent shocks, UP wins'
    },
    {
        'name': '4. Volatile – DOWN wins',
        'start_up': 0.55, 'volatility': 0.008, 'drift': -0.0002,
        'shock_prob': 0.05, 'shock_size': 0.08,
        'outcome': 'DOWN', 'depth': 200, 'thin': False,
        'description': 'High volatility, DOWN wins'
    },
    {
        'name': '5. Skewed UP (0.70/0.30) – UP wins',
        'start_up': 0.70, 'volatility': 0.004, 'drift': 0.0001,
        'shock_prob': 0.02, 'shock_size': 0.05,
        'outcome': 'UP', 'depth': 250, 'thin': False,
        'description': 'UP heavily favored from start, UP wins'
    },
    {
        'name': '6. Skewed UP (0.70/0.30) – DOWN wins (upset)',
        'start_up': 0.70, 'volatility': 0.004, 'drift': -0.0003,
        'shock_prob': 0.03, 'shock_size': 0.06,
        'outcome': 'DOWN', 'depth': 250, 'thin': False,
        'description': 'UP favored but DOWN wins — tests stop-loss'
    },
    {
        'name': '7. Thin Liquidity – UP wins',
        'start_up': 0.48, 'volatility': 0.005, 'drift': 0.0001,
        'shock_prob': 0.02, 'shock_size': 0.04,
        'outcome': 'UP', 'depth': 50, 'thin': True,
        'description': 'Very thin orderbook, more slippage and partial fills'
    },
    {
        'name': '8. Late Entry (starts at tick 600) – DOWN wins',
        'start_up': 0.45, 'volatility': 0.003, 'drift': -0.0001,
        'shock_prob': 0.02, 'shock_size': 0.04,
        'outcome': 'DOWN', 'depth': 200, 'thin': False,
        'description': 'Bot enters late with only 5 min left'
    },
    {
        'name': '9. Crash then Recovery – UP wins',
        'start_up': 0.50, 'volatility': 0.003, 'drift': 0.0,
        'shock_prob': 0.0, 'shock_size': 0.0,
        'outcome': 'UP', 'depth': 200, 'thin': False,
        'description': 'UP crashes to 0.20 then recovers — tests accumulate logic',
        'custom_path': True,
    },
    {
        'name': '10. Choppy Sideways – DOWN wins',
        'start_up': 0.50, 'volatility': 0.006, 'drift': 0.0,
        'shock_prob': 0.08, 'shock_size': 0.06,
        'outcome': 'DOWN', 'depth': 150, 'thin': False,
        'description': 'Highly choppy market with no trend, DOWN resolves'
    },
]


def generate_crash_recovery_path(duration: int = 900):
    """Custom path: UP crashes from 0.50 to 0.20 then recovers to 0.60."""
    prices = []
    for t in range(duration):
        frac = t / duration
        if frac < 0.3:
            # Crash phase: 0.50 → 0.20
            up = 0.50 - (0.30 * frac / 0.3)
        elif frac < 0.5:
            # Bottom: stay around 0.20-0.25
            up = 0.20 + random.gauss(0, 0.02)
        else:
            # Recovery: 0.20 → 0.60
            recovery_frac = (frac - 0.5) / 0.5
            up = 0.20 + 0.40 * recovery_frac + random.gauss(0, 0.015)
        
        up = max(0.02, min(0.98, up))
        down = max(0.02, min(0.98, 1.0 - up + random.uniform(-0.015, 0.015)))
        prices.append((round(up, 3), round(down, 3)))
    return prices


# ═══════════════════════════════════════════════════════════════
#  RUN ONE SCENARIO
# ═══════════════════════════════════════════════════════════════

def run_scenario(scenario: dict, market_budget: float = 100.0, starting_balance: float = 200.0) -> dict:
    """Run a single market scenario and return results."""
    random.seed(hash(scenario['name']) % (2**32))
    
    exec_sim = ExecutionSimulator(latency_ms=25.0, max_slippage_pct=5.0)
    
    # Use time.time patching for cooldown logic
    _sim_clock[0] = 1000000.0  # Start at some base time
    time.time = _fake_time
    
    strat = ArbitrageStrategy(
        market_budget=market_budget,
        starting_balance=starting_balance,
        exec_sim=exec_sim,
    )
    
    # Generate price path
    duration = 900  # 15 minutes at 1s ticks
    if scenario.get('custom_path'):
        prices = generate_crash_recovery_path(duration)
    else:
        prices = generate_price_path(
            start_up=scenario['start_up'],
            duration_ticks=duration,
            volatility=scenario['volatility'],
            drift=scenario.get('drift', 0.0),
            shock_prob=scenario.get('shock_prob', 0.02),
            shock_size=scenario.get('shock_size', 0.05),
        )
    
    # Determine start tick
    start_tick = 600 if '8.' in scenario['name'] else 0
    
    # Run simulation
    trades_total = 0
    for t in range(start_tick, duration):
        _sim_clock[0] = 1000000.0 + t  # Advance clock 1s per tick
        
        up_price, down_price = prices[t]
        time_to_close = duration - t  # seconds remaining
        
        # Build synthetic orderbook
        up_book = make_orderbook(up_price, depth_shares=scenario['depth'], thin=scenario['thin'])
        down_book = make_orderbook(down_price, depth_shares=scenario['depth'], thin=scenario['thin'])
        
        timestamp = f"T+{t}s"
        
        trades = strat.check_and_trade(
            up_price=up_price,
            down_price=down_price,
            timestamp=timestamp,
            time_to_close=time_to_close,
            up_orderbook=up_book,
            down_orderbook=down_book,
        )
        trades_total += len(trades)
    
    # Resolve
    outcome = scenario['outcome']
    pnl = strat.resolve_market(outcome)
    
    # Restore real time
    time.time = _original_time
    
    exec_stats = exec_sim.get_stats()
    
    return {
        'name': scenario['name'],
        'description': scenario['description'],
        'outcome': outcome,
        'pnl': pnl,
        'pnl_gross': strat.payout - (strat.cost_up + strat.cost_down),
        'fees': strat.last_fees_paid,
        'qty_up': strat.qty_up,
        'qty_down': strat.qty_down,
        'cost_up': strat.cost_up,
        'cost_down': strat.cost_down,
        'avg_up': strat.avg_up,
        'avg_down': strat.avg_down,
        'pair_cost': strat.pair_cost,
        'trade_count': trades_total,
        'payout': strat.payout,
        'total_invested': strat.cost_up + strat.cost_down,
        'arb_locked': strat.both_scenarios_positive(),
        'mgp_final': strat.calculate_locked_profit(),
        'exec_fills': exec_stats.get('total_fills', 0),
        'exec_rejects': exec_stats.get('total_rejects', 0),
        'exec_partials': exec_stats.get('total_partials', 0),
        'avg_slippage': exec_stats.get('avg_slippage_pct', 0),
        'total_slippage_cost': exec_stats.get('total_slippage_cost', 0),
        'fill_rate': exec_stats.get('fill_rate_pct', 0),
    }


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    print("=" * 90)
    print("  MARKEDSSIMULERING — 10 Scenarioer")
    print("  Strategi: HFT Mean-Reversion + Kelly Criterion")
    print("  Budget: $100/marked, $200 startbalanse")
    print("  Execution: 25ms latency, VWAP orderbook fills, 5% max slippage")
    print("=" * 90)
    print()
    
    results = []
    
    # Suppress individual trade prints
    import io
    old_stdout = sys.stdout
    
    for i, scenario in enumerate(SCENARIOS):
        sys.stdout = io.StringIO()  # Suppress strategy prints
        try:
            result = run_scenario(scenario)
        finally:
            sys.stdout = old_stdout
        
        results.append(result)
        
        pnl = result['pnl']
        icon = '✅' if pnl >= 0 else '❌'
        lock_icon = '🔒' if result['arb_locked'] else '  '
        
        print(f"{icon} {result['name']}")
        print(f"   {result['description']}")
        print(f"   Resultat: {result['outcome']} vinner | PnL: ${pnl:+.2f} (brutto ${result['pnl_gross']:+.2f}, fees ${result['fees']:.2f})")
        print(f"   Posisjon: UP={result['qty_up']:.1f} (${result['cost_up']:.2f}) | DOWN={result['qty_down']:.1f} (${result['cost_down']:.2f})")
        print(f"   Pair cost: ${result['pair_cost']:.4f} | Investert: ${result['total_invested']:.2f} | Trades: {result['trade_count']}")
        print(f"   Exec: {result['exec_fills']} fills, {result['exec_rejects']} rejected, {result['exec_partials']} partial | Fill rate: {result['fill_rate']:.1f}%")
        print(f"   Slippage: avg {result['avg_slippage']:.3f}% | total cost: ${result['total_slippage_cost']:.4f}")
        print(f"   {lock_icon} Arb locked: {result['arb_locked']} | Final MGP: ${result['mgp_final']:.2f}")
        print()
    
    # ── Summary ──
    print("=" * 90)
    print("  OPPSUMMERING")
    print("=" * 90)
    
    wins = [r for r in results if r['pnl'] >= 0]
    losses = [r for r in results if r['pnl'] < 0]
    total_pnl = sum(r['pnl'] for r in results)
    avg_pnl = total_pnl / len(results)
    locked_count = sum(1 for r in results if r['arb_locked'])
    
    print(f"\n  Win/Loss:        {len(wins)}/{len(losses)} ({len(wins)}/10)")
    print(f"  Total PnL:       ${total_pnl:+.2f}")
    print(f"  Avg PnL/marked:  ${avg_pnl:+.2f}")
    print(f"  Beste utfall:    ${max(r['pnl'] for r in results):+.2f}")
    print(f"  Verste utfall:   ${min(r['pnl'] for r in results):+.2f}")
    print(f"  Arb locked:      {locked_count}/10")
    
    if wins:
        print(f"  Avg gevinst:     ${sum(r['pnl'] for r in wins) / len(wins):+.2f}")
    if losses:
        print(f"  Avg tap:         ${sum(r['pnl'] for r in losses) / len(losses):+.2f}")
    
    total_fills = sum(r['exec_fills'] for r in results)
    total_rejects = sum(r['exec_rejects'] for r in results)
    total_slip = sum(r['total_slippage_cost'] for r in results)
    print(f"\n  Execution Stats:")
    print(f"    Total fills:    {total_fills}")
    print(f"    Total rejects:  {total_rejects}")
    print(f"    Total slippage: ${total_slip:.4f}")
    print()
    
    # Table view
    print(f"{'#':>2} {'Scenario':<45} {'Utfall':<5} {'PnL':>8} {'Invest':>8} {'Pair$':>7} {'Lock':>5}")
    print("-" * 90)
    for r in results:
        icon = '✅' if r['pnl'] >= 0 else '❌'
        lock = '🔒' if r['arb_locked'] else '  '
        name = r['name'][:44]
        print(f"{icon} {name:<45} {r['outcome']:<5} ${r['pnl']:>+7.2f} ${r['total_invested']:>7.2f} ${r['pair_cost']:>.4f} {lock}")
    print("-" * 90)
    print(f"   {'TOTAL':<45} {'':5} ${total_pnl:>+7.2f}")
    print()


if __name__ == '__main__':
    main()
