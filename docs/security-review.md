# Security Review — Qwen3-TTS Server

**Date:** 2026-02-28  
**Reviewer:** Eigen (Security Subagent)  
**Scope:** `server/auth.py`, `server/remote_relay.py`, `server/runpod_handler.py`, `web/app/core/security.py`, `web/app/core/config.py`, `web/.env`, `Dockerfile`, `Dockerfile.slim`, `.github/workflows/docker.yml`, `.gitignore`

---

## Summary

| Severity | Count | Status |
|----------|-------|--------|
| 🔴 CRITICAL | 2 | Act immediately |
| 🟠 HIGH | 2 | Fix before next deploy |
| 🟡 MEDIUM | 4 | Fix in current sprint |
| 🔵 LOW | 3 | Backlog / hardening |

---

## 🔴 CRITICAL

### C-1: Live API Keys Committed to Workspace File

**File:** `web/.env`

The `.env` file contains real, live credentials:

```
OPENAI_API_KEY=sk-proj-lbUk6...         ← OpenAI billing key
ANTHROPIC_API_KEY=sk-ant-api03-Rj5...   ← Anthropic billing key
RESEND_API_KEY=re_WBZQUxAx_...          ← Resend email API key
TTS_RELAY_API_KEY=T6LZfkPV...           ← TTS relay bearer token
JWT_SECRET=8pyiWsNwolxiZTS...           ← JWT signing secret
```

While `web/.env` is in `.gitignore`, the file exists on disk in the OpenClaw workspace and is readable by anyone with access to this machine. If the gitignore entry is ever bypassed (force push, different git root, another tool scanning the directory), all these secrets are exposed.

**Immediate actions required:**
1. Rotate all five credentials above — treat them as compromised.
2. Confirm `web/.env` is not in any git history: `git log --all --full-history -- web/.env`
3. Store secrets in a secrets manager (Vault, GCP Secret Manager, AWS SSM) or age-encrypted vault, not plaintext files.
4. Use a `.env.example` with placeholder values for documentation.

---

### C-2: Unauthenticated Debug Endpoints Exposing Internal State

**File:** `server/remote_relay.py`, `create_app()`

```python
# Debug endpoints (no auth required — internal use)
app.router.add_get("/ws/debug", self.handle_debug_ws)
app.router.add_get("/api/v1/debug", self.handle_debug_http)
```

`handle_debug_http` returns:
- RAM usage (RSS in MB)
- Tunnel connection state
- Pending request count
- Uptime
- Last 50 debug events (which include request body sizes, method/path, timestamps, and execution metadata)

`handle_debug_ws` streams live debug events with no authentication at all.

The relay is bound to `0.0.0.0` by default, meaning these endpoints are publicly reachable on the internet. Any attacker can enumerate operational state, confirm tunnels are connected, and observe traffic patterns in real time.

**Fix:** Add `_require_auth` to both debug handlers, or restrict to localhost via a separate internal-only bind address.

---

## 🟠 HIGH

### H-1: WebSocket Tunnel Endpoint Has No Authentication

**File:** `server/remote_relay.py`, `handle_websocket_tunnel()`

```python
async def handle_websocket_tunnel(self, request: web.Request) -> web.WebSocketResponse:
    """WebSocket endpoint for tunnel connections from local GPU machines."""
    ws = web.WebSocketResponse(max_msg_size=50 * 1024 * 1024)
    await ws.prepare(request)
    # No auth check here
    adapter = AioHTTPWebSocketAdapter(ws)
    await self.tunnel_server.handle_connection(adapter)
```

Any client that can reach the relay can connect as a "GPU machine" tunnel peer. An attacker can:
- Replace the legitimate GPU backend with a malicious one
- Intercept all synthesize/clone/design traffic
- Return tampered audio or exfiltrate input text

The relay **does** authenticate inbound API calls, but the tunnel connection itself is completely open. If a malicious client connects first, all subsequent API requests are forwarded to it.

