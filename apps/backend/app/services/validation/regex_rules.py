import re
from functools import lru_cache


@lru_cache(maxsize=256)
def _compile(pattern: str):
    return re.compile(pattern)


def check_regex(value: str, pattern: str) -> bool:
    if not pattern:
        return True
    try:
        return _compile(pattern).match(value or "") is not None
    except re.error:
        # Bad regex pattern -> treat as failed match (curator will see invalid status)
        return False
