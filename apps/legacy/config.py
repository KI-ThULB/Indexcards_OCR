import os

# === Directory Configuration ===
DEFAULT_INPUT_DIR = "./input_batches"
OUTPUT_BASE = "output_batches"
JSON_OUT_BASE = os.path.join(OUTPUT_BASE, "json")
CSV_OUT_BASE = os.path.join(OUTPUT_BASE, "csv")
FINAL_CSV = os.path.join(OUTPUT_BASE, "metadata_vlm_complete.csv")
CHECKPOINT_JSON = os.path.join(OUTPUT_BASE, "checkpoint.json")
PROGRESS_FILE = os.path.join(OUTPUT_BASE, "batch_progress.json")
LOG_FILE = os.path.join(OUTPUT_BASE, "vlm_pipeline.log")

# === API Configuration ===
API_BASE_URL = "https://openrouter.ai/api/v1"
API_ENDPOINT = f"{API_BASE_URL}/chat/completions"
MODEL_NAME = "qwen/qwen3-vl-8b-instruct"

# === Performance Defaults ===
MAX_WORKERS = 5
MAX_RETRIES = 4
RETRY_DELAY_BASE = 1.0
BATCH_SIZE_HINT = 500

# === Extraction Configuration ===
FIELD_KEYS = [
    "Komponist", "Signatur", "Titel", "Textanfang",
    "Verlag", "Material", "Textdichter", "Bearbeiter", "Bemerkungen"
]

EXTRACTION_PROMPT = """Du bist ein Experte für die Digitalisierung historischer Archivkarteikarten aus dem Bereich Musik.

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

# === Validation Configuration ===
EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "string"} for k in FIELD_KEYS + ["Datei", "Batch"]},
    "additionalProperties": True
}
