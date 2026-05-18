from pydantic_settings import BaseSettings
from typing import List
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

    # API Configuration — Ollama (FSU Jena HPC Cluster)
    OLLAMA_API_ENDPOINT: str = "https://ollama.draco.uni-jena.de/v1/chat/completions"
    OLLAMA_MODEL_NAME: str = "qwen3-vl:235b"
    OLLAMA_API_KEY: str = os.getenv("OLLAMA_API_KEY", "ollama")

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
