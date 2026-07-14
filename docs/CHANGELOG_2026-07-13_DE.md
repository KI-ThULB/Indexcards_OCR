# Indexcards OCR — Funktionsübersicht (Stand 13.07.2026)

> Dokumentation der an diesem Tag umgesetzten Funktionen. Für Confluence formatiert.

---

## Überblick

Am 13.07.2026 wurden acht Änderungen umgesetzt — im Kern zwei fachliche Funktions-Pakete
(**Konfidenz-Bewertung + Bildbeschreibung** sowie **konfigurierbarer Ollama-Anbieter**),
eine umfassende **Sicherheits-Härtung** aus einem Penetrationstest, sowie **Datenschutz-**
(DSGVO-)Funktionen und begleitende Korrekturen/Dokumentation.

| # | Bereich | Funktion |
|---|---|---|
| 1 | OCR | Konfigurierbarer Ollama-Anbieter pro Einrichtung |
| 2 | Sicherheit | Backend-Härtung gegen Pentest-Findings W-01…W-08 |
| 3 | Datenschutz | Aufbewahrungsrichtlinie + Sicherheits-Audit-Log (DSGVO) |
| 4 | OCR | Konfidenz-Bewertung (pro Feld + gesamt) + optionale Bildbeschreibung |
| 5 | OCR | Konfigurierbares Timeout für VLM-Anfragen |
| 6 | Infrastruktur | WebSocket-Allow-List akzeptiert Backend-Origin (Vite-Dev-Proxy) |
| 7 | Wartung | Neu generierte gemeinsame Typen + ignorierte lokale Artefakte |
| 8 | Dokumentation | README auf v1.0 aktualisiert |

---

## 1. Konfidenz-Bewertung + Bildbeschreibung (OCR)

Beide Funktionen nutzen den **bereits vorhandenen einzelnen VLM-Aufruf** — kein zusätzlicher
API-Roundtrip.

### 1.1 Konfidenz pro Feld + Gesamtwert

- **Prompt-Vertrag:** Der Prompt fordert das Modell auf, statt einer flachen Struktur ein
  umschlossenes Objekt zurückzugeben:
  ```json
  {
    "fields": { … },
    "confidence": { "<Feld>": 0.0–1.0 },
    "confidence_overall": 0.0–1.0
  }
  ```
- **Defensives Parsing:** `ocr_engine._split_extraction` verarbeitet sowohl das neue
  umschlossene Format als auch das alte flache Format. Ignoriert ein Modell den Vertrag,
  wird das gesamte Objekt als `fields` (ohne Konfidenz) behandelt — die Extraktion bricht
  also nie an der Antwortstruktur.
- **Bereinigung:** Konfidenzwerte werden auf `[0,1]` begrenzt; nicht-numerische Werte und
  `NaN` werden verworfen. Es werden nur Konfidenzen für tatsächlich vorhandene Felder behalten.
- **Datenmodell:** `ExtractionResult` trägt `confidence` und `confidence_overall` getrennt
  von den Daten.
- **Frontend:** 0–100 %-Chips pro Feld mit Farbband (grün ≥ 85 %, gelb ≥ 60 %, sonst rot) in
  Ergebnistabelle und Verify-Cockpit, plus eine sortierbare Spalte **„Ø Konf."** zur Triage.
  CSV-/JSON-Export enthalten die Konfidenz-Spalten; XML-Formate bleiben rein wertebasiert.
- **Hinweis:** Konfidenz ist ein QS-Signal zur Triage, **keine** Grundwahrheit. Bei
  Mehrfach-Einträgen (JSON-Array) wird die Konfidenz in v1 bewusst übersprungen.

### 1.2 Bildbeschreibung (optional aktivierbar)

- Neuer Batch-Schalter **`describe_pictures`** (analog zum Korrektor-Schalter), durchgereicht
  von `BatchCreate` → `config.json` → `run_ocr_task` → `ocr_engine`.
- Ist er aktiv, beschreibt das Modell ein etwaiges Bild/Zeichnung/Foto knapp auf Deutsch in
  einem eigenen Feld **`Bildbeschreibung`**, das unverändert durch die normale Feld-Pipeline
  läuft (Spalten, Export).
- **Abwärtskompatibel:** Vor v1.1 verarbeitete Batches werden ohne Konfidenz-Spalte und ohne
  Bildfeld dargestellt; der Schalter ist standardmäßig aus.

> Tests: +9 (61 gesamt) — Formen/Bereinigung von `_split_extraction`, Prompt-Vertrag,
> Konfig-Roundtrip und deterministisch gemocktes End-to-End-Ergebnis.

---

## 2. Sicherheits-Härtung gegen Pentest-Findings W-01…W-08

Sicher per Voreinstellung: Lokale Einzel-Kurator-Nutzung bleibt unverändert (Auth aus, an
`127.0.0.1` gebunden). Die Produktions-Härtung wird per `.env` hinter einem Reverse-Proxy
aktiviert. Zentrales neues Modul: `core/security.py`.

