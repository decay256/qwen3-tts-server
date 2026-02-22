#!/usr/bin/env python3
"""
Tests for flat 10-second reconnection timing (no exponential backoff).
"""

import pytest
import time
from unittest.mock import AsyncMock, MagicMock, PropertyMock
from server.tunnel_v2 import EnhancedTunnelClient, FailureType


class TestReconnectionTiming:
    """Test that reconnection uses flat 10s delays, not exponential backoff."""
    
    def test_network_failure_flat_delay(self):
        """Network failures should always return 10s delay."""
        client = EnhancedTunnelClient("ws://test", "test-token")
        
        # Test multiple consecutive network failures
        for i in range(5):
            client._health.consecutive_failures = i
            delay = client._calculate_reconnect_delay(FailureType.NETWORK_ERROR)
            assert delay == 10.0, f"Network failure #{i} should be 10s, got {delay}s"
    
    def test_connection_failure_flat_delay(self):
        """Connection failures should always return 10s delay."""
        client = EnhancedTunnelClient("ws://test", "test-token")
        
        for i in range(5):
            client._health.consecutive_failures = i
            delay = client._calculate_reconnect_delay(FailureType.CONNECTION_REFUSED)
            assert delay == 10.0, f"Connection failure #{i} should be 10s, got {delay}s"
    
    def test_auth_failure_longer_delay(self):
        """Auth failures should use 30s delay (don't hammer on auth issues)."""
        client = EnhancedTunnelClient("ws://test", "test-token")
        
        delay = client._calculate_reconnect_delay(FailureType.AUTH_FAILURE)
        assert delay == 30.0, f"Auth failure should be 30s, got {delay}s"
    
    def test_no_exponential_backoff(self):
        """Verify that _reconnect_delay doesn't increase after failures."""
        client = EnhancedTunnelClient("ws://test", "test-token")
        initial_delay = client._reconnect_delay
        
        # Simulate multiple network failures
        for i in range(5):
            client._calculate_reconnect_delay(FailureType.NETWORK_ERROR)
            # _reconnect_delay should not change (no exponential backoff)
            assert client._reconnect_delay == initial_delay, \
                f"_reconnect_delay changed from {initial_delay} to {client._reconnect_delay} after {i+1} failures"
    
    @pytest.mark.asyncio
    async def test_wait_for_connection_timeout(self):
        """Test wait_for_connection returns False on timeout."""
        client = EnhancedTunnelClient("ws://test", "test-token")
        
        # Client starts disconnected, should timeout quickly now
        start_time = time.time()
        result = await client.wait_for_connection(timeout=0.3)
        elapsed = time.time() - start_time
        
        assert result == False, "Should return False on timeout"
        assert elapsed >= 0.3, f"Should wait at least timeout duration, waited {elapsed}s"
        assert elapsed <= 0.5, f"Should not exceed timeout much, waited {elapsed}s"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])