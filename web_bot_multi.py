#!/usr/bin/env python3
"""
Polymarket Multi-Market Bot - BTC, ETH, SOL, XRP Up/Down Tracker
Web-based interface with real-time updates via WebSocket.
NEW: Dynamic Delta Neutral Arbitrage Strategy - Mean Reversion
"""

import asyncio
import aiohttp
import json
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional, Dict, List
from aiohttp import web
import os

# Import new arbitrage strategy
from arbitrage_strategy import ArbitrageStrategy
from execution_simulator import ExecutionSimulator

# Supported assets
SUPPORTED_ASSETS = ['btc', 'eth', 'sol', 'xrp']

# Per-asset budget (how much $ to allocate per 15-min market)
ASSET_BUDGETS = {
    'btc': 200.0,
    'eth': 200.0,
    'sol': 200.0,
    'xrp': 200.0,
}

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
        .neutral { color: #9ca3af; }
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
        
        .history-section {
            margin-top: 30px;
            background: #111827;
            padding: 20px;
            border-radius: 12px;
            border: 1px solid #1f2937;
        }
        .history-section h2 {
            margin-top: 0;
            color: #f59e0b;
        }
        .section-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
        }
        .collapse-btn {
            font-size: 11px;
            padding: 4px 8px;
            border-radius: 6px;
            border: 1px solid #374151;
            background: #0b1220;
            color: #9ca3af;
            cursor: pointer;
        }
        .collapse-btn:hover {
            color: #e5e7eb;
            border-color: #4b5563;
        }
        .history-section.collapsed table {
            display: none;
        }
        .sell-badge {
            font-size: 10px;
            padding: 2px 6px;
            border-radius: 6px;
            border: 1px solid #334155;
            margin-left: 6px;
        }
        .sell-badge-active {
            background: #b91c1c;
            color: #fff;
        }
        .sell-badge-none {
            background: #0f172a;
            color: #94a3b8;
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

        .spread-tracker {
            margin-top: 10px;
            padding: 10px;
            background: #0d0d1a;
            border: 1px solid #1e293b;
            border-radius: 6px;
        }
        .spread-tracker-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 6px;
        }
        .spread-tracker-title {
            color: #60a5fa;
            font-size: 11px;
            font-weight: bold;
            text-transform: uppercase;
        }
        .spread-metrics {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 6px;
            margin-top: 8px;
            font-size: 10px;
        }
        .spread-metric {
            text-align: center;
            padding: 4px;
            background: #111827;
            border-radius: 4px;
        }
        .spread-metric .sm-label {
            color: #6b7280;
            font-size: 9px;
            text-transform: uppercase;
        }
        .spread-metric .sm-value {
            font-weight: bold;
            font-size: 12px;
            margin-top: 2px;
        }
        .spread-chart-container {
            position: relative;
            width: 100%;
            height: 80px;
            margin-top: 6px;
        }
        .spread-chart-container canvas {
            width: 100%;
            height: 100%;
        }
        .mgp-tracker {
            margin-top: 10px;
            padding: 10px;
            background: #0d0d1a;
            border: 1px solid #1e293b;
            border-radius: 6px;
        }
        .mgp-tracker-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 6px;
        }
        .mgp-tracker-title {
            color: #22c55e;
            font-size: 11px;
            font-weight: bold;
            text-transform: uppercase;
        }
        .mgp-chart-container {
            position: relative;
            width: 100%;
            height: 90px;
            margin-top: 6px;
        }
        .mgp-chart-container canvas {
            width: 100%;
            height: 100%;
        }
        .mgp-summary {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 6px;
            margin-top: 8px;
            font-size: 10px;
        }
        .mgp-stat {
            text-align: center;
            padding: 4px;
            background: #111827;
            border-radius: 4px;
        }
        .mgp-stat .ms-label {
            color: #6b7280;
            font-size: 9px;
            text-transform: uppercase;
        }
        .mgp-stat .ms-value {
            font-weight: bold;
            font-size: 12px;
            margin-top: 2px;
        }
    </style>
