# Tunnel Restart Procedure

## Problem

When the local server (charybdis) is stopped with Ctrl+C, the relay (droplet) keeps a stale tunnel listener. The tunnel shows as "connected" but API calls fail with connection errors.

## Solution

When restarting the local server, **always restart the relay too**:

### On Droplet (relay side):
```bash
# Kill stale relay
ps aux | grep remote_relay | grep -v grep | awk '{print $2}' | xargs -r kill -9
sleep 2

# Restart relay
cd qwen3-tts-server
nohup python3 -m server.remote_relay > /tmp/relay.log 2>&1 &
```

### On Charybdis (local server):
```bash
# Start local server
cd qwen3-tts-server  
python -m server.main
```

### Check Connection:
```bash
curl -s -H "Authorization: Bearer $API_KEY" http://104.248.27.154:9800/api/v1/status
# Should show: "tunnel_connected": true
```

## Root Cause

The tunnel connection isn't properly cleaned up on disconnection. The relay should detect dropped connections and reset its state, but currently doesn't.

## Future Fix

Add proper connection state management and auto-reconnection to the relay code.