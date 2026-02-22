"""
Enhanced tunnel client with robust connection management.

Features:
- Circuit breaker pattern for persistent failures
- Connection health scoring and monitoring
- Differentiated retry logic for auth vs connection issues
- Advanced heartbeat monitoring with stale connection detection
- Graceful degradation with progressive backoff
- Comprehensive error classification and handling
"""

import asyncio
import json
import logging
import time
from enum import Enum
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass, field

import websockets
from websockets.client import WebSocketClientProtocol
from websockets.exceptions import ConnectionClosed, ConnectionClosedError, ConnectionClosedOK

from .tunnel import TunnelMessage, MessageType  # Reuse existing message types

logger = logging.getLogger(__name__)

# Connection constants
HEARTBEAT_INTERVAL = 15  # seconds (faster detection)
HEARTBEAT_TIMEOUT = 30   # seconds
RECONNECT_BASE_DELAY = 0.5  # seconds (start faster)
RECONNECT_MAX_DELAY = 120   # seconds (longer max for persistent issues)
CONNECTION_TIMEOUT = 10     # seconds
MAX_CONSECUTIVE_FAILURES = 5  # Circuit breaker threshold
CIRCUIT_BREAKER_RECOVERY_TIME = 300  # 5 minutes

class ConnectionState(str, Enum):
    """Connection state tracking."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting" 
    CONNECTED = "connected"
    AUTHENTICATING = "authenticating"
    AUTHENTICATED = "authenticated"
    CIRCUIT_BREAKER = "circuit_breaker"  # Too many failures

class FailureType(str, Enum):
    """Types of connection failures for differentiated handling."""
    AUTH_FAILURE = "auth_failure"
    CONNECTION_REFUSED = "connection_refused"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    PROTOCOL_ERROR = "protocol_error"
    UNKNOWN = "unknown"

@dataclass
class ConnectionHealth:
    """Track connection health metrics."""
    total_attempts: int = 0
    successful_connections: int = 0
    consecutive_failures: int = 0
    last_success_time: float = 0
    last_failure_time: float = 0
    failure_types: Dict[FailureType, int] = field(default_factory=dict)
    
    @property
    def success_rate(self) -> float:
        """Connection success rate (0.0 to 1.0)."""
        if self.total_attempts == 0:
            return 0.0
        return self.successful_connections / self.total_attempts
    
    @property
    def time_since_last_success(self) -> float:
        """Seconds since last successful connection."""
        if self.last_success_time == 0:
            return float('inf')
        return time.time() - self.last_success_time
    
    def record_attempt(self) -> None:
        """Record a connection attempt."""
        self.total_attempts += 1
    
    def record_success(self) -> None:
        """Record a successful connection."""
        self.successful_connections += 1
        self.consecutive_failures = 0
        self.last_success_time = time.time()
    
    def record_failure(self, failure_type: FailureType) -> None:
        """Record a connection failure."""
        self.consecutive_failures += 1
        self.last_failure_time = time.time()
        self.failure_types[failure_type] = self.failure_types.get(failure_type, 0) + 1

class EnhancedTunnelClient:
    """Enhanced tunnel client with robust connection management."""
    
    def __init__(
        self,
        remote_url: str,
        api_key: str,
        on_message: Optional[Callable[[TunnelMessage], Any]] = None,
        ca_cert: Optional[str] = None
    ):
        self.remote_url = remote_url
        self.api_key = api_key
        self.on_message = on_message
        self.ca_cert = ca_cert
        
        self._ws: Optional[WebSocketClientProtocol] = None
        self._state = ConnectionState.DISCONNECTED
        self._running = False
        self._reconnect_delay = RECONNECT_BASE_DELAY
        self._last_heartbeat_sent: float = 0
        self._last_heartbeat_ack: float = 0
        self._connect_count: int = 0
        self._health = ConnectionHealth()
        self._circuit_breaker_until: float = 0
        
        # Tasks
        self._main_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
    
    @property
    def state(self) -> ConnectionState:
        """Current connection state."""
        return self._state
    
    @property
    def is_connected(self) -> bool:
        """Whether currently connected and authenticated."""
        return self._state == ConnectionState.AUTHENTICATED
    
    @property
    def health(self) -> ConnectionHealth:
        """Connection health metrics."""
        return self._health
    
    async def start(self) -> None:
        """Start the enhanced tunnel client."""
        if self._running:
            logger.warning("Tunnel client already running")
            return
            
        self._running = True
        logger.info("Creating connection loop task...")
        try:
            self._main_task = asyncio.create_task(self._connection_loop())
            logger.info("Enhanced tunnel client started, task created: %s", self._main_task)
        except Exception as e:
            logger.error("Failed to create connection loop task: %s", e, exc_info=True)
            self._running = False
            raise
    
    async def stop(self) -> None:
        """Stop the tunnel client gracefully."""
        self._running = False
        
        # Cancel tasks
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        if self._main_task:
            self._main_task.cancel()
            try:
                await self._main_task
            except asyncio.CancelledError:
                pass
        
        # Close connection
        if self._ws:
            await self._ws.close()
            self._ws = None
        
        self._state = ConnectionState.DISCONNECTED
        logger.info("Enhanced tunnel client stopped")
    
    async def send_message(self, message: TunnelMessage) -> None:
        """Send a message through the tunnel."""
        if not self.is_connected or not self._ws:
            raise RuntimeError("Tunnel not connected")
        
        try:
            await self._ws.send(message.to_json())
        except Exception as e:
            logger.error("Failed to send message: %s", e)
            raise
    
    async def _connection_loop(self) -> None:
        """Main connection loop with enhanced error handling."""
        logger.info("Starting connection loop to %s", self.remote_url)
        
        while self._running:
            try:
                logger.debug("Connection loop iteration, running=%s, state=%s", self._running, self._state.value)
                
                # Check circuit breaker
                if self._state == ConnectionState.CIRCUIT_BREAKER:
                    if time.time() < self._circuit_breaker_until:
                        await asyncio.sleep(min(30, self._circuit_breaker_until - time.time()))
                        continue
                    else:
                        logger.info("Circuit breaker recovery - attempting reconnection")
                        self._state = ConnectionState.DISCONNECTED
                        self._health.consecutive_failures = 0  # Reset for recovery attempt
                
                await self._connect_and_run()
                
            except asyncio.CancelledError:
                logger.info("Connection loop cancelled")
                break
            except Exception as e:
                logger.error("Connection loop exception: %s", e, exc_info=True)
                failure_type = self._classify_failure(e)
                self._handle_connection_failure(failure_type, str(e))
                
                if not self._running:
                    logger.info("Connection loop exiting (_running=False)")
                    break
                
                # Wait before reconnect with enhanced backoff
                delay = self._calculate_reconnect_delay(failure_type)
                logger.info("Reconnecting in %.1fs... (attempt %d, failure: %s)", 
                           delay, self._health.total_attempts + 1, failure_type.value)
                await asyncio.sleep(delay)
        
        logger.info("Connection loop finished, _running=%s", self._running)
    
    async def _connect_and_run(self) -> None:
        """Connect and run message loop with comprehensive error handling."""
        logger.debug("_connect_and_run starting")
        self._state = ConnectionState.CONNECTING
        self._health.record_attempt()
        
        try:
            logger.debug("Attempting WebSocket connection to %s", self.remote_url)
            # Create connection with optimized settings for fiber/LAN
            # Note: ca_cert handling would be done via ssl_context if needed
            async with websockets.connect(
                self.remote_url,
                ping_interval=HEARTBEAT_INTERVAL,
                ping_timeout=HEARTBEAT_TIMEOUT,
                close_timeout=10,
                max_queue=128,  # Larger queue for burst traffic
                compression=None,  # Disable compression for LAN performance
                open_timeout=CONNECTION_TIMEOUT
            ) as ws:
                logger.debug("WebSocket connection established")
                self._ws = ws
                self._state = ConnectionState.CONNECTED
                self._connect_count += 1
                
                # Authenticate
                await self._authenticate()
                
                # Reset backoff on successful connection
                self._reconnect_delay = RECONNECT_BASE_DELAY
                self._health.record_success()
                self._state = ConnectionState.AUTHENTICATED
                
                logger.info("Tunnel connected and authenticated (connection #%d, success rate: %.1f%%)", 
                           self._connect_count, self._health.success_rate * 100)
                
                # Start heartbeat monitoring
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                
                # Process messages
                await self._message_loop()
                
        except Exception as e:
            # Connection failed
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
            self._ws = None
            self._state = ConnectionState.DISCONNECTED
            raise  # Re-raise for main loop handling
        
        finally:
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
    
    async def _authenticate(self) -> None:
        """Authenticate with the remote server."""
        if not self._ws:
            raise RuntimeError("No WebSocket connection")
        
        self._state = ConnectionState.AUTHENTICATING
        
        # Send auth message
        auth_msg = TunnelMessage(type=MessageType.AUTH, body=self.api_key)
        await self._ws.send(auth_msg.to_json())
        
        # Wait for auth response with timeout
        try:
            response_raw = await asyncio.wait_for(self._ws.recv(), timeout=10)
            response = TunnelMessage.from_json(response_raw)
            
            if response.type == MessageType.AUTH_OK:
                logger.info("Authentication successful")
                return
            elif response.type == MessageType.AUTH_FAIL:
                error_msg = response.error or "Invalid API key"
                logger.error("Authentication failed: %s", error_msg)
                raise ConnectionRefusedError(f"Authentication failed: {error_msg}")
            else:
                raise ValueError(f"Unexpected auth response: {response.type}")
                
        except asyncio.TimeoutError:
            raise ConnectionRefusedError("Authentication timeout")
    
    async def _message_loop(self) -> None:
        """Process incoming messages."""
        if not self._ws:
            return
        
        try:
            async for raw_message in self._ws:
                try:
                    message = TunnelMessage.from_json(raw_message)
                    
                    if message.type == MessageType.HEARTBEAT:
                        # Respond to heartbeat
                        ack = TunnelMessage(type=MessageType.HEARTBEAT_ACK)
                        await self._ws.send(ack.to_json())
                        
                    elif message.type == MessageType.HEARTBEAT_ACK:
                        # Update heartbeat tracking
                        self._last_heartbeat_ack = time.time()
                        
                    elif self.on_message:
                        # Forward message to handler
                        await asyncio.create_task(self.on_message(message))
                        
                except Exception as e:
                    logger.error("Error processing message: %s", e)
                    
        except ConnectionClosed:
            logger.info("WebSocket connection closed normally")
        except Exception as e:
            logger.error("Message loop error: %s", e)
            raise
    
    async def _heartbeat_loop(self) -> None:
        """Enhanced heartbeat monitoring with stale connection detection."""
        try:
            while self._running and self.is_connected:
                current_time = time.time()
                
                # Send heartbeat
                if self._ws and current_time - self._last_heartbeat_sent >= HEARTBEAT_INTERVAL:
                    try:
                        heartbeat = TunnelMessage(type=MessageType.HEARTBEAT)
                        await self._ws.send(heartbeat.to_json())
                        self._last_heartbeat_sent = current_time
                        
                    except Exception as e:
                        logger.error("Failed to send heartbeat: %s", e)
                        break  # Will trigger reconnection
                
                # Check for stale connection
                if (self._last_heartbeat_ack > 0 and 
                    current_time - self._last_heartbeat_ack > HEARTBEAT_TIMEOUT * 2):
                    logger.warning("Stale connection detected (no heartbeat ack for %.1fs)", 
                                 current_time - self._last_heartbeat_ack)
                    break  # Will trigger reconnection
                
                await asyncio.sleep(5)  # Check every 5 seconds
                
        except asyncio.CancelledError:
            pass
    
    def _classify_failure(self, exception: Exception) -> FailureType:
        """Classify the type of connection failure for appropriate handling."""
        if isinstance(exception, ConnectionRefusedError):
            if "Authentication failed" in str(exception):
                return FailureType.AUTH_FAILURE
            return FailureType.CONNECTION_REFUSED
        elif isinstance(exception, (ConnectionClosed, ConnectionClosedError)):
            return FailureType.NETWORK_ERROR
        elif isinstance(exception, asyncio.TimeoutError):
            return FailureType.TIMEOUT
        elif isinstance(exception, (ValueError, json.JSONDecodeError)):
            return FailureType.PROTOCOL_ERROR
        else:
            return FailureType.UNKNOWN
    
    def _handle_connection_failure(self, failure_type: FailureType, error_msg: str) -> None:
        """Handle connection failure with appropriate response."""
        self._health.record_failure(failure_type)
        
        logger.error("Connection failure (type: %s, consecutive: %d): %s", 
                    failure_type.value, self._health.consecutive_failures, error_msg)
        
        # Check for circuit breaker activation
        if (self._health.consecutive_failures >= MAX_CONSECUTIVE_FAILURES and
            failure_type != FailureType.AUTH_FAILURE):  # Don't circuit break on auth issues
            
            self._state = ConnectionState.CIRCUIT_BREAKER
            self._circuit_breaker_until = time.time() + CIRCUIT_BREAKER_RECOVERY_TIME
            logger.warning("Circuit breaker activated - too many consecutive failures (%d). "
                          "Will retry after %d seconds", 
                          self._health.consecutive_failures, CIRCUIT_BREAKER_RECOVERY_TIME)
    
    def _calculate_reconnect_delay(self, failure_type: FailureType) -> float:
        """Calculate reconnect delay based on failure type and history."""
        # Auth failures: don't retry aggressively
        if failure_type == FailureType.AUTH_FAILURE:
            return min(30, RECONNECT_MAX_DELAY)
        
        # Network issues on fiber: start fast, backoff quickly
        base_delay = self._reconnect_delay
        
        # Factor in consecutive failures
        failure_multiplier = min(2 ** (self._health.consecutive_failures - 1), 8)
        
        # Calculate delay
        delay = base_delay * failure_multiplier
        
        # Update for next time (exponential backoff)
        self._reconnect_delay = min(self._reconnect_delay * 1.5, RECONNECT_MAX_DELAY)
        
        return min(delay, RECONNECT_MAX_DELAY)
    
    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive connection status."""
        return {
            "state": self._state.value,
            "connected": self.is_connected,
            "connection_count": self._connect_count,
            "health": {
                "total_attempts": self._health.total_attempts,
                "success_rate": self._health.success_rate,
                "consecutive_failures": self._health.consecutive_failures,
                "time_since_last_success": self._health.time_since_last_success,
                "failure_types": dict(self._health.failure_types)
            },
            "circuit_breaker": {
                "active": self._state == ConnectionState.CIRCUIT_BREAKER,
                "recovery_in": max(0, self._circuit_breaker_until - time.time()) if self._circuit_breaker_until else 0
            }
        }