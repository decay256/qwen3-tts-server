"""Tests for GCS hooks in remote_relay.py and runpod_handler.py.

All GCS interactions are mocked — no real GCS calls.
All torch/model imports are mocked — no GPU required.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# ── Relay hook tests ──────────────────────────────────────────────────────────


class TestRelayGCSPromptUpload:
    """Tests for _gcs_push_after_create in RemoteRelay."""

    def _make_relay_with_mock_gcs(self, tmp_path):
        """Build a minimal RemoteRelay with a mocked GCS prompt store."""
        config = {
            "api_key": "test-key-abc123",
            "remote": {"bind": "0.0.0.0", "port": 9800},
        }

        mock_gcs = MagicMock()

        with (
            patch("server.remote_relay.GCSPromptStore", return_value=mock_gcs),
            patch("server.remote_relay.TunnelServer"),
            patch("server.remote_relay.AuthManager"),
        ):
            from server.remote_relay import RemoteRelay
            relay = RemoteRelay(config)
            relay.prompt_sync = mock_gcs
            return relay, mock_gcs

    @pytest.mark.asyncio
    async def test_gcs_push_after_create_success(self, tmp_path):
        """Successful GCS push after tunnel clone-prompt creation."""
        relay, mock_gcs = self._make_relay_with_mock_gcs(tmp_path)

        # Tunnel returns success with .pt data
        import base64
        fake_pt_b64 = base64.b64encode(b"fake-tensor-data").decode()

        mock_tunnel_response = MagicMock()
        mock_tunnel_response.status_code = 200
        mock_tunnel_response.body = json.dumps({"pt_b64": fake_pt_b64})

        relay.tunnel_server.send_request = AsyncMock(return_value=mock_tunnel_response)

        mock_gcs.push = MagicMock(return_value=MagicMock(
            gcs_path="gs://test-bucket/voice-prompts/maya-calm.pt",
            size_bytes=len(b"fake-tensor-data"),
        ))

        req_body = {"character": "maya", "ref_text": "Hello"}
        await relay._gcs_push_after_create("maya-calm", req_body)

        mock_gcs.push.assert_called_once()
        call_args = mock_gcs.push.call_args
        assert call_args[0][0] == "maya-calm"  # prompt_id

    @pytest.mark.asyncio
    async def test_gcs_push_no_prompt_sync_skips(self, tmp_path):
        """No GCS upload when prompt_sync is None."""
        relay, mock_gcs = self._make_relay_with_mock_gcs(tmp_path)
        relay.prompt_sync = None

        await relay._gcs_push_after_create("maya-calm", {})

        # No GCS interaction
        mock_gcs.push.assert_not_called()

    @pytest.mark.asyncio
    async def test_gcs_push_download_endpoint_returns_404(self, tmp_path):
        """If download endpoint returns non-200, skip GCS upload gracefully."""
        relay, mock_gcs = self._make_relay_with_mock_gcs(tmp_path)

        mock_tunnel_response = MagicMock()
        mock_tunnel_response.status_code = 404
        mock_tunnel_response.body = json.dumps({"error": "not found"})

        relay.tunnel_server.send_request = AsyncMock(return_value=mock_tunnel_response)

        # Should not raise
        await relay._gcs_push_after_create("maya-calm", {})
        mock_gcs.push.assert_not_called()

    @pytest.mark.asyncio
    async def test_gcs_push_no_pt_b64_in_response(self, tmp_path):
        """If download response has no pt_b64 field, skip upload gracefully."""
        relay, mock_gcs = self._make_relay_with_mock_gcs(tmp_path)

        mock_tunnel_response = MagicMock()
        mock_tunnel_response.status_code = 200
        mock_tunnel_response.body = json.dumps({"status": "ok"})  # no pt_b64

        relay.tunnel_server.send_request = AsyncMock(return_value=mock_tunnel_response)

        await relay._gcs_push_after_create("maya-calm", {})
        mock_gcs.push.assert_not_called()

    @pytest.mark.asyncio
    async def test_gcs_push_upload_failure_does_not_raise(self, tmp_path):
        """If GCS push fails, the method logs a warning but doesn't raise."""
        relay, mock_gcs = self._make_relay_with_mock_gcs(tmp_path)

        import base64
        fake_pt_b64 = base64.b64encode(b"data").decode()

        mock_tunnel_response = MagicMock()
        mock_tunnel_response.status_code = 200
        mock_tunnel_response.body = json.dumps({"pt_b64": fake_pt_b64})

        relay.tunnel_server.send_request = AsyncMock(return_value=mock_tunnel_response)
        mock_gcs.push.side_effect = RuntimeError("GCS network error")

        # Must not raise
        await relay._gcs_push_after_create("maya-calm", {})

    @pytest.mark.asyncio
    async def test_gcs_push_tunnel_exception_does_not_raise(self, tmp_path):
        """If tunnel send_request throws, the method handles it gracefully."""
        relay, mock_gcs = self._make_relay_with_mock_gcs(tmp_path)

        relay.tunnel_server.send_request = AsyncMock(side_effect=ConnectionError("tunnel down"))

        # Must not raise
        await relay._gcs_push_after_create("maya-calm", {})
        mock_gcs.push.assert_not_called()


