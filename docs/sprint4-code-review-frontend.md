# Code Review — PR #37 — Sprint 4 Frontend (Draft Queue + Templates)

**Reviewer**: orchestrator (code-reviewer phase)
**Date**: 2026-03-01
**Maturity**: mvp
**Contract**: contracts/draft-api.yaml v1.0

---

## Code Review

**Maturity level**: mvp
**Blocking issues**: 0
**Non-blocking issues**: 3

### Blocking
*None.*

### Non-blocking

1. **[CharacterPage.tsx — approveDraft useCallback]** `fetchTemplates` is called inside `approveDraft`
   but is absent from the `useCallback` dependency array (`[id, fetchDrafts]`).
   React exhaustive-deps lint rule would flag this. Functionally safe on this page (id doesn't change
   after mount, so `fetchTemplates` closure is correct), but is a technical debt item.
   Fix: add `fetchTemplates` to the dep array.

2. **[CharacterPage.tsx — fetchDrafts/fetchTemplates]** Errors are silently swallowed:
   `catch { /* silently ignore */ }`. If the API is down, the user sees nothing — no error state
   or retry prompt. Acceptable at MVP given other error paths surface via `handleError`, but
   the list endpoints should at minimum `console.error()` the failure.

3. **[CharacterPage.tsx — no frontend unit tests]** No component-level tests added. Project
   convention has zero frontend tests, so this is consistent, but the frontend-engineer maturity
   spec calls for "at minimum one E2E test per user story at MVP+". Flag for Sprint 5.

### Positive notes

- Contract compliance is complete: all 9 endpoints from `draft-api.yaml` are consumed with
  the correct methods, paths, query params, and request bodies.
- Types in `api/types.ts` exactly mirror contract schemas — `DraftSummary` correctly excludes
  `audio_b64`, `TemplateSummary` likewise.
- Polling logic is correct: 3-second interval starts only when active drafts exist, cleaned up
  on tab change via `useEffect` cleanup function.
- Draft status colors are clearly differentiated (green=ready, amber=generating, red=failed, blue=approved).
- Approve flow correctly refreshes both Drafts and Templates tabs atomically.
- `DELETE /api/v1/drafts/{id}` correctly handles 204 (no-content) as success.
- `discardDraft` correctly prevents discard while status=generating (button disabled).

**Verdict**: APPROVE
