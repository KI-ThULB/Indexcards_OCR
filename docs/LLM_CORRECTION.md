# LLM Correction for Invalid Fields

> Bilingual reference. English first, German follows (`— DE —`).
> Zweisprachige Referenz. Zuerst Englisch, danach Deutsch.

---

# 🇬🇧 English

## The idea in one sentence

After the VLM extracts a card, each field is checked against its validation rule; when a
field **fails** its rule, an optional cheap **text-only LLM** is asked to *propose* a corrected
value — which a curator then accepts or rejects. The corrector never overwrites data silently.

## When it fires

The corrector runs for a field **only if all three are true**
(`apps/backend/app/services/validation/runner.py`):

1. The batch has the corrector toggle enabled (`corrector_enabled`).
2. The specific field's rule has `corrector_enabled: true`.
3. The field actually **failed** its validation (regex or closed-vocabulary check).

A field that passes validation is marked `valid` and never touches the LLM — so there is no
cost for clean data.

## The flow per field

```
VLM extraction → run_validation() per field
        │
        ├── regex_ok AND vocab_ok? ──── yes ──► status: "valid"   (done, no LLM)
        │
        └── failed (regex | vocabulary)
                 │
                 ├── corrector NOT enabled ──► status: "invalid"  (flagged for curator)
                 │
                 └── corrector enabled ──► invoke_corrector()
                            │
                            ├── proposal returned ──► status: "corrected" + proposal + rationale
                            └── error / cap / empty ──► status: "invalid"
```

## What the corrector actually does (`corrector.py`)

1. **Cap check (thread-safe).** A per-batch counter guards spend. If `used >= cap`, it returns
   `invalid` with rationale *"Correction cap reached"* — no API call. The increment is protected
   by a lock because OCR runs cards concurrently in a thread pool.
2. **Builds a focused prompt.** It sends only the *field name*, the *failed value*, and a
   description of the *rule that failed* (the allowed vocabulary list, or the regex pattern).
   The system prompt forces a strict JSON reply: `{"proposal": ..., "rationale": ...}`.
3. **Calls the model.** `temperature=0.0` (deterministic), default model
   `anthropic/claude-haiku-4`, `max_tokens=256`, 30 s timeout — configurable via
   `CORRECTOR_MODEL_NAME` / `CORRECTOR_MAX_TOKENS` / `CORRECTOR_TIMEOUT_SECONDS`.
4. **Parses defensively.** Strips markdown fences, parses JSON. Any failure (HTTP error, bad
   JSON, empty proposal) degrades gracefully to `status: "invalid"` — the pipeline never breaks
   on a bad corrector response.

## The outcome a field carries

Each validated field ends up with a `ValidationOutcome`:

| Field | Meaning |
|---|---|
| `status` | `valid` / `invalid` / `corrected` |
| `rule_failed` | `"regex"` or `"vocabulary"` |
| `original_value` | the value the VLM extracted (preserved) |
| `corrector_proposal` | the suggested fix (only when `corrected`) |
| `rationale` | the model's brief explanation |

## Key point: it is a *proposal*, not an auto-fix

A `corrected` status means **a suggestion is waiting**, not that the data changed. In the
**Verify cockpit**, the field shows the original value plus a *"Proposed: …"* chip with the
rationale. The curator:

- **Accepts** it — press **Enter** (or click ✓) → `acceptCorrectorProposal` writes the proposal
  into the field.
- **Rejects** it → `rejectCorrectorProposal` keeps the original.

So the human stays in the loop; the LLM only accelerates triage.

## Cost controls, in summary

- Fires **only on rule failure** of corrector-flagged fields.
- Hard **per-batch call cap** (thread-safe).
- Cheap **text-only** model, `max_tokens=256`, deterministic.
- Never a second VLM/vision call — it works purely from the failed value + rule text.

---

# 🇩🇪 Deutsch

## Die Idee in einem Satz

Nachdem das VLM eine Karte extrahiert hat, wird jedes Feld gegen seine Validierungsregel
geprüft; **scheitert** ein Feld an seiner Regel, wird optional ein günstiges, reines
**Text-LLM** gebeten, einen korrigierten Wert *vorzuschlagen* — den ein Kurator dann annimmt
oder ablehnt. Der Korrektor überschreibt Daten niemals stillschweigend.

## Wann er ausgelöst wird

Der Korrektor läuft für ein Feld **nur, wenn alle drei Bedingungen erfüllt sind**
(`apps/backend/app/services/validation/runner.py`):

