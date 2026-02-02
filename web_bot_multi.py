#!/usr/bin/env python3
"""
Polymarket Multi-Market Bot - BTC, ETH, SOL, XRP Up/Down Tracker
Web-based interface with real-time updates via WebSocket.
Gabagool v4 Strategy with auto market discovery.
"""

import asyncio
import aiohttp
import json
import time
from datetime import datetime, timezone
from typing import Optional, Dict, List
from aiohttp import web
import os

# Supported assets
SUPPORTED_ASSETS = ['btc', 'eth']

# Manual markets to track (leave empty for auto-discovery)
MANUAL_MARKETS = []

# HTML Template
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 Polymarket Multi-Market Bot</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            background-color: #0c0c0c;
            color: #ffffff;
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            padding: 20px;
            min-height: 100vh;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            border: 2px solid #3b82f6;
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
        
        .header h1 {
            color: #3b82f6;
            font-size: 24px;
            margin-bottom: 5px;
        }
        
        .global-stats {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin-bottom: 20px;
            padding: 15px;
            background: #1a1a2e;
            border-radius: 8px;
            border: 1px solid #333;
        }
        
        .global-stat {
            text-align: center;
        }
        
        .global-stat .label {
            color: #888;
            font-size: 12px;
        }
        
        .global-stat .value {
            font-size: 24px;
            font-weight: bold;
        }
        
        .profit { color: #22c55e; }
        .loss { color: #ef4444; }
        .neutral { color: #3b82f6; }
        
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
        
        .market-card.resolved {
            opacity: 0.7;
            border-color: #555;
        }
        
        .market-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
            padding-bottom: 10px;
            border-bottom: 1px solid #333;
        }
        
        .asset-badge {
            padding: 4px 12px;
            border-radius: 4px;
            font-weight: bold;
            font-size: 14px;
        }
        
        .asset-btc { background: #f7931a; color: #000; }
        .asset-eth { background: #627eea; color: #fff; }
        .asset-sol { background: #9945ff; color: #fff; }
        .asset-xrp { background: #23292f; color: #fff; }
        
        .market-status {
            font-size: 12px;
            padding: 2px 8px;
            border-radius: 4px;
        }

        .sell-mode-badge {
            font-size: 11px;
            padding: 2px 6px;
            border-radius: 4px;
            margin-left: 6px;
        }

        .sell-mode-on { background: #ef4444; color: #fff; }
        .sell-mode-off { background: #374151; color: #e5e7eb; }
        
        .status-open { background: #22c55e; color: #000; }
        .status-closed { background: #f59e0b; color: #000; }
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
        
        .price-label {
            font-size: 12px;
            color: #888;
        }
        
        .price-value {
            font-size: 20px;
            font-weight: bold;
        }
        
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
        
        .holding-label {
            color: #888;
        }
        
        .holding-value {
            font-weight: bold;
            font-size: 14px;
        }
        
        .market-pnl {
            text-align: center;
            margin-top: 10px;
            padding: 10px;
            background: #1a1a2e;
            border-radius: 4px;
        }
        
        .history-section {
            margin-top: 20px;
        }
        
        .history-section h2 {
            color: #3b82f6;
            margin-bottom: 10px;
            font-size: 18px;
        }
        
        .history-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
        }
        
        .history-table th,
        .history-table td {
            padding: 8px 12px;
            text-align: left;
            border-bottom: 1px solid #333;
        }
        
        .history-table th {
            background: #1a1a2e;
            color: #888;
        }
        
        .history-table tr:hover {
            background: #1a1a2e;
        }
        
        .connection-status {
            position: fixed;
            top: 10px;
            right: 10px;
            padding: 5px 10px;
            border-radius: 4px;
            font-size: 12px;
        }
        
        .connected { background: #22c55e; color: #000; }
        .disconnected { background: #ef4444; color: #fff; }
    </style>
</head>
<body>
    <div class="connection-status disconnected" id="connection-status">Disconnected</div>
    
    <div class="container">
        <div class="header">
            <h1>🤖 Polymarket Multi-Market Bot</h1>
            <div style="color: #888; font-size: 12px;">
                Gabagool v4 Strategy | Auto Market Discovery | 
                <span id="current-time">--:--:--</span>
            </div>
            <div style="margin-top: 10px;">
                <button id="pause-btn" onclick="togglePause()" style="padding: 8px 16px; margin-right: 10px; background: #f59e0b; border: none; border-radius: 4px; color: #000; font-weight: bold; cursor: pointer;">⏸️ PAUSE</button>
                <button id="reset-btn" onclick="resetBot()" style="padding: 8px 16px; background: #ef4444; border: none; border-radius: 4px; color: #fff; font-weight: bold; cursor: pointer;">🔄 RESET</button>
            </div>
        </div>
        
        <div class="global-stats">
            <div class="global-stat">
                <div class="label">Starting Balance</div>
                <div class="value neutral">$<span id="starting-balance">1000.00</span></div>
            </div>
            <div class="global-stat">
                <div class="label">True Balance</div>
                <div class="value neutral">$<span id="current-balance">1000.00</span></div>
            </div>
            <div class="global-stat">
                <div class="label">Total PnL</div>
                <div class="value" id="total-pnl">$0.00</div>
            </div>
            <div class="global-stat">
                <div class="label">Markets Resolved</div>
                <div class="value neutral"><span id="markets-resolved">0</span></div>
            </div>
        </div>
        
        <div class="asset-stats" style="margin-bottom: 20px;">
            <h2 style="color: #3b82f6; margin-bottom: 10px;">📊 W/D/L per Asset</h2>
            <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px;" id="asset-wdl-stats">
                <div class="asset-wdl-card" style="background: #1a1a2e; padding: 12px; border-radius: 8px; text-align: center;">
                    <span class="asset-badge asset-btc">BTC</span>
                    <div style="margin-top: 8px; font-size: 12px;">
                        <span class="profit">W: --</span> | 
                        <span style="color: #888;">D: --</span> | 
                        <span class="loss">L: --</span>
                    </div>
                </div>
                <div class="asset-wdl-card" style="background: #1a1a2e; padding: 12px; border-radius: 8px; text-align: center;">
                    <span class="asset-badge asset-eth">ETH</span>
                    <div style="margin-top: 8px; font-size: 12px;">
                        <span class="profit">W: --</span> | 
                        <span style="color: #888;">D: --</span> | 
                        <span class="loss">L: --</span>
                    </div>
                </div>
            </div>
        </div>
        
        <h2 style="color: #3b82f6; margin-bottom: 15px;">📊 Active Markets</h2>
        <div class="markets-grid" id="active-markets">
            <div style="color: #888; text-align: center; padding: 40px; grid-column: span 2;">
                Searching for active markets...
            </div>
        </div>
        
        <div class="history-section">
            <h2>📜 Resolved Markets History</h2>
            <table class="history-table">
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Asset</th>
                        <th>Market</th>
                        <th>Outcome</th>
                        <th>Qty UP</th>
                        <th>Qty DOWN</th>
                        <th>Pair Cost</th>
                        <th>Payout</th>
                        <th>PnL</th>
                    </tr>
                </thead>
                <tbody id="history-body">
                    <tr>
                        <td colspan="9" style="text-align: center; color: #888;">No resolved markets yet</td>
                    </tr>
                </tbody>
            </table>
        </div>
        
        <div class="history-section">
            <h2>📊 Trade Log</h2>
            <table class="history-table">
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Asset</th>
                        <th>Side</th>
                        <th>Price</th>
                        <th>Qty</th>
                        <th>Cost</th>
                        <th>Pair Cost</th>
                    </tr>
                </thead>
                <tbody id="trade-log-body">
                    <tr>
                        <td colspan="7" style="text-align: center; color: #888;">No trades yet</td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>
    
    <script>
        let ws;
        let reconnectTimeout;
        
        function togglePause() {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ action: 'pause' }));
            }
        }
        
        function resetBot() {
            if (confirm('Are you sure you want to reset the bot? This will clear all data and reset balance to $1000.')) {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ action: 'reset' }));
                }
            }
        }
        
        function connect() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(protocol + '//' + window.location.host + '/ws');
            
            ws.onopen = () => {
                document.getElementById('connection-status').textContent = 'Connected';
                document.getElementById('connection-status').className = 'connection-status connected';
            };
            
            ws.onclose = () => {
                document.getElementById('connection-status').textContent = 'Disconnected';
                document.getElementById('connection-status').className = 'connection-status disconnected';
                reconnectTimeout = setTimeout(connect, 2000);
            };
            
            ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                updateUI(data);
            };
        }
        
        function updateUI(data) {
            // Update global stats
            document.getElementById('starting-balance').textContent = data.starting_balance.toFixed(2);
            document.getElementById('current-balance').textContent = data.true_balance.toFixed(2);
            
            const totalPnl = data.true_balance - data.starting_balance;
            const pnlEl = document.getElementById('total-pnl');
            pnlEl.textContent = (totalPnl >= 0 ? '+' : '') + '$' + totalPnl.toFixed(2);
            pnlEl.className = 'value ' + (totalPnl >= 0 ? 'profit' : 'loss');
            
            document.getElementById('markets-resolved').textContent = data.history.length;
            
            // Update W/D/L per asset
            if (data.asset_wdl) {
                const wdlContainer = document.getElementById('asset-wdl-stats');
                let wdlHtml = '';
                const assets = ['btc', 'eth'];
                for (const asset of assets) {
                    const stats = data.asset_wdl[asset] || { wins: 0, draws: 0, losses: 0, total: 0, total_pnl: 0 };
                    const winPct = stats.total > 0 ? ((stats.wins / stats.total) * 100).toFixed(0) : '--';
                    const drawPct = stats.total > 0 ? ((stats.draws / stats.total) * 100).toFixed(0) : '--';
                    const lossPct = stats.total > 0 ? ((stats.losses / stats.total) * 100).toFixed(0) : '--';
                    const pnlClass = stats.total_pnl >= 0 ? 'profit' : 'loss';
                    const pnlSign = stats.total_pnl >= 0 ? '+' : '';
                    
                    wdlHtml += `
                        <div class="asset-wdl-card" style="background: #1a1a2e; padding: 12px; border-radius: 8px; text-align: center;">
                            <span class="asset-badge asset-${asset}">${asset.toUpperCase()}</span>
                            <div style="margin-top: 8px; font-size: 12px;">
                                <span class="profit">W: ${winPct}%</span> | 
                                <span style="color: #888;">D: ${drawPct}%</span> | 
                                <span class="loss">L: ${lossPct}%</span>
                            </div>
                            <div style="font-size: 10px; color: #666; margin-top: 4px;">
                                (${stats.wins}/${stats.draws}/${stats.losses}) n=${stats.total}
                            </div>
                            <div style="margin-top: 6px; font-size: 14px; font-weight: bold;" class="${pnlClass}">
                                ${pnlSign}$${stats.total_pnl.toFixed(2)}
                            </div>
                        </div>
                    `;
                }
                wdlContainer.innerHTML = wdlHtml;
            }
            
            // Update active markets
            const marketsGrid = document.getElementById('active-markets');
            if (Object.keys(data.active_markets).length === 0) {
                marketsGrid.innerHTML = '<div style="color: #888; text-align: center; padding: 40px; grid-column: span 2;">Searching for active markets...</div>';
            } else {
                let html = '';
                for (const [slug, market] of Object.entries(data.active_markets)) {
                    const pt = market.paper_trader;
                    const asset = market.asset.toUpperCase();
                    const statusClass = pt.market_status === 'open' ? 'status-open' : 
                                       pt.market_status === 'resolved' ? 'status-resolved' : 'status-closed';
                    const sellModeClass = pt.sell_mode ? 'sell-mode-on' : 'sell-mode-off';
                    const sellModeLabel = pt.sell_mode ? 'SELL MODE' : 'SELL MODE: OFF';
                    
                    const lockedPnl = Math.min(pt.qty_up, pt.qty_down) - (pt.cost_up + pt.cost_down);
                    
                    html += `
                        <div class="market-card ${pt.market_status === 'resolved' ? 'resolved' : ''}">
                            <div class="market-header">
                                <span class="asset-badge asset-${market.asset}">${asset}</span>
                                <div>
                                    <span class="market-status ${statusClass}">${pt.market_status.toUpperCase()}</span>
                                    <span class="sell-mode-badge ${sellModeClass}">${sellModeLabel}</span>
                                </div>
                            </div>
                            <div style="font-size: 11px; color: #888; margin-bottom: 6px;">
                                ${market.window_time || slug}
                            </div>
                            ${pt.sell_mode ? '<div style="margin-bottom: 8px; padding: 6px 8px; border: 1px solid #ef4444; border-radius: 6px; color: #fecaca; font-weight: bold; background: rgba(239, 68, 68, 0.2);">🚨 SELL MODE ACTIVE</div>' : ''}
                            <div class="prices-row">
                                <div class="price-box price-up">
                                    <div class="price-label">UP</div>
                                    <div class="price-value">$${market.up_price?.toFixed(3) || '-.--'}</div>
                                </div>
                                <div class="price-box price-down">
                                    <div class="price-label">DOWN</div>
                                    <div class="price-value">$${market.down_price?.toFixed(3) || '-.--'}</div>
                                </div>
                            </div>
                            <div class="holdings-row">
                                <div class="holding-item">
                                    <div class="holding-label">Qty UP</div>
                                    <div class="holding-value">${pt.qty_up.toFixed(1)}</div>
                                    <div class="holding-label" style="margin-top: 4px;">Avg: $${pt.avg_up.toFixed(3)}</div>
                                    <div class="holding-label" style="color: #f59e0b;">Spent: $${pt.cost_up.toFixed(2)}</div>
                                </div>
                                <div class="holding-item">
                                    <div class="holding-label">Qty DOWN</div>
                                    <div class="holding-value">${pt.qty_down.toFixed(1)}</div>
                                    <div class="holding-label" style="margin-top: 4px;">Avg: $${pt.avg_down.toFixed(3)}</div>
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
                                    <div class="holding-value">$${pt.pair_cost.toFixed(3)}</div>
                                </div>
                                <div class="holding-item">
                                    <div class="holding-label">Min Payout</div>
                                    <div class="holding-value" style="color: #22c55e;">$${Math.min(pt.qty_up, pt.qty_down).toFixed(2)}</div>
                                </div>
                            </div>
                            <div class="market-pnl">
                                <span style="color: #888;">Locked PnL: </span>
                                <span class="${lockedPnl >= 0 ? 'profit' : 'loss'}" style="font-weight: bold;">
                                    ${lockedPnl >= 0 ? '+' : ''}$${lockedPnl.toFixed(2)}
                                </span>
                                ${pt.market_status === 'resolved' ? 
                                    `<br><span style="color: #3b82f6;">Outcome: ${pt.resolution_outcome} | Final: ${pt.final_pnl >= 0 ? '+' : ''}$${pt.final_pnl?.toFixed(2)}</span>` 
                                    : ''}
                            </div>
                        </div>
                    `;
                }
                marketsGrid.innerHTML = html;
            }
            
            // Update history
            const historyBody = document.getElementById('history-body');
            if (data.history.length === 0) {
                historyBody.innerHTML = '<tr><td colspan="9" style="text-align: center; color: #888;">No resolved markets yet</td></tr>';
            } else {
                let html = '';
                for (const h of data.history.slice().reverse()) {
                    const pnlClass = h.pnl >= 0 ? 'profit' : 'loss';
                    html += `
                        <tr>
                            <td>${h.resolved_at}</td>
                            <td><span class="asset-badge asset-${h.asset}" style="font-size: 10px;">${h.asset.toUpperCase()}</span></td>
                            <td style="font-size: 11px;">${h.slug}</td>
                            <td>${h.outcome}</td>
                            <td>${h.qty_up.toFixed(1)}</td>
                            <td>${h.qty_down.toFixed(1)}</td>
                            <td>$${h.pair_cost.toFixed(3)}</td>
                            <td>$${h.payout.toFixed(2)}</td>
                            <td class="${pnlClass}">${h.pnl >= 0 ? '+' : ''}$${h.pnl.toFixed(2)}</td>
                        </tr>
                    `;
                }
                historyBody.innerHTML = html;
            }
            
            // Update trade log
            const tradeLogBody = document.getElementById('trade-log-body');
            if (!data.trade_log || data.trade_log.length === 0) {
                tradeLogBody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: #888;">No trades yet</td></tr>';
            } else {
                let html = '';
                for (const t of data.trade_log.slice().reverse()) {
                    const sideClass = t.side === 'UP' ? 'profit' : 'loss';
                    html += `
                        <tr>
                            <td>${t.time}</td>
                            <td><span class="asset-badge asset-${t.asset.toLowerCase()}" style="font-size: 10px;">${t.asset}</span></td>
                            <td class="${sideClass}">${t.side}</td>
                            <td>$${t.price.toFixed(3)}</td>
                            <td>${t.qty.toFixed(1)}</td>
                            <td>$${t.cost.toFixed(2)}</td>
                            <td>$${t.pair_cost.toFixed(3)}</td>
                        </tr>
                    `;
                }
                tradeLogBody.innerHTML = html;
            }
            
            // Update pause button
            if (data.paused !== undefined) {
                const pauseBtn = document.getElementById('pause-btn');
                if (data.paused) {
                    pauseBtn.textContent = '▶️ RESUME';
                    pauseBtn.style.background = '#22c55e';
                } else {
                    pauseBtn.textContent = '⏸️ PAUSE';
                    pauseBtn.style.background = '#f59e0b';
                }
            }
        }
        
        // Update time every second
        setInterval(() => {
            const now = new Date();
            document.getElementById('current-time').textContent = now.toISOString().substr(11, 8);
        }, 1000);
        
        connect();
    </script>
</body>
</html>
"""


class PaperTrader:
    """Gabagool v7 paper trading bot - RECOVERY MODE ENABLED"""
    
    def __init__(self, cash_ref: dict, market_slug: str):
        """
        cash_ref: A dict with 'balance' key that's shared across all traders
        market_slug: The market this trader is for
        """
        self.cash_ref = cash_ref  # Shared cash balance
        self.market_slug = market_slug
        self.qty_up = 0.0
        self.qty_down = 0.0
        self.cost_up = 0.0
        self.cost_down = 0.0
        self.trade_log = []
        self.trade_count = 0
        self.market_status = 'open'
        self.resolution_outcome = None
        self.final_pnl = None
        self.payout = 0.0
        self.starting_balance = 1000.0
        
        # === GABAGOOL v7 - RECOVERY MODE STRATEGY ===
        # Core principle: Get pair_cost < $1.00 by ANY means necessary
        
        # Trading strategy parameters
        self.cheap_threshold = 0.45      # What we consider "cheap"
        self.very_cheap_threshold = 0.38 # Very cheap - accumulate
        self.force_balance_threshold = 0.52  # Max price to pay when balancing
        self.max_balance_price = 0.60    # Absolute max for emergency balance
        self.target_pair_cost = 0.95     # Ideal pair cost target
        self.max_pair_cost = 0.995       # CRITICAL: Never buy if this would push pair over
        
        # Position sizing
        self.min_trade_size = 3.0
        self.max_single_trade = 15.0
        self.cooldown_seconds = 4
        self.last_trade_time = 0
        self.first_trade_time = 0
        self.initial_trade_usd = 35.0
        self.max_position_pct = 0.50     # Max 50% of balance per market
        self.force_balance_after_seconds = 120
        
        # === RECOVERY MODE PARAMETERS ===
        # When pair_cost > $1.00, we need to be aggressive to fix it
        self.max_qty_ratio = 1.35       # Normal max imbalance (35%)
        self.emergency_ratio = 2.0      # Allow HIGH imbalance when fixing pair_cost > $1.00
        self.recovery_ratio = 2.5       # Max ratio when actively recovering (EXTREME)
        self.target_qty_ratio = 1.0     # Perfect balance
        self.rebalance_trigger = 1.15   # Start rebalancing when ratio exceeds this
        
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
        if self.qty_up == 0 or self.qty_down == 0:
            return 0.0
        return self.avg_up + self.avg_down
    
    @property
    def locked_profit(self) -> float:
        min_qty = min(self.qty_up, self.qty_down)
        total_cost = self.cost_up + self.cost_down
        return min_qty - total_cost

    def update_sell_mode(self, market_elapsed: Optional[float] = None):
        if self.sell_mode:
            return
        if market_elapsed is None:
            return
        # Only trigger sell mode if we have positions but no locked profit
        has_positions = self.qty_up > 0 or self.qty_down > 0
        if has_positions and market_elapsed >= self.sell_mode_trigger_seconds and self.locked_profit <= 0:
            self.sell_mode = True
            print(f"🚨 SELL MODE ACTIVE [{self.market_slug}] (no locked profit after 5m)")

    def unrealized_pnl(self, up_price: float, down_price: float) -> float:
        total_cost = self.cost_up + self.cost_down
        current_value = (self.qty_up * up_price) + (self.qty_down * down_price)
        return current_value - total_cost

    def improves_pair_cost(self, side: str, price: float, qty: float) -> bool:
        if self.qty_up == 0 or self.qty_down == 0:
            return True
        _, new_pair_cost = self.simulate_buy(side, price, qty)
        return new_pair_cost < self.pair_cost

    def improves_locked_profit(self, side: str, price: float, qty: float) -> bool:
        return self.locked_profit_after_buy(side, price, qty) > self.locked_profit

    def locked_profit_after_buy(self, side: str, price: float, qty: float) -> float:
        cost = price * qty
        new_qty_up = self.qty_up + qty if side == 'UP' else self.qty_up
        new_qty_down = self.qty_down + qty if side == 'DOWN' else self.qty_down
        new_cost_up = self.cost_up + cost if side == 'UP' else self.cost_up
        new_cost_down = self.cost_down + cost if side == 'DOWN' else self.cost_down
        if new_qty_up == 0 or new_qty_down == 0:
            return 0.0
        total_cost = new_cost_up + new_cost_down
        return min(new_qty_up, new_qty_down) - total_cost

    def sell_mode_allows_buy(self, side: str, price: float, qty: float) -> tuple:
        if not self.sell_mode:
            return True, ""
        if self.locked_profit_after_buy(side, price, qty) > 0:
            return True, ""
        return False, "Sell mode: profit not lockable"

    def execute_sell_all(self, up_price: float, down_price: float, timestamp: str, reason: str) -> bool:
        proceeds = 0.0
        sold_any = False

        if self.qty_up > 0 and up_price > 0:
            proceeds += self.qty_up * up_price
            self.trade_log.append({
                'time': timestamp,
                'side': 'SELL',
                'token': 'UP',
                'price': up_price,
                'qty': self.qty_up,
                'cost': -(self.qty_up * up_price),
                'note': reason
            })
            self.qty_up = 0.0
            self.cost_up = 0.0
            sold_any = True

        if self.qty_down > 0 and down_price > 0:
            proceeds += self.qty_down * down_price
            self.trade_log.append({
                'time': timestamp,
                'side': 'SELL',
                'token': 'DOWN',
                'price': down_price,
                'qty': self.qty_down,
                'cost': -(self.qty_down * down_price),
                'note': reason
            })
            self.qty_down = 0.0
            self.cost_down = 0.0
            sold_any = True

        if not sold_any:
            return False

        self.cash += proceeds
        self.trade_count += 1
        self.last_trade_time = time.time()

        if len(self.trade_log) > 20:
            self.trade_log = self.trade_log[-20:]

        return True
    
    def simulate_buy(self, side: str, price: float, qty: float) -> tuple:
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
    
    def calculate_smart_hedge(self, hedge_price: float) -> dict:
        """
        Beregner smart hedge når pair_cost > 1.0
        
        Strategi: Kjøp FLERE shares på hedge-siden slik at:
        - Hvis hedge-siden vinner: Vi går i PLUSS
        - Hvis original-siden vinner: Vi går i MINUS (men begrenset)
        
        Formel for break-even på hedge-siden:
        qty_hedge = existing_cost / (1 - hedge_price)
        
        For å gå i PLUSS, kjøper vi litt mer enn break-even.
        """
        # Determine which side we're hedging
        if self.qty_up > 0 and self.qty_down == 0:
            existing_qty = self.qty_up
            existing_cost = self.cost_up
            existing_avg = self.avg_up
            hedge_side = 'DOWN'
        elif self.qty_down > 0 and self.qty_up == 0:
            existing_qty = self.qty_down
            existing_cost = self.cost_down
            existing_avg = self.avg_down
            hedge_side = 'UP'
        else:
            return {'viable': False, 'reason': 'Need unhedged position'}
        
        # Can't smart hedge if price >= 1.0
        if hedge_price >= 1.0:
            return {'viable': False, 'reason': 'Hedge price too high'}
        
        # Calculate break-even hedge quantity
        # If hedge wins: qty_hedge - existing_cost - (qty_hedge * hedge_price) = 0
        # qty_hedge * (1 - hedge_price) = existing_cost
        # qty_hedge = existing_cost / (1 - hedge_price)
        breakeven_qty = existing_cost / (1 - hedge_price)
        breakeven_cost = breakeven_qty * hedge_price
        
        # Add buffer for profit (10% more shares)
        profit_buffer = 1.10
        smart_qty = breakeven_qty * profit_buffer
        smart_cost = smart_qty * hedge_price
        
        # Calculate outcomes
        total_cost = existing_cost + smart_cost
        
        # If hedge side wins:
        pnl_if_hedge_wins = smart_qty - total_cost
        
        # If original side wins:
        pnl_if_original_wins = existing_qty - total_cost
        
        # Check viability
        result = {
            'viable': False,
            'hedge_side': hedge_side,
            'existing_qty': existing_qty,
            'existing_cost': existing_cost,
            'hedge_price': hedge_price,
            'breakeven_qty': breakeven_qty,
            'smart_qty': smart_qty,
            'smart_cost': smart_cost,
            'total_cost': total_cost,
            'pnl_if_hedge_wins': pnl_if_hedge_wins,
            'pnl_if_original_wins': pnl_if_original_wins,
            'reason': ''
        }
        
        # Check constraints
        if hedge_price > self.smart_hedge_max_price:
            result['reason'] = f'Price ${hedge_price:.2f} > max ${self.smart_hedge_max_price}'
            return result
        
        if smart_cost > self.smart_hedge_max_spend:
            result['reason'] = f'Cost ${smart_cost:.2f} > max ${self.smart_hedge_max_spend}'
            return result
        
        if smart_cost > self.cash * 0.5:  # Don't spend more than 50% of cash
            result['reason'] = f'Cost ${smart_cost:.2f} > 50% of cash'
            return result
        
        if pnl_if_hedge_wins < self.smart_hedge_min_profit:
            result['reason'] = f'Profit ${pnl_if_hedge_wins:.2f} < min ${self.smart_hedge_min_profit}'
            return result
        
        # Check worst case loss is acceptable
        if abs(pnl_if_original_wins) > self.max_loss_per_market * 3:  # Allow 3x max loss for smart hedge
            result['reason'] = f'Worst loss ${pnl_if_original_wins:.2f} too high'
            return result
        
        result['viable'] = True
        result['reason'] = 'Smart hedge viable!'
        return result
    
    def should_buy(self, side: str, price: float, other_price: float, is_rebalance: bool = False, is_emergency: bool = False, time_to_close: float = None) -> tuple:
        """
        GABAGOOL v7 - RECOVERY MODE ENABLED
        
        THE ONLY WAY TO GUARANTEE PROFIT:
        - pair_cost (avg_UP + avg_DOWN) < $1.00
        - qty_UP ≈ qty_DOWN (balanced positions)
        
        RECOVERY MODE: When pair_cost > $1.00, allow high imbalance
        to aggressively cost-average and get pair_cost under $1.00
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
        
        # === FIRST TRADE: Only start if we can get good pair_cost ===
        if my_qty == 0 and other_qty == 0:
            if price > self.cheap_threshold:
                return False, 0, f"First trade needs price < ${self.cheap_threshold}"
            
            potential_pair_cost = price + other_price
            if potential_pair_cost > self.max_pair_cost:
                return False, 0, f"Pair would be ${potential_pair_cost:.2f} > ${self.max_pair_cost} - waiting"
            
            max_spend = min(self.initial_trade_usd, self.max_single_trade, remaining_budget, self.cash)
            qty = max_spend / price
            self.first_trade_time = now
            return True, qty, f"🎯 First trade (pair potential: ${potential_pair_cost:.2f})"
        
        # === CRITICAL: MUST BALANCE TO LOCK PROFIT ===
        if my_qty == 0 and other_qty > 0:
            time_unhedged = now - self.first_trade_time if self.first_trade_time > 0 else 0
            potential_pair_cost = other_avg + price
            
            if time_unhedged > self.force_balance_after_seconds:
                if potential_pair_cost < self.max_pair_cost:
                    price_threshold = self.max_balance_price
                    reason = f"🚨 FORCE BALANCE ({time_unhedged:.0f}s unhedged)"
                else:
                    return False, 0, f"🚨 Pair cost ${potential_pair_cost:.2f} too high even for emergency"
            elif potential_pair_cost < self.target_pair_cost:
                price_threshold = self.force_balance_threshold
                reason = f"✅ GOOD PAIR COST (${potential_pair_cost:.2f})"
            else:
                price_threshold = self.cheap_threshold
                reason = "⏳ Waiting for better price"
            
            if price > price_threshold:
                return False, 0, f"Need {side} < ${price_threshold:.2f} (pair would be ${potential_pair_cost:.2f})"
            
            target_qty = other_qty
            max_spend = min(target_qty * price, self.cash * 0.3, remaining_budget + 20)
            qty = max_spend / price
            
            if qty < target_qty * 0.5:
                qty = max(qty, self.min_trade_size / price)
            return True, qty, reason
        
        # === BOTH SIDES HAVE POSITIONS - OPTIMIZE PAIR COST ===
        current_pair_cost = self.pair_cost
        ratio = my_qty / other_qty if other_qty > 0 else 1.0
        
        # === RECOVERY MODE: When pair_cost > $1.00, be VERY aggressive ===
        recovery_mode = current_pair_cost >= 1.0
        
        # Dynamic ratio limit based on how critical the situation is
        if recovery_mode:
            if current_pair_cost >= 1.05:
                effective_max_ratio = self.recovery_ratio  # 2.5x - extreme
            elif current_pair_cost >= 1.02:
                effective_max_ratio = self.emergency_ratio  # 2.0x - high
            else:
                effective_max_ratio = 1.80
        else:
            effective_max_ratio = self.max_qty_ratio  # 1.35x - normal
        
        if ratio >= effective_max_ratio:
            return False, 0, f"BLOCKED: {side} at max ratio ({ratio:.2f}x, limit {effective_max_ratio:.2f}x)"
        
        max_qty_allowed = other_qty * effective_max_ratio - my_qty
        if max_qty_allowed <= 0:
            return False, 0, "At ratio limit"
        
        # === RECOVERY MODE: AGGRESSIVE COST AVERAGING ===
        if recovery_mode and price < my_avg:
            spend_pct = 0.15 if current_pair_cost >= 1.02 else 0.10
            max_spend = min(self.cash * spend_pct, self.max_single_trade * 2, remaining_budget + 50)
            qty = min(max_spend / price, max_qty_allowed)
            
            if qty * price >= self.min_trade_size:
                new_avg, new_pair_cost = self.simulate_buy(side, price, qty)
                if new_pair_cost < current_pair_cost:
                    improvement = current_pair_cost - new_pair_cost
                    
                    if new_pair_cost < 1.0:
                        return True, qty, f"🎯 RECOVERY SUCCESS: pair ${current_pair_cost:.3f}→${new_pair_cost:.3f} (UNDER $1.00!)"
                    
                    if improvement >= 0.002:
                        return True, qty, f"🚨 RECOVERY: pair ${current_pair_cost:.3f}→${new_pair_cost:.3f} (-${improvement:.3f})"
        
        # === NORMAL MODE: COST AVERAGING ===
        if not recovery_mode and price < my_avg:
            spend_pct = 0.04
            max_spend = min(self.cash * spend_pct, self.max_single_trade, remaining_budget)
            qty = min(max_spend / price, max_qty_allowed)
            
            if qty * price >= self.min_trade_size:
                new_avg, new_pair_cost = self.simulate_buy(side, price, qty)
                if new_pair_cost < current_pair_cost:
                    improvement = current_pair_cost - new_pair_cost
                    if improvement >= 0.003:
                        return True, qty, f"📉 IMPROVE: pair ${current_pair_cost:.3f}→${new_pair_cost:.3f} (-${improvement:.3f})"
        
        # === REBALANCING: Buy lagging side ===
        if ratio < 0.92:
            price_threshold = self.max_balance_price if recovery_mode else self.force_balance_threshold
            if price <= price_threshold:
                spend_pct = 0.10 if recovery_mode else 0.05
                max_spend = min(self.cash * spend_pct, self.max_single_trade, remaining_budget)
                qty = min(max_spend / price, max_qty_allowed)
                
                if qty * price >= self.min_trade_size:
                    new_avg, new_pair_cost = self.simulate_buy(side, price, qty)
                    pair_cost_improving = new_pair_cost < current_pair_cost
                    
                    if recovery_mode and pair_cost_improving:
                        return True, qty, f"🚨 REBALANCE: ratio {ratio:.2f}→{(my_qty+qty)/other_qty:.2f}"
                    elif new_pair_cost <= self.max_pair_cost:
                        return True, qty, f"⚖️ REBALANCE: ratio {ratio:.2f}→{(my_qty+qty)/other_qty:.2f}"
        
        # === CHEAP ACCUMULATION: Very cheap prices ===
        if price < self.very_cheap_threshold and ratio < 1.1:
            spend_pct = 0.08 if recovery_mode else 0.04
            max_spend = min(self.cash * spend_pct, self.max_single_trade, remaining_budget)
            qty = min(max_spend / price, max_qty_allowed)
            
            if qty * price >= self.min_trade_size:
                new_avg, new_pair_cost = self.simulate_buy(side, price, qty)
                pair_cost_improving = new_pair_cost < current_pair_cost
                
                if (recovery_mode and pair_cost_improving) or (new_pair_cost <= self.max_pair_cost):
                    prefix = "🚨" if recovery_mode else "🔥"
                    return True, qty, f"{prefix} CHEAP @ ${price:.3f}"
        
        # === STANDARD BUYING ===
        if ratio <= 1.0 and price < self.cheap_threshold and not recovery_mode:
            max_spend = min(self.cash * 0.03, self.max_single_trade, remaining_budget)
            qty = min(max_spend / price, max_qty_allowed)
            
            if qty * price >= self.min_trade_size:
                new_avg, new_pair_cost = self.simulate_buy(side, price, qty)
                if new_pair_cost <= self.max_pair_cost:
                    return True, qty, f"OK (${price:.3f})"
        
        return False, 0, f"{side} ${price:.3f}: no opportunity"
    
    def execute_buy(self, side: str, price: float, qty: float, timestamp: str):
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
            'time': timestamp,
            'side': 'BUY',
            'token': side,
            'price': price,
            'qty': qty,
            'cost': cost
        })
        
        if len(self.trade_log) > 20:
            self.trade_log = self.trade_log[-20:]
        
        return True
    
    def check_and_trade(self, up_price: float, down_price: float, timestamp: str, time_to_close: float = None, up_bid: Optional[float] = None, down_bid: Optional[float] = None):
        trades_made = []
        market_elapsed = None
        if time_to_close is not None:
            market_elapsed = max(0.0, 900.0 - time_to_close)
        self.update_sell_mode(market_elapsed)
        sell_up_price = up_bid if up_bid and up_bid > 0 else up_price
        sell_down_price = down_bid if down_bid and down_bid > 0 else down_price
        unrealized = self.unrealized_pnl(sell_up_price, sell_down_price)

        if unrealized <= -self.max_loss_per_market and (self.qty_up > 0 or self.qty_down > 0):
            if self.execute_sell_all(sell_up_price, sell_down_price, timestamp, "Max loss"):
                self.market_status = 'closed'
            return trades_made

        if self.sell_mode:
            if unrealized >= self.sell_mode_min_profit:
                if self.execute_sell_all(sell_up_price, sell_down_price, timestamp, "Sell mode profit"):
                    self.market_status = 'closed'
                return trades_made
        
        if self.qty_up > 0 and self.qty_down > 0:
            ratio_up = self.qty_up / self.qty_down
            ratio_down = self.qty_down / self.qty_up
            
            if ratio_up > self.rebalance_trigger:
                should, qty, reason = self.should_buy('DOWN', down_price, up_price, is_rebalance=True, time_to_close=time_to_close)
                if should:
                    if self.execute_buy('DOWN', down_price, qty, timestamp):
                        trades_made.append(('DOWN', down_price, qty))
                return trades_made
            
            if ratio_down > self.rebalance_trigger:
                should, qty, reason = self.should_buy('UP', up_price, down_price, is_rebalance=True, time_to_close=time_to_close)
                if should:
                    if self.execute_buy('UP', up_price, qty, timestamp):
                        trades_made.append(('UP', up_price, qty))
                return trades_made
        
        if up_price < down_price:
            should_buy_up, qty_up, _ = self.should_buy('UP', up_price, down_price, time_to_close=time_to_close)
            if should_buy_up:
                if self.execute_buy('UP', up_price, qty_up, timestamp):
                    trades_made.append(('UP', up_price, qty_up))
            
            should_buy_down, qty_down, _ = self.should_buy('DOWN', down_price, up_price, time_to_close=time_to_close)
            if should_buy_down:
                if self.execute_buy('DOWN', down_price, qty_down, timestamp):
                    trades_made.append(('DOWN', down_price, qty_down))
        else:
            should_buy_down, qty_down, _ = self.should_buy('DOWN', down_price, up_price, time_to_close=time_to_close)
            if should_buy_down:
                if self.execute_buy('DOWN', down_price, qty_down, timestamp):
                    trades_made.append(('DOWN', down_price, qty_down))
            
            should_buy_up, qty_up, _ = self.should_buy('UP', up_price, down_price, time_to_close=time_to_close)
            if should_buy_up:
                if self.execute_buy('UP', up_price, qty_up, timestamp):
                    trades_made.append(('UP', up_price, qty_up))
        
        return trades_made
    
    def resolve_market(self, outcome: str):
        self.market_status = 'resolved'
        self.resolution_outcome = outcome
        
        if outcome == 'UP':
            self.payout = self.qty_up * 1.0
        else:
            self.payout = self.qty_down * 1.0
        
        total_cost = self.cost_up + self.cost_down
        self.final_pnl = self.payout - total_cost
        
        # Add payout back to cash
        self.cash += self.payout
        
        return self.final_pnl
    
    def close_market(self):
        self.market_status = 'closed'
    
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
            'trade_count': self.trade_count,
            'market_status': self.market_status,
            'resolution_outcome': self.resolution_outcome,
            'final_pnl': self.final_pnl,
            'payout': self.payout,
            'sell_mode': self.sell_mode
        }


