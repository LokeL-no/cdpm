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
from typing import Optional
from aiohttp import web
import os

# Event slug - endre denne for å spore et annet market
EVENT_SLUG = "btc-updown-15m-1769756400"

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
        
        <div class="footer">
            Press F5 to refresh | Data from Polymarket CLOB API
        </div>
    </div>
    
    <script>
        const ws = new WebSocket(`ws://${window.location.host}/ws`);
        
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
        
        // Update time every second
        setInterval(() => {
            const now = new Date();
            document.getElementById('current-time').textContent = now.toISOString().substr(11, 8);
        }, 1000);
    </script>
</body>
</html>
"""


class PolymarketWebBot:
    GAMMA_API_URL = "https://gamma-api.polymarket.com"
    CLOB_API_URL = "https://clob.polymarket.com"
    
    def __init__(self, event_slug: str):
        self.event_slug = event_slug
        self.market_title = "Bitcoin Up or Down"
        self.up_token_id = None
        self.down_token_id = None
        self.update_count = 0
        self.window_start = None
        self.window_end = None
        self.websockets = set()
        self.running = True
        
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
                        
                        # Parse timestamps from slug
                        parts = self.event_slug.split('-')
                        if len(parts) >= 4:
                            try:
                                end_timestamp = int(parts[-1])
                                start_timestamp = end_timestamp - (15 * 60)
                                self.window_start = datetime.fromtimestamp(start_timestamp, tz=timezone.utc)
                                self.window_end = datetime.fromtimestamp(end_timestamp, tz=timezone.utc)
                            except:
                                pass
                        
                        # Get markets from event
                        markets = event.get('markets', [])
                        if markets:
                            for market in markets:
                                clob_token_ids = market.get('clobTokenIds', '')
                                outcomes = market.get('outcomes', '')
                                
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
        """Main data fetching loop"""
        async with aiohttp.ClientSession() as session:
            # Fetch initial event data
            print(f"Fetching event data for: {self.event_slug}")
            await self.fetch_event_data(session)
            
            if not self.up_token_id or not self.down_token_id:
                print("Could not find token IDs, running in demo mode")
            else:
                print(f"Found tokens - UP: {self.up_token_id[:20]}... DOWN: {self.down_token_id[:20]}...")
            
            while self.running:
                try:
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
                    
                    # Prepare data for broadcast
                    window_time = f"{self.window_start.strftime('%H:%M') if self.window_start else '--:--'} - {self.window_end.strftime('%H:%M') if self.window_end else '--:--'}"
                    
                    data = {
                        'title': self.market_title,
                        'event_slug': self.event_slug,
                        'window_time': window_time,
                        'current_time': datetime.now(timezone.utc).strftime('%H:%M:%S'),
                        'update_count': self.update_count,
                        'up_mid': up_mid,
                        'down_mid': down_mid,
                        'up_book': up_book,
                        'down_book': down_book,
                        'up_trades': up_trades,
                        'down_trades': down_trades
                    }
                    
                    await self.broadcast(data)
                    
                except Exception as e:
                    print(f"Error in data loop: {e}")
                
                await asyncio.sleep(1)


# Create bot instance
bot = PolymarketWebBot(EVENT_SLUG)


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
            if msg.type == aiohttp.WSMsgType.ERROR:
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
    print(f"📊 Event: {EVENT_SLUG}")
    print(f"🌐 Open http://localhost:8080 in your browser")
    print(f"Press Ctrl+C to stop")
    print()
    
    web.run_app(app, host='localhost', port=8080, print=None)


if __name__ == '__main__':
    main()
