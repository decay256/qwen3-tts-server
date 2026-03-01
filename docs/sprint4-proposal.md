# Sprint 4 Proposal: Draft Workflow & Character Templates

**Goal:** As a user, I can generate voice drafts, review them (listen, compare, annotate), and approve the best ones as permanent character templates.

**DoD:** Generate Draft on a preset → draft appears in queue → audio plays when done → Approve promotes to character template → template visible in Templates tab.

## Issues (13 points)

| # | Title | Role | Size | Points |
|---|-------|------|------|--------|
| #34 | Contract: Draft & Template API specification | Architect | S | 2 |
| #31 | Draft & Template data model + backend CRUD | Backend | M | 3 |
| #32 | Draft queue UI — central job list with status, audio, actions | Frontend | L | 5 |
| #33 | Template library view — approved templates per character | Frontend | M | 3 |

**Total: 13 points** (at capacity)

## Sprint Flow

1. **Architect** (#34) — Write `contracts/draft-api.yaml` with all endpoints, schemas, async semantics
2. **Backend** (#31) — Implement Draft + Template models, all CRUD endpoints, approve/regenerate logic
3. **Frontend** (#32 + #33) — Draft queue panel, template library tab, batch drafting
4. **Code Reviewer** — All PRs
5. **QA** — End-to-end: generate → queue → review → approve → template visible
6. **Deploy** — Rebuild + restart

## Key Design Decisions to Make (Architect)

1. **Audio storage:** Base64 in SQLite column (simple, MVP) vs file on disk with path in DB (scalable)?
2. **Async job tracking:** Poll endpoint vs WebSocket for real-time draft status?
3. **Clone prompt creation:** On approve (saves clone prompt to GPU/RunPod) or just store the reference audio?
4. **Draft retention:** Auto-discard after N days, or keep forever until manual discard?

## Dependencies
- #32 and #33 depend on #31 (backend API must exist)
- #31 depends on #34 (contract first)
- #33 can start once #31's template endpoints exist

## What This Replaces
- Current "Preview" button → "Generate Draft"
- Current "Cast" button → removed (replaced by Approve flow)
- Current "Voice Library" tab → becomes "Templates" tab showing approved templates

## Deferred to Sprint 5
- A/B comparison UI (side-by-side playback)
- Draft notes/annotations
- Batch draft progress bar
- Clone prompt auto-creation on approve (requires GPU backend)
- Undo approve (demote template back to draft)