class TestRelayHandleCreateClonePrompt:
    """Tests for handle_create_clone_prompt scheduling GCS push."""

    def _make_relay(self):
        config = {
            "api_key": "test-key-abc123",
            "remote": {"bind": "0.0.0.0", "port": 9800},
        }
        mock_gcs = MagicMock()

        with (
            patch("server.remote_relay.GCSPromptStore", return_value=mock_gcs),
            patch("server.remote_relay.TunnelServer"),
            patch("server.remote_relay.AuthManager"),
        ):
            from server.remote_relay import RemoteRelay
            relay = RemoteRelay(config)
            relay.prompt_sync = mock_gcs
            return relay, mock_gcs

    @pytest.mark.asyncio
    async def test_handle_create_clone_prompt_schedules_gcs_push(self):
        """On successful tunnel creation, GCS push future is scheduled."""
        from aiohttp.test_utils import make_mocked_request
        from aiohttp import web

        relay, mock_gcs = self._make_relay()

        # Auth passes
        relay._check_auth = MagicMock(return_value=True)
        relay.tunnel_server.has_client = True

        # Tunnel returns success
        success_response = web.json_response({"status": "created", "name": "maya-calm"})

        relay._forward_with_fallback = AsyncMock(return_value=success_response)
        relay._gcs_push_after_create = AsyncMock()

        # Build a mock request
        request = make_mocked_request(
            "POST", "/api/v1/voices/clone-prompt",
            headers={"Authorization": "Bearer test-key-abc123"},
        )
        request.text = AsyncMock(return_value=json.dumps({"name": "maya-calm"}))

        with patch("asyncio.ensure_future") as mock_ensure_future:
            response = await relay.handle_create_clone_prompt(request)

        # Response should still be returned
        assert response.status == 200

        # GCS push should have been scheduled
        mock_ensure_future.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_create_clone_prompt_no_gcs_on_failure(self):
        """If tunnel creation fails (non-2xx), do NOT schedule GCS push."""
        from aiohttp.test_utils import make_mocked_request
        from aiohttp import web

        relay, mock_gcs = self._make_relay()
        relay._check_auth = MagicMock(return_value=True)
        relay.tunnel_server.has_client = True

        error_response = web.json_response({"error": "model failed"}, status=500)
        relay._forward_with_fallback = AsyncMock(return_value=error_response)

        request = make_mocked_request(
            "POST", "/api/v1/voices/clone-prompt",
            headers={"Authorization": "Bearer test-key-abc123"},
        )
        request.text = AsyncMock(return_value=json.dumps({"name": "maya-calm"}))

        with patch("asyncio.ensure_future") as mock_ensure_future:
            response = await relay.handle_create_clone_prompt(request)

        assert response.status == 500
        mock_ensure_future.assert_not_called()


# ── RunPod handler hook tests ─────────────────────────────────────────────────

# Inject a fake 'runpod' module before any import of server.runpod_handler
if "runpod" not in sys.modules:
    sys.modules["runpod"] = MagicMock()
if "runpod.serverless" not in sys.modules:
    sys.modules["runpod.serverless"] = MagicMock()


def _get_handler_mod():
    """Import server.runpod_handler with runpod mocked out."""
    # Ensure the fake is in place
    if "runpod" not in sys.modules:
        sys.modules["runpod"] = MagicMock()
    # Clear cached import so we get a fresh module (in case of prior failures)
    sys.modules.pop("server.runpod_handler", None)
    import server.runpod_handler as handler_mod
    return handler_mod


