#!/usr/bin/env python3
"""
WebSocket Latency Test for Polymarket
Tests the actual latency for real-time market data streams
"""

import asyncio
import websockets
import json
import time
from datetime import datetime

POLYMARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

async def test_websocket_latency():
    print("=== Polymarket WebSocket Latency Test ===")
    print(f"Date: {datetime.now()}")
    print(f"\nConnecting to: {POLYMARKET_WS_URL}")
    print()
    
    try:
        # Measure connection time
        connect_start = time.time()
        async with websockets.connect(POLYMARKET_WS_URL) as websocket:
            connect_time = (time.time() - connect_start) * 1000
            print(f"✓ WebSocket connection established: {connect_time:.2f} ms")
            print()
            
            # Subscribe to a market (using a popular market ID)
            subscribe_msg = {
                "type": "subscribe",
                "channel": "market",
                "market": "0x0000000000000000000000000000000000000000"  # Example market
            }
            
            # Measure round-trip time
            latencies = []
            print("Measuring message round-trip times...")
            
            for i in range(10):
                send_start = time.time()
                
                # Send ping or subscription message
                await websocket.send(json.dumps(subscribe_msg))
                
                # Wait for response
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                    rtt = (time.time() - send_start) * 1000
                    latencies.append(rtt)
                    print(f"Test {i+1}: {rtt:.2f} ms")
                except asyncio.TimeoutError:
                    print(f"Test {i+1}: Timeout")
                
                await asyncio.sleep(0.5)
            
            print()
            print("=" * 50)
            if latencies:
                avg_latency = sum(latencies) / len(latencies)
                min_latency = min(latencies)
                max_latency = max(latencies)
                
                print(f"Connection setup: {connect_time:.2f} ms")
                print(f"Average message RTT: {avg_latency:.2f} ms")
                print(f"Min latency: {min_latency:.2f} ms")
                print(f"Max latency: {max_latency:.2f} ms")
                print("=" * 50)
                print()
                print("💡 WebSocket latency is typically lower than HTTP")
                print("   after the initial connection is established!")
                print()
                print("   Ideal for trading: < 30ms")
                print("   Good: 30-50ms")
                print("   Acceptable: 50-80ms")
                print("   Slow: > 80ms")
            else:
                print("No successful measurements")
                
    except Exception as e:
        print(f"Error: {e}")
        print()
        print("Note: This might fail if:")
        print("  1. WebSocket endpoint requires authentication")
        print("  2. Firewall blocks WebSocket connections")
        print("  3. Endpoint URL has changed")
        print()
        print("The bot will use authenticated WebSocket connections")
        print("which may have different performance characteristics.")

if __name__ == "__main__":
    asyncio.run(test_websocket_latency())
