# Enhanced Tunnel System

## Overview

The Enhanced Tunnel System provides robust, production-ready WebSocket connectivity between the local TTS server and remote relay with advanced connection management designed for high-speed fiber/LAN environments.

## Key Features

### 🔄 **Robust Reconnection Logic**
- **Flat reconnection timing**: 10-second intervals for consistent, predictable reconnection
- **Circuit breaker pattern**: Prevents resource waste during extended outages
- **Differentiated retry logic**: Different strategies for auth failures (30s) vs network issues (10s)

### 📊 **Connection Health Monitoring**
- **Real-time metrics**: Success rates, failure types, connection stability
- **Comprehensive status**: Detailed state tracking and diagnostics  
- **Performance insights**: Connection timing and reliability statistics

### 💓 **Advanced Heartbeat System**
- **Faster detection**: 15-second heartbeat interval (vs 30s in basic version)
- **Stale connection detection**: Automatic cleanup of dead connections
- **Proactive monitoring**: Prevents silent connection failures

### 🛡️ **Circuit Breaker Protection**
- **Automatic activation**: After 5 consecutive failures
- **Recovery timing**: 5-minute recovery window with gradual re-entry
- **Resource protection**: Prevents hammering failing services

### 🎯 **Optimized for Fiber/LAN**
- **Low latency settings**: Optimized timeouts and intervals
- **High performance**: Disabled compression, larger message queues
- **Connection stability**: Enhanced error handling for high-speed networks

## Architecture

```
┌─────────────────┐    WebSocket     ┌─────────────────┐
│   Local Server  │ ◄──────────────► │  Remote Relay   │
│                 │    (Enhanced)    │                 │
│  ┌─────────────┐│                  │┌─────────────┐  │
│  │   Health    ││                  ││    Auth     │  │
│  │  Monitor    ││                  ││   Manager   │  │
│  └─────────────┘│                  │└─────────────┘  │
│  ┌─────────────┐│                  │┌─────────────┐  │
│  │  Circuit    ││                  ││  Message    │  │
│  │  Breaker    ││                  ││   Router    │  │
│  └─────────────┘│                  │└─────────────┘  │
│  ┌─────────────┐│                  │                 │
│  │ Heartbeat   ││                  │                 │
│  │  Monitor    ││                  │                 │
│  └─────────────┘│                  │                 │
└─────────────────┘                  └─────────────────┘
```

## Usage

### Basic Setup

```python
from server.tunnel_v2 import EnhancedTunnelClient

# Create client
client = EnhancedTunnelClient(
    remote_url="ws://your-relay.com/tunnel",
    api_key="your-api-key",
    on_message=handle_message
)

# Start connection
await client.start()

# Send messages
message = TunnelMessage(type=MessageType.REQUEST, body="data")
await client.send_message(message)

# Monitor status
status = client.get_status()
print(f"Connected: {status['connected']}")
print(f"Success rate: {status['health']['success_rate']:.1%}")

# Graceful shutdown
await client.stop()
```

### Message Handler

```python
async def handle_message(message: TunnelMessage):
    \"\"\"Handle incoming tunnel messages.\"\"\"
    if message.type == MessageType.REQUEST:
        # Process request
        response_data = await process_request(message.body)
        
        # Send response
        response = TunnelMessage(
            type=MessageType.RESPONSE,
            message_id=message.message_id,
            body=response_data
        )
        await client.send_message(response)
```

## Configuration

### Connection Parameters

| Parameter | Default | Fiber/LAN Optimized | Description |
|-----------|---------|-------------------|-------------|
| `HEARTBEAT_INTERVAL` | 30s | **15s** | Heartbeat frequency |
| `HEARTBEAT_TIMEOUT` | 60s | **30s** | Heartbeat timeout |
| `CONNECTION_TIMEOUT` | 30s | **10s** | Initial connection timeout |
| `RECONNECT_BASE_DELAY` | 1s | **0.5s** | Initial reconnect delay |
| `RECONNECT_MAX_DELAY` | 60s | **120s** | Maximum reconnect delay |

### Circuit Breaker Settings

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MAX_CONSECUTIVE_FAILURES` | 5 | Failures before circuit breaker |
| `CIRCUIT_BREAKER_RECOVERY_TIME` | 300s | Recovery wait time |

### WebSocket Optimization

```python
# Automatic optimizations in enhanced client:
websockets.connect(
    url,
    ping_interval=15,           # Fast heartbeat
    ping_timeout=30,            # Reasonable timeout  
    close_timeout=10,           # Quick cleanup
    max_queue=128,              # Large message queue
    compression=None,           # Disable for LAN performance
    open_timeout=10             # Fast connection attempt
)
```

## Monitoring & Status

### Health Metrics

The client tracks comprehensive health metrics:

```python
status = client.get_status()

# Connection state
print(status['state'])          # connected, disconnected, etc.
print(status['connected'])      # Boolean connection status

# Performance metrics  
health = status['health']
print(f"Success rate: {health['success_rate']:.1%}")
print(f"Total attempts: {health['total_attempts']}")
print(f"Consecutive failures: {health['consecutive_failures']}")
print(f"Time since success: {health['time_since_last_success']:.1f}s")

