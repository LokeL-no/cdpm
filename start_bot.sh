#!/bin/bash
# Polymarket Bot - Start Script
# Kjører botten i tmux slik at den fortsetter etter disconnect

SESSION_NAME="polymarket"

# Sjekk om session allerede eksisterer
if tmux has-session -t $SESSION_NAME 2>/dev/null; then
    echo "🤖 Bot kjører allerede!"
    echo "📺 Koble til med: tmux attach -t $SESSION_NAME"
    echo "🛑 Stopp med: tmux kill-session -t $SESSION_NAME"
else
    echo "🚀 Starter Polymarket Bot i bakgrunnen..."
    tmux new-session -d -s $SESSION_NAME "cd /workspaces/cdpm && python3 web_bot_multi.py"
    sleep 2
    echo "✅ Bot startet!"
    echo ""
    echo "📋 Nyttige kommandoer:"
    echo "   tmux attach -t $SESSION_NAME    - Se bot output"
    echo "   Ctrl+B, D                       - Koble fra (bot fortsetter)"
    echo "   tmux kill-session -t $SESSION_NAME - Stopp bot"
    echo ""
    echo "🌐 WebSocket: http://localhost:8080"
fi
