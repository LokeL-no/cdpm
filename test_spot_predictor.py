#!/usr/bin/env python3
"""
Realistic market test WITH BTC spot price simulation.
Simulates both Polymarket prices AND actual BTC spot price movement
to test the spot-based trend predictor.
"""
import random
import math
from arbitrage_strategy import ArbitrageStrategy
from execution_simulator import ExecutionSimulator

def make_book(price, size=500):
    return {'bids': [{'price': str(price - 0.01), 'size': str(size)}],
            'asks': [{'price': str(price), 'size': str(size)}]}

def run_market(seed, budget=400, use_spot=True):
    random.seed(seed)
    sim = ExecutionSimulator(latency_ms=25.0, max_slippage_pct=2.0)
    s = ArbitrageStrategy(budget, budget, exec_sim=sim)
    s.market_status = 'open'
    
    # === SIMULATE BTC SPOT PRICE ===
    # BTC starts at ~$97,000, moves with realistic volatility
    btc_open = 97000 + random.gauss(0, 500)
    btc_price = btc_open
    btc_volatility = random.uniform(5, 25)  # $/tick volatility
    
    # Set spot open price
    if use_spot:
        s.set_market_open_spot(btc_open)
    
    # Realistic starting: combined always ~1.01-1.03 (market maker spread)
    spread_over = random.uniform(0.01, 0.03)
    
    # Market prices are informed by BTC direction but NOISY and LAGGING
    # Start at 50/50 since market just opened
    up_price = 0.50 + random.uniform(-0.05, 0.05)
    down_price = (1.0 + spread_over) - up_price
    if down_price < 0.10 or down_price > 0.90:
        down_price = max(0.10, min(0.90, down_price))
        up_price = (1.0 + spread_over) - down_price
    
    for tick in range(180):  # 180 ticks * 5s = 900s = 15 min (sampling a 5 min window)
        time_to_close = 300 - tick * (300/180)  # 5 min market, linear tick mapping
        s._last_trade_time_up = 0
        s._last_trade_time_down = 0
        
        # === BTC SPOT PRICE WALK ===
        # Random walk with slight mean-reversion to prevent extreme values
        btc_drift = random.gauss(0, btc_volatility)
        # Occasional larger moves (news, volume spikes)
        if random.random() < 0.03:
            btc_drift += random.choice([-1, 1]) * random.uniform(20, 80)
        btc_price += btc_drift
        
        # Feed spot price to strategy
        if use_spot:
            s.update_spot_price(btc_price)
        
        # === MARKET PRICES ===
        # Market prices reflect BTC direction but with:
        # - Noise (market maker spread)
        # - Lag (takes a few ticks to react)
        # - Overreaction (price swings exaggerated near end)
        btc_delta = btc_price - btc_open
        # Convert BTC delta to probability (sigmoid-like)
        # At +$50, UP ~60%. At +$200, UP ~90%
        btc_signal = btc_delta / (abs(btc_delta) + 50)  # Normalized -1 to 1
        
        # Time factor: market prices become more extreme near close
        time_factor = 1.0 + max(0, (1.0 - time_to_close / 300)) * 2.0
        
        # Target market probability
        target_up = 0.50 + btc_signal * 0.40 * time_factor
        target_up = max(0.05, min(0.95, target_up))
        
        # Market prices lag behind target (exponential smoothing)
        lag_factor = 0.15  # 15% convergence per tick
        up_price = up_price + lag_factor * (target_up - up_price) + random.gauss(0, 0.004)
        up_price = max(0.05, min(0.95, up_price))
        
        # Down price anti-correlated
        down_price = max(0.05, min(0.95, (1.0 + spread_over) - up_price + random.gauss(0, 0.005)))
        
        s.check_and_trade(up_price, down_price, '12:00:00', time_to_close=time_to_close,
            up_orderbook=make_book(up_price), down_orderbook=make_book(down_price))
    
    # Calculate locked BEFORE resolution
    locked = s.calculate_locked_profit()
    pnl_up = s.calculate_pnl_if_up_wins()
    pnl_down = s.calculate_pnl_if_down_wins()
    
    # Outcome: determined by BTC spot (ground truth)
    outcome = 'UP' if btc_price > btc_open else 'DOWN'
    pnl = s.resolve_market(outcome)
    
    # Get spot prediction info
    spot_pred = s._spot_prediction
    spot_conf = s._spot_confidence
    
    return pnl, s.trade_count, locked, s.qty_up, s.qty_down, up_price + down_price, pnl_up, pnl_down, outcome, spot_pred, spot_conf

if __name__ == '__main__':
    import sys
    N = 500
    use_spot = '--no-spot' not in sys.argv
    
    print(f"{'WITH' if use_spot else 'WITHOUT'} spot-based predictor")
    print(f"Running {N} markets...\n")
    
    wins = losses = no_trade = 0
    total_pnl = 0.0
    loss_details = []
    all_pnls = []
    correct_predictions = 0
    total_predictions = 0
    endgame_trades = 0
    
    for seed in range(N):
        result = run_market(seed, use_spot=use_spot)
        pnl, trades, locked, qu, qd, final_comb, pnl_up, pnl_down, outcome, spot_pred, spot_conf = result
        
        if trades == 0:
            no_trade += 1
        all_pnls.append(pnl)
        
        # Track prediction accuracy
        if spot_pred is not None:
            total_predictions += 1
            if spot_pred == outcome:
                correct_predictions += 1
        
        if pnl >= -0.01:
            wins += 1
        else:
            losses += 1
            loss_details.append((seed, pnl, trades, locked, qu, qd, final_comb, pnl_up, pnl_down, outcome, spot_pred, spot_conf))
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
    
    if total_predictions > 0:
        print(f'\n📊 Spot Prediction Accuracy: {correct_predictions}/{total_predictions} = {correct_predictions/total_predictions*100:.1f}%')
    
    if loss_details:
        print(f'\nLosses ({len(loss_details)}):')
        for s, p, t, l, qu, qd, c, pu, pd, out, pred, conf in loss_details[:20]:
            pred_str = f"pred={pred} {conf:.0%}" if pred else "no pred"
            print(f'  Seed {s}: PnL=${p:+.2f} | {t}t | locked=${l:+.2f} | outcome={out} | {pred_str} | pnl_up=${pu:+.2f} pnl_dn=${pd:+.2f}')
    else:
        print('\nZERO LOSSES! 🎉')