# Failure analysis
for failure_type, count in health['failure_types'].items():
    print(f"{failure_type}: {count} failures")

# Circuit breaker status
cb = status['circuit_breaker']
if cb['active']:
    print(f"Circuit breaker active, recovery in {cb['recovery_in']:.0f}s")
```

### Connection States

| State | Description |
|-------|-------------|
| `DISCONNECTED` | Not connected to relay |
| `CONNECTING` | Establishing WebSocket connection |
| `CONNECTED` | WebSocket connected, not authenticated |  
| `AUTHENTICATING` | Sending authentication credentials |
| `AUTHENTICATED` | Fully connected and ready |
| `CIRCUIT_BREAKER` | Too many failures, waiting for recovery |

### Failure Types

| Type | Description | Retry Strategy |
|------|-------------|----------------|
| `AUTH_FAILURE` | Invalid API key | Fixed 30s delay |
| `CONNECTION_REFUSED` | Network unreachable | Fixed 10s delay |
| `NETWORK_ERROR` | Connection dropped | Fixed 10s delay |
| `TIMEOUT` | Connection/auth timeout | Fixed 10s delay |
| `PROTOCOL_ERROR` | Message format issues | Fixed 10s delay |
| `UNKNOWN` | Other errors | Fixed 10s delay |

## Troubleshooting

### Common Issues

#### Authentication Failures
```
ERROR: Authentication failed: Invalid API key
```
**Solution**: Verify API key matches between local server config and relay AUTH_TOKEN.

#### Frequent Reconnections
```
WARNING: Stale connection detected (no heartbeat ack for 45.2s)
```
**Causes**: 
- Firewall blocking heartbeats
- Network instability
- Relay overload

**Solutions**:
- Check firewall WebSocket settings
- Monitor network stability
- Verify relay server health

#### Circuit Breaker Activation
```
WARNING: Circuit breaker activated - too many consecutive failures (5)
```
**Analysis**: Check failure types in status to identify root cause:
- Network issues: Check ISP stability
- Auth issues: Verify credentials
- Timeout issues: May indicate relay overload

### Debugging Commands

```python
# Enable debug logging
import logging
logging.getLogger('server.tunnel_v2').setLevel(logging.DEBUG)

# Monitor connection health
import asyncio
async def monitor():
    while True:
        status = client.get_status()
        print(f"State: {status['state']}, Success: {status['health']['success_rate']:.1%}")
        await asyncio.sleep(10)

# Force reconnection for testing
await client.stop()
await client.start()
```

## Performance Considerations

### Fiber/LAN Optimization

**Network Settings**:
- MTU: Use jumbo frames if supported (9000 bytes)
- TCP Window Scaling: Enable for high bandwidth-delay product
- TCP Congestion Control: BBR for fiber connections

**Application Settings**:
- Message batching for high-frequency operations
- Connection pooling for multiple concurrent streams
- Monitoring aggressive reconnection on stable networks

### Resource Usage

**Memory**: ~50KB per connection for message queues and state tracking
**CPU**: <1% for heartbeat and health monitoring
**Network**: ~100 bytes/15s for heartbeats when idle

## Migration from Basic Tunnel

### Code Changes

```python
# Old basic tunnel
from server.tunnel import TunnelClient
client = TunnelClient(url, api_key)

# New enhanced tunnel  
from server.tunnel_v2 import EnhancedTunnelClient
client = EnhancedTunnelClient(url, api_key, on_message=handler)
```

### Configuration Migration

1. **Update imports** in your server modules
2. **Add message handler** for incoming messages
3. **Update status monitoring** to use new health metrics
4. **Test circuit breaker behavior** with your failure scenarios

### Backward Compatibility

The enhanced client uses the same message protocol as the basic tunnel, ensuring compatibility with existing relay infrastructure.

## Testing

### Unit Tests
```bash
cd qwen3-tts-server
python -m pytest tests/test_tunnel_v2.py -v
```

### Integration Tests
```bash
# Test with actual relay
python -m pytest tests/test_tunnel_v2.py::TestIntegrationScenarios -v
```

### Load Testing
```bash
# Simulate connection failures
python tests/tunnel_stress_test.py --failures=high --duration=300
```

## Production Deployment

### Monitoring

Set up alerts for:
- Success rate < 95%
- Circuit breaker activations
- High failure rates
- Extended disconnection periods

### Logging

Configure structured logging:
```python
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
```

### Health Checks

Include tunnel status in application health endpoints:
```python
@app.route('/health')
def health():
    tunnel_status = client.get_status()
    return {
        'tunnel_connected': tunnel_status['connected'],
        'tunnel_health': tunnel_status['health']['success_rate'],
        'status': 'healthy' if tunnel_status['connected'] else 'degraded'
    }
```

---

## Support

For issues or questions:
1. Check troubleshooting section above
2. Review test cases for usage examples  
3. Enable debug logging for detailed diagnostics
4. Monitor health metrics for connection insights