#!/usr/bin/env python3
"""Qwen3-TTS Server — entry point.

Loads TTS models on GPU and connects to the OpenClaw bridge via WebSocket tunnel.
"""

import asyncio
import logging
import signal
import sys

from . import config
from .tts_engine import TTSEngine
from .tunnel import TunnelClient

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("qwen3-tts")


async def main():
    logger.info("=" * 60)
    logger.info("Qwen3-TTS Server starting...")
    logger.info("Enabled models: %s", config.ENABLED_MODELS)
    logger.info("Bridge URL: %s", config.BRIDGE_URL)
    logger.info("=" * 60)

    # Load models
    engine = TTSEngine()
    logger.info("Loading TTS models (this may take a minute)...")
    engine.load_models()
    logger.info("Models ready! %s", engine.get_health())

    # Start tunnel
    tunnel = TunnelClient(engine)

    # Graceful shutdown
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def _shutdown(sig):
        logger.info("Received %s, shutting down...", sig.name)
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown, sig)

    # Run tunnel with stop handling
    tunnel_task = asyncio.create_task(tunnel.start())
    stop_task = asyncio.create_task(stop_event.wait())

    done, pending = await asyncio.wait(
        [tunnel_task, stop_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    await tunnel.stop()
    for t in pending:
        t.cancel()

    logger.info("Server stopped.")


def run():
    """CLI entry point."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
