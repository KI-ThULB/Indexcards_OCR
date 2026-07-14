#!/usr/bin/env python3
"""
Verbessertes Batch-Processing für Karteikarten mit Qwen3 VL über OpenRouter

Wesentliche Änderungen gegenüber Original:
- requests.Session() für Connection-Pooling
- Exponentielles Backoff mit Jitter & Retry-After-Handling
- JSON-basiertes Checkpointing (lesbar & robust)
- logging (RotatingFileHandler) statt print+manuelle Logdatei
- JSON-Schema-Validierung der Modellantworten
- optionales Image-Resizing vor Base64-Encoding (Pillow)
- argparse CLI / ENV-API-Key Unterstützung
"""

import os
import io
import json
import base64
import time
import random
import argparse
import logging
import logging.handlers
import traceback
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List, Dict, Set, Tuple, Any

import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from config import (
    DEFAULT_INPUT_DIR, OUTPUT_BASE, JSON_OUT_BASE, CSV_OUT_BASE,
    FINAL_CSV, CHECKPOINT_JSON, PROGRESS_FILE, LOG_FILE,
    API_BASE_URL, API_ENDPOINT, MODEL_NAME,
    MAX_WORKERS, MAX_RETRIES, RETRY_DELAY_BASE, BATCH_SIZE_HINT,
    FIELD_KEYS, EXTRACTION_PROMPT, EXTRACTION_SCHEMA
)

# optional: Pillow für Resize (wenn nicht installiert, bleibt Funktion deaktiviert)
try:
    from PIL import Image
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

# Ensure output dirs
os.makedirs(JSON_OUT_BASE, exist_ok=True)
os.makedirs(CSV_OUT_BASE, exist_ok=True)
os.makedirs(OUTPUT_BASE, exist_ok=True)

# === Logging ===
logger = logging.getLogger("vlm_pipeline")
logger.setLevel(logging.INFO)
fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
fh = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=10_000_000, backupCount=5, encoding="utf-8")
fh.setFormatter(fmt)
sh = logging.StreamHandler()
sh.setFormatter(fmt)
logger.addHandler(fh)
logger.addHandler(sh)

# === Session (Connection Pooling) ===
_session = requests.Session()
_session.headers.update({"Content-Type": "application/json"})

# === Hilfsfunktionen ===

def format_time(seconds):
    return str(timedelta(seconds=int(seconds)))

