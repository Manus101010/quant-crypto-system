"""Pin sizing for tests so they don't depend on the live defaults in config.py
(live: $80 margin / $300 sleeve; tests were written for $50 / $500)."""
import os

os.environ.setdefault("POSITION_MARGIN_USD", "50")
os.environ.setdefault("SLEEVE_USD", "500")
