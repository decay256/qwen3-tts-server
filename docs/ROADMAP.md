# Roadmap — Qwen3 TTS Server

## Phase 1: Stabilize (Current — Feb 2026)
**Goal:** All P0 bugs fixed, security hardened, tests reliable.

- [x] Fix P0 handler bugs (PR #1)
- [x] Fix critical security issues (PR #2)
- [x] Code review both PRs
- [ ] Address reviewer feedback, merge PRs
- [ ] Deploy v1.2.0 to RunPod + relay
- [ ] End-to-end test: relay → RunPod → audio returned
- [ ] Scale RunPod to 0, verify cold start works

## Phase 2: Test Coverage (Mar 2026)
**Goal:** All critical paths tested, mocks verified against contracts.

- [ ] RunPodClient unit tests (zero coverage today)
- [ ] Web backend route tests (auth, characters, presets, TTS proxy)
- [ ] Integration test: relay → RunPod (mocked)
- [ ] Contract verification tests (inspect.signature vs YAML)
- [ ] Fix fragile tests (hardcoded counts, timing deps)
- [ ] CI pipeline running tests on every PR

## Phase 3: Voice Studio Polish (Mar 2026)
**Goal:** Frontend usable for voice casting workflow.

- [ ] Voice library tab (browse/play/delete prompts)
- [ ] Cast workflow (select character → generate emotion matrix → preview)
- [ ] Script rendering page (paste text → assign voices → render)
- [ ] Segment-level editing (re-render individual segments)
- [ ] HTTPS subdomain + Caddy (done: tts.dk-eigenvektor.de)
- [ ] Resend for transactional email (password reset)

## Phase 4: Production Hardening (Apr 2026)
**Goal:** Reliable enough for daily audiobook rendering.

- [ ] Postgres migration (replace SQLite)
- [ ] Rate limiting on web API
- [ ] Proper CORS config
- [ ] Voice package import (multipart upload)
- [ ] Backup strategy for voice library
- [ ] Monitoring dashboard (cost, requests, latency)

## Phase 5: Multi-User (Future)
**Goal:** Other people can use Voice Studio.

- [ ] Role-based access control
- [ ] Per-user voice libraries
- [ ] Usage quotas / billing
- [ ] Public voice library (share voices)
