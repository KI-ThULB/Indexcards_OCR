# GPUStack provider

Indexcards_OCR can use an institutional GPUStack deployment through its
OpenAI-compatible chat-completions API. GPUStack is intended for interactive
work and smaller API-driven batches. Large unattended collection processing on
HPC/Slurm is a separate execution mode and is not implemented by this provider.

## Configuration

Set the following values in the backend `.env`:

```env
GPUSTACK_ENABLED=true
GPUSTACK_BASE_URL=https://gpustack.test.hs-itz.de/v1
GPUSTACK_API_KEY=<backend-only access token>
GPUSTACK_DEFAULT_MODEL=stable-vlm
```

`GPUSTACK_BASE_URL` may be configured either with or without a trailing `/v1`.
The backend normalises it to exactly one `/v1/chat/completions` endpoint. A full
`.../v1/chat/completions` URL is also accepted.

The API key remains backend-only. `GET /api/v1/config` exposes only the safe
provider label, endpoint hint, default model, and enabled flag; neither the base
URL nor the token is returned to the browser.

## Model aliases and provenance

`stable-vlm` is treated as a normal requested model identifier. The application
does not infer which concrete model an alias resolves to.

For each successful extraction the checkpoint records:

- `requested_model`: the model or alias sent in the request, for example
  `stable-vlm`;
- `resolved_model`: the `model` value reported by the provider response, if the
  provider supplies one; otherwise `null`.

This keeps provenance explicit when an institutional alias is rotated to a new
underlying model. Bulk runs freeze the effective requested model at run creation,
so changing `.env` later does not silently alter a resumed run.

## Error and retry behaviour

GPUStack uses the same bounded request policy as the other VLM providers:

- `401` / `403`: credential/authorization failure, no retry;
- `429`: retry with `Retry-After` when present, otherwise exponential backoff;
- `5xx`: retry with exponential backoff;
- other `4xx`: no retry;
- transport timeout/connection errors: retry up to `MAX_RETRIES`.

There is no automatic fallback to OpenRouter, Ollama, or another provider.
Unknown or disabled providers fail closed before an outbound request is made.

## Recommended first benchmark

For the first comparison against the previous Ollama workflow, keep the runtime
settings conservative and change only the provider/model:

```env
MAX_WORKERS=1
VLM_REQUEST_TIMEOUT_SECONDS=900
MAX_RETRIES=2
VLM_MAX_OUTPUT_TOKENS=8192
GPUSTACK_ENABLED=true
GPUSTACK_DEFAULT_MODEL=stable-vlm
```

Run the same small, known test set first. Increase concurrency only after the
single-worker latency and output quality are known.
