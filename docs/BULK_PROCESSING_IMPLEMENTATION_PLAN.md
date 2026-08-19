# Bulk / Multi-Batch Processing — Implementation Plan

> **Status: APPROVED, NOT YET IMPLEMENTED.**
> This document is the authoritative execution specification for the "Automated
> Multi-Batch Processing" / "Bulk Folder Workflow" feature. It is written to be
> self-contained: a fresh Claude Code session can execute it without any prior
> conversation context. Do not begin implementation until explicitly requested.

---

## 1. Purpose and use case

### The problem

Indexcards_OCR processes **one batch at a time** through an interactive wizard:

```
upload → configure → processing → [mandatory QC stop] → results → verify → clean → export
```

That mandatory quality-control stop is correct for careful single-batch curation, but it
makes large homogeneous collections impractical. Every folder needs its own
"Commence Processing" click and its own client-side CSV export, which then has to be
merged by hand.

### Primary use case — AMIGA Tonbandkartei

A collection of **28 folders containing approximately 500 JPG files each (~14,000 cards)**:

- all cards share a largely homogeneous layout,
- all cards contain **machine-written** (not handwritten) text,
- **one extraction template already exists** in the application and has been tested,
- no manual QC step is required between folders,
- folders should be processed **sequentially**,
- all extracted metadata must be consolidated into **one final CSV** that preserves
  source-folder and source-filename provenance.

### Target outcome

An **opt-in, clearly separated** unattended mode that orchestrates the *existing* batch
engine sequentially across many folders and produces one provenance-bearing CSV. Purely
additive: the interactive workflow, its QC stop, its per-batch exports and its batch
history remain untouched. QC data is still written for every card, so any individual record
can be inspected afterwards — only the *mandatory stop between folders* is skipped.

### When to use / when NOT to use

| Use bulk mode | Do **not** use bulk mode |
|---|---|
| Homogeneous collection, one card type | Mixed layouts or card types in one run |
| Template already tested on a sample | Untested or newly written template |
| Per-folder human QC not required | Every record must be curator-approved before export |
| Results will be validated before authoritative ingest | Output feeds an authoritative system unvalidated |

UI warning text (must appear before start and on the progress view):

> Bulk mode is intended for homogeneous collections with a previously tested extraction
> template. Intermediate manual quality control is skipped. Results should be validated
> before publication or ingest into authoritative systems.

---

## 2. Architectural decisions already made

These were agreed during planning and are **not** open for re-litigation during
implementation.

| # | Decision | Rationale |
|---|---|---|
| D1 | **Server-side import root** (`BULK_IMPORT_ROOT`), **disabled by default**. Only *immediate* subfolders are exposed; folder names are never trusted as filesystem paths. | ~14,000 files must not traverse the browser. Fits HPC/Ollama deployments. Browser upload stays unchanged. |
| D2 | **No auto-resume after restart.** A run that was `running` when the backend died is marked `interrupted` at startup; a human clicks **Resume**. | An unattended crash-loop or a routine redeploy must never silently restart VLM spend. |
| D3 | **Shared checkpoint reader** fixes a pre-existing compatibility bug as a general fix (not a bulk-only workaround), and is a **prerequisite**. | Bulk resume rides on the broken code path. |
| D4 | **Orchestration above the existing batch system** — no second processing engine, no second checkpoint system, no second retry policy. | Requirement; minimises risk and duplication. |
| D5 | **Sequential by default**, no cross-folder parallelism. Existing image-level parallelism *inside* a batch (`MAX_WORKERS`) is unchanged. | Bounded VLM/API load, bounded RAM/file descriptors, simple recovery, failures attributable to one folder. |
| D6 | **Consolidated CSV built server-side, streaming.** | 14,000 rows must not be assembled in the browser or held in backend memory. |
| D7 | **Hardlink import by default** with automatic per-file fallback to copy. | Copying 28×500 JPGs duplicates tens of GB; symlinks would break image serving (see §7). |
| D8 | **`schema_fields` frozen at run creation.** | Later template edits must not shift CSV columns mid-run. |

---

## 3. Prerequisite: shared checkpoint compatibility fix

### The bug (verified by code reading; confirm with a test first)

`apps/backend/app/services/ocr_engine.py` (resume block, ~line 491) reads
`checkpoint.json` with `json.load` and iterates whatever comes back:

```python
checkpoint_data = json.load(f)
for res in checkpoint_data:
    results.append(res)
    if res.get("success", False):
        completed_files.add(res["filename"])
```

`read_checkpoint` in `apps/backend/app/api/api_v1/endpoints/batches.py` (~line 40) rewrites
a legacy flat array into the object shape — and that rewrite is triggered by a plain
`GET /api/v1/batches/{batch_name}/results`, i.e. **merely opening the Results step**:

```python
if isinstance(data, list):
    obj = {"results": data, "audit": []}
    # ... writes obj back to disk
```

Afterwards the engine's resume loop iterates dict **keys**:

1. `res` becomes the string `"results"`, appended to `results`.
2. `res.get(...)` raises `AttributeError`, swallowed by the surrounding
   `except Exception` — leaving `results == ["results"]`.
