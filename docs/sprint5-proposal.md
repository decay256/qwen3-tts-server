# Sprint 5 Proposal: Draft-Centric UX Overhaul

**Goal:** As a user, presets are my drafting tools — clicking Draft queues a job visible in the draft list, where I review, retry, or approve into templates. Status is always visible in the navbar.

**DoD:** Click Draft on preset → draft appears immediately in list → audio plays when done → Retry on error → Approve to template. Status bar in navbar polls every 3s. No Preview/Cast/Reset buttons remain.

## Issues (11 points)

| # | Title | Role | Size | Points |
|---|-------|------|------|--------|
| #38 | Draft-centric UX overhaul (all items) | Frontend + Backend | L | 5 |
| new | Move ConnectionStatus to navbar + 3s polling | Frontend | M | 3 |
| new | Debug & fix Draft 405 error | Backend + Frontend | S | 2 |
| new | Contract: update for removed endpoints/buttons | Architect | XS | 1 |

**Total: 11 points**

## Sprint Flow

1. **Architect** — Update contracts (remove cast references, document draft-as-queue semantics)
2. **Backend** — Debug 405 (may be frontend-only), ensure regenerate endpoint works
3. **Frontend** — The big one:
   - Remove Preview, Cast & Save, Override & Save, Reset from preset rows
   - Keep only Draft button
   - Draft list auto-loads on page open, polls 3s when active
   - Each Draft click = new draft entry (no overwrite)
   - Retry button on failed drafts
   - Remove Voice Library tab
   - Move ConnectionStatus to Layout navbar
   - Status polls every 3s
   - Queue counter refreshes globally
4. **Code Reviewer** — All PRs
5. **QA** — Full flow: Draft → queue → audio → retry → approve → template
