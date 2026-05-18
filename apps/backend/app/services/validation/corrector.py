import json
import logging
import requests
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

CORRECTOR_SYSTEM_PROMPT = """You are a data quality assistant helping correct OCR-extracted archival field values.

You will be given a field name, an extracted value that failed validation, and a description of the rule that failed.
Your task is to propose the most likely correct value based on the failed rule.

Respond ONLY with a JSON object in this exact format:
{"proposal": "<corrected value>", "rationale": "<brief explanation>"}

Do not include any other text, markdown, or explanation outside the JSON object."""


def invoke_corrector(
    field_name: str,
    raw_value: str,
    rule: dict,
    cap_state: dict,
    api_key: str,
) -> dict:
    """Invoke the LLM corrector for a field that failed validation.

    Args:
        field_name: The field label (e.g. "Year", "Signatur")
        raw_value: The extracted value that failed the rule
        rule: The FieldRule dict containing pattern/vocabulary/etc.
        cap_state: Mutable dict {"used": int, "cap": int, "lock": threading.Lock}
        api_key: OpenRouter API key

    Returns:
        dict with keys: status ("corrected"|"invalid"|"skipped"), proposal (str|None), rationale (str)
    """
    # Thread-safe cap check and increment
    lock = cap_state.get("lock")
    if lock is not None:
        with lock:
            if cap_state["used"] >= cap_state["cap"]:
                return {
                    "status": "invalid",
                    "proposal": None,
                    "rationale": "Correction cap reached",
                }
            cap_state["used"] += 1
    else:
        # No lock provided (e.g. single-threaded revalidate) — simple check
        if cap_state["used"] >= cap_state["cap"]:
            return {
                "status": "invalid",
                "proposal": None,
                "rationale": "Correction cap reached",
            }
        cap_state["used"] += 1

    # Build rule description for the user message
    pattern = rule.get("pattern")
    vocabulary = rule.get("vocabulary")
    if vocabulary:
        rule_description = f"Closed vocabulary match. Allowed values: {vocabulary}"
    elif pattern:
        rule_description = f"Regex pattern: {pattern}"
    else:
        rule_description = "Unknown rule"

    user_message = (
        f"Field: {field_name}\n"
        f"Extracted value: {raw_value!r}\n"
        f"Failed rule: {rule_description}\n\n"
        f"Propose a corrected value as JSON: {{\"proposal\": \"...\", \"rationale\": \"...\"}}"
    )

    payload = {
        "model": settings.CORRECTOR_MODEL_NAME,
        "messages": [
            {"role": "system", "content": CORRECTOR_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.0,
        "max_tokens": settings.CORRECTOR_MAX_TOKENS,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(
            settings.API_ENDPOINT,
            headers=headers,
            json=payload,
            timeout=settings.CORRECTOR_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        result = resp.json()

        if "choices" not in result or not result["choices"]:
            logger.warning(f"Corrector returned empty choices for field {field_name!r}")
            return {
                "status": "invalid",
                "proposal": None,
                "rationale": "Corrector returned no choices",
            }

        content = result["choices"][0]["message"]["content"].strip()

        # Strip markdown fences if present
        if content.startswith("```"):
            parts = content.split("```")
            for p in reversed(parts):
                p = p.strip()
                if p:
                    if p.startswith("json"):
                        p = p[4:].strip()
                    content = p
                    break

        parsed = json.loads(content)
        proposal = str(parsed.get("proposal", "")).strip()
        rationale = str(parsed.get("rationale", "")).strip()

        if not proposal:
            return {
                "status": "invalid",
                "proposal": None,
                "rationale": rationale or "Corrector returned empty proposal",
            }

        return {
            "status": "corrected",
            "proposal": proposal,
            "rationale": rationale,
        }

    except requests.exceptions.HTTPError as e:
        logger.warning(f"Corrector HTTP error for field {field_name!r}: {e}")
        return {
            "status": "invalid",
            "proposal": None,
            "rationale": f"Corrector HTTP error: {e}",
        }
    except json.JSONDecodeError as e:
        logger.warning(f"Corrector JSON parse error for field {field_name!r}: {e}")
        return {
            "status": "invalid",
            "proposal": None,
            "rationale": f"Corrector response parse error: {e}",
        }
    except Exception as e:
        logger.warning(f"Corrector unexpected error for field {field_name!r}: {e}")
        return {
            "status": "invalid",
            "proposal": None,
            "rationale": f"Corrector error: {e}",
        }
