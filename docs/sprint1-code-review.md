# Sprint 1 Code Review

**Reviewer:** code-reviewer agent  
**Date:** 2026-03-01  
**PRs reviewed:** #14 (`sprint1/cold-start-ux`), #15 (`sprint1/preview-e2e`)  
**Test suites:** all green (298 server tests, 84 web tests, frontend build clean)

---

## PR #14 — `sprint1/cold-start-ux` — Frontend cold-start UX

**Verdict: CHANGES_REQUESTED**

### What it does
Adds per-preset generation lifecycle tracking to `CharacterPage.tsx`:
- Elapsed-seconds counter displayed in a status bar below the active preset
- Cold-start hint message after 15s (GPU warming up)
- 180-second hard timeout via `AbortController`; distinguishes timeout from user cancel
- Cancel button to abort in-flight requests
- Pulsing border animation on the active `preset-row`
- Retry button on the error banner when a timeout fires (replaces the click-to-dismiss error)

Implementation uses `useRef` for mutable timer/abort handles (correct — avoids stale-closure issues) and `useCallback` for the three lifecycle helpers.

---

### Findings

#### 🔴 Major — No unmount cleanup for timers

**File:** `frontend/src/pages/CharacterPage.tsx`  
**Location:** `startGeneration`, `timerRef`, `timeoutRef`

`timerRef.current` (a `setInterval`) and `timeoutRef.current` (a `setTimeout`) are started in `startGeneration` but never cleared if the component unmounts mid-flight. If the user navigates away during a slow GPU generation:

1. The 1-second interval keeps firing.
2. `setElapsedSeconds` is called on an unmounted component — harmless in React 18 (no warning), but leaks memory for the entire 180s worst case.
3. If the component remounts quickly (route re-enter), `timerRef.current` is overwritten without clearing the old interval → **two intervals running simultaneously**.

**Fix — add a cleanup `useEffect`:**
```tsx
useEffect(() => {
  return () => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    abortCtrlRef.current?.abort();
  };
}, []);
```

---

#### 🟡 Minor — `castSingle` does not clear `preview` before starting

**File:** `frontend/src/pages/CharacterPage.tsx`  
**Location:** `castSingle` vs. `previewPreset`

`previewPreset` calls `setPreview(null)` before `startGeneration(...)`, so the old audio player disappears immediately. `castSingle` calls only `startGeneration(...)` and never clears `preview`. The user sees the old audio player sitting there while the Cast is in flight, which can be confusing (looks like it already has output). Intentional? If so, add a comment; otherwise add `setPreview(null)` at the top of `castSingle`.

---

#### 🟢 Nit — Inline styles still on old dismiss path (cleaned up)

The old `<div className="flash error" style={{ cursor: 'pointer' }} onClick={() => setError(null)}>` inline style is correctly removed. No residual inline styles introduced. ✓

---

#### 🟢 Nit — `--btn-dismiss` hover state not present

`.btn-dismiss:hover` is not defined in `App.css`. Minor — visual polish only; the button is functional. Low priority.

---

### Positives
- `wasTimedOutRef` as a `ref` (not state) is the right call — no re-render on timeout, and the ref is readable synchronously inside the catch block before `stopGeneration` runs.
- `stopGeneration` in the `finally` block guarantees cleanup even on throw — correct.
- Silent cancel on user-initiated abort is the right UX choice.
- Mobile responsive flex stacking for `.generating-status` is thorough.
- `isGenerating` computed correctly from `generating === row.key || generating === row.key + '_cast'` (pre-existing, unchanged).

---

## PR #15 — `sprint1/preview-e2e` — Backend proxy fix + e2e tests

**Verdict: APPROVED (with one advisory note)**

### What it does
- Adds `create_prompt: bool | None`, `prompt_name: str | None`, `tags: list[str] | None` to `DesignRequest` Pydantic model (`web/app/routes/tts.py`)
- Switches `body.model_dump()` → `body.model_dump(exclude_none=True)` so plain preview calls don't pollute relay with null fields
- 8 new tests in `web/tests/test_e2e_proxy_chain.py` covering the fixed path

### Contract review (`contracts/relay-api.yaml`)

The relay contract documents `POST /api/v1/voices/design` request as `{text, instruct, language}` only. The three new fields (`create_prompt`, `prompt_name`, `tags`) are not documented in `relay-api.yaml`.

This is a **contract deviation** — the fields are sent through to the GPU server but the contract doesn't reflect them. The relay-api.yaml should be updated to document these optional fields (and their purpose) in the `POST /api/v1/voices/design` request schema.

This is advisory (the tests pass and the GPU server supports the fields), but the contract is now stale. **Recommend updating `relay-api.yaml` as a follow-up before sprint close.**

---

### Test quality

All 8 tests are meaningful and directly target the two reported bugs:

| Test | Covers |
|---|---|
| `test_design_preview_full_chain_basic` | Preview request flows end-to-end, correct relay path called |
| `test_design_preview_language_default` | `language` defaults to `"English"` |
| `test_design_preview_relay_502_becomes_502` | 502 from relay surfaces correctly |
| `test_design_preview_relay_504_becomes_504` | 504 propagates correctly |
| `test_cast_single_create_prompt_passes_through` | **Core bug fix** — `create_prompt/prompt_name/tags` reach relay |
| `test_cast_no_create_prompt_excludes_field` | `exclude_none=True` keeps plain-preview body clean |
| `test_relay_design_endpoint_correct_path` | Relay called at `/api/v1/voices/design` (no `/tts` prefix) |
| `test_design_body_transformation_complete` | Full field-by-field body transformation verified |

Patch target (`web.app.services.tts_proxy.tts_post`) is correct because the route accesses `tts_proxy.tts_post` via module reference (not direct import), so the module-level patch is effective.

---

### Positives
- `exclude_none=True` is the minimal, correct fix — no behavior change for existing callers.
- The fix is surgical (two-line change, targeted model extension).
- Tests are isolated, fast, and use the existing `client`/`auth_headers` fixture pattern correctly.
- Error propagation tests (502, 504) close a gap in the existing suite.

---

## Test suite results

| Suite | Result |
|---|---|
| `python -m pytest tests/ -m "not slow" -q` | **298 passed, 2 skipped** |
| `python -m pytest web/tests/ -q` | **84 passed** |
| `frontend: npm run build` | **✓ 0 type errors, 3.80s** |

---

## Overall recommendation

**Merge #15 immediately** — it's a clean bug fix with solid tests, all green.

**Block #14 on the unmount cleanup fix.** The timer leak is a real issue on slow GPU starts where users navigate away mid-flight. One small `useEffect` return closes it. Once that's addressed, the PR is solid.

**Follow-up (neither PR blocks):** Update `contracts/relay-api.yaml` to document the new optional fields on `POST /api/v1/voices/design`.