**Fix:** Require the connecting tunnel client to present the `AUTH_TOKEN` / `api_key` at connection time (e.g., via a `Authorization` WebSocket header or an initial handshake message). Reject unauthenticated connections before adding them to `TunnelServer`.

---

### H-2: RunPod Handler Skips Auth When `API_KEY` Env Var Is Unset

**File:** `server/runpod_handler.py`, `handler()`

```python
api_key = os.environ.get("API_KEY", "")
req_key = inp.get("api_key", "")
if api_key and req_key != api_key:
    return {"error": "Invalid API key"}
```

If `API_KEY` is not set in the RunPod worker environment, `api_key` is `""` which is falsy. The condition `if api_key and ...` short-circuits, and **the check is never executed** — all requests are accepted with no authentication.

This is a logic error: the intent is "reject if key mismatch", but the implementation is "only check if key is configured." Missing configuration silently degrades to no-auth.

**Fix:**
```python
api_key = os.environ.get("API_KEY", "")
req_key = inp.get("api_key", "")
if not api_key:
    return {"error": "Server misconfigured: API_KEY not set"}
if not hmac.compare_digest(req_key, api_key):
    return {"error": "Invalid API key"}
```

Also note: `inp.get("api_key")` passes the key in the request body in plaintext — this is visible in RunPod logs. Consider moving to a header or a separate auth mechanism.

---

## 🟡 MEDIUM

### M-1: No Request Body Size Limits on Synthesis/Import Endpoints

**File:** `server/remote_relay.py`

Several handlers accept unbounded request bodies:

```python
async def handle_synthesize(self, request: web.Request) -> web.Response:
    body = await request.text()  # No size limit

async def handle_import_package(self, request: web.Request) -> web.Response:
    package_data = await request.read()  # No size limit
```

The WebSocket max message size is 50 MB (`max_msg_size=50 * 1024 * 1024`), but aiohttp's REST endpoints have no configured limit. An attacker can POST gigabyte-sized bodies to exhaust memory on the relay droplet.

**Fix:** Add `client_max_size` to the aiohttp Application:
```python
app = web.Application(client_max_size=50 * 1024 * 1024)  # 50MB global cap
```
For `/api/v1/tts/synthesize`, a much smaller limit (e.g., 1 MB) is appropriate since it only accepts text JSON.

---

### M-2: Docker Images Run as Root

**Files:** `Dockerfile`, `Dockerfile.slim`

Neither Dockerfile creates or switches to a non-root user:

```dockerfile
# No USER directive anywhere
WORKDIR /app
...
CMD ["python3", "-m", "server.runpod_handler"]
```

The process runs as UID 0 inside the container. If the application is compromised (e.g., via a deserialization attack in audio processing), the attacker has root within the container, making container escape significantly easier.

**Fix:**
```dockerfile
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser
```

---

### M-3: `nvidia/cuda:devel` Base Image Increases Attack Surface

**Files:** `Dockerfile`, `Dockerfile.slim`

Both images use `nvidia/cuda:12.1.0-devel-ubuntu22.04`. The `devel` variant includes:
- Full compiler toolchain (gcc, g++, make, cmake)
- CUDA headers and static libraries
- Development tools not needed at runtime

This is ~3–4 GB of unnecessary software, each package being a potential CVE vector. The `runtime` or `runtime-cudnn` variants are appropriate for inference workloads.

**Fix:**
```dockerfile
FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04
```
Note: If `torch` compilation is needed, build in a multi-stage Dockerfile using `devel` for the build stage and `runtime` for the final image.

---

### M-4: CORS Allows Plain HTTP Origin with Credentials

**File:** `web/.env`

```
CORS_ORIGINS=["http://localhost:5173","http://104.248.27.154:8080","https://core.dk-eigenvektor.de"]
```

`http://104.248.27.154:8080` is a plain HTTP origin. If the web app sends cookies or `Authorization` headers cross-origin to this endpoint, those credentials are transmitted in cleartext and visible to any network observer. The `https://` origin is fine; the IP-based HTTP one is not.

