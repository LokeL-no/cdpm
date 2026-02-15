#!/usr/bin/env python3
"""Realistic market test - combined ask ~1.01-1.03 like real Polymarket."""
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
    
    # Realistic starting: combined always ~1.01-1.03 (market maker spread)
    spread_over = random.uniform(0.01, 0.03)  # 1-3% over $1
    base_up = random.uniform(0.30, 0.70)
    base_down = (1.0 + spread_over) - base_up
    if base_down < 0.10 or base_down > 0.90:
        base_down = max(0.10, min(0.90, base_down))
        base_up = (1.0 + spread_over) - base_down
    
    up_price = base_up
    down_price = base_down
    
    for tick in range(180):
        time_to_close = 900 - tick * 5
        s._last_trade_time_up = 0
        s._last_trade_time_down = 0
        
        # Random walk - realistic price movement
        drift = random.gauss(0, 0.004)
        # Occasional bigger moves (news)
        if random.random() < 0.03:
            drift += random.choice([-0.04, 0.04])
        
        up_price = max(0.05, min(0.95, up_price + drift))
        # Down price anti-correlated but combined stays ~1.01-1.03
        down_price = max(0.05, min(0.95, (1.0 + spread_over) - up_price + random.gauss(0, 0.005)))
        
        s.check_and_trade(up_price, down_price, '12:00:00', time_to_close=time_to_close,
            up_orderbook=make_book(up_price), down_orderbook=make_book(down_price))
    
    # Calculate locked BEFORE resolution
    locked = s.calculate_locked_profit()
    pnl_up = s.calculate_pnl_if_up_wins()
    pnl_down = s.calculate_pnl_if_down_wins()
    
    # Outcome based on final direction
    outcome = 'UP' if up_price > down_price else 'DOWN'
    pnl = s.resolve_market(outcome)
    return pnl, s.trade_count, locked, s.qty_up, s.qty_down, up_price + down_price, pnl_up, pnl_down

if __name__ == '__main__':
    N = 300
    wins = losses = no_trade = 0
    total_pnl = 0.0
    loss_details = []
    all_pnls = []
    
    for seed in range(N):
        pnl, trades, locked, qu, qd, final_comb, pnl_up, pnl_down = run_market(seed)
        if trades == 0:
            no_trade += 1
        all_pnls.append(pnl)
        if pnl >= -0.01:
            wins += 1
        else:
            losses += 1
            loss_details.append((seed, pnl, trades, locked, qu, qd, final_comb, pnl_up, pnl_down))
        total_pnl += pnl
    
    traded = N - no_trade
    win_pnls = [p for p in all_pnls if p >= -0.01]
    loss_pnls = [p for p in all_pnls if p < -0.01]
    avg_win = sum(win_pnls)/len(win_pnls) if win_pnls else 0
    avg_loss = sum(loss_pnls)/len(loss_pnls) if loss_pnls else 0
    max_loss = min(loss_pnls) if loss_pnls else 0
    print(f'Results: {wins}W / {losses}L out of {N} markets')
    print(f'Win rate: {wins/N*100:.1f}% (traded: {traded})')
    print(f'Avg win: ${avg_win:+.2f} | Avg loss: ${avg_loss:+.2f} | Max loss: ${max_loss:+.2f}')
    print(f'Total PnL: ${total_pnl:+.2f} | Avg per trade: ${total_pnl/max(traded,1):+.2f}')
    if loss_details:
        print(f'\nLosses ({len(loss_details)}):')
        for s, p, t, l, qu, qd, c, pu, pd in loss_details[:20]:
            print(f'  Seed {s}: PnL=${p:+.2f} | {t}t | locked=${l:+.2f} | pnl_up=${pu:+.2f} pnl_dn=${pd:+.2f} | comb={c:.3f}')
    else:
        print('\nZERO LOSSES!')
