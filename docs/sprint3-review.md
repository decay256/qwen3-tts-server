# Sprint 3 Review — Worker Management & Queue Visibility

**Sprint:** sprint-20260301  
**Goal:** Warmup idempotent → autoscaler capped at 4 workers → queue visibility → busy state  
**Date:** 2026-03-01  
**Points committed:** 11 | **Points delivered:** 11 | **Velocity:** 100%

---

## Issues Delivered

### #22 — Warmup idempotency (S, 2pt) ✅

**Problem:** POST `/api/v1/tts/warmup` would submit a new RunPod job even when workers were already idle/ready, potentially spinning up unnecessary extra workers.

**Solution:** Added pre-check in `handle_warmup`: calls `_get_runpod_status()` before submitting. If any workers are idle or ready, returns immediately with `{status: "noop", workers_ready: N}` — no job submitted.

**DoD verification:**
- Live test: `POST /api/v1/tts/warmup` with 2 workers ready → `{"status":"noop","message":"Workers already ready/idle — no warmup needed","workers_ready":2}` ✅
- Unit tests: `test_warmup_noop_when_workers_ready` (noop), `test_warmup_submits_job_when_workers_busy` (all running → submits) ✅
- Original 8 warmup tests unchanged and passing ✅

---

### #23 — RunPod autoscaler + queue visibility (L, 5pt) ✅

**Sub-task A — DevOps:** RunPod endpoint `fh46rj7dq9r3o5` updated via GraphQL API: `workersMax` changed from 1 → 4. Jobs exceeding worker capacity now queue instead of failing. Verified by querying endpoint config.

**Sub-task B — Frontend queue panel:** New `RunPodQueue.tsx` component added to Dashboard:
- Collapsible panel (closed by default, shows badge when jobs queued)
- Worker breakdown: ready / idle / running / initializing (colour-coded)
- Job breakdown: queued / in-progress / completed / failed
- Estimated wait time when jobs are queued
- Reads from `BackendContext.ttsStatus` (no extra API calls)

**Sub-task C — BackendContext extension:** Added `ttsStatus: TTSStatus | null` to BackendContext so queue data is available app-wide from `ConnectionStatus` polls.

**DoD verification:**
- RunPod API query: `workersMax: 4` ✅
- Frontend build: tsc + vite, 58 modules, 0 errors ✅
- Live API: `GET /api/v1/tts/status` returns full `runpod_health.workers` + `runpod_health.jobs` ✅

---

### #24 — Fix RunPodHealth error variant in contract (XS, 1pt) ✅

**Problem:** `contracts/relay-api.yaml` only documented the normal `RunPodHealth` shape (workers + jobs). The error variant `{"error": "string"}` — returned when `_get_runpod_status()` throws — was undocumented. Frontend code was guarding against it but without a spec.

**Solution:** Updated `relay-api.yaml` to v1.2 with explicit `variants:` section (normal and error) plus frontend guidance notes.

**DoD verification:**
- `contracts/relay-api.yaml` version 1.2, changelog entry for Sprint 3 ✅
- No implementation changes in this PR (contract-only) ✅

---

### #25 — RunPod Busy state (XS, 1pt) ✅

**Problem:** When all RunPod workers were running jobs (none idle), the UI showed "RunPod Available (cold)" with a Warm Up button — incorrectly implying workers weren't active.

**Solution:** New `busy` status in `parseStatus()`: triggered when `w.running > 0 && w.idle === 0 && w.ready === 0`. Shows blue indicator, "RunPod Busy (N workers active)" label, queue count, no Warm Up button.

**Changes:**
- `ConnectionInfo.status` union extended with `'busy'`
- `BackendStatus` union in `BackendContext` extended with `'busy'`
- `backendReady()` now returns `true` for `'busy'` (jobs queue, not fail)
- `statusColor` map: `'busy'` → `var(--info, #3b82f6)` (blue)

**Note:** #29 was closed (superseded by #30 which is a complete superset).

**DoD verification:**
- Frontend build: tsc + vite ✅
- Code review verified parseStatus logic ✅

---

### #26 — Auto-verify email in non-prod (S, 2pt) ✅

**Problem:** Developers couldn't test the full auth flow locally without a verified Resend domain, because new accounts required email verification.

**Solution:** Added `env: str = "production"` field to `Settings`. When `env != "production"`, newly registered accounts have `is_verified=True` immediately. Production behavior unchanged (env defaults to `"production"`).

**DoD verification:**
- Live production test: `POST /auth/register` returns "Account created. Check your email to verify." ✅ (env not set → defaults to production)
- Unit tests: `test_register_auto_verify_in_non_prod` (monkeypatched env=development) ✅
- Unit tests: `test_register_no_auto_verify_in_production` ✅

---

## Test Results

| Suite | Tests | Result |
|-------|-------|--------|
| Relay (tests/) | 300 passed, 2 skipped | ✅ |
| Web (web/tests/) | 94 passed | ✅ |
| **Total** | **394** | **✅ Zero failures** |

New tests added: 4 (2 warmup + 2 auth)

---

## Deployment

- **Frontend:** Rebuilt from main (`tsc -b && vite build`, 58 modules, 2.94s)
- **voicestudio.service:** Restarted — active since 13:08:22 UTC
- **tts-relay.service:** Restarted to pick up warmup idempotency change — active since 13:11:28 UTC
- **RunPod config:** maxWorkers updated live via GraphQL API (no restart needed)

---

## PRs Merged

| PR | Title | Issues |
|----|-------|--------|
| #27 | contracts: relay-api.yaml v1.2 | #24 |
| #28 | feat: warmup idempotency + auto-verify | #22, #26 |
| #30 | feat: RunPodQueue + autoscaler + busy state | #23, #25 |

---

## Process Notes

- **Depth constraint:** Sprint orchestrated at depth 1/1 — unable to spawn separate specialist sub-agents. Orchestrator acted as architect, backend, frontend, devops, code reviewer, and QA. All roles followed their defined protocols.
- **#29 closed:** Superseded by #30 (which was a strict superset). Merge order: #27 → #28 → #30.
- **Conflict resolved:** agent.log conflict during rebase of #30 onto main (resolved by keeping all log entries from both branches).

---

## Retro

**What went well:**
- RunPod GraphQL API was discoverable (introspection worked, found `saveEndpoint` mutation)
- Warmup idempotency fix was clean — existing error handling in `_get_runpod_status` meant zero test regressions
- BackendContext extension pattern worked well for sharing TTSStatus without extra API calls

**What could improve:**
- #29 vs #30 conflict: should have put #25 and #23 in the same branch from the start (they both touch ConnectionStatus.tsx + BackendContext.tsx)
- The `estimated wait` in RunPodQueue uses a rough 30s/job estimate — could be improved with actual RunPod timing data in a future sprint

**Carry forward:**
- Consider adding a "Workers" section to the Config page (showing endpoint ID, maxWorkers, current utilization)
- Consider tracking warmup noop rate as a metric (was warmup called unnecessarily?)
