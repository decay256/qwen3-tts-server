"""
Comprehensive tests for enhanced tunnel client.

Tests cover:
- Connection establishment and authentication
- Heartbeat monitoring and stale connection detection  
- Circuit breaker functionality
- Different failure types and retry logic
- Message sending and receiving
- Health monitoring and metrics
- Graceful shutdown
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from websockets.exceptions import ConnectionClosed, ConnectionClosedError

from server.tunnel_v2 import (
    EnhancedTunnelClient, 
    ConnectionState, 
    FailureType,
    ConnectionHealth,
    HEARTBEAT_INTERVAL,
    HEARTBEAT_TIMEOUT,
    MAX_CONSECUTIVE_FAILURES
)
from server.tunnel import TunnelMessage, MessageType


class TestConnectionHealth:
    """Test connection health tracking."""
    
    def test_initial_state(self):
        health = ConnectionHealth()
        assert health.total_attempts == 0
        assert health.successful_connections == 0 
        assert health.consecutive_failures == 0
        assert health.success_rate == 0.0
        assert health.time_since_last_success == float('inf')
    
    def test_record_attempt(self):
        health = ConnectionHealth()
        health.record_attempt()
        assert health.total_attempts == 1
    
    def test_record_success(self):
        health = ConnectionHealth()
        health.consecutive_failures = 3
        health.record_success()
        
        assert health.successful_connections == 1
        assert health.consecutive_failures == 0
        assert health.last_success_time > 0
        assert health.time_since_last_success < 1  # Just recorded
    
    def test_record_failure(self):
        health = ConnectionHealth()
        health.record_failure(FailureType.NETWORK_ERROR)
        
        assert health.consecutive_failures == 1
        assert health.last_failure_time > 0
        assert health.failure_types[FailureType.NETWORK_ERROR] == 1
    
    def test_success_rate_calculation(self):
        health = ConnectionHealth()
        
        # No attempts
        assert health.success_rate == 0.0
        
        # 50% success rate
        health.total_attempts = 4
        health.successful_connections = 2
        assert health.success_rate == 0.5
        
        # 100% success rate
        health.successful_connections = 4
        assert health.success_rate == 1.0


class TestEnhancedTunnelClient:
    """Test enhanced tunnel client functionality."""
    
    @pytest.fixture
    def client(self):
        """Create test tunnel client."""
        return EnhancedTunnelClient(
            remote_url="ws://test.example.com/tunnel",
            api_key="test-api-key"
        )
    
    @pytest.fixture
    def mock_websocket(self):
        """Mock WebSocket connection."""
        ws = AsyncMock()
        ws.send = AsyncMock()
        ws.recv = AsyncMock()
        ws.close = AsyncMock()
        return ws
    
    def test_initial_state(self, client):
        assert client.state == ConnectionState.DISCONNECTED
        assert not client.is_connected
        assert client.health.total_attempts == 0
    
    @pytest.mark.asyncio
    async def test_successful_connection_and_auth(self, client, mock_websocket):
        """Test successful connection and authentication flow."""
        # Mock successful auth response
        auth_response = TunnelMessage(type=MessageType.AUTH_OK)
        mock_websocket.recv.return_value = auth_response.to_json()
        
        with patch('websockets.connect', return_value=mock_websocket) as mock_connect:
            # Make the context manager work
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_websocket)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            
            # Start connection (will authenticate but then message loop will end)
            task = asyncio.create_task(client._connect_and_run())
            
            # Give it time to connect and authenticate
            await asyncio.sleep(0.1)
            
            # Should have connected and authenticated
            assert client.state == ConnectionState.AUTHENTICATED
            
            # Should have sent auth message
            mock_websocket.send.assert_called()
            auth_call = mock_websocket.send.call_args_list[0][0][0]
            auth_msg = TunnelMessage.from_json(auth_call)
            assert auth_msg.type == MessageType.AUTH
            assert auth_msg.body == "test-api-key"
            
            # Cancel the task to clean up
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    
    @pytest.mark.asyncio
    async def test_auth_failure(self, client, mock_websocket):
        """Test authentication failure handling."""
        # Mock auth failure response
        auth_response = TunnelMessage(type=MessageType.AUTH_FAIL, error="Invalid key")
        mock_websocket.recv.return_value = auth_response.to_json()
        
        with patch('websockets.connect', return_value=mock_websocket) as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_websocket)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)
            
            with pytest.raises(ConnectionRefusedError, match="Authentication failed"):
                await client._connect_and_run()
            
            assert client.state == ConnectionState.DISCONNECTED
    
    def test_failure_classification(self, client):
        """Test failure type classification."""
        # Auth failure
        auth_error = ConnectionRefusedError("Authentication failed: Invalid key")
        assert client._classify_failure(auth_error) == FailureType.AUTH_FAILURE
        
        # Connection refused
        conn_error = ConnectionRefusedError("Connection refused")
        assert client._classify_failure(conn_error) == FailureType.CONNECTION_REFUSED
        
        # Network error
        net_error = ConnectionClosed(None, None)
        assert client._classify_failure(net_error) == FailureType.NETWORK_ERROR
        
        # Timeout
        timeout_error = asyncio.TimeoutError()
        assert client._classify_failure(timeout_error) == FailureType.TIMEOUT
        
        # Protocol error
        protocol_error = ValueError("Bad message")
        assert client._classify_failure(protocol_error) == FailureType.PROTOCOL_ERROR
        
        # Unknown
        unknown_error = RuntimeError("Something else")
        assert client._classify_failure(unknown_error) == FailureType.UNKNOWN
    
    def test_reconnect_delay_calculation(self, client):
        """Test reconnect delay calculation logic."""
        # Auth failures should have longer delay
        auth_delay = client._calculate_reconnect_delay(FailureType.AUTH_FAILURE)
        assert auth_delay >= 30
        
        # Network failures start fast
        client._health.consecutive_failures = 1
        net_delay = client._calculate_reconnect_delay(FailureType.NETWORK_ERROR)
        assert net_delay < 5  # Should be quick for first failure
        
        # Multiple failures increase delay
        client._health.consecutive_failures = 3
        multi_delay = client._calculate_reconnect_delay(FailureType.NETWORK_ERROR)
        assert multi_delay > net_delay
    
    def test_circuit_breaker_activation(self, client):
        """Test circuit breaker activation after consecutive failures."""
        # Record multiple failures
        for _ in range(MAX_CONSECUTIVE_FAILURES):
            client._handle_connection_failure(FailureType.NETWORK_ERROR, "Test error")
        
        # Should activate circuit breaker
        assert client.state == ConnectionState.CIRCUIT_BREAKER
        assert client._circuit_breaker_until > 0
    
    def test_circuit_breaker_not_activated_for_auth_failures(self, client):
        """Test that auth failures don't trigger circuit breaker."""
        # Record multiple auth failures
        for _ in range(MAX_CONSECUTIVE_FAILURES + 2):
            client._handle_connection_failure(FailureType.AUTH_FAILURE, "Auth error")
        
        # Should NOT activate circuit breaker for auth issues
        assert client.state != ConnectionState.CIRCUIT_BREAKER
    
    @pytest.mark.asyncio 
    async def test_heartbeat_monitoring(self, client, mock_websocket):
        """Test heartbeat sending and monitoring."""
        client._ws = mock_websocket
        client._state = ConnectionState.AUTHENTICATED
        client._running = True
        
        # Start heartbeat task
        heartbeat_task = asyncio.create_task(client._heartbeat_loop())
        
        # Wait a bit for heartbeat to be sent
        await asyncio.sleep(0.1)
        
        # Should have sent heartbeat
        mock_websocket.send.assert_called()
        heartbeat_call = mock_websocket.send.call_args_list[-1][0][0]
        heartbeat_msg = TunnelMessage.from_json(heartbeat_call)
        assert heartbeat_msg.type == MessageType.HEARTBEAT
        
        # Clean up
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
    
    @pytest.mark.asyncio
    async def test_message_sending(self, client, mock_websocket):
        """Test sending messages through tunnel."""
        client._ws = mock_websocket
        client._state = ConnectionState.AUTHENTICATED
        
        test_message = TunnelMessage(type=MessageType.REQUEST, body="test data")
        await client.send_message(test_message)
        
        mock_websocket.send.assert_called_with(test_message.to_json())
    
    @pytest.mark.asyncio
    async def test_message_sending_when_disconnected(self, client):
        """Test error when sending message while disconnected.""" 
        with pytest.raises(RuntimeError, match="Tunnel not connected"):
            test_message = TunnelMessage(type=MessageType.REQUEST, body="test")
            await client.send_message(test_message)
    
    @pytest.mark.asyncio
    async def test_graceful_shutdown(self, client, mock_websocket):
        """Test graceful shutdown of tunnel client."""
        client._ws = mock_websocket
        client._state = ConnectionState.AUTHENTICATED
        client._running = True
        
        # Start some tasks
        client._main_task = asyncio.create_task(asyncio.sleep(10))
        client._heartbeat_task = asyncio.create_task(asyncio.sleep(10))
        
        await client.stop()
        
        assert not client._running
        assert client.state == ConnectionState.DISCONNECTED
        assert client._main_task.cancelled()
        assert client._heartbeat_task.cancelled()
        mock_websocket.close.assert_called_once()
    
    def test_status_reporting(self, client):
        """Test comprehensive status reporting."""
        # Set up some test state
        client._connect_count = 3
        client._health.total_attempts = 5
        client._health.successful_connections = 3
        client._health.consecutive_failures = 2
        client._health.failure_types = {FailureType.NETWORK_ERROR: 1, FailureType.TIMEOUT: 1}
        client._state = ConnectionState.AUTHENTICATED
        
        status = client.get_status()
        
        assert status["state"] == "authenticated"
        assert status["connected"] == True
        assert status["connection_count"] == 3
        assert status["health"]["total_attempts"] == 5
        assert status["health"]["success_rate"] == 0.6
        assert status["health"]["consecutive_failures"] == 2
        assert status["health"]["failure_types"]["network_error"] == 1
        assert status["circuit_breaker"]["active"] == False