3. In `_run_batch`, `res_map = {r["filename"]: r for r in results}` raises
   `TypeError: string indices must be integers`.
4. `run_ocr_task` catches it and marks the batch **`failed`**.

**Net effect today: view a batch's results once, and resume/retry for that batch is
broken.** Two writers disagree on the format — the engine writes a bare list on every
checkpoint save, the API writes the object shape.

### Required fix

**New `apps/backend/app/core/checkpoint.py`** — one canonical reader/writer:

- `read_checkpoint(path) -> tuple[list[dict], list[dict]]`
  - Accepts **both** formats for backward compatibility:
    1. legacy flat list `[...]` → `(data, [])`
    2. current object `{"results": [...], "audit": [...]}` → `(results, audit)`
  - Normalises both to one canonical `(results, audit)` structure.
  - **Pure — no write-on-read.** This deliberately removes the surprising migration side
    effect; a legacy file is upgraded on the next real write instead. Callers must not
    depend on read-triggered migration.
  - Raises on unreadable/corrupt JSON so each caller decides (the engine already wraps its
    read in `try/except`; endpoints should surface 500).
- `write_checkpoint(path, results, audit) -> None`
  - Always writes the object shape.
  - **Atomic**: write to a temp file in the same directory, then `os.replace`. A reboot
    400 images into a folder must not leave a truncated checkpoint.
- `completed_filenames(results) -> set[str]`
  - The single definition of "already done" (`success is True`), used by both single-batch
    and bulk resume.

**Rewired callers:**

- `services/ocr_engine.py` — the resume block and `_save_checkpoint` both use the shared
  helpers. `process_batch` must iterate **only the normalised `results` list**, and must
  **carry the existing `audit` list through untouched** so curator audit entries survive
  resume and retry. (Today the engine writes a bare list and would silently discard them.)
- `api/api_v1/endpoints/batches.py` — `read_checkpoint` / `write_checkpoint` become
  re-exports of the shared functions. Existing call sites (`patch_result`,
  `get_batch_config`, `get_batch_results`, `revalidate_batch`, `retry_image`) stay
  unchanged.
- The bulk resume logic **must reuse this same shared reader** — no parallel implementation.

**Constraints:** keep the patch narrowly scoped; no unrelated checkpoint refactors;
preserve compatibility with checkpoints already on disk from older versions.

### Required regression tests — `apps/backend/tests/test_checkpoint_compat.py`

- [ ] resume from a legacy flat-list checkpoint
- [ ] resume from a current `{results, audit}` checkpoint
- [ ] viewing results before resume (the exact bug path)
- [ ] retry after viewing results
- [ ] audit entries survive resume/retry (not rewritten, not discarded)
- [ ] no duplicate processing of already-completed images

---

## 4. Server-side ingestion via `BULK_IMPORT_ROOT`

### Behaviour

- `BULK_IMPORT_ROOT` is **empty by default** ⇒ bulk mode is entirely unavailable:
  endpoints return `404` and the UI hides the entry point.
- When configured, `GET /api/v1/bulk/sources` lists **only the immediate subfolders** of
  that root, each with a supported-image count (via the existing
  `app.core.images.iter_image_files`).
- **Never** expose or accept arbitrary filesystem paths. The client sends folder *names*
  chosen from that listing; the backend resolves each with
  `app.core.security.safe_join(BULK_IMPORT_ROOT, name)` and re-validates it against the
  live listing. Anything that escapes the root is rejected with `400`.
- No recursion into nested subfolders in v1 (documented limitation).
- `BULK_MAX_FOLDERS` guards against a pathological root.

### Reused existing helpers

`safe_join`, `validate_batch_name`, `validate_filename` (`app/core/security.py`);
`is_supported_image`, `iter_image_files` (`app/core/images.py`) — the latter already gives
**case-insensitive `.JPG` / `.JPEG` / `.TIFF` matching for free**, which is a hard
requirement for this feature.

---

## 5. Sequential folder processing

```
BulkRun Orchestrator  (one folder at a time, in configured order)
   ├─ register source folder → existing batch (config.json written from the template)
   ├─ acquire existing batch lock → run_ocr_task() → existing ocr_engine.process_batch
   ├─ existing per-batch checkpoint.json   ← the resume unit, unchanged
   ├─ update bulk-run state, broadcast bulk progress, release lock
   └─ … next folder …
        └─ streaming consolidated CSV (reads one checkpoint at a time)
```

For each source folder, in order:

1. Create or reuse an internal batch (idempotent — a folder already registered in this run
   is not re-created).
2. Process all supported image files with the run's template/provider/model.
3. Save checkpoint/results (existing mechanism).
4. Mark the folder completed in the bulk-run state.
5. Continue automatically with the next folder — **no user interaction between folders**.

No cross-folder parallelism. If it is ever added it must be explicitly configurable and
**disabled by default**.

### Reused as-is (do not reimplement)

