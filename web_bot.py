#!/usr/bin/env python3
"""
Polymarket Web Bot - Bitcoin Up or Down Price Tracker
Web-based interface with real-time updates via WebSocket.
"""

import asyncio
import aiohttp
import json
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict
from aiohttp import web
import os

# Asset to track (btc, eth, sol, xrp)
ASSET = "btc"

# Market interval in minutes
MARKET_INTERVAL_MINUTES = 15

# HTML Template
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 Polymarket Bot - Bitcoin Up or Down</title>
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
            max-width: 900px;
            margin: 0 auto;
            border: 2px solid #3b82f6;
            border-radius: 8px;
            padding: 20px;
            background: linear-gradient(180deg, #0c0c0c 0%, #1a1a2e 100%);
        }
        
        .header {
            border-bottom: 1px solid #3b82f6;
            padding-bottom: 15px;
            margin-bottom: 20px;
        }
        
        .header h1 {
            color: #fbbf24;
            font-size: 1.5rem;
            margin-bottom: 8px;
        }
        
        .header .market {
            color: #22d3ee;
            font-size: 0.9rem;
        }
        
        .header .info {
            color: #9ca3af;
            font-size: 0.85rem;
            margin-top: 5px;
        }
        
        .header .status {
            margin-top: 8px;
        }
        
        .header .status .connected {
            color: #22c55e;
        }
        
        .header .status .disconnected {
            color: #ef4444;
        }
        
        .section-title {
            color: #fbbf24;
            text-align: center;
            margin: 20px 0 15px;
            font-size: 1.1rem;
        }
        
        .prices-container {
            display: flex;
            justify-content: space-around;
            margin-bottom: 20px;
            padding: 15px;
            background: rgba(0, 0, 0, 0.3);
            border-radius: 8px;
        }
        
        .price-box {
            text-align: center;
            padding: 15px 30px;
        }
        
        .price-box.up .label {
            color: #22c55e;
            font-weight: bold;
            font-size: 1.2rem;
        }
        
        .price-box.down .label {
            color: #ef4444;
            font-weight: bold;
            font-size: 1.2rem;
        }
        
        .price-box .percent {
            font-size: 2rem;
            font-weight: bold;
            margin: 10px 0;
            padding: 8px 20px;
            border-radius: 4px;
        }
        
        .price-box.up .percent {
            background: #22c55e;
            color: #000;
        }
        
        .price-box.down .percent {
            background: #ef4444;
            color: #fff;
        }
        
        .price-box .bid-ask {
            font-size: 0.9rem;
            margin-top: 5px;
        }
        
        .price-box .bid {
            color: #22c55e;
        }
        
        .price-box .ask {
            color: #ef4444;
        }
        
        .total {
            text-align: center;
            margin-top: 15px;
            color: #22d3ee;
            font-size: 1.1rem;
        }
        
        .orderbooks {
            display: flex;
            justify-content: space-between;
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .orderbook {
            flex: 1;
            background: rgba(0, 0, 0, 0.3);
            border-radius: 8px;
            padding: 15px;
        }
        
        .orderbook h3 {
            text-align: center;
            margin-bottom: 10px;
            font-size: 1rem;
        }
        
        .orderbook.up h3 {
            color: #22c55e;
        }
        
        .orderbook.down h3 {
            color: #ef4444;
        }
        
        .orderbook table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
        }
        
        .orderbook th {
            color: #9ca3af;
            padding: 5px;
            text-align: left;
            border-bottom: 1px solid #374151;
        }
        
        .orderbook td {
            padding: 5px;
        }
        
        .orderbook .bid-price {
            color: #22c55e;
        }
        
        .orderbook .ask-price {
            color: #ef4444;
        }
        
        .orderbook .size {
            color: #fbbf24;
        }
        
        .activity {
            background: rgba(0, 0, 0, 0.3);
            border-radius: 8px;
            padding: 15px;
        }
        
        .activity table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.8rem;
        }
        
        .activity th {
            color: #9ca3af;
            padding: 8px 5px;
            text-align: left;
            border-bottom: 1px solid #374151;
        }
        
        .activity td {
            padding: 8px 5px;
            border-bottom: 1px solid #1f2937;
        }
        
        .activity .time {
            color: #22d3ee;
        }
        
        .activity .token-up {
            color: #22c55e;
        }
        
        .activity .token-down {
            color: #ef4444;
        }
        
        .activity .side-buy {
            background: #22c55e;
            color: #000;
            padding: 2px 8px;
            border-radius: 3px;
            font-weight: bold;
        }
        
        .activity .side-sell {
            background: #ef4444;
            color: #fff;
            padding: 2px 8px;
            border-radius: 3px;
            font-weight: bold;
        }
        
        .footer {
            text-align: center;
            margin-top: 20px;
            color: #6b7280;
            font-size: 0.8rem;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .loading {
            animation: pulse 1.5s infinite;
        }
        
        /* Paper Trading Styles */
        .trading-section {
            background: rgba(0, 0, 0, 0.4);
            border: 2px solid #8b5cf6;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 20px;
        }
        
        .trading-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #8b5cf6;
        }
        
        .trading-header h2 {
            color: #8b5cf6;
            font-size: 1.2rem;
        }
        
        .market-status {
            padding: 5px 12px;
            border-radius: 4px;
            font-weight: bold;
            font-size: 0.85rem;
        }
        
        .market-status.open {
            background: #22c55e;
            color: #000;
        }
        
        .market-status.closed {
            background: #ef4444;
            color: #fff;
        }
        
        .market-status.resolved {
            background: #fbbf24;
            color: #000;
        }
        
        .trading-stats {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
            margin-bottom: 15px;
        }
        
        .stat-box {
            background: rgba(139, 92, 246, 0.1);
            border-radius: 6px;
            padding: 12px;
            text-align: center;
        }
        
        .stat-box .label {
            color: #9ca3af;
            font-size: 0.75rem;
            margin-bottom: 5px;
        }
        
        .stat-box .value {
            font-size: 1.1rem;
            font-weight: bold;
        }
        
        .stat-box .value.positive {
            color: #22c55e;
        }
        
        .stat-box .value.negative {
            color: #ef4444;
        }
        
        .stat-box .value.neutral {
            color: #fbbf24;
        }
        
        .pair-cost-bar {
            background: rgba(0, 0, 0, 0.3);
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 15px;
        }
        
        .pair-cost-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 10px;
        }
        
        .pair-cost-label {
            color: #9ca3af;
        }
        
        .pair-cost-value {
            font-size: 1.5rem;
            font-weight: bold;
        }
        
        .pair-cost-value.profit {
            color: #22c55e;
        }
        
        .pair-cost-value.loss {
            color: #ef4444;
        }
        
        .progress-bar {
            height: 20px;
            background: #374151;
            border-radius: 10px;
            overflow: hidden;
            position: relative;
        }
        
        .progress-fill {
            height: 100%;
            transition: width 0.3s ease;
        }
        
        .progress-fill.safe {
            background: linear-gradient(90deg, #22c55e, #16a34a);
        }
        
        .progress-fill.warning {
            background: linear-gradient(90deg, #fbbf24, #f59e0b);
        }
        
        .progress-fill.danger {
            background: linear-gradient(90deg, #ef4444, #dc2626);
        }
        
        .progress-marker {
            position: absolute;
            top: 0;
            bottom: 0;
            width: 2px;
            background: #fff;
        }
        
        .holdings-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 15px;
            margin-bottom: 15px;
        }
        
        .holding-box {
            background: rgba(0, 0, 0, 0.3);
            border-radius: 6px;
            padding: 12px;
        }
        
        .holding-box.up {
            border-left: 3px solid #22c55e;
        }
        
        .holding-box.down {
            border-left: 3px solid #ef4444;
        }
        
        .holding-title {
            font-weight: bold;
            margin-bottom: 8px;
        }
        
        .holding-box.up .holding-title {
            color: #22c55e;
        }
        
        .holding-box.down .holding-title {
            color: #ef4444;
        }
        
        .holding-row {
            display: flex;
            justify-content: space-between;
            font-size: 0.85rem;
            margin-bottom: 4px;
        }
        
        .holding-row .label {
            color: #9ca3af;
        }
        
        .trade-log {
            max-height: 150px;
            overflow-y: auto;
            background: rgba(0, 0, 0, 0.3);
            border-radius: 6px;
            padding: 10px;
        }
        
        .trade-entry {
            font-size: 0.75rem;
            padding: 4px 0;
            border-bottom: 1px solid #1f2937;
        }
        
        .trade-entry:last-child {
            border-bottom: none;
        }
        
        .trade-entry .time {
            color: #6b7280;
        }
        
        .trade-entry.buy-up {
            color: #22c55e;
        }
        
        .trade-entry.buy-down {
            color: #ef4444;
        }
        
        .pnl-display {
            text-align: center;
            padding: 15px;
            background: rgba(0, 0, 0, 0.4);
            border-radius: 8px;
            margin-top: 15px;
        }
        
        .pnl-display .label {
            color: #9ca3af;
            margin-bottom: 5px;
        }
        
        .pnl-display .value {
            font-size: 2rem;
            font-weight: bold;
        }
        
        .pnl-display .value.profit {
            color: #22c55e;
        }
        
        .pnl-display .value.loss {
            color: #ef4444;
        }
        
        /* Control Buttons */
        .control-buttons {
            display: flex;
            gap: 10px;
            margin-top: 15px;
        }
        
        .control-btn {
            flex: 1;
            padding: 12px 20px;
            border: none;
            border-radius: 6px;
            font-family: inherit;
            font-size: 0.9rem;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        
        .control-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }
        
        .control-btn:active {
            transform: translateY(0);
        }
        
        .control-btn.pause {
            background: linear-gradient(135deg, #f59e0b, #d97706);
            color: #000;
        }
        
        .control-btn.pause.paused {
            background: linear-gradient(135deg, #22c55e, #16a34a);
            color: #000;
        }
        
        .control-btn.reset {
            background: linear-gradient(135deg, #ef4444, #dc2626);
            color: #fff;
        }
        
        .control-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }
        
        .bot-status-badge {
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: bold;
            margin-left: 10px;
        }
        
        .bot-status-badge.active {
            background: #22c55e;
            color: #000;
        }
        
        .bot-status-badge.paused {
            background: #f59e0b;
            color: #000;
            animation: pulse 1.5s infinite;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 POLYMARKET BOT - <span id="market-title">Bitcoin Up or Down</span></h1>
            <div class="market">Market: <span id="event-slug">Loading...</span></div>
            <div class="info">
                Window: <span id="window-time">--:-- - --:--</span> UTC | 
                Time: <span id="current-time">--:--:--</span> UTC
            </div>
            <div class="status">
                Status: <span id="status" class="disconnected">⏳ Connecting...</span> | 
                Updates: <span id="update-count">0</span>
            </div>
        </div>
        
        <div class="section-title">💰 CURRENT MARKET PRICES 💰</div>
        
        <div class="prices-container">
            <div class="price-box up">
                <div class="label">UP</div>
                <div class="percent" id="up-percent">--%</div>
                <div class="bid-ask">
                    <span class="bid">Bid: <span id="up-bid">--¢</span></span><br>
                    <span class="ask">Ask: <span id="up-ask">--¢</span></span>
                </div>
            </div>
            <div class="price-box down">
                <div class="label">DOWN</div>
                <div class="percent" id="down-percent">--%</div>
                <div class="bid-ask">
                    <span class="bid">Bid: <span id="down-bid">--¢</span></span><br>
                    <span class="ask">Ask: <span id="down-ask">--¢</span></span>
                </div>
            </div>
        </div>
        
        <div class="total">Total: <span id="total">--¢</span></div>
        
        <div class="section-title">📊 ORDER BOOKS 📊</div>
        
        <div class="orderbooks">
            <div class="orderbook up">
                <h3>UP Token Orderbook</h3>
                <table>
                    <thead>
                        <tr>
                            <th>Bid $</th>
                            <th>Size</th>
                            <th>Ask $</th>
                            <th>Size</th>
                        </tr>
                    </thead>
                    <tbody id="up-orderbook">
                        <tr><td colspan="4" class="loading">Loading...</td></tr>
                    </tbody>
                </table>
            </div>
            <div class="orderbook down">
                <h3>DOWN Token Orderbook</h3>
                <table>
                    <thead>
                        <tr>
                            <th>Bid $</th>
                            <th>Size</th>
                            <th>Ask $</th>
                            <th>Size</th>
                        </tr>
                    </thead>
                    <tbody id="down-orderbook">
                        <tr><td colspan="4" class="loading">Loading...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
        
        <div class="section-title">📈 RECENT ACTIVITY 📈</div>
        
        <div class="activity">
            <table>
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Token</th>
                        <th>Side</th>
                        <th>Price</th>
                        <th>Size</th>
                    </tr>
                </thead>
                <tbody id="recent-activity">
                    <tr><td colspan="5" class="loading">Loading...</td></tr>
                </tbody>
            </table>
        </div>
        
        <div class="section-title">🤖 GABAGOOL PAPER TRADING 🤖</div>
        
        <div class="trading-section">
            <div class="trading-header">
                <h2>📈 Paper Trading Bot <span id="bot-status-badge" class="bot-status-badge active">ACTIVE</span></h2>
                <span id="market-status" class="market-status open">OPEN</span>
            </div>
            
            <div class="control-buttons">
                <button id="pause-btn" class="control-btn pause" onclick="togglePause()">
                    ⏸️ Pause Trading
                </button>
                <button id="reset-btn" class="control-btn reset" onclick="resetBot()">
                    🔄 Reset Bot
                </button>
            </div>
            
            <div class="trading-stats">
                <div class="stat-box">
                    <div class="label">Starting Balance</div>
                    <div class="value neutral">$1,000.00</div>
                </div>
                <div class="stat-box">
                    <div class="label">Cash Remaining</div>
                    <div class="value" id="cash-remaining">$1,000.00</div>
                </div>
                <div class="stat-box">
                    <div class="label">Total Invested</div>
                    <div class="value" id="total-invested">$0.00</div>
                </div>
            </div>
            
            <div class="pair-cost-bar">
                <div class="pair-cost-header">
                    <span class="pair-cost-label">Pair Cost (Target: &lt; $1.00)</span>
                    <span id="pair-cost-value" class="pair-cost-value profit">$0.00</span>
                </div>
                <div class="progress-bar">
                    <div id="pair-cost-fill" class="progress-fill safe" style="width: 0%"></div>
                    <div class="progress-marker" style="left: 100%"></div>
                </div>
                <div style="display: flex; justify-content: space-between; margin-top: 5px; font-size: 0.75rem; color: #6b7280;">
                    <span>$0.00</span>
                    <span>$1.00 (Break-even)</span>
                    <span>$1.10</span>
                </div>
            </div>
            
            <div class="holdings-grid">
                <div class="holding-box up">
                    <div class="holding-title">📗 UP Holdings</div>
                    <div class="holding-row">
                        <span class="label">Shares:</span>
                        <span id="up-shares">0</span>
                    </div>
                    <div class="holding-row">
                        <span class="label">Total Cost:</span>
                        <span id="up-cost">$0.00</span>
                    </div>
                    <div class="holding-row">
                        <span class="label">Avg Price:</span>
                        <span id="up-avg">$0.00</span>
                    </div>
                    <div class="holding-row">
                        <span class="label">Current Value:</span>
                        <span id="up-value">$0.00</span>
                    </div>
                </div>
                <div class="holding-box down">
                    <div class="holding-title">📕 DOWN Holdings</div>
                    <div class="holding-row">
                        <span class="label">Shares:</span>
                        <span id="down-shares">0</span>
                    </div>
                    <div class="holding-row">
                        <span class="label">Total Cost:</span>
                        <span id="down-cost">$0.00</span>
                    </div>
                    <div class="holding-row">
                        <span class="label">Avg Price:</span>
                        <span id="down-avg">$0.00</span>
                    </div>
                    <div class="holding-row">
                        <span class="label">Current Value:</span>
                        <span id="down-value">$0.00</span>
                    </div>
                </div>
            </div>
            
            <div class="trading-stats">
                <div class="stat-box">
                    <div class="label">Guaranteed Payout</div>
                    <div class="value" id="guaranteed-payout">$0.00</div>
                </div>
                <div class="stat-box">
                    <div class="label">Locked Profit</div>
                    <div class="value" id="locked-profit">$0.00</div>
                </div>
                <div class="stat-box">
                    <div class="label">Trade Count</div>
                    <div class="value neutral" id="trade-count">0</div>
                </div>
            </div>
            
            <div style="color: #9ca3af; font-size: 0.8rem; margin-bottom: 10px;">📜 Trade Log</div>
            <div class="trade-log" id="trade-log">
                <div class="trade-entry" style="color: #6b7280;">Waiting for trading signals...</div>
            </div>
            
            <div class="pnl-display">
                <div class="label">Unrealized P&L</div>
                <div id="unrealized-pnl" class="value profit">$0.00</div>
            </div>
            
            <div id="final-pnl-section" style="display: none;">
                <div class="pnl-display" style="border: 2px solid #fbbf24; margin-top: 10px;">
                    <div class="label">🏆 FINAL REALIZED P&L 🏆</div>
                    <div id="final-pnl" class="value profit">$0.00</div>
                    <div id="resolution-outcome" style="margin-top: 10px; color: #9ca3af;"></div>
                </div>
            </div>
        </div>
        
        <div class="section-title">📊 PNL HISTORY 📊</div>
        
        <div class="trading-section" style="border-color: #22d3ee;">
            <div class="trading-header" style="border-color: #22d3ee;">
                <h2 style="color: #22d3ee;">💰 Session PNL Summary</h2>
                <span id="markets-traded" style="color: #9ca3af;">Markets: 0</span>
            </div>
            
            <div class="trading-stats">
                <div class="stat-box">
                    <div class="label">Total Realized PNL</div>
                    <div class="value" id="total-realized-pnl">$0.00</div>
                </div>
                <div class="stat-box">
                    <div class="label">Wins / Losses</div>
                    <div class="value neutral" id="win-loss-record">0 / 0</div>
                </div>
                <div class="stat-box">
                    <div class="label">Avg PNL per Market</div>
                    <div class="value" id="avg-pnl">$0.00</div>
                </div>
            </div>
            
            <div style="color: #9ca3af; font-size: 0.8rem; margin-bottom: 10px;">📜 Market History</div>
            <div class="trade-log" id="pnl-history" style="max-height: 200px;">
                <div class="trade-entry" style="color: #6b7280;">No markets resolved yet...</div>
            </div>
            
            <div style="margin-top: 15px; padding: 10px; background: rgba(34, 211, 238, 0.1); border-radius: 6px; border: 1px solid #22d3ee;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="color: #22d3ee;">🔄 Auto Market Discovery</span>
                    <span id="next-market-info" style="color: #9ca3af; font-size: 0.85rem;">Watching for next market...</span>
                </div>
            </div>
        </div>
        
        <div class="footer">
            Press F5 to refresh | Data from Polymarket CLOB API | Gabagool Strategy Paper Trading
        </div>
    </div>
    
    <script>
        const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const ws = new WebSocket(`${wsProtocol}://${window.location.host}/ws`);
        
        ws.onopen = () => {
            document.getElementById('status').innerHTML = '✓ Connected & Streaming';
            document.getElementById('status').className = 'connected';
        };
        
        ws.onclose = () => {
            document.getElementById('status').innerHTML = '✗ Disconnected';
            document.getElementById('status').className = 'disconnected';
        };
        
        ws.onerror = () => {
            document.getElementById('status').innerHTML = '✗ Error';
            document.getElementById('status').className = 'disconnected';
        };
        
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            updateDisplay(data);
            updatePaperTrading(data);
        };
        
        function formatSize(size) {
            if (size >= 1000000) return (size / 1000000).toFixed(1) + 'M';
            if (size >= 1000) return (size / 1000).toFixed(0) + 'k';
            return size.toFixed(1);
        }
        
        function formatPrice(price) {
            return (price * 100).toFixed(1) + '¢';
        }
        
        function updateDisplay(data) {
            // Update header
            document.getElementById('market-title').textContent = data.title || 'Bitcoin Up or Down';
            document.getElementById('event-slug').textContent = data.event_slug || '';
            document.getElementById('window-time').textContent = data.window_time || '--:-- - --:--';
            document.getElementById('current-time').textContent = data.current_time || '--:--:--';
            document.getElementById('update-count').textContent = data.update_count || 0;
            
            // Update prices
            const upMid = data.up_mid || 0;
            const downMid = data.down_mid || 0;
            
            document.getElementById('up-percent').textContent = (upMid * 100).toFixed(1) + '%';
            document.getElementById('down-percent').textContent = (downMid * 100).toFixed(1) + '%';
            
            const upBook = data.up_book || {};
            const downBook = data.down_book || {};
            
            const upBid = upBook.bids && upBook.bids[0] ? parseFloat(upBook.bids[0].price) : 0;
            const upAsk = upBook.asks && upBook.asks[0] ? parseFloat(upBook.asks[0].price) : 0;
            const downBid = downBook.bids && downBook.bids[0] ? parseFloat(downBook.bids[0].price) : 0;
            const downAsk = downBook.asks && downBook.asks[0] ? parseFloat(downBook.asks[0].price) : 0;
            
            document.getElementById('up-bid').textContent = formatPrice(upBid);
            document.getElementById('up-ask').textContent = formatPrice(upAsk);
            document.getElementById('down-bid').textContent = formatPrice(downBid);
            document.getElementById('down-ask').textContent = formatPrice(downAsk);
            
            document.getElementById('total').textContent = ((upMid + downMid) * 100).toFixed(1) + '¢';
            
            // Update orderbooks
            updateOrderbook('up-orderbook', upBook);
            updateOrderbook('down-orderbook', downBook);
            
            // Update activity
            updateActivity(data.up_trades || [], data.down_trades || []);
        }
        
        function updateOrderbook(elementId, book) {
            const tbody = document.getElementById(elementId);
            const bids = book.bids || [];
            const asks = book.asks || [];
            
            let html = '';
            for (let i = 0; i < 3; i++) {
                const bid = bids[i] || {};
                const ask = asks[i] || {};
                html += `<tr>
                    <td class="bid-price">${bid.price ? parseFloat(bid.price).toFixed(3) : '-'}</td>
                    <td class="size">${bid.size ? formatSize(parseFloat(bid.size)) : '-'}</td>
                    <td class="ask-price">${ask.price ? parseFloat(ask.price).toFixed(3) : '-'}</td>
                    <td class="size">${ask.size ? formatSize(parseFloat(ask.size)) : '-'}</td>
                </tr>`;
            }
            tbody.innerHTML = html;
        }
        
        function updateActivity(upTrades, downTrades) {
            const tbody = document.getElementById('recent-activity');
            
            // Combine trades
            const allTrades = [];
            upTrades.slice(0, 5).forEach(t => { t.token = 'UP'; allTrades.push(t); });
            downTrades.slice(0, 5).forEach(t => { t.token = 'DOWN'; allTrades.push(t); });
            
            // Sort by time
            allTrades.sort((a, b) => {
                const timeA = a.match_time || a.timestamp || 0;
                const timeB = b.match_time || b.timestamp || 0;
                return timeB - timeA;
            });
            
            let html = '';
            allTrades.slice(0, 10).forEach(trade => {
                const ts = trade.match_time || trade.timestamp;
                let timeStr = '--:--:--';
                if (ts) {
                    const date = new Date(ts * 1000);
                    timeStr = date.toISOString().substr(11, 8);
                }
                
                const tokenClass = trade.token === 'UP' ? 'token-up' : 'token-down';
                const sideClass = trade.side === 'BUY' ? 'side-buy' : 'side-sell';
                const price = parseFloat(trade.price || 0);
                const size = parseFloat(trade.size || 0);
                
                html += `<tr>
                    <td class="time">${timeStr}</td>
                    <td class="${tokenClass}">${trade.token}</td>
                    <td><span class="${sideClass}">${trade.side}</span></td>
                    <td>$${price.toFixed(2)}</td>
                    <td>${size.toFixed(1)}</td>
                </tr>`;
            });
            
            tbody.innerHTML = html || '<tr><td colspan="5">No recent trades</td></tr>';
        }
        
        function updatePaperTrading(data) {
            const pt = data.paper_trading;
            if (!pt) return;
            
            // Update market status
            const statusEl = document.getElementById('market-status');
            statusEl.textContent = pt.market_status.toUpperCase();
            statusEl.className = 'market-status ' + pt.market_status;
            
            // Update stats
            document.getElementById('cash-remaining').textContent = '$' + pt.cash.toFixed(2);
            document.getElementById('total-invested').textContent = '$' + (pt.cost_up + pt.cost_down).toFixed(2);
            
            // Update pair cost
            const pairCost = pt.pair_cost;
            const pairCostEl = document.getElementById('pair-cost-value');
            pairCostEl.textContent = '$' + pairCost.toFixed(4);
            pairCostEl.className = 'pair-cost-value ' + (pairCost < 1.0 ? 'profit' : 'loss');
            
            // Update progress bar
            const fillEl = document.getElementById('pair-cost-fill');
            const fillPercent = Math.min(pairCost / 1.1 * 100, 100);
            fillEl.style.width = fillPercent + '%';
            if (pairCost < 0.95) {
                fillEl.className = 'progress-fill safe';
            } else if (pairCost < 1.0) {
                fillEl.className = 'progress-fill warning';
            } else {
                fillEl.className = 'progress-fill danger';
            }
            
            // Update holdings
            document.getElementById('up-shares').textContent = pt.qty_up.toFixed(2);
            document.getElementById('up-cost').textContent = '$' + pt.cost_up.toFixed(2);
            document.getElementById('up-avg').textContent = '$' + pt.avg_up.toFixed(4);
            document.getElementById('up-value').textContent = '$' + (pt.qty_up * data.up_mid).toFixed(2);
            
            document.getElementById('down-shares').textContent = pt.qty_down.toFixed(2);
            document.getElementById('down-cost').textContent = '$' + pt.cost_down.toFixed(2);
            document.getElementById('down-avg').textContent = '$' + pt.avg_down.toFixed(4);
            document.getElementById('down-value').textContent = '$' + (pt.qty_down * data.down_mid).toFixed(2);
            
            // Update guaranteed payout and locked profit
            const minQty = Math.min(pt.qty_up, pt.qty_down);
            const totalCost = pt.cost_up + pt.cost_down;
            document.getElementById('guaranteed-payout').textContent = '$' + minQty.toFixed(2);
            
            const lockedProfit = minQty - totalCost;
            const lockedEl = document.getElementById('locked-profit');
            lockedEl.textContent = '$' + lockedProfit.toFixed(2);
            lockedEl.className = 'value ' + (lockedProfit > 0 ? 'positive' : 'negative');
            
            document.getElementById('trade-count').textContent = pt.trade_count;
            
            // Update trade log
            if (pt.trade_log && pt.trade_log.length > 0) {
                const logEl = document.getElementById('trade-log');
                logEl.innerHTML = pt.trade_log.map(t => 
                    `<div class="trade-entry ${t.side.toLowerCase()}-${t.token.toLowerCase()}">
                        <span class="time">[${t.time}]</span> 
                        ${t.side} ${t.qty.toFixed(2)} ${t.token} @ $${t.price.toFixed(4)}
                    </div>`
                ).join('');
            }
            
            // Update unrealized PnL
            const currentValue = (pt.qty_up * data.up_mid) + (pt.qty_down * data.down_mid);
            const unrealizedPnl = currentValue - totalCost;
            const unrealizedEl = document.getElementById('unrealized-pnl');
            unrealizedEl.textContent = (unrealizedPnl >= 0 ? '+' : '') + '$' + unrealizedPnl.toFixed(2);
            unrealizedEl.className = 'value ' + (unrealizedPnl >= 0 ? 'profit' : 'loss');
            
            // Show final PnL if market is resolved
            if (pt.market_status === 'resolved' && pt.final_pnl !== undefined) {
                document.getElementById('final-pnl-section').style.display = 'block';
                const finalPnlEl = document.getElementById('final-pnl');
                finalPnlEl.textContent = (pt.final_pnl >= 0 ? '+' : '') + '$' + pt.final_pnl.toFixed(2);
                finalPnlEl.className = 'value ' + (pt.final_pnl >= 0 ? 'profit' : 'loss');
                document.getElementById('resolution-outcome').textContent = 
                    'Market resolved: ' + pt.resolution_outcome + ' | Payout: $' + pt.payout.toFixed(2);
            }
            
            // Update PNL history
            updatePnlHistory(data);
        }
        
        function updatePnlHistory(data) {
            const pnlHistory = data.pnl_history || [];
            const totalPnl = data.total_realized_pnl || 0;
            const nextMarketInfo = data.next_market_info || 'Watching for next market...';
            
            // Update summary stats
            const totalEl = document.getElementById('total-realized-pnl');
            totalEl.textContent = (totalPnl >= 0 ? '+' : '') + '$' + totalPnl.toFixed(2);
            totalEl.className = 'value ' + (totalPnl >= 0 ? 'profit' : 'loss');
            
            const wins = pnlHistory.filter(h => h.pnl > 0).length;
            const losses = pnlHistory.filter(h => h.pnl <= 0).length;
            document.getElementById('win-loss-record').textContent = wins + ' / ' + losses;
            
            const avgPnl = pnlHistory.length > 0 ? totalPnl / pnlHistory.length : 0;
            const avgEl = document.getElementById('avg-pnl');
            avgEl.textContent = (avgPnl >= 0 ? '+' : '') + '$' + avgPnl.toFixed(2);
            avgEl.className = 'value ' + (avgPnl >= 0 ? 'profit' : 'loss');
            
            document.getElementById('markets-traded').textContent = 'Markets: ' + pnlHistory.length;
            document.getElementById('next-market-info').textContent = nextMarketInfo;
            
            // Update history log
            if (pnlHistory.length > 0) {
                const historyEl = document.getElementById('pnl-history');
                historyEl.innerHTML = pnlHistory.slice().reverse().map(h => {
                    const pnlClass = h.pnl >= 0 ? 'buy-up' : 'buy-down';
                    const pnlSign = h.pnl >= 0 ? '+' : '';
                    return `<div class="trade-entry ${pnlClass}">
                        <span class="time">[${h.time}]</span>
                        ${h.slug} | Outcome: ${h.outcome} | PNL: ${pnlSign}$${h.pnl.toFixed(2)}
                    </div>`;
                }).join('');
            }
            
            // Update bot paused status
            updateBotStatus(data.bot_paused || false);
        }
        
        function updateBotStatus(isPaused) {
            const pauseBtn = document.getElementById('pause-btn');
            const statusBadge = document.getElementById('bot-status-badge');
            
            if (isPaused) {
                pauseBtn.innerHTML = '▶️ Resume Trading';
                pauseBtn.classList.add('paused');
                statusBadge.textContent = 'PAUSED';
                statusBadge.className = 'bot-status-badge paused';
            } else {
                pauseBtn.innerHTML = '⏸️ Pause Trading';
                pauseBtn.classList.remove('paused');
                statusBadge.textContent = 'ACTIVE';
                statusBadge.className = 'bot-status-badge active';
            }
        }
        
        function togglePause() {
            ws.send(JSON.stringify({ command: 'toggle_pause' }));
        }
        
        function resetBot() {
            if (confirm('Are you sure you want to reset the bot? This will clear all PNL history and current positions.')) {
                ws.send(JSON.stringify({ command: 'reset_bot' }));
            }
        }
        
        // Update time every second
        setInterval(() => {
            const now = new Date();
            document.getElementById('current-time').textContent = now.toISOString().substr(11, 8);
        }, 1000);
    </script>
</body>
</html>
"""


class PaperTrader:
    """Gabagool-style paper trading bot - BALANCED HEDGING STRATEGY"""
    
    def __init__(self, starting_balance: float = 1000.0):
        self.starting_balance = starting_balance
        self.cash = starting_balance
        self.qty_up = 0.0
        self.qty_down = 0.0
        self.cost_up = 0.0
        self.cost_down = 0.0
        self.trade_log = []
        self.trade_count = 0
        self.market_status = 'open'  # open, closed, resolved
        self.resolution_outcome = None  # 'UP' or 'DOWN'
        self.final_pnl = None
        self.payout = 0.0
        
        # === GABAGOOL STRATEGY v3 PARAMETERS ===
        # The key insight: we need avg_UP + avg_DOWN < 1.00 to guarantee profit
        # And we need qty_UP ≈ qty_DOWN to maximize the guaranteed payout
        # v4: EMERGENCY BALANCING - force balance even at bad prices if unhedged too long
        
        self.target_pair_cost = 0.90    # Target pair cost (below this = profit zone)
        self.max_pair_cost = 0.96       # Absolute max pair cost - allow up to 0.96 for emergency balance
        self.cheap_threshold = 0.46     # Only buy when price is below this
        self.rebalance_threshold_price = 0.50  # Buy to rebalance even at this price
        self.emergency_rebalance_price = 0.55  # EMERGENCY: Force buy at this price if unhedged
        self.very_cheap_threshold = 0.40 # Aggressively buy when below this
        self.min_trade_size = 5.0       # Minimum trade size in dollars
        self.max_single_trade = 20.0    # Max single trade size (smaller = more control)
        self.cooldown_seconds = 3       # Seconds between trades
        self.last_trade_time = 0
        self.first_trade_time = 0       # When we made our first trade (for emergency timing)
        self.emergency_after_seconds = 300  # 5 minutes - force balance after this
        
        # Balance constraints - THIS IS CRITICAL for Gabagool strategy
        # v4: Must balance even at worse prices to avoid total loss
        self.max_qty_ratio = 1.05       # Max ratio - EXTREMELY STRICT
        self.target_qty_ratio = 1.0     # Ideal ratio (perfectly balanced)
        self.rebalance_trigger = 1.03   # Start rebalancing when ratio exceeds this
        
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
    
    def simulate_buy(self, side: str, price: float, qty: float) -> tuple:
        """Simulate what happens if we buy, returns (new_avg, new_pair_cost)"""
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
    
    def should_buy(self, side: str, price: float, other_price: float, is_rebalance: bool = False, is_emergency: bool = False) -> tuple:
        """
        GABAGOOL STRATEGY v4: Emergency balancing.
        
        Key principles:
        1. BALANCE IS ABSOLUTELY REQUIRED - ratio must stay < 1.05
        2. Rebalancing takes priority over cheap prices
        3. EMERGENCY: After 5 min unhedged, force balance even at bad prices
        4. The guaranteed profit = min(qty_UP, qty_DOWN) - total_cost
        """
        import time as time_module
        
        if self.market_status != 'open':
            return False, 0, "Market not open"
        
        # Cooldown check (shorter cooldown for rebalancing/emergency)
        now = time_module.time()
        cooldown = self.cooldown_seconds / 3 if (is_rebalance or is_emergency) else self.cooldown_seconds
        if now - self.last_trade_time < cooldown:
            return False, 0, "Cooldown active"
        
        my_qty = self.qty_up if side == 'UP' else self.qty_down
        other_qty = self.qty_down if side == 'UP' else self.qty_up
        other_side = 'DOWN' if side == 'UP' else 'UP'
        
        # === FIRST TRADE ===
        if my_qty == 0 and other_qty == 0:
            if price > self.cheap_threshold:
                return False, 0, f"First trade needs cheap price (< {self.cheap_threshold})"
            max_spend = min(self.cash * 0.02, self.max_single_trade)
            qty = max_spend / price
            # Record first trade time for emergency timing
            self.first_trade_time = now
            return True, qty, "First trade - starting small"
        
        # === MUST BALANCE BEFORE ADDING MORE ===
        if other_qty == 0 and my_qty > 0:
            return False, 0, f"BLOCKED: Must buy {other_side} first"
        
        # === CATCH UP MODE (including EMERGENCY) ===
        if my_qty == 0 and other_qty > 0:
            # Check if this is an emergency (been waiting too long)
            time_unhedged = now - self.first_trade_time if self.first_trade_time > 0 else 0
            is_emergency_mode = time_unhedged > self.emergency_after_seconds
            
            # Determine price threshold based on urgency
            if is_emergency_mode or is_emergency:
                price_threshold = self.emergency_rebalance_price
                reason_prefix = "🚨 EMERGENCY"
            else:
                price_threshold = self.rebalance_threshold_price
                reason_prefix = "REBALANCE"
            
            if price > price_threshold:
                if is_emergency_mode:
                    return False, 0, f"🚨 EMERGENCY: Need {side} < ${price_threshold} (unhedged {time_unhedged:.0f}s)"
                return False, 0, f"Need {side} < ${price_threshold} to balance"
            
            # Calculate how much to buy to match
            target_qty = other_qty
            max_spend = min(target_qty * price, self.cash * 0.2, self.max_single_trade * 2)
            qty = max_spend / price
            return True, qty, f"{reason_prefix}: Catching up {side}"
        
        # === BOTH SIDES HAVE POSITIONS ===
        ratio = my_qty / other_qty
        
        # HARD BLOCK: If we're at or above max ratio, NO MORE BUYS on this side
        if ratio >= self.max_qty_ratio:  # 1.05x
            return False, 0, f"HARD BLOCK: {side} at max ({ratio:.3f}x)"
        
        # SOFT BLOCK: If we're ahead at all, only buy if it's a rebalancing call
        if ratio >= self.rebalance_trigger:  # 1.03x
            if not is_rebalance:
                return False, 0, f"BLOCKED: {side} ahead ({ratio:.3f}x) - waiting for {other_side}"
        
        # Calculate how much we can buy while staying balanced
        max_qty_allowed = other_qty * self.max_qty_ratio - my_qty
        if max_qty_allowed <= 0:
            return False, 0, f"At balance limit"
        
        # Determine price threshold based on balance state
        if ratio < 0.97:  # We're behind - be more lenient
            price_threshold = self.rebalance_threshold_price
            qty_multiplier = 1.5  # Buy more to catch up
        elif ratio < 1.0:  # Slightly behind
            price_threshold = self.cheap_threshold
            qty_multiplier = 1.2
        else:  # At or ahead of balance - very strict
            price_threshold = self.cheap_threshold - 0.03
            qty_multiplier = 0.5
        
        if price > price_threshold:
            return False, 0, f"{side} price ${price:.3f} > threshold ${price_threshold:.2f}"
        
        # Calculate trade size
        base_spend = min(self.cash * 0.03, self.max_single_trade)
        max_spend = base_spend * qty_multiplier
        
        if max_spend < self.min_trade_size:
            return False, 0, "Insufficient funds"
        
        qty = min(max_spend / price, max_qty_allowed)
        
        if qty * price < self.min_trade_size:
            return False, 0, "Trade too small"
        
        # === PAIR COST CHECK ===
        if self.qty_up > 0 and self.qty_down > 0:
            new_avg, new_pair_cost = self.simulate_buy(side, price, qty)
            
            # Try reducing quantity if pair cost too high
            while new_pair_cost > self.max_pair_cost and qty > self.min_trade_size / price:
                qty = qty * 0.6
                new_avg, new_pair_cost = self.simulate_buy(side, price, qty)
            
            if new_pair_cost > self.max_pair_cost:
                return False, 0, f"Would exceed pair cost ${new_pair_cost:.3f}"
            
            # Don't make pair cost worse if already above target
            if self.pair_cost > self.target_pair_cost and new_pair_cost >= self.pair_cost:
                return False, 0, f"Pair cost ${self.pair_cost:.3f} already high"
        
        # === VERY CHEAP BONUS ===
        if price < self.very_cheap_threshold and ratio < 1.0:
            # Can be slightly more aggressive when price is very cheap AND we're behind
            bonus_qty = min(qty * 1.2, max_qty_allowed)
            if bonus_qty * price < self.cash * 0.1:
                qty = bonus_qty
        
        # Final sanity check
        if qty * price > self.cash:
            qty = self.cash / price * 0.95
        
        if qty * price < self.min_trade_size:
            return False, 0, "Trade too small"
        
        final_ratio = (my_qty + qty) / other_qty if other_qty > 0 else 1.0
        return True, qty, f"OK (${price:.3f}, ratio: {final_ratio:.2f}x)"
    
    def execute_buy(self, side: str, price: float, qty: float, timestamp: str):
        """Execute a paper trade"""
        import time as time_module
        
        cost = price * qty
        
        if cost > self.cash:
            return False
        
        self.cash -= cost
        self.trade_count += 1
        self.last_trade_time = time_module.time()
        
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
        
        # Keep only last 20 trades in log
        if len(self.trade_log) > 20:
            self.trade_log = self.trade_log[-20:]
        
        return True
    
    def check_and_trade(self, up_price: float, down_price: float, timestamp: str):
        """
        GABAGOOL v4: EMERGENCY BALANCE-FIRST TRADING
        
        Priority:
        1. EMERGENCY: If unhedged too long, force balance at higher prices
        2. If imbalanced, buy the LAGGING side
        3. If balanced, buy the CHEAPER side (only if cheap enough)
        4. Never let ratio exceed 1.05x
        """
        import time as time_module
        trades_made = []
        
        # Check if we're in emergency mode (one side has no position for too long)
        is_emergency = False
        if self.first_trade_time > 0:
            time_since_first = time_module.time() - self.first_trade_time
            if time_since_first > self.emergency_after_seconds:
                if (self.qty_up == 0 and self.qty_down > 0) or (self.qty_down == 0 and self.qty_up > 0):
                    is_emergency = True
                    print(f"🚨 EMERGENCY MODE: Unhedged for {time_since_first:.0f}s!")
        
        # === EMERGENCY BALANCING ===
        if is_emergency:
            if self.qty_up == 0 and self.qty_down > 0:
                should, qty, reason = self.should_buy('UP', up_price, down_price, is_rebalance=True, is_emergency=True)
                if should:
                    if self.execute_buy('UP', up_price, qty, timestamp):
                        trades_made.append(('UP', up_price, qty))
                        print(f"🚨 EMERGENCY BUY: {qty:.1f} UP @ ${up_price:.3f}")
                return trades_made
            
            if self.qty_down == 0 and self.qty_up > 0:
                should, qty, reason = self.should_buy('DOWN', down_price, up_price, is_rebalance=True, is_emergency=True)
                if should:
                    if self.execute_buy('DOWN', down_price, qty, timestamp):
                        trades_made.append(('DOWN', down_price, qty))
                        print(f"🚨 EMERGENCY BUY: {qty:.1f} DOWN @ ${down_price:.3f}")
                return trades_made
        
        # Calculate current balance
        if self.qty_up > 0 and self.qty_down > 0:
            ratio_up = self.qty_up / self.qty_down
            ratio_down = self.qty_down / self.qty_up
            
            # REBALANCING MODE: If one side is ahead, only buy the other
            if ratio_up > self.rebalance_trigger:  # UP ahead, need DOWN
                should, qty, reason = self.should_buy('DOWN', down_price, up_price, is_rebalance=True)
                if should:
                    if self.execute_buy('DOWN', down_price, qty, timestamp):
                        trades_made.append(('DOWN', down_price, qty))
                return trades_made  # Only rebalance, don't add to leading side
            
            if ratio_down > self.rebalance_trigger:  # DOWN ahead, need UP
                should, qty, reason = self.should_buy('UP', up_price, down_price, is_rebalance=True)
                if should:
                    if self.execute_buy('UP', up_price, qty, timestamp):
                        trades_made.append(('UP', up_price, qty))
                return trades_made  # Only rebalance, don't add to leading side
        
        # Determine which side is cheaper
        if up_price < down_price:
            # UP is cheaper - try UP first, then DOWN
            should_buy_up, qty_up, reason_up = self.should_buy('UP', up_price, down_price)
            if should_buy_up:
                if self.execute_buy('UP', up_price, qty_up, timestamp):
                    trades_made.append(('UP', up_price, qty_up))
            
            # Now check DOWN (might need to balance)
            should_buy_down, qty_down, reason_down = self.should_buy('DOWN', down_price, up_price)
            if should_buy_down:
                if self.execute_buy('DOWN', down_price, qty_down, timestamp):
                    trades_made.append(('DOWN', down_price, qty_down))
        else:
            # DOWN is cheaper - try DOWN first, then UP
            should_buy_down, qty_down, reason_down = self.should_buy('DOWN', down_price, up_price)
            if should_buy_down:
                if self.execute_buy('DOWN', down_price, qty_down, timestamp):
                    trades_made.append(('DOWN', down_price, qty_down))
            
            # Now check UP (might need to balance)
            should_buy_up, qty_up, reason_up = self.should_buy('UP', up_price, down_price)
            if should_buy_up:
                if self.execute_buy('UP', up_price, qty_up, timestamp):
                    trades_made.append(('UP', up_price, qty_up))
        
        return trades_made
    
    def resolve_market(self, outcome: str):
        """Resolve the market and calculate final PnL"""
        self.market_status = 'resolved'
        self.resolution_outcome = outcome
        
        if outcome == 'UP':
            self.payout = self.qty_up * 1.0  # Each UP share pays $1
        else:
            self.payout = self.qty_down * 1.0  # Each DOWN share pays $1
        
        total_cost = self.cost_up + self.cost_down
        self.final_pnl = self.payout - total_cost
        
        return self.final_pnl
    
    def close_market(self):
        """Mark market as closed (no more trading)"""
        self.market_status = 'closed'
    
    def get_state(self) -> dict:
        """Return current state for broadcasting"""
        return {
            'cash': self.cash,
            'qty_up': self.qty_up,
            'qty_down': self.qty_down,
            'cost_up': self.cost_up,
            'cost_down': self.cost_down,
            'avg_up': self.avg_up,
            'avg_down': self.avg_down,
            'pair_cost': self.pair_cost,
            'locked_profit': self.locked_profit,
            'trade_count': self.trade_count,
            'trade_log': self.trade_log[-10:],  # Last 10 trades
            'market_status': self.market_status,
            'resolution_outcome': self.resolution_outcome,
            'final_pnl': self.final_pnl,
            'payout': self.payout
        }


class PolymarketWebBot:
    GAMMA_API_URL = "https://gamma-api.polymarket.com"
    CLOB_API_URL = "https://clob.polymarket.com"
    
    def __init__(self, asset: str = "btc", interval_minutes: int = 15):
        self.asset = asset.lower()
        self.interval_minutes = interval_minutes
        self.event_slug = None
        self.market_title = f"{asset.upper()} Up or Down"
        self.up_token_id = None
        self.down_token_id = None
        self.update_count = 0
        self.window_start = None
        self.window_end = None
        self.websockets = set()
        self.running = True
        self.paper_trader = PaperTrader(starting_balance=1000.0)
        self.market_closed = False
        self.market_resolved = False
        
        # PNL History tracking
        self.pnl_history: List[Dict] = []
        self.total_realized_pnl = 0.0
        self.next_market_info = "Initializing..."
        
        # Track current market start epoch
        self.current_market_epoch = None
        
        # Bot control state
        self.bot_paused = False
    
    def toggle_pause(self):
        """Toggle the bot's paused state"""
        self.bot_paused = not self.bot_paused
        status = "PAUSED" if self.bot_paused else "RESUMED"
        print(f"🎮 Bot {status}")
        return self.bot_paused
    
    def reset_bot(self):
        """Reset all bot state including PNL history"""
        self.pnl_history = []
        self.total_realized_pnl = 0.0
        self.paper_trader = PaperTrader(starting_balance=1000.0)
        self.bot_paused = False
        print("🔄 Bot RESET - All PNL history and positions cleared")
    
    def calculate_current_market_epoch(self) -> int:
        """Calculate the epoch for the current/next market window.
        
        The epoch in the slug is the START time of the market.
        Markets run every 15 minutes at :00, :15, :30, :45
        """
        now = datetime.now(timezone.utc)
        interval_seconds = self.interval_minutes * 60
        
        # Get current timestamp
        current_ts = int(now.timestamp())
        
        # Find the current window's start time (floor to interval)
        current_window_start = (current_ts // interval_seconds) * interval_seconds
        current_window_end = current_window_start + interval_seconds
        
        # If we're past the end of current window, get next window
        # Or if market is resolved, also get next window
        if current_ts >= current_window_end or self.market_resolved:
            return current_window_start + interval_seconds
        
        return current_window_start
    
    def calculate_next_market_epoch(self) -> int:
        """Calculate epoch for the next upcoming market after current one"""
        current = self.calculate_current_market_epoch()
        return current + (self.interval_minutes * 60)
    
    def generate_event_slug(self, epoch: int) -> str:
        """Generate the event slug for a given epoch timestamp"""
        return f"{self.asset}-updown-{self.interval_minutes}m-{epoch}"
    
    async def discover_and_switch_market(self, session: aiohttp.ClientSession) -> bool:
        """Auto-discover the current market and switch to it if different"""
        target_epoch = self.calculate_current_market_epoch()
        target_slug = self.generate_event_slug(target_epoch)
        
        # Check if current market should be closed and PNL saved
        if self.event_slug and self.event_slug != target_slug:
            # Current market window has ended, save PNL before switching
            if self.paper_trader.market_status != 'resolved':
                # Force close and calculate PNL based on positions
                await self.close_and_save_current_market(session)
        
        if target_slug == self.event_slug and not self.market_resolved:
            return False  # Already on correct market
        
        # Try to fetch the target market
        success = await self.fetch_market_by_slug(session, target_slug)
        
        if success:
            # Switch to new market
            old_slug = self.event_slug
            self.event_slug = target_slug
            self.current_market_epoch = target_epoch
            
            # Reset for new market
            self.reset_for_new_market()
            
            # Fetch the new market data
            await self.fetch_event_data(session)
            
            print(f"🔄 Switched to new market: {target_slug}")
            self.next_market_info = f"Active: {target_slug}"
            return True
        else:
            # Market not available yet, calculate when it should be
            next_start = datetime.fromtimestamp(target_epoch, tz=timezone.utc)
            self.next_market_info = f"Waiting for market at {next_start.strftime('%H:%M:%S')} UTC"
            return False
    
    async def fetch_market_by_slug(self, session: aiohttp.ClientSession, slug: str) -> bool:
        """Try to fetch a specific market by slug"""
        try:
            url = f"{self.GAMMA_API_URL}/events/slug/{slug}"
            async with session.get(url) as response:
                if response.status == 200:
                    event = await response.json()
                    if event:
                        return True
            return False
        except Exception as e:
            return False
    
    async def close_and_save_current_market(self, session: aiohttp.ClientSession):
        """Close current market and save PNL - called when market window ends"""
        if not self.event_slug:
            return
        
        # Check if we have any positions
        pt = self.paper_trader
        if pt.qty_up == 0 and pt.qty_down == 0:
            print(f"📭 Market {self.event_slug} closed with no positions")
            return
        
        # Try to fetch final resolution from API
        await self.fetch_event_data(session)
        
        # If market is resolved, use that outcome
        if self.market_resolved and pt.final_pnl is not None:
            self.save_market_pnl()
            return
        
        # If not resolved yet, estimate PNL based on hedged position
        # For a hedged position: guaranteed payout = min(qty_up, qty_down)
        # PNL = guaranteed_payout - total_cost
        guaranteed_payout = min(pt.qty_up, pt.qty_down)
        total_cost = pt.cost_up + pt.cost_down
        estimated_pnl = guaranteed_payout - total_cost
        
        # Determine likely outcome based on final prices
        outcome = 'HEDGED'
        if pt.qty_up > pt.qty_down:
            outcome = 'UP (unhedged)'
        elif pt.qty_down > pt.qty_up:
            outcome = 'DOWN (unhedged)'
        
        pnl_entry = {
            'slug': self.event_slug,
            'time': datetime.now(timezone.utc).strftime('%H:%M:%S'),
            'outcome': outcome,
            'pnl': estimated_pnl,
            'payout': guaranteed_payout,
            'cost': total_cost,
            'qty_up': pt.qty_up,
            'qty_down': pt.qty_down,
            'status': 'closed'
        }
        
        self.pnl_history.append(pnl_entry)
        self.total_realized_pnl += estimated_pnl
        
        print(f"💰 Market CLOSED: {self.event_slug}")
        print(f"   Positions: {pt.qty_up:.1f} UP / {pt.qty_down:.1f} DOWN")
        print(f"   PNL: ${estimated_pnl:.2f} | Total: ${self.total_realized_pnl:.2f}")
    
    def save_market_pnl(self):
        """Save the PNL from the resolved market to history"""
        if self.paper_trader.final_pnl is None:
            return
        
        pnl_entry = {
            'slug': self.event_slug,
            'time': datetime.now(timezone.utc).strftime('%H:%M:%S'),
            'outcome': self.paper_trader.resolution_outcome or 'Unknown',
            'pnl': self.paper_trader.final_pnl,
            'payout': self.paper_trader.payout,
            'cost': self.paper_trader.cost_up + self.paper_trader.cost_down,
            'qty_up': self.paper_trader.qty_up,
            'qty_down': self.paper_trader.qty_down
        }
        
        self.pnl_history.append(pnl_entry)
        self.total_realized_pnl += self.paper_trader.final_pnl
        
        print(f"💰 Saved PNL: {pnl_entry['pnl']:.2f} | Total: {self.total_realized_pnl:.2f}")
    
    def reset_for_new_market(self):
        """Reset state for a new market"""
        self.up_token_id = None
        self.down_token_id = None
        self.window_start = None
        self.window_end = None
        self.market_closed = False
        self.market_resolved = False
        self.paper_trader = PaperTrader(starting_balance=1000.0)
        
    async def fetch_event_data(self, session: aiohttp.ClientSession):
        """Fetch event data from Gamma API"""
        try:
            url = f"{self.GAMMA_API_URL}/events?slug={self.event_slug}"
            async with session.get(url) as response:
                if response.status == 200:
                    events = await response.json()
                    if events and len(events) > 0:
                        event = events[0]
                        self.market_title = event.get('title', 'Bitcoin Up or Down')
                        
                        # Check if market is closed or resolved
                        self.market_closed = event.get('closed', False)
                        
                        # Parse timestamps - use endDate from API if available
                        end_date_str = event.get('endDate', '')
                        start_time_str = event.get('startTime', '')
                        
                        if end_date_str:
                            try:
                                self.window_end = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                            except:
                                pass
                        
                        if start_time_str:
                            try:
                                self.window_start = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                            except:
                                pass
                        
                        # Fallback to parsing from slug if not set
                        if not self.window_start or not self.window_end:
                            parts = self.event_slug.split('-')
                            if len(parts) >= 4:
                                try:
                                    end_timestamp = int(parts[-1])
                                    start_timestamp = end_timestamp - (15 * 60)
                                    if not self.window_start:
                                        self.window_start = datetime.fromtimestamp(start_timestamp, tz=timezone.utc)
                                    if not self.window_end:
                                        self.window_end = datetime.fromtimestamp(end_timestamp, tz=timezone.utc)
                                except:
                                    pass
                        
                        # Get markets from event
                        markets = event.get('markets', [])
                        if markets:
                            for market in markets:
                                clob_token_ids = market.get('clobTokenIds', '')
                                outcomes = market.get('outcomes', '')
                                outcome_prices = market.get('outcomePrices', '')
                                
                                # Check market status
                                if market.get('closed', False):
                                    self.market_closed = True
                                    self.paper_trader.close_market()
                                
                                # Check for resolution
                                if outcome_prices:
                                    try:
                                        prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                                        # If one price is 1.0 and other is 0.0, market is resolved
                                        if len(prices) >= 2:
                                            p1, p2 = float(prices[0]), float(prices[1])
                                            if p1 >= 0.99 and p2 <= 0.01:
                                                self.market_resolved = True
                                                self.paper_trader.resolve_market('UP')
                                            elif p2 >= 0.99 and p1 <= 0.01:
                                                self.market_resolved = True
                                                self.paper_trader.resolve_market('DOWN')
                                    except:
                                        pass
                                
                                if clob_token_ids and outcomes:
                                    try:
                                        token_ids = json.loads(clob_token_ids) if isinstance(clob_token_ids, str) else clob_token_ids
                                        outcome_list = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
                                        
                                        for i, outcome in enumerate(outcome_list):
                                            if i < len(token_ids):
                                                if outcome.lower() in ['up', 'yes']:
                                                    self.up_token_id = token_ids[i]
                                                elif outcome.lower() in ['down', 'no']:
                                                    self.down_token_id = token_ids[i]
                                    except:
                                        pass
                        return True
            return False
        except Exception as e:
            print(f"Error fetching event data: {e}")
            return False
    
    async def fetch_orderbook(self, session: aiohttp.ClientSession, token_id: str) -> dict:
        """Fetch orderbook for a token"""
        try:
            url = f"{self.CLOB_API_URL}/book?token_id={token_id}"
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
        except:
            pass
        return {}
    
    async def fetch_midpoint(self, session: aiohttp.ClientSession, token_id: str) -> float:
        """Fetch midpoint price"""
        try:
            url = f"{self.CLOB_API_URL}/midpoint?token_id={token_id}"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return float(data.get('mid', 0))
        except:
            pass
        return 0
    
    async def fetch_trades(self, session: aiohttp.ClientSession, token_id: str) -> list:
        """Fetch recent trades"""
        try:
            url = f"{self.CLOB_API_URL}/trades?token_id={token_id}&limit=10"
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
        except:
            pass
        return []
    
    async def broadcast(self, data: dict):
        """Send data to all connected WebSocket clients"""
        if not self.websockets:
            return
        
        message = json.dumps(data)
        dead_sockets = set()
        
        for ws in self.websockets:
            try:
                await ws.send_str(message)
            except:
                dead_sockets.add(ws)
        
        self.websockets -= dead_sockets
    
    async def data_loop(self):
        """Main data fetching loop with auto market discovery"""
        async with aiohttp.ClientSession() as session:
            # Auto-discover initial market
            print(f"🔍 Auto-discovering {self.asset.upper()} markets...")
            await self.discover_and_switch_market(session)
            
            if self.event_slug:
                print(f"📊 Found market: {self.event_slug}")
                await self.fetch_event_data(session)
            
            if not self.up_token_id or not self.down_token_id:
                print("Could not find token IDs, running in demo mode")
            else:
                print(f"Found tokens - UP: {self.up_token_id[:20]}... DOWN: {self.down_token_id[:20]}...")
            
            while self.running:
                try:
                    # Check for market switch every 5 seconds
                    if self.update_count % 5 == 0:
                        switched = await self.discover_and_switch_market(session)
                        if switched:
                            await self.fetch_event_data(session)
                            if self.up_token_id and self.down_token_id:
                                print(f"Found tokens - UP: {self.up_token_id[:20]}... DOWN: {self.down_token_id[:20]}...")
                    
                    # Fetch all data
                    if self.up_token_id and self.down_token_id:
                        results = await asyncio.gather(
                            self.fetch_midpoint(session, self.up_token_id),
                            self.fetch_midpoint(session, self.down_token_id),
                            self.fetch_orderbook(session, self.up_token_id),
                            self.fetch_orderbook(session, self.down_token_id),
                            self.fetch_trades(session, self.up_token_id),
                            self.fetch_trades(session, self.down_token_id),
                            return_exceptions=True
                        )
                        
                        up_mid = results[0] if not isinstance(results[0], Exception) else 0.1
                        down_mid = results[1] if not isinstance(results[1], Exception) else 0.9
                        up_book = results[2] if not isinstance(results[2], Exception) else {}
                        down_book = results[3] if not isinstance(results[3], Exception) else {}
                        up_trades = results[4] if not isinstance(results[4], Exception) else []
                        down_trades = results[5] if not isinstance(results[5], Exception) else []
                    else:
                        # Demo mode
                        import random
                        up_mid = random.uniform(0.08, 0.15)
                        down_mid = 1.0 - up_mid - random.uniform(-0.02, 0.02)
                        
                        up_book = {
                            'bids': [{'price': str(up_mid - 0.01), 'size': str(random.uniform(500, 2000))},
                                     {'price': str(up_mid - 0.02), 'size': str(random.uniform(1000, 5000))},
                                     {'price': str(up_mid - 0.03), 'size': str(random.uniform(500, 1000))}],
                            'asks': [{'price': str(up_mid + 0.01), 'size': str(random.uniform(500, 2000))},
                                     {'price': str(up_mid + 0.02), 'size': str(random.uniform(1000, 5000))},
                                     {'price': str(up_mid + 0.03), 'size': str(random.uniform(500, 1000))}]
                        }
                        down_book = {
                            'bids': [{'price': str(down_mid - 0.01), 'size': str(random.uniform(500, 2000))},
                                     {'price': str(down_mid - 0.02), 'size': str(random.uniform(1000, 5000))},
                                     {'price': str(down_mid - 0.03), 'size': str(random.uniform(500, 1000))}],
                            'asks': [{'price': str(down_mid + 0.01), 'size': str(random.uniform(500, 2000))},
                                     {'price': str(down_mid + 0.02), 'size': str(random.uniform(1000, 5000))},
                                     {'price': str(down_mid + 0.03), 'size': str(random.uniform(500, 1000))}]
                        }
                        
                        up_trades = [{'match_time': time.time() - i * 60, 'side': random.choice(['BUY', 'SELL']),
                                      'price': random.uniform(0.1, 0.2), 'size': random.uniform(50, 300)} for i in range(5)]
                        down_trades = [{'match_time': time.time() - i * 60 - 30, 'side': random.choice(['BUY', 'SELL']),
                                        'price': random.uniform(0.8, 0.9), 'size': random.uniform(50, 300)} for i in range(5)]
                    
                    self.update_count += 1
                    
                    # Check market status periodically
                    if self.update_count % 10 == 0:  # Every 10 updates
                        await self.fetch_event_data(session)
                    
                    # Check if market window has ended
                    now = datetime.now(timezone.utc)
                    if self.window_end and now > self.window_end and not self.market_closed:
                        self.market_closed = True
                        self.paper_trader.close_market()
                        print(f"Market window ended at {self.window_end}")
                    
                    # Run paper trading logic (only if not paused)
                    if self.paper_trader.market_status == 'open' and not self.bot_paused:
                        # Get best ask prices for buying (lowest ask = best price to buy)
                        # Asks are sorted ascending, so first ask is cheapest
                        asks_up = up_book.get('asks', [])
                        asks_down = down_book.get('asks', [])
                        
                        # Find lowest ask price
                        if asks_up:
                            up_ask = min(float(a.get('price', 1.0)) for a in asks_up if a.get('price'))
                        else:
                            up_ask = up_mid if up_mid > 0 else 0.5
                        
                        if asks_down:
                            down_ask = min(float(a.get('price', 1.0)) for a in asks_down if a.get('price'))
                        else:
                            down_ask = down_mid if down_mid > 0 else 0.5
                        
                        # Debug: print status every 10 updates
                        if self.update_count % 10 == 0:
                            import time as time_module
                            pt = self.paper_trader
                            ratio = pt.qty_up / pt.qty_down if pt.qty_down > 0 else (999 if pt.qty_up > 0 else 0)
                            guaranteed = min(pt.qty_up, pt.qty_down)
                            total_cost = pt.cost_up + pt.cost_down
                            locked_pnl = guaranteed - total_cost if guaranteed > 0 else 0
                            
                            # Check unhedged time
                            unhedged_time = 0
                            if pt.first_trade_time > 0 and (pt.qty_up == 0 or pt.qty_down == 0):
                                unhedged_time = time_module.time() - pt.first_trade_time
                            
                            status = "✅ HEDGED" if (pt.qty_up > 0 and pt.qty_down > 0) else f"⚠️ UNHEDGED {unhedged_time:.0f}s"
                            
                            print(f"📊 UP: ${up_ask:.3f} | DOWN: ${down_ask:.3f} | {status}")
                            print(f"   Qty: {pt.qty_up:.1f}U / {pt.qty_down:.1f}D | Ratio: {ratio:.3f}x")
                            print(f"   Pair Cost: ${pt.pair_cost:.3f} | Locked PnL: ${locked_pnl:.2f}")
                            print(f"   Cash: ${pt.cash:.2f} | Trades: {pt.trade_count}")
                        
                        timestamp = datetime.now(timezone.utc).strftime('%H:%M:%S')
                        trades = self.paper_trader.check_and_trade(up_ask, down_ask, timestamp)
                        
                        if trades:
                            for side, price, qty in trades:
                                pt = self.paper_trader
                                print(f"📈 BUY {qty:.1f} {side} @ ${price:.3f} | Pair Cost: ${pt.pair_cost:.4f} | Balance: {pt.qty_up:.0f}U/{pt.qty_down:.0f}D")
                    
                    # Prepare data for broadcast
                    window_time = f"{self.window_start.strftime('%H:%M') if self.window_start else '--:--'} - {self.window_end.strftime('%H:%M') if self.window_end else '--:--'}"
                    
                    data = {
                        'title': self.market_title,
                        'event_slug': self.event_slug or 'Discovering...',
                        'window_time': window_time,
                        'current_time': datetime.now(timezone.utc).strftime('%H:%M:%S'),
                        'update_count': self.update_count,
                        'up_mid': up_mid,
                        'down_mid': down_mid,
                        'up_book': up_book,
                        'down_book': down_book,
                        'up_trades': up_trades,
                        'down_trades': down_trades,
                        'paper_trading': self.paper_trader.get_state(),
                        # PNL History data
                        'pnl_history': self.pnl_history,
                        'total_realized_pnl': self.total_realized_pnl,
                        'next_market_info': self.next_market_info,
                        # Bot control state
                        'bot_paused': self.bot_paused
                    }
                    
                    await self.broadcast(data)
                    
                except Exception as e:
                    print(f"Error in data loop: {e}")
                
                await asyncio.sleep(1)


# Create bot instance
bot = PolymarketWebBot(asset=ASSET, interval_minutes=MARKET_INTERVAL_MINUTES)


async def index_handler(request):
    """Serve the HTML page"""
    return web.Response(text=HTML_TEMPLATE, content_type='text/html')


async def websocket_handler(request):
    """Handle WebSocket connections"""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    bot.websockets.add(ws)
    print(f"WebSocket client connected. Total clients: {len(bot.websockets)}")
    
    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    command = data.get('command')
                    
                    if command == 'toggle_pause':
                        bot.toggle_pause()
                    elif command == 'reset_bot':
                        bot.reset_bot()
                except json.JSONDecodeError:
                    pass
            elif msg.type == aiohttp.WSMsgType.ERROR:
                break
    finally:
        bot.websockets.discard(ws)
        print(f"WebSocket client disconnected. Total clients: {len(bot.websockets)}")
    
    return ws


async def start_background_tasks(app):
    """Start the data fetching loop"""
    app['data_task'] = asyncio.create_task(bot.data_loop())


async def cleanup_background_tasks(app):
    """Stop the data fetching loop"""
    bot.running = False
    app['data_task'].cancel()
    try:
        await app['data_task']
    except asyncio.CancelledError:
        pass


def main():
    app = web.Application()
    app.router.add_get('/', index_handler)
    app.router.add_get('/ws', websocket_handler)
    
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    
    print(f"🤖 Polymarket Web Bot starting...")
    print(f"📊 Asset: {ASSET.upper()} | Interval: {MARKET_INTERVAL_MINUTES}m")
    print(f"🔍 Auto-discovery enabled - will find current market automatically")
    print(f"🌐 Open http://localhost:8080 in your browser")
    print(f"Press Ctrl+C to stop")
    print()
    
    web.run_app(app, host='localhost', port=8080, print=None)


if __name__ == '__main__':
    main()
