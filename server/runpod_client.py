"""RunPod serverless client for the relay.

Forwards TTS requests to RunPod when the local GPU tunnel is not connected.
"""

import asyncio
import base64
import json
import logging
import os
import time

import aiohttp

logger = logging.getLogger(__name__)


class RunPodClient:
    """Async client for RunPod serverless endpoint."""

    def __init__(self, endpoint_id: str, runpod_api_key: str, tts_api_key: str):
        self.endpoint_id = endpoint_id
        self.runpod_api_key = runpod_api_key
        self.tts_api_key = tts_api_key
        self.base_url = f"https://api.runpod.ai/v2/{endpoint_id}"
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def health(self) -> dict:
        """Check endpoint health."""
        session = await self._get_session()
        async with session.get(
            f"{self.base_url}/health",
            headers={"Authorization": f"Bearer {self.runpod_api_key}"},
        ) as resp:
            return await resp.json()

    async def runsync(self, endpoint: str, body: dict | None = None, timeout: float = 90) -> dict:
        """Send a synchronous request to RunPod.

        Args:
            endpoint: The TTS API endpoint path (e.g. /api/v1/voices/design)
            body: Request body for the endpoint
            timeout: Timeout in seconds (RunPod default is 90s)

        Returns:
            RunPod response dict with status, output/error, timing info.
        """
        session = await self._get_session()
        payload = {
            "input": {
                "endpoint": endpoint,
                "body": body or {},
                "api_key": self.tts_api_key,
            }
        }
        async with session.post(
            f"{self.base_url}/runsync",
            json=payload,
            headers={"Authorization": f"Bearer {self.runpod_api_key}"},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            return await resp.json()

    async def run_async(self, endpoint: str, body: dict | None = None) -> str:
        """Send an async request, return job ID."""
        session = await self._get_session()
        payload = {
            "input": {
                "endpoint": endpoint,
                "body": body or {},
                "api_key": self.tts_api_key,
            }
        }
        async with session.post(
            f"{self.base_url}/run",
            json=payload,
            headers={"Authorization": f"Bearer {self.runpod_api_key}"},
        ) as resp:
            data = await resp.json()
            return data.get("id", "")

    async def poll_status(self, job_id: str) -> dict:
        """Poll job status."""
        session = await self._get_session()
        async with session.get(
            f"{self.base_url}/status/{job_id}",
            headers={"Authorization": f"Bearer {self.runpod_api_key}"},
        ) as resp:
            return await resp.json()