class TestRunPodHandlerGCSEnsureLocal:
    """Tests for ensure_local hook in handle_synthesize_with_prompt."""

    @pytest.fixture(autouse=True)
    def _mock_runpod(self):
        """Ensure runpod is mocked for every test in this class."""
        if "runpod" not in sys.modules:
            sys.modules["runpod"] = MagicMock()
        yield

    def _import_handler(self):
        """Import handler module with all heavy deps mocked."""
        sys.modules.pop("server.runpod_handler", None)
        import server.runpod_handler as handler_mod
        return handler_mod

    def test_ensure_local_called_when_prompt_missing(self, tmp_path):
        """ensure_local is called when the prompt is not in the local voices dir."""
        handler_mod = self._import_handler()

        mock_gcs = MagicMock()
        mock_gcs.ensure_local.return_value = MagicMock(
            local_path=str(tmp_path / "voices" / "maya-calm.pt"),
            cache_hit=False,
        )

        mock_engine = MagicMock()
        mock_prompt_store = MagicMock()
        mock_prompt_store.load_prompt.return_value = MagicMock()

        import numpy as np
        fake_wav = np.zeros(24000, dtype=np.float32)
        mock_engine.synthesize_with_clone_prompt.return_value = (fake_wav, 24000)

        voices_dir = str(tmp_path / "voices")
        os.makedirs(voices_dir, exist_ok=True)

        handler_mod.engine = mock_engine
        handler_mod.prompt_store = mock_prompt_store
        handler_mod.gcs_prompt_store = mock_gcs

        with patch.dict(os.environ, {"PROMPTS_DIR": voices_dir}):
            with patch("os.path.exists", return_value=False):
                handler_mod.handle_synthesize_with_prompt({
                    "voice_prompt": "maya-calm",
                    "text": "Hello world",
                })

        mock_gcs.ensure_local.assert_called_once_with("maya-calm", voices_dir)

    def test_ensure_local_not_called_when_prompt_exists_locally(self, tmp_path):
        """ensure_local is NOT called when the .prompt file already exists locally."""
        handler_mod = self._import_handler()

        mock_gcs = MagicMock()
        mock_engine = MagicMock()
        mock_prompt_store = MagicMock()
        mock_prompt_store.load_prompt.return_value = MagicMock()

        import numpy as np
        fake_wav = np.zeros(24000, dtype=np.float32)
        mock_engine.synthesize_with_clone_prompt.return_value = (fake_wav, 24000)

        voices_dir = tmp_path / "voices"
        voices_dir.mkdir()
        # Create the .prompt file locally so the handler skips GCS
        (voices_dir / "maya-calm.prompt").write_bytes(b"fake-prompt-data")

        handler_mod.engine = mock_engine
        handler_mod.prompt_store = mock_prompt_store
        handler_mod.gcs_prompt_store = mock_gcs

        with patch.dict(os.environ, {"PROMPTS_DIR": str(voices_dir)}):
            handler_mod.handle_synthesize_with_prompt({
                "voice_prompt": "maya-calm",
                "text": "Hello",
            })

        mock_gcs.ensure_local.assert_not_called()

    def test_ensure_local_gcs_not_found_does_not_crash(self, tmp_path):
        """If ensure_local raises FileNotFoundError, the handler continues gracefully."""
        handler_mod = self._import_handler()

        mock_gcs = MagicMock()
        mock_gcs.ensure_local.side_effect = FileNotFoundError("Prompt not in GCS")

        mock_engine = MagicMock()
        mock_prompt_store = MagicMock()
        mock_prompt_store.load_prompt.side_effect = FileNotFoundError("not found")

        voices_dir = tmp_path / "voices"
        voices_dir.mkdir()

        handler_mod.engine = mock_engine
        handler_mod.prompt_store = mock_prompt_store
        handler_mod.gcs_prompt_store = mock_gcs

        with patch.dict(os.environ, {"PROMPTS_DIR": str(voices_dir)}):
            with patch("os.path.exists", return_value=False):
                # Should not crash from the GCS layer; PromptStore may still raise
                try:
                    handler_mod.handle_synthesize_with_prompt({
                        "voice_prompt": "maya-calm",
                        "text": "Hello",
                    })
                except (FileNotFoundError, Exception):
                    pass

        # ensure_local was still called
        mock_gcs.ensure_local.assert_called_once()

    def test_ensure_local_gcs_error_does_not_crash(self, tmp_path):
        """If ensure_local raises a generic exception, the handler continues."""
        handler_mod = self._import_handler()

        mock_gcs = MagicMock()
        mock_gcs.ensure_local.side_effect = RuntimeError("GCS network error")

        mock_engine = MagicMock()
        mock_prompt_store = MagicMock()
        mock_prompt_store.load_prompt.return_value = MagicMock()

        import numpy as np
        fake_wav = np.zeros(24000, dtype=np.float32)
        mock_engine.synthesize_with_clone_prompt.return_value = (fake_wav, 24000)

        voices_dir = tmp_path / "voices"
        voices_dir.mkdir()

        handler_mod.engine = mock_engine
        handler_mod.prompt_store = mock_prompt_store
        handler_mod.gcs_prompt_store = mock_gcs

        with patch.dict(os.environ, {"PROMPTS_DIR": str(voices_dir)}):
            with patch("os.path.exists", return_value=False):
                # Should not crash
                result = handler_mod.handle_synthesize_with_prompt({
                    "voice_prompt": "maya-calm",
                    "text": "Hello",
                })

        assert result is not None

    def test_no_gcs_store_skips_ensure_local(self, tmp_path):
        """When gcs_prompt_store is None, ensure_local is never called."""
        handler_mod = self._import_handler()

        mock_engine = MagicMock()
        mock_prompt_store = MagicMock()
        mock_prompt_store.load_prompt.return_value = MagicMock()

        import numpy as np
        fake_wav = np.zeros(24000, dtype=np.float32)
        mock_engine.synthesize_with_clone_prompt.return_value = (fake_wav, 24000)

        voices_dir = tmp_path / "voices"
        voices_dir.mkdir()

        handler_mod.engine = mock_engine
        handler_mod.prompt_store = mock_prompt_store
        handler_mod.gcs_prompt_store = None  # explicitly None

        with patch.dict(os.environ, {"PROMPTS_DIR": str(voices_dir)}):
            result = handler_mod.handle_synthesize_with_prompt({
                "voice_prompt": "maya-calm",
                "text": "Hello",
            })

        assert result is not None
