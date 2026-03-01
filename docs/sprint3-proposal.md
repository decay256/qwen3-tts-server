# Sprint 3 Proposal: Worker Management & Queue Visibility

**Goal:** As a user, I can see RunPod worker/job state, warm up without spawning duplicate workers, and manage queue overflow with up to 4 workers.

**DoD:** Warm Up is idempotent → autoscaler capped at 4 → jobs page shows queue state → busy workers show correct status.

## Issues (11 points)

| # | Title | Role | Size | Points |
|---|-------|------|------|--------|
| #22 | Warmup no-op when workers already ready | Backend + Frontend | S | 2 |
| #23 | Autoscaler: cap 4 workers, queue overflow, job visibility | DevOps + Frontend + Backend | L | 5 |
| #24 | Fix RunPodHealth error variant in contract | Architect | XS | 1 |
| #25 | Show 'RunPod Busy' when all workers running, none idle | Frontend | XS | 1 |
| #26 | Auto-verify email on registration in non-prod | Backend | S | 2 |

**Total: 11 points** (under 13pt capacity)

## Sprint Flow

1. **Architect** (#24) — Update contract with error variant
2. **DevOps** (#23 partial) — Configure RunPod max workers = 4
3. **Backend** (#22, #23 partial, #26) — Warmup idempotency check, job tracking endpoint, auto-verify
4. **Frontend** (#23 partial, #25) — Jobs/queue page, RunPod Busy state
5. **Code Reviewer** — All PRs
6. **QA** — End-to-end: warmup idempotent, queue visible, busy state correct

## Dependencies
- #25 is independent (can start immediately)
- #22 backend fix is independent
- #23 frontend depends on #23 backend (job tracking endpoint)
- #26 is independent
