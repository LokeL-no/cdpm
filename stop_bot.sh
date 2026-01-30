#!/bin/bash
# Stopp Polymarket Bot

SESSION_NAME="polymarket"

if tmux has-session -t $SESSION_NAME 2>/dev/null; then
    tmux kill-session -t $SESSION_NAME
    echo "🛑 Bot stoppet!"
else
    echo "ℹ️ Bot kjører ikke"
fi