| Component | Location |
|---|---|
| `iter_image_files`, `is_supported_image` | `app/core/images.py` |
| `create_batch`, `get_batch_path`, `acquire_batch_lock` / `release_batch_lock`, `update_batch_status`, `is_run_active`, `purge_batch_data` | `app/services/batch_manager.py` |
| `process_batch` (incl. `MAX_WORKERS` pool, `_errors/` handling, bounded retry/backoff) | `app/services/ocr_engine.py` |
| `run_ocr_task`, `_resolve_provider` | `app/api/api_v1/endpoints/batches.py` |
| `get_template` | `app/services/template_service.py` |
| `ws_manager` (connections, last-state replay, cancel events) | `app/services/ws_manager.py` |
| `log_event` | `app/core/audit.py` |
| `limiter`, `require_auth` | `app/core/rate_limit.py`, `app/core/security.py` |

### The single additive change to existing code

`run_ocr_task` gains an **optional** `progress_callback` parameter, defaulting to
`ws_manager.broadcast_progress` (exactly current behaviour). The orchestrator passes a
wrapper that forwards per-batch progress *and* updates bulk counters, so the per-batch and
bulk progress views run off one event stream. Everything else in `run_ocr_task` (config
loading, provider resolution, picture-field injection, final status, lock release in
`finally`) is reused untouched.

### New backend modules

| File | Responsibility |
|---|---|
| `app/core/checkpoint.py` | §3 shared reader/writer |
| `app/services/bulk_manager.py` | Persistent run state, atomic updates, single-run lock, `mark_interrupted_runs()` |
| `app/services/bulk_import.py` | Subfolder listing, image counts, materialising a folder as a batch |
| `app/services/bulk_orchestrator.py` | The sequential driver; pause/cancel/resume; error classification |
| `app/services/bulk_export.py` | Streaming consolidated CSV + failures CSV |
| `app/api/api_v1/endpoints/bulk.py` | REST surface |

---

## 6. Persistent bulk-run state model

One directory per run: `data/bulk_runs/<bulk_run_id>/` containing `run.json` (atomic
writes: temp file + `os.replace`) and the generated `consolidated.csv`.

```jsonc
{
  "bulk_run_id": "…",            // uuid4
  "name": "AMIGA Tonbandkartei", // operator-supplied label; NEVER used as a path
  "template_id": "…",
  "schema_fields": ["Komponist", "Signatur", "…"],  // FROZEN at creation (D8)
  "provider": "ollama",
  "model": "qwen3-vl:235b",
  "created_at": "…", "started_at": "…", "completed_at": null,
  "interrupted_at": null,
  "status": "running",
  "folders_total": 28, "folders_completed": 11,
  "images_total": 14000, "images_processed": 5347, "images_failed": 3,
  "current_folder": "Batch_011", "current_batch_id": "Batch_011_ab12cd34",
  "output_csv": "data/bulk_runs/<id>/consolidated.csv",
  "pause_requested": false, "cancel_requested": false,
  "folders": [
    {
      "source_folder": "Batch_001",
      "batch_name": "Batch_001_ab12cd34",
      "status": "completed",
      "images_total": 500, "images_processed": 500, "images_failed": 0,
      "started_at": "…", "completed_at": "…", "error": null
    }
  ]
}
```

**Statuses:** `queued | running | paused | interrupted | completed | completed_with_errors |
failed | cancelled`

(`interrupted` is an addition to the originally suggested list, required by D2.)

**Per-folder statuses:** `pending | running | completed | completed_with_errors | failed |
skipped`

A **single-run lock** (`O_EXCL` lockfile, mirroring
`BatchManager.acquire_batch_lock`) prevents two bulk runs executing concurrently.

`run.json` contains no extracted metadata and no personal data — only folder names, counts
and timestamps.

---

## 7. Materialising a source folder as a batch — and immutability

### Import mode

`BULK_IMPORT_MODE=hardlink` (default) with **automatic per-file fallback to `copy`** on
`OSError` (cross-device link, unsupported filesystem).

Why not the alternatives:

- **copy** duplicates tens of GB for 28×500 scans (still available, and the fallback).
- **symlink** breaks image serving: `serve_batch_image` in `apps/backend/app/main.py`
  calls `.resolve()` and requires the result to stay inside `BATCHES_DIR`; a symlink
  resolves to its target outside that tree and yields `404`. Fixing that would mean editing
  security-sensitive path logic — explicitly out of scope.
- **hardlink** is a real directory entry, so `serve_batch_image`, `_errors/` moves,
  `shutil.rmtree` and purge all behave exactly as for an uploaded batch, with no extra
  disk use.

Source folders are only ever **read** — never moved, renamed or deleted.

### ⚠️ Safety requirement: imported image files are immutable

A hardlink **shares its inode** with the file in `BULK_IMPORT_ROOT`. Therefore **any
in-place write to a batch-side image would silently corrupt the archival original.** Every
downstream batch operation must treat imported image files as strictly immutable.

**Permitted** on the batch-side link:

- moving it (e.g. into `_errors/` on failure, and back on retry),
- renaming it,
- deleting it (`delete_batch`, `purge_batch_data`, retention sweep, `shutil.rmtree`).

**Forbidden anywhere in the pipeline:**

- opening an image with a writing mode (`"wb"`, `"w"`, `"r+b"`, `"a"`),
- truncating an image,
- writing a resized/derived image back over the original.

Specific points to preserve and verify:

