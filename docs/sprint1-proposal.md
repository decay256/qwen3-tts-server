# Sprint 1 Proposal: RunPod Preview Rendering

**Goal:** As a user, I can go to the frontend and run a preview rendering for a character.

**DoD:** User can open a character page, click Preview on any preset, and hear audio — even when RunPod is cold-starting.

**Capacity:** 13 points

| # | Title | Role | Size | Points |
|---|-------|------|------|--------|
| #10 | Verify & fix preview via RunPod (full path) | Backend + Frontend | M | 3 |
| #11 | Verify RunPod handler serves VoiceDesign | Backend | S | 2 |
| #12 | Handle cold start gracefully in frontend | Frontend | M | 3 |
| #13 | E2E QA validation | QA | M | 3 |

**Sprint flow:**
1. Backend verifies full chain (relay → RunPod) works
2. Frontend handles cold-start UX gracefully
3. QA validates end-to-end user flow
