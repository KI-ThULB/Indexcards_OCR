from typing import Dict, Iterable, Optional
from .regex_rules import check_regex
from .vocab_rules import matches_vocabulary
from .corrector import invoke_corrector


def run_validation(
    data: Dict[str, str],
    field_rules: Optional[Dict[str, dict]],
    corrector_enabled: bool,
    cap_state: dict,
    api_key: str,
    skip_fields: Optional[Iterable[str]] = None,
) -> Dict[str, dict]:
    """Run per-field validation rules against extracted data.

    Returns a map of field_label -> ValidationOutcome dict.
    An empty dict is returned when field_rules is None or empty (backward compat).

    skip_fields names labels a scalar rule must not touch — repeatable groups,
    whose value is a serialised JSON array. A regex or vocabulary match over that
    text is meaningless, and letting it fail would hand the LLM corrector a JSON
    blob as if it were a field value. Group shape is validated by
    validation.groups.normalise_group instead.
    """
    outcomes: Dict[str, dict] = {}
    if not field_rules:
        return outcomes

    skip = set(skip_fields or ())
    for field, rule in field_rules.items():
        if not rule or field in skip:
            continue
        value = (data or {}).get(field, "") or ""
        pattern = rule.get("pattern")
        vocab = rule.get("vocabulary")
        fuzzy = rule.get("fuzzy_distance")

        regex_ok = check_regex(value, pattern) if pattern else True
        vocab_ok = matches_vocabulary(value, vocab, fuzzy) if vocab else True

        if regex_ok and vocab_ok:
            outcomes[field] = {
                "status": "valid",
                "rule_failed": None,
                "original_value": None,
                "rationale": None,
                "corrector_proposal": None,
            }
            continue

        rule_failed = "regex" if not regex_ok else "vocabulary"
        should_correct = corrector_enabled and rule.get("corrector_enabled", False)

        if should_correct:
            result = invoke_corrector(field, value, rule, cap_state, api_key)
            outcomes[field] = {
                "status": result["status"],   # "corrected" or "invalid"
                "rule_failed": rule_failed,
                "original_value": value,
                "rationale": result["rationale"],
                "corrector_proposal": result.get("proposal"),
            }
        else:
            outcomes[field] = {
                "status": "invalid",
                "rule_failed": rule_failed,
                "original_value": value,
                "rationale": None,
                "corrector_proposal": None,
            }

    return outcomes