- `ocr_engine._encode_image_to_base64` must keep resizing **in memory only** — it currently
  writes the thumbnail into a `BytesIO` buffer (`img.save(buf, format="JPEG")`). This must
  never be changed to save in place.
- `serve_batch_image` (`app/main.py`) must stay strictly read-only.
- Retry paths (`retry_image`, `retry_batch`) only `shutil.move` files between the batch
  directory and `_errors/` — moving is fine, rewriting is not.
- During implementation, audit the whole image path for write-mode opens against any path
  under `BATCHES_DIR`.

**Rule of thumb: moving or deleting the batch-side hardlink is acceptable; modifying its
contents is not. The source folders under `BULK_IMPORT_ROOT` must always remain untouched.**

### Required regression tests — `apps/backend/tests/test_bulk_immutability.py`

Record SHA-256 + size + mtime for every source file before the run; assert byte-identity
afterwards for each scenario:

- [ ] after **successful** processing of a bulk run
- [ ] after **failed** processing / error handling (image moved to `_errors/`)
- [ ] after **retry** — both `POST /batches/{name}/retry` and
      `POST /batches/{name}/retry-image/{filename}`
- [ ] after **batch cleanup / purge** — `purge_batch_data` and `delete_batch`
      (batch-side link gone, source file still present and byte-identical)
- [ ] the source directory **listing** is unchanged — no files added, removed or renamed
- [ ] a `copy`-mode import behaves identically (sources untouched)

---

## 8. Explicit Resume after backend restart

The orchestrator is an in-process `asyncio` task, so a backend restart necessarily
interrupts a run. Per D2:

1. On startup, `main.py`'s `lifespan` hook calls
   `bulk_manager.mark_interrupted_runs()`: any run in status `running` becomes
   `interrupted`, stamped with `interrupted_at`, keeping `current_folder` and
   `current_batch_id` as recorded.
2. **No VLM processing is auto-started.**
3. The UI shows the run as interrupted, including **last processed folder, last processed
   image and the interruption timestamp**, so the operator can verify state before acting.
4. `POST /api/v1/bulk/runs/{id}/resume` continues from the persisted bulk-run state and the
   existing per-batch checkpoints:
   - folders already `completed` are **skipped entirely** (not re-processed),
   - the interrupted folder resumes from its own `checkpoint.json` via the shared reader —
     **already-successful images are never re-sent to the model**,
   - remaining folders proceed in configured order.

The bulk-run state **orchestrates** existing batch checkpoints; it never duplicates them.

---

## 9. Progress reporting over the existing WebSocket

Reuse `/api/v1/ws/task/{channel}` (`app/api/api_v1/endpoints/ws.py`) with channel id
`bulk:<bulk_run_id>`. `ws_manager` is already keyed by an arbitrary string, and its existing
"re-send last state on connect" logic gives **browser-close/reload reconnection for free**.

Additions (small, contained — no new transport):

- `BulkProgress` Pydantic model in `app/models/schemas.py`
- `bulk_states: Dict[str, BulkProgress]` in `ConnectionManager`
- `broadcast_bulk_progress(bulk_run_id, progress)`
- `ConnectionManager.connect` replays whichever state exists for the channel

The WebSocket keeps its existing Origin allow-list + `?token=` authentication
(`check_ws_auth`) — unchanged.

Progress view must show at least:

```
Project: AMIGA Tonbandkartei
Folders: 11 / 28 completed
Current folder: Batch_011
Images current folder: 347 / 500
Images overall: 5,347 / 14,000
Failed images: 3
Elapsed time: …
Current status: Processing
```

---

## 10. Consolidated provenance-bearing CSV export

### Streaming design (bounded memory)

