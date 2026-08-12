#!/usr/bin/env python3
"""Entry point — launches the dashboard + trading engine.

    python run.py                 # start the web dashboard
    python run.py --autostart     # also start the engine immediately

Then open http://localhost:8000
"""
from __future__ import annotations

import argparse
import logging

import uvicorn

from app.config import load_settings


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    ap = argparse.ArgumentParser(description="Crypto trading bot")
    ap.add_argument("--autostart", action="store_true",
                    help="start the trading engine on launch")
    args = ap.parse_args()

    settings = load_settings()

    from app.web.server import app  # imported here so logging is configured first
    if args.autostart:
        app.state.engine.start()

    banner = "LIVE TRADING" if settings.live_confirmed else \
        ("LIVE (unconfirmed — orders blocked)" if settings.is_live else "PAPER TRADING")
    logging.getLogger("run").info("Mode: %s | Dashboard: http://%s:%s",
                                  banner, settings.web_host, settings.web_port)

    uvicorn.run(app, host=settings.web_host, port=settings.web_port, log_level="info")


if __name__ == "__main__":
    main()
