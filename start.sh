#!/bin/bash
cd /Users/manusmclaughlin/Desktop/claude-trading-sytem
while true; do
  ./venv/bin/python server.py
  echo "Server crashed — restarting in 2s..."
  sleep 2
done