class MarketTracker:
    """Tracks a single market"""
    
    def __init__(self, slug: str, asset: str, cash_ref: dict):
        self.slug = slug
        self.asset = asset
        self.up_token_id = None
        self.down_token_id = None
        self.window_start = None
        self.window_end = None
        self.up_price = None
        self.down_price = None
        self.last_up_bid = 0.0
        self.last_down_bid = 0.0
        self.paper_trader = PaperTrader(cash_ref, slug)
        self.initialized = False
        self.last_update = 0


class MultiMarketBot:
    GAMMA_API_URL = "https://gamma-api.polymarket.com"
    CLOB_API_URL = "https://clob.polymarket.com"
    
    def __init__(self, starting_balance: float = 1000.0):
        self.starting_balance = starting_balance
        self.cash_ref = {'balance': starting_balance}
        self.active_markets: Dict[str, MarketTracker] = {}
        self.history: List[dict] = []
        self.websockets = set()
        self.running = True
        self.update_count = 0
        self.manual_markets_loaded = False
        self.trade_log: List[dict] = []
        self.paused = False
    
    async def load_manual_markets(self, session: aiohttp.ClientSession):
        """Load manually specified markets"""
        if self.manual_markets_loaded:
            return
        
        self.manual_markets_loaded = True
        
        for slug in MANUAL_MARKETS:
            if slug in self.active_markets:
                continue
            if any(h['slug'] == slug for h in self.history):
                continue
            
            # Determine asset from slug
            asset = None
            for a in SUPPORTED_ASSETS:
                if slug.startswith(f'{a}-updown-15m-'):
                    asset = a
                    break
            
            if not asset:
                print(f"⚠️ Unknown asset in slug: {slug}")
                continue
            
            try:
                url = f"{self.GAMMA_API_URL}/events?slug={slug}"
                async with session.get(url) as response:
                    if response.status == 200:
                        events = await response.json()
                        
                        if not events:
                            print(f"⚠️ Market not found: {slug}")
                            continue
                        
                        event = events[0]
                        markets = event.get('markets', [])
                        
                        up_token = None
                        down_token = None
                        
                        # New format: single market with outcomes array
                        for m in markets:
                            outcomes = m.get('outcomes', [])
                            tokens = m.get('clobTokenIds', [])
                            
                            # Parse tokens if it's a JSON string
                            if isinstance(tokens, str):
                                try:
                                    tokens = json.loads(tokens)
                                except:
                                    tokens = []
                            
                            # Parse outcomes if it's a JSON string
                            if isinstance(outcomes, str):
                                try:
                                    outcomes = json.loads(outcomes)
                                except:
                                    outcomes = []
                            
                            if outcomes and tokens and len(outcomes) >= 2 and len(tokens) >= 2:
                                for i, outcome in enumerate(outcomes):
                                    if outcome.lower() == 'up':
                                        up_token = tokens[i]
                                    elif outcome.lower() == 'down':
                                        down_token = tokens[i]
                            
                            # Fallback: old format with groupItemTitle
                            if not up_token or not down_token:
                                outcome = m.get('groupItemTitle', '').lower()
                                if 'up' in outcome and tokens:
                                    up_token = tokens[0]
                                elif 'down' in outcome and tokens:
                                    down_token = tokens[0]
                        
                        if up_token and down_token:
                            tracker = MarketTracker(slug, asset, self.cash_ref)
                            tracker.up_token_id = up_token
                            tracker.down_token_id = down_token
                            
                            end_date_str = event.get('endDate', '')
                            if end_date_str:
                                try:
                                    tracker.window_end = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                                except:
                                    pass
                            
                            tracker.initialized = True
                            self.active_markets[slug] = tracker
                            print(f"✅ Loaded market: {slug}")
                            print(f"   UP token: {up_token[:20]}...")
                            print(f"   DOWN token: {down_token[:20]}...")
                        else:
                            print(f"⚠️ Missing tokens for: {slug}")
                    else:
                        print(f"⚠️ Failed to fetch {slug}: status {response.status}")
            except Exception as e:
                print(f"Error loading manual market {slug}: {e}")
        
    async def discover_markets(self, session: aiohttp.ClientSession):
        """Discover active markets for all supported assets"""
        # First, load manual markets if any
        await self.load_manual_markets(session)
        
        # Calculate current and next 15-minute windows
        now = int(time.time())
        current_window = (now // 900) * 900  # Current 15-min window start
        next_window = current_window + 900   # Next 15-min window
        
        # Only track one market per asset at a time
        # Check current window first, then next if current is closed
        timestamps_to_check = [current_window, next_window]
        
        for asset in SUPPORTED_ASSETS:
            # Skip if we already have an active market for this asset
            has_active = any(
                t.asset == asset and t.paper_trader.market_status == 'open' 
                for t in self.active_markets.values()
            )
            if has_active:
                continue
            
            # Find one market for this asset
            for ts in timestamps_to_check:
                slug = f"{asset}-updown-15m-{ts}"
                
                # Skip if already tracking or in history
                if slug in self.active_markets:
                    break  # Already have this one
                if any(h['slug'] == slug for h in self.history):
                    continue  # Already resolved, try next
                
                try:
                    # Use the direct slug endpoint
                    url = f"{self.GAMMA_API_URL}/events/slug/{slug}"
                    async with session.get(url) as response:
                        if response.status != 200:
                            continue
                        
                        event = await response.json()
                        
                        if not event:
                            continue
                        
                        # Skip closed markets
                        if event.get('closed', False):
                            continue
                        
                        markets = event.get('markets', [])
                        
                        up_token = None
                        down_token = None
                        
                        for m in markets:
                            outcomes = m.get('outcomes', [])
                            tokens = m.get('clobTokenIds', [])
                            
                            # Parse tokens if it's a JSON string
                            if isinstance(tokens, str):
                                try:
                                    tokens = json.loads(tokens)
                                except:
                                    tokens = []
                            
                            # Parse outcomes if it's a JSON string
                            if isinstance(outcomes, str):
                                try:
                                    outcomes = json.loads(outcomes)
                                except:
                                    outcomes = []
                            
                            if outcomes and tokens and len(outcomes) >= 2 and len(tokens) >= 2:
                                for i, outcome in enumerate(outcomes):
                                    if outcome.lower() == 'up':
                                        up_token = tokens[i]
                                    elif outcome.lower() == 'down':
                                        down_token = tokens[i]
                        
                        if up_token and down_token:
                            tracker = MarketTracker(slug, asset, self.cash_ref)
                            tracker.up_token_id = up_token
                            tracker.down_token_id = down_token
                            
                            end_date_str = event.get('endDate', '')
                            if end_date_str:
                                try:
                                    tracker.window_end = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                                except:
                                    pass
                            
                            tracker.initialized = True
                            self.active_markets[slug] = tracker
                            print(f"🔍 Auto-discovered: {slug}")
                            break  # Found one for this asset, move to next asset
                except Exception as e:
                    pass  # Silently skip failed lookups
    
    async def update_market(self, session: aiohttp.ClientSession, tracker: MarketTracker):
        """Update a single market's data"""
        if not tracker.initialized:
            return
        
        # Check if market window has ended
        now = datetime.now(timezone.utc)
        if tracker.window_end and now > tracker.window_end:
            if tracker.paper_trader.market_status == 'open':
                # Market closed - liquidate positions and move to history
                pt = tracker.paper_trader
                liquidation_value = (pt.qty_up * tracker.last_up_bid) + (pt.qty_down * tracker.last_down_bid)
                if liquidation_value == 0 and (pt.qty_up > 0 or pt.qty_down > 0):
                    liquidation_value = min(pt.qty_up, pt.qty_down)
                total_cost = pt.cost_up + pt.cost_down
                pnl = liquidation_value - total_cost
                
                # Add payout back to cash
                self.cash_ref['balance'] += liquidation_value
                
                # Mark as resolved with "CLOSED" outcome
                pt.market_status = 'resolved'
                pt.resolution_outcome = 'CLOSED'
                pt.payout = liquidation_value
                pt.final_pnl = pnl
                
                print(f"🔒 Market closed: {tracker.slug} | Liquidated: ${liquidation_value:.2f} | PnL: ${pnl:+.2f}")
                
                # Add to history
                self.history.append({
                    'resolved_at': datetime.now(timezone.utc).strftime('%H:%M:%S'),
                    'slug': tracker.slug,
                    'asset': tracker.asset,
                    'outcome': 'CLOSED',
                    'qty_up': pt.qty_up,
                    'qty_down': pt.qty_down,
                    'pair_cost': pt.pair_cost,
                    'payout': liquidation_value,
                    'pnl': pnl
                })
            return
        
        try:
            # Get orderbook for both tokens
            up_book = {}
            down_book = {}
            
            if tracker.up_token_id:
                url = f"{self.CLOB_API_URL}/book?token_id={tracker.up_token_id}"
                async with session.get(url) as response:
                    if response.status == 200:
                        up_book = await response.json()
            
            if tracker.down_token_id:
                url = f"{self.CLOB_API_URL}/book?token_id={tracker.down_token_id}"
                async with session.get(url) as response:
                    if response.status == 200:
                        down_book = await response.json()
            
            # Extract prices
            asks_up = up_book.get('asks', [])
            asks_down = down_book.get('asks', [])
            bids_up = up_book.get('bids', [])
            bids_down = down_book.get('bids', [])
            
            if asks_up:
                tracker.up_price = min(float(a.get('price', 1.0)) for a in asks_up if a.get('price'))
            
            if asks_down:
                tracker.down_price = min(float(a.get('price', 1.0)) for a in asks_down if a.get('price'))

            bids_up = up_book.get('bids', [])
            bids_down = down_book.get('bids', [])
            if bids_up:
                tracker.last_up_bid = max(float(b.get('price', 0.0)) for b in bids_up if b.get('price'))
            if bids_down:
                tracker.last_down_bid = max(float(b.get('price', 0.0)) for b in bids_down if b.get('price'))

            up_bid = None
            down_bid = None
            if bids_up:
                up_bid = max(float(b.get('price', 0.0)) for b in bids_up if b.get('price'))
            if bids_down:
                down_bid = max(float(b.get('price', 0.0)) for b in bids_down if b.get('price'))
            
            # Paper trading - calculate time to close for urgency
            if tracker.up_price and tracker.down_price and tracker.paper_trader.market_status == 'open':
                # Skip trading if paused
                if self.paused:
                    return
                
                timestamp = datetime.now(timezone.utc).strftime('%H:%M:%S')
                
                # Calculate time remaining until market close
                time_to_close = None
                if tracker.window_end:
                    time_to_close = (tracker.window_end - now).total_seconds()
                
                trades = tracker.paper_trader.check_and_trade(
                    tracker.up_price, 
                    tracker.down_price, 
                    timestamp,
                    time_to_close=time_to_close,
                    up_bid=up_bid,
                    down_bid=down_bid
                )
                
                if trades:
                    for side, price, qty in trades:
                        pt = tracker.paper_trader
                        urgency_msg = f" [⚠️ {time_to_close:.0f}s left!]" if time_to_close and time_to_close < 300 else ""
                        print(f"📈 [{tracker.asset.upper()}] BUY {qty:.1f} {side} @ ${price:.3f} | Pair: ${pt.pair_cost:.3f}{urgency_msg}")
                        
                        # Add to trade log
                        self.trade_log.append({
                            'time': timestamp,
                            'asset': tracker.asset.upper(),
                            'market': tracker.slug,
                            'side': side,
                            'price': price,
                            'qty': qty,
                            'cost': price * qty,
                            'pair_cost': pt.pair_cost
                        })
                        
                        # Keep only last 50 trades
                        if len(self.trade_log) > 50:
                            self.trade_log = self.trade_log[-50:]
            
            tracker.last_update = time.time()
            
        except Exception as e:
            print(f"Error updating {tracker.slug}: {e}")
    
    async def check_resolution(self, session: aiohttp.ClientSession, tracker: MarketTracker):
        """Check if a market has been resolved"""
        try:
            url = f"{self.GAMMA_API_URL}/events?slug={tracker.slug}"
            async with session.get(url) as response:
                if response.status == 200:
                    events = await response.json()
                    if events and len(events) > 0:
                        event = events[0]
                        markets = event.get('markets', [])
                        
                        for m in markets:
                            outcome = m.get('groupItemTitle', '').lower()
                            winner = m.get('winner')
                            
                            if winner:
                                if 'up' in outcome:
                                    resolution = 'UP'
                                elif 'down' in outcome:
                                    resolution = 'DOWN'
                                else:
                                    continue
                                
                                if tracker.paper_trader.market_status != 'resolved':
                                    pnl = tracker.paper_trader.resolve_market(resolution)
                                    print(f"🏁 [{tracker.asset.upper()}] Resolved: {resolution} | PnL: ${pnl:.2f}")
                                    
                                    # Add to history
                                    self.history.append({
                                        'resolved_at': datetime.now(timezone.utc).strftime('%H:%M:%S'),
                                        'slug': tracker.slug,
                                        'asset': tracker.asset,
                                        'outcome': resolution,
                                        'qty_up': tracker.paper_trader.qty_up,
                                        'qty_down': tracker.paper_trader.qty_down,
                                        'pair_cost': tracker.paper_trader.pair_cost,
                                        'payout': tracker.paper_trader.payout,
                                        'pnl': pnl
                                    })
                                break
        except Exception as e:
            print(f"Error checking resolution for {tracker.slug}: {e}")
    
    async def cleanup_old_markets(self):
        """Remove old resolved markets from active tracking"""
        to_remove = []
        for slug, tracker in self.active_markets.items():
            if tracker.paper_trader.market_status == 'resolved':
                # Keep resolved markets for a bit so UI can show them
                if time.time() - tracker.last_update > 60:
                    to_remove.append(slug)
        
        for slug in to_remove:
            del self.active_markets[slug]
            print(f"🗑️ Removed old market: {slug}")
    
    async def broadcast(self, data: dict):
        """Broadcast data to all connected websockets"""
        if not self.websockets:
            return
        
        message = json.dumps(data)
        disconnected = set()
        
        for ws in self.websockets:
            try:
                await ws.send_str(message)
            except:
                disconnected.add(ws)
        
        self.websockets -= disconnected
    
    async def data_loop(self):
        """Main data loop"""
        async with aiohttp.ClientSession() as session:
            while self.running:
                try:
                    # Discover new markets
                    await self.discover_markets(session)
                    
                    # Update all active markets
                    for tracker in list(self.active_markets.values()):
                        await self.update_market(session, tracker)
                        
                        # Check resolution for closed markets
                        if tracker.paper_trader.market_status == 'closed':
                            await self.check_resolution(session, tracker)
                    
                    # Cleanup old markets
                    await self.cleanup_old_markets()
                    
                    # Prepare broadcast data
                    active_data = {}
                    total_locked_profit = 0
                    total_position_value = 0
                    
                    for slug, tracker in self.active_markets.items():
                        pt = tracker.paper_trader
                        # Calculate position value (what we'd get if market resolved now)
                        min_qty = min(pt.qty_up, pt.qty_down)
                        position_value = min_qty  # Locked pairs pay out $1 per pair
                        total_position_value += position_value
                        total_locked_profit += pt.locked_profit
                        
                        active_data[slug] = {
                            'asset': tracker.asset,
                            'up_price': tracker.up_price,
                            'down_price': tracker.down_price,
                            'window_time': f"{tracker.window_end.strftime('%H:%M:%S') if tracker.window_end else '--:--'}",
                            'paper_trader': tracker.paper_trader.get_state()
                        }
                    
                    # True balance = cash + value of locked positions
                    true_balance = self.cash_ref['balance'] + total_position_value
                    
                    # Calculate W/D/L per asset
                    asset_wdl = {}
                    for asset in SUPPORTED_ASSETS:
                        asset_history = [h for h in self.history if h['asset'] == asset]
                        wins = sum(1 for h in asset_history if h['pnl'] > 0)
                        draws = sum(1 for h in asset_history if h['pnl'] == 0)
                        losses = sum(1 for h in asset_history if h['pnl'] < 0)
                        total = len(asset_history)
                        total_pnl = sum(h['pnl'] for h in asset_history)
                        asset_wdl[asset] = {
                            'wins': wins,
                            'draws': draws,
                            'losses': losses,
                            'total': total,
                            'total_pnl': total_pnl
                        }
                    
                    data = {
                        'starting_balance': self.starting_balance,
                        'current_balance': self.cash_ref['balance'],
                        'true_balance': true_balance,
                        'total_locked_profit': total_locked_profit,
                        'active_markets': active_data,
                        'history': self.history,
                        'trade_log': self.trade_log,
                        'paused': self.paused,
                        'asset_wdl': asset_wdl
                    }
                    
                    await self.broadcast(data)
                    
                    self.update_count += 1
                    if self.update_count % 10 == 0:
                        total_pnl = true_balance - self.starting_balance
                        print(f"📊 Cash: ${self.cash_ref['balance']:.2f} | True Balance: ${true_balance:.2f} | PnL: ${total_pnl:+.2f} | Active: {len(self.active_markets)}")
                    
                except Exception as e:
                    print(f"Error in data loop: {e}")
                
                await asyncio.sleep(1)
    
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
                        
                        if action == 'pause':
                            self.paused = not self.paused
                            status = "PAUSED" if self.paused else "RESUMED"
                            print(f"🔄 Trading {status}")
                            await self.broadcast({'paused': self.paused})
                        
                        elif action == 'reset':
                            # Reset everything
                            self.starting_balance = 1000.0
                            self.cash_ref['balance'] = 1000.0
                            self.history = []
                            self.trade_log = []
                            self.active_markets = {}
                            print(f"🔄 Bot RESET - Balance: $1000.00")
                            await self.broadcast({
                                'starting_balance': self.starting_balance,
                                'current_balance': self.cash_ref['balance'],
                                'true_balance': 1000.0,
                                'total_locked_profit': 0,
                                'active_markets': {},
                                'history': [],
                                'trade_log': [],
                                'paused': self.paused
                            })
                    except Exception as e:
                        print(f"Error handling websocket message: {e}")
        finally:
            self.websockets.discard(ws)
            print(f"WebSocket disconnected. Total: {len(self.websockets)}")
        
        return ws
    
    def create_app(self):
        app = web.Application()
        app.router.add_get('/', self.index_handler)
        app.router.add_get('/ws', self.websocket_handler)
        return app
    
    async def start(self):
        app = self.create_app()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', 8080)
        await site.start()
        
        print("🤖 Multi-Market Bot starting...")
        print(f"📊 Tracking: {', '.join(a.upper() for a in SUPPORTED_ASSETS)}")
        print("🌐 Open http://localhost:8080 in your browser")
        print("Press Ctrl+C to stop\n")
        
        await self.data_loop()


if __name__ == '__main__':
    bot = MultiMarketBot(starting_balance=1000.0)
    try:
        asyncio.run(bot.start())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped")