def encode_image_to_base64(image_path: Path, max_size: Optional[int] = None) -> str:
    """Kodiert ein Bild als Base64; optional vorheriges Resize (falls Pillow installiert)."""
    if max_size and PIL_AVAILABLE:
        try:
            img = Image.open(image_path)
            img.thumbnail((max_size, max_size))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception as e:
            logger.warning(f"Resize failed for {image_path}: {e} — fallback to raw")
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def save_checkpoint_json(cp: dict):
    """Speichert checkpoint als JSON (lesbar). Expect {batch_name: [filenames,...]}"""
    try:
        serial = {k: list(v) for k, v in cp.items()}
        with open(CHECKPOINT_JSON, "w", encoding="utf-8") as fh:
            json.dump(serial, fh, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception(f"Fehler beim Speichern des Checkpoints: {e}")

def load_checkpoint_json() -> dict:
    if not os.path.exists(CHECKPOINT_JSON):
        return {}
    try:
        with open(CHECKPOINT_JSON, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return {k: set(v) for k, v in raw.items()}
    except Exception as e:
        logger.warning(f"Fehler beim Laden des Checkpoints: {e}")
        return {}

def save_progress(progress: dict):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as fh:
        json.dump(progress, fh, ensure_ascii=False, indent=2)

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}
    return {}

def validate_signature(signature: Optional[str]) -> bool:
    if not signature:
        return False
    import re
    patterns = [
        r'^Spez\.\d{1,2}\.\d{3,4}(\s+[a-z])?$',
        r'^(RTSO|RTOB|TOB)\s+\d{3,4}$'
    ]
    return any(re.match(p, signature) for p in patterns)

def extract_json_from_model_content(content: str) -> str:
    """Entfernt Markdown-Fences und versucht, sauberes JSON zu extrahieren."""
    content = content.strip()
    # Entferne ```json ... ``` oder ``` ... ```
    if content.startswith("```"):
        parts = content.split("```")
        # take last non-empty part
        for p in reversed(parts):
            if p.strip():
                content = p.strip()
                break
    # fallback: try to find first { and last }
    if not content.startswith("{"):
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            content = content[start:end+1]
    return content

def validate_extraction(parsed: dict) -> (bool, list):
    """Einfache Validierung gegen das Schema (keine Abhängigkeit notwendig)."""
    errors = []
    if not isinstance(parsed, dict):
        return False, ["Parsed object is not a dict"]
    for k in FIELD_KEYS:
        if k in parsed and not isinstance(parsed[k], str):
            errors.append(f"Field {k} not a string")
    return (len(errors) == 0), errors

# === Resiliente API-Aufrufe ===

def call_vlm_api_resilient(image_path: Path, api_key: str, max_retries: int = MAX_RETRIES, max_size: Optional[int] = None):
    """
    Resilienter API-Aufruf: Session, exponential backoff with jitter, Retry-After handling.
    Return: (parsed_dict or None, error_message or None)
    """
    base64_image = encode_image_to_base64(image_path, max_size=max_size)
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": EXTRACTION_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }
        ],
        "temperature": 0.1,
        "max_tokens": 1200
    }

    attempt = 0
    while attempt < max_retries:
        try:
            resp = _session.post(API_ENDPOINT, headers=headers, json=payload, timeout=120)
            if resp.status_code == 429:
                ra = resp.headers.get("Retry-After")
                wait = float(ra) if ra and ra.isdigit() else (2 ** attempt) + random.random()
                logger.warning(f"Rate limit (429). Sleeping {wait:.1f}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
                attempt += 1
                continue
            resp.raise_for_status()
            result = resp.json()
            if "choices" in result and len(result["choices"]) > 0:
                content = result["choices"][0]["message"]["content"]
                cleaned = extract_json_from_model_content(content)
                try:
                    parsed = json.loads(cleaned)
                except json.JSONDecodeError:
                    logger.warning(f"JSON decode failed, storing raw content for inspection (file: {image_path.name})")
                    return None, f"JSONDecodeError. RawContentSaved"
                return parsed, None
            else:
                return None, "No choices returned by API"
        except requests.exceptions.RequestException as e:
            wait = (2 ** attempt) + random.uniform(0, 1)
            logger.warning(f"RequestException: {e}. Retrying in {wait:.1f}s (attempt {attempt+1}/{max_retries})")
            time.sleep(wait)
            attempt += 1
        except Exception as e:
            logger.exception(f"Unexpected error in call_vlm_api_resilient: {e}")
            return None, str(e)
    return None, "Max retries reached"

# === Worker & Batch-Processing ===

def process_single_card(image_path: Path, api_key: str, batch_name: str, max_size: Optional[int] = None):
    """Verarbeitet eine einzelne Karteikarte (Worker-Funktion)."""
    start_time = time.time()
    filename = image_path.name
    try:
        data, error = call_vlm_api_resilient(image_path, api_key, max_retries=MAX_RETRIES, max_size=max_size)
        if error:
            logger.error(f"[{batch_name}] {filename} -> {error}")
            return {"filename": filename, "batch": batch_name, "success": False, "error": error, "duration": time.time() - start_time}
        # enrich metadata
        data["Datei"] = filename
        data["Batch"] = batch_name
        # validation
        ok, v_errors = validate_extraction(data)
        if not ok:
            logger.warning(f"[{batch_name}] {filename} parsed but validation warnings: {v_errors}")
            data["_validation_warnings"] = v_errors
        # save JSON per batch
        batch_json_dir = Path(JSON_OUT_BASE) / batch_name
        batch_json_dir.mkdir(parents=True, exist_ok=True)
        json_path = batch_json_dir / f"{image_path.stem}.json"
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        return {
            "filename": filename,
            "batch": batch_name,
            "success": True,
            "data": data,
            "duration": time.time() - start_time,
            "has_komponist": bool(data.get("Komponist", "").strip()),
            "has_signatur": bool(data.get("Signatur", "").strip()),
            "valid_signatur": validate_signature(data.get("Signatur", ""))
        }
    except Exception as e:
        logger.exception(f"Unexpected error processing card {filename}: {e}")
        return {"filename": filename, "batch": batch_name, "success": False, "error": str(e), "duration": time.time() - start_time}

def process_single_batch(batch_dir: Path, api_key: str, batch_number: int, total_batches: int, max_size: Optional[int] = None):
    batch_name = batch_dir.name
    logger.info("="*80)
    logger.info(f"Processing batch {batch_number}/{total_batches}: {batch_name}")
    # load checkpoint and processed files
    checkpoint = load_checkpoint_json()
    processed_files = checkpoint.get(batch_name, set())
    all_files = sorted(list(batch_dir.glob("*.jpg")) + list(batch_dir.glob("*.jpeg")))
    image_files = [f for f in all_files if f.name not in processed_files]
    total = len(image_files)
    already_processed = len(all_files) - total
    if total == 0:
        if already_processed > 0:
            logger.info(f"Batch {batch_name} already complete ({already_processed} files)")
        else:
            logger.warning(f"No images found in {batch_dir}")
        return None

    logger.info(f"Found {total} new images in {batch_name} (workers={MAX_WORKERS})")
    records = []
    success_count = error_count = komponist_count = signatur_count = valid_signatur_count = 0

    batch_start = time.time()
    processed_count = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_single_card, img, api_key, batch_name, max_size): img for img in image_files}
        for fut in as_completed(futures):
            res = fut.result()
            processed_count += 1
            if res["success"]:
                success_count += 1
                records.append(res["data"])
                processed_files.add(res["filename"])
                if res.get("has_komponist"):
                    komponist_count += 1
                if res.get("has_signatur"):
                    signatur_count += 1
                if res.get("valid_signatur"):
                    valid_signatur_count += 1
            else:
                error_count += 1
                logger.error(f"[{batch_name}] {res['filename']} failed: {res.get('error')}")
            # progress & checkpointing
            if processed_count % 50 == 0 or processed_count == total:
                checkpoint[batch_name] = processed_files
                save_checkpoint_json(checkpoint)
                logger.info(f"[{batch_name}] Progress: {processed_count}/{total} (success: {success_count}, errors: {error_count})")
    batch_duration = time.time() - batch_start
    logger.info(f"Batch {batch_name} completed in {format_time(batch_duration)} — success {success_count}/{total}")

    if records:
        df = pd.DataFrame(records)
        cols = ["Datei", "Batch", "Signatur", "Komponist"] + [k for k in FIELD_KEYS if k not in ["Signatur", "Komponist"] and k in df.columns]
        df = df[cols]
        csv_path = os.path.join(CSV_OUT_BASE, f"{batch_name}.csv")
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        logger.info(f"Saved batch CSV: {csv_path}")
        checkpoint[batch_name] = processed_files
        save_checkpoint_json(checkpoint)
        return {
            "batch_name": batch_name,
            "total_cards": len(all_files),
            "processed": total,
            "success": success_count,
            "errors": error_count,
            "duration": batch_duration,
            "csv_file": csv_path,
            "komponist_found": komponist_count,
            "signatur_found": signatur_count,
            "valid_signatur": valid_signatur_count
        }
    return None

