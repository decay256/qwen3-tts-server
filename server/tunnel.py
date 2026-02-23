"""WebSocket reverse tunnel for secure communication between local and remote servers."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

import websockets
from websockets.client import WebSocketClientProtocol
from websockets.server import WebSocketServerProtocol

from server.auth import verify_token

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 30  # seconds
RECONNECT_BASE_DELAY = 1  # seconds
RECONNECT_MAX_DELAY = 60  # seconds
MESSAGE_TIMEOUT = 300  # 5 minutes max for TTS processing


class MessageType(str, Enum):
    """WebSocket message types for the tunnel protocol."""

    AUTH = "auth"
    AUTH_OK = "auth_ok"
    AUTH_FAIL = "auth_fail"
    HEARTBEAT = "heartbeat"
    HEARTBEAT_ACK = "heartbeat_ack"
    REQUEST = "request"
    RESPONSE = "response"
    ERROR = "error"
    STATUS = "status"


@dataclass
class TunnelMessage:
    """A message sent through the tunnel."""

    type: MessageType
    request_id: Optional[str] = None
    method: Optional[str] = None
    path: Optional[str] = None
    headers: dict[str, str] = field(default_factory=dict)
    body: Optional[str] = None  # JSON string or base64 for binary
    body_binary: bool = False
    status_code: int = 200
    error: Optional[str] = None

    def to_json(self) -> str:
        """Serialize to JSON string."""
        data: dict[str, Any] = {"type": self.type.value}
        if self.request_id:
            data["request_id"] = self.request_id
        if self.method:
            data["method"] = self.method
        if self.path:
            data["path"] = self.path
        if self.headers:
            data["headers"] = self.headers
        if self.body is not None:
            data["body"] = self.body
        if self.body_binary:
            data["body_binary"] = True
        if self.status_code != 200:
            data["status_code"] = self.status_code
        if self.error:
            data["error"] = self.error
        return json.dumps(data)

    @classmethod
    def from_json(cls, raw: str) -> TunnelMessage:
        """Deserialize from JSON string."""
        data = json.loads(raw)
        return cls(
            type=MessageType(data["type"]),
            request_id=data.get("request_id"),
            method=data.get("method"),
            path=data.get("path"),
            headers=data.get("headers", {}),
            body=data.get("body"),
            body_binary=data.get("body_binary", False),
            status_code=data.get("status_code", 200),
            error=data.get("error"),
        )


# Type alias for request handler
RequestHandler = Callable[[TunnelMessage], Coroutine[Any, Any, TunnelMessage]]


class TunnelClient:
    """WebSocket tunnel client — runs on the local GPU machine.

    Connects to the remote relay server and handles incoming TTS requests.
    """

    def __init__(
        self,
        remote_url: str,
        api_key: str,
        request_handler: RequestHandler,
        tls: bool = False,
        ca_cert: Optional[str] = None,
    ) -> None:
        """Initialize tunnel client.

        Args:
            remote_url: WebSocket URL of the remote relay (e.g. ws://host:port/ws/tunnel).
            api_key: API key for authentication.
            request_handler: Async function to handle incoming requests.
            tls: Whether to use TLS.
            ca_cert: Path to CA certificate for TLS verification.
        """
        self.remote_url = remote_url
        self.api_key = api_key
        self.request_handler = request_handler
        self.tls = tls
        self.ca_cert = ca_cert

        self._ws: Optional[WebSocketClientProtocol] = None
        self._running = False
        self._connected = False
        self._reconnect_delay = RECONNECT_BASE_DELAY
        self._last_heartbeat: float = 0
        self._connect_count: int = 0

    @property
    def is_connected(self) -> bool:
        """Whether currently connected to remote."""
        return self._connected

    async def start(self) -> None:
        """Start the tunnel client with auto-reconnect."""
        self._running = True
        logger.info("Starting tunnel client, connecting to %s", self.remote_url)

        while self._running:
            try:
                await self._connect_and_run()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Tunnel connection error")

            if not self._running:
                break

            # Exponential backoff reconnect
            logger.info("Reconnecting in %.1fs...", self._reconnect_delay)
            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, RECONNECT_MAX_DELAY)

    async def stop(self) -> None:
        """Stop the tunnel client."""
        self._running = False
        if self._ws:
            await self._ws.close()
        logger.info("Tunnel client stopped")

    async def _connect_and_run(self) -> None:
        """Connect to remote and process messages."""
        import ssl

        ssl_context = None
        if self.tls:
            ssl_context = ssl.create_default_context()
            if self.ca_cert:
                ssl_context.load_verify_locations(self.ca_cert)

        async with websockets.connect(
            self.remote_url,
            ssl=ssl_context,
            ping_interval=HEARTBEAT_INTERVAL,
            ping_timeout=HEARTBEAT_INTERVAL * 2,
            max_size=50 * 1024 * 1024,  # 50MB max message (for audio)
        ) as ws:
            self._ws = ws
            self._connect_count += 1

            # Authenticate
            auth_msg = TunnelMessage(type=MessageType.AUTH, body=self.api_key)
            await ws.send(auth_msg.to_json())

            response = await asyncio.wait_for(ws.recv(), timeout=10)
            resp_msg = TunnelMessage.from_json(response)

            if resp_msg.type != MessageType.AUTH_OK:
                logger.error("Authentication failed: %s", resp_msg.error)
                raise ConnectionRefusedError("Authentication failed")

            self._connected = True
            self._reconnect_delay = RECONNECT_BASE_DELAY
            logger.info("Tunnel connected and authenticated (connection #%d)", self._connect_count)

            # Start heartbeat task
            heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws))

            try:
                async for raw_message in ws:
                    try:
                        msg = TunnelMessage.from_json(raw_message)
                        if msg.type == MessageType.HEARTBEAT_ACK:
                            continue
                        if msg.type == MessageType.REQUEST:
                            asyncio.create_task(self._handle_request(ws, msg))
                        else:
                            logger.warning("Unexpected message type: %s", msg.type)
                    except json.JSONDecodeError:
                        logger.error("Invalid JSON message received")
            finally:
                heartbeat_task.cancel()
                self._connected = False

    async def _heartbeat_loop(self, ws: WebSocketClientProtocol) -> None:
        """Send periodic heartbeats."""
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                msg = TunnelMessage(type=MessageType.HEARTBEAT)
                await ws.send(msg.to_json())
                self._last_heartbeat = time.time()
            except Exception:
                break

    async def _handle_request(
        self, ws: WebSocketClientProtocol, request: TunnelMessage
    ) -> None:
        """Handle an incoming request from the remote relay."""
        try:
            response = await asyncio.wait_for(
                self.request_handler(request), timeout=MESSAGE_TIMEOUT
            )
            response.request_id = request.request_id
            await ws.send(response.to_json())
        except asyncio.TimeoutError:
            error_resp = TunnelMessage(
                type=MessageType.ERROR,
                request_id=request.request_id,
                error="Request timed out",
                status_code=504,
            )
            await ws.send(error_resp.to_json())
        except Exception as e:
            logger.exception("Error handling request %s", request.request_id)
            error_resp = TunnelMessage(
                type=MessageType.ERROR,
                request_id=request.request_id,
                error=str(e),
                status_code=500,
            )
            await ws.send(error_resp.to_json())


class TunnelServer:
    """WebSocket tunnel server — runs on the remote relay.

    Accepts connections from local GPU machines and forwards API requests.
    """

    def __init__(self) -> None:
        """Initialize tunnel server."""
        self._clients: dict[str, WebSocketServerProtocol] = {}
        self._pending_requests: dict[str, asyncio.Future] = {}
        self._client_counter = 0

    @property
    def connected_clients(self) -> int:
        """Number of connected tunnel clients."""
        return len(self._clients)

    @property
    def has_client(self) -> bool:
        """Whether at least one client is connected."""
        return len(self._clients) > 0

    async def handle_connection(self, websocket: WebSocketServerProtocol) -> None:
        """Handle a new WebSocket connection from a local machine.

        Args:
            websocket: The WebSocket connection.
        """
        client_id = None
        try:
            # Wait for authentication
            raw = await asyncio.wait_for(websocket.recv(), timeout=10)
            msg = TunnelMessage.from_json(raw)

            if msg.type != MessageType.AUTH:
                await websocket.close(4001, "Expected auth message")
                return

            if not verify_token(msg.body or ""):
                fail = TunnelMessage(type=MessageType.AUTH_FAIL, error="Invalid API key")
                await websocket.send(fail.to_json())
                await websocket.close(4003, "Authentication failed")
                logger.warning("Tunnel auth failed from %s", websocket.remote_address)
                return

            # Authenticated — kick any existing clients (only one GPU at a time)
            if self._clients:
                for old_id, old_ws in list(self._clients.items()):
                    logger.warning("Kicking stale client %s to make room for new connection", old_id)
                    try:
                        await old_ws.close(4001, "Replaced by new connection")
                    except Exception:
                        pass
                    # Cancel any pending requests on the old connection
                    for req_id, future in list(self._pending_requests.items()):
                        if not future.done():
                            future.set_exception(ConnectionError("Tunnel client replaced"))
                    self._pending_requests.clear()
                self._clients.clear()

            self._client_counter += 1
            client_id = f"client_{self._client_counter}"
            self._clients[client_id] = websocket

            ok = TunnelMessage(type=MessageType.AUTH_OK)
            await websocket.send(ok.to_json())
            logger.info("Tunnel client connected: %s from %s", client_id, websocket.remote_address)

            # Process messages from client (responses to our requests)
            async for raw_message in websocket:
                try:
                    msg = TunnelMessage.from_json(raw_message)
                    if msg.type == MessageType.HEARTBEAT:
                        ack = TunnelMessage(type=MessageType.HEARTBEAT_ACK)
                        await websocket.send(ack.to_json())
                    elif msg.type in (MessageType.RESPONSE, MessageType.ERROR):
                        # Route response to waiting future
                        logger.debug(f"Received response: request_id={msg.request_id}, type={msg.type}")
                        if msg.request_id and msg.request_id in self._pending_requests:
                            logger.debug(f"Setting future result for request {msg.request_id}")
                            self._pending_requests[msg.request_id].set_result(msg)
                        else:
                            logger.error(f"No pending request for {msg.request_id}, pending: {list(self._pending_requests.keys())}")
                    else:
                        logger.debug("Ignoring message type %s from client", msg.type)
                except json.JSONDecodeError:
                    logger.error("Invalid JSON from tunnel client")

        except asyncio.TimeoutError:
            logger.warning("Tunnel client timed out during auth")
        except websockets.exceptions.ConnectionClosed:
            logger.info("Tunnel client disconnected: %s", client_id or "unknown")
        except Exception:
            logger.exception("Error in tunnel connection handler")
        finally:
            if client_id and client_id in self._clients:
                del self._clients[client_id]
                logger.info("Removed tunnel client: %s (%d remaining)", client_id, len(self._clients))

    async def send_request(
        self,
        method: str,
        path: str,
        headers: Optional[dict[str, str]] = None,
        body: Optional[str] = None,
        body_binary: bool = False,
        timeout: float = MESSAGE_TIMEOUT,
    ) -> TunnelMessage:
        """Send a request through the tunnel to the local machine.

        Args:
            method: HTTP method.
            path: Request path.
            headers: Optional headers.
            body: Request body (JSON string or base64).
            body_binary: Whether body is base64-encoded binary.
            timeout: Response timeout in seconds.

        Returns:
            Response TunnelMessage.

        Raises:
            ConnectionError: If no client is connected.
            TimeoutError: If response times out.
        """
        if not self._clients:
            raise ConnectionError("No tunnel client connected")

        # Use first available client
        client_id = next(iter(self._clients))
        ws = self._clients[client_id]

        request_id = f"req_{int(time.time() * 1000)}_{id(ws) % 10000}"

        request = TunnelMessage(
            type=MessageType.REQUEST,
            request_id=request_id,
            method=method,
            path=path,
            headers=headers or {},
            body=body,
            body_binary=body_binary,
        )

        # Create future for response
        future: asyncio.Future[TunnelMessage] = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        try:
            logger.debug(f"Sending request {request_id}: {method} {path}")
            await ws.send(request.to_json())
            logger.debug(f"Waiting for response to request {request_id}")
            response = await asyncio.wait_for(future, timeout=timeout)
            logger.debug(f"Received response for request {request_id}")
            return response
        except asyncio.TimeoutError:
            raise TimeoutError(f"Request {request_id} timed out after {timeout}s")
        except ConnectionError as e:
            # WebSocket connection failed - remove the client
            if client_id in self._clients:
                del self._clients[client_id]
                logger.warning(f"Removed failed tunnel client: {client_id}")
            raise ConnectionError(f"Tunnel connection failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error sending request: {e}")
            raise ConnectionError(f"Request failed: {e}")
        finally:
            self._pending_requests.pop(request_id, None)
