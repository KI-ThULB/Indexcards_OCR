from dataclasses import dataclass


@dataclass
class ValidationPreset:
    id: str
    label: str
    pattern: str
    description: str
    has_prefix_input: bool = False


VALIDATION_PRESETS = [
    ValidationPreset("required",    "Required / Non-empty",     r"^.+$",                        "Field must not be empty"),
    ValidationPreset("year",        "Year (YYYY)",              r"^\d{4}$",                     "Four-digit year"),
    ValidationPreset("year_range",  "Year Range (YYYY-YYYY)",   r"^\d{4}[–\-]\d{4}$",           "Year range with dash or en-dash"),
    ValidationPreset("iso_date",    "ISO Date (YYYY-MM-DD)",    r"^\d{4}-\d{2}-\d{2}$",         "ISO 8601 date"),
    ValidationPreset("german_date", "German Date (DD.MM.YYYY)", r"^\d{2}\.\d{2}\.\d{4}$",       "German date format"),
    ValidationPreset("gnd_id",      "GND Authority ID",         r"^(DE-588)?[0-9X]+$",          "GND identifier"),
    ValidationPreset("rkd_id",      "RKD Authority ID",         r"^\d+$",                       "RKD numeric identifier"),
    ValidationPreset("aat_id",      "Getty AAT ID",             r"^aat:\d+$",                   "AAT concept identifier"),
    ValidationPreset("viaf_id",     "VIAF ID",                  r"^\d+$",                       "VIAF numeric identifier"),
    ValidationPreset("prefix",      "Prefix Pattern",           r"",                            "Custom prefix + digits", True),
    ValidationPreset("custom",      "Custom Regex",             r"",                            "User-supplied regex"),
    ValidationPreset("vocabulary",  "Closed Vocabulary",        r"",                            "Match against allowed values list"),
]
