#!/usr/bin/env python3
"""
Polymarket Web Bot - Multi-Asset Up or Down Price Tracker
Web-based interface with real-time updates via WebSocket.
Supports multiple assets (BTC, ETH) simultaneously.
"""

import asyncio
import aiohttp
import json
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict
from aiohttp import web
import os

# Assets to track (can be multiple)
ASSETS = os.getenv("ASSETS", "btc,eth").split(",")

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
        
        /* Asset selector buttons */
        .asset-btn {
            background: #1f2937;
            color: #9ca3af;
            border: 2px solid #374151;
            padding: 8px 20px;
            margin: 0 5px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: bold;
            font-size: 1rem;
            transition: all 0.2s;
        }
        
        .asset-btn:hover {
            background: #374151;
            color: #fff;
        }
        
        .asset-btn.active {
            background: #3b82f6;
            color: #fff;
            border-color: #60a5fa;
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
        
        .market-status.sold {
            background: #8b5cf6;
            color: #fff;
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

        .sell-mode-badge {
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: bold;
            margin-left: 10px;
        }

        .sell-mode-badge.on {
            background: #ef4444;
            color: #fff;
        }

        .sell-mode-badge.off {
            background: #374151;
            color: #e5e7eb;
        }

        .sell-mode-alert {
            margin-top: 10px;
            padding: 10px 12px;
            border-radius: 6px;
            font-weight: bold;
            text-align: center;
            background: rgba(239, 68, 68, 0.2);
            border: 1px solid #ef4444;
            color: #fecaca;
            display: none;
        }

        .sell-mode-alert.active {
            display: block;
            animation: pulse 1.5s infinite;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div id="asset-buttons" style="margin-bottom: 10px;"></div>
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
                <div>
                    <span id="market-status" class="market-status open">OPEN</span>
                    <span id="sell-mode-badge" class="sell-mode-badge off">SELL MODE: OFF</span>
                </div>
            </div>

            <div id="sell-mode-alert" class="sell-mode-alert">🚨 SELL MODE ACTIVE — no locked profit after 5m</div>
            
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
            
            <!-- Position Value Tracking -->
            <div class="pair-cost-bar" style="border: 1px solid #22c55e; margin-top: 15px;">
                <div class="pair-cost-header">
                    <span class="pair-cost-label">📊 Position Value vs Cost</span>
                    <span id="value-vs-cost" class="pair-cost-value profit">$0.00</span>
                </div>
                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 10px;">
                    <div style="text-align: center;">
                        <div style="color: #9ca3af; font-size: 0.75rem;">UP Value</div>
                        <div id="up-position-value" style="color: #22c55e; font-weight: bold;">$0.00</div>
                    </div>
                    <div style="text-align: center;">
                        <div style="color: #9ca3af; font-size: 0.75rem;">DOWN Value</div>
                        <div id="down-position-value" style="color: #ef4444; font-weight: bold;">$0.00</div>
                    </div>
                    <div style="text-align: center;">
                        <div style="color: #9ca3af; font-size: 0.75rem;">Total Value</div>
                        <div id="total-position-value" style="color: #fbbf24; font-weight: bold;">$0.00</div>
                    </div>
                </div>
                <div style="margin-top: 10px; padding: 8px; background: rgba(0,0,0,0.3); border-radius: 4px;">
                    <div style="display: flex; justify-content: space-between; font-size: 0.85rem;">
                        <span style="color: #9ca3af;">Total Cost:</span>
                        <span id="total-cost-display" style="color: #ef4444;">$0.00</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 0.85rem; margin-top: 4px;">
                        <span style="color: #9ca3af;">Current Value:</span>
                        <span id="current-value-display" style="color: #22c55e;">$0.00</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 0.9rem; margin-top: 6px; padding-top: 6px; border-top: 1px solid #374151;">
                        <span style="color: #fbbf24; font-weight: bold;">Value Profit:</span>
                        <span id="value-profit-display" style="font-weight: bold;">$0.00</span>
                    </div>
                </div>
            </div>
            
            <div style="color: #9ca3af; font-size: 0.8rem; margin-bottom: 10px; margin-top: 15px;">📜 Trade Log</div>
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
        
        // Multi-asset state management
        let assetData = {};  // Store data for each asset
        let currentAsset = 'btc';  // Currently displayed asset
        
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            const asset = data.asset || 'unknown';
            
            // Store data for this asset
            assetData[asset] = data;
            
            // Update asset indicator if we have both
            updateAssetIndicators();
            
            // Only update display if this is the currently selected asset
            if (asset === currentAsset) {
                updateDisplay(data);
                updatePaperTrading(data);
            }
        };
        
        function switchAsset(asset) {
            currentAsset = asset;
            // Update buttons
            document.querySelectorAll('.asset-btn').forEach(btn => {
                btn.classList.remove('active');
            });
            document.getElementById('asset-' + asset).classList.add('active');
            
            // Update display with stored data
            if (assetData[asset]) {
                updateDisplay(assetData[asset]);
                updatePaperTrading(assetData[asset]);
            }
        }
        
        function updateAssetIndicators() {
            const assets = Object.keys(assetData);
            const container = document.getElementById('asset-buttons');
            if (!container || container.dataset.initialized) return;
            
            let html = '';
            assets.forEach(asset => {
                const isActive = asset === currentAsset ? 'active' : '';
                html += `<button id="asset-${asset}" class="asset-btn ${isActive}" onclick="switchAsset('${asset}')">${asset.toUpperCase()}</button>`;
            });
            container.innerHTML = html;
            container.dataset.initialized = 'true';
        }
        
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

            // Update sell mode badge
            const sellOn = !!pt.sell_mode;
            const sellModeEl = document.getElementById('sell-mode-badge');
            if (sellModeEl) {
                sellModeEl.textContent = sellOn ? 'SELL MODE: ON' : 'SELL MODE: OFF';
                sellModeEl.className = 'sell-mode-badge ' + (sellOn ? 'on' : 'off');
            }

            const sellAlertEl = document.getElementById('sell-mode-alert');
            if (sellAlertEl) {
                sellAlertEl.className = sellOn ? 'sell-mode-alert active' : 'sell-mode-alert';
            }
            
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
            
            // Update position value tracking
            const upPosValue = pt.current_up_value || 0;
            const downPosValue = pt.current_down_value || 0;
            const totalPosValue = pt.current_total_value || 0;
            const valueVsCost = pt.value_vs_cost || 0;
            
            document.getElementById('up-position-value').textContent = '$' + upPosValue.toFixed(2);
            document.getElementById('down-position-value').textContent = '$' + downPosValue.toFixed(2);
            document.getElementById('total-position-value').textContent = '$' + totalPosValue.toFixed(2);
            document.getElementById('total-cost-display').textContent = '$' + totalCost.toFixed(2);
            document.getElementById('current-value-display').textContent = '$' + totalPosValue.toFixed(2);
            
            const valueProfitEl = document.getElementById('value-profit-display');
            valueProfitEl.textContent = (valueVsCost >= 0 ? '+' : '') + '$' + valueVsCost.toFixed(2);
            valueProfitEl.style.color = valueVsCost >= 0 ? '#22c55e' : '#ef4444';
            
            const valueVsCostEl = document.getElementById('value-vs-cost');
            valueVsCostEl.textContent = (valueVsCost >= 0 ? '+' : '') + '$' + valueVsCost.toFixed(2);
            valueVsCostEl.className = 'pair-cost-value ' + (valueVsCost >= 0 ? 'profit' : 'loss');
            
            // Show final PnL if market is resolved OR sold
            if ((pt.market_status === 'resolved' || pt.market_status === 'sold') && pt.final_pnl !== undefined && pt.final_pnl !== null) {
                document.getElementById('final-pnl-section').style.display = 'block';
                const finalPnlEl = document.getElementById('final-pnl');
                finalPnlEl.textContent = (pt.final_pnl >= 0 ? '+' : '') + '$' + pt.final_pnl.toFixed(2);
                finalPnlEl.className = 'value ' + (pt.final_pnl >= 0 ? 'profit' : 'loss');
                const statusText = pt.market_status === 'sold' ? 'Positions sold' : 'Market resolved';
                document.getElementById('resolution-outcome').textContent = 
                    statusText + ': ' + pt.resolution_outcome + ' | Payout: $' + pt.payout.toFixed(2);
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
        
        # === GABAGOOL STRATEGY v6: GUARANTEED PROFIT ===
        # THE ONLY WAY TO GUARANTEE PROFIT: pair_cost < $1.00 with balanced positions
        # Formula: avg_UP + avg_DOWN < $1.00 means we ALWAYS profit at settlement
        # REALITY: Polymarket spread is often ~1.01, so we accept slight risk
        
        self.target_pair_cost = 0.96    # Target pair cost for good profit margin
        self.max_pair_cost = 0.995      # NEVER exceed $1.00 - this is the profit threshold!
        self.cheap_threshold = 0.48     # "Cheap" price to start buying
        self.force_balance_threshold = 0.80  # Buy other side at this price if pair_cost is OK
        self.max_balance_price = 0.88   # Absolute max to pay for balancing (emergency) - tighter limit
        self.very_cheap_threshold = 0.40 # Super cheap - accumulate more aggressively
        self.min_trade_size = 3.0       # Minimum trade size
        self.max_single_trade = 12.0    # Max single trade
        self.cooldown_seconds = 4       # Seconds between trades
        self.last_trade_time = 0
        self.first_trade_time = 0       # When we made our first trade
        self.force_balance_after_seconds = 60  # Force balance after 60 seconds!
        self.initial_trade_usd = 35.0   # Initial trade size ($30-40)
        self.max_loss_per_market = 50.0 # Max loss per market
        self.sell_mode = False
        self.sell_mode_trigger_seconds = 300  # 5 minutes
        self.sell_mode_min_profit = 1.0
        self.market_start_time = None
        
        # === VALUE-BASED PROFIT TAKING ===
        # Sell when position value exceeds total cost by this amount
        self.value_profit_threshold = 2.00  # Sell when value > cost + $2.00 (absolute)
        self.min_profit_pct = 0.03  # Or when profit > 3% of cost AND > $1.00 minimum
        
        # Track current position values (updated each tick)
        self.current_up_value = 0.0
        self.current_down_value = 0.0
        self.current_total_value = 0.0
        
        # === BALANCE IS KING ===
        # Without balance, there is NO guaranteed profit
        # BUT we allow temporary imbalance to achieve pair_cost < $1.00
        self.max_qty_ratio = 1.35       # Normal max imbalance (35%)
        self.emergency_ratio = 2.0      # Allow HIGH imbalance when fixing pair_cost > $1.00
        self.recovery_ratio = 2.5       # Max ratio when actively recovering (EXTREME)
        self.target_qty_ratio = 1.0     # Perfect balance
        self.rebalance_trigger = 1.15   # Start rebalancing when ratio exceeds this
        self.max_position_pct = 0.50    # Max 50% of balance per market (more aggressive)
        
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

    def set_market_start_time(self, start_time: Optional[datetime]):
        if start_time:
            self.market_start_time = start_time.timestamp()
        else:
            self.market_start_time = None

    def update_sell_mode(self, now_ts: float, market_elapsed: Optional[float] = None):
        if self.sell_mode:
            return
        elapsed = market_elapsed
        if elapsed is None and self.market_start_time:
            elapsed = now_ts - self.market_start_time
        if elapsed is None:
            return
        # Only trigger sell mode if we have positions but no locked profit
        has_positions = self.qty_up > 0 or self.qty_down > 0
        if has_positions and elapsed >= self.sell_mode_trigger_seconds and self.locked_profit <= 0:
            self.sell_mode = True
            print("🚨 SELL MODE ACTIVE (no locked profit after 5m)")

    def unrealized_pnl(self, up_price: float, down_price: float) -> float:
        total_cost = self.cost_up + self.cost_down
        current_value = (self.qty_up * up_price) + (self.qty_down * down_price)
        return current_value - total_cost
    
    def update_position_values(self, up_bid: float, down_bid: float):
        """Update current position values based on bid prices (what we could sell for)"""
        self.current_up_value = self.qty_up * up_bid if up_bid > 0 else 0.0
        self.current_down_value = self.qty_down * down_bid if down_bid > 0 else 0.0
        self.current_total_value = self.current_up_value + self.current_down_value
    
    def should_take_profit(self) -> tuple:
        """Check if we should sell positions to lock in profit based on current value.
        
        Returns (should_sell, reason)
        """
        if self.qty_up == 0 and self.qty_down == 0:
            return False, "No positions"
        
        total_cost = self.cost_up + self.cost_down
        if total_cost == 0:
            return False, "No cost"
        
        profit = self.current_total_value - total_cost
        profit_pct = profit / total_cost if total_cost > 0 else 0
        
        # Check absolute profit threshold ($1.50 or more)
        if profit >= self.value_profit_threshold:
            return True, f"Value profit: ${profit:.2f} (${self.current_total_value:.2f} > ${total_cost:.2f})"
        
        # Check percentage profit threshold (3% or more AND at least $1.00)
        if profit_pct >= self.min_profit_pct and profit >= 1.00:
            return True, f"Pct profit: {profit_pct*100:.1f}% (${profit:.2f})"
        
        return False, f"Profit ${profit:.2f} below threshold (need ${self.value_profit_threshold:.2f} or {self.min_profit_pct*100:.0f}%)"

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
        """Check if a buy is allowed in sell mode.
        
        In sell mode, we still allow trades that:
        1. Lock in positive profit (locked_profit > 0 after trade)
        2. Improve the pair cost (even if profit not yet locked)
        3. Improve locked profit compared to current locked profit
        
        This allows the bot to keep improving positions during price swings.
        """
        if not self.sell_mode:
            return True, ""
        
        locked_after = self.locked_profit_after_buy(side, price, qty)
        
        # If this trade results in positive locked profit, always allow
        if locked_after > 0:
            return True, f"Sell mode: locks ${locked_after:.2f} profit"
        
        # If we already have locked profit and this improves it, allow
        if self.locked_profit > 0 and locked_after > self.locked_profit:
            return True, f"Sell mode: improves locked profit ${self.locked_profit:.2f}→${locked_after:.2f}"
        
        # If this improves pair cost AND we have balanced positions, allow
        # (this can help swing towards profit during price movements)
        if self.qty_up > 0 and self.qty_down > 0 and self.improves_pair_cost(side, price, qty):
            _, new_pair_cost = self.simulate_buy(side, price, qty)
            if new_pair_cost < self.pair_cost - 0.005:  # At least 0.5 cent improvement
                return True, f"Sell mode: improves pair ${self.pair_cost:.3f}→${new_pair_cost:.3f}"
        
        return False, "Sell mode: trade doesn't improve position"

    def execute_sell_all(self, up_price: float, down_price: float, timestamp: str, reason: str) -> bool:
        """Sell all positions and calculate final PnL.
        
        This also records the final PnL so it can be saved to history
        even when selling before market resolution.
        """
        import time as time_module
        proceeds = 0.0
        sold_any = False
        
        # Store original quantities and costs for PnL calculation
        original_qty_up = self.qty_up
        original_qty_down = self.qty_down
        original_cost_up = self.cost_up
        original_cost_down = self.cost_down
        total_cost = original_cost_up + original_cost_down

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
        self.last_trade_time = time_module.time()
        
        # Calculate and store final PnL from the sale
        self.final_pnl = proceeds - total_cost
        self.payout = proceeds
        self.resolution_outcome = f"{reason} (sold)"
        # Note: Keep qty values for history, restore them temporarily for the pnl entry
        self._sold_qty_up = original_qty_up
        self._sold_qty_down = original_qty_down
        self._sold_cost = total_cost

        if len(self.trade_log) > 20:
            self.trade_log = self.trade_log[-20:]

        return True
    
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
        GABAGOOL STRATEGY v6: GUARANTEED PROFIT
        
        THE ONLY WAY TO GUARANTEE PROFIT:
        - pair_cost (avg_UP + avg_DOWN) < $1.00
        - qty_UP ≈ qty_DOWN (balanced positions)
        
        Example: 100 UP @ $0.30 + 100 DOWN @ $0.65 = $95 cost → $100 payout = $5 GUARANTEED
        
        Strategy:
        1. Buy cheap side first (< $0.45)
        2. MUST buy other side to lock in profit (even if expensive)
        3. Keep pair_cost under $0.98 at all times
        4. Cost average to improve pair_cost when possible
        """
        import time as time_module
        
        if self.market_status != 'open':
            return False, 0, "Market not open"
        
        now = time_module.time()
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

        if self.sell_mode and my_qty == 0 and other_qty == 0:
            return False, 0, "Sell mode: waiting for lockable profit"
        
        # === POSITION SIZE LIMIT ===
        total_spent = self.cost_up + self.cost_down
        max_total_spend = self.starting_balance * self.max_position_pct
        remaining_budget = max_total_spend - total_spent
        
        # Allow emergency balance even if over budget
        if remaining_budget <= self.min_trade_size and not is_emergency and not (my_qty == 0 and other_qty > 0):
            return False, 0, f"Position limit reached (spent ${total_spent:.0f})"
        
        # === FIRST TRADE: Only start if we can get good pair_cost ===
        if my_qty == 0 and other_qty == 0:
            if price > self.cheap_threshold:
                return False, 0, f"First trade needs price < ${self.cheap_threshold}"
            
            # CRITICAL: Check if the OTHER side would give us good pair_cost
            potential_pair_cost = price + other_price
            if potential_pair_cost > self.max_pair_cost:
                return False, 0, f"Pair would be ${potential_pair_cost:.2f} > ${self.max_pair_cost} - waiting"
            
            max_spend = min(self.initial_trade_usd, self.max_single_trade, remaining_budget, self.cash)
            qty = max_spend / price
            self.first_trade_time = now
            allowed, reason = self.sell_mode_allows_buy(side, price, qty)
            if not allowed:
                return False, 0, reason
            return True, qty, f"🎯 First trade (pair potential: ${potential_pair_cost:.2f})"
        
        # === CRITICAL: MUST BALANCE TO LOCK PROFIT ===
        if my_qty == 0 and other_qty > 0:
            time_unhedged = now - self.first_trade_time if self.first_trade_time > 0 else 0
            
            # Calculate what pair_cost would be if we buy at current price
            potential_pair_cost = other_avg + price
            
            # Determine price threshold based on urgency and pair_cost
            if time_unhedged > self.force_balance_after_seconds:
                # Force balance - accept higher prices
                if potential_pair_cost < self.max_pair_cost:
                    price_threshold = self.max_balance_price
                    reason = f"🚨 FORCE BALANCE ({time_unhedged:.0f}s unhedged)"
                else:
                    return False, 0, f"🚨 Pair cost ${potential_pair_cost:.2f} too high even for emergency"
            elif potential_pair_cost < self.target_pair_cost:
                # Great opportunity - pair_cost would be good
                price_threshold = self.force_balance_threshold
                reason = f"✅ GOOD PAIR COST (${potential_pair_cost:.2f})"
            else:
                # Wait for better price
                price_threshold = self.cheap_threshold
                reason = "⏳ Waiting for better price"
            
            if price > price_threshold:
                return False, 0, f"Need {side} < ${price_threshold:.2f} (pair would be ${potential_pair_cost:.2f})"
            
            # Buy to match other side for perfect balance - DYNAMIC SIZING
            # Calculate exact quantity needed for 1:1 balance
            needed_qty = other_qty
            needed_cost = needed_qty * price
            
            # Limit by available cash and budget
            max_affordable = min(self.cash * 0.3, remaining_budget + 20)
            
            if needed_cost <= max_affordable:
                # We can afford perfect balance - use exact quantity
                qty = needed_qty
            else:
                # Can't afford full balance - buy what we can
                qty = max_affordable / price
            
            # Ensure minimum trade size
            if qty * price < self.min_trade_size:
                qty = self.min_trade_size / price
            
            allowed, reason_block = self.sell_mode_allows_buy(side, price, qty)
            if not allowed:
                return False, 0, reason_block
            return True, qty, reason
        
        # === BOTH SIDES HAVE POSITIONS - OPTIMIZE PAIR COST ===
        current_pair_cost = self.pair_cost
        ratio = my_qty / other_qty if other_qty > 0 else 1.0
        
        # === RECOVERY MODE: When pair_cost > $1.00, be VERY aggressive ===
        # The ONLY thing that matters is getting pair_cost under $1.00
        # We don't care about temporary locked_profit loss!
        recovery_mode = current_pair_cost >= 1.0
        
        # Dynamic ratio limit based on how critical the situation is
        if recovery_mode:
            # The worse the pair_cost, the more imbalance we allow
            if current_pair_cost >= 1.05:
                effective_max_ratio = self.recovery_ratio  # 2.5x - extreme
            elif current_pair_cost >= 1.02:
                effective_max_ratio = self.emergency_ratio  # 2.0x - high
            else:
                effective_max_ratio = 1.80  # Getting better but still aggressive
        else:
            effective_max_ratio = self.max_qty_ratio  # 1.35x - normal
        
        # Hard block at effective max ratio
        if ratio >= effective_max_ratio:
            return False, 0, f"BLOCKED: {side} at max ratio ({ratio:.2f}x, limit {effective_max_ratio:.2f}x)"
        
        max_qty_allowed = other_qty * effective_max_ratio - my_qty
        if max_qty_allowed <= 0:
            return False, 0, "At ratio limit"
        
        # === RECOVERY MODE: AGGRESSIVE COST AVERAGING ===
        # When pair_cost > $1.00, we need to get it under $1.00 FAST
        # Accept any trade that improves pair_cost, even at the expense of balance
        if recovery_mode and price < my_avg:
            # In recovery, allow MUCH larger trades to fix the situation faster
            spend_pct = 0.15 if current_pair_cost >= 1.02 else 0.10
            max_spend = min(self.cash * spend_pct, self.max_single_trade * 2, remaining_budget + 50)  # Allow overspend
            qty = min(max_spend / price, max_qty_allowed)
            
            if qty * price >= self.min_trade_size:
                new_avg, new_pair_cost = self.simulate_buy(side, price, qty)
                if new_pair_cost < current_pair_cost:
                    improvement = current_pair_cost - new_pair_cost
                    
                    if new_pair_cost < 1.0:
                        # SUCCESS! This gets us under $1.00
                        allowed, reason_block = self.sell_mode_allows_buy(side, price, qty)
                        if not allowed:
                            return False, 0, reason_block
                        return True, qty, f"🎯 RECOVERY SUCCESS: pair ${current_pair_cost:.3f}→${new_pair_cost:.3f} (UNDER $1.00!)"
                    
                    if improvement >= 0.002:  # Even tiny improvements count in recovery
                        allowed, reason_block = self.sell_mode_allows_buy(side, price, qty)
                        if not allowed:
                            return False, 0, reason_block
                        return True, qty, f"🚨 RECOVERY: pair ${current_pair_cost:.3f}→${new_pair_cost:.3f} (-${improvement:.3f})"
        
        # === NORMAL MODE: COST AVERAGING ===
        # Only buy if new price < current avg (improves our average)
        if not recovery_mode and price < my_avg:
            # Standard conservative trading
            spend_pct = 0.04
            max_spend = min(self.cash * spend_pct, self.max_single_trade, remaining_budget)
            qty = min(max_spend / price, max_qty_allowed)
            
            if qty * price >= self.min_trade_size:
                new_avg, new_pair_cost = self.simulate_buy(side, price, qty)
                if new_pair_cost < current_pair_cost:
                    improvement = current_pair_cost - new_pair_cost
                    
                    # Normal case: require both pair cost and locked profit improvement
                    if self.improves_pair_cost(side, price, qty) and self.improves_locked_profit(side, price, qty):
                        allowed, reason_block = self.sell_mode_allows_buy(side, price, qty)
                        if not allowed:
                            return False, 0, reason_block
                        return True, qty, f"📉 IMPROVE: pair ${current_pair_cost:.3f}→${new_pair_cost:.3f} (-${improvement:.3f})"
        
        # === REBALANCING: Buy lagging side ===
        if ratio < 0.92:  # We're behind - catch up
            price_threshold = self.max_balance_price if recovery_mode else self.force_balance_threshold
            if price <= price_threshold:
                # DYNAMIC SIZING: Calculate exact quantity needed to reach 1:1 balance
                needed_qty = other_qty - my_qty  # Exact difference to balance
                needed_cost = needed_qty * price
                
                # Limit by available budget
                spend_pct = 0.10 if recovery_mode else 0.05
                max_affordable = min(self.cash * spend_pct, self.max_single_trade, remaining_budget)
                
                if needed_cost <= max_affordable:
                    # We can afford exact balance - use precise quantity
                    qty = min(needed_qty, max_qty_allowed)
                else:
                    # Buy what we can afford
                    qty = min(max_affordable / price, max_qty_allowed)
                
                # Ensure minimum trade size
                if qty * price < self.min_trade_size:
                    qty = max(self.min_trade_size / price, qty)
                
                if qty * price >= self.min_trade_size:
                    new_avg, new_pair_cost = self.simulate_buy(side, price, qty)
                    pair_cost_ok = new_pair_cost <= self.max_pair_cost
                    pair_cost_improving = new_pair_cost < current_pair_cost
                    
                    # In recovery mode, just check if it improves pair_cost
                    # In normal mode, require both pair_cost AND locked_profit improvement
                    should_trade = (recovery_mode and pair_cost_improving) or \
                                   (pair_cost_ok and self.improves_pair_cost(side, price, qty) and self.improves_locked_profit(side, price, qty))
                    
                    if should_trade:
                        allowed, reason_block = self.sell_mode_allows_buy(side, price, qty)
                        if not allowed:
                            return False, 0, reason_block
                        prefix = "🚨" if recovery_mode else "⚖️"
                        return True, qty, f"{prefix} REBALANCE: ratio {ratio:.2f}→{(my_qty+qty)/other_qty:.2f}"
        
        # === CHEAP ACCUMULATION: Very cheap prices ===
        if price < self.very_cheap_threshold and ratio < 1.1:
            spend_pct = 0.08 if recovery_mode else 0.04
            max_spend = min(self.cash * spend_pct, self.max_single_trade, remaining_budget)
            qty = min(max_spend / price, max_qty_allowed)
            
            if qty * price >= self.min_trade_size:
                new_avg, new_pair_cost = self.simulate_buy(side, price, qty)
                pair_cost_improving = new_pair_cost < current_pair_cost
                
                should_trade = (recovery_mode and pair_cost_improving) or \
                               (new_pair_cost <= self.max_pair_cost and self.improves_pair_cost(side, price, qty) and self.improves_locked_profit(side, price, qty))
                
                if should_trade:
                    allowed, reason_block = self.sell_mode_allows_buy(side, price, qty)
                    if not allowed:
                        return False, 0, reason_block
                    prefix = "🚨" if recovery_mode else "🔥"
                    return True, qty, f"{prefix} CHEAP @ ${price:.3f}"
        
        # === STANDARD BUYING ===
        if ratio <= 1.0 and price < self.cheap_threshold and not recovery_mode:
            max_spend = min(self.cash * 0.03, self.max_single_trade, remaining_budget)
            qty = min(max_spend / price, max_qty_allowed)
            
            if qty * price >= self.min_trade_size:
                new_avg, new_pair_cost = self.simulate_buy(side, price, qty)
                if new_pair_cost <= self.max_pair_cost and self.improves_pair_cost(side, price, qty) and self.improves_locked_profit(side, price, qty):
                    allowed, reason_block = self.sell_mode_allows_buy(side, price, qty)
                    if not allowed:
                        return False, 0, reason_block
                    return True, qty, f"OK (${price:.3f})"
        
        return False, 0, f"{side} ${price:.3f}: no opportunity"
    
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
    
    def check_and_trade(self, up_price: float, down_price: float, timestamp: str, up_bid: Optional[float] = None, down_bid: Optional[float] = None, market_elapsed: Optional[float] = None):
        """
        GABAGOOL v6: GUARANTEED PROFIT STRATEGY
        
        Priority:
        0. VALUE-BASED PROFIT TAKING: Sell if position value > total cost
        1. BALANCE FIRST: If one side has no position, buy it to lock profit
        2. COST AVERAGE: If price < our avg, buy to improve pair_cost
        3. REBALANCE: Keep qty ratio near 1.0
        4. ACCUMULATE: Buy very cheap prices
        """
        import time as time_module
        trades_made = []
        now_ts = time_module.time()
        self.update_sell_mode(now_ts, market_elapsed)
        sell_up_price = up_bid if up_bid and up_bid > 0 else up_price
        sell_down_price = down_bid if down_bid and down_bid > 0 else down_price
        
        # Update position values for tracking
        self.update_position_values(sell_up_price, sell_down_price)
        
        unrealized = self.unrealized_pnl(sell_up_price, sell_down_price)

        # === PRIORITY 0: MAX LOSS PROTECTION ===
        if unrealized <= -self.max_loss_per_market and (self.qty_up > 0 or self.qty_down > 0):
            if self.execute_sell_all(sell_up_price, sell_down_price, timestamp, "Max loss"):
                self.market_status = 'sold'
            return trades_made
        
        # === PRIORITY 0.5: VALUE-BASED PROFIT TAKING ===
        # If current position value exceeds total cost, sell to lock profit!
        should_sell, sell_reason = self.should_take_profit()
        if should_sell:
            print(f"💰 PROFIT TAKING: {sell_reason}")
            if self.execute_sell_all(sell_up_price, sell_down_price, timestamp, sell_reason):
                self.market_status = 'sold'
            return trades_made

        if self.sell_mode:
            # In sell mode with positive unrealized profit, sell to lock it in
            if unrealized >= self.sell_mode_min_profit:
                if self.execute_sell_all(sell_up_price, sell_down_price, timestamp, "Sell mode profit"):
                    self.market_status = 'sold'
                return trades_made
            # NOTE: Don't return here! Continue to check for opportunities to improve position
        
        # === PRIORITY 1: BALANCE - Lock in guaranteed profit ===
        # If we have position on one side but not other, we MUST balance
        if (self.qty_up > 0 and self.qty_down == 0):
            # Need to buy DOWN to lock profit
            should, qty, reason = self.should_buy('DOWN', down_price, up_price, is_rebalance=True)
            if should:
                if self.execute_buy('DOWN', down_price, qty, timestamp):
                    trades_made.append(('DOWN', down_price, qty))
                    print(f"🔒 LOCK PROFIT: {reason}")
                    return trades_made
            else:
                # Report why we can't balance
                time_unhedged = time_module.time() - self.first_trade_time if self.first_trade_time > 0 else 0
                potential_pair = self.avg_up + down_price
                print(f"⏳ Waiting for DOWN: ${down_price:.3f} (pair would be ${potential_pair:.2f}) [{time_unhedged:.0f}s]")
                return trades_made
        
        if (self.qty_down > 0 and self.qty_up == 0):
            # Need to buy UP to lock profit
            should, qty, reason = self.should_buy('UP', up_price, down_price, is_rebalance=True)
            if should:
                if self.execute_buy('UP', up_price, qty, timestamp):
                    trades_made.append(('UP', up_price, qty))
                    print(f"🔒 LOCK PROFIT: {reason}")
                    return trades_made
            else:
                time_unhedged = time_module.time() - self.first_trade_time if self.first_trade_time > 0 else 0
                potential_pair = self.avg_down + up_price
                print(f"⏳ Waiting for UP: ${up_price:.3f} (pair would be ${potential_pair:.2f}) [{time_unhedged:.0f}s]")
                return trades_made
        
        # === PRIORITY 2: REBALANCE if imbalanced ===
        if self.qty_up > 0 and self.qty_down > 0:
            ratio_up = self.qty_up / self.qty_down
            ratio_down = self.qty_down / self.qty_up
            
            if ratio_up > self.rebalance_trigger:  # UP ahead, need DOWN
                should, qty, reason = self.should_buy('DOWN', down_price, up_price, is_rebalance=True)
                if should:
                    if self.execute_buy('DOWN', down_price, qty, timestamp):
                        trades_made.append(('DOWN', down_price, qty))
                        print(f"⚖️ REBALANCE: {reason}")
                return trades_made
            
            if ratio_down > self.rebalance_trigger:  # DOWN ahead, need UP
                should, qty, reason = self.should_buy('UP', up_price, down_price, is_rebalance=True)
                if should:
                    if self.execute_buy('UP', up_price, qty, timestamp):
                        trades_made.append(('UP', up_price, qty))
                        print(f"⚖️ REBALANCE: {reason}")
                return trades_made
        
        # === PRIORITY 3: COST AVERAGE - Improve pair_cost ===
        if self.qty_up > 0 and self.qty_down > 0:
            # Check if either price is below our average (opportunity to improve)
            if up_price < self.avg_up:
                should, qty, reason = self.should_buy('UP', up_price, down_price)
                if should:
                    if self.execute_buy('UP', up_price, qty, timestamp):
                        trades_made.append(('UP', up_price, qty))
                        print(f"📉 {reason}")
                        return trades_made
            
            if down_price < self.avg_down:
                should, qty, reason = self.should_buy('DOWN', down_price, up_price)
                if should:
                    if self.execute_buy('DOWN', down_price, qty, timestamp):
                        trades_made.append(('DOWN', down_price, qty))
                        print(f"📉 {reason}")
                        return trades_made
        
        # === PRIORITY 4: FIRST TRADE - Start position ===
        if self.qty_up == 0 and self.qty_down == 0:
            # Pick the cheaper side to start
            if up_price < down_price:
                should, qty, reason = self.should_buy('UP', up_price, down_price)
                if should:
                    if self.execute_buy('UP', up_price, qty, timestamp):
                        trades_made.append(('UP', up_price, qty))
                        print(f"🎯 START: {reason}")
            else:
                should, qty, reason = self.should_buy('DOWN', down_price, up_price)
                if should:
                    if self.execute_buy('DOWN', down_price, qty, timestamp):
                        trades_made.append(('DOWN', down_price, qty))
                        print(f"🎯 START: {reason}")
            return trades_made
        
        # === PRIORITY 5: ACCUMULATE - Very cheap prices ===
        if self.qty_up > 0 and self.qty_down > 0:
            if up_price < self.very_cheap_threshold:
                should, qty, reason = self.should_buy('UP', up_price, down_price)
                if should:
                    if self.execute_buy('UP', up_price, qty, timestamp):
                        trades_made.append(('UP', up_price, qty))
                        print(f"🔥 {reason}")
                        return trades_made
            
            if down_price < self.very_cheap_threshold:
                should, qty, reason = self.should_buy('DOWN', down_price, up_price)
                if should:
                    if self.execute_buy('DOWN', down_price, qty, timestamp):
                        trades_made.append(('DOWN', down_price, qty))
                        print(f"🔥 {reason}")
                        return trades_made
        
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
        # Use stored sold quantities if available for display consistency
        qty_up = getattr(self, '_sold_qty_up', self.qty_up) if self.market_status == 'sold' else self.qty_up
        qty_down = getattr(self, '_sold_qty_down', self.qty_down) if self.market_status == 'sold' else self.qty_down
        
        total_cost = self.cost_up + self.cost_down
        
        return {
            'cash': self.cash,
            'qty_up': qty_up,
            'qty_down': qty_down,
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
            'payout': self.payout,
            'sell_mode': self.sell_mode,
            # Position value tracking
            'current_up_value': self.current_up_value,
            'current_down_value': self.current_down_value,
            'current_total_value': self.current_total_value,
            'total_cost': total_cost,
            'value_vs_cost': self.current_total_value - total_cost if total_cost > 0 else 0.0
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
        self._last_saved_slug: Optional[str] = None
        
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
        
        # Check if positions were already sold (market_status == 'sold')
        if pt.market_status == 'sold' and pt.final_pnl is not None:
            self.save_market_pnl()
            return
        
        if pt.qty_up == 0 and pt.qty_down == 0:
            # Check if we have stored sold quantities (from execute_sell_all)
            if hasattr(pt, '_sold_qty_up') and (pt._sold_qty_up > 0 or getattr(pt, '_sold_qty_down', 0) > 0):
                self.save_market_pnl()
            else:
                print(f"📭 Market {self.event_slug} closed with no positions")
            return
        
        # Try to fetch final resolution from API
        await self.fetch_event_data(session)
        
        # If market is resolved, use that outcome
        if self.market_resolved and pt.final_pnl is not None:
            self.save_market_pnl()
            return
        
        # If not resolved yet, estimate PNL by liquidating at best bids
        up_bid = 0.0
        down_bid = 0.0
        if self.up_token_id:
            up_book = await self.fetch_orderbook(session, self.up_token_id)
            if up_book and up_book.get('bids'):
                up_bid = max(float(b.get('price', 0.0)) for b in up_book.get('bids', []) if b.get('price'))

        if self.down_token_id:
            down_book = await self.fetch_orderbook(session, self.down_token_id)
            if down_book and down_book.get('bids'):
                down_bid = max(float(b.get('price', 0.0)) for b in down_book.get('bids', []) if b.get('price'))

        liquidation_value = (pt.qty_up * up_bid) + (pt.qty_down * down_bid)
        if liquidation_value == 0 and (pt.qty_up > 0 or pt.qty_down > 0):
            liquidation_value = min(pt.qty_up, pt.qty_down)
        total_cost = pt.cost_up + pt.cost_down
        estimated_pnl = liquidation_value - total_cost
        
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
            'payout': liquidation_value,
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
        """Save the PNL from the resolved or sold market to history"""
        if not self.event_slug:
            return
        if self._last_saved_slug == self.event_slug:
            return  # Already saved
        if self.paper_trader.final_pnl is None:
            return
        
        pt = self.paper_trader
        
        # Use stored sold quantities if available (from execute_sell_all)
        qty_up = getattr(pt, '_sold_qty_up', pt.qty_up)
        qty_down = getattr(pt, '_sold_qty_down', pt.qty_down)
        cost = getattr(pt, '_sold_cost', pt.cost_up + pt.cost_down)
        
        pnl_entry = {
            'slug': self.event_slug,
            'time': datetime.now(timezone.utc).strftime('%H:%M:%S'),
            'outcome': pt.resolution_outcome or 'Unknown',
            'pnl': pt.final_pnl,
            'payout': pt.payout,
            'cost': cost,
            'qty_up': qty_up,
            'qty_down': qty_down,
            'status': 'sold' if 'sold' in str(pt.resolution_outcome) else 'resolved'
        }
        
        self.pnl_history.append(pnl_entry)
        self.total_realized_pnl += pt.final_pnl
        self._last_saved_slug = self.event_slug
        
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
        self.paper_trader.set_market_start_time(None)
        
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

                        self.paper_trader.set_market_start_time(self.window_start)
                        
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
                                
                                # If market is closed, resolved, or sold, save PNL if not already saved
                                try:
                                    if (self.market_closed or self.market_resolved or self.paper_trader.market_status == 'sold') and self.event_slug and self._last_saved_slug != self.event_slug:
                                        # Save PNL if available (resolved or sold)
                                        if self.paper_trader.final_pnl is not None:
                                            self.save_market_pnl()
                                        elif self.market_resolved or self.market_closed:
                                            await self.close_and_save_current_market(session)
                                except Exception:
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
                        bids_up = up_book.get('bids', [])
                        bids_down = down_book.get('bids', [])
                        
                        # Find lowest ask price
                        if asks_up:
                            up_ask = min(float(a.get('price', 1.0)) for a in asks_up if a.get('price'))
                        else:
                            up_ask = up_mid if up_mid > 0 else 0.5
                        
                        if asks_down:
                            down_ask = min(float(a.get('price', 1.0)) for a in asks_down if a.get('price'))
                        else:
                            down_ask = down_mid if down_mid > 0 else 0.5

                        if bids_up:
                            up_bid = max(float(b.get('price', 0.0)) for b in bids_up if b.get('price'))
                        else:
                            up_bid = up_mid if up_mid > 0 else up_ask

                        if bids_down:
                            down_bid = max(float(b.get('price', 0.0)) for b in bids_down if b.get('price'))
                        else:
                            down_bid = down_mid if down_mid > 0 else down_ask
                        
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
                            
                            print(f"📊 [{self.asset.upper()}] UP: ${up_ask:.3f} | DOWN: ${down_ask:.3f} | {status}")
                            print(f"   [{self.asset.upper()}] Qty: {pt.qty_up:.1f}U / {pt.qty_down:.1f}D | Ratio: {ratio:.3f}x")
                            print(f"   [{self.asset.upper()}] Pair Cost: ${pt.pair_cost:.3f} | Locked PnL: ${locked_pnl:.2f}")
                            print(f"   [{self.asset.upper()}] Cash: ${pt.cash:.2f} | Trades: {pt.trade_count}")
                        
                        timestamp = datetime.now(timezone.utc).strftime('%H:%M:%S')
                        market_elapsed = None
                        if self.window_start:
                            market_elapsed = (datetime.now(timezone.utc) - self.window_start).total_seconds()
                        trades = self.paper_trader.check_and_trade(up_ask, down_ask, timestamp, up_bid=up_bid, down_bid=down_bid, market_elapsed=market_elapsed)
                        
                        if trades:
                            for side, price, qty in trades:
                                pt = self.paper_trader
                                print(f"📈 [{self.asset.upper()}] BUY {qty:.1f} {side} @ ${price:.3f} | Pair Cost: ${pt.pair_cost:.4f} | Balance: {pt.qty_up:.0f}U/{pt.qty_down:.0f}D")
                    
                    # Prepare data for broadcast
                    window_time = f"{self.window_start.strftime('%H:%M') if self.window_start else '--:--'} - {self.window_end.strftime('%H:%M') if self.window_end else '--:--'}"
                    
                    data = {
                        'asset': self.asset,  # Identify which asset this data is for
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


# Create bot instances - one per asset
bots: Dict[str, 'PolymarketWebBot'] = {}
for asset in ASSETS:
    asset = asset.strip().lower()
    if asset:
        bots[asset] = PolymarketWebBot(asset=asset, interval_minutes=MARKET_INTERVAL_MINUTES)
        print(f"📊 Created bot for {asset.upper()}")

# For backward compatibility
bot = list(bots.values())[0] if bots else None


async def index_handler(request):
    """Serve the HTML page"""
    return web.Response(text=HTML_TEMPLATE, content_type='text/html')


async def websocket_handler(request):
    """Handle WebSocket connections"""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    # Add to all bots
    for b in bots.values():
        b.websockets.add(ws)
    print(f"WebSocket client connected. Total clients: {len(list(bots.values())[0].websockets) if bots else 0}")
    
    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    command = data.get('command')
                    asset = data.get('asset', '').lower()
                    
                    # Handle commands for specific asset or all
                    target_bots = [bots[asset]] if asset and asset in bots else list(bots.values())
                    
                    if command == 'toggle_pause':
                        for b in target_bots:
                            b.toggle_pause()
                    elif command == 'reset_bot':
                        for b in target_bots:
                            b.reset_bot()
                    elif command == 'toggle_sell_mode':
                        for b in target_bots:
                            b.paper_trader.sell_mode = not b.paper_trader.sell_mode
                            print(f"🎯 {b.asset.upper()} Sell Mode: {'ON' if b.paper_trader.sell_mode else 'OFF'}")
                except json.JSONDecodeError:
                    pass
            elif msg.type == aiohttp.WSMsgType.ERROR:
                break
    finally:
        for b in bots.values():
            b.websockets.discard(ws)
        print(f"WebSocket client disconnected. Total clients: {len(list(bots.values())[0].websockets) if bots else 0}")
    
    return ws


async def start_background_tasks(app):
    """Start the data fetching loop for all bots"""
    app['data_tasks'] = []
    for asset, b in bots.items():
        task = asyncio.create_task(b.data_loop())
        app['data_tasks'].append(task)
        print(f"🚀 Started data loop for {asset.upper()}")


async def cleanup_background_tasks(app):
    """Stop the data fetching loops"""
    for b in bots.values():
        b.running = False
    for task in app.get('data_tasks', []):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def main():
    app = web.Application()
    app.router.add_get('/', index_handler)
    app.router.add_get('/ws', websocket_handler)
    
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    
    print(f"🤖 Polymarket Web Bot starting...")
    print(f"📊 Assets: {', '.join([a.upper() for a in ASSETS])} | Interval: {MARKET_INTERVAL_MINUTES}m")
    print(f"🔍 Auto-discovery enabled - will find current markets automatically")
    print(f"🌐 Open http://localhost:8080 in your browser")
    print(f"Press Ctrl+C to stop")
    print()
    
    web.run_app(app, host='localhost', port=8080, print=None)


if __name__ == '__main__':
    main()
