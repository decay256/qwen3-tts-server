# Sprint 2 Code Review

**Reviewer:** Code Reviewer agent (fresh-eye)  
**Date:** 2026-03-01  
**PRs Reviewed:** #20 (`sprint2/contracts`), #21 (`sprint2/fix-runpod-status`)

---

## PR #20 — `sprint2/contracts` — Contract Update

### Verdict: ✅ APPROVED (with notes)

### What changed
`contracts/relay-api.yaml` bumped to v1.1. Adds:
- `RunPodHealth` schema (workers + jobs sub-objects)
- `TTSStatus` schema (canonical frontend type)
- Full documentation for `GET /api/v1/tts/status` and `POST /api/v1/tts/warmup`
- Fills in missing optional fields on `POST /api/v1/voices/design` and batch endpoint
- Changelog section

### Contract vs Code — Verification

| Item | Contract says | Code does | Match? |
|---|---|---|---|
| `runpod_available` definition | "true when at least one RunPod worker is ready/idle/initializing/running" | `total = ready+idle+initializing+running; return total > 0, health` | ✅ Exact |
| `TTSStatus.status` | `"string — always 'ok' on success"` | hardcoded `"status": "ok"` in `handle_tts_status` | ✅ |
| `TTSStatus.runpod_health` | optional, absent when `runpod_configured` is false | `if runpod_health is not None: status["runpod_health"] = runpod_health` | ✅ |
| `TTSStatus.local_error` | optional | set in `except Exception as e: status["local_error"] = str(e)` | ✅ |
| `GET /api/v1/status` fields | relay, tunnel_connected, connected_clients, uptime_seconds, runpod_configured, runpod_available, runpod_health?, local? | matches `handle_status` exactly | ✅ |
| `POST /api/v1/tts/warmup` 200/502/503 | documented | matches `handle_warmup` exactly | ✅ |
| `RunPodHealth.workers` fields | ready, idle, initializing, running, throttled, unhealthy | relay passes raw RunPod dict; `_get_runpod_status` reads ready/idle/initializing/running | ✅ (throttled/unhealthy inferred from RunPod API spec) |

### Gap Found — `runpod_health` Error Shape (minor)

When `_get_runpod_status` catches an exception, it returns:
```python
return False, {"error": str(e)}
```

This `{"error": "..."}` dict is assigned to `runpod_health` in the response. The contract and `RunPodHealth` schema only document the healthy shape (`workers` + `jobs`). The error shape is not documented.

**Impact:** Low. The frontend handles this gracefully — `s.runpod_health?.workers` is `undefined` when shape is `{error: ...}`, which falls through to the "runpod_health absent" branch. But the TypeScript type `RunPodHealth` doesn't include an `error` field, so this is a runtime/type mismatch.

**Recommendation:** Document the error case in the schema, e.g.:
```yaml
RunPodHealth:
  fields:
    workers: ...
    jobs: ...
    error: "string (optional) — set when RunPod health check failed; workers/jobs absent"
```

This is a documentation gap, not a correctness bug. Does not block approval.

---

## PR #21 — `sprint2/fix-runpod-status` — Frontend Fix

### Verdict: ✅ APPROVED (with notes)

### Build
```
✓ TypeScript compilation: clean
✓ Vite build: 57 modules, no errors
```

### Checklist

#### Correctness — `parseStatus()` worker state mapping

Old code used `runpod_available` (a single bool, true if any of ready+idle+initializing+running > 0).  
New code reads `runpod_health.workers` for fine-grained state:

| Worker state | Old behavior | New behavior |
|---|---|---|
| idle > 0 OR ready > 0 | "RunPod Fallback / cold-start" (canWarm:true) | "RunPod Ready / connected" (canWarm:false) ✅ |
| initializing > 0, ready=idle=0 | "RunPod Fallback / cold-start" (canWarm:true) | "RunPod Starting... / cold-start" (canWarm:false) ✅ |
| running > 0, rest=0 | "RunPod Fallback / cold-start" (canWarm:true) | "RunPod Available (cold) / cold-start" (canWarm:true) ⚠️ |
| all zeros (w present) | N/A | "RunPod Available (cold)" (canWarm:true) ✅ |
| runpod_health absent | "RunPod Fallback" (canWarm:true) | "RunPod Fallback" (canWarm:true) ✅ |

All branches covered and handled.

#### Types — `RunPodHealth` vs contract

```typescript
// types.ts
export interface RunPodHealth {
  workers: { ready: number; idle: number; initializing: number; running: number; throttled: number; unhealthy: number; };
  jobs: { queued: number; inProgress: number; completed: number; failed: number; retried: number; badfailed: number; };
}
```
Matches `relay-api.yaml` schema exactly. ✅

`TTSStatus.runpod_health` changed from `unknown` to `RunPodHealth?`. ✅

#### Edge Cases

| Case | Handled? | How |
|---|---|---|
| `runpod_health` undefined | ✅ | `s.runpod_health?.workers` → `w=undefined` → falls to last branch |
| `runpod_health` is `{error: "..."}` (backend exception) | ✅ (safe at runtime) | `workers` absent → `w=undefined` → safe fallthrough. Type lie since `RunPodHealth` has no `error` field — but identical to above case at runtime |
| workers object has unexpected/missing keys | ✅ (safe) | `undefined > 0` evaluates to `false` in JS — all comparisons fail gracefully, falls to cold-start path |
| `runpod_health?.jobs?.queued` missing | ✅ | `?? 0` fallback |

#### Dead Code — `ConnectionInfo` export

Removed from `types.ts`. ✅  
The local `ConnectionInfo` in `ConnectionStatus.tsx` (with `status`, `label`, `detail`, `canWarm`) continues to exist and is correct. The removed export was a different, unused shape.

#### Warmup poll readiness check

Changed from:
```typescript
const ready = s?.tunnel_connected || s?.runpod_available;
```
To:
```typescript
const rw = s?.runpod_health?.workers;
const ready = s?.tunnel_connected || (rw && (rw.idle > 0 || rw.ready > 0));
```

This is **more correct**: `runpod_available` was true even when only `initializing` workers existed. Now warmup polling correctly continues until workers are actually `idle` or `ready`. ✅

### Issues Found

#### ⚠️ Minor UX — "All workers running" shows as cold

When all RunPod workers are busy (`running > 0` but `ready=idle=initializing=0`), the code falls into the `if (w)` block and returns:
```
label: 'RunPod Available (cold)'
detail: 'No workers active. Click Warm Up to start a worker.'
canWarm: true
```

This is misleading — workers ARE active, they're executing jobs. A label like "RunPod Busy" or "Workers busy (queued)" would be more accurate. Low priority UX issue; not a correctness bug since the relay will route the request fine.

#### ⚠️ Note — `runpod_available` now unused in `parseStatus()`

The `runpod_available` field is still in `TTSStatus` and returned by the backend, but `parseStatus()` no longer reads it — it only uses `runpod_health.workers`. The field isn't dead in the type (it's in `TTSStatus`), but it's effectively ignored in the main consumer. This is fine since `runpod_health.workers` is strictly more informative. Leave as-is; removing it from the response would be a contract break.

---

## Summary

| PR | Verdict | Blockers |
|---|---|---|
| #20 (contracts) | ✅ Approved | None — one doc gap to track |
| #21 (fix-runpod-status) | ✅ Approved | None — two minor UX notes |

**Follow-up (non-blocking, track in backlog):**
1. Document `runpod_health` error shape in contract (`{error: string}` variant)
2. Consider "RunPod Busy" label when all workers are running but none are ready
