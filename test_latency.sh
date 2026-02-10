#!/bin/bash

echo "=== Polymarket Latency Test ==="
echo "Testing from: $(hostname)"
echo "Date: $(date)"
echo ""

echo "Running 10 tests to Polymarket API..."
echo ""

count=10
results=""

for i in $(seq 1 $count); do
    result=$(curl -w "%{time_starttransfer}" -o /dev/null -s https://gamma-api.polymarket.com/ping)
    results="$results $result"
    ms=$(python3 -c "print(f'{float($result)*1000:.2f}')")
    echo "Test $i: ${ms} ms"
    sleep 0.5
done

average=$(python3 -c "import sys; times = [float(x) for x in '$results'.split()]; print(f'{sum(times)/len(times)*1000:.2f}')")

echo ""
echo "=========================================="
echo "Average latency: ${average} ms"
echo "=========================================="
echo ""
echo "💡 For comparison, test the same from your VPS candidates!"
echo "   Good latency for trading: < 50ms"
echo "   Acceptable: 50-100ms"
echo "   Slow: > 100ms"
