#!/usr/bin/env python3
"""
Standalone Telegram alert-channel smoke test.

Zero dependency on any monitor or app code: it reads TELEGRAM_BOT_TOKEN and
TELEGRAM_CHAT_ID straight from .env, POSTs a single sendMessage to the Telegram
Bot API with the text "pipe works", and prints the HTTP status code plus the
full JSON response. Errors are NOT swallowed — the raw response/exception is
printed so a failure is obvious.

Usage:
    python3 scripts/test_telegram.py
"""
from __future__ import annotations
import sys
from pathlib import Path

import requests
from dotenv import dotenv_values


def main() -> int:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    env = dotenv_values(env_path)
    token = env.get("TELEGRAM_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_CHAT_ID")

    print(f".env: {env_path}")
    print(f"TELEGRAM_BOT_TOKEN: {'set' if token else 'MISSING'}")
    print(f"TELEGRAM_CHAT_ID:   {chat_id or 'MISSING'}")
    if not token or not chat_id:
        print("ERROR: token and/or chat id missing from .env", file=sys.stderr)
        return 1

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": "pipe works"}, timeout=15)

    print(f"HTTP status: {resp.status_code}")
    print("Raw response:")
    print(resp.text)
    return 0 if resp.ok else 2


if __name__ == "__main__":
    sys.exit(main())
