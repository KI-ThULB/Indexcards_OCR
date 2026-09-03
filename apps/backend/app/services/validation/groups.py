"""Repeatable field groups: canonical wire format and defensive normalisation.

A repeatable group lets one template field hold zero, one or many sub-records —
for an AMIGA tape card, the individual track titles each with their own duration,
alongside the card-level overall title and overall duration.

Wire format
-----------
``ExtractionResult.data`` is ``Dict[str, str]`` and rejects nested values, so a
group's value is stored as a **canonical JSON array serialised to a string** in
``data[groupLabel]``. This follows the convention ``data["_entries"]`` already
uses. Canonical means: every item holds exactly the defined child names in the
template's child order, with compact separators — so re-serialising the same
logical value is byte-identical, which is what makes the CSV export deterministic.

Confidence and curator edits
----------------------------
Per-child confidence lives in the existing ``Dict[str, float]`` under flattened
keys, e.g. ``Titel_Tracks[0].Titel``. Curator edits store the whole edited array
under ``edited_data[groupLabel]``; see :func:`effective_items`.

Defensiveness
-------------
Bulk runs are unattended: one card whose model output is malformed must never
stop a 14,000-card collection. :func:`normalise_group` therefore never raises. It
coerces whatever it is given into a safe list and reports *problem codes* — never
extracted content — so the diagnostic can be surfaced without leaking card data
into logs.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Flattened per-child key, e.g. "Titel_Tracks[0].Titel".
CHILD_KEY_RE = re.compile(r"^(?P<group>[^\[\]]+)\[(?P<index>\d+)\]\.(?P<child>.+)$")

# Problem codes recorded by normalise_group. Codes only — never card content.
PROBLEM_WAS_STRING = "group_was_string"
PROBLEM_WAS_OBJECT = "group_was_object"
PROBLEM_NON_OBJECT_ITEM = "non_object_item"
PROBLEM_MALFORMED = "group_malformed"
PROBLEM_UNKNOWN_CHILD = "unknown_child_key"

# Status/rule identifiers reused by the existing ValidationOutcome shape.
GROUP_RULE = "group_shape"


# --------------------------------------------------------------------------- #
# Flattened key helpers (confidence, and the granular PATCH address)
# --------------------------------------------------------------------------- #
def child_key(group: str, index: int, child: str) -> str:
    """The flattened confidence/address key for one child of one entry."""
    return f"{group}[{index}].{child}"


def parse_child_key(key: str) -> Optional[Tuple[str, int, str]]:
    """Split a flattened key into ``(group, index, child)``, or None if it is not one."""
    match = CHILD_KEY_RE.match(key)
    if not match:
        return None
    try:
        index = int(match.group("index"))
    except ValueError:  # pragma: no cover - the regex already guarantees digits
        return None
    return match.group("group"), index, match.group("child")


def child_names(group_def: Any) -> List[str]:
    """Defined child names, in template order. Accepts a model or a plain dict."""
    fields = getattr(group_def, "fields", None)
    if fields is None and isinstance(group_def, dict):
        fields = group_def.get("fields")
    out: List[str] = []
    for child in fields or []:
        name = getattr(child, "name", None)
        if name is None and isinstance(child, dict):
            name = child.get("name")
        if name:
            out.append(str(name))
    return out


def max_items(group_def: Any, default: int = 12) -> int:
    """The group's frozen CSV width. Accepts a model or a plain dict."""
    value = getattr(group_def, "max_items", None)
    if value is None and isinstance(group_def, dict):
        value = group_def.get("max_items")
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


# --------------------------------------------------------------------------- #
# Canonical serialisation
# --------------------------------------------------------------------------- #
def serialise_group(items: List[Dict[str, str]]) -> str:
    """Serialise group items canonically, so equal values give equal strings."""
    return json.dumps(list(items), ensure_ascii=False, separators=(",", ":"))


