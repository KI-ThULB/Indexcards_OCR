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
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from PIL import Image
from app.core.checkpoint import completed_filenames, read_checkpoint, write_checkpoint
from app.core.config import settings
from app.core.images import iter_image_files
from app.services.validation import groups as group_util

logger = logging.getLogger(__name__)

# ── Model-response failure classes ──────────────────────────────────────────
# Stable codes rather than prose. A card failure is already carried as a single
# ``error`` string through checkpoint.json, the progress WebSocket and the
# failure CSV's Error column, so no exception hierarchy and no schema change is
# needed — but the code embedded in that string lets the orchestrator, the tests
# and an operator tell these cases apart, which one generic
# "JSON-Parsing fehlgeschlagen" could not.
ERROR_NO_CHOICES = "no_choices_in_response"
ERROR_EMPTY_RESPONSE = "empty_model_response"
ERROR_TRUNCATED_RESPONSE = "truncated_model_response"
ERROR_INVALID_JSON = "invalid_json_response"

# Not a failure: a pause or cancel landed before this card reached the model.
# process_batch recognises it and leaves the card completely untouched — no
# checkpoint row and no move to _errors/ — so a resume picks it up normally
# instead of finding it recorded as failed.
ERROR_STOP_REQUESTED = "stop_requested"

# Wait before re-asking the model after it returned something unusable. Short
# and flat: this is not a loaded or unreachable server, so exponential backoff
# would only add latency to a 14,000-card run.
_MODEL_RETRY_DELAY_SECONDS = 1.0


