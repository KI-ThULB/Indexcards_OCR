import asyncio
import base64
import io
import json
import logging
import random
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from PIL import Image
from app.core.checkpoint import completed_filenames, read_checkpoint, write_checkpoint
from app.core.config import settings
from app.core.images import iter_image_files
from app.services.validation import groups as group_util

logger = logging.getLogger(__name__)

class OcrEngine:
    def __init__(self, api_key: Optional[str] = None):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.api_key = api_key or settings.OPENROUTER_API_KEY
        
    def _encode_image_to_base64(self, image_path: Path, max_size: Optional[int] = 1600) -> str:
        """Kodiert ein Bild als Base64; optional vorheriges Resize."""
        if max_size:
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

    def _extract_json_from_model_content(self, content: str) -> str:
        """Entfernt Markdown-Fences und extrahiert sauberes JSON (Objekt oder Array).

        Behandelt:
        - Code-Fences (```json ... ```)
        - Trailing Text nach dem JSON (z. B. "Hinweis: ...")
        - Vorangestellten Text vor dem JSON
        """
        content = content.strip()

        # 1. Markdown-Code-Fences entfernen
        if content.startswith("```"):
            parts = content.split("```")
            for p in reversed(parts):
                p = p.strip()
                if p:
                    if p.startswith("json"):
                        p = p[4:].strip()
                    content = p
                    break
        content = content.strip()

        # 2. JSON-Grenzen ermitteln und auf den reinen JSON-Block trimmen
        if content.startswith("["):
            end = content.rfind("]")
            if end != -1:
                content = content[:end + 1]
        elif content.startswith("{"):
            end = content.rfind("}")
            if end != -1:
                content = content[:end + 1]
        else:
            # Weder [ noch { am Anfang → erstes Vorkommen suchen
            start_brace = content.find("{")
            start_bracket = content.find("[")
            if start_bracket != -1 and (start_brace == -1 or start_bracket < start_brace):
                end = content.rfind("]")
                if end != -1:
                    content = content[start_bracket:end + 1]
            elif start_brace != -1:
                end = content.rfind("}")
                if end != -1:
                    content = content[start_brace:end + 1]

        return content

    @staticmethod
    def _coerce_confidence(value: Any) -> Optional[float]:
        """Coerce a model-supplied confidence to a float in [0,1], or None if unusable."""
        try:
            f = float(value)
        except (TypeError, ValueError):
            return None
        if f != f:  # NaN
            return None
        return max(0.0, min(1.0, f))

    def _split_extraction(
        self, parsed: Any, field_groups: Optional[Dict[str, Any]] = None
    ) -> Tuple[Dict[str, Any], Dict[str, float], Optional[float]]:
        """Split a parsed VLM response into (fields, confidence, overall).

        Handles both the wrapped shape {fields, confidence, confidence_overall} and the
        legacy flat shape {field: value}. Defensive by design: a model that ignores the
        confidence contract still yields usable fields (with empty confidence), so
        extraction never breaks on response shape.
        """
        if isinstance(parsed, dict) and isinstance(parsed.get("fields"), dict):
            fields = parsed["fields"]
            raw_conf = parsed.get("confidence") or {}
            overall = self._coerce_confidence(parsed.get("confidence_overall"))
        else:
            # Legacy / flat object → treat the whole thing as fields, no confidence.
            fields = parsed if isinstance(parsed, dict) else {}
            raw_conf = {}
            overall = None

        # Keep only confidences for keys that are actually present as fields, coerced to [0,1].
        # A repeatable group may additionally report per-child confidence under a
        # flattened key ("Titel_Tracks[0].Titel"); accept those when the group and
        # child are defined, so the existing Dict[str, float] carries them without
        # a second confidence model.
        groups = field_groups or {}
        confidence: Dict[str, float] = {}
        if isinstance(raw_conf, dict):
            for k, v in raw_conf.items():
                if k not in fields and not self._is_known_child_key(k, groups):
                    continue
                c = self._coerce_confidence(v)
                if c is not None:
                    confidence[k] = c
        return fields, confidence, overall

    @staticmethod
    def _is_known_child_key(key: str, field_groups: Dict[str, Any]) -> bool:
        """True for a flattened confidence key naming a defined group and child."""
        parsed = group_util.parse_child_key(key)
        if parsed is None:
            return False
        group, _index, child = parsed
        definition = field_groups.get(group)
        return definition is not None and child in group_util.child_names(definition)

    def _validate_extraction(self, parsed: dict) -> Tuple[bool, List[str]]:
        """Einfache Validierung gegen das Schema."""
        errors = []
        if not isinstance(parsed, dict):
            return False, ["Parsed object is not a dict"]
        for k in settings.FIELD_KEYS:
            if k in parsed and not isinstance(parsed[k], str):
                errors.append(f"Field {k} not a string")
        return (len(errors) == 0), errors

    def _validate_signature(self, signature: Optional[str]) -> bool:
        if not signature:
            return False
        patterns = [
            r'^Spez\.\d{1,2}\.\d{3,4}(\s+[a-z])?$',
            r'^(RTSO|RTOB|TOB)\s+\d{3,4}$'
        ]
        return any(re.match(p, signature) for p in patterns)

    # Field name used to hold the AI-generated description of a picture/drawing/photo
    # found on a card (feature: opt-in picture description). Kept as a module-level
    # constant so the engine, config plumbing and tests agree on the exact key.
    PICTURE_FIELD = "Bildbeschreibung"

    def _group_instruction_block(
        self, fields: List[str], field_groups: Optional[Dict[str, Any]]
    ) -> str:
        """Instructions for repeatable groups. Empty string when none are defined.

        Deliberately gated: a scalar-only template must produce a byte-identical
        prompt to before this feature existed, so nothing here is emitted unless
        the template actually declares a group.

        The name-collision block is derived, not hard-coded per template: whenever
        a scalar field's name contains a group child's name (AMIGA's
        "Gesamttitel" vs. the group's "Titel", "Gesamtspieldauer" vs.
        "Spieldauer"), the model is told explicitly that they are different
        things and that the summary value must never suppress the individual
        ones. That is the failure mode this whole feature exists to prevent.
        """
        if not field_groups:
            return ""

        blocks: List[str] = []
        for label, group in field_groups.items():
            children = group_util.child_names(group)
            if not children:
                continue
            description = ""
            desc = getattr(group, "description", None)
            if desc is None and isinstance(group, dict):
                desc = group.get("description")
            if desc:
                description = f" — {desc}"
            child_list = ", ".join(f'"{c}"' for c in children)

            lines = [
                f'\n**Wiederholbare Gruppe „{label}"**{description}',
                f'- "{label}" ist eine **Liste von Objekten** mit genau diesen Schlüsseln: {child_list}.',
                "- Es können **keine, eine oder mehrere** Einträge vorhanden sein.",
                "- Extrahiere **jeden sichtbaren Eintrag**, auch wenn es viele sind.",
                "- Bewahre die **Reihenfolge des Dokuments**.",
                "- Werte, die visuell zur **selben Zeile/Position** gehören, müssen im selben "
                "Objekt bleiben. Nutze Zeilenausrichtung, Numerierung und Layout-Bezüge.",
                "- Fasse **niemals mehrere Einträge zu einem zusammen**.",
                "- Fehlt ein Kindwert, lass ihn **leer** (\"\") und verschiebe **nicht** die "
                "Werte der folgenden Einträge nach oben.",
                "- **Erfinde keine Einträge und keine Kindwerte.** Gib nur zurück, was zu sehen ist.",
                "- **Berechne und schätze nichts** — auch keine fehlenden Zahlenwerte.",
            ]

            # Derived disambiguation for summary-vs-item field pairs.
            for child in children:
                for scalar in fields:
                    if scalar == label or scalar in children:
                        continue
                    if child.lower() in scalar.lower() and child.lower() != scalar.lower():
                        lines.append(
                            f'- „{scalar}" (Einzelfeld) und „{label}[*].{child}" (Gruppe) sind '
                            f'**verschiedene Angaben**. Ein vorhandener Wert in „{scalar}" darf '
                            f'**niemals** dazu führen, dass „{child}"-Werte der Gruppe weggelassen '
                            f'oder zusammengefasst werden. Erfasse **beides** getrennt.'
                        )
            blocks.append("\n".join(lines))

        return "\n" + "\n".join(blocks) + "\n" if blocks else ""

    def _output_contract_block(
        self,
        fields: List[str],
        describe_pictures: bool,
        field_groups: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Shared instruction appended to every prompt: return a wrapped JSON object
        carrying values, per-field confidence, and an overall confidence. Instructing
        the model to self-report confidence lets the curator triage weak extractions.
        Parsing is defensive (see _split_extraction), so a model that ignores this and
        returns a flat object still works — it just yields no confidence.

        Repeatable groups are rendered as an array-of-objects illustration and get
        their own instruction block; scalar-only templates are unaffected."""
        groups = field_groups or {}
        if not groups:
            # No groups: reproduce the pre-feature rendering byte-for-byte, so
            # every existing scalar template keeps its exact prompt and its
            # extraction behaviour is untouched.
            field_list = ", ".join(f'"{f}"' for f in fields) if fields else '"…"'
            if describe_pictures:
                field_list += ', "' + self.PICTURE_FIELD + '"'
        else:
            # With groups the illustration must show the nesting, so each field is
            # rendered on its own line and a group as an array of objects.
            rendered: List[str] = []
            for f in fields:
                group = groups.get(f)
                if group is not None:
                    children = group_util.child_names(group)
                    if children:
                        obj = ", ".join(f'"{c}": "…"' for c in children)
                        rendered.append(f'"{f}": [ {{ {obj} }}, … ]')
                        continue
                rendered.append(f'"{f}": "…"')
            if describe_pictures:
                rendered.append(f'"{self.PICTURE_FIELD}": "…"')
            field_list = ",\n    ".join(rendered) if rendered else '"…": "…"'

        confidence_hint = (
            '<derselbe Schlüssel>: <Zahl 0.0–1.0> für jedes Feld'
            if not groups else
            '<derselbe Schlüssel>: <Zahl 0.0–1.0> für jedes Feld; '
            'für Kindwerte einer Gruppe im Format "Gruppe[0].Kind"'
        )
        picture_line = ""
        if describe_pictures:
            picture_line = (
                f'\n- Prüfe, ob auf der Karte ein Bild, eine Zeichnung oder ein Foto zu sehen ist. '
                f'Falls ja, beschreibe in "{self.PICTURE_FIELD}" knapp auf Deutsch, was darauf dargestellt ist '
                f'(1–2 Sätze). Falls kein Bild vorhanden ist, verwende einen leeren String ("").'
            )
        fields_section = (
            f'  "fields": {{ {field_list} }},'
            if not groups
            else f'  "fields": {{\n    {field_list}\n  }},'
        )
        return f"""

**AUSGABEFORMAT:** Antworte NUR mit einem validen JSON-Objekt in genau dieser Struktur:
{{
{fields_section}
  "confidence": {{ {confidence_hint} }},
  "confidence_overall": <Zahl 0.0–1.0>
}}
- "fields" enthält die extrahierten Werte (leerer String, wenn nicht vorhanden/lesbar).
- "confidence" gibt für JEDES Feld an, wie sicher du dir des Wertes bist (1.0 = sehr sicher, 0.0 = geraten).
- "confidence_overall" ist deine Gesamtsicherheit für diese Karte.{picture_line}
{self._group_instruction_block(fields, field_groups)}"""

    def _generate_prompt(
        self,
        fields: List[str],
        template: Optional[str] = None,
        describe_pictures: bool = False,
        field_groups: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Generiert einen dynamischen Prompt basierend auf den gewünschten Feldern.

        If template is provided, renders it by substituting {{fields}} with the fields block.
        If {{fields}} is not present in the template, the fields block is appended.
        If template is None, falls back to the default hardcoded German prompt.
        In all cases the confidence/output contract (and optional picture instruction) is appended.
        """
        groups = field_groups or {}
        lines: List[str] = []
        for i, field in enumerate(fields):
            group = groups.get(field)
            children = group_util.child_names(group) if group is not None else []
            if children:
                desc = getattr(group, "description", None)
                if desc is None and isinstance(group, dict):
                    desc = group.get("description")
                suffix = f" {desc}" if desc else ""
                lines.append(
                    f"{i+1}. **{field}** (wiederholbare Gruppe):{suffix} "
                    f"Erfasse jeden sichtbaren Eintrag als eigenes Objekt mit den Feldern "
                    + ", ".join(f"'{c}'" for c in children)
                    + "."
                )
            else:
                lines.append(f"{i+1}. **{field}**: Extrahiere den Wert für das Feld '{field}'.")
        fields_block = "\n".join(lines)
        contract = self._output_contract_block(fields, describe_pictures, field_groups)

        if template is not None:
            if "{{fields}}" in template:
                return template.replace("{{fields}}", fields_block) + contract
            else:
                return template + "\n\n" + fields_block + contract

        return f"""Du bist ein Experte für die Digitalisierung historischer Archivkarteikarten.

Deine Aufgabe ist es, die Informationen von der Karteikarte präzise zu extrahieren.
Achte besonders auf die Handschrift und mögliche Streichungen.

**Extrahiere folgende Felder:**
{fields_block}

Falls ein Feld nicht auf der Karte vorhanden ist oder nicht entziffert werden kann, verwende einen leeren String ("").
Ändere nichts an der Schreibweise historischer Begriffe, außer bei offensichtlichen Tippfehlern.
{contract}"""

    def _call_vlm_api_resilient(
        self,
        image_path: Path,
        fields: Optional[List[str]] = None,
        max_size: Optional[int] = 1600,
        prompt_template: Optional[str] = None,
        api_endpoint: Optional[str] = None,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        describe_pictures: bool = False,
        field_groups: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """Resilienter API-Aufruf: Session, exponential backoff with jitter."""
        resolved_endpoint = api_endpoint or settings.API_ENDPOINT
        resolved_model = model_name or settings.MODEL_NAME
        resolved_key = api_key if api_key is not None else self.api_key

        if not resolved_key:
            return None, "API Key missing"

        base64_image = self._encode_image_to_base64(image_path, max_size=max_size)
        headers = {"Authorization": f"Bearer {resolved_key}"}

        # Always build a prompt so the confidence contract is included. When no explicit
        # field list is given, fall back to the default FIELD_KEYS.
        prompt = self._generate_prompt(
            fields or settings.FIELD_KEYS,
            template=prompt_template,
            describe_pictures=describe_pictures,
            field_groups=field_groups,
        )

        payload = {
            "model": resolved_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ],
            "temperature": 0.1,
            "max_tokens": 4096
        }

        max_retries = settings.MAX_RETRIES
        attempt = 0
        while attempt < max_retries:
            try:
                resp = self.session.post(
                    resolved_endpoint, headers=headers, json=payload,
                    timeout=settings.VLM_REQUEST_TIMEOUT_SECONDS,
                )

                # --- Explicit HTTP error handling with body capture ---
                if resp.status_code >= 400:
                    error_msg = f"HTTP {resp.status_code}"
                    try:
                        err_json = resp.json()
                        detail = (
                            err_json.get("error", {}).get("message")
                            or err_json.get("detail")
                            or ""
                        )
                        if detail:
                            error_msg += f": {str(detail)[:250]}"
                        else:
                            body = resp.text[:250].strip()
                            if body:
                                error_msg += f": {body}"
                    except Exception:
                        body = resp.text[:250].strip()
                        if body:
                            error_msg += f": {body}"

                    if resp.status_code == 401:
                        return None, "Ungültiger API Key (401)"
                    if resp.status_code == 429:
                        ra = resp.headers.get("Retry-After")
                        wait = float(ra) if ra and ra.isdigit() else (2 ** attempt) + random.random()
                        logger.warning(f"Rate limit (429). Sleeping {wait:.1f}s (attempt {attempt + 1}/{max_retries})")
                        time.sleep(wait)
                        attempt += 1
                        continue
                    if resp.status_code >= 500:
                        # Server error — retry with backoff
                        wait = (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(f"{error_msg}. Retrying in {wait:.1f}s (attempt {attempt+1}/{max_retries})")
                        time.sleep(wait)
                        attempt += 1
                        continue
                    # 4xx client error (except 401/429) — no point retrying
                    return None, error_msg

                result = resp.json()
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"]
                    cleaned = self._extract_json_from_model_content(content)
                    try:
                        parsed = json.loads(cleaned)
                    except json.JSONDecodeError:
                        raw_preview = cleaned[:120].replace("\n", " ")
                        logger.warning(f"JSON decode failed for {image_path.name}: {raw_preview}")
                        return None, f"JSON-Parsing fehlgeschlagen. Antwort: {raw_preview}"
                    return parsed, None
                else:
                    return None, "Keine Antwort vom Modell (leere choices)"
            except requests.exceptions.ConnectionError as e:
                wait = (2 ** attempt) + random.uniform(0, 1)
                logger.warning(f"Verbindungsfehler: {e}. Retrying in {wait:.1f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                attempt += 1
            except requests.exceptions.Timeout:
                wait = (2 ** attempt) + random.uniform(0, 1)
                logger.warning(f"Timeout. Retrying in {wait:.1f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                attempt += 1
            except requests.exceptions.RequestException as e:
                wait = (2 ** attempt) + random.uniform(0, 1)
                logger.warning(f"RequestException: {e}. Retrying in {wait:.1f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                attempt += 1
            except Exception as e:
                logger.exception(f"Unexpected error in _call_vlm_api_resilient: {e}")
                return None, str(e)
        return None, f"Max. Versuche ({max_retries}) erreicht – API antwortet nicht"

    def _process_card_sync(
        self,
        image_path: Path,
        batch_name: str,
        fields: Optional[List[str]] = None,
        max_size: Optional[int] = 1600,
        prompt_template: Optional[str] = None,
        api_endpoint: Optional[str] = None,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        field_rules: Optional[Dict[str, dict]] = None,
        corrector_enabled: bool = False,
        cap_state: Optional[dict] = None,
        describe_pictures: bool = False,
        field_groups: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Synchronous card processing logic."""
        start_time = time.time()
        filename = image_path.name
        try:
            raw, error = self._call_vlm_api_resilient(
                image_path, fields=fields, max_size=max_size,
                prompt_template=prompt_template,
                api_endpoint=api_endpoint, model_name=model_name, api_key=api_key,
                describe_pictures=describe_pictures,
                field_groups=field_groups,
            )
            duration = time.time() - start_time

            if error:
                logger.error(f"[{batch_name}] {filename} -> {error}")
                return {
                    "filename": filename,
                    "batch": batch_name,
                    "success": False,
                    "error": error,
                    "duration": duration
                }

            # Handle multi-entry pages (AI returned a JSON array, e.g. Findmittel).
            # Confidence is skipped for multi-entry in v1 (same carve-out as validation).
            if isinstance(raw, list):
                entry_count = len(raw)
                data = {
                    "_entries": json.dumps(raw, ensure_ascii=False),
                    "_entry_count": str(entry_count),
                    "Datei": filename,
                    "Batch": batch_name,
                }
                return {
                    "filename": filename,
                    "batch": batch_name,
                    "success": True,
                    "data": data,
                    "duration": time.time() - start_time,
                    "validation_errors": [],
                    "validation": None,  # v1: skip validation for multi-entry results
                    "confidence": None,
                    "confidence_overall": None,
                }

            # Split wrapped {fields, confidence, confidence_overall} — or legacy flat dict.
            data, confidence, confidence_overall = self._split_extraction(raw, field_groups)

            # Enrich metadata (single-entry / dict response)
            if data is None:
                data = {}

            # Repeatable groups: coerce each defined group into safe canonical items
            # and store them as a JSON string, because data is Dict[str, str] and
            # rejects nested values. normalise_group never raises, so a malformed
            # group degrades to an empty group with a validation outcome instead of
            # failing the card (and, in a bulk run, the whole collection).
            group_outcomes: Dict[str, Any] = {}
            for label, definition in (field_groups or {}).items():
                items, problems = group_util.normalise_group(data.get(label), definition)
                data[label] = group_util.serialise_group(items)
                group_outcomes[label] = group_util.outcome_for(problems)
                if problems:
                    logger.info(
                        "[%s] %s: group %r normalised with problems: %s",
                        batch_name, filename, label, ", ".join(sorted(set(problems))),
                    )

            data["Datei"] = filename
            data["Batch"] = batch_name

            # Existing schema validation
            ok, v_errors = self._validate_extraction(data)

            # Phase 8: per-field validation rules
            validation_outcomes = {}
            try:
                if field_rules:
                    from app.services.validation.runner import run_validation
                    resolved_cap_state = cap_state or {"used": 0, "cap": 100, "lock": None}
                    validation_outcomes = run_validation(
                        data=data,
                        field_rules=field_rules,
                        corrector_enabled=corrector_enabled,
                        cap_state=resolved_cap_state,
                        api_key=api_key or self.api_key or "",
                        skip_fields=list(field_groups or {}),
                    )
            except Exception as e:
                import logging as _logging
                _logging.getLogger(__name__).warning(f"Validation error for {filename}: {e}")
                validation_outcomes = {}

            # Group shape outcomes sit alongside the per-field rule outcomes. They
            # win for a group label, since a scalar rule cannot meaningfully apply
            # to a serialised array.
            if group_outcomes:
                validation_outcomes = {**validation_outcomes, **group_outcomes}

            return {
                "filename": filename,
                "batch": batch_name,
                "success": True,
                "data": data,
                "duration": duration,
                "has_komponist": bool(data.get("Komponist", "").strip()),
                "has_signatur": bool(data.get("Signatur", "").strip()),
                "valid_signatur": self._validate_signature(data.get("Signatur", "")),
                "validation_errors": v_errors if not ok else [],
                "validation": validation_outcomes or None,
                "confidence": confidence or None,
                "confidence_overall": confidence_overall,
            }
        except Exception as e:
            logger.exception(f"Unexpected error processing card {filename}: {e}")
            return {
                "filename": filename,
                "batch": batch_name,
                "success": False,
                "error": str(e),
                "duration": time.time() - start_time
            }

    async def process_card(self, image_path: Path, batch_name: str, fields: Optional[List[str]] = None, max_size: Optional[int] = 1600) -> Dict[str, Any]:
        """Async wrapper for process_card_sync."""
        return await asyncio.to_thread(self._process_card_sync, image_path, batch_name, fields, max_size)

    async def process_batch(
        self,
        batch_dir: Path,
        fields: Optional[List[str]] = None,
        max_size: Optional[int] = 1600,
        progress_callback: Optional[Callable[[str, Any], Any]] = None,
        resume: bool = True,
        cancel_event: Optional[threading.Event] = None,
        prompt_template: Optional[str] = None,
        api_endpoint: Optional[str] = None,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        field_rules: Optional[Dict[str, dict]] = None,
        corrector_enabled: bool = False,
        corrector_cap: int = 100,
        describe_pictures: bool = False,
        field_groups: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Processes an entire batch of images asynchronously using a thread pool."""
        batch_name = batch_dir.name
        image_files = iter_image_files(batch_dir)

        if not image_files:
            logger.warning(f"No images found in {batch_dir}")
            return []

        # Error directory
        error_dir = batch_dir / "_errors"
        error_dir.mkdir(parents=True, exist_ok=True)

        # Checkpoint handling — one canonical format for both writers, so viewing
        # a batch's results can no longer break a later resume (see app/core/checkpoint.py).
        checkpoint_path = batch_dir / "checkpoint.json"
        completed_files: set = set()
        results: List[Dict[str, Any]] = []
        # Curator audit entries live alongside the results and must survive a
        # resume/retry untouched — the engine used to write a bare list and drop them.
        audit: List[Dict[str, Any]] = []
        if resume and checkpoint_path.exists():
            try:
                results, audit = read_checkpoint(checkpoint_path)
                completed_files = completed_filenames(results)
                logger.info(f"Resuming batch {batch_name}: {len(completed_files)} already successfully processed")
            except Exception as e:
                logger.error(f"Failed to read checkpoint for {batch_name}: {e}")
                results, audit = [], []

        files_to_process = [f for f in image_files if f.name not in completed_files]
        if not files_to_process:
            logger.info(f"Batch {batch_name} already fully processed")
            return results

        total = len(image_files)
        start_time = time.time()

        # Helper to update checkpoint (atomic write, existing audit carried through)
        def _save_checkpoint(current_results):
            try:
                write_checkpoint(checkpoint_path, current_results, audit)
            except Exception as e:
                logger.error(f"Failed to save checkpoint for {batch_name}: {e}")

        # Capture the running event loop here (in the async context) before entering the thread
        loop = asyncio.get_running_loop()

        # Build per-batch cap_state for corrector (thread-safe counter shared across workers)
        cap_state = {"used": 0, "cap": corrector_cap or 100, "lock": threading.Lock()}

        # Use to_thread for the whole pool execution to avoid blocking the event loop
        def _run_batch():
            # Use a dict to track results by filename to handle replacements (retries)
            res_map = {r["filename"]: r for r in results}

            # Not a `with` block: leaving one calls shutdown(wait=True) without
            # cancel_futures, which drains every queued card. A cancelled batch
            # would then keep sending images to the provider long after the stop
            # — for a refused credential or an exhausted balance, hundreds of
            # them. The finally below cancels whatever has not started yet.
            executor = ThreadPoolExecutor(max_workers=settings.MAX_WORKERS)
            try:
                futures = {
                    executor.submit(
                        self._process_card_sync, img, batch_name, fields, max_size,
                        prompt_template, api_endpoint, model_name, api_key,
                        field_rules, corrector_enabled, cap_state, describe_pictures,
                        field_groups
                    ): img
                    for img in files_to_process
                }
                for i, fut in enumerate(as_completed(futures), len(completed_files) + 1):
                    res = fut.result()

                    # Error handling: move failed cards to _errors/
                    if not res.get("success", False):
                        img_path = futures[fut]
                        try:
                            import shutil
                            shutil.move(str(img_path), str(error_dir / img_path.name))
                            logger.info(f"Moved failed card {img_path.name} to {error_dir}")
                        except Exception as e:
                            logger.error(f"Failed to move {img_path.name} to errors: {e}")

                    res_map[res["filename"]] = res
                    current_results = list(res_map.values())
                    _save_checkpoint(current_results)

                    # Cooperative cancellation: check after each image + checkpoint save
                    if cancel_event and cancel_event.is_set():
                        logger.info(f"Batch {batch_name} cancelled by user after {i} images")
                        break

                    if progress_callback:
                        elapsed = time.time() - start_time
                        processed_count = i - len(completed_files)
                        avg_time = elapsed / processed_count if processed_count > 0 else 0
                        remaining_count = total - i
                        eta = avg_time * remaining_count

                        from app.models.schemas import BatchProgress, ExtractionResult

                        # Prepare progress data
                        progress_data = BatchProgress(
                            batch_name=batch_name,
                            current=i,
                            total=total,
                            percentage=round((i / total) * 100, 2),
                            eta_seconds=round(eta, 1),
                            last_result=ExtractionResult(**res),
                            status="running"
                        )

                        # Call the callback via the main loop's thread-safe method if it's async
                        if asyncio.iscoroutinefunction(progress_callback):
                            asyncio.run_coroutine_threadsafe(
                                progress_callback(batch_name, progress_data),
                                loop
                            )
                        else:
                            progress_callback(batch_name, progress_data)
            finally:
                # cancel_futures drops cards that have not started yet; cards
                # already running still finish and are checkpointed, so nothing
                # extracted is lost and a resume simply picks up the rest.
                executor.shutdown(wait=True, cancel_futures=True)
            return list(res_map.values())

        return await asyncio.to_thread(_run_batch)

ocr_engine = OcrEngine()
