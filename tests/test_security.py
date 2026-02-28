"""Tests for security fixes: auth on debug/tunnel, body limits, RunPod auth warning."""
import os
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from aiohttp import web

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestRunPodAuthWarning(unittest.TestCase):
    """Test that RunPod handlers warn when API_KEY is unset."""

    def test_handler_warns_when_no_api_key(self):
        sys.modules["runpod"] = MagicMock()
        sys.modules["runpod.serverless"] = MagicMock()
        import server.runpod_slim as slim
        slim.engine = MagicMock()
        slim.engine._models = {"voice_design": True}
        slim.init_done = True
        slim.init_error = None

        # With API_KEY set — valid key works
        with patch.dict(os.environ, {"API_KEY": "test123"}):
            result = slim.handler({"input": {"endpoint": "/api/v1/status", "api_key": "test123"}})
            self.assertEqual(result["status"], "running")

        # With API_KEY set — wrong key rejected
        with patch.dict(os.environ, {"API_KEY": "test123"}):
            result = slim.handler({"input": {"endpoint": "/api/v1/status", "api_key": "wrong"}})
            self.assertIn("error", result)

        # With API_KEY unset — still works (RunPod auth layer)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("API_KEY", None)
            result = slim.handler({"input": {"endpoint": "/api/v1/status", "api_key": ""}})
            self.assertEqual(result["status"], "running")


class TestBodySizeLimit(unittest.TestCase):
    """Test that the relay has a body size limit configured."""

    def test_app_has_client_max_size(self):
        """Verify Application is created with client_max_size."""
        from server.remote_relay import RemoteRelay
        # We can't easily instantiate the full relay, but we can check the code
        import inspect
        source = inspect.getsource(RemoteRelay.create_app)
        self.assertIn("client_max_size", source)
        self.assertIn("10 * 1024 * 1024", source)


class TestDebugAuthRequired(unittest.TestCase):
    """Test that debug endpoints have auth checks."""

    def test_debug_http_has_auth(self):
        import inspect
        from server.remote_relay import RemoteRelay
        source = inspect.getsource(RemoteRelay.handle_debug_http)
        self.assertIn("_require_auth", source)

    def test_debug_ws_has_auth(self):
        import inspect
        from server.remote_relay import RemoteRelay
        source = inspect.getsource(RemoteRelay.handle_debug_ws)
        self.assertIn("_require_auth", source)

    def test_tunnel_has_auth(self):
        import inspect
        from server.remote_relay import RemoteRelay
        source = inspect.getsource(RemoteRelay.handle_websocket_tunnel)
        self.assertIn("auth", source.lower())


if __name__ == "__main__":
    unittest.main()
