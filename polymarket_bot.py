#!/usr/bin/env python3
"""
Polymarket Bot - Bitcoin Up or Down Price Tracker
Tracks live prices, orderbooks and recent activity for Bitcoin prediction markets.
"""

import asyncio
import aiohttp
import json
import time
from datetime import datetime, timezone
from typing import Optional
import os

# ANSI color codes for terminal
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    
    # Regular colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    
    # Bright colors
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"
    
    # Background colors
    BG_GREEN = "\033[42m"
    BG_RED = "\033[41m"
    BG_BLUE = "\033[44m"
    BG_YELLOW = "\033[43m"


class PolymarketBot:
    GAMMA_API_URL = "https://gamma-api.polymarket.com"
    CLOB_API_URL = "https://clob.polymarket.com"
    
    def __init__(self, event_slug: str):
        self.event_slug = event_slug
        self.market_data = None
        self.up_token_id = None
        self.down_token_id = None
        self.up_orderbook = None
        self.down_orderbook = None
        self.recent_trades = []
        self.update_count = 0
        self.is_connected = False
        self.market_title = "Bitcoin Up or Down"
        self.window_start = None
        self.window_end = None
        
    def clear_screen(self):
        """Clear terminal screen"""
        os.system('cls' if os.name == 'nt' else 'clear')
        
    def format_price(self, price: float) -> str:
        """Format price as cents"""
        cents = price * 100
        return f"{cents:.1f}¢"
    
    def format_size(self, size: float) -> str:
        """Format size with abbreviation"""
        if size >= 1000000:
            return f"{size/1000000:.1f}M"
        elif size >= 1000:
            return f"{size/1000:.0f}k" if size >= 10000 else f"{size:.0f}"
        return f"{size:.1f}"
    
    async def fetch_market_data(self, session: aiohttp.ClientSession):
        """Fetch market data from Gamma API"""
        try:
            # Søk etter markeder med denne event slug
            url = f"{self.GAMMA_API_URL}/markets?slug={self.event_slug}"
            async with session.get(url) as response:
                if response.status == 200:
                    markets = await response.json()
                    if markets and len(markets) > 0:
                        self.market_data = markets[0]
                        return True
            
            # Alternativ: søk etter event
            url = f"{self.GAMMA_API_URL}/events?slug={self.event_slug}"
            async with session.get(url) as response:
                if response.status == 200:
                    events = await response.json()
                    if events and len(events) > 0:
                        event = events[0]
                        self.market_title = event.get('title', self.market_title)
                        # Hent markets fra event
                        if 'markets' in event:
                            markets = event['markets']
                            if isinstance(markets, str):
                                markets = json.loads(markets)
                            self.market_data = markets
                            return True
            return False
        except Exception as e:
            print(f"Error fetching market data: {e}")
            return False
    
    async def fetch_markets_by_event(self, session: aiohttp.ClientSession):
        """Fetch all markets for a specific event slug"""
        try:
            # Hent events med denne slug
            url = f"{self.GAMMA_API_URL}/events?slug={self.event_slug}"
            async with session.get(url) as response:
                if response.status == 200:
                    events = await response.json()
                    if events and len(events) > 0:
                        event = events[0]
                        self.market_title = event.get('title', 'Bitcoin Up or Down')
                        
                        # Parse start og end times fra title
                        title = event.get('title', '')
                        
                        # Hent timestamps fra slug (btc-updown-15m-1769755500)
                        parts = self.event_slug.split('-')
                        if len(parts) >= 4:
                            try:
                                end_timestamp = int(parts[-1])
                                # 15m window
                                start_timestamp = end_timestamp - (15 * 60)
                                self.window_start = datetime.fromtimestamp(start_timestamp, tz=timezone.utc)
                                self.window_end = datetime.fromtimestamp(end_timestamp, tz=timezone.utc)
                            except:
                                pass
                        
                        return event
            return None
        except Exception as e:
            print(f"Error fetching event: {e}")
            return None
    
    async def fetch_token_ids(self, session: aiohttp.ClientSession):
        """Fetch token IDs for UP and DOWN outcomes"""
        try:
            # Søk etter markeder basert på event slug
            url = f"{self.GAMMA_API_URL}/markets?limit=100"
            async with session.get(url) as response:
                if response.status == 200:
                    markets = await response.json()
                    
                    for market in markets:
                        slug = market.get('slug', '')
                        events = market.get('events', [])
                        
                        # Sjekk om dette markedet tilhører vår event
                        for event in events:
                            if event.get('slug') == self.event_slug:
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
                                break
                        
                        if self.up_token_id and self.down_token_id:
                            break
            
            # Hvis vi ikke fant tokens, prøv å søke direkte
            if not self.up_token_id or not self.down_token_id:
                # Søk etter event direkte
                event = await self.fetch_markets_by_event(session)
                if event:
                    # Prøv å hente markets fra CLOB API
                    clob_url = f"{self.CLOB_API_URL}/markets"
                    async with session.get(clob_url) as response:
                        if response.status == 200:
                            data = await response.json()
                            # Filtrer basert på condition_id eller question
                            pass
            
            return self.up_token_id is not None and self.down_token_id is not None
        except Exception as e:
            print(f"Error fetching token IDs: {e}")
            return False
    
    async def fetch_orderbook(self, session: aiohttp.ClientSession, token_id: str) -> Optional[dict]:
        """Fetch orderbook for a specific token"""
        try:
            url = f"{self.CLOB_API_URL}/book?token_id={token_id}"
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
            return None
        except Exception as e:
            return None
    
    async def fetch_recent_trades(self, session: aiohttp.ClientSession, token_id: str) -> list:
        """Fetch recent trades for a token"""
        try:
            url = f"{self.CLOB_API_URL}/trades?token_id={token_id}&limit=10"
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
            return []
        except:
            return []
    
    async def fetch_price(self, session: aiohttp.ClientSession, token_id: str) -> Optional[dict]:
        """Fetch current price for a token"""
        try:
            url = f"{self.CLOB_API_URL}/price?token_id={token_id}&side=buy"
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
            return None
        except:
            return None
    
    async def fetch_midpoint(self, session: aiohttp.ClientSession, token_id: str) -> Optional[float]:
        """Fetch midpoint price for a token"""
        try:
            url = f"{self.CLOB_API_URL}/midpoint?token_id={token_id}"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return float(data.get('mid', 0))
            return None
        except:
            return None
    
    def render_header(self):
        """Render the header section"""
        print(f"  {Colors.BRIGHT_YELLOW}🤖 POLYMARKET BOT - {self.market_title}{Colors.RESET}")
        print(f"  {Colors.CYAN}Market: {self.event_slug}{Colors.RESET}")
        
        # Window time
        if self.window_start and self.window_end:
            start_str = self.window_start.strftime("%H:%M")
            end_str = self.window_end.strftime("%H:%M")
            print(f"  {Colors.WHITE}Window: {start_str} - {end_str} UTC{Colors.RESET}", end="")
        
        # Current time
        now = datetime.now(timezone.utc)
        time_str = now.strftime("%H:%M:%S UTC")
        print(f"  {Colors.WHITE}|  Time: {time_str}{Colors.RESET}")
        
        # Status
        status = "Connected & Streaming" if self.is_connected else "Connecting..."
        status_color = Colors.BRIGHT_GREEN if self.is_connected else Colors.YELLOW
        print(f"  {Colors.WHITE}Status: {status_color}✓ {status}{Colors.RESET}  {Colors.WHITE}|  Updates: {self.update_count}{Colors.RESET}")
    
    def render_prices(self, up_mid: float, down_mid: float, up_book: dict, down_book: dict):
        """Render the current market prices section"""
        print()
        print(f"  {Colors.BRIGHT_YELLOW}💰 CURRENT MARKET PRICES 💰{Colors.RESET}")
        
        # Calculate bid/ask from orderbooks
        up_bid = float(up_book.get('bids', [{}])[0].get('price', 0)) if up_book and up_book.get('bids') else 0
        up_ask = float(up_book.get('asks', [{}])[0].get('price', 0)) if up_book and up_book.get('asks') else 0
        down_bid = float(down_book.get('bids', [{}])[0].get('price', 0)) if down_book and down_book.get('bids') else 0
        down_ask = float(down_book.get('asks', [{}])[0].get('price', 0)) if down_book and down_book.get('asks') else 0
        
        # UP section
        up_pct = up_mid * 100 if up_mid else 0
        down_pct = down_mid * 100 if down_mid else 0
        
        print(f"            {Colors.BRIGHT_GREEN}UP{Colors.RESET}                          {Colors.RED}DOWN{Colors.RESET}")
        
        # Price bars
        up_bar = f"{Colors.BG_GREEN}{Colors.BLACK} {up_pct:.1f}% {Colors.RESET}"
        down_bar = f"{Colors.BG_RED}{Colors.WHITE} {down_pct:.1f}% {Colors.RESET}"
        print(f"          {up_bar}                      {down_bar}")
        
        # Bid/Ask
        print(f"       {Colors.GREEN}Bid: {self.format_price(up_bid)}{Colors.RESET}                  {Colors.GREEN}Bid: {self.format_price(down_bid)}{Colors.RESET}")
        print(f"       {Colors.RED}Ask: {self.format_price(up_ask)}{Colors.RESET}                  {Colors.RED}Ask: {self.format_price(down_ask)}{Colors.RESET}")
        
        # Total
        total = (up_mid or 0) + (down_mid or 0)
        print(f"            {Colors.WHITE}Total:{Colors.RESET}")
        print(f"            {Colors.BRIGHT_CYAN}{total*100:.1f}¢{Colors.RESET}")
    
    def render_orderbook(self, title: str, orderbook: dict, color: str):
        """Render a single orderbook"""
        if not orderbook:
            return
        
        bids = orderbook.get('bids', [])[:3]
        asks = orderbook.get('asks', [])[:3]
        
        print(f"  {color}{Colors.BOLD}Bid ${Colors.RESET}    {color}Size{Colors.RESET}    {color}Ask ${Colors.RESET}    {color}Size{Colors.RESET}")
        
        max_rows = max(len(bids), len(asks))
        for i in range(min(3, max_rows)):
            bid_price = ""
            bid_size = ""
            ask_price = ""
            ask_size = ""
            
            if i < len(bids):
                bid_price = f"{float(bids[i].get('price', 0)):.3f}"
                bid_size = self.format_size(float(bids[i].get('size', 0)))
            
            if i < len(asks):
                ask_price = f"{float(asks[i].get('price', 0)):.3f}"
                ask_size = self.format_size(float(asks[i].get('size', 0)))
            
            print(f"  {Colors.GREEN}{bid_price:<7}{Colors.RESET} {Colors.YELLOW}{bid_size:<7}{Colors.RESET} {Colors.RED}{ask_price:<7}{Colors.RESET} {Colors.YELLOW}{ask_size:<7}{Colors.RESET}")
    
    def render_orderbooks(self, up_book: dict, down_book: dict):
        """Render both orderbooks side by side"""
        print()
        print(f"    {Colors.BRIGHT_GREEN}UP Token Orderbook{Colors.RESET}              {Colors.RED}DOWN Token Orderbook{Colors.RESET}")
        
        up_bids = up_book.get('bids', [])[:3] if up_book else []
        up_asks = up_book.get('asks', [])[:3] if up_book else []
        down_bids = down_book.get('bids', [])[:3] if down_book else []
        down_asks = down_book.get('asks', [])[:3] if down_book else []
        
        # Headers
        print(f"  {Colors.BRIGHT_GREEN}Bid ${Colors.RESET}  {Colors.YELLOW}Size{Colors.RESET}    {Colors.RED}Ask ${Colors.RESET}  {Colors.YELLOW}Size{Colors.RESET}    ", end="")
        print(f"{Colors.BRIGHT_GREEN}Bid ${Colors.RESET}  {Colors.YELLOW}Size{Colors.RESET}    {Colors.RED}Ask ${Colors.RESET}  {Colors.YELLOW}Size{Colors.RESET}")
        
        for i in range(3):
            # UP orderbook
            up_bid_price = f"{float(up_bids[i].get('price', 0)):.3f}" if i < len(up_bids) else "     "
            up_bid_size = self.format_size(float(up_bids[i].get('size', 0))) if i < len(up_bids) else "    "
            up_ask_price = f"{float(up_asks[i].get('price', 0)):.3f}" if i < len(up_asks) else "     "
            up_ask_size = self.format_size(float(up_asks[i].get('size', 0))) if i < len(up_asks) else "    "
            
            # DOWN orderbook
            down_bid_price = f"{float(down_bids[i].get('price', 0)):.3f}" if i < len(down_bids) else "     "
            down_bid_size = self.format_size(float(down_bids[i].get('size', 0))) if i < len(down_bids) else "    "
            down_ask_price = f"{float(down_asks[i].get('price', 0)):.3f}" if i < len(down_asks) else "     "
            down_ask_size = self.format_size(float(down_asks[i].get('size', 0))) if i < len(down_asks) else "    "
            
            print(f"  {Colors.GREEN}{up_bid_price}{Colors.RESET}  {Colors.YELLOW}{up_bid_size:<6}{Colors.RESET}  {Colors.RED}{up_ask_price}{Colors.RESET}  {Colors.YELLOW}{up_ask_size:<6}{Colors.RESET}  ", end="")
            print(f"{Colors.GREEN}{down_bid_price}{Colors.RESET}  {Colors.YELLOW}{down_bid_size:<6}{Colors.RESET}  {Colors.RED}{down_ask_price}{Colors.RESET}  {Colors.YELLOW}{down_ask_size:<6}{Colors.RESET}")
    
    def render_recent_activity(self, up_trades: list, down_trades: list):
        """Render recent orderbook activity"""
        print()
        print(f"  {Colors.BRIGHT_YELLOW}📊 Recent Orderbook Activity 📊{Colors.RESET}")
        print()
        
        # Combine and sort trades
        all_trades = []
        for trade in up_trades[:5]:
            trade['token'] = 'UP'
            all_trades.append(trade)
        for trade in down_trades[:5]:
            trade['token'] = 'DOWN'
            all_trades.append(trade)
        
        # Sort by timestamp
        all_trades.sort(key=lambda x: x.get('timestamp', 0) or x.get('created_at', ''), reverse=True)
        
        # Headers
        print(f"  {Colors.WHITE}Time{Colors.RESET}       {Colors.WHITE}Token{Colors.RESET}  {Colors.WHITE}Si...{Colors.RESET}  {Colors.WHITE}Price{Colors.RESET}    {Colors.WHITE}Size{Colors.RESET}      {Colors.WHITE}Best{Colors.RESET}     {Colors.WHITE}Best{Colors.RESET}")
        print(f"                                            {Colors.WHITE}Bid{Colors.RESET}      {Colors.WHITE}Ask{Colors.RESET}")
        
        for trade in all_trades[:10]:
            # Parse timestamp
            ts = trade.get('match_time') or trade.get('created_at') or trade.get('timestamp', '')
            if ts:
                try:
                    if isinstance(ts, (int, float)):
                        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    else:
                        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    time_str = dt.strftime("%H:%M:...")
                except:
                    time_str = "??:??:..."
            else:
                time_str = "??:??:..."
            
            token = trade.get('token', '??')
            token_color = Colors.GREEN if token == 'UP' else Colors.RED
            
            side = trade.get('side', 'BUY')
            side_color = Colors.BG_GREEN if side == 'BUY' else Colors.BG_RED
            side_text = f"{side_color}{Colors.BLACK} {side[:2]}... {Colors.RESET}"
            
            price = float(trade.get('price', 0))
            price_str = f"${price:.2f}"
            
            size = float(trade.get('size', 0))
            size_str = f"{size:.1f}"
            
            # Placeholder for best bid/ask (would need real-time data)
            best_bid = trade.get('best_bid', 0.1)
            best_ask = trade.get('best_ask', 0.9)
            
            print(f"  {Colors.CYAN}{time_str}{Colors.RESET}  {token_color}{token:<5}{Colors.RESET}  {side_text}  {Colors.WHITE}{price_str:<7}{Colors.RESET}  {Colors.YELLOW}{size_str:<8}{Colors.RESET}  {Colors.GREEN}{best_bid:<7}{Colors.RESET}  {Colors.RED}{best_ask}{Colors.RESET}")
    
    def render_display(self, up_mid: float, down_mid: float, up_book: dict, down_book: dict, up_trades: list, down_trades: list):
        """Render the full terminal display"""
        self.clear_screen()
        
        # Draw border
        print(f"  {Colors.BLUE}{'─' * 60}{Colors.RESET}")
        
        self.render_header()
        
        print(f"  {Colors.BLUE}{'─' * 60}{Colors.RESET}")
        
        self.render_prices(up_mid, down_mid, up_book, down_book)
        
        print(f"  {Colors.BLUE}{'─' * 60}{Colors.RESET}")
        
        self.render_orderbooks(up_book, down_book)
        
        print(f"  {Colors.BLUE}{'─' * 60}{Colors.RESET}")
        
        self.render_recent_activity(up_trades, down_trades)
        
        print(f"  {Colors.BLUE}{'─' * 60}{Colors.RESET}")
        print(f"  {Colors.WHITE}Press Ctrl+C to exit{Colors.RESET}")
    
    async def run(self):
        """Main run loop"""
        print(f"{Colors.CYAN}Starting Polymarket Bot...{Colors.RESET}")
        print(f"{Colors.WHITE}Event: {self.event_slug}{Colors.RESET}")
        print()
        
        async with aiohttp.ClientSession() as session:
            # Fetch event data first
            print(f"{Colors.YELLOW}Fetching event data...{Colors.RESET}")
            event = await self.fetch_markets_by_event(session)
            
            if not event:
                print(f"{Colors.RED}Could not find event: {self.event_slug}{Colors.RESET}")
                print(f"{Colors.YELLOW}Trying to search for markets...{Colors.RESET}")
            
            # Fetch token IDs
            print(f"{Colors.YELLOW}Fetching token IDs...{Colors.RESET}")
            found_tokens = await self.fetch_token_ids(session)
            
            if not found_tokens:
                # Use demo mode with sample data
                print(f"{Colors.YELLOW}Could not find token IDs, using demo mode with sample data...{Colors.RESET}")
                print(f"{Colors.WHITE}Note: In production, you would need valid token IDs from Polymarket{Colors.RESET}")
                await asyncio.sleep(2)
                
                # Demo mode - show interface with simulated data
                await self.run_demo_mode()
                return
            
            print(f"{Colors.GREEN}Found tokens:{Colors.RESET}")
            print(f"  UP Token: {self.up_token_id}")
            print(f"  DOWN Token: {self.down_token_id}")
            
            self.is_connected = True
            
            # Main update loop
            try:
                while True:
                    # Fetch all data in parallel
                    results = await asyncio.gather(
                        self.fetch_midpoint(session, self.up_token_id),
                        self.fetch_midpoint(session, self.down_token_id),
                        self.fetch_orderbook(session, self.up_token_id),
                        self.fetch_orderbook(session, self.down_token_id),
                        self.fetch_recent_trades(session, self.up_token_id),
                        self.fetch_recent_trades(session, self.down_token_id),
                        return_exceptions=True
                    )
                    
                    up_mid, down_mid, up_book, down_book, up_trades, down_trades = results
                    
                    # Handle exceptions
                    up_mid = up_mid if not isinstance(up_mid, Exception) else 0.5
                    down_mid = down_mid if not isinstance(down_mid, Exception) else 0.5
                    up_book = up_book if not isinstance(up_book, Exception) else {}
                    down_book = down_book if not isinstance(down_book, Exception) else {}
                    up_trades = up_trades if not isinstance(up_trades, Exception) else []
                    down_trades = down_trades if not isinstance(down_trades, Exception) else []
                    
                    self.update_count += 1
                    
                    self.render_display(up_mid, down_mid, up_book, down_book, up_trades, down_trades)
                    
                    # Wait before next update
                    await asyncio.sleep(1)
                    
            except KeyboardInterrupt:
                print(f"\n{Colors.YELLOW}Bot stopped by user.{Colors.RESET}")
    
    async def run_demo_mode(self):
        """Run in demo mode with simulated data"""
        import random
        
        self.is_connected = True
        
        # Set demo window times
        now = datetime.now(timezone.utc)
        self.window_start = now
        self.window_end = now
        
        try:
            while True:
                # Generate realistic demo data
                up_mid = random.uniform(0.08, 0.15)
                down_mid = 1.0 - up_mid - random.uniform(-0.02, 0.02)
                
                up_book = {
                    'bids': [
                        {'price': str(up_mid - 0.01), 'size': str(random.uniform(500, 2000))},
                        {'price': str(up_mid - 0.02), 'size': str(random.uniform(1000, 5000))},
                        {'price': str(up_mid - 0.03), 'size': str(random.uniform(500, 1000))},
                    ],
                    'asks': [
                        {'price': str(up_mid + 0.01), 'size': str(random.uniform(500, 2000))},
                        {'price': str(up_mid + 0.02), 'size': str(random.uniform(1000, 5000))},
                        {'price': str(up_mid + 0.03), 'size': str(random.uniform(500, 1000))},
                    ]
                }
                
                down_book = {
                    'bids': [
                        {'price': str(down_mid - 0.01), 'size': str(random.uniform(500, 2000))},
                        {'price': str(down_mid - 0.02), 'size': str(random.uniform(1000, 5000))},
                        {'price': str(down_mid - 0.03), 'size': str(random.uniform(500, 1000))},
                    ],
                    'asks': [
                        {'price': str(down_mid + 0.01), 'size': str(random.uniform(500, 2000))},
                        {'price': str(down_mid + 0.02), 'size': str(random.uniform(1000, 5000))},
                        {'price': str(down_mid + 0.03), 'size': str(random.uniform(500, 1000))},
                    ]
                }
                
                # Generate demo trades
                up_trades = []
                down_trades = []
                
                for i in range(5):
                    up_trades.append({
                        'match_time': time.time() - i * 60,
                        'side': random.choice(['BUY', 'SELL']),
                        'price': random.uniform(0.1, 0.2),
                        'size': random.uniform(50, 300),
                        'best_bid': 0.1,
                        'best_ask': 0.11
                    })
                    down_trades.append({
                        'match_time': time.time() - i * 60 - 30,
                        'side': random.choice(['BUY', 'SELL']),
                        'price': random.uniform(0.8, 0.9),
                        'size': random.uniform(50, 300),
                        'best_bid': 0.89,
                        'best_ask': 0.9
                    })
                
                self.update_count += 1
                self.render_display(up_mid, down_mid, up_book, down_book, up_trades, down_trades)
                
                await asyncio.sleep(1)
                
        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}Demo mode stopped.{Colors.RESET}")


async def main():
    # Event slug fra URL: https://polymarket.com/event/btc-updown-15m-1769755500
    event_slug = "btc-updown-15m-1769755500"
    
    bot = PolymarketBot(event_slug)
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