# === Main Orchestration ===

def process_all_batches(base_input_dir: str, api_key: Optional[str], batch_pattern: str = "*", max_size: Optional[int] = None):
    logger.info("Starting multi-batch OCR pipeline")
    if not api_key:
        logger.error("No API key provided")
        return
    base_path = Path(base_input_dir)
    batch_dirs = sorted([d for d in base_path.glob(batch_pattern) if d.is_dir()])
    if not batch_dirs:
        batch_dirs = sorted([d for d in base_path.iterdir() if d.is_dir()])
    if not batch_dirs:
        logger.error(f"No batch directories found in {base_input_dir}")
        return
    total_batches = len(batch_dirs)
    progress = load_progress()
    completed_batches = progress.get("completed_batches", [])
    overall_start = time.time()
    batch_results = []
    for idx, batch_dir in enumerate(batch_dirs, 1):
        batch_name = batch_dir.name
        if batch_name in completed_batches:
            logger.info(f"Skipping completed batch {batch_name}")
            continue
        try:
            result = process_single_batch(batch_dir, api_key, idx, total_batches, max_size=max_size)
            if result:
                batch_results.append(result)
                completed_batches.append(batch_name)
                progress["completed_batches"] = completed_batches
                progress["last_updated"] = datetime.now().isoformat()
                save_progress(progress)
        except KeyboardInterrupt:
            logger.info("Processing interrupted by user. Progress saved.")
            return
        except Exception as e:
            logger.exception(f"Critical error while processing batch {batch_name}: {e}")
            continue

    # combine CSVs
    csv_files = sorted([f for f in Path(CSV_OUT_BASE).glob("*.csv")])
    if not csv_files:
        logger.warning("No batch CSVs found for combining")
    else:
        all_dfs = []
        for p in csv_files:
            try:
                all_dfs.append(pd.read_csv(p, encoding="utf-8-sig"))
            except Exception as e:
                logger.warning(f"Failed to read {p}: {e}")
        if all_dfs:
            combined_df = pd.concat(all_dfs, ignore_index=True)
            combined_df.to_csv(FINAL_CSV, index=False, encoding="utf-8-sig")
            logger.info(f"Combined CSV saved: {FINAL_CSV} ({len(combined_df):,} rows)")

    total_elapsed = time.time() - overall_start
    logger.info(f"Processing finished in {format_time(total_elapsed)}")
    if len(batch_results) > 0:
        total_cards = sum(r["total_cards"] for r in batch_results)
        total_success = sum(r["success"] for r in batch_results)
        total_errors = sum(r["errors"] for r in batch_results)
        logger.info(f"Total cards: {total_cards:,} — success: {total_success:,} — errors: {total_errors:,}")

    # cleanup checkpoint files if everything done
    progress = load_progress()
    completed_batches = progress.get("completed_batches", [])
    if len(completed_batches) > 0 and len(completed_batches) == total_batches:
        try:
            if os.path.exists(CHECKPOINT_JSON):
                os.remove(CHECKPOINT_JSON)
            if os.path.exists(PROGRESS_FILE):
                os.remove(PROGRESS_FILE)
            logger.info("All batches completed — checkpoint files removed")
        except Exception:
            logger.exception("Failed to remove checkpoint files")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch OCR pipeline for archive index cards with Qwen3 VL via OpenRouter")
    parser.add_argument("--input", "-i", default=DEFAULT_INPUT_DIR, help="Base input directory with batch subfolders")
    parser.add_argument("--pattern", "-p", default="*", help="Glob pattern for batch folders")
    parser.add_argument("--workers", "-w", type=int, default=MAX_WORKERS, help="Number of parallel workers")
    parser.add_argument("--max-size", type=int, default=1600, help="Optional max image size (px) for resizing before upload; 0 to disable")
    parser.add_argument("--api-key", type=str, default=None, help="OpenRouter API key (optional, otherwise env or prompt used)")
    args = parser.parse_args()

    # set globals from CLI
    MAX_WORKERS = args.workers
    max_size = args.max_size if args.max_size and args.max_size > 0 else None

    api_key = args.api_key or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        # secure prompt
        import getpass
        api_key = getpass.getpass("OpenRouter API-Key: ")

    try:
        process_all_batches(args.input, api_key, args.pattern, max_size=max_size)
    except KeyboardInterrupt:
        logger.info("User aborted processing.")
    except Exception as e:
        logger.exception(f"Unhandled exception in main: {e}")
