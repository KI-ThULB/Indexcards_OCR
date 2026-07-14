---
name: Bug report
about: Something is broken or behaves unexpectedly
title: "[bug] "
labels: bug
---

## What happened

<!-- Describe what you observed. Screenshots welcome. -->

## What you expected

<!-- Describe what you expected to happen. -->

## Steps to reproduce

1.
2.
3.

## Environment

- **OS:** (macOS 14.x, Ubuntu 22.04, etc.)
- **Browser:** (Chrome 132, Firefox 128, etc.)
- **Node version:** (`node --version`)
- **Python version:** (`python3 --version`)
- **Branch / commit:** (`git log -1 --oneline`)

## Affected feature

<!-- Roughly which workflow phase does this involve? -->

- [ ] Upload
- [ ] Configure (field setup / validation rules / authority bindings / prompt template)
- [ ] Processing (OCR / progress / cancel / catastrophic failure)
- [ ] Results (table / editing / exports / filter chips / soft-block gate)
- [ ] Verify cockpit
- [ ] Clean view (clustering / facets / transforms / undo / audit log)
- [ ] Reconcile (candidate drawer / bulk mode / authority cache / 4 authorities)
- [ ] Batch history dashboard
- [ ] Build / install / dev server

## Backend log output

<!-- Paste relevant lines from the uvicorn terminal. STRIP API KEYS before posting. -->

```
```

## Browser console output

<!-- Paste any error / warning from the DevTools console. -->

```
```

## Additional context

<!-- Anything else worth knowing: was this working before? What changed? -->
