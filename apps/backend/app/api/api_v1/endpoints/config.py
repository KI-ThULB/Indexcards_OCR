"""Public runtime configuration for the frontend.

Serves only non-sensitive, UI-facing settings so the same built frontend can be
pointed at a different Ollama instance by editing the backend `.env` — no rebuild.

Security notes:
  - The browser NEVER talks to Ollama directly. OLLAMA_BASE_URL and OLLAMA_API_KEY
    stay backend-only; the model list is fetched server-side and proxied.
  - GET /config exposes provider labels/hints/default-models only — no base URLs,
    no credentials.
"""
import logging

import aiohttp
from fastapi import APIRouter

from app.core.config import settings
from app.models.schemas import (
    AppConfig,
    OllamaModel,
    OllamaModelsResponse,
    ProviderInfo,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=AppConfig)
async def get_app_config() -> AppConfig:
    """Return non-sensitive UI configuration (provider labels, defaults, enabled flags)."""
    providers = [
        ProviderInfo(
            value="openrouter",
            label="OpenRouter",
            endpoint_hint="Cloud · openrouter.ai",
            default_model=settings.MODEL_NAME,
            enabled=True,
        ),
        ProviderInfo(
            value="ollama",
            label=settings.OLLAMA_LABEL,
            endpoint_hint=settings.OLLAMA_ENDPOINT_HINT,
            default_model=settings.OLLAMA_MODEL_NAME,
            enabled=settings.OLLAMA_ENABLED,
        ),
    ]
    return AppConfig(providers=providers)


@router.get("/ollama/models", response_model=OllamaModelsResponse)
async def get_ollama_models() -> OllamaModelsResponse:
    """Fetch the installed model list from the configured Ollama server.

    The request is made server-side using the backend-only base URL and credential.
    Connection failures are reported gracefully (reachable=False + error) so the UI
    can fall back to a free-text model entry instead of breaking.

    Model filtering (in priority order):
      1. Explicit OLLAMA_MODEL_ALLOWLIST — exact ids, always wins.
      2. Else, if OLLAMA_VISION_FILTER is on (default): keep only models whose id
         looks vision-capable, since OCR requires a VLM. This is the sensible
         institution-agnostic default — it hides embedding/coder/text-only models
         without assuming specific model names.
      3. Else: return every model the server reports.
    If a filter would remove everything (e.g. no id matches the heuristic), the
    unfiltered list is returned so the curator is never left with an empty dropdown.
    """
    if not settings.OLLAMA_ENABLED:
        return OllamaModelsResponse(models=[], reachable=False, error="Ollama provider is disabled")

    headers = {"Authorization": f"Bearer {settings.OLLAMA_API_KEY}"}

    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(settings.OLLAMA_MODELS_ENDPOINT, headers=headers) as resp:
                resp.raise_for_status()
                payload = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError) as e:
        logger.warning("Could not reach Ollama at %s: %s", settings.OLLAMA_MODELS_ENDPOINT, e)
        return OllamaModelsResponse(
            models=[],
            reachable=False,
            error="Ollama-Server nicht erreichbar. Modell manuell eingeben oder Konfiguration prüfen.",
        )

    # OpenAI-compatible /v1/models returns {"data": [{"id": ...}, ...]}.
    raw = payload.get("data", []) if isinstance(payload, dict) else []
    ids = [item.get("id", "") for item in raw if isinstance(item, dict) and item.get("id")]

    filtered = _filter_models(ids)
    models = [OllamaModel(value=mid, label=mid, description="") for mid in sorted(filtered)]
    return OllamaModelsResponse(models=models, reachable=True, error=None)


def _filter_models(ids: list[str]) -> list[str]:
    """Apply allow-list → vision-filter → passthrough, never returning empty
    when the server did report models (so the UI dropdown is never blank)."""
    # 1. Explicit allow-list wins.
    allowlist = settings.ollama_model_allowlist
    if allowlist:
        allowed = set(allowlist)
        result = [mid for mid in ids if mid in allowed]
        return result or ids  # fall back to full list if nothing matched

    # 2. Vision heuristic (sensible default, no hardcoded model names).
    if settings.OLLAMA_VISION_FILTER:
        keywords = settings.ollama_vision_keywords
        result = [mid for mid in ids if any(kw in mid.lower() for kw in keywords)]
        return result or ids  # fall back to full list if heuristic matched nothing

    # 3. No filtering.
    return ids
