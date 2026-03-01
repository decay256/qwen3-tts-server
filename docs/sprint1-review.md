# Sprint 1 Review: RunPod Preview Rendering

**Date:** 2026-03-01
**Sprint Goal:** As a user, I can go to the frontend and run a preview rendering for a character.
**Verdict:** ✅ **DoD MET**

---

## Issues Delivered

| # | Title | Points | Status |
|---|-------|--------|--------|
| #10 | Verify & fix preview via RunPod (full path) | 3 | ✅ Merged (PR #15) |
| #11 | Verify RunPod handler serves VoiceDesign | 2 | ✅ Merged (PR #15) |
| #12 | Handle cold start gracefully in frontend | 3 | ✅ Merged (PR #14) |
| #13 | E2E QA validation | 3 | ✅ Closed |

**Velocity:** 11/13 points delivered (QA was 2 points of validation, not implementation)

## What Was Built

### PR #14 — Cold-Start UX
- Elapsed timer with pulsing dot animation on generating preset row
- Cold-start detection: amber warning after 15s
- 180s hard timeout with Retry button
- Cancel button for user-initiated abort
- Proper cleanup on unmount (useEffect + stopGeneration)
- Mobile responsive CSS

### PR #15 — E2E Proxy Fix
- `DesignRequest` Pydantic model extended with `create_prompt`, `prompt_name`, `tags`
- `exclude_none=True` keeps preview payloads clean
- 8 new E2E proxy chain tests

## E2E Verification

Full chain tested: Login → List characters → TTS status → Preview rendering → Cast with prompt fields.
- Preview returns 188KB valid WAV audio via RunPod
- Cast request returns 200 (was 500 before fix)
- RunPod available with 1 idle worker

## Process Violations & Lessons

This sprint exposed process gaps that have been fixed:

1. **Sprint proposal only in chat** — lost on context compaction. Fixed: proposals now persisted to `docs/sprint-N-proposal.md`
2. **Architect skipped** — ran post-hoc instead. Fixed: ORCHESTRATION.md now mandates architect on every sprint
3. **Code reviewer skipped initially** — orchestrator was going to self-merge. Fixed: hard rule against self-merges
4. **Sprint review not written** — was about to close without one. Fixed: mandatory sprint review document

All enforcement rules added to `ORCHESTRATION.md` and `AGENTS.md`.

## Bugs Found

- **B1 (fixed):** `DesignRequest` silently dropping cast fields (Pydantic `extra="ignore"` default)
- **B2 (fixed):** No timer cleanup on component unmount
- **B3 (noted):** `relay-api.yaml` contract doesn't document `create_prompt`/`prompt_name`/`tags` — needs update
- **B4 (noted):** QA task spec had wrong API paths — docs need updating

## Metrics

| Metric | Value |
|--------|-------|
| Agents spawned | 7 (2 backend, 2 frontend, 1 architect, 2 code reviewer, 1 QA) |
| PRs opened | 2 (#14, #15) |
| PRs merged | 2 |
| Tests added | 8 (e2e proxy chain) |
| Total tests | 317+ (234 server + 83 web) |
| Review cycles | 2 (PR #14 needed fix for unmount cleanup) |

## Recommendations for Sprint 2

1. Update `contracts/relay-api.yaml` with optional design fields
2. Add browser automation E2E tests (Playwright)
3. Fix QA task templates with correct API paths
4. Consider: warm-up button still only calls status endpoint — separate issue?
