#!/usr/bin/env python3
"""Qwen3-TTS Server — entry point.

Loads TTS models on GPU and connects to the remote relay via WebSocket tunnel.
Can run in two modes:
  - local: GPU server that connects to a remote relay via tunnel
  - remote: Relay server that accepts tunnel connections and exposes REST API
"""

import asyncio
import logging
import os
import signal
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("qwen3-tts")


async def run_local():
    """Run the local GPU server."""
    from .local_server import LocalServer, load_config, setup_logging

    config_path = os.environ.get("QWEN3_TTS_CONFIG", "config.yaml")

    try:
        config = load_config(config_path)
    except (FileNotFoundError, ValueError) as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)

    setup_logging(config)
    server = LocalServer(config)

    # Graceful shutdown
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def _shutdown(sig):
        logger.info("Received %s, shutting down...", sig.name)
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown, sig)

    server_task = asyncio.create_task(server.start())
    stop_task = asyncio.create_task(stop_event.wait())

    done, pending = await asyncio.wait(
        [server_task, stop_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    await server.stop()
    for t in pending:
        t.cancel()

    logger.info("Server stopped.")


def run():
    """CLI entry point."""
    asyncio.run(run_local())


if __name__ == "__main__":
    run()
