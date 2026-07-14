---
phase: 06-merge-features-of-main-and-current-branch-with-interview-which-feature-to-pick
plan: 06
subsystem: ui/branding
tags: [react, typescript, branding, assets, svg, header, sidebar]

# Dependency graph
requires:
  - phase: 06-03
    provides: "Frontend reimplementation base (provider selection, results, WebSocket)"
  - phase: feat/phase-03-processing-results
    provides: "Source SVG/PNG assets: ThULB_Logo_Line_Outline.svg, hacktheheritage_banner.png"
provides:
  - "ThULB institutional logo in header (link to thulb.uni-jena.de)"
  - "Hack the Heritage event banner in sidebar footer"
  - "App title renamed to 'Archival Metadata Extraction & Export Tool'"
  - "Header icon letter changed from I to A"
affects:
  - "All app views (Header/Sidebar are global layout components)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SVG import via Vite asset URL (import thuLbLogoUrl from '../../pics/...svg')"
    - "PNG import via Vite asset URL (import hackBannerUrl from '../../pics/...png')"

key-files:
  created:
    - "apps/frontend/pics/ThULB_Logo_Line_Outline.svg"
    - "apps/frontend/pics/hacktheheritage_banner.png"
  modified:
    - "apps/frontend/src/components/Header.tsx"
    - "apps/frontend/src/components/Sidebar.tsx"

key-decisions:
  - "Assets copied from feat/phase-03-processing-results via git checkout branch -- path (no manual download)"
  - "Header retains main-branch archive/history navigation while adding ThULB logo from source branch"
  - "Sidebar banner replaces generic 'Archive-Ready Solution' placeholder text"

# Metrics
duration: ~5min
completed: 2026-02-23
---

# Phase 06 Plan 06: App Branding & Rename Summary

**ThULB institutional logo added to header with link, Hack the Heritage event banner in sidebar footer, app title renamed to 'Archival Metadata Extraction & Export Tool'**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-02-23T14:41:47Z
- **Completed:** 2026-02-23T14:46:00Z
- **Tasks:** 1 (Task 2 is checkpoint — verification only)
- **Files modified:** 2 components, 2 new assets

## Accomplishments

- Copied `ThULB_Logo_Line_Outline.svg` (3,098 bytes) and `hacktheheritage_banner.png` (215,310 bytes) from `feat/phase-03-processing-results` branch
- Updated `Header.tsx`:
  - ThULB logo link (`bg-white/90`, border, shadow-sm) with `href="https://www.thulb.uni-jena.de"`, `target="_blank"`, `rel="noopener noreferrer"`
  - App title changed from "Indexcards OCR" to "Archival Metadata Extraction & Export Tool"
  - Icon letter changed from `I` to `A`
  - ThULB logo placed before action buttons with vertical divider separator
- Updated `Sidebar.tsx`:
  - Added `hackBannerUrl` PNG import
  - Replaced generic `"Archive-Ready Solution"` placeholder footer with "A Hack the Heritage Project" label + banner image
  - Banner uses `opacity-70 hover:opacity-100 transition-opacity` for subtle hover effect

## Task Commits

1. **Task 1: Branding changes** — `3f5c4d0` (feat)

## Verification Results

**TypeScript compile (`tsc --noEmit`):**
- Exit code: 0 — no errors

**Backend import check:**
- `python3 -c "from app.main import app; print('Backend import OK')"` — PASSED
- (urllib3/LibreSSL warning is pre-existing, not related to this change)

**Git log (feat/phase-06-ported-features):**
```
3f5c4d0 feat(06-06): app branding — ThULB logo in header, Hack the Heritage banner in sidebar
dd1b57b docs(06): record 06-04 and 06-05 summaries — built during 06-03 execution
35a82f1 docs(06-03): complete frontend feature reimplementation plan
edc81ac feat(06-03): port Results step with multi-entry, XML exports, hover thumbnails (Feature 2)
fe77f9e feat(06-03): improve WebSocket reconnect pattern (Feature 1)
a43221d feat(06-03): wire ProviderSelector into ConfigureStep (Feature 4)
a3a9e9e feat(06-03): add ProviderSelector component (Feature 4)
c307d6a feat(06-03): update startBatch API call to accept provider/model (Feature 9)
57ab516 feat(06-03): expand Zustand store with provider/model state (Feature 8)
```

## Decisions Made

- **Assets copied via `git checkout branch -- path`**: Clean approach — no manual download, preserves original file contents exactly
- **Header retains main-branch navigation while adding source-branch ThULB logo**: Best of both branches — archive/history nav from main + institutional branding from source
- **Banner replaces placeholder text**: Sidebar footer now shows actual event branding rather than generic text

## Deviations from Plan

None — Feature 7 (App Branding & Rename) executed as specified. Assets copied from source branch, Header and Sidebar updated with institutional/event branding.

## Self-Check: PASSED

- [x] `apps/frontend/pics/ThULB_Logo_Line_Outline.svg` — FOUND
- [x] `apps/frontend/pics/hacktheheritage_banner.png` — FOUND
- [x] `apps/frontend/src/components/Header.tsx` — ThULB logo import + link present
- [x] `apps/frontend/src/components/Sidebar.tsx` — hackBannerUrl import + banner render present
- [x] Commit `3f5c4d0` — FOUND in git log
- [x] TypeScript compile: 0 errors

---
*Phase: 06-merge-features-of-main-and-current-branch-with-interview-which-feature-to-pick*
*Completed: 2026-02-23*
