# Sprint 4 Review: Draft Workflow & Character Templates

**Date**: 2026-03-01
**Sprint goal**: As a user, I can generate voice drafts, review them (listen, compare, annotate), and approve the best ones as permanent character templates.
**DoD**: Generate Draft on a preset → draft appears in queue → audio plays when done → Approve promotes to character template → template visible in Templates tab.

---

## Results

| # | Title | Role | Points | Status |
|---|-------|------|--------|--------|
| #34 | Contract: Draft & Template API specification | Architect | 2 | ✅ Done |
| #31 | Draft & Template data model + backend CRUD | Backend | 3 | ✅ Done |
| #32 | Draft queue UI | Frontend | 5 | ✅ Done |
| #33 | Template library view | Frontend | 3 | ✅ Done |

**Total delivered: 13 / 13 points (100%)**

---

## PRs Merged

| PR | Title | Issues |
|----|-------|--------|
| #35 | feat: Draft & Template API contract | #34 |
| #36 | feat: Draft + Template backend CRUD | #31 |
| #37 | feat: Draft queue UI + Template library view | #32, #33 |

---

## What Was Built

### Backend (PR #36)
- `Draft` and `Template` SQLAlchemy models with full CRUD
- 9 REST endpoints per `contracts/draft-api.yaml`:
  - POST /api/v1/drafts (creates draft, kicks off background TTS generation)
  - GET /api/v1/drafts (list, no audio_b64)
  - GET /api/v1/drafts/{id} (full, with audio_b64)
  - DELETE /api/v1/drafts/{id}
  - POST /api/v1/drafts/{id}/approve (creates Template, sets draft status=approved)
  - POST /api/v1/drafts/{id}/regenerate
  - GET /api/v1/templates, GET /api/v1/templates/{id}
  - PATCH /api/v1/templates/{id} (rename)
  - DELETE /api/v1/templates/{id}
- Background task: status transitions pending → generating → ready/failed
- 32 new tests (126 total)

### Frontend (PR #37)
- **Drafts tab** in CharacterPage: queue view with status badges, 3-second polling while
  active, color-coded border-left (green=ready, amber=generating, red=failed, blue=approved),
  play audio on demand, approve, discard
- **Templates tab**: grid of approved templates per character, play/rename/delete
- **📝 Draft button** on each preset row — queues generation, auto-navigates to Drafts tab
- Tab badges: count bubble + animated amber dot when generation is active
- 443 lines added to CharacterPage.tsx, 53 types, 229 CSS lines

### Contract (PR #35)
- `contracts/draft-api.yaml` v1.0 with full schema, endpoint spec, and design decision rationale

---

## QA Verification Results

| Test | Endpoint | Expected | Actual | Result |
|------|----------|----------|--------|--------|
| TC-01 | POST /api/v1/drafts | 201, status=pending, no audio_b64 | ✓ | PASS |
| TC-02 | GET /api/v1/drafts | 200, list excludes audio_b64 | ✓ | PASS |
| TC-03 | GET /api/v1/drafts/{id} | 200, status=failed (no GPU) | ✓ | PASS |
| TC-04 | DELETE /api/v1/drafts/{id} | 204 | ✓ | PASS |
| TC-05 | GET /api/v1/templates | 200, empty list | ✓ | PASS |
| TC-06 | POST /api/v1/drafts missing intensity | 400 | ✓ | PASS |
| TC-07 | POST /api/v1/drafts/{id}/approve (failed draft) | 400 correct error | ✓ | PASS |
| TC-08 | Background status transitions (pending→generating→failed) | ✓ | PASS |

Note: Approve→Template flow (TC-09) was not tested end-to-end because RunPod GPU is not active
in this environment. The approve endpoint logic is covered by backend unit tests (#36).

---

## Test Counts

| Suite | Before | After | Delta |
|-------|--------|-------|-------|
| Backend (web/tests/) | 94 | 126 | +32 |
| Frontend unit tests | 0 | 0 | 0 (flagged for Sprint 5) |

---

## Code Review Findings

**PR #35 (contract)**: 0 blocking. Bulk-discard endpoint not defined (acceptable deferral).
**PR #36 (backend)**: 0 blocking. Minor: models/ in .gitignore needs cleanup (future ticket).
**PR #37 (frontend)**: 0 blocking. 3 non-blocking:
  - `approveDraft` useCallback missing `fetchTemplates` in dep array (React lint)
  - Silent error swallowing in fetchDrafts/fetchTemplates list endpoints
  - No frontend unit tests (consistent with project convention; flag for Sprint 5)

---

## Deploy

- Frontend rebuilt: 58 modules, 2.88s, 0 errors
- `voicestudio.service` restarted
- Serving from `main@6153b1f`

---

## Deferred to Sprint 5

- End-to-end approve flow (requires GPU active in test environment)
- Frontend unit tests
- Fix `approveDraft` useCallback dependency array
- Clone-prompt auto-creation on approve (GPU backend)
- A/B comparison UI
- Bulk discard endpoint
- Draft notes/annotations
- Auto-expire drafts option

---

## Retrospective

**What went well:**
- Contract-first design paid off — backend and frontend integration was zero-friction
- Background task / polling model works cleanly at MVP level
- Sprint was delivered 100% despite orchestrator timeout mid-sprint (recovery via resume)

**What went wrong:**
- Previous orchestrator timed out mid-sprint (frontend work was uncommitted)
- Recovery worked but required manual resume orchestrator intervention

**Action items:**
- Sprint 5: Add frontend unit tests for DraftQueue and Templates components
- Sprint 5: Run QA with GPU active to test full approve → template flow
- Sprint 5: Fix useCallback dependency array lint warnings