Iterate folders in configured order; for each, read that folder's `checkpoint.json` via the
shared reader, iterate its results in **deterministic filename order** (already guaranteed
by `iter_image_files`' sort), and append rows incrementally with the stdlib `csv` module.
Peak memory is **one batch**, never 14,000 rows. Works for collections far larger than
28×500.

Per-batch result and export files remain available and unchanged.

### Format — mirrors the existing client-side CSV exactly

Conventions copied from
`apps/frontend/src/features/results/useResultsExport.ts` (`downloadCSV`): UTF-8 **BOM** for
Excel, **CRLF** line endings, **every cell quoted** with `"` doubled, and `_ocr` /
`_edited` / `_confidence` triplets per field. Multi-entry cards (`data["_entries"]`, the
Findmittel case) expand to one row per entry, mirroring
`apps/frontend/src/features/results/expandResults.ts`; confidence is per-page in v1 and
left blank on entry rows.

### Column order

```
bulk_run_id, source_folder, source_filename, batch_id,
File, Status, Error, Duration(s), Confidence_overall,
<Field1>_ocr, <Field1>_edited, <Field1>_confidence,
<Field2>_ocr, <Field2>_edited, <Field2>_confidence,
…
```

Example header for a two-field template:

```csv
"bulk_run_id","source_folder","source_filename","batch_id","File","Status","Error","Duration(s)","Confidence_overall","Komponist_ocr","Komponist_edited","Komponist_confidence","Signatur_ocr","Signatur_edited","Signatur_confidence"
"7f3a…","Batch_001","IMG_6662.JPG","Batch_001_ab12cd34","IMG_6662.JPG","success","","2.41","87","Bach, Johann Sebastian","","92","Spez. 12.345","","81"
```

### Schema consistency (requirement 6)

- Before a run starts, validate that the selected template resolves to a **non-empty,
  stable** field list; store it as `schema_fields` in `run.json` (**frozen** — later
  template edits cannot shift columns mid-run).
- All sub-batches use the same template, field definitions, output schema and
  provider/model.
- A result **missing** a field writes an **empty value** — never a changed schema.
- **Unexpected extra keys are not promoted to columns**; they are counted and logged, so
  the CSV schema cannot drift. Internal keys (`_entries`, `_entry_count`, `Datei`, `Batch`)
  are handled explicitly, not emitted as data columns.
- `edited_data` takes precedence in the `_edited` column, matching
  `fieldValue()` in the frontend exporter.

### Determinism

Source folders in configured processing order; files within a folder in sorted filename
order. Re-running the export over the same state produces a byte-identical file.

### Endpoints

- `GET /api/v1/bulk/runs/{id}/export.csv` — the consolidated CSV (downloadable from the UI)
- `GET /api/v1/bulk/runs/{id}/failures.csv` — failed image records, so they can be retried
  selectively without rerunning the collection

---

## 11. Pause, cancel and resume behaviour

| Action | Mechanism | Resulting status | Data |
|---|---|---|---|
| **Pause** | Sets `pause_requested`; the current batch's existing `cancel_event` stops processing **after the current image** (checkpoint already saved) | `paused` | All completed results kept |
| **Cancel** | Sets `cancel_requested`; same cooperative stop | `cancelled` | All completed results kept |
| **Resume** | From `paused` or `interrupted`; skips completed folders/images | `running` | Continues from checkpoints |

- Cancellation must **never** corrupt already-generated results and must **never**
  automatically delete completed batch data.
- Because `run_ocr_task` marks a cooperatively stopped batch `cancelled` in `batches.json`,
  a paused folder's batch shows `cancelled` until the run resumes and it completes. This is
  cosmetic; note it as a known limitation.
- Pause granularity is **after the current image**; the run additionally stops cleanly at
  folder boundaries.

---

## 12. Error handling and retry policy

### Retry — reuse only

Image-level transient errors use the **existing** bounded retry with exponential backoff
and jitter in `ocr_engine._call_vlm_api_resilient` (`MAX_RETRIES`, `Retry-After` handling
for 429, retry on 5xx/timeout/connection errors, no retry on other 4xx). **Do not add a
new retry loop.** Failed cards move to the batch's `_errors/` directory as they do today.
Selective later retry uses the existing endpoints
`POST /api/v1/batches/{name}/retry-image/{filename}` and `POST /api/v1/batches/{name}/retry`.

### Classification

**Recoverable (image-level):** a folder finishes with `images_failed > 0`. With
`BULK_CONTINUE_ON_BATCH_ERROR=true` (default) the run continues to the next folder, and
the run ends `completed_with_errors`.

**Structural (stop the whole run, status `failed`)** — conditions that would invalidate all
following folders:

- template missing or resolves to an empty field list,
- provider credential missing / invalid (e.g. `401`, "API Key missing"),
- `BULK_IMPORT_ROOT` unreachable or a selected folder disappeared,
- a folder yields **zero** successful images (treated as a configuration fault),
- an unexpected exception escaping `run_ocr_task` for a folder.

### Tracking

Per folder and per run: failed images, failed folders, provider/API errors and retry
counts. Final status must clearly distinguish `completed`, `completed_with_errors` and
`failed`.

### Final summary (UI)

Total folders, total images, successfully processed images, failed images, elapsed time,
provider/model used, consolidated CSV download, and an optional list/download of failed
image records. Provider cost is shown **only if** the application already tracks it — it
currently does not, so this is omitted rather than invented.

---

## 13. Security requirements

No existing hardening may be weakened. Specifically:

- **Authenticated API access** — register the bulk router with the same
  `dependencies=[Depends(require_auth)]` used by every other HTTP router in
  `app/api/api_v1/api.py`.
- **WebSocket auth/origin** — reuse the existing `check_ws_auth` (Origin allow-list +
  `?token=`); no changes.
- **Path validation** — every folder name goes through `safe_join` against
  `BULK_IMPORT_ROOT` and is re-validated against the live subfolder listing. Batch names
  keep `validate_batch_name`; filenames keep `validate_filename`.
- **Names are never paths** — the run `name` and folder labels are display-only. Batch
  directory names continue to be generated by `batch_manager.create_batch` (which
  sanitises Windows-illegal characters and appends a uuid suffix).
- **Upload validation** — untouched; bulk import bypasses HTTP upload entirely, so it must
  independently enforce the supported-extension check via `is_supported_image`.
- **Rate limiting** — `@limiter.limit(settings.RATE_LIMIT_BULK_START)` on run creation and
  start.
- **Single-run locks** — the existing per-batch `O_EXCL` lock plus a new bulk-level
  single-run lock.
- **Security headers** — unchanged (global middleware).
- **Retention rules** — respected (see §14).
- **Secrets** — API keys/base URLs stay backend-only; nothing new is exposed to the browser
  beyond a `bulk_enabled` boolean and folder names/counts.

---

## 14. Audit and retention integration

### Audit events

Logged through the existing `app.core.audit.log_event`:

```
bulk_run_created
bulk_run_started
bulk_run_paused
bulk_run_resumed
bulk_run_cancelled
bulk_run_completed
bulk_run_exported
```

Each record carries only non-sensitive fields (run id, run name, folder counts, image
counts, provider, resulting status). **Never** log extracted metadata, OCR text, prompts,
image contents, keys or tokens.

### Retention / purge

Batches created by a bulk run are **ordinary batches**: they appear in `batches.json`, get
`completed_at` stamps via `update_batch_status`, and are therefore already covered by
`RETENTION_DAYS`, the startup sweep, `preview_purgeable`, the manual
`POST /batches/{name}/purge` and `AUTO_PURGE_AFTER_EXPORT`. No retention logic is
duplicated.

Additional points:

- Purging a bulk batch must not corrupt the bulk-run state: the run keeps its counts and
  the folder is reported as purged rather than re-processable.
- The consolidated CSV **does** contain extracted metadata, so `data/bulk_runs/<id>/` must
  be documented as personal-data-bearing in `DEPLOYMENT.md` (encrypted volume, backup and
  purge guidance), and covered by the deployment retention story.
- Existing purge safeguards (`is_run_active`, `.exporting` marker) apply unchanged; a bulk
  run holding a batch lock therefore cannot be purged mid-run.

---

## 15. Frontend changes

New, self-contained under `apps/frontend/src/`:

| File | Purpose |
|---|---|
| `api/bulkApi.ts` | react-query hooks over axios (inherits the bearer token from `api/client.ts`) |
| `store/bulkStore.ts` | Separate zustand store — `wizardStore` is **not** restructured |
| `features/bulk/BulkStartStep.tsx` | Folder picker, template select, provider/model (reusing `features/configure/ProviderSelector.tsx`), run name, review screen, warning |
| `features/bulk/BulkProgressStep.tsx` | Live progress (§9), Pause/Cancel/Resume, interrupted banner with last folder/image + interruption timestamp |
| `features/bulk/BulkSummary.tsx` | Final summary (§12), consolidated CSV download, failed-records download |
| `features/bulk/useBulkWebSocket.ts` | Mirrors `features/processing/useProcessingWebSocket.ts` on channel `bulk:<id>` |

Minimal edits to existing files:

- `store/wizardStore.ts` — extend the `AppView` union with `'bulk'` (no other changes).
- `App.tsx` — one route branch for the bulk view.
- `components/Sidebar.tsx` — one nav entry, shown **only** when `bulk_enabled` is true,
  presented as a separate optional mode:

```
New Project
 ├── Standard Batch
 └── Bulk / Multi-Batch Processing
```

Bulk flow: select folders → select existing template → select provider/model → review
(28 folders, ~14,000 images, sequential, intermediate QC skipped) → start → monitor →
download consolidated CSV.

Nothing is removed: normal batch QC, individual exports, individual batch history,
existing templates and the normal upload/start workflow all stay exactly as they are.

---

## 16. Configuration additions

`apps/backend/app/core/config.py` (`Settings`), documented in `.env.example` and
`docs/DEPLOYMENT.md`:

```bash
# ── Bulk / multi-batch processing (opt-in; empty root ⇒ feature unavailable) ──
# Absolute path to a directory whose IMMEDIATE subfolders each hold one card
# collection. Only these subfolders are ever offered in the UI; arbitrary paths
# are never accepted. Empty (default) disables bulk mode entirely.
BULK_IMPORT_ROOT=

# How source images become batch files: hardlink (default, no extra disk; falls
# back to copy per file when the source is on another filesystem) or copy.
# Source files are only ever read — never modified, moved or deleted.
BULK_IMPORT_MODE=hardlink

# Continue with the next folder when a folder finishes with recoverable
# image-level errors. Structural/configuration errors always stop the run.
BULK_CONTINUE_ON_BATCH_ERROR=true

# Guard against a pathological import root.
BULK_MAX_FOLDERS=200

# Rate limit for creating/starting a bulk run.
RATE_LIMIT_BULK_START=6/minute
```

`GET /api/v1/config` gains a `bulk_enabled: bool` field (derived from `BULK_IMPORT_ROOT`)
so the UI can hide the entry point — the same runtime-config pattern already used for the
Ollama provider. No migration is required: no database exists, all state is JSON on disk,
and existing batches/checkpoints/templates keep working untouched.

---

## 17. Tests

All VLM calls are mocked using the established project pattern — no network, deterministic:

```python
monkeypatch.setattr(ocr_engine, "_call_vlm_api_resilient", lambda *a, **k: (payload, None))
```

(see `apps/backend/tests/test_confidence_and_pictures.py`). `apps/backend/tests/conftest.py`
already redirects `DATA_DIR` to a temp directory at collection time; reuse its `client`
fixture and the `make_jpeg_bytes()` / `make_tiff_bytes()` helpers.

| Test file | Coverage |
|---|---|
| `test_checkpoint_compat.py` | The six §3 cases |
| `test_bulk_run.py` | Multiple folders processed **sequentially**; same template applied to all batches; uppercase `.JPG` accepted; deterministic processing order; resume skips completed batches **and** completed images; one failed image does not corrupt the run; folder failure → `completed_with_errors` (and `BULK_CONTINUE_ON_BATCH_ERROR=false` → `failed`); cancellation leaves completed data intact; startup marks a `running` run `interrupted` |
| `test_bulk_export.py` | Consolidated CSV contains **all** records; provenance columns correct; missing fields do not alter the schema; extra keys add no columns; deterministic row order; multi-entry expansion |
| `test_bulk_immutability.py` | The six §7 cases (sources byte-identical) |
| `test_bulk_security.py` | Disabled by default → 404; traversal in folder names rejected; auth enforced when `AUTH_TOKEN` set; sources never escape the import root |
| existing suite | Must stay green, plus an explicit test that the standard single-batch create → start → results flow is unchanged |

---

## 18. Verification commands

```bash
# Backend
cd apps/backend
uv run pytest tests/ -v --tb=short
uv run ruff check app/
uv run mypy app/

# Frontend (shared types must be generated first — CI does this)
cd ../..
npm run build --workspace @indexcards/shared-types
npm run lint --workspace @indexcards/frontend
npm run typecheck --workspace @indexcards/frontend
npm run build --workspace @indexcards/frontend
```

**Manual end-to-end walkthrough** (mocked provider or a tiny real folder set):

1. Point `BULK_IMPORT_ROOT` at a scratch directory with 3 folders × 2 mixed-case JPGs.
2. Record source checksums.
3. Start a bulk run; confirm sequential progress over the WebSocket.
4. Kill the backend mid-run; restart → the run shows `interrupted` with last
   folder/image and `interrupted_at`.
5. Click **Resume** → already-completed images are not re-sent to the model.
6. Consolidated CSV row count equals total images (plus multi-entry expansion), provenance
   columns correct, ordering deterministic.
7. Source checksums unchanged; source listing unchanged.
8. Run the normal single-batch wizard once to confirm it is unaffected.

**Do not commit until every check above passes.**

---

## 19. Documentation changes

- **`docs/GETTING_STARTED.md`** — new "Bulk / multi-batch processing" section: what it is,
  the opt-in `BULK_IMPORT_ROOT` setup, the step-by-step flow, and an explicit when-to-use /
  when-not-to-use subsection (§1), including this example:

  > 28 folders containing approximately 500 homogeneous machine-written historical index
  > cards each can be processed sequentially using one tested extraction template. No
  > intermediate QC stop is required, and all extracted records are consolidated into a
  > final CSV while preserving source-folder and source-filename provenance.

- **`docs/DEPLOYMENT.md`** — the new environment variables; import-root and hardlink
  guidance including the immutability guarantee and disk implications; a note that bulk mode
  is off unless `BULK_IMPORT_ROOT` is set; `data/bulk_runs/` added to the data-folders,
  backup and retention sections.
- **`.env.example`** — the block from §16.
- **`CHANGELOG.md`** — under `[Unreleased]`: an `### Added` entry for the bulk workflow and
  a `### Fixed` entry for the checkpoint compatibility bug.

---

## 20. Known limitations (report these at the end)

- The orchestrator is in-process: a backend restart interrupts a run by design; resuming is
  an explicit human action (D2).
- Hardlink import requires the source and `DATA_DIR` to share a filesystem; otherwise it
  silently falls back to copying (extra disk use).
- `BULK_IMPORT_ROOT` must be on a filesystem reachable by the backend process — no
  remote/S3/object-store sources.
- Only immediate subfolders are offered; no recursion into nested directory trees in v1.
- Multi-entry cards expand to several CSV rows, so the row count exceeds the image count
  for those pages.
- A paused folder's batch is briefly marked `cancelled` in `batches.json` until the run
  resumes (cosmetic).
- Provider cost is not reported because the application does not currently track it.
- No cross-folder parallelism (deliberate, D5).

---

## 21. Implementation order

Each step must end green (backend pytest · ruff · mypy, plus the frontend checks from
step 7) before the next begins, and each is a separate atomic commit.

1. **Checkpoint compatibility fix** (§3) — independently valuable; land first.
2. **Config + persistent state store** (§6, §16).
3. **Import layer** (§4, §7) — including security and immutability tests.
4. **Orchestrator** (§5, §8, §11, §12).
5. **Consolidated export** (§10).
6. **REST + WebSocket surface** (§9, §13, §14).
7. **Frontend** (§15).
8. **Docs + changelog** (§19).
9. **Full verification sweep** (§18), then report: architecture summary, files changed,
   state-model changes, tests added, test/build results, example consolidated CSV columns,
   `.env`/migration additions, known limitations and the commit hash.

---

## Implementation checklist

- [ ] **Phase 1 — Shared checkpoint reader (prerequisite)**
  - [ ] Write a failing test first that reproduces the view-results-then-resume bug
  - [ ] `app/core/checkpoint.py`: `read_checkpoint` (both formats, pure/no write-on-read),
        atomic `write_checkpoint`, `completed_filenames`
  - [ ] Rewire `ocr_engine.process_batch` resume block + `_save_checkpoint`; iterate only
        normalised `results`; carry `audit` through untouched
  - [ ] Re-export from `api/api_v1/endpoints/batches.py`; existing call sites unchanged
  - [ ] `tests/test_checkpoint_compat.py` — all six cases green
  - [ ] Confirm older on-disk checkpoints still load
- [ ] **Phase 2 — Config & persistent bulk-run state**
  - [ ] `Settings`: `BULK_IMPORT_ROOT`, `BULK_IMPORT_MODE`,
        `BULK_CONTINUE_ON_BATCH_ERROR`, `BULK_MAX_FOLDERS`, `RATE_LIMIT_BULK_START`
  - [ ] `app/services/bulk_manager.py`: create/get/list/update, atomic `run.json` writes,
        `O_EXCL` single-run lock
  - [ ] `mark_interrupted_runs()` wired into `main.py` `lifespan` (no auto-resume)
- [ ] **Phase 3 — Server-side import (`BULK_IMPORT_ROOT`)**
  - [ ] `app/services/bulk_import.py`: `safe_join` subfolder listing, counts via
        `iter_image_files`, hardlink → per-file copy fallback
  - [ ] Audit the image path for write-mode opens under `BATCHES_DIR`
  - [ ] `tests/test_bulk_security.py` green
  - [ ] `tests/test_bulk_immutability.py` green — sources byte-identical after success,
        failure, retry, cleanup/purge; listing unchanged; copy mode equivalent
- [ ] **Phase 4 — Sequential orchestrator**
  - [ ] `app/services/bulk_orchestrator.py` driving existing batches one at a time
  - [ ] Additive optional `progress_callback` on `run_ocr_task` (default unchanged)
  - [ ] Pause / cancel / resume; structural-vs-recoverable error classification
  - [ ] `asyncio.create_task` + module-level task registry (not `BackgroundTasks`)
  - [ ] `tests/test_bulk_run.py` green
- [ ] **Phase 5 — Consolidated CSV export**
  - [ ] `app/services/bulk_export.py` streaming writer (one checkpoint in memory at a time)
  - [ ] Provenance columns, frozen `schema_fields`, missing → empty, extra keys dropped,
        multi-entry expansion, BOM/CRLF/quoting parity with the frontend exporter
  - [ ] Failures CSV
  - [ ] `tests/test_bulk_export.py` green
- [ ] **Phase 6 — REST & WebSocket surface**
  - [ ] `app/api/api_v1/endpoints/bulk.py`: sources, create, start, pause, resume, cancel,
        list, detail, `export.csv`, `failures.csv`
  - [ ] Router registered with `require_auth`; rate limit on create/start
  - [ ] `BulkProgress` schema, `bulk_states`, `broadcast_bulk_progress`, channel `bulk:<id>`
  - [ ] `bulk_enabled` in `GET /api/v1/config`
  - [ ] All seven audit events emitted, no metadata logged
- [ ] **Phase 7 — Frontend**
  - [ ] `api/bulkApi.ts`, `store/bulkStore.ts`, `features/bulk/useBulkWebSocket.ts`
  - [ ] `BulkStartStep.tsx`, `BulkProgressStep.tsx`, `BulkSummary.tsx`
  - [ ] Warning text before start and on the progress view
  - [ ] Interrupted banner: last folder, last image, interruption timestamp, Resume action
  - [ ] Minimal edits: `App.tsx`, `Sidebar.tsx` (gated on `bulk_enabled`), `wizardStore.ts`
        (`AppView` only)
  - [ ] Reconnect after browser close/reload verified
- [ ] **Phase 8 — Documentation**
  - [ ] `docs/GETTING_STARTED.md` — bulk section incl. when to use / when not
  - [ ] `docs/DEPLOYMENT.md` — env vars, hardlink/immutability, disk, `data/bulk_runs/`
  - [ ] `.env.example` block
  - [ ] `CHANGELOG.md` — Added (bulk workflow) + Fixed (checkpoint compatibility)
- [ ] **Phase 9 — Verification & handover**
  - [ ] `pytest` · `ruff` · `mypy` green
  - [ ] frontend `lint` · `typecheck` · `build` green
  - [ ] Manual restart/resume walkthrough (§18) completed
  - [ ] Existing single-batch workflow confirmed unchanged
  - [ ] Final report: architecture, files changed, state-model changes, tests added,
        results, example CSV columns, env additions, limitations, commit hash

---

## 22. Constraints (non-negotiable)

- Backward-compatible and **additive/opt-in** throughout.
- Do **not** silently bypass or delete QC information — only the mandatory stop between
  batches is skipped; per-card QC data is still written and inspectable.
- Do **not** process folders concurrently by default.
- Do **not** duplicate existing checkpoint, export or security logic.
- Do **not** redesign unrelated parts of the application.
- Do **not** weaken any existing security hardening.
- Do **not** modify image file contents anywhere in the pipeline (§7).
- Do **not** commit until all tests and builds pass.