</head>
<body>
    <div class="connection-status disconnected" id="connection-status">Disconnected</div>
    
    <div class="container">
        <div class="header">
            <h1>🤖 Polymarket Multi-Market Bot</h1>
            <div style="color: #888; font-size: 12px;">
                <span style="color: #3b82f6; font-weight: bold;">
                💰 MGP ARBITRAGE 💰 | Delta Neutral | Lock Both Scenarios Positive
                </span> | 
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
                <div class="value neutral">$<span id="starting-balance">800.00</span></div>
            </div>
            <div class="global-stat">
                <div class="label">True Balance</div>
                <div class="value neutral">$<span id="current-balance">800.00</span></div>
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
            <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px;" id="asset-wdl-stats">
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
                <div class="asset-wdl-card" style="background: #1a1a2e; padding: 12px; border-radius: 8px; text-align: center;">
                    <span class="asset-badge asset-sol">SOL</span>
                    <div style="margin-top: 8px; font-size: 12px;">
                        <span class="profit">W: --</span> | 
                        <span style="color: #888;">D: --</span> | 
                        <span class="loss">L: --</span>
                    </div>
                </div>
                <div class="asset-wdl-card" style="background: #1a1a2e; padding: 12px; border-radius: 8px; text-align: center;">
                    <span class="asset-badge asset-xrp">XRP</span>
                    <div style="margin-top: 8px; font-size: 12px;">
                        <span class="profit">W: --</span> | 
                        <span style="color: #888;">D: --</span> | 
                        <span class="loss">L: --</span>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Execution Simulator Panel (Slippage & Latency) -->
        <div class="exec-sim-panel" style="margin-bottom: 20px; background: #1a1a2e; padding: 15px; border-radius: 8px; border: 1px solid #333;">
            <h2 style="color: #f59e0b; margin-bottom: 12px;">⚡ Execution Simulator (25ms latency)</h2>
            <div style="display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 15px;">
                <div style="text-align: center;">
                    <div style="color: #888; font-size: 11px;">Total Fills</div>
                    <div style="font-size: 20px; font-weight: bold; color: #22c55e;" id="exec-fills">0</div>
                </div>
                <div style="text-align: center;">
                    <div style="color: #888; font-size: 11px;">Rejections</div>
                    <div style="font-size: 20px; font-weight: bold; color: #ef4444;" id="exec-rejections">0</div>
                </div>
                <div style="text-align: center;">
                    <div style="color: #888; font-size: 11px;">Partial Fills</div>
                    <div style="font-size: 20px; font-weight: bold; color: #f59e0b;" id="exec-partials">0</div>
                </div>
                <div style="text-align: center;">
                    <div style="color: #888; font-size: 11px;">Fill Rate</div>
                    <div style="font-size: 20px; font-weight: bold; color: #3b82f6;" id="exec-fill-rate">--</div>
                </div>
                <div style="text-align: center;">
                    <div style="color: #888; font-size: 11px;">PnL Impact (Slippage)</div>
                    <div style="font-size: 20px; font-weight: bold;" id="exec-pnl-impact">$0.00</div>
                </div>
            </div>
            <div id="slippage-log" style="max-height: 200px; overflow-y: auto; font-size: 11px;">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="color: #888; border-bottom: 1px solid #333;">
                            <th style="text-align: left; padding: 4px 6px;">Time</th>
                            <th style="text-align: left; padding: 4px 6px;">Asset</th>
                            <th style="text-align: left; padding: 4px 6px;">Side</th>
                            <th style="text-align: right; padding: 4px 6px;">Wanted</th>
                            <th style="text-align: right; padding: 4px 6px;">Got</th>
                            <th style="text-align: right; padding: 4px 6px;">Slip %</th>
                            <th style="text-align: right; padding: 4px 6px;">Slip $</th>
                            <th style="text-align: right; padding: 4px 6px;">Qty</th>
                            <th style="text-align: center; padding: 4px 6px;">Levels</th>
                            <th style="text-align: center; padding: 4px 6px;">Partial</th>
                        </tr>
                    </thead>
                    <tbody id="slippage-tbody">
                        <tr><td colspan="10" style="color: #555; text-align: center; padding: 15px;">No slippage events yet</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
        
        <h2 style="color: #3b82f6; margin-bottom: 15px;">📊 Active Markets</h2>
        <div class="markets-grid" id="active-markets">
            <div style="color: #888; text-align: center; padding: 40px; grid-column: span 2;">
                Searching for active markets...
            </div>
        </div>
        
        <div class="history-section" id="resolved-history-section">
            <div class="section-header">
                <h2>📜 Resolved Markets History</h2>
                <button class="collapse-btn" id="resolved-toggle" onclick="toggleResolvedHistory()">Hide</button>
            </div>
            <table class="history-table" id="resolved-history-table">
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
                        <th>Action</th>
                        <th>Side</th>
                        <th>Price</th>
                        <th>Qty</th>
                        <th>Cost</th>
                        <th>Profit</th>
                        <th>Pair Cost</th>
                    </tr>
                </thead>
                <tbody id="trade-log-body">
                    <tr>
                        <td colspan="9" style="text-align: center; color: #888;">No trades yet</td>
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
            if (confirm('Are you sure you want to reset the bot? This will clear all data and reset balance to $800.')) {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ action: 'reset' }));
                }
            }
        }

        function toggleResolvedHistory() {
            const section = document.getElementById('resolved-history-section');
            const btn = document.getElementById('resolved-toggle');
            if (!section || !btn) return;
            const isCollapsed = section.classList.toggle('collapsed');
            btn.textContent = isCollapsed ? 'Show' : 'Hide';
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
        
        function drawSpreadChart(canvasId, zHistory, spreadHistory, bbUpperHist, bbLowerHist, signalHistory) {
            const canvas = document.getElementById(canvasId);
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            const dpr = window.devicePixelRatio || 1;
            const rect = canvas.parentElement.getBoundingClientRect();
            const w = rect.width;
            const h = rect.height;
            canvas.width = w * dpr;
            canvas.height = h * dpr;
            canvas.style.width = w + 'px';
            canvas.style.height = h + 'px';
            ctx.scale(dpr, dpr);

            const n = zHistory.length;
            if (n < 2) return;

            // Determine Y range from z-scores
            let minZ = -3, maxZ = 3;
            for (const z of zHistory) {
                if (z < minZ) minZ = z - 0.5;
                if (z > maxZ) maxZ = z + 0.5;
            }
            const rangeZ = maxZ - minZ || 1;

            const padL = 28, padR = 4, padT = 4, padB = 14;
            const cw = w - padL - padR;
            const ch = h - padT - padB;

            const xStep = cw / (n - 1);
            const yOf = (z) => padT + ch - ((z - minZ) / rangeZ) * ch;

            // Background
            ctx.fillStyle = '#0a0a14';
            ctx.fillRect(0, 0, w, h);

            // Entry zone bands (z = ±2)
            const y2p = yOf(2);
            const y2n = yOf(-2);
            ctx.fillStyle = 'rgba(239, 68, 68, 0.08)';
            ctx.fillRect(padL, padT, cw, y2p - padT);
            ctx.fillRect(padL, y2n, cw, padT + ch - y2n);
            ctx.fillStyle = 'rgba(34, 197, 94, 0.06)';
            ctx.fillRect(padL, y2p, cw, y2n - y2p);

            // Horizontal grid lines at z = -2, 0, +2
            ctx.strokeStyle = '#1e293b';
            ctx.lineWidth = 0.5;
            ctx.setLineDash([3, 3]);
            for (const lvl of [-2, 0, 2]) {
                const yy = yOf(lvl);
                ctx.beginPath();
                ctx.moveTo(padL, yy);
                ctx.lineTo(padL + cw, yy);
                ctx.stroke();
            }
            ctx.setLineDash([]);

            // Y-axis labels
            ctx.fillStyle = '#4b5563';
            ctx.font = '9px monospace';
            ctx.textAlign = 'right';
            for (const lvl of [-2, 0, 2]) {
                ctx.fillText(lvl.toFixed(0), padL - 3, yOf(lvl) + 3);
            }

            // Signal background markers
            if (signalHistory && signalHistory.length === n) {
                for (let i = 0; i < n; i++) {
                    const sig = signalHistory[i];
                    if (sig === 'SHORT_UP_LONG_DOWN' || sig === 'LONG_UP_SHORT_DOWN') {
                        ctx.fillStyle = 'rgba(34, 197, 94, 0.15)';
                        ctx.fillRect(padL + i * xStep - xStep / 2, padT, xStep, ch);
                    } else if (sig === 'EXIT_ALL') {
                        ctx.fillStyle = 'rgba(245, 158, 11, 0.10)';
                        ctx.fillRect(padL + i * xStep - xStep / 2, padT, xStep, ch);
                    }
                }
            }

            // Z-score line
            ctx.beginPath();
            ctx.strokeStyle = '#60a5fa';
            ctx.lineWidth = 1.5;
            for (let i = 0; i < n; i++) {
                const x = padL + i * xStep;
                const y = yOf(zHistory[i]);
                if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
            }
            ctx.stroke();

            // Current z dot
            const lastZ = zHistory[n - 1];
            const dotColor = Math.abs(lastZ) > 2 ? '#f59e0b' : Math.abs(lastZ) > 3 ? '#ef4444' : '#22c55e';
            ctx.beginPath();
            ctx.arc(padL + (n - 1) * xStep, yOf(lastZ), 3, 0, Math.PI * 2);
            ctx.fillStyle = dotColor;
            ctx.fill();

            // Entry threshold labels
            ctx.fillStyle = '#ef4444';
            ctx.font = '8px monospace';
            ctx.textAlign = 'left';
            ctx.fillText('+entry', padL + cw - 30, y2p - 2);
            ctx.fillText('-entry', padL + cw - 30, y2n + 9);
        }

        function drawMgpChart(canvasId, mgpHistory, pnlUpHistory, pnlDownHistory, arbLocked) {
            const canvas = document.getElementById(canvasId);
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            const dpr = window.devicePixelRatio || 1;
            const rect = canvas.parentElement.getBoundingClientRect();
            const w = rect.width;
            const h = rect.height;
            canvas.width = w * dpr;
            canvas.height = h * dpr;
            canvas.style.width = w + 'px';
            canvas.style.height = h + 'px';
            ctx.scale(dpr, dpr);

            const n = mgpHistory.length;
            if (n < 2) return;

            // Determine Y range from all three series
            const allVals = [...mgpHistory, ...pnlUpHistory, ...pnlDownHistory];
            let minY = Math.min(...allVals, 0);
            let maxY = Math.max(...allVals, 0);
            const pad = Math.max(Math.abs(maxY - minY) * 0.15, 1);
            minY -= pad;
            maxY += pad;
            const rangeY = maxY - minY || 1;

            const padL = 36, padR = 4, padT = 4, padB = 14;
            const cw = w - padL - padR;
            const ch = h - padT - padB;

            const xStep = cw / (n - 1);
            const yOf = (v) => padT + ch - ((v - minY) / rangeY) * ch;

            // Background
            ctx.fillStyle = '#0a0a14';
            ctx.fillRect(0, 0, w, h);

            // Positive/negative zones
            const y0 = yOf(0);
            if (y0 > padT && y0 < padT + ch) {
                ctx.fillStyle = 'rgba(34, 197, 94, 0.05)';
                ctx.fillRect(padL, padT, cw, y0 - padT);
                ctx.fillStyle = 'rgba(239, 68, 68, 0.05)';
                ctx.fillRect(padL, y0, cw, padT + ch - y0);
            }

            // Zero line
            ctx.strokeStyle = '#374151';
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 4]);
            ctx.beginPath();
            ctx.moveTo(padL, y0);
            ctx.lineTo(padL + cw, y0);
            ctx.stroke();
            ctx.setLineDash([]);

            // Y-axis labels
            ctx.fillStyle = '#4b5563';
            ctx.font = '9px monospace';
            ctx.textAlign = 'right';
            ctx.fillText('$0', padL - 3, y0 + 3);
            const topVal = maxY - pad / 2;
            const botVal = minY + pad / 2;
            ctx.fillText('$' + topVal.toFixed(1), padL - 3, padT + 10);
            ctx.fillText('$' + botVal.toFixed(1), padL - 3, padT + ch - 2);

            // Helper to draw a line
            function drawLine(data, color, width, dash) {
                if (data.length < n) return;
                ctx.beginPath();
                ctx.strokeStyle = color;
                ctx.lineWidth = width;
                if (dash) ctx.setLineDash(dash);
                for (let i = 0; i < n; i++) {
                    const x = padL + i * xStep;
                    const y = yOf(data[i]);
                    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
                }
                ctx.stroke();
                if (dash) ctx.setLineDash([]);
            }

            // PnL if UP wins (dashed blue)
            drawLine(pnlUpHistory, 'rgba(96, 165, 250, 0.4)', 1, [3, 3]);
            // PnL if DOWN wins (dashed orange)
            drawLine(pnlDownHistory, 'rgba(251, 146, 60, 0.4)', 1, [3, 3]);
            // MGP line (solid green/red)
            const lastMgp = mgpHistory[n - 1];
            const mgpColor = lastMgp >= 0 ? '#22c55e' : '#ef4444';
            drawLine(mgpHistory, mgpColor, 2, null);

            // Fill area under MGP line to zero
            ctx.beginPath();
            ctx.moveTo(padL, y0);
            for (let i = 0; i < n; i++) {
                ctx.lineTo(padL + i * xStep, yOf(mgpHistory[i]));
            }
            ctx.lineTo(padL + (n - 1) * xStep, y0);
            ctx.closePath();
            ctx.fillStyle = lastMgp >= 0 ? 'rgba(34, 197, 94, 0.12)' : 'rgba(239, 68, 68, 0.12)';
            ctx.fill();

            // Current MGP dot
            const dotColor = lastMgp >= 0 ? '#22c55e' : '#ef4444';
            ctx.beginPath();
            ctx.arc(padL + (n - 1) * xStep, yOf(lastMgp), 4, 0, Math.PI * 2);
            ctx.fillStyle = dotColor;
            ctx.fill();
            ctx.strokeStyle = '#fff';
            ctx.lineWidth = 1;
            ctx.stroke();

            // Value label at dot
            ctx.fillStyle = dotColor;
            ctx.font = 'bold 10px monospace';
            ctx.textAlign = 'right';
            ctx.fillText('$' + lastMgp.toFixed(2), padL + (n - 1) * xStep - 6, yOf(lastMgp) - 6);

            // ARB LOCKED banner
            if (arbLocked) {
                ctx.fillStyle = 'rgba(34, 197, 94, 0.15)';
                ctx.fillRect(padL, padT, cw, ch);
                ctx.fillStyle = '#22c55e';
                ctx.font = 'bold 10px sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText('LOCKED', padL + cw / 2, padT + 12);
            }

            // Legend
            ctx.font = '8px monospace';
            ctx.textAlign = 'left';
            ctx.fillStyle = mgpColor; ctx.fillText('--- MGP', padL + 4, padT + ch + 11);
            ctx.fillStyle = 'rgba(96, 165, 250, 0.6)'; ctx.fillText('-- UP', padL + 50, padT + ch + 11);
            ctx.fillStyle = 'rgba(251, 146, 60, 0.6)'; ctx.fillText('-- DN', padL + 82, padT + ch + 11);
        }

        function updateUI(data) {
            // Update global stats
            document.getElementById('starting-balance').textContent = data.starting_balance.toFixed(2);
            document.getElementById('current-balance').textContent = data.true_balance.toFixed(2);
            
            const totalPnl = data.true_balance - data.starting_balance;
            const slippageCost = (data.exec_stats && data.exec_stats.total_slippage_cost) || 0;
            const pnlEl = document.getElementById('total-pnl');
            if (slippageCost > 0.001) {
                pnlEl.innerHTML = (totalPnl >= 0 ? '+' : '') + '$' + totalPnl.toFixed(2) + 
                    '<br><span style="font-size:11px;color:#f59e0b;">slip: -$' + slippageCost.toFixed(4) + '</span>';
            } else {
                pnlEl.textContent = (totalPnl >= 0 ? '+' : '') + '$' + totalPnl.toFixed(2);
            }
            pnlEl.className = 'value ' + (totalPnl >= 0 ? 'profit' : 'loss');
            
            document.getElementById('markets-resolved').textContent = data.history.length;
            
            // Update W/D/L per asset
            if (data.asset_wdl) {
                const wdlContainer = document.getElementById('asset-wdl-stats');
                const assets = (data.supported_assets && data.supported_assets.length)
                    ? data.supported_assets
                    : Object.keys(data.asset_wdl);
                if (assets.length > 0) {
                    wdlContainer.style.gridTemplateColumns = `repeat(${assets.length}, 1fr)`;
                }
                let wdlHtml = '';
                for (const asset of assets) {
                    const stats = data.asset_wdl[asset] || { wins: 0, draws: 0, losses: 0, total: 0, total_pnl: 0 };
                    const winPct = stats.total > 0 ? ((stats.wins / stats.total) * 100).toFixed(0) : '--';
                    const drawPct = stats.total > 0 ? ((stats.draws / stats.total) * 100).toFixed(0) : '--';
                    const lossPct = stats.total > 0 ? ((stats.losses / stats.total) * 100).toFixed(0) : '--';
                    const pnl = stats.total_pnl || 0;
                    const realized = stats.realized_profit || 0;
                    const pnlClass = pnl >= 0 ? 'profit' : 'loss';
                    const pnlSign = pnl >= 0 ? '+' : '';
                    
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
                                ${pnlSign}$${pnl.toFixed(2)}
                            </div>
                            <div style="margin-top: 4px; font-size: 11px; color: ${realized >= 0 ? '#22c55e' : '#ef4444'};">
                                Locked profit: ${realized >= 0 ? '+' : ''}$${realized.toFixed(2)}
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
                    
                    const markUp = typeof market.up_price === 'number' ? market.up_price : 0;
                    const markDown = typeof market.down_price === 'number' ? market.down_price : 0;
                    const livePnl = (pt.qty_up * markUp) + (pt.qty_down * markDown)
                        + (pt.total_sell_proceeds || 0) - (pt.cost_up + pt.cost_down);
                    const finalPnl = pt.final_pnl ?? 0;
                    const finalGross = pt.final_pnl_gross ?? finalPnl;
                    const feesPaid = pt.fees_paid ?? 0;
                    const activeSells = pt.active_sells || [];
                    const filledSells = pt.filled_sells || [];
                    const lockedProfit = filledSells.reduce((sum, s) => sum + (s.profit || 0), 0);
                    const activeSellText = activeSells.length
                        ? activeSells.map(s => `${s.side} ${s.qty.toFixed(1)}sh @ $${s.min_price.toFixed(2)}`).join(' | ')
                        : 'none';
                    const filledSellText = filledSells.length
                        ? filledSells.map(s => `${s.side} ${s.qty.toFixed(1)}sh @ $${s.fill_price.toFixed(3)}`).join(' | ')
                        : 'none';
                    const sellBadge = activeSells.length
                        ? `<span class="sell-badge sell-badge-active">SELLS ${activeSells.length}</span>`
                        : `<span class="sell-badge sell-badge-none">SELLS 0</span>`;
                    
                    html += `
                        <div class="market-card ${pt.market_status === 'resolved' ? 'resolved' : ''}">
                            <div class="market-header">
                                <span class="asset-badge asset-${market.asset}">${asset}</span>
                                <span class="market-status ${statusClass}">${pt.market_status.toUpperCase()}</span>
                                ${sellBadge}
                            </div>
                            <div style="font-size: 11px; color: #888; margin-bottom: 6px;">
                                ${market.window_time || slug}
                            </div>
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
                                    ${pt.qty_up > 0 && pt.qty_down === 0 ? 
                                        `<div class="holding-label" style="color: #3b82f6; margin-top: 4px;">Need DOWN &lt;$${pt.max_hedge_down.toFixed(3)}</div>` 
                                        : ''}
                                </div>
                                <div class="holding-item">
                                    <div class="holding-label">Qty DOWN</div>
                                    <div class="holding-value">${pt.qty_down.toFixed(1)}</div>
                                    <div class="holding-label" style="margin-top: 4px;">Avg: $${pt.avg_down.toFixed(3)}</div>
                                    <div class="holding-label" style="color: #f59e0b;">Spent: $${pt.cost_down.toFixed(2)}</div>
                                    ${pt.qty_down > 0 && pt.qty_up === 0 ? 
                                        `<div class="holding-label" style="color: #3b82f6; margin-top: 4px;">Need UP &lt;$${pt.max_hedge_up.toFixed(3)}</div>` 
                                        : ''}
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
                            <div class="holdings-row-2" style="margin-top: 4px;">
                                <div class="holding-item">
                                    <div class="holding-label">Pivots</div>
                                    <div class="holding-value" style="color: ${pt.pivot_count === 0 ? '#888' : pt.equalized ? '#ef4444' : '#3b82f6'};">🔄 ${pt.pivot_count || 0}/${pt.max_pivots || 4}${pt.equalized ? ' ⚖️' : ''}</div>
                                </div>
                                <div class="holding-item" style="grid-column: span 2;">
                                    <div class="holding-label">Active Sells</div>
                                    <div class="holding-label" style="color: #9ca3af;">${activeSellText}</div>
                                    <div class="holding-label" style="margin-top: 4px;">Filled Sells</div>
                                    <div class="holding-label" style="color: #22c55e;">${filledSellText}</div>
                                </div>
                                <div class="holding-item">
                                    <div class="holding-label">Trades</div>
                                    <div class="holding-value" style="color: #888;">${pt.trade_count || 0}</div>
                                </div>
                                <div class="holding-item">
                                    <div class="holding-label">Budget Used</div>
                                    <div class="holding-value" style="color: ${(pt.cost_up + pt.cost_down) / 200 < 0.5 ? '#22c55e' : (pt.cost_up + pt.cost_down) / 200 < 0.9 ? '#f59e0b' : '#ef4444'};">$${(pt.cost_up + pt.cost_down).toFixed(0)}/$200</div>
                                </div>
                            </div>
                            <div class="holdings-row-2" style="margin-top: 8px; border-top: 1px solid #374151; padding-top: 8px;">
                                <div class="holding-item" style="grid-column: span 3;">
                                    <div class="holding-label">⚖️ Position Balance</div>
                                    <div style="margin-top: 4px;">
                                        ${(() => {
                                            if (pt.qty_up === 0 && pt.qty_down === 0) {
                                                return `<span style="color: #888;">No position yet</span>`;
                                            } else if (pt.qty_up === 0 || pt.qty_down === 0) {
                                                const side = pt.qty_up > 0 ? 'UP' : 'DOWN';
                                                const needSide = pt.qty_up > 0 ? 'DOWN' : 'UP';
                                                return `<span style="color: #ef4444; font-weight: bold;">🔴 UNHEDGED ${side} - Need ${needSide}!</span>`;
                                            } else {
                                                const ratio = Math.max(pt.qty_up, pt.qty_down) / Math.min(pt.qty_up, pt.qty_down);
                                                // Position delta: |A-B| / (A+B) * 100
                                                // v11: STRICTER - 2% ideal, 5% max
                                                const delta_pct = (Math.abs(pt.qty_up - pt.qty_down) / (pt.qty_up + pt.qty_down) * 100);
                                                const balanceColor = delta_pct <= 2 ? '#22c55e' : delta_pct <= 5 ? '#f59e0b' : '#ef4444';
                                                const balanceIcon = delta_pct <= 2 ? '✅' : delta_pct <= 5 ? '⚠️' : '🔴';
                                                const balanceStatus = delta_pct <= 2 ? 'BALANCED' : delta_pct <= 5 ? 'OK' : 'MUST BALANCE';
                                                return `<span style="color: ${balanceColor}; font-weight: bold;">${balanceIcon} ${balanceStatus}: ${delta_pct.toFixed(1)}% (${ratio.toFixed(2)}x)</span>`;
                                            }
                                        })()}
                                    </div>
                                </div>
                            </div>
                            ${pt.qty_up > 0 || pt.qty_down > 0 ? `
                            <div class="holdings-row-2" style="margin-top: 8px; border-top: 1px solid #374151; padding-top: 8px;">
                                <div class="holding-item">
                                    <div class="holding-label">If UP wins</div>
                                    <div class="holding-value" style="color: #10b981;">$${pt.qty_up.toFixed(2)}</div>
                                    <div class="holding-label" style="font-size: 0.65rem; color: ${(pt.qty_up - pt.cost_up - pt.cost_down) >= 0 ? '#10b981' : '#ef4444'};">
                                        ${(pt.qty_up - pt.cost_up - pt.cost_down) >= 0 ? '+' : ''}$${(pt.qty_up - pt.cost_up - pt.cost_down).toFixed(2)}
                                    </div>
                                </div>
                                <div class="holding-item">
                                    <div class="holding-label">If DOWN wins</div>
                                    <div class="holding-value" style="color: #10b981;">$${pt.qty_down.toFixed(2)}</div>
                                    <div class="holding-label" style="font-size: 0.65rem; color: ${(pt.qty_down - pt.cost_up - pt.cost_down) >= 0 ? '#10b981' : '#ef4444'};">
                                        ${(pt.qty_down - pt.cost_up - pt.cost_down) >= 0 ? '+' : ''}$${(pt.qty_down - pt.cost_up - pt.cost_down).toFixed(2)}
                                    </div>
                                </div>
                                <div class="holding-item">
                                    <div class="holding-label">Worst Case</div>
                                    <div class="holding-value" style="color: ${Math.min(pt.qty_up, pt.qty_down) - pt.cost_up - pt.cost_down >= 0 ? '#22c55e' : '#ef4444'};">
                                        ${Math.min(pt.qty_up, pt.qty_down) - pt.cost_up - pt.cost_down >= 0 ? '+' : ''}$${(Math.min(pt.qty_up, pt.qty_down) - pt.cost_up - pt.cost_down).toFixed(2)}
                                    </div>
                                </div>
                            </div>
                            ` : ''}
                            <div class="market-pnl">
                                <span style="color: #888;">Live PnL: </span>
                                <span class="${livePnl >= 0 ? 'profit' : 'loss'}" style="font-weight: bold;">
                                    ${livePnl >= 0 ? '+' : ''}$${livePnl.toFixed(2)}
                                </span>
                                ${lockedProfit > 0.001 ? `<br><span style="color: #888;">Locked profit: </span><span class="profit" style="font-weight: bold;">+$${lockedProfit.toFixed(2)}</span>` : ''}
                                ${pt.market_status === 'resolved' ? 
                                    `<br><span style="color: #3b82f6;">Outcome: ${pt.resolution_outcome} | Final: ${finalPnl >= 0 ? '+' : ''}$${finalPnl.toFixed(2)}${Math.abs(finalGross - finalPnl) > 0.005 || feesPaid > 0 ? ` <span style="color:#888;">(gross $${finalGross.toFixed(2)} | fees $${feesPaid.toFixed(2)})</span>` : ''}</span>` 
                                    : ''}
                            </div>
                            ${pt.current_mode && pt.market_status === 'open' ? `
                            <div style="margin-top: 10px; padding: 8px; background: rgba(59, 130, 246, 0.1); border-radius: 4px; border-left: 3px solid #3b82f6;">
                                <div style="color: #60a5fa; font-weight: bold; font-size: 0.75rem; text-transform: uppercase;">
                                    ${pt.current_mode === 'mgp_lock' ? '🔒 MGP LOCKING' :
                                      pt.current_mode === 'mgp_maximize' ? '📈 MGP MAXIMIZE' :
                                      pt.current_mode === 'accumulate' ? '💰 ACCUMULATING' :
                                      pt.current_mode === 'priority_fix' ? '🎯 PRIORITY FIX' : 
                                      pt.current_mode === 'improve' ? '📉 IMPROVING' :
                                      pt.current_mode === 'arbitrage' ? '💰 ARBITRAGE' :
                                      pt.current_mode === 'seeking_arb' ? '💰 SEEKING ARB' :
                                      pt.current_mode === 'hedge' ? '🔒 HEDGING' :
                                      pt.current_mode === 'rebalancing' ? '⚖️ REBALANCING' :
                                      pt.current_mode === 'rebalance' ? '⚖️ REBALANCING' :
                                      pt.current_mode === 'optimize' ? '⚡ OPTIMIZING' :
                                      pt.current_mode === 'improving' ? '📉 IMPROVING' :
                                      pt.current_mode === 'exit_wait' ? '⏳ EXIT WAIT' :
                                      pt.current_mode === 'entry' ? '🎯 ENTERING' : '💤 IDLE'}
                                </div>
                                <div style="color: #9ca3af; font-size: 0.7rem; margin-top: 3px;">${pt.mode_reason || 'Monitoring market'}</div>
                            </div>
                            ` : ''}
                            ${pt.market_status === 'open' ? `
                            <div class="mgp-tracker">
                                <div class="mgp-tracker-header">
                                    <span class="mgp-tracker-title">📈 MGP Tracker</span>
                                    <span style="font-size: 10px; color: ${pt.arb_locked ? '#22c55e' : (pt.mgp !== undefined && pt.mgp >= 0 ? '#22c55e' : '#ef4444')};">
                                        ${pt.arb_locked ? '🔒 LOCKED' : (pt.mgp !== undefined ? '$' + pt.mgp.toFixed(2) : '--')}
                                    </span>
                                </div>
                                <div class="mgp-chart-container">
                                    <canvas id="mgp-chart-${slug.replace(/[^a-zA-Z0-9]/g, '_')}"></canvas>
                                </div>
                                <div class="mgp-summary">
                                    <div class="mgp-stat">
                                        <div class="ms-label">If UP wins</div>
                                        <div class="ms-value" style="color: ${(pt.pnl_if_up_wins || 0) >= 0 ? '#22c55e' : '#ef4444'};">
                                            ${(pt.pnl_if_up_wins || 0) >= 0 ? '+' : ''}$${(pt.pnl_if_up_wins || 0).toFixed(2)}
                                        </div>
                                    </div>
                                    <div class="mgp-stat">
                                        <div class="ms-label">If DOWN wins</div>
                                        <div class="ms-value" style="color: ${(pt.pnl_if_down_wins || 0) >= 0 ? '#22c55e' : '#ef4444'};">
                                            ${(pt.pnl_if_down_wins || 0) >= 0 ? '+' : ''}$${(pt.pnl_if_down_wins || 0).toFixed(2)}
                                        </div>
                                    </div>
                                    <div class="mgp-stat">
                                        <div class="ms-label">Deficit</div>
                                        <div class="ms-value" style="color: ${(pt.deficit || 0) > 0 ? '#f59e0b' : '#6b7280'};">
                                            ${(pt.deficit || 0) > 0 ? (pt.deficit || 0).toFixed(1) + ' sh' : '✓ 0'}
                                        </div>
                                    </div>
                                </div>
                            </div>
                            ` : ''}
                            ${pt.market_status === 'open' ? `
                            <div class="spread-tracker">
                                <div class="spread-tracker-header">
                                    <span class="spread-tracker-title">📊 Spread Engine</span>
                                    <span style="font-size: 10px; color: ${pt.spread_engine_ready ? '#22c55e' : '#f59e0b'};">
                                        ${pt.spread_engine_ready ? '● LIVE' : '○ WARMING UP'}
                                    </span>
                                </div>
                                <div class="spread-chart-container">
                                    <canvas id="spread-chart-${slug.replace(/[^a-zA-Z0-9]/g, '_')}"></canvas>
                                </div>
                                <div class="spread-metrics">
                                    <div class="spread-metric">
                                        <div class="sm-label">Z-Score</div>
                                        <div class="sm-value" style="color: ${Math.abs(pt.z_score || 0) > 2 ? '#f59e0b' : Math.abs(pt.z_score || 0) > 3 ? '#ef4444' : '#22c55e'};">
                                            ${(pt.z_score || 0).toFixed(2)}
                                        </div>
                                    </div>
                                    <div class="spread-metric">
                                        <div class="sm-label">Beta (β)</div>
                                        <div class="sm-value" style="color: #a78bfa;">${(pt.spread_beta || 1).toFixed(3)}</div>
                                    </div>
                                    <div class="spread-metric">
                                        <div class="sm-label">Signal</div>
                                        <div class="sm-value" style="color: ${(pt.spread_signal === 'SHORT_UP_LONG_DOWN' || pt.spread_signal === 'LONG_UP_SHORT_DOWN') ? '#22c55e' : pt.spread_signal === 'EXIT_ALL' ? '#f59e0b' : '#6b7280'}; font-size: 9px;">
                                            ${pt.spread_signal === 'SHORT_UP_LONG_DOWN' ? '↓UP ↑DN' : pt.spread_signal === 'LONG_UP_SHORT_DOWN' ? '↑UP ↓DN' : pt.spread_signal === 'EXIT_ALL' ? 'EXIT' : 'NONE'}
                                        </div>
                                    </div>
                                    <div class="spread-metric">
                                        <div class="sm-label">Pos Δ%</div>
                                        <div class="sm-value" style="color: ${(pt.spread_delta_pct || 0) > 0 ? '#f59e0b' : '#6b7280'};">
                                            ${(pt.spread_delta_pct || 0).toFixed(0)}%
                                        </div>
                                    </div>
                                </div>
                            </div>
                            ` : ''}
                        </div>
                    `;
                }
                marketsGrid.innerHTML = html;

                // Draw spread charts after DOM update
                for (const [slug, market] of Object.entries(data.active_markets)) {
                    const pt = market.paper_trader;
                    if (pt.market_status === 'open' && pt.z_history && pt.z_history.length > 1) {
                        const canvasId = 'spread-chart-' + slug.replace(/[^a-zA-Z0-9]/g, '_');
                        drawSpreadChart(canvasId, pt.z_history, pt.spread_history_arr, pt.bb_upper_history, pt.bb_lower_history, pt.signal_history);
                    }
                    // Draw MGP charts
                    if (pt.market_status === 'open' && pt.mgp_history && pt.mgp_history.length > 1) {
                        const mgpCanvasId = 'mgp-chart-' + slug.replace(/[^a-zA-Z0-9]/g, '_');
                        drawMgpChart(mgpCanvasId, pt.mgp_history, pt.pnl_up_history || [], pt.pnl_down_history || [], pt.arb_locked || false);
                    }
                }
            }
            
            // Update history
            const historyBody = document.getElementById('history-body');
            if (data.history.length === 0) {
                historyBody.innerHTML = '<tr><td colspan="9" style="text-align: center; color: #888;">No resolved markets yet</td></tr>';
            } else {
                let html = '';
                for (const h of data.history.slice().reverse()) {
                    const netPayout = (h.net_payout !== undefined) ? h.net_payout : h.payout;
                    const fees = h.fees !== undefined ? h.fees : 0;
                    const grossPayout = h.payout !== undefined ? h.payout : netPayout;
                    const pnlValue = h.pnl_after_fees !== undefined ? h.pnl_after_fees : h.pnl;
                    const pnlGross = h.gross_pnl !== undefined ? h.gross_pnl : pnlValue;
                    const pnlClass = pnlValue >= 0 ? 'profit' : 'loss';
                    html += `
                        <tr>
                            <td>${h.resolved_at}</td>
                            <td><span class="asset-badge asset-${h.asset}" style="font-size: 10px;">${h.asset.toUpperCase()}</span></td>
                            <td style="font-size: 11px;">${h.slug}</td>
                            <td>${h.outcome}</td>
                            <td>${h.qty_up.toFixed(1)}</td>
                            <td>${h.qty_down.toFixed(1)}</td>
                            <td>$${h.pair_cost.toFixed(3)}</td>
                            <td>
                                $${netPayout.toFixed(2)}
                                ${fees > 0 ? `<div style="font-size: 10px; color: #888;">gross $${grossPayout.toFixed(2)} | fees $${fees.toFixed(2)}</div>` : ''}
                            </td>
                            <td class="${pnlClass}">${pnlValue >= 0 ? '+' : ''}$${pnlValue.toFixed(2)}
                                ${Math.abs(pnlGross - pnlValue) > 0.005 ? `<div style="font-size: 10px; color: #888;">gross $${pnlGross.toFixed(2)}</div>` : ''}
                            </td>
                        </tr>
                    `;
                }
                historyBody.innerHTML = html;
            }
            
            // Update trade log
            const tradeLogBody = document.getElementById('trade-log-body');
            if (!data.trade_log || data.trade_log.length === 0) {
                tradeLogBody.innerHTML = '<tr><td colspan="9" style="text-align: center; color: #888;">No trades yet</td></tr>';
            } else {
                let html = '';
                for (const t of data.trade_log.slice().reverse()) {
                    const action = t.action || 'BUY';
                    const actionClass = action === 'SELL' ? 'loss' : action === 'SELL_PLACED' ? 'neutral' : 'profit';
                    const sideClass = t.side === 'UP' ? 'profit' : 'loss';
                    const costCell = (action === 'SELL_PLACED') ? '-' : `$${t.cost.toFixed(2)}`;
                    const profitCell = (action === 'SELL' && typeof t.profit === 'number')
                        ? `${t.profit >= 0 ? '+' : ''}$${t.profit.toFixed(2)}`
                        : '-';
                    const profitClass = (action === 'SELL' && typeof t.profit === 'number')
                        ? (t.profit >= 0 ? 'profit' : 'loss')
                        : 'neutral';
                    html += `
                        <tr>
                            <td>${t.time}</td>
                            <td><span class="asset-badge asset-${t.asset.toLowerCase()}" style="font-size: 10px;">${t.asset}</span></td>
                            <td class="${actionClass}">${action}</td>
                            <td class="${sideClass}">${t.side}</td>
                            <td>$${t.price.toFixed(3)}</td>
                            <td>${t.qty.toFixed(1)}</td>
                            <td>${costCell}</td>
                            <td class="${profitClass}">${profitCell}</td>
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
            
            // Update Execution Simulator panel
            if (data.exec_stats) {
                const es = data.exec_stats;
                document.getElementById('exec-fills').textContent = es.total_fills || 0;
                document.getElementById('exec-rejections').textContent = es.total_rejections || 0;
                document.getElementById('exec-partials').textContent = es.total_partial_fills || 0;
                document.getElementById('exec-fill-rate').textContent = (es.fill_rate || 0) + '%';
                
                const pnlImpact = es.pnl_impact || 0;
                const pnlEl = document.getElementById('exec-pnl-impact');
                pnlEl.textContent = (pnlImpact >= 0 ? '' : '-') + '$' + Math.abs(pnlImpact).toFixed(4);
                pnlEl.style.color = pnlImpact >= 0 ? '#22c55e' : '#ef4444';
                
                // Update slippage log table
                const slipTbody = document.getElementById('slippage-tbody');
                if (es.recent_slippage && es.recent_slippage.length > 0) {
                    let slipHtml = '';
                    for (const s of es.recent_slippage) {
                        const slipColor = s.slip_pct > 0 ? '#ef4444' : s.slip_pct < 0 ? '#22c55e' : '#888';
                        const partialBadge = s.partial ? '<span style="color:#f59e0b;">⚠️</span>' : '✓';
                        slipHtml += `
                            <tr style="border-bottom: 1px solid #1a1a2e;">
                                <td style="padding: 3px 6px; color: #888;">${s.time || '--'}</td>
                                <td style="padding: 3px 6px; color: #3b82f6;">${s.asset || '--'}</td>
                                <td style="padding: 3px 6px; color: ${s.side === 'UP' ? '#22c55e' : '#ef4444'};">${s.side}</td>
                                <td style="padding: 3px 6px; text-align: right;">$${(s.desired || 0).toFixed(4)}</td>
                                <td style="padding: 3px 6px; text-align: right;">$${(s.filled || 0).toFixed(4)}</td>
                                <td style="padding: 3px 6px; text-align: right; color: ${slipColor};">${s.slip_pct > 0 ? '+' : ''}${(s.slip_pct || 0).toFixed(3)}%</td>
                                <td style="padding: 3px 6px; text-align: right; color: ${slipColor};">$${(s.slip_cost || 0).toFixed(4)}</td>
                                <td style="padding: 3px 6px; text-align: right;">${(s.qty || 0).toFixed(1)}</td>
                                <td style="padding: 3px 6px; text-align: center;">${s.levels || 1}</td>
                                <td style="padding: 3px 6px; text-align: center;">${partialBadge}</td>
                            </tr>
                        `;
                    }
                    slipTbody.innerHTML = slipHtml;
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
    
    def __init__(self, cash_ref: dict, market_slug: str, market_budget: float):
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
        self.final_pnl_gross = None
        self.payout = 0.0
        self.last_fees_paid = 0.0
        self.market_budget = market_budget
        self.starting_balance = market_budget

        # Prefer "paired" compounding once profit is locked:
        # Buying equal UP+DOWN at a favorable combined price increases locked profit
        # while keeping worst-case protected.
        # v12: More aggressive compounding
        self.pair_growth_max_pair_price = 0.99   # Only compound when (up_price + down_price) <= this (WAS 0.98)
        self.pair_growth_budget_fraction = 0.70  # Use up to 70% of remaining budget per compound attempt (WAS 0.50)
        self.pair_growth_min_improvement = 0.005 # Require at least $0.005 improvement (WAS 0.01)
        self.growth_min_locked_after_trade = 0.00  # One-sided growth must keep locked profit >= 0
        
        # === TRADING MODE TRACKING ===
        self.current_mode = 'idle'  # idle, entry, hedge, priority_fix, improve, rebalance, optimize
        self.mode_reason = ''
        
        # === GABAGOOL v10 - POSITION IMPROVEMENT STRATEGY ===
        # Core principle: Continuously improve position to make hedging easier
        # If we buy UP @ $0.46, and later UP is $0.38, buy more to lower average!
        # This widens the profitable hedge window.
        
        # Trading strategy parameters
        self.cheap_threshold = 0.45      # What we consider "cheap" for entry (WAS 0.48)
        self.very_cheap_threshold = 0.40 # Very cheap - accumulate more
        self.force_balance_threshold = 0.52  # Max price to pay when balancing (WAS 0.55)
        self.max_balance_price = 0.65    # Absolute max for emergency balance
        self.target_pair_cost = 0.93     # Ideal pair cost target (WAS 0.95)
        self.max_pair_cost = 0.98        # CRITICAL: Never buy if this would push pair over (WAS 0.995)
        
        # === POSITION IMPROVEMENT PARAMETERS ===
        # Key insight: Buying more at lower price LOWERS the average!
        # Example: avg_UP=$0.46, buy more @$0.38 → new avg ~$0.42
        # Now DOWN only needs to be <$0.58 instead of <$0.54!
        self.improvement_threshold = 0.005   # Buy more if price is 0.5 cents below average (was 0.001)
        self.min_improvement_pct = 0.01      # Or 1% below average (was 0.005)
        self.force_improve_pct = 0.05        # Force average-down if price drops 5%+ vs avg
        self.max_imbalance_for_improvement = 3.0  # Max qty ratio during improvement phase
        self.improvement_trade_pct = 0.01     # Use 1% of budget per improvement (was 0.005)
        
        # Position sizing - scaled to bankroll
        self.min_trade_size = 1.00       # Larger min trade to reduce fees (was $0.10)
        self.max_single_trade = 25.0     # Cap at $25 per trade (was $15)
        self.cooldown_seconds = 8        # Slow down: 8 seconds between trades (was 3) - fewer but bigger trades
        self.last_trade_time = 0
        self.first_trade_time = 0
        self.initial_trade_usd = 5.0     # Start with $5 (was $3) - larger initial trades
        self.max_position_pct = 0.85     # Use max 85% of budget (keep 15% reserve)
        self.force_balance_after_seconds = 120
        
        # === TIME-BASED BALANCE ENFORCEMENT ===
        # First 30 seconds: allow imbalance to take good entry prices
        # After 30 seconds: actively minimize delta % - prioritize smaller side
        self.balance_enforcement_delay = 30  # Grace period for initial positioning
        
        # === LOSS PROTECTION ===
        # Bot will continuously try to improve positions - only abandon if mathematically impossible
        self.abandon_threshold_pair_cost = 1.02  # If pair > $1.02, stop trying (mathematically unprofitable)
        self.conservative_mode_loss_threshold = -5.0  # Go conservative at -$5
        
        # === SPREAD-AWARE TRADING ===
        # Key insight: High spread = good opportunity to buy cheap side
        # BUT: Don't over-favor cheap side - we need balance on BOTH sides!
        self.high_spread_threshold = 0.35  # Was 0.25, now 0.35 (harder to trigger)
        self.medium_spread_threshold = 0.25  # Was 0.15, now 0.25
        self.spread_multiplier = 1.1  # Was 1.2, now only 1.1x boost (even less aggressive)
        
        # === STRATEGIC IMBALANCE (Asymmetric PnL) ===
        # Don't always aim for perfect 1:1 - accept imbalance if it gives better averages
        self.strategic_imbalance_max = 1.3  # Allow 30% more on the cheaper-average side
        self.prefer_better_average = True  # Prefer more qty on side with better average
        
        # === PROFIT GROWTH MODE ===
        # v12: AGGRESSIVE profit growth - never stop trading while market is open!
        # After securing locked profit, continue buying to maximize upside
        self.enable_profit_growth = True
        self.min_locked_for_growth = 0.001  # Almost any profit enables growth (WAS 0.01)
        self.min_target_locked_profit = 1.0  # Lower target: $1 locked is good start (WAS 3.0)
        self.growth_budget_pct = 0.70      # Use up to 70% of budget for growth trades (WAS 0.60)
        self.growth_max_pair_cost = 0.99   # Allow growth up to 0.99 pair (WAS 0.98)
        self.growth_max_pair_cost_low_profit = 0.998  # Be very aggressive when building profit (WAS 0.995)
        self.growth_favor_probability = True  # Favor side with higher market probability
        self.growth_favor_better_avg = True  # Favor side with better average
        self.growth_max_single_trade = 40.0  # Allow larger trades in growth mode (WAS 30.0)
        
        # === GUARANTEED PROFIT PARAMETERS ===
        # NEW STRATEGY: Ensure min(qty_up, qty_down) > total_spent
        # This guarantees profit regardless of outcome!
        # Position Delta % = |UP - DOWN| / (UP + DOWN) × 100
        # v11: ULTRA STRICT BALANCE - Losses are from imbalance!
        self.ideal_balance_delta_pct = 2.0   # IDEAL: Keep position delta ≤ 2% (WAS 5%)
        self.max_flex_delta_pct = 5.0        # MAX FLEX: Allow up to 5% temporarily (WAS 15%)
        self.critical_ratio = 1.20           # CRITICAL: Stop buying larger side at 1.2x imbalance (WAS 2.0)
        self.emergency_ratio = 1.35          # EMERGENCY: Absolute hard stop at 1.35x (WAS 2.5)
        self.emergency_hedge_ratio = 1.50    # Force emergency hedge even at pair 1.05 when ratio > 1.5x (WAS 3.0)
        self.max_qty_ratio = 1.10            # Allow only 10% strategic imbalance (WAS 30%)
        
        # === FEE AWARENESS ===
        # Polymarket uses dynamic fees: highest at $0.50 (1.56%), lowest at extremes
        # Fee formula: fee_rate ≈ price * (1 - price) * 0.0624 (capped at ~1.56%)
        # CRITICAL: For guaranteed profit, pair_cost MUST be < $1.00
        # With ~1.5% avg fees, we need pair_cost < ~$0.985 to profit
        self.max_entry_pair_potential = 0.98  # STRICT: Only enter if pair < $0.98

        # === PROFIT GROWTH MODE ===
        # Allow continued buying after locked profit is secured, but only if it
        # improves locked profit and keeps pair_cost under target.
        self.allow_profit_growth = True
        self.min_locked_profit_increase = 0.01  # Only 1 cent improvement needed

        # === BANKROLL RESERVES ===
        self.pre_hedge_reserve_ratio = 0.10   # Keep 10% of budget before hedging
        self.post_hedge_reserve_ratio = 0.05  # Keep 5% once both sides exist
        self.min_reserve_cash = 5.0           # Always keep at least $5 available
        self.reserve_price_floor = 0.05       # Minimal assumed hedge price

        # === GUARANTEED BREAK-EVEN SYSTEM ===
        # CRITICAL: Always keep enough cash to hedge entire position to break-even
        # Formula: max_spend = budget * min_expected_avg_price
        # With avg floor ~$0.15: max_spend = $200 * 0.15 = $30
        # INCREASED: Was $35, now $50 to allow better positioning
        self.max_spend_per_side = 50.0        # Hard limit per side ($50 of $200)
        self.breakeven_hedge_price = 0.90     # Worst case hedge price assumption
        self.enable_breakeven_check = True    # Enable break-even reserve check
        
        # === BREAK-EVEN HEDGE TRIGGERS ===
        # When to accept pair <= 1.00 instead of waiting for pair < 0.99
        self.breakeven_time_threshold = 180   # Accept break-even when < 3 min to close
        self.breakeven_price_threshold = 0.92 # Accept break-even when opposite side > $0.92
        self.max_acceptable_pair_profit = 0.99  # Normal: require profit (pair < 0.99)
        self.max_acceptable_pair_breakeven = 1.00  # Fallback: accept break-even (pair <= 1.00)
        
        # === STOP BUYING GUARD ===
        # CRITICAL: Stop buying when opposite side is too expensive for ANY hedge
        # If opposite > this, even break-even is impossible with reasonable avg
        self.stop_buying_opposite_price = 0.85  # Stop if opposite > $0.85
        
        # === ACCELERATED LADDER ===
        # Buy more when price is low to drag down average faster
        # Larger amounts to minimize number of trades (reduce fees)
        self.ladder_tiers = [
            # (price_threshold, spend_amount)
            (0.10, 6.0),    # Below $0.10: spend $6 per rung (was $4) - fewer trades
            (0.20, 4.5),    # $0.10 - $0.20: spend $4.5 per rung (was $3)
            (0.30, 3.0),    # $0.20 - $0.30: spend $3 per rung (was $2.5)
            (1.00, 2.0),    # Above $0.30: spend $2 per rung (was $1.5)
        ]

        # === IMPROVEMENT THROTTLE ===
        self.improvement_spend_window = 2.0   # Seconds to look back when throttling
        self.improvement_spend_cap = 15.0     # Max spend allowed per window on improvements
        self.improvement_spend_log = {
            'UP': deque(),
            'DOWN': deque()
        }
        self.improvement_step_price = 0.02   # Require $0.02 drop before next ladder fill
        self.last_improvement_price = {
            'UP': None,
            'DOWN': None
        }
    
    @staticmethod
    def calculate_fee(price: float, qty: float) -> float:
        """
        Calculate Polymarket fee based on price.
        Fee is highest at $0.50 (~1.56%) and approaches 0 at extremes ($0.01, $0.99)
        
        Fee table (per 100 shares):
        $0.50 → $0.78 (1.56%)
        $0.45 → $0.69 (1.53%)  
        $0.40 → $0.58 (1.44%)
        $0.30 → $0.33 (1.10%)
        $0.20 → $0.13 (0.64%)
        $0.10 → $0.02 (0.20%)
        $0.05 → $0.003 (0.06%)
        """
        # Effective rate lookup table (interpolated)
        fee_table = {
            0.01: 0.0000, 0.05: 0.0006, 0.10: 0.0020, 0.15: 0.0041,
            0.20: 0.0064, 0.25: 0.0088, 0.30: 0.0110, 0.35: 0.0129,
            0.40: 0.0144, 0.45: 0.0153, 0.50: 0.0156, 0.55: 0.0153,
            0.60: 0.0144, 0.65: 0.0129, 0.70: 0.0110, 0.75: 0.0088,
            0.80: 0.0064, 0.85: 0.0041, 0.90: 0.0020, 0.95: 0.0006,
            0.99: 0.0000
        }
        
        # Find closest prices in table and interpolate
        prices = sorted(fee_table.keys())
        
        if price <= prices[0]:
            rate = fee_table[prices[0]]
        elif price >= prices[-1]:
            rate = fee_table[prices[-1]]
        else:
            # Linear interpolation
            for i in range(len(prices) - 1):
                if prices[i] <= price <= prices[i + 1]:
                    p1, p2 = prices[i], prices[i + 1]
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
    
    def remaining_budget(self) -> float:
        total_spent = self.cost_up + self.cost_down
        budget_limit = self.starting_balance * self.max_position_pct
        return max(0.0, budget_limit - total_spent)
    
    def affordable_cash(self, fraction: float = 1.0) -> float:
        fraction = max(0.0, min(1.0, fraction))
        return max(0.0, min(self.cash * fraction, self.remaining_budget()))
    
    def capped_spend(self, desired_spend: float, fraction: float = 1.0) -> float:
        return min(desired_spend, self.affordable_cash(fraction))

    def _prune_improvement_window(self, side: str, now: Optional[float] = None):
        now = now if now is not None else time.time()
        log = self.improvement_spend_log.get(side)
        if log is None:
            return
        window = self.improvement_spend_window
        while log and now - log[0][0] > window:
            log.popleft()

    def _recent_improvement_spend(self, side: str, now: Optional[float] = None) -> float:
        now = now if now is not None else time.time()
        self._prune_improvement_window(side, now)
        log = self.improvement_spend_log.get(side)
        if not log:
            return 0.0
        return sum(amount for _, amount in log)

    def _check_breakeven_reserve(self, side: str, price: float, my_qty: float, my_cost: float, desired_spend: float) -> tuple:
        """
        Check if we have enough cash to hedge the entire position to break-even after this purchase.
        
        For break-even: pair_cost = 1.00, so hedge_price = 1 - avg_price
        Hedge cost = qty * hedge_price
        
        We must have: remaining_cash >= hedge_cost after the purchase
        
        Returns: (ok, allowed_spend, reason)
        """
        new_qty = my_qty + (desired_spend / price)
        new_cost = my_cost + desired_spend
        new_avg = new_cost / new_qty if new_qty > 0 else price
        
        # Worst case hedge price: use breakeven_hedge_price as ceiling
        breakeven_hedge_price = min(1.0 - new_avg, self.breakeven_hedge_price)
        hedge_cost = new_qty * breakeven_hedge_price
        
        cash_after = self.cash - desired_spend
        
        if cash_after < hedge_cost:
            # Calculate max spend that allows break-even hedge
            # cash - spend >= (my_qty + spend/price) * breakeven_hedge_price
            # cash - spend >= my_qty * bhp + spend * bhp / price
            # cash - my_qty * bhp >= spend + spend * bhp / price
            # cash - my_qty * bhp >= spend * (1 + bhp / price)
            # spend <= (cash - my_qty * bhp) / (1 + bhp / price)
            current_hedge_cost = my_qty * breakeven_hedge_price
            available_for_spend = self.cash - current_hedge_cost
            max_spend = available_for_spend / (1 + breakeven_hedge_price / price)
            
            if max_spend < self.min_trade_size:
                return False, 0, f"Break-even reserve: need ${hedge_cost:.2f} for hedge, only ${cash_after:.2f} available"
            return True, max_spend, f"Capped to ${max_spend:.2f} for break-even reserve"
        
        return True, desired_spend, ""

    def _evaluate_improvement_throttle(self, side: str, desired_spend: float) -> tuple:
        if desired_spend <= 0:
            return True, 0.0, ""
        now = time.time()
        recent_spend = self._recent_improvement_spend(side, now)
        remaining_allowance = max(0.0, self.improvement_spend_cap - recent_spend)
        if desired_spend <= remaining_allowance + 1e-6:
            return True, desired_spend, ""
        return False, remaining_allowance, (
            f"Throttle: ${recent_spend:.2f} used last {self.improvement_spend_window:.0f}s (cap ${self.improvement_spend_cap:.2f})"
        )

    def record_improvement_spend(self, side: str, spend: float):
        if spend <= 0:
            return
        now = time.time()
        log = self.improvement_spend_log.get(side)
        if log is None:
            return
        self._prune_improvement_window(side, now)
        log.append((now, spend))

    def cap_qty_to_reserve(
        self,
        side: str,
        price: float,
        desired_qty: float,
        opposing_price: Optional[float] = None,
        iterations: int = 20
    ) -> float:
        """Shrink qty until reserve_ok passes while staying within budget."""
        if price <= 0 or desired_qty <= 0:
            return 0.0

        ok, _ = self.reserve_ok(side, price, desired_qty, opposing_price)
        if ok:
            return desired_qty

        low = 0.0
        high = desired_qty

        for _ in range(iterations):
            mid = (low + high) / 2.0
            ok, _ = self.reserve_ok(side, price, mid, opposing_price)
            if ok:
                low = mid
            else:
                high = mid

        return low

    def capped_spend_until_ok(
        self,
        side: str,
        price: float,
        desired_spend: float,
        opposing_price: Optional[float] = None,
        fraction: float = 1.0,
        min_spend: float = 0.10,
        reduction_factor: float = 0.5,
        max_iter: int = 6
    ) -> float:
        """Try smaller spends until reserve_ok passes or min_spend reached."""
        spend = self.capped_spend(desired_spend, fraction)
        iteration = 0

        while spend >= min_spend and iteration < max_iter:
            qty = spend / price if price > 0 else 0.0
            if qty <= 0:
                break
            ok, _ = self.reserve_ok(side, price, qty, opposing_price)
            if ok:
                return spend
            spend *= reduction_factor
            iteration += 1

        return 0.0

    def cap_qty_to_reserve(
        self,
        side: str,
        price: float,
        desired_qty: float,
        opposing_price: Optional[float] = None,
        iterations: int = 20
    ) -> float:
        if price <= 0 or desired_qty <= 0:
            return 0.0
        ok, _ = self.reserve_ok(side, price, desired_qty, opposing_price)
        if ok:
            return desired_qty

        low = 0.0
        high = desired_qty
        for _ in range(iterations):
            mid = (low + high) / 2.0
            ok, _ = self.reserve_ok(side, price, mid, opposing_price)
            if ok:
                low = mid
            else:
                high = mid

        return low

    def _reserve_cash_needed_for_state(
        self,
        qty_up: float,
        qty_down: float,
        opposing_price: Optional[float] = None,
        cost_up: Optional[float] = None,
        cost_down: Optional[float] = None
    ) -> float:
        opposing_price = opposing_price if opposing_price is not None else 0.0
        cost_up = cost_up if cost_up is not None else self.cost_up
        cost_down = cost_down if cost_down is not None else self.cost_down

        if qty_up <= 0 and qty_down <= 0:
            return max(self.min_reserve_cash, self.market_budget * self.pre_hedge_reserve_ratio)

        if qty_up == 0 or qty_down == 0:
            qty_single = qty_up if qty_down == 0 else qty_down
            if qty_single <= 0:
                return max(self.min_reserve_cash, self.market_budget * self.pre_hedge_reserve_ratio)

            if qty_down == 0 and qty_up > 0:
                avg_single = cost_up / qty_up
            elif qty_up == 0 and qty_down > 0:
                avg_single = cost_down / qty_down
            else:
                avg_single = 0.0

            max_profitable_price = max(0.01, min(0.99, 0.99 - avg_single))
            observed_price = opposing_price if opposing_price > 0 else max_profitable_price
            est_price = max(self.reserve_price_floor, min(max_profitable_price, observed_price))

            dynamic = qty_single * est_price
            base = self.market_budget * self.pre_hedge_reserve_ratio
            return max(self.min_reserve_cash, base, dynamic)

        base = self.market_budget * self.post_hedge_reserve_ratio
        return max(self.min_reserve_cash, base)

    def reserve_ok(self, side: str, price: float, qty: float, opposing_price: Optional[float] = None) -> tuple:
        if price <= 0 or qty <= 0:
            return False, "Invalid trade sizing"
        cost = price * qty
        new_qty_up = self.qty_up + (qty if side == 'UP' else 0.0)
        new_qty_down = self.qty_down + (qty if side == 'DOWN' else 0.0)
        new_cost_up = self.cost_up + (cost if side == 'UP' else 0.0)
        new_cost_down = self.cost_down + (cost if side == 'DOWN' else 0.0)

        reserve_needed = self._reserve_cash_needed_for_state(
            new_qty_up,
            new_qty_down,
            opposing_price,
            new_cost_up,
            new_cost_down
        )
        budget_limit = self.market_budget * self.max_position_pct
        new_total_spent = new_cost_up + new_cost_down
        remaining_budget_after = budget_limit - new_total_spent
        cash_after = self.cash - cost

        if remaining_budget_after < -1e-6 or cash_after < -1e-6:
            return False, "Insufficient funds"

        if remaining_budget_after + 1e-6 < reserve_needed:
            return False, f"Need ${reserve_needed:.2f} budget reserved (have ${remaining_budget_after:.2f})"

        if cash_after + 1e-6 < reserve_needed:
            return False, f"Need ${reserve_needed:.2f} cash reserved (have ${cash_after:.2f})"

        return True, ""
        
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
        """Guaranteed profit regardless of outcome (worst-case), accounting for fees"""
        min_qty = min(self.qty_up, self.qty_down)
        total_cost = self.cost_up + self.cost_down
        fees = self.calculate_total_fees()
        return min_qty - total_cost - fees
    
    @property
    def best_case_profit(self) -> float:
        """Best-case profit if the larger position wins"""
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

    @property
    def position_delta_pct(self) -> float:
        """Position delta %: |UP - DOWN| / (UP + DOWN) × 100"""
        total = self.qty_up + self.qty_down
        if total == 0:
            return 0.0
        return abs(self.qty_up - self.qty_down) / total * 100

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
        """Calculate guaranteed profit after a hypothetical buy, with accurate fees"""
        cost = price * qty
        new_qty_up = self.qty_up + qty if side == 'UP' else self.qty_up
        new_qty_down = self.qty_down + qty if side == 'DOWN' else self.qty_down
        new_cost_up = self.cost_up + cost if side == 'UP' else self.cost_up
        new_cost_down = self.cost_down + cost if side == 'DOWN' else self.cost_down
        if new_qty_up == 0 or new_qty_down == 0:
            return 0.0
        
        # Calculate fees with new averages
        new_avg_up = new_cost_up / new_qty_up if new_qty_up > 0 else 0
        new_avg_down = new_cost_down / new_qty_down if new_qty_down > 0 else 0
        fee_up = self.calculate_fee(new_avg_up, new_qty_up)
        fee_down = self.calculate_fee(new_avg_down, new_qty_down)
        total_fees = fee_up + fee_down
        
        total_cost = new_cost_up + new_cost_down
        return min(new_qty_up, new_qty_down) - total_cost - total_fees

    def pair_cost_for_state(self, qty_up: float, cost_up: float, qty_down: float, cost_down: float) -> float:
        if qty_up <= 0 or qty_down <= 0:
            return float("inf")
        return (cost_up / qty_up) + (cost_down / qty_down)

    def best_pair_cost_after_spend(self, qty_up: float, cost_up: float, qty_down: float, cost_down: float,
                                   up_price: float, down_price: float, spend: float) -> float:
        best = self.pair_cost_for_state(qty_up, cost_up, qty_down, cost_down)
        if spend <= 0:
            return best

        for side, price in (("UP", up_price), ("DOWN", down_price)):
            if price <= 0:
                continue
            qty = spend / price
            if side == "UP":
                new_qty_up = qty_up + qty
                new_cost_up = cost_up + spend
                new_qty_down = qty_down
                new_cost_down = cost_down
            else:
                new_qty_down = qty_down + qty
                new_cost_down = cost_down + spend
                new_qty_up = qty_up
                new_cost_up = cost_up

            new_pair_cost = self.pair_cost_for_state(new_qty_up, new_cost_up, new_qty_down, new_cost_down)
            if new_pair_cost < best:
                best = new_pair_cost

        return best

    def can_recover_pair_cost(self, up_price: float, down_price: float, remaining_budget: float,
                              qty_up: Optional[float] = None, cost_up: Optional[float] = None,
                              qty_down: Optional[float] = None, cost_down: Optional[float] = None) -> bool:
        qty_up = self.qty_up if qty_up is None else qty_up
        cost_up = self.cost_up if cost_up is None else cost_up
        qty_down = self.qty_down if qty_down is None else qty_down
        cost_down = self.cost_down if cost_down is None else cost_down

        current_pair = self.pair_cost_for_state(qty_up, cost_up, qty_down, cost_down)
        if current_pair <= 1.0:
            return True
        if remaining_budget < self.min_trade_size:
            return False

    def _pair_reserve_ok(self, up_price: float, down_price: float, qty: float) -> tuple:
        """Reserve check for a paired buy of qty on BOTH sides."""
        if qty <= 0 or up_price <= 0 or down_price <= 0:
            return False, "Invalid paired sizing"

        cost_up = up_price * qty
        cost_down = down_price * qty
        total_cost = cost_up + cost_down

        new_qty_up = self.qty_up + qty
        new_qty_down = self.qty_down + qty
        new_cost_up = self.cost_up + cost_up
        new_cost_down = self.cost_down + cost_down

        reserve_needed = self._reserve_cash_needed_for_state(
            new_qty_up,
            new_qty_down,
            opposing_price=None,
            cost_up=new_cost_up,
            cost_down=new_cost_down,
        )

        budget_limit = self.market_budget * self.max_position_pct
        new_total_spent = new_cost_up + new_cost_down
        remaining_budget_after = budget_limit - new_total_spent
        cash_after = self.cash - total_cost

        if remaining_budget_after < -1e-6 or cash_after < -1e-6:
            return False, "Insufficient funds"

        if remaining_budget_after + 1e-6 < reserve_needed:
            return False, f"Need ${reserve_needed:.2f} budget reserved (have ${remaining_budget_after:.2f})"

        if cash_after + 1e-6 < reserve_needed:
            return False, f"Need ${reserve_needed:.2f} cash reserved (have ${cash_after:.2f})"

        return True, ""

    def _attempt_pair_profit_compound(
        self,
        up_price: float,
        down_price: float,
        locked_profit: float,
        pair_cost: float,
        remaining_budget: float,
        timestamp: str,
    ) -> List[tuple]:
        """Try to increase locked profit by buying equal qty of UP and DOWN."""
        trades: List[tuple] = []
        if up_price <= 0 or down_price <= 0:
            return trades

        combined = up_price + down_price
        if combined > self.pair_growth_max_pair_price + 1e-9:
            return trades

        growth_budget = min(
            remaining_budget * self.pair_growth_budget_fraction,
            self.growth_max_single_trade,
            self.affordable_cash(self.pair_growth_budget_fraction),
        )

        if growth_budget < self.min_trade_size * 2:
            return trades

        qty = growth_budget / combined
        if qty < 0.5:
            return trades

        # Simulate new averages and new locked profit (incl fees)
        new_qty_up = self.qty_up + qty
        new_qty_down = self.qty_down + qty
        new_cost_up = self.cost_up + (qty * up_price)
        new_cost_down = self.cost_down + (qty * down_price)
        new_avg_up = new_cost_up / new_qty_up
        new_avg_down = new_cost_down / new_qty_down
        new_pair_cost = new_avg_up + new_avg_down

        fee_up = self.calculate_fee(new_avg_up, new_qty_up)
        fee_down = self.calculate_fee(new_avg_down, new_qty_down)
        new_fees = fee_up + fee_down

        new_total_spent = new_cost_up + new_cost_down
        new_min_qty = min(new_qty_up, new_qty_down)
        new_locked = new_min_qty - new_total_spent - new_fees
        improvement = new_locked - locked_profit

        # Dynamic pair cost limit: be more aggressive when locked profit < $3
        max_allowed_pair = (
            self.growth_max_pair_cost_low_profit 
            if locked_profit < self.min_target_locked_profit 
            else self.growth_max_pair_cost
        )
        
        if new_pair_cost > max_allowed_pair + 1e-9:
            return trades

        if improvement < self.pair_growth_min_improvement:
            return trades

        ok, reason = self._pair_reserve_ok(up_price, down_price, qty)
        if not ok:
            print(f"⚠️  [PAIR GROWTH BLOCKED] {reason}")
            return trades

        self.current_mode = 'profit_growth'
        self.mode_reason = f'Compounding locked profit (+${improvement:.2f}) @ ${combined:.3f} pair'

        if self.execute_buy('UP', up_price, qty, timestamp):
            trades.append(('UP', up_price, qty))
        if self.execute_buy('DOWN', down_price, qty, timestamp):
            trades.append(('DOWN', down_price, qty))

        print(f"📈 [PAIR COMPOUND] Bought {qty:.1f} UP + {qty:.1f} DOWN | pair ${pair_cost:.3f}→${new_pair_cost:.3f} | locked ${locked_profit:.2f}→${new_locked:.2f}")
        return trades

        best = self.best_pair_cost_after_spend(
            qty_up,
            cost_up,
            qty_down,
            cost_down,
            up_price,
            down_price,
            remaining_budget
        )
        return best <= 1.0

    def evaluate_worst_positioned_side(self, up_price: float, down_price: float) -> tuple:
        """
        ENHANCED: Spread-aware + Asymmetric PnL optimization
        
        Evaluates which side to prioritize considering:
        - Spread opportunities (high spread = aggressive buying)
        - Expected value optimization (not just worst-case)
        - Strategic imbalance (allow more qty on better average side)
        - Discount opportunities
        - Pair cost trajectory
        
        Returns: (worst_side, severity_score, recommended_spend, reason)
        """
        if self.qty_up == 0 or self.qty_down == 0:
            return None, 0, 0, "Need both sides"
        
        # Calculate conservative mode status
        min_qty = min(self.qty_up, self.qty_down) if self.qty_up > 0 and self.qty_down > 0 else 0
        total_spent = self.cost_up + self.cost_down
        fees = self.calculate_total_fees()
        unrealized = min_qty - total_spent - fees
        in_conservative_mode = unrealized < self.conservative_mode_loss_threshold
        
        # === SPREAD ANALYSIS ===
        spread = abs(up_price - down_price)
        spread_pct = spread / max(up_price, down_price) if max(up_price, down_price) > 0 else 0
        high_spread = spread > self.high_spread_threshold
        medium_spread = spread > self.medium_spread_threshold
        
        # Calculate metrics for each side
        up_discount = self.avg_up - up_price  # Positive = good buying opportunity
        down_discount = self.avg_down - down_price
        
        up_discount_pct = up_discount / self.avg_up if self.avg_up > 0 else 0
        down_discount_pct = down_discount / self.avg_down if self.avg_down > 0 else 0
        
        # === EXPECTED VALUE CALCULATION ===
        # Use prices as probability estimates: up_price ≈ P(UP wins)
        prob_up = up_price
        prob_down = down_price
        pnl_if_up = self.qty_up - total_spent - fees
        pnl_if_down = self.qty_down - total_spent - fees
        expected_pnl = (prob_up * pnl_if_up) + (prob_down * pnl_if_down)
        worst_case_pnl = min(pnl_if_up, pnl_if_down)
        
        # Potential hedge cost for each side
        up_hedge_cost = self.qty_up * down_price
        down_hedge_cost = self.qty_down * up_price
        
        # Which side has worse avg vs current price?
        up_pair_if_buy = self.simulate_buy('UP', up_price, 10)[1]
        down_pair_if_buy = self.simulate_buy('DOWN', down_price, 10)[1]
        
        # Imbalance
        ratio = max(self.qty_up, self.qty_down) / min(self.qty_up, self.qty_down)
        up_is_lagging = self.qty_up < self.qty_down
        down_is_lagging = self.qty_down < self.qty_up
        
        # Score each side (higher = more urgent to fix)
        up_score = 0
        down_score = 0
        
        # CRITICAL: If locked profit is negative, prioritize LAGGING side heavily
        # Because only buying the lagging side increases min_qty!
        if unrealized < 0:
            if up_is_lagging:
                up_score += abs(unrealized) * 2  # Heavy weight based on loss size
            if down_is_lagging:
                down_score += abs(unrealized) * 2
        
        # === SPREAD BONUS: High spread = opportunity BUT NOT PRIMARY FOCUS ===
        # The cheaper side in high-spread situations is valuable
        # BUT: If pair cost is already good (<0.95), HEAVILY dampen this
        # CRITICAL: We need BOTH sides positioned well, not just the cheap side!
        current_pair = self.pair_cost
        spread_score_multiplier = 80  # Reduced from 150
        if current_pair < 0.95:
            spread_score_multiplier = 5  # Reduce from 30 to 5 when pair is good - almost ignore spread!
        
        if high_spread:
            if up_price < down_price:
                up_score += spread_pct * spread_score_multiplier
            else:
                down_score += spread_pct * spread_score_multiplier
        elif medium_spread:
            medium_spread_multiplier = 40  # Reduced from 80
            if current_pair < 0.95:
                medium_spread_multiplier = 3  # Reduce from 20 to 3 when pair is good
            if up_price < down_price:
                up_score += spread_pct * medium_spread_multiplier
            else:
                down_score += spread_pct * medium_spread_multiplier
        
        # Big discount = opportunity
        if up_discount_pct > 0.02:  # > 2% discount
            up_score += up_discount_pct * 100
        if down_discount_pct > 0.02:
            down_score += down_discount_pct * 100
        
        # === WORST CASE OPTIMIZATION (when pair is good) ===
        # If pair < 0.95 and worst case is negative, MASSIVELY prioritize fixing it
        # This is CRITICAL - if we lose on one side, fix that side!
        if current_pair < 0.95 and worst_case_pnl < 0:
            # Which side would improve worst case if we bought it?
            # If UP wins gives worst case, buy DOWN. If DOWN wins gives worst case, buy UP.
            if pnl_if_up < pnl_if_down:  # UP outcome is worse
                # Buying DOWN improves UP outcome (reduces avg_down, increases max acceptable up_price)
                # INCREASED: Was 3, now 10 - make this a TOP priority!
                down_score += abs(worst_case_pnl) * 10  # Massive bonus to fix worst case
            else:  # DOWN outcome is worse
                up_score += abs(worst_case_pnl) * 10  # Massive bonus to fix worst case
        
        # High avg = harder to hedge = more urgent to fix
        if self.avg_up > 0.55:
            up_score += (self.avg_up - 0.55) * 50
        if self.avg_down > 0.55:
            down_score += (self.avg_down - 0.55) * 50
        
        # STRATEGIC IMBALANCE: Allow more on better-average side
        # Don't penalize lagging if it has significantly better average
        better_avg_up = self.avg_up < self.avg_down - 0.05  # UP avg is 5¢ better
        better_avg_down = self.avg_down < self.avg_up - 0.05
        
        if up_is_lagging and ratio > 1.15:
            # Reduce penalty if UP has better average (we WANT more UP)
            penalty = (ratio - 1.0) * 10
            if better_avg_up and ratio < self.strategic_imbalance_max:
                penalty *= 0.3  # Reduce penalty by 70%
            up_score += penalty
        if down_is_lagging and ratio > 1.15:
            penalty = (ratio - 1.0) * 10
            if better_avg_down and ratio < self.strategic_imbalance_max:
                penalty *= 0.3
            down_score += penalty
        
        # Pair cost improvement potential
        current_pair = self.pair_cost
        if current_pair > 0.97:
            if up_pair_if_buy < current_pair:
                up_score += (current_pair - up_pair_if_buy) * 200
            if down_pair_if_buy < current_pair:
                down_score += (current_pair - down_pair_if_buy) * 200
        
        # === BLOCK TRADES THAT WORSEN WORST CASE (when pair is good) ===
        # If pair < 0.95 and worst case < 0, don't buy side that makes it worse
        if current_pair < 0.95 and worst_case_pnl < 0:
            # Buying UP makes "if DOWN wins" worse (more qty_up, same avg_down)
            # Buying DOWN makes "if UP wins" worse (more qty_down, same avg_up)
            if pnl_if_up < pnl_if_down:  # UP outcome is already worse
                # Don't make it worse by buying UP
                if up_score > down_score:
                    print(f"  🚫 [WORST CASE BLOCK] Refusing UP (would worsen worst case ${worst_case_pnl:.2f})")
                    up_score = 0  # Block UP
            else:  # DOWN outcome is worse
                if down_score > up_score:
                    print(f"  🚫 [WORST CASE BLOCK] Refusing DOWN (would worsen worst case ${worst_case_pnl:.2f})")
                    down_score = 0  # Block DOWN
        
        # === TIME-BASED BALANCE PRIORITY ===
        # After grace period, heavily boost priority for the smaller side
        time_since_first = time.time() - self.first_trade_time if self.first_trade_time > 0 else 0
        if time_since_first > self.balance_enforcement_delay:
            current_delta_pct = abs(self.qty_up - self.qty_down) / (self.qty_up + self.qty_down) * 100
            if current_delta_pct > self.ideal_balance_delta_pct:  # >5% imbalance
                balance_urgency = current_delta_pct * 5  # 10% delta = +50 severity
                if up_is_lagging:
                    up_score += balance_urgency
                    print(f"  ⏱️ [BALANCE BOOST] UP lagging - adding {balance_urgency:.1f} severity (delta {current_delta_pct:.1f}%)")
                if down_is_lagging:
                    down_score += balance_urgency
                    print(f"  ⏱️ [BALANCE BOOST] DOWN lagging - adding {balance_urgency:.1f} severity (delta {current_delta_pct:.1f}%)")
        
        # Decide worst side
        if up_score > down_score and up_score > 1.0:
            worst_side = 'UP'
            severity = up_score
            # Dynamic spend based on severity, discount, AND SPREAD
            base_spend_pct = 0.02  # Was 0.04
            if up_discount_pct > 0.10:  # >10% discount
                base_spend_pct = 0.10  # Was 0.20
            elif up_discount_pct > 0.05:  # >5% discount
                base_spend_pct = 0.06  # Was 0.125
            elif up_discount_pct > 0.02:  # >2% discount
                base_spend_pct = 0.04  # Was 0.075
            
            # SPREAD MULTIPLIER: Buy more during high spread
            if high_spread:
                base_spend_pct *= self.spread_multiplier  # 2x when spread is huge
            elif medium_spread:
                base_spend_pct *= 1.5
            
            recommended_spend = min(
                self.cash * base_spend_pct,
                self.max_single_trade,  # Respect single trade limit
                self.affordable_cash(base_spend_pct)
            )
            # Cut spending in half if we're in conservative mode (losing money)
            if in_conservative_mode:
                recommended_spend *= 0.5
            
            spread_info = f", spread={spread_pct*100:.0f}%" if spread > 0.10 else ""
            reason = f"UP: {up_discount_pct*100:.1f}% discount, avg=${self.avg_up:.3f}, score={up_score:.1f}{spread_info}"
        elif down_score > 1.0:
            worst_side = 'DOWN'
            severity = down_score
            base_spend_pct = 0.02  # Was 0.04
            if down_discount_pct > 0.10:
                base_spend_pct = 0.10  # Was 0.20
            elif down_discount_pct > 0.05:
                base_spend_pct = 0.06  # Was 0.125
            elif down_discount_pct > 0.02:
                base_spend_pct = 0.04  # Was 0.075
            
            # SPREAD MULTIPLIER
            if high_spread:
                base_spend_pct *= self.spread_multiplier
            elif medium_spread:
                base_spend_pct *= 1.5
            
            recommended_spend = min(
                self.cash * base_spend_pct,
                self.max_single_trade,
                self.affordable_cash(base_spend_pct)
            )
            if in_conservative_mode:
                recommended_spend *= 0.5
            
            spread_info = f", spread={spread_pct*100:.0f}%" if spread > 0.10 else ""
            reason = f"DOWN: {down_discount_pct*100:.1f}% discount, avg=${self.avg_down:.3f}, score={down_score:.1f}{spread_info}"
        else:
            return None, 0, 0, "No clear priority"
        
        return worst_side, severity, recommended_spend, reason
    
    def should_improve_position(self, side: str, price: float, opposing_price: float = None) -> tuple:
        """
        POSITION IMPROVEMENT STRATEGY
        
        Check if we should buy MORE of the same side to lower our average cost.
        This widens the profitable window for hedging the other side.
        
        Example:
        - Current: avg_DOWN = $0.51, max UP = $0.48 for profit
        - If DOWN drops to $0.45, buy more!
        - New avg_DOWN = $0.48, now max UP = $0.51 (easier to hit!)
        
        Returns: (should_buy, qty, reason)
        """
        my_qty = self.qty_up if side == 'UP' else self.qty_down
        my_cost = self.cost_up if side == 'UP' else self.cost_down
        my_avg = my_cost / my_qty if my_qty > 0 else 0
        other_qty = self.qty_down if side == 'UP' else self.qty_up
        other_cost = self.cost_down if side == 'UP' else self.cost_up
        other_avg = other_cost / other_qty if other_qty > 0 else 0
        other_side = 'DOWN' if side == 'UP' else 'UP'
        
        # Only improve if we have a position on this side
        if my_qty == 0:
            return False, 0, "No position to improve"
        
        # TIME-BASED BALANCE ENFORCEMENT
        # After grace period, aggressively enforce balance
        time_since_first = time.time() - self.first_trade_time if self.first_trade_time > 0 else 0
        strict_balance_mode = time_since_first > self.balance_enforcement_delay
        
        # CRITICAL: HARD STOP - Never improve if we're already 1.2x+ larger than other side
        # v11: Much stricter - balance is EVERYTHING!
        if other_qty > 0:
            current_ratio = my_qty / other_qty
            if current_ratio > 1.15:  # Hard stop at 1.15x imbalance (WAS 2.0x)
                return False, 0, f"🚨 HARD STOP: ratio {current_ratio:.2f}x - MUST balance {other_side} first!"
            
            # CRITICAL: DELTA PROTECTION - Stricter after grace period
            current_delta_pct = abs(my_qty - other_qty) / (my_qty + other_qty) * 100
            
            # After 30s: Don't improve larger side if delta >5% (strict mode)
            # Before 30s: Allow up to 15% delta (flexible mode)
            max_allowed_delta = self.ideal_balance_delta_pct if strict_balance_mode else self.max_flex_delta_pct
            
            if current_delta_pct > max_allowed_delta and my_qty > other_qty:
                mode_str = "STRICT" if strict_balance_mode else "FLEX"
                return False, 0, f"🚨 DELTA STOP ({mode_str}): {current_delta_pct:.1f}% > {max_allowed_delta:.1f}% - MUST balance {other_side} first!"
        
        # CRITICAL: Stop buying if opposite side is too expensive for ANY hedge
        # Even break-even requires pair <= 1.00, so if opposite > stop_threshold,
        # we'd need avg < (1.00 - opposite) which may be impossible
        if opposing_price is not None and opposing_price > self.stop_buying_opposite_price:
            max_avg_for_breakeven = 1.00 - opposing_price
            if my_avg > max_avg_for_breakeven:
                return False, 0, f"🛑 STOP: opposite ${opposing_price:.2f} too expensive, need avg <${max_avg_for_breakeven:.2f}"
        
        # Check if current price is below our average (ANY amount!)
        price_improvement = my_avg - price
        price_improvement_pct = price_improvement / my_avg if my_avg > 0 else 0
        
        # DEBUG
        print(f"  🔍 [IMPROVE CHECK {side}] price=${price:.3f} avg=${my_avg:.3f} diff=${price_improvement:.3f} ({price_improvement_pct*100:.1f}%)")
        
        if price >= my_avg:
            return False, 0, f"Price ${price:.3f} >= avg ${my_avg:.3f}"
        
        if price_improvement < self.improvement_threshold and price_improvement_pct < self.min_improvement_pct:
            return False, 0, f"Improvement only ${price_improvement:.3f} ({price_improvement_pct*100:.1f}%) - need >{self.improvement_threshold} or >{self.min_improvement_pct*100}%"
        
        # If we have both sides, check imbalance
        if other_qty > 0:
            current_ratio = my_qty / other_qty
            # If we're already the larger side by a lot, only improve if profit is not locked
            if current_ratio > self.max_imbalance_for_improvement:
                # Allow if we don't have locked profit yet, or if improvement is significant
                if self.locked_profit > 0 and price_improvement_pct < 0.10:  # < 10% improvement
                    return False, 0, f"Already ahead: {current_ratio:.2f}x ratio"
        available = min(self.affordable_cash(self.improvement_trade_pct), self.max_single_trade)
        
        if available < self.min_trade_size:
            return False, 0, f"Insufficient budget ${available:.2f}"

        desired_spend = available
        if other_qty == 0:
            last_price = self.last_improvement_price.get(side)
            if last_price is not None and price > last_price - self.improvement_step_price + 1e-6:
                required = max(0.0, last_price - self.improvement_step_price)
                return False, 0, f"Need price <= ${required:.3f} for next ladder"
            
            # Accelerated ladder: spend more at lower prices
            ladder_spend = self.ladder_tiers[-1][1]  # default
            for threshold, spend_amt in self.ladder_tiers:
                if price <= threshold:
                    ladder_spend = spend_amt
                    break
            desired_spend = min(ladder_spend, available)
            
            # Check max spend per side limit
            if my_cost + desired_spend > self.max_spend_per_side:
                remaining_allowed = self.max_spend_per_side - my_cost
                if remaining_allowed < self.min_trade_size:
                    return False, 0, f"Max spend per side ${self.max_spend_per_side:.0f} reached"
                desired_spend = min(desired_spend, remaining_allowed)
            
            # Check break-even hedge reserve
            if self.enable_breakeven_check:
                can_spend, allowed_spend, reason = self._check_breakeven_reserve(side, price, my_qty, my_cost, desired_spend)
                if not can_spend:
                    return False, 0, reason
                if allowed_spend < desired_spend:
                    print(f"  💰 [BREAKEVEN CAP] {reason}")
                    desired_spend = allowed_spend
        
        spend = self.capped_spend_until_ok(
            side,
            price,
            desired_spend=desired_spend,
            opposing_price=other_avg if other_qty > 0 else None,
            fraction=1.0,
            min_spend=self.min_trade_size
        )

        throttle_ok, allowed_spend, throttle_reason = self._evaluate_improvement_throttle(side, spend)
        throttled = False
        if not throttle_ok:
            if allowed_spend >= self.min_trade_size:
                spend = allowed_spend
                throttled = True
            else:
                return False, 0, throttle_reason

        if spend < self.min_trade_size:
            return False, 0, f"Insufficient reserve for improvement"

        qty = spend / price
        
        # Simulate the new average
        new_cost = my_cost + (qty * price)
        new_qty = my_qty + qty
        new_avg = new_cost / new_qty
        avg_improvement = my_avg - new_avg
        
        # Check: new average must be meaningfully better
        if avg_improvement < 0.01:
            return False, 0, f"Would only improve avg by ${avg_improvement:.3f}"
        
        # Calculate new hedge requirement
        old_max_hedge_price = 1.0 - my_avg
        new_max_hedge_price = 1.0 - new_avg
        window_expansion = new_max_hedge_price - old_max_hedge_price

        reason = f"📈 IMPROVE: +${spend:.2f} avg ${my_avg:.3f}→${new_avg:.3f} | hedge window expands by ${window_expansion:.3f}"
        if throttled:
            reason += f" | throttle cap ${self.improvement_spend_cap:.0f}/{self.improvement_spend_window:.0f}s"

        return True, qty, reason

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
        
        # ============================================================
        # GOAL: min(qty_up, qty_down) > total_spent  AND  pair_cost < $1
        # This guarantees profit regardless of outcome!
        # ============================================================
        
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
        
        # === PHASE 2: HEDGE or IMPROVE - One side only ===
        if my_qty == 0 and other_qty > 0:
            potential_pair = other_avg + price
            
            # === NEW: POSITION IMPROVEMENT ===
            # Before accepting a bad hedge, check if we can IMPROVE the existing position!
            # If the OTHER side (which we own) has a better price now, buy more to lower avg
            other_side_local = 'DOWN' if side == 'UP' else 'UP'
            should_improve, improve_qty, improve_reason = self.should_improve_position(other_side_local, other_price, opposing_price=price)
            
            if should_improve and potential_pair > 0.96:
                # The hedge would be expensive - try improving instead!
                return False, 0, f"⏳ Hedge expensive (pair ${potential_pair:.3f}). {improve_reason}"
            
            # After 10 seconds, refuse pair > $1.00 unless it is mathematically recoverable
            market_elapsed = 900.0 - time_to_close if time_to_close is not None else 0.0
            if market_elapsed > 10 and potential_pair > 1.0:
                target_qty = other_qty
                hedge_cost = target_qty * price
                remaining_after = remaining_budget - hedge_cost

                if side == 'UP':
                    qty_up_after = self.qty_up + target_qty
                    cost_up_after = self.cost_up + hedge_cost
                    qty_down_after = self.qty_down
                    cost_down_after = self.cost_down
                    up_price = price
                    down_price = other_price
                else:
                    qty_down_after = self.qty_down + target_qty
                    cost_down_after = self.cost_down + hedge_cost
                    qty_up_after = self.qty_up
                    cost_up_after = self.cost_up
                    up_price = other_price
                    down_price = price

                recoverable = remaining_after >= self.min_trade_size and self.can_recover_pair_cost(
                    up_price,
                    down_price,
                    remaining_after,
                    qty_up_after,
                    cost_up_after,
                    qty_down_after,
                    cost_down_after
                )

                if not recoverable:
                    return False, 0, f"⛔ REFUSE hedge: pair ${potential_pair:.3f} > $1.00 after {market_elapsed:.0f}s"
            
            # Match qty to balance
            target_qty = other_qty
            cost_needed = target_qty * price
            # Allow larger hedge if it locks profit, otherwise cap at max_single_trade
            will_lock_profit = (min(target_qty, other_qty) - (self.cost_up + self.cost_down + cost_needed)) > 0
            if will_lock_profit:
                max_spend = min(cost_needed, self.cash * 0.8)  # Can spend more to lock profit
            else:
                max_spend = min(cost_needed, self.max_single_trade, self.cash * 0.3)  # Limited otherwise
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
        
        # TARGET: pair_cost < $0.93 to ensure profit after fees!
        TARGET_PAIR_COST = 0.93
        
        # === SUCCESS CHECK ===
        # v12: NEVER stop trading just because we have profit!
        # Always look for ways to GROW profit until market closes
        profit_growth_mode = guaranteed_profit > 0 and current_pair_cost < TARGET_PAIR_COST
        # REMOVED: No longer stop when profit is locked - keep growing!
        # if profit_growth_mode and not self.allow_profit_growth:
        #     return False, 0, f"✅ DONE! profit=${guaranteed_profit:.2f}, pair=${current_pair_cost:.3f}"

        def profit_growth_allows(new_locked: float, new_pair_cost: float) -> bool:
            """v12: Much more permissive - allow trades that don't HURT us significantly"""
            if not profit_growth_mode:
                return True
            # Allow if pair cost improves
            if new_pair_cost < current_pair_cost:
                return True
            # Allow if locked profit increases
            if new_locked > guaranteed_profit:
                return True
            # v12: Also allow if we maintain at least 90% of locked profit
            # and pair cost doesn't get too bad (< 0.99)
            profit_preserved = new_locked >= guaranteed_profit * 0.90
            pair_still_safe = new_pair_cost < 0.99
            if profit_preserved and pair_still_safe:
                return True
            return False
        
        # === NEED TO IMPROVE ===
        # Strategy: Buy whichever side helps reach the goal
        
        # RULE 0: EMERGENCY STOP - Never allow ratio > 1.35x (v11: was 2.5x)
        if ratio > self.emergency_ratio:
            return False, 0, f"🚨 EMERGENCY STOP: Ratio {ratio:.2f}x > {self.emergency_ratio}x - MUST buy {other_side} first!"
        
        # RULE 0.5: CRITICAL - Don't buy larger side when ratio > 1.2x (v11: was 2.0x)
        if ratio > self.critical_ratio and my_qty > other_qty:
            return False, 0, f"🛑 CRITICAL: Ratio {ratio:.2f}x - cannot buy {side}, must balance with {other_side} first"
        
        # RULE 1: Don't exceed ratio of 1.10 under normal conditions (v11: was 1.3)
        if ratio > 1.10 and my_qty > other_qty:
            return False, 0, f"⛔ Ratio {ratio:.2f}x - need to buy {other_side}"
        
        # RULE 1.5: PRIORITIZE balance when position delta > 5%
        # This ensures we maintain tight qty balance for guaranteed profit
        current_delta_pct = abs(my_qty - other_qty) / (my_qty + other_qty) * 100 if (my_qty + other_qty) > 0 else 0
        
        if current_delta_pct > self.ideal_balance_delta_pct and my_qty < other_qty:
            # We're the lagging side and imbalance exceeds 5% - prioritize catching up
            # Target: reduce delta to 5% or less
            target_my_qty = other_qty * (1 - self.ideal_balance_delta_pct / 100) / (1 + self.ideal_balance_delta_pct / 100)
            qty_to_balance = max(0, target_my_qty - my_qty)
            
            if qty_to_balance > 0:
                max_spend = min(self.cash * 0.4, qty_to_balance * price, remaining_budget)
                qty = max_spend / price
                
                if qty * price >= self.min_trade_size:
                    new_locked = self.locked_profit_after_buy(side, price, qty)
                    new_my_qty = my_qty + qty
                    new_delta_pct = abs(new_my_qty - other_qty) / (new_my_qty + other_qty) * 100
                    new_avg, new_pair_cost = self.simulate_buy(side, price, qty)
                    if profit_growth_allows(new_locked, new_pair_cost):
                        return True, qty, f"⚖️ BALANCE (5% rule): delta {current_delta_pct:.1f}%→{new_delta_pct:.1f}%, locked ${guaranteed_profit:.2f}→${new_locked:.2f}"
        
        # RULE 2: If we're the lagging side, buy to catch up (increases min_qty!)
        # v11: Trigger rebalance earlier at 0.98 ratio (WAS 0.95)
        if ratio < 0.98:
            qty_to_balance = other_qty - my_qty
            max_spend = min(self.cash * 0.7, qty_to_balance * price, remaining_budget)  # 70% of cash for balance
            qty = max_spend / price
            
            if qty * price >= self.min_trade_size:
                new_locked = self.locked_profit_after_buy(side, price, qty)
                new_ratio = (my_qty + qty) / other_qty
                new_avg, new_pair_cost = self.simulate_buy(side, price, qty)
                if profit_growth_allows(new_locked, new_pair_cost):
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
                if profit_growth_allows(new_locked, new_pair_cost):
                    return True, qty, f"📉 REDUCE: pair ${current_pair_cost:.3f}→${new_pair_cost:.3f}, locked ${guaranteed_profit:.2f}→${new_locked:.2f}"
        
        # RULE 4: If pair_cost < TARGET, buy cheap to grow position
        # v11: Only allow growth if almost balanced (ratio <= 1.05, was 1.15)
        if price <= self.cheap_threshold and ratio <= 1.05:
            max_spend = min(self.cash * 0.3, self.max_single_trade, remaining_budget)
            qty = max_spend / price
            
            if qty * price >= self.min_trade_size:
                new_locked = self.locked_profit_after_buy(side, price, qty)
                new_avg, new_pair_cost = self.simulate_buy(side, price, qty)
                if new_locked > guaranteed_profit and profit_growth_allows(new_locked, new_pair_cost):
                    return True, qty, f"💰 CHEAP @ ${price:.3f}: locked ${guaranteed_profit:.2f}→${new_locked:.2f}"
        
        return False, 0, f"⏳ pair=${current_pair_cost:.3f} (target <${TARGET_PAIR_COST}), locked=${guaranteed_profit:.2f}, ratio={ratio:.2f}x"
    
    def execute_buy(self, side: str, price: float, qty: float, timestamp: str, mode: str = None, reason: str = None):
        cost = price * qty
        # No cash limit for testing - just track spending
        
        self.cash -= cost
        self.trade_count += 1
        self.last_trade_time = time.time()
        
        if side == 'UP':
            self.qty_up += qty
            self.cost_up += cost
        else:
            self.qty_down += qty
            self.cost_down += cost

        # Update ladder anchor for this side
        self.last_improvement_price[side] = price
        
        # Update mode if provided
        if mode:
            self.current_mode = mode
        if reason:
            self.mode_reason = reason
        
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
    
    def _attempt_profit_growth(self, up_price: float, down_price: float, locked_profit: float, pair_cost: float, remaining_budget: float, timestamp: str) -> List[tuple]:
        """
        PROFIT GROWTH MODE
        
        After securing locked profit, continue buying strategically to maximize upside.
        
        Strategy:
        1. Identify favorable side (better avg OR higher probability)
        2. Use limited budget (% of locked profit)
        3. Only buy if it improves expected value
        4. Stop if pair cost approaches danger zone
        
        Returns: list of trades made
        """
        trades = []
        
        # Calculate growth budget - use available budget
        # v12: More aggressive - use 70% of remaining budget
        growth_budget = min(
            remaining_budget * 0.70,  # Use up to 70% of remaining budget per trade (WAS 50%)
            self.growth_max_single_trade,
            self.affordable_cash(0.70) # Ensure we have actual cash
        )
        
        if growth_budget < self.min_trade_size:
            return trades
        
        # Determine which side to favor
        # Factor 1: Market probability (price indicates probability)
        prob_up = up_price
        prob_down = down_price
        
        # Factor 2: Better average
        avg_advantage_up = self.avg_down - self.avg_up if self.avg_down > 0 and self.avg_up > 0 else 0
        avg_advantage_down = self.avg_up - self.avg_down if self.avg_up > 0 and self.avg_down > 0 else 0
        
        # Factor 3: Expected value calculation
        total_spent = self.cost_up + self.cost_down
        fees = self.calculate_total_fees()
        ev_up = (prob_up * self.qty_up) - total_spent - fees
        ev_down = (prob_down * self.qty_down) - total_spent - fees
        
        # Score each side
        up_score = 0
        down_score = 0
        
        if self.growth_favor_probability:
            up_score += prob_up * 100
            down_score += prob_down * 100
        
        if self.growth_favor_better_avg:
            up_score += avg_advantage_up * 50
            down_score += avg_advantage_down * 50
        
        # Bonus for side that's below its average (can improve avg further)
        if up_price < self.avg_up:
            discount = (self.avg_up - up_price) / self.avg_up
            up_score += discount * 30
        if down_price < self.avg_down:
            discount = (self.avg_down - down_price) / self.avg_down
            down_score += discount * 30
        
        # Choose side to grow
        # v12: Lower score requirement from 5 to 2 - be more willing to grow
        if up_score > down_score and up_score > 2:
            growth_side = 'UP'
            growth_price = up_price
            opposing_price = down_price
            reason = f"Growing UP: prob={prob_up:.0%}, avg_adv=${avg_advantage_up:.3f}, score={up_score:.1f}"
        elif down_score > 2:
            growth_side = 'DOWN'
            growth_price = down_price
            opposing_price = up_price
            reason = f"Growing DOWN: prob={prob_down:.0%}, avg_adv=${avg_advantage_down:.3f}, score={down_score:.1f}"
        else:
            return trades  # No clear advantage
        
        # Calculate qty to buy
        qty = growth_budget / growth_price
        
        if qty < 0.5:
            return trades
        
        # Simulate the trade - check if pair cost stays safe
        if growth_side == 'UP':
            new_cost_up = self.cost_up + growth_budget
            new_qty_up = self.qty_up + qty
            new_avg_up = new_cost_up / new_qty_up
            new_pair_cost = new_avg_up + self.avg_down
        else:
            new_cost_down = self.cost_down + growth_budget
            new_qty_down = self.qty_down + qty
            new_avg_down = new_cost_down / new_qty_down
            new_pair_cost = self.avg_up + new_avg_down
        
        # Safety check: don't worsen pair cost too much
        # Dynamic limit: be more aggressive when locked profit < $3
        max_allowed_pair = (
            self.growth_max_pair_cost_low_profit 
            if locked_profit < self.min_target_locked_profit 
            else self.growth_max_pair_cost
        )
        
        if new_pair_cost > max_allowed_pair:
            print(f"⚠️ [GROWTH BLOCKED] Would push pair ${pair_cost:.3f}→${new_pair_cost:.3f} > ${max_allowed_pair:.3f}")
            return trades

        # Guardrail: one-sided growth must not destroy locked profit (tail-loss protection)
        new_locked = self.locked_profit_after_buy(growth_side, growth_price, qty)
        if new_locked < self.growth_min_locked_after_trade - 1e-9:
            print(f"⚠️ [GROWTH BLOCKED] Would reduce locked ${locked_profit:.2f}→${new_locked:.2f} (< ${self.growth_min_locked_after_trade:.2f})")
            return trades
        
        # Check reserves
        ok, reserve_reason = self.reserve_ok(growth_side, growth_price, qty, opposing_price)
        if not ok:
            print(f"⚠️ [GROWTH BLOCKED] {reserve_reason}")
            return trades
        
        # Execute growth trade
        self.current_mode = 'profit_growth'
        self.mode_reason = f'Growing position: {reason}'
        
        if self.execute_buy(growth_side, growth_price, qty, timestamp):
            trades.append((growth_side, growth_price, qty))
            print(f"📈 [PROFIT GROWTH] {reason}")
            print(f"   Bought {qty:.1f} {growth_side} @ ${growth_price:.3f} (${growth_budget:.2f})")
            print(f"   pair: ${pair_cost:.3f}→${new_pair_cost:.3f} | locked was ${locked_profit:.2f}")
        
        return trades
    
    def check_and_trade(self, up_price: float, down_price: float, timestamp: str, time_to_close: float = None, up_bid: Optional[float] = None, down_bid: Optional[float] = None):
        """
        GABAGOOL v9 - ULTRA AGGRESSIVE PROFIT HUNTER
        
        RULE: If locked profit < 0, ALWAYS try to buy something to improve it!
        Buy small amounts constantly until profit is locked.
        
        GOAL: min(qty_up, qty_down) > total_spent + fees
        """
        trades_made = []
        
        # Cooldown check
        now = time.time()
        if now - self.last_trade_time < self.cooldown_seconds:
            return trades_made
        
        total_spent = self.cost_up + self.cost_down
        budget_limit = self.starting_balance * self.max_position_pct
        remaining_budget = max(0, budget_limit - total_spent)
        
        # === LOSS PROTECTION: Only abandon if mathematically impossible to profit ===
        if self.qty_up > 0 and self.qty_down > 0:
            # ABANDON only if pair cost makes profit impossible
            if self.pair_cost > self.abandon_threshold_pair_cost:
                print(f"🛑 [ABANDON] Pair cost ${self.pair_cost:.3f} > ${self.abandon_threshold_pair_cost:.2f} - mathematically unprofitable")
                return trades_made
        
        # Calculate conservative mode status for spend adjustments
        unrealized_for_mode = 0
        if self.qty_up > 0 or self.qty_down > 0:
            min_qty = min(self.qty_up, self.qty_down) if self.qty_up > 0 and self.qty_down > 0 else 0
            fees = self.calculate_total_fees()
            unrealized_for_mode = min_qty - total_spent - fees
        in_conservative_mode = unrealized_for_mode < self.conservative_mode_loss_threshold
        
        # === NO POSITION - ENTRY ===
        if self.qty_up == 0 and self.qty_down == 0:
            cheaper_side = 'UP' if up_price <= down_price else 'DOWN'
            cheaper_price = min(up_price, down_price)
            opposing_price = down_price if cheaper_side == 'UP' else up_price
            
            # ENTRY STRATEGY: Enter if cheapest side is below threshold
            potential_pair = cheaper_price + opposing_price
            
            # Only skip if BOTH sides are very expensive
            if potential_pair > 1.05:
                print(f"⛔ [SKIP ENTRY] pair would be ${potential_pair:.3f} > $1.05 - both sides too expensive")
                return trades_made
            
            # Enter if cheapest side is reasonably priced (< $0.48)
            if cheaper_price <= self.cheap_threshold:
                max_spend = self.capped_spend(min(self.initial_trade_usd, self.max_single_trade))
                # Be even more conservative if we're tracking losses in other markets
                if in_conservative_mode:
                    max_spend = min(max_spend, self.initial_trade_usd * 0.5)
                if max_spend >= self.min_trade_size:
                    qty = max_spend / cheaper_price
                    if qty >= 1.0:
                        ok, reason = self.reserve_ok(cheaper_side, cheaper_price, qty, opposing_price)
                        if not ok:
                            print(f"⚠️ [ENTRY BLOCKED] {reason}")
                            return trades_made
                        self.first_trade_time = now
                        self.current_mode = 'entry'
                        self.mode_reason = f'Starting with {cheaper_side} @ ${cheaper_price:.3f}'
                        if self.execute_buy(cheaper_side, cheaper_price, qty, timestamp):
                            trades_made.append((cheaper_side, cheaper_price, qty))
                            print(f"🎯 [ENTRY] Bought {qty:.1f} {cheaper_side} @ ${cheaper_price:.3f}")
            return trades_made
        
        # === ONLY ONE SIDE - HEDGE OR IMPROVE! ===
        if self.qty_up > 0 and self.qty_down == 0:
            potential_pair = self.avg_up + down_price
            
            # ABANDON only if potential pair makes profit impossible
            if potential_pair > self.abandon_threshold_pair_cost:
                print(f"🛑 [ABANDON ONE-SIDED UP] Potential pair ${potential_pair:.3f} > ${self.abandon_threshold_pair_cost:.2f} - mathematically unprofitable")
                return trades_made
            
            # CRITICAL: Dynamic pair threshold based on urgency AND imbalance
            # Normal: require profit (pair < 0.99)
            # Fallback: accept break-even (pair <= 1.00) when time is short or price is extreme
            # EMERGENCY: accept up to pair 1.05 when ratio > 3x to prevent catastrophic imbalance
            current_ratio = self.qty_down / self.qty_up if self.qty_up > 0 else 999
            emergency_imbalance = current_ratio > self.emergency_hedge_ratio
            
            urgent_time = time_to_close is not None and time_to_close < self.breakeven_time_threshold
            urgent_price = down_price > self.breakeven_price_threshold
            
            if emergency_imbalance:
                MAX_ACCEPTABLE_PAIR = 1.05
                print(f"🚨 [EMERGENCY HEDGE] Ratio {current_ratio:.1f}x - accepting pair up to $1.05!")
            elif urgent_time or urgent_price:
                MAX_ACCEPTABLE_PAIR = self.max_acceptable_pair_breakeven
                urgency_reason = f"time={time_to_close:.0f}s" if urgent_time else f"price=${down_price:.2f}"
                print(f"⏰ [URGENT MODE] Accepting break-even hedge ({urgency_reason})")
            else:
                MAX_ACCEPTABLE_PAIR = self.max_acceptable_pair_profit
            
            # === CONTINUOUS POSITION IMPROVEMENT CHECK ===
            # Always check if we can lower avg_UP - this widens the hedge window
            should_improve, improve_qty, improve_reason = self.should_improve_position('UP', up_price, opposing_price=down_price)
            
            # DEBUG
            print(f"  → should_improve={should_improve}, improve_qty={improve_qty:.1f}, reason={improve_reason}")
            print(f"  → remaining_budget=${remaining_budget:.2f}, min_trade=${self.min_trade_size}")
            
            # If price dropped enough below avg, ALWAYS buy to lower avg (even if hedge is possible)
            force_improve = should_improve and self.avg_up > 0 and up_price <= self.avg_up * (1 - self.force_improve_pct)

            # === CONTINUOUS IMPROVEMENT - CHECK EVERY TICK ===
            # But respect balance enforcement after grace period (no force improve when one-sided)
            time_since_first = time.time() - self.first_trade_time if self.first_trade_time > 0 else 0
            strict_balance_mode = time_since_first > self.balance_enforcement_delay
            
            if force_improve:
                # After 30s, block FORCE IMPROVE on one-sided positions (must hedge first)
                if strict_balance_mode:
                    print(f"⏱️ [FORCE IMPROVE UP BLOCKED] After {self.balance_enforcement_delay}s - must hedge DOWN first (balance priority)")
                else:
                    ok, reason = self.reserve_ok('UP', up_price, improve_qty, down_price)
                    if not ok:
                        print(f"⚠️ [FORCE IMPROVE UP BLOCKED] {reason}")
                    else:
                        self.current_mode = 'improve'
                        self.mode_reason = f'Lowering UP avg from ${self.avg_up:.3f} @ ${up_price:.3f}'
                        if self.execute_buy('UP', up_price, improve_qty, timestamp):
                            trades_made.append(('UP', up_price, improve_qty))
                            self.record_improvement_spend('UP', up_price * improve_qty)
                            new_max_hedge = 1.0 - self.avg_up
                            print(f"🔥 [FORCE IMPROVE UP] Bought {improve_qty:.1f} UP @ ${up_price:.3f} | "
                                  f"avg_UP now ${self.avg_up:.3f} | hedge window <${new_max_hedge:.3f}")
                            return trades_made

            # If pair would exceed $1, try to improve first
            if potential_pair > 1.00:
                if should_improve:
                    ok, reason = self.reserve_ok('UP', up_price, improve_qty, down_price)
                    if ok:
                        if self.execute_buy('UP', up_price, improve_qty, timestamp):
                            trades_made.append(('UP', up_price, improve_qty))
                            self.record_improvement_spend('UP', up_price * improve_qty)
                            new_max_hedge = 1.0 - self.avg_up
                            print(f"📈 [IMPROVE UP] Bought {improve_qty:.1f} UP @ ${up_price:.3f} | "
                                  f"avg_UP now ${self.avg_up:.3f} | hedge window <${new_max_hedge:.3f}")
                            return trades_made
                    else:
                        print(f"⚠️ [IMPROVE UP BLOCKED] {reason}")
                
                # REFUSE HEDGE if pair > $1.00 - this guarantees loss!
                print(f"⛔ [REFUSE HEDGE] pair ${potential_pair:.3f} > $1.00 would guarantee loss - waiting for better DOWN price")
                return trades_made
            
            # === HEDGE! BUY DOWN! ===
            if potential_pair < 0.99:
                hedge_type = "PROFIT"
            elif potential_pair <= 1.00:
                hedge_type = "BREAK-EVEN"
            else:
                hedge_type = "HIGH (will improve)"
            print(f"✅ [HEDGE - {hedge_type}] pair ${potential_pair:.3f} - BUYING DOWN!")
            
            target_qty = self.qty_up
            desired_spend = target_qty * down_price
            # CRITICAL FIX: Increase hedge budget to ensure proper balancing!
            # Was fraction=0.6, now 0.85 to allow buying enough of expensive side
            max_spend = self.capped_spend(desired_spend, fraction=0.85)
            # CRITICAL FIX: Increase hedge cap from $20 to $40 for better balance
            max_spend = min(max_spend, 40.0)  # Cap hedge at $40 (was $20)
            qty = max_spend / down_price if down_price > 0 else 0.0
            
            # 🛡️ DELTA PROTECTION: Limit hedge qty to avoid excessive imbalance
            # If budget-limited qty creates >15% delta, warn but proceed (budget constrained)
            if qty > 0:
                new_delta_pct = abs(self.qty_up - qty) / (self.qty_up + qty) * 100
                if new_delta_pct > 15.0:
                    print(f"   ⚠️ HEDGE CREATES {new_delta_pct:.1f}% delta (budget limited to ${max_spend:.2f})")
            
            if qty >= 0.5 and max_spend >= self.min_trade_size:
                ok, reason = self.reserve_ok('DOWN', down_price, qty, up_price)
                if not ok:
                    print(f"⚠️ [HEDGE BLOCKED] {reason}")
                    return trades_made
                self.current_mode = 'hedge'
                self.mode_reason = f'Hedging UP with DOWN @ ${down_price:.3f} (pair: ${potential_pair:.3f})'
                if self.execute_buy('DOWN', down_price, qty, timestamp):
                    trades_made.append(('DOWN', down_price, qty))
                    print(f"🔒 [HEDGE] Bought {qty:.1f} DOWN @ ${down_price:.3f} | spend ${max_spend:.2f} | pair: ${self.pair_cost:.3f}")
            return trades_made
        
        if self.qty_down > 0 and self.qty_up == 0:
            potential_pair = up_price + self.avg_down
            
            # ABANDON only if potential pair makes profit impossible
            if potential_pair > self.abandon_threshold_pair_cost:
                print(f"🛑 [ABANDON ONE-SIDED DOWN] Potential pair ${potential_pair:.3f} > ${self.abandon_threshold_pair_cost:.2f} - mathematically unprofitable")
                return trades_made
            
            # CRITICAL: Dynamic pair threshold based on urgency AND imbalance
            # Normal: require profit (pair < 0.99)
            # Fallback: accept break-even (pair <= 1.00) when time is short or price is extreme
            # EMERGENCY: accept up to pair 1.05 when ratio > 3x to prevent catastrophic imbalance
            current_ratio = self.qty_up / self.qty_down if self.qty_down > 0 else 999
            emergency_imbalance = current_ratio > self.emergency_hedge_ratio
            
            urgent_time = time_to_close is not None and time_to_close < self.breakeven_time_threshold
            urgent_price = up_price > self.breakeven_price_threshold
            
            if emergency_imbalance:
                MAX_ACCEPTABLE_PAIR = 1.05
                print(f"🚨 [EMERGENCY HEDGE] Ratio {current_ratio:.1f}x - accepting pair up to $1.05!")
            elif urgent_time or urgent_price:
                MAX_ACCEPTABLE_PAIR = self.max_acceptable_pair_breakeven
                urgency_reason = f"time={time_to_close:.0f}s" if urgent_time else f"price=${up_price:.2f}"
                print(f"⏰ [URGENT MODE] Accepting break-even hedge ({urgency_reason})")
            else:
                MAX_ACCEPTABLE_PAIR = self.max_acceptable_pair_profit
            
            # Calculate the max UP price we can afford for profit
            max_up_for_profit = MAX_ACCEPTABLE_PAIR - self.avg_down
            
            # DEBUG: Always show state for one-sided positions
            print(f"🔵 [ONE-SIDED DOWN] qty={self.qty_down:.1f} avg=${self.avg_down:.3f} | "
                  f"UP=${up_price:.3f} | pair=${potential_pair:.3f} | max_UP=${max_up_for_profit:.3f} | budget=${remaining_budget:.2f}")
            
            # === POSITION IMPROVEMENT - CHECK FIRST! ===
            should_improve, improve_qty, improve_reason = self.should_improve_position('DOWN', down_price, opposing_price=up_price)
            
            force_improve = should_improve and self.avg_down > 0 and down_price <= self.avg_down * (1 - self.force_improve_pct)

            # === ALWAYS IMPROVE ON DEEP DISCOUNT - BEFORE CHECKING HEDGE ===
            # But respect balance enforcement after grace period (no force improve when one-sided)
            time_since_first = time.time() - self.first_trade_time if self.first_trade_time > 0 else 0
            strict_balance_mode = time_since_first > self.balance_enforcement_delay
            
            if force_improve:
                # After 30s, block FORCE IMPROVE on one-sided positions (must hedge first)
                if strict_balance_mode:
                    print(f"⏱️ [FORCE IMPROVE DOWN BLOCKED] After {self.balance_enforcement_delay}s - must hedge UP first (balance priority)")
                else:
                    ok, reason = self.reserve_ok('DOWN', down_price, improve_qty, up_price)
                    if not ok:
                        print(f"⚠️ [FORCE IMPROVE DOWN BLOCKED] {reason}")
                    else:
                        if self.execute_buy('DOWN', down_price, improve_qty, timestamp):
                            trades_made.append(('DOWN', down_price, improve_qty))
                            self.record_improvement_spend('DOWN', down_price * improve_qty)
                            new_max_up = MAX_ACCEPTABLE_PAIR - self.avg_down
                            print(f"🔥 [FORCE IMPROVE DOWN] Bought {improve_qty:.1f} DOWN @ ${down_price:.3f} | "
                                  f"avg_DOWN ${self.avg_down:.3f} | can now pay UP <${new_max_up:.3f}")
                            return trades_made

            if potential_pair > 1.00:
                # Try to improve first
                if should_improve:
                    ok, reason = self.reserve_ok('DOWN', down_price, improve_qty, up_price)
                    if ok:
                        if self.execute_buy('DOWN', down_price, improve_qty, timestamp):
                            trades_made.append(('DOWN', down_price, improve_qty))
                            self.record_improvement_spend('DOWN', down_price * improve_qty)
                            new_max_up = 1.0 - self.avg_down
                            print(f"📈 [IMPROVE DOWN] Bought {improve_qty:.1f} DOWN @ ${down_price:.3f} | "
                                  f"avg_DOWN ${self.avg_down:.3f} | can now pay UP <${new_max_up:.3f}")
                            return trades_made
                    else:
                        print(f"⚠️ [IMPROVE DOWN BLOCKED] {reason}")
                
                # REFUSE HEDGE if pair > $1.00
                print(f"⛔ [REFUSE HEDGE] pair ${potential_pair:.3f} > $1.00 would guarantee loss - waiting for better UP price")
                return trades_made
            
            # === HEDGE! BUY UP! ===
            if potential_pair < 0.99:
                hedge_type = "PROFIT"
            elif potential_pair <= 1.00:
                hedge_type = "BREAK-EVEN"
            else:
                hedge_type = "HIGH (will improve)"
            print(f"✅ [HEDGE - {hedge_type}] pair ${potential_pair:.3f} - BUYING UP!")
            
            target_qty = self.qty_down
            desired_spend = target_qty * up_price
            # CRITICAL FIX: Increase hedge budget to ensure proper balancing!
            # Was fraction=0.6, now 0.85 to allow buying enough of expensive side
            max_spend = self.capped_spend(desired_spend, fraction=0.85)
            # CRITICAL FIX: Increase hedge cap from $20 to $40 for better balance
            max_spend = min(max_spend, 40.0)  # Cap hedge at $40 (was $20)
            qty = max_spend / up_price if up_price > 0 else 0.0
            
            # 🛡️ DELTA PROTECTION: Limit hedge qty to avoid excessive imbalance
            # If budget-limited qty creates >15% delta, warn but proceed (budget constrained)
            if qty > 0:
                new_delta_pct = abs(self.qty_down - qty) / (self.qty_down + qty) * 100
                if new_delta_pct > 15.0:
                    print(f"   ⚠️ HEDGE CREATES {new_delta_pct:.1f}% delta (budget limited to ${max_spend:.2f})")
            
            print(f"   target_qty={target_qty:.1f} | afford=${max_spend:.2f} | qty={qty:.1f}")
            
            if qty >= 0.5 and max_spend >= self.min_trade_size:
                ok, reason = self.reserve_ok('UP', up_price, qty, down_price)
                if not ok:
                    print(f"⚠️ [HEDGE BLOCKED] {reason}")
                    return trades_made
                self.current_mode = 'hedge'
                self.mode_reason = f'Hedging DOWN with UP @ ${up_price:.3f} (pair: ${potential_pair:.3f})'
                if self.execute_buy('UP', up_price, qty, timestamp):
                    trades_made.append(('UP', up_price, qty))
                    print(f"🔒 [HEDGE] Bought {qty:.1f} UP @ ${up_price:.3f} | spend ${max_spend:.2f} | pair: ${self.pair_cost:.3f}")
            else:
                print(f"⚠️ [SKIP HEDGE] qty {qty:.1f} < 0.5 minimum")
            return trades_made
        
        # === HAVE BOTH SIDES - OPTIMIZE UNTIL PROFIT LOCKED ===
        min_qty = min(self.qty_up, self.qty_down)
        fees = self.calculate_total_fees()
        locked = min_qty - total_spent - fees
        pair_cost = self.pair_cost
        
        # Show current position status
        if locked < -50:
            print(f"⚠️ [LARGE LOSS] unrealized=${locked:.2f}, pair=${pair_cost:.3f}, spent=${total_spent:.0f} - seeking improvements")
        
        # ✅ PROFIT SECURED - Continue improving if possible
        profit_is_locked = locked > 0.02
        if profit_is_locked:
            self.current_mode = 'arbitrage'
            self.mode_reason = f'Profit locked ${locked:.2f} - seeking improvements'
            print(f"✅ [PROFIT LOCKED] locked=${locked:.2f} - looking for improvements")
            
            # === PROFIT GROWTH MODE ===
            # Keep trading until window closes IF we can improve profit.
            # 1) Prefer paired compounding (increases locked profit without adding tail risk)
            if self.enable_profit_growth and locked >= self.min_locked_for_growth:
                pair_trades = self._attempt_pair_profit_compound(up_price, down_price, locked, pair_cost, remaining_budget, timestamp)
                if pair_trades:
                    trades_made.extend(pair_trades)
                    return trades_made

            # 2) Optional one-sided growth (only if it keeps locked profit >= 0 and stays under pair-cost guard)
            if self.enable_profit_growth and locked >= self.min_locked_for_growth and pair_cost < self.growth_max_pair_cost:
                growth_trades = self._attempt_profit_growth(up_price, down_price, locked, pair_cost, remaining_budget, timestamp)
                if growth_trades:
                    trades_made.extend(growth_trades)
                    return trades_made
            
            # v12: Even with profit locked, keep looking for favorable opportunities!
            # If price drops significantly below our average, we can grow profit further
            print(f"📈 [GROW SCAN] Searching for growth opportunities (pair=${pair_cost:.3f}, locked=${locked:.2f})")
        
        # ⚠️ PROFIT NOT LOCKED - MUST IMPROVE!
        if remaining_budget < self.min_trade_size:
            print(f"⚠️ [NO BUDGET] locked=${locked:.2f} but only ${remaining_budget:.2f} budget left!")
            return trades_made
        
        # === DYNAMIC WORST-SIDE PRIORITIZATION ===
        # v12: Always run this, even with profit locked - we want to GROW profit!
        worst_side, severity, recommended_spend, priority_reason = self.evaluate_worst_positioned_side(up_price, down_price)
        
        # Only log when not profit-locked (reduce noise)
        if not profit_is_locked:
            print(f"🔍 [PRIORITY CHECK] worst={worst_side}, severity={severity:.1f}, spend=${recommended_spend:.2f}, reason={priority_reason}")
        
        # Reduce spending if in conservative mode
        if in_conservative_mode and recommended_spend > 0:
            recommended_spend = min(recommended_spend, self.max_single_trade * 0.5)
            if not profit_is_locked:
                print(f"   Conservative mode: reduced spend to ${recommended_spend:.2f}")
        
        if worst_side and severity > 2.0 and recommended_spend >= self.min_trade_size:
                worst_price = up_price if worst_side == 'UP' else down_price
                opp_price = down_price if worst_side == 'UP' else up_price
                worst_avg = self.avg_up if worst_side == 'UP' else self.avg_down
                
                print(f"   worst_price=${worst_price:.3f}, worst_avg=${worst_avg:.3f}")
                
                # Only execute if price is actually below average
                if worst_price < worst_avg:
                    qty_to_buy = recommended_spend / worst_price
                    
                    if qty_to_buy >= 1.0:
                        ok, reason = self.reserve_ok(worst_side, worst_price, qty_to_buy, opp_price)
                        if not ok:
                            print(f"⚠️ [PRIORITY BLOCKED] {reason}")
                        else:
                            # Simulate result
                            if worst_side == 'UP':
                                new_qty_up = self.qty_up + qty_to_buy
                                new_cost_up = self.cost_up + recommended_spend
                                new_avg_up = new_cost_up / new_qty_up
                                new_pair = new_avg_up + self.avg_down
                                new_min_qty = min(new_qty_up, self.qty_down)
                            else:
                                new_qty_down = self.qty_down + qty_to_buy
                                new_cost_down = self.cost_down + recommended_spend
                                new_avg_down = new_cost_down / new_qty_down
                                new_pair = self.avg_up + new_avg_down
                                new_min_qty = min(self.qty_up, new_qty_down)
                            
                            new_locked = new_min_qty - (total_spent + recommended_spend) - self.calculate_total_fees()
                            improvement = new_locked - locked
                            
                            # Execute if it helps
                            if new_pair <= pair_cost or improvement > 0:
                                self.current_mode = 'priority_fix'
                                self.mode_reason = priority_reason
                                if self.execute_buy(worst_side, worst_price, qty_to_buy, timestamp):
                                    trades_made.append((worst_side, worst_price, qty_to_buy))
                                    print(f"🎯 [PRIORITY FIX] {priority_reason}")
                                    print(f"   Bought {qty_to_buy:.1f} {worst_side} @ ${worst_price:.3f} | ${recommended_spend:.2f}")
                                    print(f"   pair ${pair_cost:.3f}→${new_pair:.3f} | locked ${locked:.2f}→${new_locked:.2f}")
                                    return trades_made
        
        # === CRITICAL FIX: Check for "CATCH UP + COST AVERAGE" opportunity ===
        # When one side is behind AND price is below average, this is a DOUBLE WIN:
        # 1. Increases min_qty (the smaller side grows)
        # 2. Lowers pair_cost (buying below average lowers the average)
        
        # Find the lagging side
        if self.qty_up < self.qty_down:
            lagging_side = 'UP'
            lagging_qty = self.qty_up
            lagging_avg = self.avg_up
            lagging_price = up_price
            leading_qty = self.qty_down
        else:
            lagging_side = 'DOWN'
            lagging_qty = self.qty_down
            lagging_avg = self.avg_down
            lagging_price = down_price
            leading_qty = self.qty_up
        
        imbalance_ratio = leading_qty / lagging_qty if lagging_qty > 0 else 999
        price_below_avg = lagging_price < lagging_avg
        price_discount = lagging_avg - lagging_price
        
        # DEBUG: Show current state
        if locked < 0:
            print(f"🔴 [LOSING] pair=${pair_cost:.3f} | {lagging_side}: {lagging_qty:.1f} @ ${lagging_avg:.3f} (price ${lagging_price:.3f}) | "
                  f"imbalance={imbalance_ratio:.1f}x | locked=${locked:.2f} | budget=${remaining_budget:.2f}")
        
        # === AGGRESSIVE CATCH-UP when imbalanced ===
        # CRITICAL: If locked < 0, we MUST buy the lagging side to increase min_qty
        # Even if price is above average, it's better than guaranteed loss!
        needs_urgent_balance = locked < -10 and imbalance_ratio > 1.3
        
        if (price_below_avg and imbalance_ratio > 1.3) or needs_urgent_balance:
            # Calculate how much we need to catch up
            qty_gap = leading_qty - lagging_qty
            
            # Calculate optimal buy: enough to significantly improve both metrics
            # Start with catching up to at least 80% of leading side
            target_catch_up = leading_qty * 0.8 - lagging_qty
            if target_catch_up > 0:
                cost_to_catch_up = target_catch_up * lagging_price
                # INCREASED: Was 0.15, now 0.25 - allow larger catch-up trades!
                max_spend = self.capped_spend(cost_to_catch_up, fraction=0.25)
                # INCREASED: Cap at $50 for catch-ups (was $30) - allows better hedging!
                max_spend = min(max_spend, 50.0)
                qty_to_buy = max_spend / lagging_price if lagging_price > 0 else 0.0
                
                if qty_to_buy >= 1.0 and max_spend >= self.min_trade_size:
                    opp_price = down_price if lagging_side == 'UP' else up_price
                    ok, reason = self.reserve_ok(lagging_side, lagging_price, qty_to_buy, opp_price)
                    if not ok:
                        print(f"⚠️ [CATCH-UP BLOCKED] {reason}")
                        return trades_made
                    # Simulate the result
                    if lagging_side == 'UP':
                        new_qty_up = self.qty_up + qty_to_buy
                        new_cost_up = self.cost_up + (qty_to_buy * lagging_price)
                        new_avg_up = new_cost_up / new_qty_up
                        new_pair_cost = new_avg_up + self.avg_down
                        new_min_qty = min(new_qty_up, self.qty_down)
                        new_total_spent = new_cost_up + self.cost_down
                    else:
                        new_qty_down = self.qty_down + qty_to_buy
                        new_cost_down = self.cost_down + (qty_to_buy * lagging_price)
                        new_avg_down = new_cost_down / new_qty_down
                        new_pair_cost = self.avg_up + new_avg_down
                        new_min_qty = min(self.qty_up, new_qty_down)
                        new_total_spent = self.cost_up + new_cost_down
                    
                    new_locked = new_min_qty - new_total_spent
                    improvement = new_locked - locked
                    
                    # Only execute if it actually improves locked profit
                    if improvement > 0.5 and new_pair_cost < pair_cost:
                        if new_pair_cost > 1.0:
                            remaining_after = remaining_budget - (qty_to_buy * lagging_price)
                            if remaining_after < self.min_trade_size or not self.can_recover_pair_cost(
                                up_price,
                                down_price,
                                remaining_after,
                                new_qty_up,
                                new_cost_up,
                                new_qty_down,
                                new_cost_down
                            ):
                                return trades_made
                        # Allow if it improves locked profit or pair cost
                        if profit_is_locked and improvement < 0.01 and new_pair_cost >= pair_cost:
                            return trades_made
                        self.current_mode = 'rebalance'
                        self.mode_reason = f'Catching up {lagging_side}: ratio {imbalance_ratio:.1f}x → balanced'
                        if self.execute_buy(lagging_side, lagging_price, qty_to_buy, timestamp):
                            trades_made.append((lagging_side, lagging_price, qty_to_buy))
                            print(f"🚀 [CATCH-UP] Bought {qty_to_buy:.1f} {lagging_side} @ ${lagging_price:.3f} (below avg ${lagging_avg:.3f}) | "
                                  f"pair ${pair_cost:.3f}→${new_pair_cost:.3f} | locked ${locked:.2f}→${new_locked:.2f} (+${improvement:.2f})")
                            return trades_made
        
        # === Standard optimization: try different trade sizes ===
        best_side = None
        best_qty = 0
        best_improvement = 0
        best_new_pair = pair_cost
        best_new_locked = locked
        
        # Try larger trade sizes - limited by bankroll availability
        trade_sizes = [1.0, 5.0, 10.0, 25.0, 50.0, 100.0, 200.0]  # USD amounts
        affordable_for_tests = self.affordable_cash(0.5)
        
        for try_side, try_price in [('UP', up_price), ('DOWN', down_price)]:
            my_qty = self.qty_up if try_side == 'UP' else self.qty_down
            my_avg = self.avg_up if try_side == 'UP' else self.avg_down
            other_qty = self.qty_down if try_side == 'UP' else self.qty_up
            opp_price = down_price if try_side == 'UP' else up_price
            
            # ⚖️ BALANCE CHECK: Don't buy larger side when position delta > 15% (max flex)
            # Allow rebalancing even at high delta if pair_cost is critical
            if other_qty > 0 and my_qty > other_qty:
                current_delta_pct = abs(my_qty - other_qty) / (my_qty + other_qty) * 100
                if current_delta_pct > self.max_flex_delta_pct:
                    # Already over 15% delta - don't make it worse unless emergency
                    if pair_cost < 1.05:  # Only skip if we're not in deep trouble
                        continue
            
            for trade_usd in trade_sizes:
                if trade_usd > affordable_for_tests:
                    continue
                
                # Evaluate only sizes we can fund
                test_qty = trade_usd / try_price
                if test_qty < 0.5:
                    continue
                ok, _ = self.reserve_ok(try_side, try_price, test_qty, opp_price)
                if not ok:
                    continue
                
                # Simulate the trade
                if try_side == 'UP':
                    new_qty_up = self.qty_up + test_qty
                    new_qty_down = self.qty_down
                    new_cost_up = self.cost_up + trade_usd
                    new_cost_down = self.cost_down
                else:
                    new_qty_down = self.qty_down + test_qty
                    new_qty_up = self.qty_up
                    new_cost_down = self.cost_down + trade_usd
                    new_cost_up = self.cost_up
                
                new_avg_up = new_cost_up / new_qty_up
                new_avg_down = new_cost_down / new_qty_down
                new_pair_cost = new_avg_up + new_avg_down
                
                fee_up = self.calculate_fee(new_avg_up, new_qty_up)
                fee_down = self.calculate_fee(new_avg_down, new_qty_down)
                new_fees = fee_up + fee_down
                
                new_total_spent = new_cost_up + new_cost_down
                new_min_qty = min(new_qty_up, new_qty_down)
                new_locked = new_min_qty - new_total_spent - new_fees
                
                improvement = new_locked - locked
                
                # Accept if it improves locked profit
                if improvement > best_improvement:
                    # STRATEGIC POSITIONING when pair_cost > $1.00:
                    # Prioritize buying the side with HIGHER average (lowers it the most)
                    # Even if pair cost temporarily increases, it positions us better for recovery
                    if pair_cost >= 1.00:
                        # Which side has higher average?
                        higher_avg_side = 'UP' if self.avg_up > self.avg_down else 'DOWN'
                        
                        # Only accept trades on the higher-avg side, OR trades that reduce pair_cost
                        if new_pair_cost > pair_cost:
                            # Pair cost got worse - only accept if buying the high-avg side
                            if try_side != higher_avg_side:
                                continue
                            # And only if we're buying significantly below average
                            if try_price >= my_avg * 0.90:  # Must be at least 10% discount
                                continue
                            print(f"   💡 [STRATEGIC] Buying {try_side} (high avg ${my_avg:.3f}) @ ${try_price:.3f} to position for recovery")

                    if new_pair_cost > 1.0:
                        remaining_after = remaining_budget - trade_usd
                        if remaining_after < self.min_trade_size or not self.can_recover_pair_cost(
                            up_price,
                            down_price,
                            remaining_after,
                            new_qty_up,
                            new_cost_up,
                            new_qty_down,
                            new_cost_down
                        ):
                            continue

                    if profit_is_locked:
                        # Allow if it improves pair cost OR locked profit (even slightly)
                        if new_pair_cost >= pair_cost and improvement < 0.01:
                            continue
                    
                    # Prefer buying the lagging side
                    is_lagging_side = (my_qty < other_qty)
                    
                    # Bonus for buying below average (cost averaging)
                    is_below_avg = (try_price < my_avg)
                    
                    # Give priority to trades that are both lagging AND below avg
                    effective_improvement = improvement
                    if is_lagging_side and is_below_avg:
                        effective_improvement *= 1.5  # 50% bonus
                    elif is_lagging_side or is_below_avg:
                        effective_improvement *= 1.2  # 20% bonus
                    
                    if effective_improvement > best_improvement:
                        best_side = try_side
                        best_qty = test_qty
                        best_improvement = improvement  # Store actual improvement
                        best_new_pair = new_pair_cost
                        best_new_locked = new_locked
        
        # Execute the best trade if we found one that helps
        if best_side and best_improvement > 0.05:  # At least 5 cents improvement
            best_price = up_price if best_side == 'UP' else down_price
            opp_price = down_price if best_side == 'UP' else up_price
            ok, reason = self.reserve_ok(best_side, best_price, best_qty, opp_price)
            if not ok:
                print(f"⚠️ [OPTIMIZE BLOCKED] {reason}")
                return trades_made
            self.current_mode = 'optimize'
            self.mode_reason = f'Optimizing {best_side} for +${best_improvement:.2f} locked profit'
            if self.execute_buy(best_side, best_price, best_qty, timestamp):
                trades_made.append((best_side, best_price, best_qty))
                print(
                    f"💰 [OPTIMIZE] Bought {best_qty:.1f} {best_side} @ ${best_price:.3f} | "
                    f"pair ${pair_cost:.3f}→${best_new_pair:.3f} | locked ${locked:.2f}→${best_new_locked:.2f} (+${best_improvement:.2f})"
                )
        
        return trades_made
    
    def resolve_market(self, outcome: str):
        self.market_status = 'resolved'
        self.resolution_outcome = outcome
        
        if outcome == 'UP':
            self.payout = self.qty_up * 1.0
        else:
            self.payout = self.qty_down * 1.0
        
        total_cost = self.cost_up + self.cost_down
        fees = self.calculate_total_fees()
        self.last_fees_paid = fees
        self.final_pnl_gross = self.payout - total_cost
        self.final_pnl = self.final_pnl_gross - fees
        net_payout = max(0.0, self.payout - fees)
        
        # Add net payout back to cash
        self.cash += net_payout
        
        return self.final_pnl
    
    def close_market(self):
        self.market_status = 'closed'
    
    def get_state(self) -> dict:
        # Calculate hedge windows - max price we can pay for the other side
        # Use 0.99 threshold (not 1.0) to account for fees
        max_hedge_up = 0.99 - self.avg_down if self.avg_down > 0 else 0.99
        max_hedge_down = 0.99 - self.avg_up if self.avg_up > 0 else 0.99
        
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
            # Position delta: |A-B| / (A+B) * 100
            'balance_pct': (abs(self.qty_up - self.qty_down) / (self.qty_up + self.qty_down) * 100) if (self.qty_up + self.qty_down) > 0 else 0,
            'is_balanced': ((abs(self.qty_up - self.qty_down) / (self.qty_up + self.qty_down) * 100) <= 5.0) if (self.qty_up + self.qty_down) > 0 else False,
            'trade_count': self.trade_count,
            'market_status': self.market_status,
            'resolution_outcome': self.resolution_outcome,
            'final_pnl': self.final_pnl,
            'final_pnl_gross': self.final_pnl_gross,
            'fees_paid': self.last_fees_paid,
            'payout': self.payout,
            # Hedge window info - max price for profitable hedge (pair < $0.99)
            'max_hedge_up': max_hedge_up,    # Max UP price for profit if we only have DOWN
            'max_hedge_down': max_hedge_down,  # Max DOWN price for profit if we only have UP
            # Trading mode
            'current_mode': self.current_mode,
            'mode_reason': self.mode_reason
        }


class MarketTracker:
    """Tracks a single market"""
    
    def __init__(self, slug: str, asset: str, cash_ref: dict, market_budget: float, exec_sim: ExecutionSimulator = None):
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
        self.market_budget = market_budget
        # NEW: Use ArbitrageStrategy with shared ExecutionSimulator
        self.paper_trader = ArbitrageStrategy(market_budget=market_budget, starting_balance=market_budget, exec_sim=exec_sim)
        self.paper_trader.cash_ref = cash_ref  # Share cash reference
        self.initialized = False
        self.last_update = 0


class MultiMarketBot:
    GAMMA_API_URL = "https://gamma-api.polymarket.com"
    CLOB_API_URL = "https://clob.polymarket.com"
    
    def __init__(self, starting_balance: float = 800.0, per_market_budget: float = 200.0):
        self.initial_starting_balance = starting_balance
        # Allow overrides via env to match Render/VPS config.
        try:
            starting_balance = float(os.getenv('STARTING_BALANCE', starting_balance))
        except Exception:
            pass
        try:
            per_market_budget = float(os.getenv('PER_MARKET_BUDGET', per_market_budget))
        except Exception:
            pass
        self.initial_per_market_budget = per_market_budget
        self.starting_balance = starting_balance
        self.per_market_budget = per_market_budget
        self.cash_ref = {'balance': starting_balance}
        self.active_markets: Dict[str, MarketTracker] = {}
        self.history: List[dict] = []
        self.websockets = set()
        self.running = True
        self.update_count = 0
        self.manual_markets_loaded = False
        self.trade_log: List[dict] = []
        self.paused = False
        # Shared execution simulator — stats persist across all markets
        self.exec_sim = ExecutionSimulator(latency_ms=25.0, max_slippage_pct=2.0)
    
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
                            asset_budget = ASSET_BUDGETS.get(asset, self.per_market_budget)
                            tracker = MarketTracker(slug, asset, self.cash_ref, asset_budget, self.exec_sim)
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
            # Skip if we already have an OPEN market for this asset
            # Resolved markets don't block new ones
            has_open_market = any(
                t.asset == asset and t.paper_trader.market_status == 'open'
                for t in self.active_markets.values()
            )
            if has_open_market:
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
                            asset_budget = ASSET_BUDGETS.get(asset, self.per_market_budget)
                            tracker = MarketTracker(slug, asset, self.cash_ref, asset_budget, self.exec_sim)
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
                            print(f"🔍 Auto-discovered: {slug} (budget ${asset_budget:.0f})")
                            break  # Found one for this asset, move to next asset
                except Exception as e:
                    pass  # Silently skip failed lookups
    
    async def update_market(self, session: aiohttp.ClientSession, tracker: MarketTracker):
        """Update a single market's data"""
        if not tracker.initialized:
            return
        
        # Don't update resolved markets
        if tracker.paper_trader.market_status == 'resolved':
            return
        
        # Check if market window has ended
        now = datetime.now(timezone.utc)
        market_expired = tracker.window_end and now > tracker.window_end
        
        # If market expired, close it immediately and calculate PnL
        if market_expired and tracker.paper_trader.market_status == 'open':
            pt = tracker.paper_trader
            
            # Determine winner based on last prices (UP wins if UP price > DOWN price)
            up_price = tracker.up_price or 0.5
            down_price = tracker.down_price or 0.5
            if up_price > down_price:
                outcome = 'UP'
                payout = pt.qty_up  # $1 per UP share
            else:
                outcome = 'DOWN'
                payout = pt.qty_down  # $1 per DOWN share
            
            pnl = pt.resolve_market(outcome)
            fees_paid = getattr(pt, 'last_fees_paid', 0.0)
            gross_pnl = getattr(pt, 'final_pnl_gross', pnl + fees_paid)
            net_payout = max(0.0, pt.payout - fees_paid)
            
            print(f"🏁 [{tracker.asset.upper()}] Market closed: {outcome} won | Net: ${pnl:+.2f} (fees ${fees_paid:.2f})")
            
            # Add to history
            self.history.append({
                'resolved_at': datetime.now(timezone.utc).strftime('%H:%M:%S'),
                'slug': tracker.slug,
                'asset': tracker.asset,
                'outcome': outcome,
                'qty_up': pt.qty_up,
                'qty_down': pt.qty_down,
                'pair_cost': pt.pair_cost,
                'payout': pt.payout,
                'net_payout': net_payout,
                'fees': fees_paid,
                'gross_pnl': gross_pnl,
                'pnl': pnl,
                'pnl_after_fees': pnl
            })
            return
        
        try:
            # Get orderbook for both tokens IN PARALLEL for temporal consistency
            # Sequential fetching causes UP/DOWN prices to be from different moments,
            # which is dangerous during rapid price swings.
            up_book = {}
            down_book = {}
            fetch_start = time.time()

            async def fetch_book(token_id):
                if not token_id:
                    return {}
                url = f"{self.CLOB_API_URL}/book?token_id={token_id}"
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=0.5)) as response:
                        if response.status == 200:
                            return await response.json()
                except asyncio.TimeoutError:
                    pass  # Silent — will just use previous prices
                return {}

            up_book, down_book = await asyncio.gather(
                fetch_book(tracker.up_token_id),
                fetch_book(tracker.down_token_id)
            )
            fetch_latency_ms = (time.time() - fetch_start) * 1000
            
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
                
                # DEBUG: Print prices and why no trade
                pt = tracker.paper_trader
                if pt.qty_up == 0 and pt.qty_down == 0:
                    spread = abs(tracker.up_price - tracker.down_price) if tracker.up_price and tracker.down_price else 0
                    print(f"🔍 [{tracker.asset}] UP=${tracker.up_price:.3f} DOWN=${tracker.down_price:.3f} | spread=${spread:.3f} | mode={pt.current_mode} | {fetch_latency_ms:.0f}ms")
                
                trades = tracker.paper_trader.check_and_trade(
                    tracker.up_price, 
                    tracker.down_price, 
                    timestamp,
                    time_to_close=time_to_close,
                    up_bid=up_bid,
                    down_bid=down_bid,
                    up_orderbook=up_book,
                    down_orderbook=down_book
                )
                
                if trades:
                    for trade in trades:
                        if len(trade) == 4:
                            action, side, actual_price, actual_qty = trade
                        else:
                            side, actual_price, actual_qty = trade
                            action = 'BUY'
                        pt = tracker.paper_trader
                        urgency_msg = f" [⚠️ {time_to_close:.0f}s left!]" if time_to_close and time_to_close < 300 else ""
                        print(f"📈 [{tracker.asset.upper()}] {action} {actual_qty:.1f} {side} @ ${actual_price:.3f} | Pair: ${pt.pair_cost:.3f} | {fetch_latency_ms:.0f}ms{urgency_msg}")
                        
                        # Add to trade log
                        cost_value = actual_price * actual_qty if action in ('BUY', 'SELL') else 0.0
                        self.trade_log.append({
                            'time': timestamp,
                            'asset': tracker.asset.upper(),
                            'market': tracker.slug,
                            'action': action,
                            'side': side,
                            'price': actual_price,
                            'qty': actual_qty,
                            'cost': cost_value,
                            'pair_cost': pt.pair_cost
                        })
                        
                        # Keep only last 1000 trades
                        if len(self.trade_log) > 1000:
                            self.trade_log = self.trade_log[-1000:]
            
            tracker.last_update = time.time()
            
        except Exception as e:
            print(f"Error updating {tracker.slug}: {e}")
    
    async def check_resolution(self, session: aiohttp.ClientSession, tracker: MarketTracker):
        """Check if a market has been resolved"""
        pt = tracker.paper_trader
        
        # Already resolved, nothing to do
        if pt.market_status == 'resolved':
            return
            
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
                                
                                pnl = pt.resolve_market(resolution)
                                fees_paid = getattr(pt, 'last_fees_paid', 0.0)
                                gross_pnl = getattr(pt, 'final_pnl_gross', pnl + fees_paid)
                                net_payout = max(0.0, pt.payout - fees_paid)
                                print(f"🏁 [{tracker.asset.upper()}] Resolved: {resolution} | Net: ${pnl:.2f} (fees ${fees_paid:.2f})")
                                
                                # Add to history
                                self.history.append({
                                    'resolved_at': datetime.now(timezone.utc).strftime('%H:%M:%S'),
                                    'slug': tracker.slug,
                                    'asset': tracker.asset,
                                    'outcome': resolution,
                                    'qty_up': pt.qty_up,
                                    'qty_down': pt.qty_down,
                                    'pair_cost': pt.pair_cost,
                                    'payout': pt.payout,
                                    'net_payout': net_payout,
                                    'fees': fees_paid,
                                    'gross_pnl': gross_pnl,
                                    'pnl': pnl,
                                    'pnl_after_fees': pnl
                                })
                                return
                        
                        # No winner found yet - check if we've been waiting too long
                        now = datetime.now(timezone.utc)
                        if tracker.window_end:
                            time_since_close = (now - tracker.window_end).total_seconds()
                            # If we've waited more than 5 minutes without resolution, assume market failed
                            if time_since_close > 300 and pt.market_status != 'resolved':
                                # Liquidate at last known prices
                                liquidation_value = (pt.qty_up * tracker.last_up_bid) + (pt.qty_down * tracker.last_down_bid)
                                if liquidation_value == 0 and (pt.qty_up > 0 or pt.qty_down > 0):
                                    liquidation_value = min(pt.qty_up, pt.qty_down)
                                total_cost = pt.cost_up + pt.cost_down
                                fees_paid = pt.calculate_total_fees()
                                net_liquidation = max(0.0, liquidation_value - fees_paid)
                                pnl_after_fees = net_liquidation - total_cost
                                gross_pnl = liquidation_value - total_cost
                                
                                # Add net payout back to cash
                                self.cash_ref['balance'] += net_liquidation
                                
                                pt.market_status = 'resolved'
                                pt.resolution_outcome = 'TIMEOUT'
                                pt.payout = liquidation_value
                                pt.final_pnl = pnl_after_fees
                                pt.final_pnl_gross = gross_pnl
                                pt.last_fees_paid = fees_paid
                                
                                print(f"⚠️ [{tracker.asset.upper()}] Resolution timeout | Net: ${pnl_after_fees:+.2f} (fees ${fees_paid:.2f})")
                                
                                self.history.append({
                                    'resolved_at': datetime.now(timezone.utc).strftime('%H:%M:%S'),
                                    'slug': tracker.slug,
                                    'asset': tracker.asset,
                                    'outcome': 'TIMEOUT',
                                    'qty_up': pt.qty_up,
                                    'qty_down': pt.qty_down,
                                    'pair_cost': pt.pair_cost,
                                    'payout': liquidation_value,
                                    'net_payout': net_liquidation,
                                    'fees': fees_paid,
                                    'gross_pnl': gross_pnl,
                                    'pnl': pnl_after_fees,
                                    'pnl_after_fees': pnl_after_fees
                                })
                                
        except Exception as e:
            print(f"Error checking resolution for {tracker.slug}: {e}")
    
    async def cleanup_old_markets(self):
        """Remove old resolved markets from active tracking"""
        to_remove = []
        for slug, tracker in self.active_markets.items():
            if tracker.paper_trader.market_status == 'resolved':
                # Keep resolved markets for 2 minutes so UI can show them
                if time.time() - tracker.last_update > 120:
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
                        
                        # Check resolution for expired markets (window_end has passed)
                        if tracker.window_end and datetime.now(timezone.utc) > tracker.window_end:
                            if tracker.paper_trader.market_status != 'resolved':
                                await self.check_resolution(session, tracker)
                    
                    # Cleanup old markets
                    await self.cleanup_old_markets()
                    
                    # Prepare broadcast data - only send NEWEST market per asset
                    active_data = {}
                    total_locked_profit = 0
                    total_position_value = 0
                    
                    # First, find the newest market per asset
                    newest_per_asset = {}
                    for slug, tracker in self.active_markets.items():
                        asset = tracker.asset
                        # Extract timestamp from slug
                        import re
                        match = re.search(r'-(\d+)$', slug)
                        timestamp = int(match.group(1)) if match else 0
                        
                        if asset not in newest_per_asset or timestamp > newest_per_asset[asset][1]:
                            newest_per_asset[asset] = (slug, timestamp)
                    
                    # Now only include newest markets in broadcast
                    newest_slugs = {slug for slug, _ in newest_per_asset.values()}
                    
                    for slug, tracker in self.active_markets.items():
                        pt = tracker.paper_trader
                        is_active = pt.market_status != 'resolved'
                        if is_active:
                            # Calculate position value (what we'd get if market resolved now) minus fees
                            min_qty = min(pt.qty_up, pt.qty_down)
                            fees_estimate = pt.calculate_total_fees()
                            position_value = max(0.0, min_qty - fees_estimate)
                            total_position_value += position_value
                            total_locked_profit += pt.locked_profit
                        
                        # Only include newest market per asset in UI data
                        if slug in newest_slugs:
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
                        total_pnl = sum(h.get('pnl_after_fees', h['pnl']) for h in asset_history)
                        asset_wdl[asset] = {
                            'wins': wins,
                            'draws': draws,
                            'losses': losses,
                            'total': total,
                            'total_pnl': total_pnl
                        }
                    
                    # Use shared execution simulator stats (persists across all markets)
                    es = self.exec_sim.get_stats()
                    total_slippage_cost = es.get('total_slippage_cost', 0)

                    data = {
                        'starting_balance': self.starting_balance,
                        'current_balance': self.cash_ref['balance'],
                        'true_balance': true_balance,
                        'total_locked_profit': total_locked_profit,
                        'active_markets': active_data,
                        'history': self.history,
                        # Show full trade log across all markets
                        'trade_log': self.trade_log,
                        'paused': self.paused,
                        'asset_wdl': asset_wdl,
                        'supported_assets': SUPPORTED_ASSETS,
                        # Execution simulator stats (shared, never resets between markets)
                        'exec_stats': es
                    }
                    
                    await self.broadcast(data)
                    
                    self.update_count += 1
                    if self.update_count % 10 == 0:
                        total_pnl = true_balance - self.starting_balance
                        slip_str = f" | Slippage: -${total_slippage_cost:.4f}" if total_slippage_cost > 0 else ""
                        adj_pnl = total_pnl - total_slippage_cost
                        print(f"📊 Cash: ${self.cash_ref['balance']:.2f} | True Balance: ${true_balance:.2f} | Paper PnL: ${total_pnl:+.2f} | Real PnL (adj): ${adj_pnl:+.2f}{slip_str} | Active: {len(self.active_markets)}")
                    
                except Exception as e:
                    import traceback
                    print(f"Error in data loop: {e}")
                    traceback.print_exc()
                
                await asyncio.sleep(0.2)  # 200ms polling — near-realtime price tracking
    
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
                            self.starting_balance = self.initial_starting_balance
                            self.per_market_budget = self.initial_per_market_budget
                            self.cash_ref['balance'] = self.initial_starting_balance
                            self.history = []
                            self.trade_log = []
                            self.active_markets = {}
                            print(f"🔄 Bot RESET - Balance: ${self.starting_balance:.2f}")
                            await self.broadcast({
                                'starting_balance': self.starting_balance,
                                'current_balance': self.cash_ref['balance'],
                                'true_balance': self.starting_balance,
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
    bot = MultiMarketBot()
    try:
        asyncio.run(bot.start())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped")
        print("\n👋 Bot stopped")
    bot = MultiMarketBot()
    try:
        asyncio.run(bot.start())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped")