| Finding | Maßnahme |
|---|---|
| **W-01** Auth | Optionales, per Umgebungsvariable aktiviertes Bearer-Token auf der JSON-API (`require_auth`, **Constant-Time-Vergleich**) + WebSocket-`?token=`; Standard-Bindung `127.0.0.1`. No-op, solange kein `AUTH_TOKEN` gesetzt ist. |
| **W-02 / W-05 / K-3** Path-Traversal | Zentrale Validierer: uuid4-Session-IDs, `[A-Za-z0-9._-]` für Namen/Dateinamen (verwirft `.`/`..`/Dotfiles) und `safe_join()` als letzte Absicherung, dass der aufgelöste Pfad im Basisverzeichnis bleibt. |
| **W-03 / K-4 / H-1** Stored-XSS + Upload | `StaticFiles`-Mount ersetzt durch eine validierte Bild-Route (Endungs-Whitelist, expliziter Content-Type, `nosniff`). Upload prüft Endung **+ Magic-Bytes** (JPEG/PNG/TIFF, da `imghdr` in Python 3.13+ entfernt wurde — HTML/SVG/Skripte werden abgewiesen) sowie Größen- und Anzahl-Limits mit frühem Abbruch. |
| **W-04 / H-4** WebSocket | Origin-Allow-List + Token-Prüfung **vor** `accept()`; Schließen mit Code `1008` bei Fehler. |
| **W-06 / H-2 / M-6** | Lockfile für genau einen aktiven Lauf pro Batch (409 bei parallelem Start/Retry) + slowapi-Rate-Limits auf Upload/Start/Reconcile mit konfigurierbarem (Redis-fähigem) Storage-URI. |
| **W-07 / H-6** | Generische 500er (kein `str(e)`-Leak); OpenAPI/Docs hinter `ENABLE_DOCS`. |
| **W-08 / M-1 / F-3** | Security-Header-Middleware (CSP, nosniff, Referrer-Policy, X-Frame-Options); optional striktes CORS. |
| **H-7** | `requirements.txt` mit `==` gepinnt; slowapi ergänzt. |

- **Frontend:** axios setzt standardmäßig den `Authorization`-Header, der WebSocket nutzt
  `?token=` aus `VITE_API_TOKEN` — dasselbe gebaute Bundle funktioniert mit und ohne Token.
- **Dokumentation:** `DEPLOYMENT.md` zu einem Produktionsleitfaden umgeschrieben
  (NGINX/Apache/Caddy/Docker Compose, TLS, WebSocket-Proxying, Umgebungsvariablen-Referenz).

> Tests: neue `apps/backend/tests/` (35 Tests) für Pfad-Validierung, Bild-Auslieferung, Auth,
> WS-Origin/-Token und Security-Header. Die PoCs aus dem Bericht wurden erneut gespielt und
> blockiert.

---

## 3. Datenschutz: Aufbewahrung + Sicherheits-Audit-Log (DSGVO)

- **Aufbewahrungsrichtlinie:** konfigurierbares automatisches Löschen abgeschlossener Batches
  (opt-in, standardmäßig aus) über `RETENTION_DAYS` / `AUTO_PURGE_AFTER_EXPORT`, mit
  Dry-Run-Vorschau und explizitem manuellem Löschen je Batch.
- **Sicherheits-Audit-Log:** append-only JSONL (`data/audit.log.jsonl`) datenschutzrelevanter
  Ereignisse (Auth, Start/Abbruch/Löschen, Export, Purge, Konfig-Änderungen) — **ohne**
  OCR-Text und **ohne** Secrets.
- Verschlüsselung im Ruhezustand wird an die Hosting-Infrastruktur delegiert.
- Umgesetzt als Audit-Punkte **I-2 / I-3**.

---

## 4. Konfigurierbarer Ollama-Anbieter pro Einrichtung (OCR)

- Der VLM-/Ollama-Anbieter ist zur Laufzeit über die Backend-`.env` konfigurierbar — **keine
  Code-Änderung, kein Frontend-Rebuild**.
- Endpunkt und Zugangsdaten bleiben rein backend-seitig; der Browser kontaktiert Ollama nie
  direkt.
- Installierte Modelle werden automatisch erkannt und auf vision-fähige gefiltert, mit
  optionaler Allow-List.

---

## 5. Konfigurierbares Timeout für VLM-Anfragen (OCR)

- Das Timeout für VLM-Anfragen ist nun konfigurierbar, statt fest im Code hinterlegt zu sein —
  robuster gegenüber langsameren, selbst-gehosteten Modellen.

---

## 6. Kleinere Korrekturen & Wartung

- **WebSocket-Allow-List (Fix):** akzeptiert den Backend-Origin in der Standard-Allow-List,
  damit der Vite-Dev-Proxy funktioniert.
- **Gemeinsame Typen (Wartung):** neu generiert; lokale Audit-/Patch-Artefakte werden nun
  per `.gitignore` ausgeschlossen.
- **README (Dokumentation):** auf die v1.0-Änderungen aktualisiert.