1. Der Batch hat den Korrektor-Schalter aktiviert (`corrector_enabled`).
2. Die Regel des konkreten Feldes hat `corrector_enabled: true`.
3. Das Feld ist tatsächlich an seiner Validierung **gescheitert** (Regex- oder
   Closed-Vocabulary-Prüfung).

Ein Feld, das die Validierung besteht, wird als `valid` markiert und berührt das LLM nie — für
saubere Daten entstehen also keine Kosten.

## Der Ablauf pro Feld

```
VLM-Extraktion → run_validation() pro Feld
        │
        ├── regex_ok UND vocab_ok? ──── ja ──► status: "valid"   (fertig, kein LLM)
        │
        └── gescheitert (regex | vocabulary)
                 │
                 ├── Korrektor NICHT aktiv ──► status: "invalid"  (für Kurator markiert)
                 │
                 └── Korrektor aktiv ──► invoke_corrector()
                            │
                            ├── Vorschlag erhalten ──► status: "corrected" + Vorschlag + Begründung
                            └── Fehler / Limit / leer ──► status: "invalid"
```

## Was der Korrektor konkret tut (`corrector.py`)

1. **Limit-Prüfung (thread-sicher).** Ein Zähler pro Batch begrenzt die Kosten. Bei
   `used >= cap` wird `invalid` mit der Begründung *„Correction cap reached"* zurückgegeben —
   ohne API-Aufruf. Das Hochzählen ist durch einen Lock geschützt, da die OCR Karten
   nebenläufig in einem Thread-Pool verarbeitet.
2. **Baut einen fokussierten Prompt.** Gesendet werden nur der *Feldname*, der *gescheiterte
   Wert* und eine Beschreibung der *gescheiterten Regel* (die erlaubte Vokabularliste oder das
   Regex-Muster). Der System-Prompt erzwingt eine strikte JSON-Antwort:
   `{"proposal": ..., "rationale": ...}`.
3. **Ruft das Modell auf.** `temperature=0.0` (deterministisch), Standardmodell
   `anthropic/claude-haiku-4`, `max_tokens=256`, 30 s Timeout — konfigurierbar über
   `CORRECTOR_MODEL_NAME` / `CORRECTOR_MAX_TOKENS` / `CORRECTOR_TIMEOUT_SECONDS`.
4. **Parst defensiv.** Entfernt Markdown-Codezäune, parst JSON. Jeder Fehler (HTTP-Fehler,
   ungültiges JSON, leerer Vorschlag) fällt sauber auf `status: "invalid"` zurück — die
   Pipeline bricht nie an einer fehlerhaften Korrektor-Antwort ab.

## Das Ergebnis, das ein Feld trägt

Jedes validierte Feld erhält ein `ValidationOutcome`:

| Feld | Bedeutung |
|---|---|
| `status` | `valid` / `invalid` / `corrected` |
| `rule_failed` | `"regex"` oder `"vocabulary"` |
| `original_value` | der vom VLM extrahierte Wert (bleibt erhalten) |
| `corrector_proposal` | der vorgeschlagene Korrekturwert (nur bei `corrected`) |
| `rationale` | die kurze Begründung des Modells |

## Kernpunkt: Es ist ein *Vorschlag*, keine Auto-Korrektur

Der Status `corrected` bedeutet, dass **ein Vorschlag bereitliegt** — nicht, dass sich die
Daten geändert haben. Im **Verify-Cockpit** zeigt das Feld den ursprünglichen Wert plus einen
*„Proposed: …"*-Chip mit der Begründung. Der Kurator:

- **nimmt an** — **Enter** drücken (oder ✓ klicken) → `acceptCorrectorProposal` schreibt den
  Vorschlag in das Feld.
- **lehnt ab** → `rejectCorrectorProposal` behält den ursprünglichen Wert.

So bleibt der Mensch in der Schleife; das LLM beschleunigt lediglich die Triage.

## Kostenkontrolle in Kürze

- Wird **nur bei Regelverstoß** von korrektor-markierten Feldern ausgelöst.
- Hartes **Aufruf-Limit pro Batch** (thread-sicher).
- Günstiges **reines Text-Modell**, `max_tokens=256`, deterministisch.
- Nie ein zweiter VLM-/Vision-Aufruf — arbeitet ausschließlich mit dem gescheiterten Wert +
  dem Regeltext.
