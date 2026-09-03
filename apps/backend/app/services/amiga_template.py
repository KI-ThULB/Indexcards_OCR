"""Seed template: AMIGA Tonband-Karteikarte (with a repeatable track group).

The historical AMIGA tape index cards carry an overall title *and* several
individual track titles, plus one duration per track *and* an overall duration.
A flat template collapses that to one title and one duration, losing every
track — which is why this template's ``Titel_Tracks`` field is a repeatable
group.

The pre-existing flat ``AMIGA Tonbandkartei`` template is deliberately left
untouched; this one is added alongside under a distinct name. Batches already
extracted with the flat template keep working, and operators migrate simply by
choosing this template for new runs.

Field identifiers follow the existing convention: the string in ``fields`` is
both the identifier and the display label. No separate label abstraction is
introduced.
"""
from typing import Any, Dict, List

TEMPLATE_NAME = "AMIGA Tonband-Karteikarte"

# max_items freezes the CSV width for the group. 20 is the operator-set value for
# this collection; generic groups created in the UI default to 12.
TRACKS_MAX_ITEMS = 20

FIELDS: List[str] = [
    "Bestellnummer",
    "Tonband_Nr",
    "Gesamttitel",
    "Titel_Tracks",          # ← repeatable group; the label stays a normal field
    "Gesamtspieldauer",
    "Sperrvermerk",
    "Ort_der_Aufnahme",
    "Aufnahmedatum",
    "Aufnahmeleiter",
    "Tonmeister",
    "Aufnahmetechniker",
    "Kuenstlerische_Freigabe_Datum",
    "Kuenstlerische_Freigabe_Gez",
    "Technische_Freigabe_Datum",
    "Technische_Freigabe_Gez",
    "Sicherheitsumschnitt_Datum",
    "Sicherheitsumschnitt_Von",
    "Bemerkungen",
    "Orchester",
    "Dirigent_Orchester",
    "Chor",
    "Dirigent_Chor",
    "Solisten",
    "Komponist",
    "Textdichter",
    "Bearbeiter",
    "Verlag",
]

FIELD_GROUPS: Dict[str, Dict[str, Any]] = {
    "Titel_Tracks": {
        "description": (
            "Die Einzeltitel des Tonbands. Jede Zeile der Titelliste ist ein "
            "eigener Eintrag mit der zu genau dieser Zeile gehörenden Spieldauer."
        ),
        "max_items": TRACKS_MAX_ITEMS,
        "fields": [
            {
                "name": "Lfd_Nr",
                "description": "Die laufende Nummer dieser Zeile, falls auf der Karte angegeben.",
            },
            {
                "name": "Titel",
                "description": (
                    "Der Einzeltitel dieser Zeile — NICHT der Gesamt-/Sammeltitel des Tonbands."
                ),
            },
            {
                "name": "Spieldauer",
                "description": (
                    "Die Spieldauer genau dieser Zeile — NICHT die Gesamtspieldauer des Tonbands."
                ),
            },
        ],
    }
}

# Card-type framing and extraction discipline. This lives in the template's own
# prompt_template rather than in the engine, so no existing template's prompt
# changes. The engine adds the generic group rules and the
# Gesamttitel/Einzeltitel disambiguation on top.
PROMPT_TEMPLATE = """Du bist ein Experte für die Erschließung historischer Rundfunk- und Tonarchivalien.

Vor dir liegt eine **historische AMIGA Tonband-Karteikarte** (VEB Deutsche Schallplatten).
Deine Aufgabe ist **strukturierte Metadatenerfassung**, nicht bloßes Abschreiben des Textes.

**Grundregeln:**
1. Erfasse **ausschließlich** Informationen, die auf der Karte tatsächlich zu sehen sind.
2. **Erfinde nichts.** Ergänze keine Angaben aus eigenem Wissen über Werke, Personen oder Aufnahmen.
3. Übernimm die **historische Schreibweise der Quelle**, auch bei alter Orthographie oder Abkürzungen.
4. Ist ein Feld auf der Karte nicht ausgefüllt, gib einen **leeren String** ("") zurück.
5. **Vorgedruckte Formularbezeichnungen sind Struktur, nicht Inhalt.** Übernimm sie nicht als Feldwert.
6. Erfasse **maschinenschriftliche, gestempelte und gut lesbare handschriftliche** Einträge gleichermaßen.
   Ist eine handschriftliche Angabe unlesbar, lass das Feld leer statt zu raten.
7. Bewahre die **Reihenfolge des Dokuments**.
8. Stehen in einem Personenfeld mehrere Namen, erfasse **alle**, getrennt durch Semikolon.

**Zu erfassende Felder:**
{{fields}}"""


def template_payload() -> Dict[str, Any]:
    """The template as a TemplateCreate-compatible dict."""
    return {
        "name": TEMPLATE_NAME,
        "fields": list(FIELDS),
        "prompt_template": PROMPT_TEMPLATE,
        "field_groups": {k: dict(v) for k, v in FIELD_GROUPS.items()},
    }


def ensure_seeded() -> bool:
    """Create the template if no template of that name exists yet.

    Idempotent, and it never modifies or deletes an existing template — including
    the older flat ``AMIGA Tonbandkartei``. Returns True if it created one.
    """
    from app.models.schemas import TemplateCreate
    from app.services.template_service import template_service

    for existing in template_service.list_templates():
        if existing.name == TEMPLATE_NAME:
            return False
    template_service.create_template(TemplateCreate(**template_payload()))
    return True