class TestIntegrationScenarios:
    """Integration tests for realistic failure scenarios."""
    
    @pytest.fixture
    def client(self):
        return EnhancedTunnelClient(
            remote_url="ws://test.example.com/tunnel",
            api_key="test-api-key"
        )
    
    @pytest.mark.asyncio
    async def test_connection_recovery_after_network_drop(self, client):
        """Test recovery after simulated network drop."""
        connection_attempts = []
        
        async def mock_connect(*args, **kwargs):
            connection_attempts.append(len(connection_attempts) + 1)
            if len(connection_attempts) <= 2:
                # First two attempts fail
                raise ConnectionRefusedError("Network unreachable")
            else:
                # Third attempt succeeds
                mock_ws = AsyncMock()
                auth_response = TunnelMessage(type=MessageType.AUTH_OK)
                mock_ws.recv.return_value = auth_response.to_json()
                mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
                mock_ws.__aexit__ = AsyncMock(return_value=None)
                return mock_ws
        
        with patch('websockets.connect', side_effect=mock_connect):
            # Start connection loop
            task = asyncio.create_task(client._connection_loop())
            
            # Give it time to fail twice and succeed once
            await asyncio.sleep(2.0)
            
            # Should have made 3 attempts and be connected
            assert len(connection_attempts) == 3
            assert client.health.consecutive_failures == 0  # Reset after success
            assert client.health.total_attempts == 3
            assert client.health.successful_connections == 1
            
            # Clean up
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_recovery(self, client):
        """Test circuit breaker activation and recovery."""
        failure_count = 0
        
        async def mock_connect(*args, **kwargs):
            nonlocal failure_count
            failure_count += 1
            
            if failure_count <= MAX_CONSECUTIVE_FAILURES:
                raise ConnectionRefusedError("Connection failed")
            elif failure_count == MAX_CONSECUTIVE_FAILURES + 1:
                # Still failing during circuit breaker
                raise ConnectionRefusedError("Still failing")
            else:
                # Recovery attempt succeeds
                mock_ws = AsyncMock()
                auth_response = TunnelMessage(type=MessageType.AUTH_OK)
                mock_ws.recv.return_value = auth_response.to_json()
                mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
                mock_ws.__aexit__ = AsyncMock(return_value=None)
                return mock_ws
        
        with patch('websockets.connect', side_effect=mock_connect):
            # Speed up circuit breaker for testing
            import server.tunnel_v2
            original_recovery_time = server.tunnel_v2.CIRCUIT_BREAKER_RECOVERY_TIME
            server.tunnel_v2.CIRCUIT_BREAKER_RECOVERY_TIME = 0.5
            
            try:
                task = asyncio.create_task(client._connection_loop())
                
                # Wait for circuit breaker activation
                while client.state != ConnectionState.CIRCUIT_BREAKER:
                    await asyncio.sleep(0.1)
                
                assert client.state == ConnectionState.CIRCUIT_BREAKER
                
                # Wait for recovery
                await asyncio.sleep(1.0)
                
                # Should have attempted recovery
                assert failure_count > MAX_CONSECUTIVE_FAILURES
                
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                    
            finally:
                server.tunnel_v2.CIRCUIT_BREAKER_RECOVERY_TIME = original_recovery_time


# Fixtures and test configuration
@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])