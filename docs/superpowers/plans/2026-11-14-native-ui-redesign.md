# Native UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Apply the approved clean native design to all six pages and provide persistent presentation, exact 2/3/5 columns, and independent page size controls.

**Architecture:** Keep Android + Python + Alpine. A validated `showcase.display` configuration and a dedicated atomic endpoint own live browsing preferences; existing gallery export preferences stay separate. Common native theme primitives replace the old glass layer, and page styles consume the same tokens.

**Tech Stack:** Existing Pydantic v2, FastAPI, Alpine, CSS, Android Java/resources; no new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-11-14-native-ui-redesign-design.md` (approved 2026-11-14).

## Global Constraints

- Exact grid choices: 2/3/5; independent page sizes: 30/45/60/90/120, compatible reads of existing valid sizes up to API maximum 500.
- Cover/poster/list selectable on mobile; retain table view. Logical multipart counts remain unchanged.
- Four UI languages, five font sizes, light/dim themes, 320/360/412 pixel widths and landscape.
- Keep image-window mount/unmount and request-generation guards. No new UI framework or remote font dependency.
- Use current isolated worktree and explicitly stage files. Do not remove old diagnostics or publish without a new release request.

## Review Focus

- Old localStorage/config preferences must not override a saved new display preference after refresh.
- Saving unrelated settings must not overwrite display preferences changed in another page.
- Rapid page-size changes must not commit an older API response or an older persisted value.
- Five columns plus large text must not spill out of a 320-pixel screen or silently become three columns.
- A 120-film page must retain bounded cover decoding and successful return/refresh behavior.

## Task 1: Persistent browsing preferences

**Files:** `core/config.py`, `web/config.default.json`, `web/routers/config.py`, `web/static/js/shared/showcase-display.js`; tests in `tests/test_native_display.py`, `tests/js/showcase-display.test.mjs`.

**Interfaces:** `ShowcaseDisplayConfig(presentation, columns, items_per_page)`; `PUT /api/config/showcase-display` accepts the complete three-field preference object and mutates only `showcase.display`. `resolveDisplayPreferences(display, legacyState, gallery)` validates config and legacy inputs; `createDisplaySaver(write)` serializes/coalesces writes and exposes a promise per requested save.

- [ ] Write and run RED tests for exact column validation, invalid input, independent page sizes, atomic preservation of unrelated config, legacy fallback, and serialized saves.
- [ ] Implement typed preference schema, new-install defaults, dedicated endpoint, and the pure shared helper. Full-config saves preserve the canonical display field, including absence on legacy configs.
- [ ] Run focused Python and Node tests GREEN. Commit this task explicitly.

## Task 2: Home and settings controls

**Files:** `showcase/main.js`, new `showcase/state-display.js`, `showcase/state-base.js`, `showcase/state-videos.js`, `templates/showcase.html`, settings state/template, `components/mobile-back.js`, five locale JSON files.

**Interfaces:** `stateDisplay()` exposes `displayOpen`, `displaySaving`, `displayError`, `gridColumns`, `openDisplaySettings()`, `setDisplayPresentation(value)`, `setDisplayColumns(value)`, `setDisplayPageSize(value)`, and retry. Consumes Task 1 helper and endpoint. `window.__SHOWCASE_DISPLAY__` supplies persisted preferences.

- [ ] Add behavior regression tests for restoration, filtering/pagination after page-size changes, request races, and mobile-back close behavior; observe RED.
- [ ] Replace mobile presentation gate with a visible Display button and one accessible panel. Add native classes/data to the grid; retain existing image window.
- [ ] Remove implicit 45 cap for explicit preferences. Reset page only on page-size changes, preserve filters and sorting, and fetch current server pages as needed.
- [ ] Add settings live-browsing preferences distinct from offline export controls; use dedicated save only when changed.
- [ ] Translate new labels and states in all existing locale files; run focused tests and JS syntax GREEN. Commit explicitly.

## Task 3: Native visual primitives and all pages

**Files:** `theme.css`, `components/fluent-materials.css` (replace old material implementation with native common surfaces), `mobile-ui.css`, page CSS, `base.html`, selected page template classes, Android `themes.xml` and palette resources.

**Interfaces:** Shared `--surface-*`, `--text-*`, `--stroke-*`, radius/space/control tokens consumed by all pages. New `native-bottom-nav` provides browsing/scanner/settings links through existing guarded navigation. Display grid uses exact `--browse-columns` with compact five-column captions.

- [ ] Remove network font imports; replace glass/background/shadow primitives with opaque light/dim native tokens and consistent controls.
- [ ] Simplify headers, add bottom navigation, normalize dialogs and states. Keep every existing route and action reachable.
- [ ] Update per-page layout rules rather than retaining contradictory materials. Make settings appearance group centered, fields readable, and maintenance buttons consistently orange.
- [ ] Validate actual layouts at narrow/large-font breakpoints in the simulator; use behavioral tests for state changes, not tests duplicating decorative CSS.
- [ ] Commit explicitly after focused regression checks.

## Task 4: Integration and verification

**Files:** patch generator file list, generated patches, implementation ledger/verification notes.

- [ ] Register new files, regenerate patches against upstream v0.18.17, verify source replay.
- [ ] Run TUR and Cleanup Python suites, all JS syntax checks, relevant Node behavior suites and Android unit/Debug build for x86_64.
- [ ] Use emulator-5554 with isolated fixtures. Measure exact 2/3/5 columns, all page sizes on 150+ logical films, filter/last-page counts, persistence after app restart, and image-window bounds at 120.
- [ ] Check all six pages in four languages, light/dim, standard/largest fonts, narrow widths and landscape. Restore emulator data and configuration.
- [ ] Perform one fresh whole-branch review, fix material findings with regression evidence, and record limitations honestly.
- [ ] Build arm64 Debug/Release for local review; do not publish or change the version without user direction. Explicitly commit final source/patch/docs only.

## Execution record

User explicitly authorized implementation of the approved design. Execute inline in the existing isolated worktree; no further permission check is needed for the implementation steps above.
