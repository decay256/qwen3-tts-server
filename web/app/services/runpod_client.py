"""RunPod serverless client — sends requests via RunPod's /runsync API.

Translates our internal TTS API calls to RunPod's queue-based endpoint format.

Usage:
    client = RunPodClient(endpoint_id="abc123", runpod_api_key="rpa_...", tts_api_key="T6L...")
    result = await client.call("/api/v1/voices/design", {"text": "Hello", "instruct": "..."})
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class RunPodClient:
    """Client for RunPod serverless queue-based endpoints."""

    def __init__(self, endpoint_id: str, runpod_api_key: str, tts_api_key: str = ""):
        self.endpoint_url = f"https://api.runpod.ai/v2/{endpoint_id}/runsync"
        self.status_url = f"https://api.runpod.ai/v2/{endpoint_id}/health"
        self.runpod_api_key = runpod_api_key
        self.tts_api_key = tts_api_key
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={"Authorization": f"Bearer {self.runpod_api_key}"},
                timeout=600.0,
            )
        return self._client

    async def call(self, endpoint: str, body: dict | None = None) -> dict:
        """Call a TTS endpoint via RunPod.

        Args:
            endpoint: API path (e.g., "/api/v1/voices/design")
            body: Request body dict

        Returns:
            Result dict from the handler
        """
        client = self._get_client()
        payload = {
            "input": {
                "endpoint": endpoint,
                "body": body or {},
                "api_key": self.tts_api_key,
            }
        }

        resp = await client.post(self.endpoint_url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        # RunPod wraps the result
        if data.get("status") == "COMPLETED":
            return data.get("output", {})
        elif data.get("status") == "FAILED":
            raise Exception(f"RunPod job failed: {data.get('error', 'unknown')}")
        else:
            # IN_QUEUE or IN_PROGRESS — shouldn't happen with runsync but handle it
            raise Exception(f"RunPod job not completed: {data.get('status')}")

    async def health(self) -> dict:
        """Check RunPod endpoint health."""
        client = self._get_client()
        resp = await client.get(self.status_url)
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
