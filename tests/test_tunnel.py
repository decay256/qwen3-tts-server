"""Tests for tunnel protocol (TunnelMessage serialization, message types)."""

import json
import pytest


def test_tunnel_message_roundtrip():
    from server.tunnel import TunnelMessage, MessageType
    msg = TunnelMessage(
        type=MessageType.REQUEST,
        request_id="req_123",
        method="POST",
        path="/api/v1/tts/synthesize",
        headers={"Content-Type": "application/json"},
        body='{"text": "hello"}',
        status_code=200,
    )
    serialized = msg.to_json()
    restored = TunnelMessage.from_json(serialized)
    assert restored.type == MessageType.REQUEST
    assert restored.request_id == "req_123"
    assert restored.method == "POST"
    assert restored.path == "/api/v1/tts/synthesize"
    assert restored.headers == {"Content-Type": "application/json"}
    assert restored.body == '{"text": "hello"}'


def test_tunnel_message_minimal():
    from server.tunnel import TunnelMessage, MessageType
    msg = TunnelMessage(type=MessageType.HEARTBEAT)
    serialized = msg.to_json()
    data = json.loads(serialized)
    assert data == {"type": "heartbeat"}
    restored = TunnelMessage.from_json(serialized)
    assert restored.type == MessageType.HEARTBEAT
    assert restored.request_id is None
    assert restored.body is None


def test_tunnel_message_error():
    from server.tunnel import TunnelMessage, MessageType
    msg = TunnelMessage(
        type=MessageType.ERROR,
        request_id="req_456",
        error="Something failed",
        status_code=500,
    )
    serialized = msg.to_json()
    restored = TunnelMessage.from_json(serialized)
    assert restored.type == MessageType.ERROR
    assert restored.error == "Something failed"
    assert restored.status_code == 500


def test_tunnel_message_auth():
    from server.tunnel import TunnelMessage, MessageType
    msg = TunnelMessage(type=MessageType.AUTH, body="my-api-key")
    serialized = msg.to_json()
    restored = TunnelMessage.from_json(serialized)
    assert restored.type == MessageType.AUTH
    assert restored.body == "my-api-key"


def test_tunnel_message_binary_flag():
    from server.tunnel import TunnelMessage, MessageType
    msg = TunnelMessage(
        type=MessageType.RESPONSE,
        body='{"audio": "base64data"}',
        body_binary=True,
    )
    serialized = msg.to_json()
    data = json.loads(serialized)
    assert data["body_binary"] is True
    restored = TunnelMessage.from_json(serialized)
    assert restored.body_binary is True


def test_tunnel_message_default_status_code_omitted():
    from server.tunnel import TunnelMessage, MessageType
    msg = TunnelMessage(type=MessageType.RESPONSE, body="{}")
    data = json.loads(msg.to_json())
    assert "status_code" not in data  # default 200 is omitted


def test_tunnel_message_non_200_included():
    from server.tunnel import TunnelMessage, MessageType
    msg = TunnelMessage(type=MessageType.RESPONSE, status_code=404, body="{}")
    data = json.loads(msg.to_json())
    assert data["status_code"] == 404


def test_message_type_values():
    from server.tunnel import MessageType
    assert MessageType.AUTH.value == "auth"
    assert MessageType.AUTH_OK.value == "auth_ok"
    assert MessageType.AUTH_FAIL.value == "auth_fail"
    assert MessageType.HEARTBEAT.value == "heartbeat"
    assert MessageType.REQUEST.value == "request"
    assert MessageType.RESPONSE.value == "response"
    assert MessageType.ERROR.value == "error"


def test_tunnel_message_from_invalid_json():
    from server.tunnel import TunnelMessage
    with pytest.raises(json.JSONDecodeError):
        TunnelMessage.from_json("not json")


def test_tunnel_message_from_invalid_type():
    from server.tunnel import TunnelMessage
    with pytest.raises(ValueError):
        TunnelMessage.from_json('{"type": "nonexistent"}')


def test_tunnel_server_init():
    from server.tunnel import TunnelServer
    ts = TunnelServer()
    assert ts.connected_clients == 0
    assert ts.has_client is False


def test_tunnel_client_init():
    from server.tunnel import TunnelClient

    async def handler(msg):
        return msg

    client = TunnelClient(
        remote_url="ws://localhost:9999/ws/tunnel",
        api_key="test-key",
        request_handler=handler,
    )
    assert client.remote_url == "ws://localhost:9999/ws/tunnel"
    assert client.api_key == "test-key"
    assert client.is_connected is False


def test_tunnel_server_send_request_no_client():
    import asyncio
    from server.tunnel import TunnelServer

    ts = TunnelServer()
    with pytest.raises(ConnectionError):
        asyncio.get_event_loop().run_until_complete(
            ts.send_request("GET", "/test")
        )
