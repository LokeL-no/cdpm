#!/usr/bin/env python3
"""Monte Carlo stress test for ArbitrageStrategy - 100% win rate verification."""
import random
from arbitrage_strategy import ArbitrageStrategy
from execution_simulator import ExecutionSimulator

def make_book(price, size=500):
    return {'bids': [{'price': str(price - 0.01), 'size': str(size)}],
            'asks': [{'price': str(price), 'size': str(size)}]}

def run_market(seed, budget=400):
    random.seed(seed)
    sim = ExecutionSimulator(latency_ms=25.0, max_slippage_pct=2.0)
    s = ArbitrageStrategy(budget, budget, exec_sim=sim)
    s.market_status = 'open'
    
    combined = random.uniform(0.90, 1.05)
    up_price = random.uniform(0.30, 0.70)
    down_price = combined - up_price
    if down_price < 0.10 or down_price > 0.90:
        down_price = max(0.10, min(0.90, down_price))
        up_price = combined - down_price
    
    for tick in range(180):
        time_to_close = 900 - tick * 5
        s._last_trade_time_up = 0
        s._last_trade_time_down = 0
        drift = random.gauss(0, 0.005)
        if random.random() < 0.02:
            drift += random.choice([-0.05, 0.05])
        up_price = max(0.05, min(0.95, up_price + drift))
        down_price = max(0.05, min(0.95, down_price - drift * 0.8 + random.gauss(0, 0.003)))
        s.check_and_trade(up_price, down_price, '12:00:00', time_to_close=time_to_close,
            up_orderbook=make_book(up_price), down_orderbook=make_book(down_price))
    
    outcome = 'UP' if up_price > down_price else 'DOWN'
    pnl = s.resolve_market(outcome)
    return pnl, s.trade_count, s.calculate_locked_profit(), s.qty_up, s.qty_down, combined

if __name__ == '__main__':
    wins = 0
    losses = 0
    total_pnl = 0.0
    no_trade = 0
    loss_details = []
    
    N = 500
    for seed in range(N):
        pnl, trades, locked, qu, qd, comb = run_market(seed)
        if trades == 0:
            no_trade += 1
        if pnl >= -0.01:
            wins += 1
        else:
            losses += 1
            loss_details.append((seed, pnl, trades, locked, qu, qd, comb))
        total_pnl += pnl
    
    print(f'Results: {wins} wins / {losses} losses out of {N}')
    print(f'Win rate: {wins/N*100:.1f}%')
    print(f'No-trade: {no_trade}')
    print(f'Total PnL: ${total_pnl:+.2f} | Avg: ${total_pnl/N:+.2f}')
    if loss_details:
        print('Losses:')
        for s, p, t, l, qu, qd, c in loss_details[:15]:
            print(f'  Seed {s}: PnL=${p:+.2f} | {t}t | locked=${l:+.2f} | UP={qu:.1f} DN={qd:.1f} | comb={c:.3f}')
    else:
        print('NO LOSSES - 100% WIN RATE ACHIEVED!')
