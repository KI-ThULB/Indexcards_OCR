from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings
from typing import List, Optional
import os

class Settings(BaseSettings):
    PROJECT_NAME: str = "Indexcards OCR API"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"

    # Directory Configuration
    # These paths are relative to the backend root or absolute
    DATA_DIR: str = os.getenv("DATA_DIR", "data")
    TEMP_DIR: str = os.path.join(DATA_DIR, "temp")
    BATCHES_DIR: str = os.path.join(DATA_DIR, "batches")
    TEMPLATES_FILE: str = os.path.join(DATA_DIR, "templates.json")
    BATCHES_HISTORY_FILE: str = os.path.join(DATA_DIR, "batches.json")
    OUTPUT_BASE: str = "output_batches"
    
    # API Configuration — OpenRouter (default)
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    API_BASE_URL: str = "https://openrouter.ai/api/v1"
    API_ENDPOINT: str = f"{API_BASE_URL}/chat/completions"
    MODEL_NAME: str = "qwen/qwen3-vl-8b-instruct"

    # ------------------------------------------------------------------
    # API Configuration — Ollama (self-hosted / on-premise VLM)
    #
    # Every field below is overridable via environment variable or .env —
    # pydantic-settings binds each field name to an env var of the same
    # name. This lets a new institution point the app at their own Ollama
    # instance purely through configuration, with no code change and no
    # frontend rebuild. See .env.example and docs/GETTING_STARTED.md.
    # ------------------------------------------------------------------
    # Base URL of the Ollama server (OpenAI-compatible API). HTTP or HTTPS.
    # The chat and model-listing endpoints are derived from this.
    #   e.g. http://localhost:11434  or  https://ollama.example.org
    OLLAMA_BASE_URL: str = "https://ollama.draco.uni-jena.de"
    # Default model pre-selected in the UI when Ollama is chosen.
    OLLAMA_MODEL_NAME: str = "qwen3-vl:235b"
    # Bearer token for the Ollama endpoint. Ollama ignores it by default,
    # but reverse proxies in front of it often require one.
    OLLAMA_API_KEY: str = os.getenv("OLLAMA_API_KEY", "ollama")
    # Whether the Ollama provider is offered in the UI at all.
    OLLAMA_ENABLED: bool = True
    # Human-readable name shown on the provider radio button.
    OLLAMA_LABEL: str = "Ollama (self-hosted)"
    # Cosmetic sub-label under the provider name. Purely for display —
    # the real base URL is never sent to the browser.
    OLLAMA_ENDPOINT_HINT: str = "Lokal · on-premise"
    # Optional comma-separated allow-list restricting which installed
    # models are offered in the UI. Empty = fall back to the vision filter
    # below (or, if that is off, offer every model the server reports).
    # An explicit allow-list ALWAYS wins. e.g. "qwen3-vl:235b,qwen2.5vl:72b"
    OLLAMA_MODEL_ALLOWLIST: str = ""
    # Sensible institution-agnostic default: when no explicit allow-list is
    # set, only show models whose id looks vision-capable (OCR needs a VLM).
    # This hides embedding/coder/text-only models a typical Ollama server has
    # installed, without assuming any specific model NAMES (which differ per
    # institution). Set to false to offer the server's full model list.
    OLLAMA_VISION_FILTER: bool = True
    # Substrings (case-insensitive) that mark a model id as vision-capable.
    # Tune per institution if a local VLM uses a naming scheme not covered here.
    OLLAMA_VISION_KEYWORDS: str = "vl,vision,llava,-ocr,ocr:,minicpm-v,pixtral,granite3.2-vision,gemma3"
    # Backward-compatible explicit override. Older .env files set the full
    # chat-completions URL directly via OLLAMA_API_ENDPOINT; if present it wins
    # over the derived value. Leave unset to derive from OLLAMA_BASE_URL.
    OLLAMA_API_ENDPOINT_OVERRIDE: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("OLLAMA_API_ENDPOINT_OVERRIDE", "OLLAMA_API_ENDPOINT"),
    )

    @property
    def OLLAMA_API_ENDPOINT(self) -> str:
        """Chat-completions endpoint. Explicit override wins, else derived from base URL."""
        if self.OLLAMA_API_ENDPOINT_OVERRIDE:
            return self.OLLAMA_API_ENDPOINT_OVERRIDE
        return f"{self.OLLAMA_BASE_URL.rstrip('/')}/v1/chat/completions"

    @property
    def OLLAMA_MODELS_ENDPOINT(self) -> str:
        """Model-listing endpoint. Derived from the override host if set, else base URL."""
        if self.OLLAMA_API_ENDPOINT_OVERRIDE:
            # Strip a trailing /chat/completions to reuse the same /v1 base.
            base = self.OLLAMA_API_ENDPOINT_OVERRIDE.rstrip("/")
            if base.endswith("/chat/completions"):
                base = base[: -len("/chat/completions")]
            return f"{base}/models"
        return f"{self.OLLAMA_BASE_URL.rstrip('/')}/v1/models"

    @property
    def ollama_model_allowlist(self) -> List[str]:
        """OLLAMA_MODEL_ALLOWLIST parsed into a clean list (empty = no explicit list)."""
        return [s.strip() for s in self.OLLAMA_MODEL_ALLOWLIST.split(",") if s.strip()]

    @property
    def ollama_vision_keywords(self) -> List[str]:
        """OLLAMA_VISION_KEYWORDS parsed into a clean lowercase list."""
        return [s.strip().lower() for s in self.OLLAMA_VISION_KEYWORDS.split(",") if s.strip()]

    # ------------------------------------------------------------------
    # Security configuration (pentest remediation W-01…W-08)
    #
    # Secure-by-default: local dev is unaffected (AUTH off, bind localhost).
    # Production hardening is enabled via .env + an authenticating reverse
    # proxy. See docs/DEPLOYMENT.md.
    # ------------------------------------------------------------------
    # Network interface the dev/prod server binds to. Default localhost so the
    # backend is never network-exposed without a deliberate proxy in front (K-2).
    HOST: str = "127.0.0.1"
    # Optional bearer token guarding the JSON API + WebSocket (W-01/H-4).
    # Empty ⇒ auth disabled (local single-curator dev). When set, every
    # /api/v1 request must send `Authorization: Bearer <token>` and the
    # WebSocket must pass `?token=<token>`. Not a replacement for the
    # reverse-proxy SSO in production — a backend safeguard.
    AUTH_TOKEN: str = ""
    # Comma-separated allow-list of Origins accepted for the WebSocket
    # handshake (W-04). Cross-site origins are rejected with close code 1008.
    ALLOWED_WS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Expose OpenAPI schema + Swagger/ReDoc UIs. Off in production so the
    # full API surface is not published without auth (W-07/H-6).
    ENABLE_DOCS: bool = False
    # Optional comma-separated CORS allow-list. Empty ⇒ no CORS middleware
    # (same-origin behind the proxy). Never combine "*" with credentials (M-1).
    CORS_ALLOW_ORIGINS: str = ""

    # Upload limits (W-03/H-1). Reject oversized or non-image uploads.
    MAX_UPLOAD_BYTES: int = 25 * 1024 * 1024   # 25 MB per file
    MAX_UPLOAD_FILES: int = 2000               # per request
    ALLOWED_IMAGE_EXTENSIONS: str = ".jpg,.jpeg,.png,.tif,.tiff"

    # Rate limiting (W-06/H-2). storage_uri="memory://" is per-process; point
    # at redis://… when running multiple workers so limits are shared.
    RATE_LIMIT_STORAGE_URI: str = "memory://"
    RATE_LIMIT_UPLOAD: str = "30/minute"
    RATE_LIMIT_START: str = "12/minute"
    RATE_LIMIT_RECONCILE: str = "120/minute"

    @property
    def allowed_ws_origins(self) -> List[str]:
        """ALLOWED_WS_ORIGINS parsed into a clean list."""
        return [s.strip() for s in self.ALLOWED_WS_ORIGINS.split(",") if s.strip()]

    @property
    def cors_allow_origins(self) -> List[str]:
        """CORS_ALLOW_ORIGINS parsed into a clean list (empty = CORS disabled)."""
        return [s.strip() for s in self.CORS_ALLOW_ORIGINS.split(",") if s.strip()]

    @property
    def allowed_image_extensions(self) -> set:
        """ALLOWED_IMAGE_EXTENSIONS parsed into a lowercase set (with leading dot)."""
        return {e.strip().lower() for e in self.ALLOWED_IMAGE_EXTENSIONS.split(",") if e.strip()}

    # GeoNames account username — required for GeoNames authority reconciliation. See https://www.geonames.org/login
    GEONAMES_USERNAME: Optional[str] = None

    # LLM Corrector Configuration
    CORRECTOR_MODEL_NAME: str = "anthropic/claude-haiku-4"  # cheap text-only default
    CORRECTOR_MAX_TOKENS: int = 256
    CORRECTOR_TIMEOUT_SECONDS: int = 30

    # Performance Defaults
    MAX_WORKERS: int = 5
    MAX_RETRIES: int = 4
    RETRY_DELAY_BASE: float = 1.0
    BATCH_SIZE_HINT: int = 500

    # Extraction Configuration
    FIELD_KEYS: List[str] = [
        "Komponist", "Signatur", "Titel", "Textanfang",
        "Verlag", "Material", "Textdichter", "Bearbeiter", "Bemerkungen"
    ]

    EXTRACTION_PROMPT: str = """Du bist ein Experte für die Digitalisierung historischer Archivkarteikarten.

Deine Aufgabe ist es, die Informationen von der Karteikarte präzise zu extrahieren. 
Achte besonders auf die Handschrift und mögliche Streichungen.

**Regeln für die Extraktion:**
1. **Komponist**: Der Name des Komponisten (z.B. "Bach, Johann Sebastian").
2. **Signatur**: Die Standortnummer oder das Aktenzeichen (z.B. "Spez. 12.345" oder "RTSO 101").
3. **Titel**: Der Titel des Musikstücks oder Werkes.
4. **Textanfang**: Die ersten Worte des Textes oder des Liedanfangs.
5. **Verlag**: Name des Verlags oder der Druckerei, falls angegeben.
6. **Material**: Beschreibung des Materials (z.B. "Ms." für Manuskript, "Druck").
7. **Textdichter**: Der Verfasser des Liedtextes oder Librettos.
8. **Bearbeiter**: Arrangeur oder Herausgeber der vorliegenden Fassung.
9. **Bemerkungen**: Zusätzliche Informationen, Anmerkungen oder Besonderheiten auf der Karte.

Falls ein Feld nicht auf der Karte vorhanden ist oder nicht entziffert werden kann, verwende einen leeren String ("").
Ändere nichts an der Schreibweise historischer Begriffe, außer bei offensichtlichen Tippfehlern.

**AUSGABEFORMAT:** Antworte NUR mit einem validen JSON-Objekt.
"""

    class Config:
        env_file = ("../../.env", ".env")  # repo root first, then local fallback
        case_sensitive = True

settings = Settings()


def get_settings() -> Settings:
    """Dependency-injectable settings accessor for FastAPI endpoints."""
    return settings
