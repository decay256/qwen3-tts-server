# Sprint 2 Proposal: Fix RunPod Status & Connection UX

**Goal:** As a user, I can see accurate GPU status (cold/warming/ready), warm up RunPod, and confirm preview rendering works end-to-end in the browser.

**DoD:** Open character page → status shows correct state → click Warm Up → status transitions to green "Ready" → click Preview → hear audio in the player.

## Issues (11 points)

| # | Title | Role | Size | Points |
|---|-------|------|------|--------|
| #16 | ConnectionStatus always shows 'RunPod Fallback' even when workers ready | Frontend | M | 3 |
| #17 | Relay status endpoint missing runpod_health worker details | Backend | S | 2 |
| #18 | Update relay-api.yaml contract: design + status + warmup endpoints | Architect | S | 2 |
| #19 | Verify Preview button shows audio player on success (browser E2E) | QA | M | 3 |

**Total: 10 points** (under 13pt capacity)

## Sprint Flow

1. **Architect** (#18) — Update contracts first (design optional fields, status response shape, warmup endpoint)
2. **Backend** (#17) — Ensure web proxy passes full `runpod_health` to frontend (may already work, needs verification)
3. **Frontend** (#16) — Rewrite `parseStatus()` to use worker counts, fix warmup polling logic
4. **Code Reviewer** — Review all PRs
5. **QA** (#19) — Browser or curl E2E: full flow from warmup → preview → audio playback

## Dependencies
- #16 depends on #17 (frontend needs worker data) and #18 (contract defines the shape)
- #19 depends on #16 and #17 being deployed