**Fix:** Either remove the HTTP origin, put it behind HTTPS, or ensure no credentials are ever sent to it. If it's a development endpoint, keep it out of production `.env`.

---

## 🔵 LOW

### L-1: JWT Uses HS256 with Shared Secret

**File:** `web/app/core/security.py`, `web/app/core/config.py`

HS256 is a symmetric algorithm — the same secret is used to both sign and verify tokens. If the secret leaks (see C-1), an attacker can forge arbitrary tokens with any `sub` claim. There is also no server-side token revocation: refresh tokens last 30 days and cannot be invalidated once issued.

**Mitigations:**
- Already addressed if C-1 (key rotation) is done.
- Consider RS256 (asymmetric) for future hardening — private key signs, public key verifies.
- Implement a token revocation list (Redis set of revoked JTIs) for refresh tokens.
- Consider reducing refresh token expiry from 30 days to 7 days.

---

### L-2: Debug Event Log May Contain Sensitive Metadata

**File:** `server/remote_relay.py`, `debug_event()`

```python
debug_event("synth_start", body_len=len(body))
debug_event("tunnel_connect", remote=request.remote)
```

The ring buffer (`deque(maxlen=500)`) accumulates request metadata. While body content isn't logged, IP addresses and timing patterns are. Once C-2 is fixed (auth on debug endpoints), this is lower risk, but the log should still be cleared on sensitive operations and not include client IPs unnecessarily.

---

### L-3: `init()` Logs Directory Contents at Startup

**File:** `server/runpod_handler.py`

```python
logger.info("Contents: %s", os.listdir("."))
```

RunPod logs are visible to anyone with RunPod account access. Listing the working directory at startup could expose unexpected file names (voice data, config fragments, etc.) if the container is misconfigured. Remove this debug line in production.

---

## Dependency Risk Notes

| Package | Version | Risk |
|---------|---------|------|
| `python-jose` | unpinned | Has had CVEs (CVE-2024-33664 — algorithm confusion); pin to `>=3.3.0` and use only HS256/RS256 |
| `torch` | 2.5.1 | No critical CVEs at time of review; keep updated |
| `nvidia/cuda` | 12.1.0 | Ubuntu 22.04 base — receives security updates; rebuild images periodically |
| `passlib` | unpinned | Stable; bcrypt backend is sound |
| `aiohttp` | unpinned | Pin version; aiohttp has had request smuggling CVEs — use `>=3.9.0` |

---

## Recommended Fix Priority

| Priority | Item | Effort |
|----------|------|--------|
| 1 | **Rotate all credentials in `web/.env`** (C-1) | 15 min |
| 2 | **Authenticate `/ws/tunnel`** (H-1) | 2–4 hours |
| 3 | **Fix RunPod auth bypass** (H-2) | 30 min |
| 4 | **Add auth to debug endpoints** (C-2) | 30 min |
| 5 | **Add request body size limits** (M-1) | 1 hour |
| 6 | **Switch to non-root Docker user** (M-2) | 1 hour |
| 7 | **Switch to `cuda:runtime` base** (M-3) | 1–2 hours (test rebuild) |
| 8 | **Remove HTTP CORS origin** (M-4) | 5 min |
| 9 | **Pin dependency versions** (deps) | 1 hour |
| 10 | **Token revocation / JWT hardening** (L-1) | 4–8 hours |

---

## Notes on What Is Done Well

- HMAC signatures with timestamp replay protection in `auth.py` — solid design.
- `hmac.compare_digest` used consistently for constant-time comparison — no timing oracle vulnerabilities.
- Multipart audio upload validates MIME types in `handle_clone` before processing.
- `.gitignore` correctly excludes `.env` files and config YAMLs.
- `load_config()` validates that `api_key` is set and not the placeholder `"CHANGE_ME"` before starting.
- CI workflow uses `secrets.GITHUB_TOKEN` (ephemeral) rather than baking credentials into images.
