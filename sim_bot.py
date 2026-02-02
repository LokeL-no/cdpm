#!/usr/bin/env python3
"""
Polymarket Simulator Bot - Manual Price Control for Testing
Allows manual control of BTC/ETH prices via sliders to test trading logic.
"""

import asyncio
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict
from aiohttp import web

# Supported assets
SUPPORTED_ASSETS = ['btc', 'eth']

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🧪 Polymarket Simulator</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0c0c0c;
            color: #fff;
            font-family: 'Consolas', monospace;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
            border: 2px solid #f59e0b;
            border-radius: 8px;
            padding: 20px;
            background: linear-gradient(180deg, #0c0c0c 0%, #1a1a2e 100%);
        }
        .header {
            text-align: center;
            border-bottom: 1px solid #333;
            padding-bottom: 15px;
            margin-bottom: 20px;
        }
        .header h1 { color: #f59e0b; font-size: 24px; }
        .sim-badge {
            background: #f59e0b;
            color: #000;
            padding: 4px 12px;
            border-radius: 4px;
            font-weight: bold;
            display: inline-block;
            margin-top: 8px;
        }
        
        /* Controls Panel */
        .controls-panel {
            background: #1a1a2e;
            border: 2px solid #f59e0b;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .controls-title {
            color: #f59e0b;
            font-size: 18px;
            margin-bottom: 15px;
            text-align: center;
        }
        .asset-controls {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        .asset-control-box {
            background: #111;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 15px;
        }
        .asset-control-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        .asset-badge {
            padding: 4px 12px;
            border-radius: 4px;
            font-weight: bold;
        }
        .asset-btc { background: #f7931a; color: #000; }
        .asset-eth { background: #627eea; color: #fff; }
        
        .slider-group {
            margin-bottom: 15px;
        }
        .slider-label {
            display: flex;
            justify-content: space-between;
            margin-bottom: 5px;
            font-size: 14px;
        }
        .slider-label .price-display {
            font-weight: bold;
            font-size: 16px;
        }
        .up-label { color: #22c55e; }
        .down-label { color: #ef4444; }
        
        input[type="range"] {
            width: 100%;
            height: 8px;
            border-radius: 4px;
            outline: none;
            -webkit-appearance: none;
        }
        input[type="range"]::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            cursor: pointer;
        }
        .up-slider { background: linear-gradient(to right, #166534, #22c55e); }
        .up-slider::-webkit-slider-thumb { background: #22c55e; }
        .down-slider { background: linear-gradient(to right, #991b1b, #ef4444); }
        .down-slider::-webkit-slider-thumb { background: #ef4444; }
        
        .pair-info {
            text-align: center;
            padding: 10px;
            background: #1a1a2e;
            border-radius: 4px;
            margin-top: 10px;
        }
        .pair-cost { font-size: 18px; font-weight: bold; }
        .pair-good { color: #22c55e; }
        .pair-bad { color: #ef4444; }
        
        /* Market Controls */
        .market-controls {
            display: flex;
            justify-content: center;
            gap: 15px;
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid #333;
        }
        .control-btn {
            padding: 10px 25px;
            border: none;
            border-radius: 6px;
            font-weight: bold;
            cursor: pointer;
            font-size: 14px;
        }
        .btn-start { background: #22c55e; color: #000; }
        .btn-end { background: #ef4444; color: #fff; }
        .btn-reset { background: #3b82f6; color: #fff; }
        .control-btn:hover { opacity: 0.8; }
        
        .time-display {
            text-align: center;
            font-size: 24px;
            color: #f59e0b;
            margin: 10px 0;
        }
        
        /* Stats */
        .global-stats {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin-bottom: 20px;
            padding: 15px;
            background: #1a1a2e;
            border-radius: 8px;
        }
        .global-stat { text-align: center; }
        .global-stat .label { color: #888; font-size: 12px; }
        .global-stat .value { font-size: 24px; font-weight: bold; }
        .profit { color: #22c55e; }
        .loss { color: #ef4444; }
        
        /* Markets Grid */
        .markets-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 15px;
            margin-bottom: 20px;
        }
        .market-card {
            background: #111;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 15px;
        }
        .market-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
            padding-bottom: 10px;
            border-bottom: 1px solid #333;
        }
        .market-status {
            font-size: 12px;
            padding: 2px 8px;
            border-radius: 4px;
        }
        .status-open { background: #22c55e; color: #000; }
        .status-resolved { background: #3b82f6; color: #fff; }
        
        .prices-row {
            display: flex;
            justify-content: space-around;
            margin-bottom: 10px;
        }
        .price-box {
            text-align: center;
            padding: 10px 20px;
            border-radius: 4px;
        }
        .price-up { background: rgba(34, 197, 94, 0.2); border: 1px solid #22c55e; }
        .price-down { background: rgba(239, 68, 68, 0.2); border: 1px solid #ef4444; }
        .price-label { font-size: 12px; color: #888; }
        .price-value { font-size: 20px; font-weight: bold; }
        
        .holdings-row {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 10px;
            font-size: 12px;
            margin-bottom: 10px;
        }
        .holdings-row-2 {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
            font-size: 12px;
        }
        .holding-item {
            text-align: center;
            padding: 8px;
            background: #1a1a2e;
            border-radius: 4px;
        }
        .holding-label { color: #888; margin-bottom: 4px; }
        .holding-value { font-size: 14px; font-weight: bold; }
        .market-pnl {
            text-align: center;
            padding: 10px;
            background: #0a0a0a;
            border-radius: 4px;
            margin-top: 10px;
        }
        
        /* Trade Log */
        .log-section {
            background: #111;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 15px;
            max-height: 300px;
            overflow-y: auto;
        }
        .log-section h2 {
            color: #3b82f6;
            margin-bottom: 10px;
            font-size: 16px;
        }
        .log-entry {
            padding: 5px 10px;
            margin-bottom: 5px;
            border-radius: 4px;
            font-size: 12px;
            background: #1a1a2e;
        }
        .log-buy { border-left: 3px solid #22c55e; }
        .log-info { border-left: 3px solid #3b82f6; }
        .log-profit { border-left: 3px solid #f59e0b; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🧪 Polymarket Trading Simulator</h1>
            <div class="sim-badge">⚠️ SIMULATION MODE - No Real Trades</div>
        </div>
        
        <!-- Price Controls -->
        <div class="controls-panel">
            <div class="controls-title">📊 Manual Price Control</div>
            <div class="time-display" id="market-timer">Market: Not Started</div>
            <div class="asset-controls">
                <!-- BTC Controls -->
                <div class="asset-control-box">
                    <div class="asset-control-header">
                        <span class="asset-badge asset-btc">BTC</span>
                        <span id="btc-pair-badge" class="pair-cost pair-bad">Pair: $1.01</span>
                    </div>
                    <div class="slider-group">
                        <div class="slider-label">
                            <span class="up-label">UP Price:</span>
                            <span class="price-display up-label" id="btc-up-display">$0.50</span>
                        </div>
                        <input type="range" id="btc-up-slider" class="up-slider" min="1" max="99" value="50" oninput="updatePrice('btc', 'up', this.value)">
                    </div>
                    <div class="slider-group">
                        <div class="slider-label">
                            <span class="down-label">DOWN Price:</span>
                            <span class="price-display down-label" id="btc-down-display">$0.51</span>
                        </div>
                        <input type="range" id="btc-down-slider" class="down-slider" min="1" max="99" value="51" oninput="updatePrice('btc', 'down', this.value)">
                    </div>
                </div>
                
                <!-- ETH Controls -->
                <div class="asset-control-box">
                    <div class="asset-control-header">
                        <span class="asset-badge asset-eth">ETH</span>
                        <span id="eth-pair-badge" class="pair-cost pair-bad">Pair: $1.01</span>
                    </div>
                    <div class="slider-group">
                        <div class="slider-label">
                            <span class="up-label">UP Price:</span>
                            <span class="price-display up-label" id="eth-up-display">$0.50</span>
                        </div>
                        <input type="range" id="eth-up-slider" class="up-slider" min="1" max="99" value="50" oninput="updatePrice('eth', 'up', this.value)">
                    </div>
                    <div class="slider-group">
                        <div class="slider-label">
                            <span class="down-label">DOWN Price:</span>
                            <span class="price-display down-label" id="eth-down-display">$0.51</span>
                        </div>
                        <input type="range" id="eth-down-slider" class="down-slider" min="1" max="99" value="51" oninput="updatePrice('eth', 'down', this.value)">
                    </div>
                </div>
            </div>
            <div class="market-controls">
                <button class="control-btn btn-start" onclick="startMarket()">▶️ Start 15min Market</button>
                <button class="control-btn btn-end" onclick="endMarket()">⏹️ End Market Now</button>
                <button class="control-btn btn-reset" onclick="resetBot()">🔄 Reset Bot</button>
            </div>
        </div>
        
        <!-- Global Stats -->
        <div class="global-stats">
            <div class="global-stat">
                <div class="label">Starting Balance</div>
                <div class="value">$<span id="starting-balance">1000.00</span></div>
            </div>
            <div class="global-stat">
                <div class="label">Cash Balance</div>
                <div class="value">$<span id="current-balance">1000.00</span></div>
            </div>
            <div class="global-stat">
                <div class="label">True Balance</div>
                <div class="value">$<span id="true-balance">1000.00</span></div>
            </div>
            <div class="global-stat">
                <div class="label">Total PnL</div>
                <div class="value" id="total-pnl">$0.00</div>
            </div>
        </div>
        
        <!-- Markets -->
        <div class="markets-grid" id="active-markets">
            <div style="color: #888; text-align: center; padding: 40px; grid-column: span 2;">
                Press "Start 15min Market" to begin simulation
            </div>
        </div>
        
        <!-- Trade Log -->
        <div class="log-section">
            <h2>📋 Activity Log</h2>
            <div id="trade-log">
                <div class="log-entry log-info">Welcome to the simulator! Adjust prices with sliders and click Start.</div>
            </div>
        </div>
    </div>
    
    <script>
        let ws;
        let prices = {
            btc: { up: 0.50, down: 0.51 },
            eth: { up: 0.50, down: 0.51 }
        };
        
        function updatePrice(asset, side, value) {
            const price = value / 100;
            prices[asset][side] = price;
            
            // Auto-adjust the other side to keep pair cost = $1.01 (realistic spread)
            const PAIR_TARGET = 1.01;
            const otherSide = side === 'up' ? 'down' : 'up';
            const otherPrice = Math.max(0.01, Math.min(0.99, PAIR_TARGET - price));
            prices[asset][otherSide] = otherPrice;
            
            // Update both displays
            document.getElementById(`${asset}-${side}-display`).textContent = `$${price.toFixed(2)}`;
            document.getElementById(`${asset}-${otherSide}-display`).textContent = `$${otherPrice.toFixed(2)}`;
            
            // Update both sliders
            document.getElementById(`${asset}-${otherSide}-slider`).value = Math.round(otherPrice * 100);
            
            // Update pair badge
            const pair = prices[asset].up + prices[asset].down;
            const badge = document.getElementById(`${asset}-pair-badge`);
            badge.textContent = `Pair: $${pair.toFixed(2)}`;
            badge.className = pair < 1.0 ? 'pair-cost pair-good' : 'pair-cost pair-bad';
            
            // Send to server
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                    action: 'set_price',
                    asset: asset,
                    up: prices[asset].up,
                    down: prices[asset].down
                }));
            }
        }
        
        function startMarket() {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ action: 'start_market' }));
                addLog('🚀 Starting new 15-minute market...', 'info');
            }
        }
        
        function endMarket() {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ action: 'end_market' }));
                addLog('⏹️ Ending market early...', 'info');
            }
        }
        
        function resetBot() {
            if (confirm('Reset bot? This will clear all positions and reset to $1000.')) {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ action: 'reset' }));
                    addLog('🔄 Bot reset to initial state', 'info');
                }
            }
        }
        
        function addLog(message, type) {
            const log = document.getElementById('trade-log');
            const entry = document.createElement('div');
            entry.className = `log-entry log-${type}`;
            entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
            log.insertBefore(entry, log.firstChild);
            if (log.children.length > 50) {
                log.removeChild(log.lastChild);
            }
        }
        
        function connect() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(protocol + '//' + window.location.host + '/ws');
            
            ws.onopen = () => addLog('Connected to simulator', 'info');
            ws.onclose = () => setTimeout(connect, 2000);
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                updateUI(data);
            };
        }
        
        function updateUI(data) {
            // Update balances
            document.getElementById('starting-balance').textContent = data.starting_balance.toFixed(2);
            document.getElementById('current-balance').textContent = data.cash.toFixed(2);
            document.getElementById('true-balance').textContent = data.true_balance.toFixed(2);
            
            const pnl = data.true_balance - data.starting_balance;
            const pnlEl = document.getElementById('total-pnl');
            pnlEl.textContent = (pnl >= 0 ? '+' : '') + '$' + pnl.toFixed(2);
            pnlEl.className = 'value ' + (pnl >= 0 ? 'profit' : 'loss');
            
            // Update timer
            const timer = document.getElementById('market-timer');
            if (data.market_active) {
                const mins = Math.floor(data.time_remaining / 60);
                const secs = Math.floor(data.time_remaining % 60);
                timer.textContent = `⏱️ Time Remaining: ${mins}:${secs.toString().padStart(2, '0')}`;
                timer.style.color = data.time_remaining < 60 ? '#ef4444' : '#f59e0b';
            } else {
                timer.textContent = 'Market: Not Active';
                timer.style.color = '#888';
            }
            
            // Update markets
            const grid = document.getElementById('active-markets');
            if (!data.market_active) {
                grid.innerHTML = '<div style="color: #888; text-align: center; padding: 40px; grid-column: span 2;">Press "Start 15min Market" to begin simulation</div>';
            } else {
                let html = '';
                for (const [asset, m] of Object.entries(data.markets)) {
                    const pt = m;
                    const assetUpper = asset.toUpperCase();
                    const lockedPnl = Math.min(pt.qty_up, pt.qty_down) - (pt.cost_up + pt.cost_down);
                    const statusClass = pt.market_status === 'open' ? 'status-open' : 'status-resolved';
                    
                    html += `
                        <div class="market-card">
                            <div class="market-header">
                                <span class="asset-badge asset-${asset}">${assetUpper}</span>
                                <span class="market-status ${statusClass}">${pt.market_status.toUpperCase()}</span>
                            </div>
                            <div class="prices-row">
                                <div class="price-box price-up">
                                    <div class="price-label">UP</div>
                                    <div class="price-value">$${m.up_price.toFixed(3)}</div>
                                </div>
                                <div class="price-box price-down">
                                    <div class="price-label">DOWN</div>
                                    <div class="price-value">$${m.down_price.toFixed(3)}</div>
                                </div>
                            </div>
                            <div class="holdings-row">
                                <div class="holding-item">
                                    <div class="holding-label">Qty UP</div>
                                    <div class="holding-value">${pt.qty_up.toFixed(1)}</div>
                                    <div class="holding-label">Avg: $${pt.avg_up.toFixed(3)}</div>
                                    <div class="holding-label" style="color: #f59e0b;">Spent: $${pt.cost_up.toFixed(2)}</div>
                                </div>
                                <div class="holding-item">
                                    <div class="holding-label">Qty DOWN</div>
                                    <div class="holding-value">${pt.qty_down.toFixed(1)}</div>
                                    <div class="holding-label">Avg: $${pt.avg_down.toFixed(3)}</div>
                                    <div class="holding-label" style="color: #f59e0b;">Spent: $${pt.cost_down.toFixed(2)}</div>
                                </div>
                            </div>
                            <div class="holdings-row-2">
                                <div class="holding-item">
                                    <div class="holding-label">Total Spent</div>
                                    <div class="holding-value" style="color: #f59e0b;">$${(pt.cost_up + pt.cost_down).toFixed(2)}</div>
                                </div>
                                <div class="holding-item">
                                    <div class="holding-label">Pair Cost</div>
                                    <div class="holding-value ${pt.pair_cost < 1 ? 'profit' : 'loss'}">$${pt.pair_cost.toFixed(3)}</div>
                                </div>
                                <div class="holding-item">
                                    <div class="holding-label">Qty Ratio</div>
                                    <div class="holding-value ${pt.qty_ratio <= 1.1 ? 'profit' : 'loss'}">${pt.qty_ratio?.toFixed(2) || '0.00'}x</div>
                                </div>
                            </div>
                            <div class="market-pnl">
                                <span style="color: #888;">Locked PnL: </span>
                                <span class="${pt.locked_profit >= 0 ? 'profit' : 'loss'}" style="font-weight: bold;">
                                    ${pt.locked_profit >= 0 ? '+' : ''}$${pt.locked_profit.toFixed(2)}
                                </span>
                                <span style="color: #888; margin-left: 15px;">Best Case: </span>
                                <span class="${pt.best_case_profit >= 0 ? 'profit' : 'loss'}" style="font-weight: bold;">
                                    ${pt.best_case_profit >= 0 ? '+' : ''}$${(pt.best_case_profit || 0).toFixed(2)}
                                </span>
                                ${pt.market_status === 'resolved' ? 
                                    `<br><span style="color: #3b82f6;">Outcome: ${pt.resolution_outcome} | Final: ${pt.final_pnl >= 0 ? '+' : ''}$${pt.final_pnl?.toFixed(2)}</span>` 
                                    : ''}
                            </div>
                        </div>
                    `;
                }
                grid.innerHTML = html;
            }
            
            // Show trade logs
            if (data.log_messages) {
                for (const msg of data.log_messages) {
                    addLog(msg.text, msg.type);
                }
            }
        }
        
        connect();
    </script>
</body>
</html>
"""


class SimulatedTrader:
    """Paper trader for simulation - SAME LOGIC AS web_bot_multi.py"""
    
    def __init__(self, cash_ref: dict, asset: str):
        self.cash_ref = cash_ref
        self.asset = asset
        self.qty_up = 0.0
        self.qty_down = 0.0
        self.cost_up = 0.0
        self.cost_down = 0.0
        self.trade_count = 0
        self.market_status = 'open'
        self.resolution_outcome = None
        self.final_pnl = None
        self.payout = 0.0
        self.last_trade_time = 0
        self.first_trade_time = 0
        self.starting_balance = 100.0
        
        # === GABAGOOL v7 - RECOVERY MODE STRATEGY ===
        # Core principle: Get pair_cost < $1.00 by ANY means necessary
        
        # Trading strategy parameters
        self.cheap_threshold = 0.45      # What we consider "cheap"
        self.very_cheap_threshold = 0.38 # Very cheap - accumulate
        self.force_balance_threshold = 0.52  # Max price to pay when balancing
        self.max_balance_price = 0.60    # Absolute max for emergency balance
        self.target_pair_cost = 0.95     # Ideal pair cost target
        self.max_pair_cost = 0.995       # CRITICAL: Never buy if this would push pair over
        
        # Position sizing (10x increased)
        self.min_trade_size = 3.0        # Was 0.3
        self.max_single_trade = 15.0     # Was 1.5
        self.cooldown_seconds = 4
        self.initial_trade_usd = 35.0    # Was 3.5
        self.max_position_pct = 0.50     # Max 50% of balance per market
        self.force_balance_after_seconds = 120
        
        # === GUARANTEED PROFIT PARAMETERS ===
        self.max_qty_ratio = 1.20       # Max 20% imbalance
        self.emergency_ratio = 1.35     # Emergency: max 35% imbalance
        self.recovery_ratio = 1.50      # Recovery: max 50% (only when pair_cost > 1.05)
        self.target_qty_ratio = 1.0     # Perfect balance
        self.rebalance_trigger = 1.10   # Start rebalancing earlier
        
        # === FEE AWARENESS ===
        self.max_entry_pair_potential = 0.98  # STRICT: Only enter if pair < $0.98
    
    @staticmethod
    def calculate_fee(price: float, qty: float) -> float:
        """Calculate Polymarket fee based on price."""
        fee_table = {
            0.01: 0.0000, 0.05: 0.0006, 0.10: 0.0020, 0.15: 0.0041,
            0.20: 0.0064, 0.25: 0.0088, 0.30: 0.0110, 0.35: 0.0129,
            0.40: 0.0144, 0.45: 0.0153, 0.50: 0.0156, 0.55: 0.0153,
            0.60: 0.0144, 0.65: 0.0129, 0.70: 0.0110, 0.75: 0.0088,
            0.80: 0.0064, 0.85: 0.0041, 0.90: 0.0020, 0.95: 0.0006,
            0.99: 0.0000
        }
        prices_list = sorted(fee_table.keys())
        
        if price <= prices_list[0]:
            rate = fee_table[prices_list[0]]
        elif price >= prices_list[-1]:
            rate = fee_table[prices_list[-1]]
        else:
            for i in range(len(prices_list) - 1):
                if prices_list[i] <= price <= prices_list[i + 1]:
                    p1, p2 = prices_list[i], prices_list[i + 1]
                    r1, r2 = fee_table[p1], fee_table[p2]
                    rate = r1 + (r2 - r1) * (price - p1) / (p2 - p1)
                    break
        
        trade_value = price * qty
        return trade_value * rate
    
    def calculate_total_fees(self) -> float:
        """Calculate total fees for current positions"""
        fee_up = self.calculate_fee(self.avg_up, self.qty_up) if self.qty_up > 0 else 0
        fee_down = self.calculate_fee(self.avg_down, self.qty_down) if self.qty_down > 0 else 0
        return fee_up + fee_down
    
    @property
    def cash(self):
        return self.cash_ref['balance']
    
    @cash.setter
    def cash(self, value):
        self.cash_ref['balance'] = value
    
    @property
    def avg_up(self):
        return self.cost_up / self.qty_up if self.qty_up > 0 else 0
    
    @property
    def avg_down(self):
        return self.cost_down / self.qty_down if self.qty_down > 0 else 0
    
    @property
    def pair_cost(self):
        if self.qty_up == 0 or self.qty_down == 0:
            return 0.0
        return self.avg_up + self.avg_down
    
    @property
    def locked_profit(self):
        """Guaranteed profit regardless of outcome (worst-case), accounting for fees"""
        if self.qty_up == 0 or self.qty_down == 0:
            return 0.0
        min_qty = min(self.qty_up, self.qty_down)
        total_cost = self.cost_up + self.cost_down
        fees = self.calculate_total_fees()
        return min_qty - total_cost - fees
    
    @property
    def best_case_profit(self) -> float:
        """Best-case profit if the larger position wins"""
        if self.qty_up == 0 or self.qty_down == 0:
            return 0.0
        max_qty = max(self.qty_up, self.qty_down)
        total_cost = self.cost_up + self.cost_down
        fees = self.calculate_total_fees()
        return max_qty - total_cost - fees
    
    @property
    def qty_ratio(self) -> float:
        """Ratio of larger qty to smaller qty (1.0 = perfectly balanced)"""
        if self.qty_up == 0 or self.qty_down == 0:
            return 0.0
        return max(self.qty_up, self.qty_down) / min(self.qty_up, self.qty_down)
    
    def simulate_buy(self, side: str, price: float, qty: float) -> tuple:
        """Simulate a buy and return (new_avg, new_pair_cost)"""
        cost = price * qty
        if side == 'UP':
            new_cost_up = self.cost_up + cost
            new_qty_up = self.qty_up + qty
            new_avg_up = new_cost_up / new_qty_up
            new_avg_down = self.avg_down
        else:
            new_cost_down = self.cost_down + cost
            new_qty_down = self.qty_down + qty
            new_avg_down = new_cost_down / new_qty_down
            new_avg_up = self.avg_up
        
        if new_avg_up == 0 or new_avg_down == 0:
            return (new_avg_up if side == 'UP' else new_avg_down, 0.0)
        return (new_avg_up if side == 'UP' else new_avg_down, new_avg_up + new_avg_down)
    
    def locked_profit_after_buy(self, side: str, price: float, qty: float) -> float:
        """Calculate guaranteed profit after a hypothetical buy, with accurate fees"""
        cost = price * qty
        new_qty_up = self.qty_up + qty if side == 'UP' else self.qty_up
        new_qty_down = self.qty_down + qty if side == 'DOWN' else self.qty_down
        new_cost_up = self.cost_up + cost if side == 'UP' else self.cost_up
        new_cost_down = self.cost_down + cost if side == 'DOWN' else self.cost_down
        if new_qty_up == 0 or new_qty_down == 0:
            return 0.0
        
        new_avg_up = new_cost_up / new_qty_up if new_qty_up > 0 else 0
        new_avg_down = new_cost_down / new_qty_down if new_qty_down > 0 else 0
        fee_up = self.calculate_fee(new_avg_up, new_qty_up)
        fee_down = self.calculate_fee(new_avg_down, new_qty_down)
        total_fees = fee_up + fee_down
        
        total_cost = new_cost_up + new_cost_down
        return min(new_qty_up, new_qty_down) - total_cost - total_fees
    
    def should_buy(self, side: str, price: float, other_price: float, is_rebalance: bool = False, is_emergency: bool = False, time_to_close: float = None) -> tuple:
        """
        GABAGOOL v7 - RECOVERY MODE ENABLED
        
        THE ONLY WAY TO GUARANTEE PROFIT:
        - pair_cost (avg_UP + avg_DOWN) < $1.00
        - qty_UP ≈ qty_DOWN (balanced positions)
        """
        if self.market_status != 'open':
            return False, 0, "Market not open"
        
        now = time.time()
        cooldown = self.cooldown_seconds / 2 if is_rebalance else self.cooldown_seconds
        if now - self.last_trade_time < cooldown:
            return False, 0, "Cooldown active"
        
        my_qty = self.qty_up if side == 'UP' else self.qty_down
        my_cost = self.cost_up if side == 'UP' else self.cost_down
        my_avg = my_cost / my_qty if my_qty > 0 else 0
        other_qty = self.qty_down if side == 'UP' else self.qty_up
        other_cost = self.cost_down if side == 'UP' else self.cost_up
        other_avg = other_cost / other_qty if other_qty > 0 else 0
        other_side = 'DOWN' if side == 'UP' else 'UP'
        
        # === POSITION SIZE LIMIT ===
        total_spent = self.cost_up + self.cost_down
        max_total_spend = self.starting_balance * self.max_position_pct
        remaining_budget = max_total_spend - total_spent
        
        if remaining_budget <= self.min_trade_size and not is_emergency and not (my_qty == 0 and other_qty > 0):
            return False, 0, f"Position limit reached (spent ${total_spent:.0f})"
        
        # === PHASE 1: ENTRY - Buy cheap side first ===
        if my_qty == 0 and other_qty == 0:
            if price > self.cheap_threshold:
                return False, 0, f"First trade needs price < ${self.cheap_threshold}"
            
            if time_to_close is not None and time_to_close < 180:
                return False, 0, f"Only {time_to_close:.0f}s left - too late to start"
            
            max_spend = min(self.initial_trade_usd, self.max_single_trade, remaining_budget, self.cash)
            qty = max_spend / price
            self.first_trade_time = now
            return True, qty, f"🎯 ENTRY @ ${price:.3f}"
        
        # === PHASE 2: HEDGE - Must have both sides ===
        if my_qty == 0 and other_qty > 0:
            potential_pair = other_avg + price
            
            # After 10 seconds, NEVER accept pair > $1.00!
            market_elapsed = 900.0 - time_to_close if time_to_close is not None else 0.0
            if market_elapsed > 10 and potential_pair > 1.0:
                return False, 0, f"⛔ REFUSE hedge: pair ${potential_pair:.3f} > $1.00 after {market_elapsed:.0f}s"
            
            # Match qty to balance
            target_qty = other_qty
            cost_needed = target_qty * price
            max_spend = min(cost_needed, self.cash * 0.8)
            qty = max_spend / price
            
            if qty < 1.0:
                return False, 0, f"Not enough cash to hedge"
            
            return True, qty, f"🔒 HEDGE @ ${price:.3f} (pair: ${potential_pair:.2f})"
        
        # === PHASE 3: OPTIMIZE - Build toward guaranteed profit ===
        current_pair_cost = self.pair_cost
        total_spent = self.cost_up + self.cost_down
        min_qty = min(self.qty_up, self.qty_down)
        fees = self.calculate_total_fees()
        
        # THE KEY METRIC: guaranteed_profit = min_qty - total_spent - fees
        guaranteed_profit = min_qty - total_spent - fees
        
        # Current ratio (1.0 = perfectly balanced)
        ratio = my_qty / other_qty if other_qty > 0 else 1.0
        
        # TARGET: pair_cost < $0.97 to ensure profit after fees!
        TARGET_PAIR_COST = 0.97
        
        # === SUCCESS CHECK ===
        if guaranteed_profit > 0 and current_pair_cost < TARGET_PAIR_COST:
            return False, 0, f"✅ DONE! profit=${guaranteed_profit:.2f}, pair=${current_pair_cost:.3f}"
        
        # === NEED TO IMPROVE ===
        # RULE 1: Don't exceed ratio of 1.3
        if ratio > 1.3:
            return False, 0, f"⛔ Ratio {ratio:.2f}x - need to buy {other_side}"
        
        # RULE 2: If we're the lagging side, buy to catch up (increases min_qty!)
        if ratio < 0.95:
            qty_to_balance = other_qty - my_qty
            max_spend = min(self.cash * 0.6, qty_to_balance * price, remaining_budget)
            qty = max_spend / price
            
            if qty * price >= self.min_trade_size:
                new_locked = self.locked_profit_after_buy(side, price, qty)
                new_ratio = (my_qty + qty) / other_qty
                return True, qty, f"⚖️ BALANCE: ratio {ratio:.2f}→{new_ratio:.2f}, locked ${guaranteed_profit:.2f}→${new_locked:.2f}"
        
        # RULE 3: If pair_cost >= TARGET ($0.97), only buy if it reduces pair_cost
        if current_pair_cost >= TARGET_PAIR_COST:
            new_avg, new_pair_cost = self.simulate_buy(side, price, 10)
            
            if new_pair_cost >= current_pair_cost:
                return False, 0, f"⏳ pair=${current_pair_cost:.3f} (need <${TARGET_PAIR_COST}), price ${price:.3f} won't help"
            
            # Good! This trade reduces pair_cost toward target
            max_spend = min(self.cash * 0.4, self.max_single_trade, remaining_budget)
            qty = max_spend / price
            
            if qty * price >= self.min_trade_size:
                new_avg, new_pair_cost = self.simulate_buy(side, price, qty)
                new_locked = self.locked_profit_after_buy(side, price, qty)
                return True, qty, f"📉 REDUCE: pair ${current_pair_cost:.3f}→${new_pair_cost:.3f}, locked ${guaranteed_profit:.2f}→${new_locked:.2f}"
        
        # RULE 4: If pair_cost < TARGET, buy cheap to grow position
        if price <= self.cheap_threshold and ratio <= 1.15:
            max_spend = min(self.cash * 0.3, self.max_single_trade, remaining_budget)
            qty = max_spend / price
            
            if qty * price >= self.min_trade_size:
                new_locked = self.locked_profit_after_buy(side, price, qty)
                if new_locked > guaranteed_profit:
                    return True, qty, f"💰 CHEAP @ ${price:.3f}: locked ${guaranteed_profit:.2f}→${new_locked:.2f}"
        
        return False, 0, f"⏳ pair=${current_pair_cost:.3f} (target <${TARGET_PAIR_COST}), locked=${guaranteed_profit:.2f}, ratio={ratio:.2f}x"
    
    def execute_buy(self, side: str, price: float, qty: float) -> bool:
        cost = price * qty
        if cost > self.cash:
            return False
        
        self.cash -= cost
        self.trade_count += 1
        self.last_trade_time = time.time()
        
        if self.first_trade_time == 0:
            self.first_trade_time = time.time()
        
        if side == 'UP':
            self.qty_up += qty
            self.cost_up += cost
        else:
            self.qty_down += qty
            self.cost_down += cost
        
        return True
    
    def check_and_trade(self, up_price: float, down_price: float, time_to_close: float = None) -> list:
        """Main trading logic - EXACT COPY from web_bot_multi.py"""
        logs = []
        
        if self.market_status != 'open':
            return logs
        
        # === CHECK IF PROFIT IS SECURED ===
        if self.qty_up > 0 and self.qty_down > 0:
            total_spent = self.cost_up + self.cost_down
            min_qty = min(self.qty_up, self.qty_down)
            fees = self.calculate_total_fees()
            locked = min_qty - total_spent - fees
            
            # ✅ PROFIT SECURED - STOP ALL TRADING!
            if locked > 0:
                return logs
        
        # === REBALANCE if ratio too high ===
        if self.qty_up > 0 and self.qty_down > 0:
            ratio_up = self.qty_up / self.qty_down
            ratio_down = self.qty_down / self.qty_up
            
            if ratio_up > self.rebalance_trigger:
                should, qty, reason = self.should_buy('DOWN', down_price, up_price, is_rebalance=True, time_to_close=time_to_close)
                if should:
                    if self.execute_buy('DOWN', down_price, qty):
                        logs.append({'text': f'📉 [{self.asset.upper()}] {reason}', 'type': 'buy'})
                return logs
            
            if ratio_down > self.rebalance_trigger:
                should, qty, reason = self.should_buy('UP', up_price, down_price, is_rebalance=True, time_to_close=time_to_close)
                if should:
                    if self.execute_buy('UP', up_price, qty):
                        logs.append({'text': f'📈 [{self.asset.upper()}] {reason}', 'type': 'buy'})
                return logs
        
        # === PRIORITY: HEDGE if we only have one side! ===
        if self.qty_up > 0 and self.qty_down == 0:
            should, qty, reason = self.should_buy('DOWN', down_price, up_price, time_to_close=time_to_close)
            if should:
                if self.execute_buy('DOWN', down_price, qty):
                    logs.append({'text': f'📉 [{self.asset.upper()}] {reason}', 'type': 'buy'})
            return logs
        
        if self.qty_down > 0 and self.qty_up == 0:
            should, qty, reason = self.should_buy('UP', up_price, down_price, time_to_close=time_to_close)
            if should:
                if self.execute_buy('UP', up_price, qty):
                    logs.append({'text': f'📈 [{self.asset.upper()}] {reason}', 'type': 'buy'})
            return logs
        
        # === Normal trading when both sides have positions ===
        if up_price < down_price:
            should_buy_up, qty_up, reason = self.should_buy('UP', up_price, down_price, time_to_close=time_to_close)
            if should_buy_up:
                if self.execute_buy('UP', up_price, qty_up):
                    logs.append({'text': f'📈 [{self.asset.upper()}] {reason}', 'type': 'buy'})
            
            should_buy_down, qty_down, reason = self.should_buy('DOWN', down_price, up_price, time_to_close=time_to_close)
            if should_buy_down:
                if self.execute_buy('DOWN', down_price, qty_down):
                    logs.append({'text': f'📉 [{self.asset.upper()}] {reason}', 'type': 'buy'})
        else:
            should_buy_down, qty_down, reason = self.should_buy('DOWN', down_price, up_price, time_to_close=time_to_close)
            if should_buy_down:
                if self.execute_buy('DOWN', down_price, qty_down):
                    logs.append({'text': f'📉 [{self.asset.upper()}] {reason}', 'type': 'buy'})
            
            should_buy_up, qty_up, reason = self.should_buy('UP', up_price, down_price, time_to_close=time_to_close)
            if should_buy_up:
                if self.execute_buy('UP', up_price, qty_up):
                    logs.append({'text': f'📈 [{self.asset.upper()}] {reason}', 'type': 'buy'})
        
        return logs
    
    def resolve(self, outcome: str) -> float:
        """Resolve market with given outcome"""
        self.market_status = 'resolved'
        self.resolution_outcome = outcome
        
        if outcome == 'UP':
            self.payout = self.qty_up
        else:
            self.payout = self.qty_down
        
        total_cost = self.cost_up + self.cost_down
        self.final_pnl = self.payout - total_cost
        self.cash += self.payout
        
        return self.final_pnl
    
    def get_state(self) -> dict:
        return {
            'qty_up': self.qty_up,
            'qty_down': self.qty_down,
            'cost_up': self.cost_up,
            'cost_down': self.cost_down,
            'avg_up': self.avg_up,
            'avg_down': self.avg_down,
            'pair_cost': self.pair_cost,
            'locked_profit': self.locked_profit,
            'best_case_profit': self.best_case_profit,
            'qty_ratio': self.qty_ratio,
            'market_status': self.market_status,
            'resolution_outcome': self.resolution_outcome,
            'final_pnl': self.final_pnl,
            'payout': self.payout
        }
    
    def reset(self):
        self.qty_up = 0.0
        self.qty_down = 0.0
        self.cost_up = 0.0
        self.cost_down = 0.0
        self.trade_count = 0
        self.market_status = 'open'
        self.resolution_outcome = None
        self.final_pnl = None
        self.payout = 0.0
        self.last_trade_time = 0
        self.first_trade_time = 0


class SimulatorBot:
    """Simulator with manual price control"""
    
    def __init__(self):
        self.starting_balance = 1000.0
        self.cash_ref = {'balance': self.starting_balance}
        self.websockets = set()
        self.running = True
        
        # Manual prices (pair cost = $1.01 like real market)
        self.prices = {
            'btc': {'up': 0.50, 'down': 0.51},
            'eth': {'up': 0.50, 'down': 0.51}
        }
        
        # Market state
        self.market_active = False
        self.market_start_time = None
        self.market_duration = 900  # 15 minutes
        
        # Traders
        self.traders = {
            'btc': SimulatedTrader(self.cash_ref, 'btc'),
            'eth': SimulatedTrader(self.cash_ref, 'eth')
        }
        
        # Pending logs to send to UI
        self.pending_logs = []
    
    def reset(self):
        self.cash_ref['balance'] = self.starting_balance
        self.market_active = False
        self.market_start_time = None
        for trader in self.traders.values():
            trader.reset()
        self.pending_logs.append({'text': '🔄 Bot reset to initial state', 'type': 'info'})
    
    def start_market(self):
        self.market_active = True
        self.market_start_time = time.time()
        for trader in self.traders.values():
            trader.reset()
            trader.market_status = 'open'
        self.pending_logs.append({'text': '🚀 New 15-minute market started!', 'type': 'info'})
    
    def end_market(self):
        if not self.market_active:
            return
        
        self.market_active = False
        
        for asset, trader in self.traders.items():
            if trader.market_status == 'open':
                # Determine winner based on prices
                up_price = self.prices[asset]['up']
                down_price = self.prices[asset]['down']
                outcome = 'UP' if up_price > down_price else 'DOWN'
                pnl = trader.resolve(outcome)
                self.pending_logs.append({
                    'text': f'🏁 [{asset.upper()}] Market ended: {outcome} won | PnL: ${pnl:+.2f}',
                    'type': 'profit' if pnl >= 0 else 'info'
                })
    
    def get_time_remaining(self) -> float:
        if not self.market_active or not self.market_start_time:
            return 0
        elapsed = time.time() - self.market_start_time
        return max(0, self.market_duration - elapsed)
    
    async def broadcast(self, data):
        disconnected = set()
        for ws in self.websockets:
            try:
                await ws.send_str(json.dumps(data))
            except:
                disconnected.add(ws)
        self.websockets -= disconnected
    
    async def data_loop(self):
        while self.running:
            try:
                # Check if market has ended
                if self.market_active and self.get_time_remaining() <= 0:
                    self.end_market()
                
                # Run trading logic if market is active
                if self.market_active:
                    time_remaining = self.get_time_remaining()
                    for asset, trader in self.traders.items():
                        logs = trader.check_and_trade(
                            self.prices[asset]['up'],
                            self.prices[asset]['down'],
                            time_remaining
                        )
                        self.pending_logs.extend(logs)
                
                # Calculate true balance
                position_value = 0
                for trader in self.traders.values():
                    position_value += min(trader.qty_up, trader.qty_down)
                true_balance = self.cash_ref['balance'] + position_value
                
                # Build market data
                markets_data = {}
                for asset, trader in self.traders.items():
                    state = trader.get_state()
                    state['up_price'] = self.prices[asset]['up']
                    state['down_price'] = self.prices[asset]['down']
                    markets_data[asset] = state
                
                data = {
                    'starting_balance': self.starting_balance,
                    'cash': self.cash_ref['balance'],
                    'true_balance': true_balance,
                    'market_active': self.market_active,
                    'time_remaining': self.get_time_remaining(),
                    'markets': markets_data,
                    'log_messages': self.pending_logs
                }
                
                await self.broadcast(data)
                self.pending_logs = []
                
            except Exception as e:
                print(f"Error in data loop: {e}")
            
            await asyncio.sleep(0.5)
    
    async def index_handler(self, request):
        return web.Response(text=HTML_TEMPLATE, content_type='text/html')
    
    async def websocket_handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        
        self.websockets.add(ws)
        print(f"WebSocket connected. Total: {len(self.websockets)}")
        
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        action = data.get('action')
                        
                        if action == 'set_price':
                            asset = data.get('asset')
                            if asset in self.prices:
                                self.prices[asset]['up'] = data.get('up', 0.5)
                                self.prices[asset]['down'] = data.get('down', 0.5)
                        
                        elif action == 'start_market':
                            self.start_market()
                        
                        elif action == 'end_market':
                            self.end_market()
                        
                        elif action == 'reset':
                            self.reset()
                    
                    except json.JSONDecodeError:
                        pass
        finally:
            self.websockets.discard(ws)
            print(f"WebSocket disconnected. Total: {len(self.websockets)}")
        
        return ws
    
    async def run(self):
        app = web.Application()
        app.router.add_get('/', self.index_handler)
        app.router.add_get('/ws', self.websocket_handler)
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', 8080)
        
        print("🧪 Simulator Bot starting...")
        print("🌐 Open http://localhost:8080 in your browser")
        print("📊 Use sliders to control prices manually")
        print("Press Ctrl+C to stop\n")
        
        await site.start()
        
        try:
            await self.data_loop()
        except asyncio.CancelledError:
            pass
        finally:
            self.running = False
            await runner.cleanup()


async def main():
    bot = SimulatorBot()
    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\n👋 Simulator stopped")


if __name__ == "__main__":
    asyncio.run(main())