class OcrEngine:
    def __init__(self, api_key: Optional[str] = None):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.api_key = api_key or settings.OPENROUTER_API_KEY
        # Per-worker-thread provider response metadata. This preserves the public
        # two-value return contract of _call_vlm_api_resilient while letting
        # _process_card_sync capture a provider-reported resolved model safely
        # under ThreadPoolExecutor concurrency.
        self._provider_response_meta = threading.local()
        
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

    # ------------------------------------------------------------------ #
    # Provider response evaluation
    # ------------------------------------------------------------------ #
    @staticmethod
    def _reasoning_length(message: Dict[str, Any]) -> int:
        """Characters the provider reported as chain-of-thought, if any.

        Ollama's OpenAI-compatible layer puts a reasoning model's thinking in a
        separate ``reasoning`` field (some servers use ``reasoning_content``)
        and leaves ``content`` empty when the token budget was spent thinking.
        Only the *length* is returned: it is the diagnostic that distinguishes
        "the model said nothing" from "the model thought until it ran out",
        while the text itself is model output about a card and is never logged.
        """
        for key in ("reasoning", "reasoning_content", "thinking"):
            value = message.get(key)
            if isinstance(value, str) and value:
                return len(value)
        return 0

    @staticmethod
    def _provider_error_detail(result: Dict[str, Any]) -> str:
        """A provider-supplied error message carried alongside an HTTP 200."""
        error = result.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or "")
        return str(error or "")

    def _interpret_response(
        self, result: Dict[str, Any]
    ) -> Tuple[Optional[Any], Optional[str], bool]:
        """Turn a provider's HTTP 200 body into ``(parsed, error, retryable)``.

        Exactly one of *parsed* and *error* is set. *retryable* says whether
        asking the same model again could plausibly help — it never does when
        the output limit was the cause, because an identical request hits the
        same limit and merely doubles the cost of a failure.

        The cases separated here used to collapse into a single
        "JSON-Parsing fehlgeschlagen" message, which is why an empty HTTP 200
        and a response cut off mid-object were indistinguishable in the logs.
        """
        choices = result.get("choices")
        if not isinstance(choices, list) or not choices:
            detail = self._provider_error_detail(result)
            message = f"Keine Antwort vom Modell ({ERROR_NO_CHOICES}): leere choices"
            if detail:
                message += f" — {detail[:200]}"
            return None, message, False

        choice: Dict[str, Any] = choices[0] if isinstance(choices[0], dict) else {}
        raw_message = choice.get("message")
        message_obj: Dict[str, Any] = raw_message if isinstance(raw_message, dict) else {}
        finish_reason = str(choice.get("finish_reason") or "")
        truncated = finish_reason == "length"
        reasoning_chars = self._reasoning_length(message_obj)
        content = message_obj.get("content")

        if content is None or (isinstance(content, str) and not content.strip()):
            # Valid envelope, no answer. With finish_reason=length the budget
            # was consumed before any content was emitted — for a
            # reasoning-capable VLM, inside its own chain-of-thought.
            if truncated:
                return (
                    None,
                    f"Leere Modellantwort ({ERROR_EMPTY_RESPONSE}): das Ausgabelimit "
                    f"({settings.VLM_MAX_OUTPUT_TOKENS} Tokens) war erreicht, bevor Inhalt "
                    f"geliefert wurde (finish_reason=length, {reasoning_chars} Zeichen "
                    "Reasoning). VLM_MAX_OUTPUT_TOKENS erhöhen oder ein Modell ohne "
                    "Thinking verwenden.",
                    False,
                )
            detail = self._provider_error_detail(result)
            suffix = f" — {detail[:200]}" if detail else ""
            return (
                None,
                f"Leere Modellantwort ({ERROR_EMPTY_RESPONSE}): HTTP 200 ohne Inhalt "
                f"(finish_reason={finish_reason or 'unbekannt'}, {reasoning_chars} Zeichen "
                f"Reasoning){suffix}",
                True,
            )

        if not isinstance(content, str):
            return (
                None,
                f"Unerwartetes Antwortformat ({ERROR_INVALID_JSON}): content ist "
                f"{type(content).__name__}, nicht Text",
                False,
            )

        cleaned = self._extract_json_from_model_content(content)
        recovered_non_strict_json = False
        recovered_unescaped_value_quote = False
        strict_json_error: json.JSONDecodeError | None = None
        non_strict_json_error: json.JSONDecodeError | None = None
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            strict_json_error = exc
            # Some otherwise valid model responses contain literal control
            # characters inside JSON strings (most commonly a line break or
            # tab copied from a multi-line catalogue field).  RFC-compliant
            # JSON requires those characters to be escaped, but Python can
            # parse the same structure with ``strict=False`` without changing
            # the field content.  Keep this recovery deliberately narrow.
            try:
                parsed = json.loads(cleaned, strict=False)
                recovered_non_strict_json = True
            except json.JSONDecodeError as exc:
                non_strict_json_error = exc
                parsed = None

        if parsed is None and non_strict_json_error is not None:
            repaired = self._repair_unescaped_value_quote_before_colon(
                cleaned, non_strict_json_error
            )
            if repaired is not None:
                try:
                    # Use the same non-strict mode so this recovery also works
                    # when the response contains literal line breaks/tabs.
                    parsed = json.loads(repaired, strict=False)
                    recovered_unescaped_value_quote = True
                except json.JSONDecodeError:
                    parsed = None

        if parsed is None:
            if truncated:
                return (
                    None,
                    f"Abgeschnittene Modellantwort ({ERROR_TRUNCATED_RESPONSE}): das "
                    f"Ausgabelimit ({settings.VLM_MAX_OUTPUT_TOKENS} Tokens) wurde mitten "
                    f"in der Antwort erreicht (finish_reason=length, {len(content)} Zeichen "
                    f"Inhalt, {reasoning_chars} Zeichen Reasoning). VLM_MAX_OUTPUT_TOKENS "
                    "erhöhen.",
                    False,
                )
            # Complete but syntactically invalid. The bounded preview stays in
            # the card's error because checkpoint.json and the failure CSV
            # already hold this card's extracted data — the application log
            # gets metadata only.
            preview = " ".join(cleaned[:120].split())
            parse_error = non_strict_json_error or strict_json_error
            diagnostic = ""
            if parse_error is not None:
                start = max(0, parse_error.pos - 45)
                end = min(len(cleaned), parse_error.pos + 45)
                context = " ".join(cleaned[start:end].split())
                diagnostic = (
                    f" JSON-Parser: {parse_error.msg} "
                    f"(Zeile {parse_error.lineno}, Spalte {parse_error.colno}, "
                    f"Position {parse_error.pos}); Kontext: {context}"
                )
            return (
                None,
                f"Ungültiges JSON in der Modellantwort ({ERROR_INVALID_JSON}): "
                f"finish_reason={finish_reason or 'unbekannt'}, {len(content)} Zeichen. "
                f"Antwort: {preview}.{diagnostic}",
                True,
            )

        if recovered_non_strict_json:
            logger.info(
                "Recovered model JSON containing literal control characters "
                "with non-strict parsing (content_chars=%d)",
                len(content),
            )
        if recovered_unescaped_value_quote:
            logger.info(
                "Recovered one unescaped quote inside a JSON value string "
                "without changing field content (content_chars=%d)",
                len(content),
            )

        if not isinstance(parsed, (dict, list)):
            return (
                None,
                f"Ungültiges JSON in der Modellantwort ({ERROR_INVALID_JSON}): "
                f"{type(parsed).__name__} statt Objekt oder Liste",
                True,
            )

        if truncated:
            # Parsed only because _extract_json_from_model_content trimmed to the
            # last closing brace, so the record is incomplete by construction.
            return (
                None,
                f"Abgeschnittene Modellantwort ({ERROR_TRUNCATED_RESPONSE}): das "
                f"Ausgabelimit ({settings.VLM_MAX_OUTPUT_TOKENS} Tokens) wurde erreicht "
                f"(finish_reason=length, {len(content)} Zeichen Inhalt). "
                "VLM_MAX_OUTPUT_TOKENS erhöhen.",
                False,
            )

        return parsed, None, False

    @staticmethod
    def _repair_unescaped_value_quote_before_colon(
        text: str, error: json.JSONDecodeError
    ) -> Optional[str]:
        """Escape one highly constrained stray quote inside a value string.

        Observed VLM failure mode::

            "Beschreibung": "„RIAS – Ente": gerupfte Ente ..."

        The ASCII quote before the colon prematurely terminates the JSON value.
        We only repair when the parser stops *on that colon*, the immediately
        preceding non-space character is an unescaped quote, and the matching
        previous unescaped quote is demonstrably the opening quote of an object
        value (i.e. it follows a colon).  The repair changes only JSON syntax by
        inserting a backslash before that quote.  Any ambiguity or a second
        structural defect remains a normal invalid-JSON failure.
        """
        if error.msg != "Expecting ',' delimiter" or error.pos >= len(text):
            return None
        if text[error.pos] != ":":
            return None

        quote_pos = error.pos - 1
        while quote_pos >= 0 and text[quote_pos].isspace():
            quote_pos -= 1
        if quote_pos < 0 or text[quote_pos] != '"':
            return None

        # The candidate quote itself must not already be escaped.
        backslashes = 0
        i = quote_pos - 1
        while i >= 0 and text[i] == "\\":
            backslashes += 1
            i -= 1
        if backslashes % 2:
            return None

        # Find the previous unescaped ASCII quote.  For this deliberately
        # narrow recovery it must be the opening quote of the same value.
        opening_quote = None
        i = quote_pos - 1
        while i >= 0:
            if text[i] == '"':
                backslashes = 0
                j = i - 1
                while j >= 0 and text[j] == "\\":
                    backslashes += 1
                    j -= 1
                if backslashes % 2 == 0:
                    opening_quote = i
                    break
            i -= 1
        if opening_quote is None:
            return None

        before_open = opening_quote - 1
        while before_open >= 0 and text[before_open].isspace():
            before_open -= 1
        if before_open < 0 or text[before_open] != ":":
            return None

        return text[:quote_pos] + "\\" + text[quote_pos:]

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
        cancel_event: Optional[threading.Event] = None,
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """Resilienter API-Aufruf: Session, exponential backoff with jitter.

        *cancel_event* is the batch's cooperative stop signal. It is checked
        before the first request and before every retry, so a pause or cancel
        can no longer be followed by a *new* outbound request — previously the
        worst-case stop latency was ``MAX_WORKERS × MAX_RETRIES × timeout``
        (30 minutes at the current settings), which is what made Pause look
        like it did nothing.
        """
        resolved_endpoint = api_endpoint or settings.API_ENDPOINT
        resolved_model = model_name or settings.MODEL_NAME
        resolved_key = api_key if api_key is not None else self.api_key

        if not resolved_key:
            return None, "API Key missing"

        if cancel_event is not None and cancel_event.is_set():
            # Stop already requested: do not even encode the image.
            return None, ERROR_STOP_REQUESTED

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

        payload: Dict[str, Any] = {
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
            # A cap, not a reservation: a response that finishes earlier costs
            # and takes exactly as long as it did before. It must nevertheless
            # be large enough to cover a reasoning-capable VLM's
            # chain-of-thought, which is generated *inside* this budget — the
            # previously hard-coded 4096 was the direct cause of answers cut
            # off mid-JSON and of HTTP 200s whose whole budget went into
            # thinking, leaving no content at all.
            "max_tokens": settings.VLM_MAX_OUTPUT_TOKENS,
        }
        # GPUStack/vLLM: reasoning-capable Qwen-family VLMs can spend the entire
        # max_tokens budget in ``reasoning_content`` and return no JSON at all.
        # For extraction we therefore disable thinking by default. Keep this
        # provider-specific so Ollama/OpenRouter request shapes remain unchanged.
        if resolved_endpoint == settings.GPUSTACK_API_ENDPOINT:
            payload["chat_template_kwargs"] = {
                "enable_thinking": settings.GPUSTACK_ENABLE_THINKING,
            }

        if settings.VLM_JSON_MODE:
            # Provider-side JSON enforcement, opt-in. Support depends on the
            # provider and — behind a reverse proxy — on the proxy forwarding
            # the field; a constrained decoder can also interact badly with a
            # model that emits chain-of-thought. The prompt asks for JSON
            # either way, so a provider that ignores this behaves as before.
            payload["response_format"] = {"type": "json_object"}

        max_retries = settings.MAX_RETRIES
        attempt = 0
        while attempt < max_retries:
            if cancel_event is not None and cancel_event.is_set():
                return None, ERROR_STOP_REQUESTED
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

                    if resp.status_code in (401, 403):
                        return None, f"Ungültige oder nicht autorisierte Provider-Zugangsdaten ({resp.status_code})"
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
                provider_model = result.get("model") if isinstance(result, dict) else None
                if not isinstance(provider_model, str) or not provider_model.strip():
                    provider_model = None
                self._provider_response_meta.resolved_model = provider_model
                parsed, model_error, retryable = self._interpret_response(result)
                if model_error is None:
                    return parsed, None

                # Metadata only — never the model's text. The card's own error
                # string (stored in checkpoint.json, which already holds this
                # card's data) carries the bounded preview where one helps.
                logger.warning(
                    "Unusable model response for %s: model=%s host=%s attempt=%d/%d "
                    "retryable=%s detail=%s",
                    image_path.name, resolved_model,
                    urlparse(resolved_endpoint).hostname or "",
                    attempt + 1, max_retries, retryable,
                    model_error.split(". Antwort:")[0],
                )

                # A model-output fault consumes the SAME attempt budget as a
                # transport fault, so MAX_RETRIES keeps meaning "requests in
                # total" and no retry amplification is introduced. A fault
                # caused by the output limit is never retried: the identical
                # request would hit the identical limit.
                if retryable and attempt + 1 < max_retries:
                    if cancel_event is not None and cancel_event.is_set():
                        return None, ERROR_STOP_REQUESTED
                    time.sleep(_MODEL_RETRY_DELAY_SECONDS + random.random())
                    attempt += 1
                    continue
                return None, model_error
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
        cancel_event: Optional[threading.Event] = None,
    ) -> Dict[str, Any]:
        """Synchronous card processing logic.

        A card whose processing was pre-empted by a pause or cancel comes back
        marked ``stopped``. That is not a failure: it was never sent to the
        model, so process_batch must not record it or move it to ``_errors/``.
        """
        start_time = time.time()
        filename = image_path.name
        try:
            # Clear any metadata left on a reused worker thread before the call.
            self._provider_response_meta.resolved_model = None
            raw, error = self._call_vlm_api_resilient(
                image_path, fields=fields, max_size=max_size,
                prompt_template=prompt_template,
                api_endpoint=api_endpoint, model_name=model_name, api_key=api_key,
                describe_pictures=describe_pictures,
                field_groups=field_groups,
                cancel_event=cancel_event,
            )
            duration = time.time() - start_time
            provider_model = getattr(self._provider_response_meta, "resolved_model", None)

            if error == ERROR_STOP_REQUESTED:
                return {
                    "filename": filename,
                    "batch": batch_name,
                    "success": False,
                    "stopped": True,
                    "error": "Verarbeitung vor dem Modellaufruf gestoppt (Pause/Abbruch)",
                    "duration": duration,
                }

            if error:
                logger.error(f"[{batch_name}] {filename} -> {error}")
                return {
                    "filename": filename,
                    "batch": batch_name,
                    "success": False,
                    "error": error,
                    "duration": duration,
                    "requested_model": model_name,
                    "resolved_model": provider_model,
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
                    "requested_model": model_name,
                    "resolved_model": provider_model,
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
                "requested_model": model_name,
                "resolved_model": provider_model,
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
                        field_groups, cancel_event
                    ): img
                    for img in files_to_process
                }
                for i, fut in enumerate(as_completed(futures), len(completed_files) + 1):
                    res = fut.result()

                    # Pre-empted by a pause/cancel: the card never reached the
                    # model, so it must stay as if untouched — no checkpoint
                    # row, no move to _errors/. A resume then simply processes
                    # it, instead of finding it recorded as a failure that only
                    # a manual retry could clear. Do not break here: another
                    # worker may already have completed successfully, and its
                    # result still has to be drained and checkpointed.
                    if res.get("stopped"):
                        logger.info(
                            "Batch %s: stopping before %s — pause/cancel requested",
                            batch_name, res.get("filename"),
                        )
                        continue

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

                    # Cooperative cancellation: do not start retries/new model
                    # requests, but keep draining futures that were already
                    # running. Otherwise a fast stopped future can win the race
                    # in as_completed() and make an already-successful card
                    # disappear from the checkpoint/export.
                    if cancel_event and cancel_event.is_set():
                        logger.info(f"Batch {batch_name} cancelled by user after {i} images")
                        continue

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