def parse_group(raw: Any) -> List[Dict[str, str]]:
    """Parse a stored group value back into items. Tolerant: never raises.

    Returns ``[]`` for anything unusable, so a corrupt cell degrades to "no
    entries" rather than breaking a results view or an export.
    """
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


# --------------------------------------------------------------------------- #
# Defensive normalisation
# --------------------------------------------------------------------------- #
def normalise_group(raw: Any, group_def: Any) -> Tuple[List[Dict[str, str]], List[str]]:
    """Coerce a model-supplied group value into safe canonical items.

    Returns ``(items, problems)`` and **never raises**. Every item holds exactly
    the defined child names in template order; a missing child becomes ``""``, so
    a gap in one row can never shift a later row's values up.

    Unknown child keys are dropped and counted rather than promoted, so a
    creative model cannot silently widen the template schema (and therefore the
    CSV) at runtime.
    """
    names = child_names(group_def)
    problems: List[str] = []

    # ---- coerce the container into a list of candidate items ----
    if raw is None:
        candidates: List[Any] = []
    elif isinstance(raw, list):
        candidates = list(raw)
    elif isinstance(raw, str):
        # Some models wrap the array in a string. Accept it, but record it.
        stripped = raw.strip()
        if not stripped:
            candidates = []
        else:
            parsed_str = parse_group(stripped)
            if parsed_str:
                candidates = list(parsed_str)
                problems.append(PROBLEM_WAS_STRING)
            else:
                return [], [PROBLEM_MALFORMED]
    elif isinstance(raw, dict):
        # The model collapsed many entries into one object.
        candidates = [raw]
        problems.append(PROBLEM_WAS_OBJECT)
    else:
        return [], [PROBLEM_MALFORMED]

    # ---- normalise each item ----
    items: List[Dict[str, str]] = []
    unknown = 0
    non_object = 0
    for candidate in candidates:
        if not isinstance(candidate, dict):
            non_object += 1
            continue
        unknown += sum(1 for key in candidate if key not in names)
        item = {name: _as_text(candidate.get(name)) for name in names}
        # Drop an item that carries nothing — a trailing blank form row must not
        # become a phantom entry.
        if any(value for value in item.values()):
            items.append(item)

    if non_object:
        problems.append(PROBLEM_NON_OBJECT_ITEM)
    if unknown:
        problems.append(PROBLEM_UNKNOWN_CHILD)
    return items, problems


def _as_text(value: Any) -> str:
    """Coerce a child value to a string. ``None`` and containers become empty."""
    if value is None or isinstance(value, (list, dict)):
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def outcome_for(problems: List[str]) -> Dict[str, Any]:
    """Build a ValidationOutcome dict for a group, in the existing shape.

    ``rationale`` carries problem **codes only**, never extracted content, so it
    is safe to surface in the UI and in diagnostics.
    """
    if not problems:
        return {
            "status": "valid",
            "rule_failed": None,
            "original_value": None,
            "rationale": None,
            "corrector_proposal": None,
        }
    return {
        "status": "invalid",
        "rule_failed": GROUP_RULE,
        "original_value": None,
        "rationale": ", ".join(sorted(set(problems))),
        "corrector_proposal": None,
    }


# --------------------------------------------------------------------------- #
# Effective value (raw vs. curator-edited)
# --------------------------------------------------------------------------- #
def effective_items(result: Dict[str, Any], group: str) -> List[Dict[str, str]]:
    """The items a curator currently sees: edited array if present, else raw.

    One definition, shared by the PATCH endpoint and both CSV exporters, so the
    three can never disagree about what a card's group currently holds.
    """
    edited = (result.get("edited_data") or {}).get(group)
    if edited:
        items = parse_group(edited)
        if items or edited.strip() in ("[]", ""):
            return items
    return parse_group((result.get("data") or {}).get(group))


def group_labels(field_groups: Any) -> List[str]:
    """Defined group labels, or an empty list when no groups are configured."""
    if not field_groups:
        return []
    if isinstance(field_groups, dict):
        return list(field_groups.keys())
    return []
