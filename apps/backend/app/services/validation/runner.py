from typing import Dict, Optional, Any
from .regex_rules import check_regex
from .vocab_rules import matches_vocabulary
from .corrector import invoke_corrector


def run_validation(
    data: Dict[str, str],
    field_rules: Optional[Dict[str, dict]],
    corrector_enabled: bool,
    cap_state: dict,
    api_key: str,
) -> Dict[str, dict]:
    """Run per-field validation rules against extracted data.

    Returns a map of field_label -> ValidationOutcome dict.
    An empty dict is returned when field_rules is None or empty (backward compat).
    """
    outcomes: Dict[str, dict] = {}
    if not field_rules:
        return outcomes

    for field, rule in field_rules.items():
        if not rule:
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
