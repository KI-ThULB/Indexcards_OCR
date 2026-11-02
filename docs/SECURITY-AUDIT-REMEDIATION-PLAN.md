# Security-Audit: Abgleich und priorisierter Maßnahmenplan

Stand: 2026-11-02. Repository `Indexcards_OCR`, Branch `fix/security-audit-2026`, HEAD `71fa7af`. Ausgangszustand: sauberer Git-Working-Tree. Dieser Durchlauf verändert ausschließlich dieses Dokument; keine Fixes, Dependency-Updates, Commits oder Änderungen produktiver Daten/Konfigurationen.

## Bewertungsgrundlage und Grenzen

Quellen:

- **A:** `IT_report/SECURITY_AUDIT_WEBAPP.md`, Audit vom 2026-05-22 auf älterem Branch `docs/v1.0-handover` (K-, H-, M-, N-, I-, F-IDs).
- **P:** `IT_report/PENTEST_REPORT_WEBAPP.md` (W-01 bis W-09); historische Live-PoCs sind kein Nachweis für den heutigen Stand.
- **R:** `IT_report/REMEDIATION_PLAN_WEBAPP.md`; teilweise Sollbeschreibung, keine vollständige Implementierungsbescheinigung.
- **Z:** `IT_report/Indexcards_OCR_Pentest_Audit_Zusammenfassung.md`; historische Managementzusammenfassung.
- **D:** `SECURITY.md`, `docs/DEPLOYMENT.md`, `docs/CHANGELOG_2026-07-13_DE.md`, `docs/BULK_PROCESSING_IMPLEMENTATION_PLAN.md`.
- **M:** `.planning/v1.0-MILESTONE-AUDIT.md` vom 2026-05-18, funktionaler Integrationsaudit. Nicht mit einem aktuellen Security-/Deployment-Abnahmetest gleichzusetzen; nachfolgende Phasen/Fixes berücksichtigen.
- **C:** aktueller Code, Tests und Git-Historie. Ein gesonderter neuerer Deployment-Auditbericht wurde im Repository nicht gefunden; Betriebsbefunde ergeben sich aus D/C.

Relevante jüngste Commits: `71fa7af` Checkpoint-Exception-Logging; `eb879a5` Docker-/Proxy-Authentifizierung dokumentiert; `5b0d109` OCR-/Provider-Logs bereinigt; `21a33fe` WebSocket-Zustand nach Löschen entfernt; `32b386d` Löschen während OCR verhindert; `a6186cb` Python- und `366740d` npm-Dependencies aktualisiert; `72b2330` Corrector-Provider-Schlüssel isoliert. Bereits enthalten: `6d74866` fertige Bulk-Ergebnisse bei Cancel erhalten, `576e7ac` Bulk-Ausgabe/Stop, `fd1e36c` Abbruch bei Provider-Abrechnungsfehlern und `b51c5a3` explizites Provider-Routing.

**Evidenzklassen:** „bestätigt“ bedeutet konkreter Codepfad oder isolierter Nachweis, nicht automatisch erfolgreiche externe Ausnutzung. „Potenziell“ benennt Voraussetzung und fehlenden Nachweis. Status und Evidenz sind getrennt: „offen“ kann auch eine nachweislich fehlende Schutzmaßnahme betreffen. „Behoben“ gilt für den bezeichneten Teilumfang, keine allgemeine Sicherheitsgarantie.

Prioritäten: **P0** Freigabebedingung vor Netzbetrieb; **P1** vor Produktivbetrieb bzw. kurzfristig; **P2** anschließende Härtung; **P3** Wartung. Komplexität: **S** lokal, **M** mehrere Komponenten, **L** Architektur/Betrieb. Keine Aufwandsschätzung in Personentagen ohne Implementierungsplanung.

## Durchgeführte Verifikation

- Python 3.14.3, vorhandene Backend-venv, keine Installation: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/ -q -p no:cacheprovider` in `apps/backend`: **526 passed, 606 warnings, 16.72 s**. Warnungen betreffen unter anderem Pydantic-, Starlette/httpx- und asyncio-Abkündigungen; keine fehlgeschlagenen Tests. `tests/conftest.py` leitet die Datenhaltung vor App-Import nach `/tmp` um und deaktiviert Bulk standardmäßig.
- Isolierte In-Memory-/Temp-Proben mit synthetischem Sentinel: Corrector-Exception erscheint im Log und `rationale`; `get_batch_path` folgt angelegtem Batch-Verzeichnis-Symlink; `_RowWriter` erzeugt für `=1+1` die unveränderte Zelle `"=1+1"`; Redis-Storage-Initialisierung wirft `ConfigurationError`. Keine echten Provideraufrufe oder Datenmanipulationen.
- `npm audit --json --ignore-scripts`: **nicht auswertbar**, Registry-DNS `ENOTFOUND registry.npmjs.org`; Exit 1 bedeutet hier keinen Vulnerability-Nachweis. `python -m pip_audit --version`: Modul fehlt. Keine nachträgliche Installation.
- Keine neuen Persistenz-, Last-, Browser- oder Mehrprozess-Tests implementiert. Kein Live-Proxy-/SSO-, Docker-Build- oder Exploit-Test gegen produktive Systeme. Frontend-Script `test` meldet derzeit nur `No tests yet`.

## Befundregister

### SAR-01 — Netzfreigabe und Zugriffsschutz müssen betrieblich nachgewiesen werden

- **Quelle:** A K-1/K-2, P W-01, R, D; C `core/security.py::require_auth/check_ws_auth`, `api/api_v1/api.py`, `main.py::serve_batch_image`, beide Dockerfiles, `docs/DEPLOYMENT.md`.
- **Status/Evidenz:** **teilweise behoben**. HTTP-Router sind optional bearer-geschützt, WS prüft Token/Origin, lokaler Dev-Bind ist localhost. `AUTH_TOKEN` bleibt standardmäßig leer. Bildroute ist bewusst dem authentifizierenden Proxy überlassen. Docker bindet für interne Erreichbarkeit `0.0.0.0`; daraus allein folgt keine öffentliche Exposition. Tatsächliche Netz-/SSO-Konfiguration **ungeklärt**.
- **Relevanz/Priorität:** Vertraulichkeit/Integrität aller Bestände; **P0 als Freigabebedingung**, keine erneute Behauptung einer generell ungeschützten API.
- **Korrektur:** TLS/SSO für SPA, API, WS und Bilder durchgängig abnehmen; Backend nicht direkt veröffentlichen. Gemeinsamen Bearer nicht als Benutzer-/Rollenmodell behandeln. Tenant-/Batch-Ownership nur ergänzen, falls Benutzer gegeneinander abgeschottet werden sollen. Den dokumentierten Bildrouten-Ansatz beibehalten.
- **Tests:** bestehende `test_security.py`, `test_ws_auth.py`, `test_bulk_security.py`; ergänzend Proxy-E2E ohne/mit SSO für alle Routen einschließlich WS-Upgrades und direktem Backendzugriff.
- **Abhängigkeiten/Komplexität:** SAR-08/09/14; **M**, bei echter Mandantentrennung **L**.

### SAR-02 — Exception-Texte in Logs, WS-Fehlern und Bulk-Zuständen

- **Quelle/Dateien:** A H-6/M-3, P W-07. Betroffene Anwendungspfade: `main.py`, `core/{audit,delivery,error_reporting}.py`, `endpoints/{batches,bulk,config,reconcile,ws}.py`, `services/{bulk_export,bulk_manager,bulk_orchestrator,bulk_progress,ocr_engine,retention,ws_manager}.py`, `services/validation/corrector.py`; Browser-Logs in `features/processing/useProcessingWebSocket.ts` und `features/bulk/useBulkWebSocket.ts`.
- **Status/Evidenz:** **behoben für neu erzeugte Exception-Fehler in den geprüften Anwendungspfaden (Fix 1 einschließlich Reviewnachbesserung, 2026-11-02)**. Rohe Exception-Texte und vollständige Tracebacks werden dort nicht mehr geloggt oder in API-/WS-/Bulk-Fehler übernommen. Bereits vorhandene Provider-/GET-Results-Fixes bleiben erhalten. Bulk verwendet fest zugeordnete Meldungen anhand interner Fehlerkategorien, auch für Import-, Checkpoint-, verschwundene Batch- und Credential-/Billingfehler. Exception-Texte werden nicht als sichere Strukturfehlermeldungen durchgereicht. Hintergrundfehler bleiben im bisherigen Status-/Cleanup-Ablauf; Retry-, Abbruch-, OCR- und Persistenzsemantik bleiben unverändert.
- **Review-P1 implementiert:** `DeliveryErrorBoundary` umfasst den gesamten inneren HTTP-ASGI-Aufruf einschließlich Streaming-/Dateibody und später Hintergrundfehler. Für Exporte, Dateien und Streams wird nur der letzte Body-Frame bis zum erfolgreichen Abschluss zurückgehalten; vorherige Chunks werden weiter gestreamt. Bei später Exception bleiben Header/Teilinhalt bereits gesendet, es folgt aber kein erfolgreicher Abschlussframe und keine zweite HTTP-Antwort. Die Originalexception wird nicht an den Server weitergegeben. Uvicorn-h11 beendet die unvollständige Antwort mit einem festen Diagnoseeintrag ohne Traceback. Path-send wird für die inneren FileResponses deaktiviert, damit die Dateiauslieferung innerhalb der kontrollierten Read-/Send-Grenze bleibt. Normale JSON-Kommandos mit Content-Length schließen weiterhin vor langen OCR-BackgroundTasks ab; nachträgliche Fehler werden sicher diagnostiziert, können deren bereits abgeschlossene Antwort nicht zurücknehmen.
- **Export-Audit korrigiert:** `bulk.py::export_csv/export_failures_csv` hinterlegen Auslieferungsmetadaten statt vorab Erfolg zu protokollieren. Die Fehlergrenze schreibt `bulk_run_exported` erst nach erfolgreichem ASGI-Send mit `delivery_stage=server_send_complete`, bei erkanntem Fehler mit `result=failure` und `delivery_stage=server_send_failed`. Beide tragen `delivery_confirmation=asgi_send_only`. Generierungsfehler bleiben getrennte Fehlerereignisse. Dies bestätigt ausschließlich serverseitige Auslieferung, keinen Empfang oder Speichervorgang beim Benutzer.
- **Review-P2 implementiert:** `error_reporting.py::correlation_id/report_error` liefert feste Operations-/Fehlercodes und Exception-Typen ohne Texte/Tracebacks. Request-IDs werden serverseitig erzeugt und als `X-Request-ID` mit dem Log korreliert; fremde Header werden nicht ungeprüft übernommen. Reconciliation unterscheidet Konfigurations- und Requestfehler. Providerpfade unterscheiden fehlenden, unbekannten und deaktivierten Provider; öffentliche JSON-Formate bleiben unverändert. Bulk loggt die freigegebene Strukturfehlerkategorie mit Run-ID. Batch-Hintergrundfehler und WS-Close-Meldungen enthalten eine neutrale Referenz zum Logereignis.
- **WebSocket-Lifecycle korrigiert:** ein Fehler beim Replay nach `accept()` entfernt die Verbindung aus dem Connection-Manager und sendet Close-Code **1011** mit neutraler Referenz. Ein Fehler beim Schließen wird separat ohne Exception-Inhalt diagnostiziert.
- **Relevanz/Priorität:** ursprüngliche **P1**-Offenlegung möglicher OCR-, URL-, Credential- und Providerdaten; der abgegrenzte Implementierungsauftrag ist abgeschlossen. SAR-03/04 und die übrigen Befunde bleiben unverändert offen.
- **Implementierte Korrektur:** neutrale öffentliche Meldungen; technische Diagnose über Operation, Exception-Typ und vorhandene Batch-/Run-/Kanal-IDs statt Exception-Inhalt. Anwendungsseitige `logger.exception()`-Aufrufe durch Logging ohne `exc_info` ersetzt. Generische HTTP-Fehler werden vor Starlettes erneut auslösender Serverfehlergrenze mit derselben neutralen 500-Antwort behandelt, damit die Exception nicht zur erneuten Traceback-Protokollierung an den ASGI-Server weitergereicht wird. WS-Verbindungs-/Replayfehler liegen im bestehenden Fehlerhandler. Eingehende WS-Nachrichten und Browser-Parsefehler enthalten im Log keine vollständigen Nutzdaten mehr. Fachliche OCR-Diagnosen und bestehende Fehlercodes werden nicht pauschal entfernt.
- **Regressionstests:** neu `tests/test_error_disclosure.py` mit **31 parametrisierten Testfällen**: Corrector-HTTP-/JSON-/Runtime-Exceptions; Batch-Hintergrundfehler mit/ohne vorhandenen Status und echtes WS-Replay; generische HTTP-500 ohne Weiterreichen an den Test-ASGI-Server; Bulk-Runtime-/StructuralError in API, WS und `run.json`; Startkonflikt, Export, Fortschrittsaufbau/-versand, Zustandslesen und Klassifikation; WS-Sende-/Empfangs-/Replayfehler und eingehende Nutzdaten; Checkpoint-Resume/-Schreiben/-Retry; Batchanlage, Purge, Reconciliation, Resize-Fallback, Retention und Auditlog-Schreibfehler. Synthetische Geheimtexte dürfen weder in Ausgaben noch Logs erscheinen; LogRecords dürfen kein Traceback anhängen. Bestehender `test_bulk_run.py::test_run_state_never_stores_the_raw_provider_message` prüft zusätzlich Logs. Bestehende Sentinel- und OCR-/Routing-/Stop-/Resume-Tests bleiben erhalten.
- **Neue tatsächlich getestete Reviewpfade:** `tests/test_delivery_security.py` ergänzt **14 Fälle**: später Fehler in der echten Bulk-StreamingResponse und im FileResponse-Auslieferungspfad, nachdem Header/Teilinhalt gesendet wurden; erfolgreicher Stream-/Dateidownload; Fehler nach einem bereits erzeugten finalen Body-Frame in einer BackgroundTask; normales JSON-Kommando mit Antwort vor Hintergrundarbeit; reale WS-Annahme mit fehlschlagender Replay-Serialisierung und definiertem Close; globale Fehlerreferenz mit manipuliertem Request-ID-Header; drei Providerfehler, zwei Reconciliationfehler und Bulk-Strukturfehlerdiagnose. Die HTTP-Lifecycle-Tests verwenden den **installierten Uvicorn-h11-RequestResponseCycle mit echtem h11-Framing und Speichertransport**, einschließlich Server-Logging. Nachgewiesen sind Response-Start, Teilbody, fehlender Terminalframe, Transport-close, kein Sentinel/Traceback in Anwendungs- oder Uvicorn-LogRecords und ausschließlich fehlgeschlagenes Export-Audit. Erfolgsfälle prüfen vollständige Antwort und Erfolgs-Audit. Der WS-Test verwendet echte Endpoint-/Manager-/accept()-Abläufe im TestClient, keine vollständig gemockte connect()-Methode.
- **Validierung vor der Nachbesserung:** Ausgangslauf der betroffenen bisherigen Tests: **151 bestanden**. Nach Implementierung erweiterter betroffener Lauf: **205 bestanden, 543 Warnungen**; nach Wiederherstellung des bestehenden Hinweises „no longer exists“ für gelöschte Batches zusätzlicher gezielter Lauf: **49 bestanden, 37 Warnungen**. Abschließende Gesamtsuite: **557 bestanden, 610 Warnungen, 19,26 s**. Aufruf jeweils aus `apps/backend`: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest … -q -p no:cacheprovider`. Ruff für `app/` und neue Testdatei erfolgreich; Mypy mit Backend-Konfiguration: **43 Quelldateien ohne Fehler**. `git diff --check` erfolgreich. Warnungen betreffen bestehende Pydantic-/Starlette-/asyncio-Abkündigungen.
- **Validierung der Nachbesserung:** neue gezielte Lifecycle-/Diagnosefälle **14 bestanden**; kombinierter gezielter Lauf mit den bisherigen Sentinel-/Bulk-API-/Exporttests **120 bestanden, 92 Warnungen** vor Ergänzung des JSON-Timingfalls. Abschließende Gesamtsuite: **571 bestanden, 610 Warnungen, 19,74 s**. Ruff für Backend und beide Security-Testdateien erfolgreich; Mypy: **45 Quelldateien ohne Fehler**; `git diff --check` erfolgreich. Frontend-Build `npm run build --workspace @indexcards/frontend` erfolgreich, ohne neue Frontendänderung in dieser Nachbesserung; bestehende Hinweise auf `paper-noise.png` und Bundlegröße bleiben offen, kein Browserlaufzeittest.
- **Nicht getestete Infrastruktur-/Protokollgrenzen:** kein realer TCP/TLS-/Proxy-/SSO-/APM-Test; Uvicorn-h11 läuft im Speichertransport, andere ASGI-Server, Uvicorn-httptools, HTTP/2 und Browser-Downloadverhalten wurden nicht abgenommen. ASGI besitzt keine portable Abort-/Empfangsbestätigung: die Verbindungsschließung wurde für die installierte h11-Implementierung nachgewiesen. Ein nicht vom Server signalisiertes Disconnect oder ein nach erfolgreichem Send verlorener Download ist aus Anwendungssicht nicht sicher erkennbar; das Audit nennt daher ausdrücklich nur ASGI-Send, keine bestätigte Benutzerzustellung. Bereits gesendete Header/Statuscodes können nicht zurückgenommen werden. Fehler außerhalb der inneren HTTP-Anwendung (Server selbst, Startup/Shutdown, Prozessabbruch/Cancellation, Infrastruktur-Logging) unterliegen nicht dieser Fehlergrenze. Auch für diese Grenzen wird kein vollständiger Schutz behauptet.
- **Verbleibende Grenzen:** historisch bereits gespeicherte Fehlermeldungen/Logs werden nicht migriert oder gelöscht und können beim Lesen alter Zustände weiterhin sichtbar sein. Fachliche, geschützte OCR-Ergebnisdiagnosen können weiterhin begrenzte Modellinhalte enthalten; sie sind kein Exception-Logging. Proxy-/uvicorn-Access-Logs, APM und sonstige Infrastruktur bleiben außerhalb dieses Fixes (SAR-14/19); keine Live-Infrastruktur- oder Browser-Laufzeitabnahme (siehe gesonderte Testgrenzen). Für die beiden Browser-Hooks wurden ausschließlich Nutzdatenargumente aus Fehlermeldungen entfernt. Kein Dependency-/Deploymentwechsel und keine Produktivdatenänderung.
- **Abhängigkeiten/Komplexität:** Implementierung abgeschlossen; Regressionserhalt bei SAR-03/04/08/12. Ursprüngliche Schätzung **M**. Kein Commit/Push erstellt.

### SAR-03 — Checkpoint-Fehler führen zu Neustart oder scheinbar erfolgreichem Lauf

- **Quelle/Dateien:** A N-2/H-5; `services/ocr_engine.py::process_batch`, lokale Funktion `_save_checkpoint`; `endpoints/batches.py::retry_image`; `core/checkpoint.py::read_checkpoint`.
- **Status/Evidenz:** **offen**, bestätigter Kontrollfluss. Resume-Lesefehler setzen `results, audit = [], []`; Schreibfehler werden nur geloggt. Dadurch sind erneute Providerkosten, Verlust vorhandener Kurator-Audits und Erfolg trotz fehlender persistierter Ergebnisse möglich. Keine Disk-full-Fehlerinjektion in dieser Prüfung.
- **Relevanz/Priorität:** Integrität, Wiederaufnehmbarkeit, Kosten; **P1**.
- **Korrektur:** bei unlesbarem Checkpoint keine automatische Neuverarbeitung; Original sichern und expliziten Recovery-Schritt verlangen. Persistenzfehler müssen den Lauf kontrolliert stoppen und einen eindeutigen fehlgeschlagenen Zustand erzeugen. Retry darf bei fehlgeschlagener Zustandsänderung keinen neuen Lauf starten. Struktur der Checkpoint-Zeilen/Audit-Liste validieren statt stiller Normalisierung zu leerem Zustand.
- **Tests:** vorhandene Format-/Resume-/Audit-Tests in `test_checkpoint_compat.py`; zusätzlich defektes JSON, falsche Struktur, EACCES, ENOSPC und Replace-Fehler: Original bleibt erhalten, kein falsches `completed`, keine weiteren Provideraufrufe nach erkanntem Persistenzfehler.
- **Abhängigkeiten/Komplexität:** SAR-02/04; **M**.

### SAR-04 — Atomare Persistenz ist unvollständig; Read-Modify-Write bleibt unkoordiniert

- **Quelle/Dateien:** A H-5/I-1/N-2; `services/batch_manager.py::_record_history/update_batch_status/get_history`, `template_service.py::_read_templates/_save_templates`, `endpoints/batches.py::patch_result/revalidate_batch`, `core/atomic_io.py`, `core/checkpoint.py`.
- **Status/Evidenz:** **teilweise behoben**. Checkpoint/Bulk-Dateien nutzen atomare Writes. History-/Template-Pfade schreiben weiterhin direkt mit `open(..., 'w')`; Lesefehler werden teilweise als leere Liste behandelt. Zwei Checkpoint-Schreiber können trotz atomarem Replace auf demselben alten Snapshot arbeiten; OCR-Run-Lock sperrt keine allgemeinen PATCH-Operationen. Kein paralleler Datenverlust dynamisch erzeugt.
- **Relevanz/Priorität:** Integrität/Kurator-Audit und Status/Retention; **P1**.
- **Korrektur:** alle langlebigen Writer auf atomare Persistenz umstellen; transaktionale Sperre über Lesen, Ändern und Schreiben oder Datenbank/optimistische Revision. Fehler nicht als leere Daten überschreiben. Laufende OCR und Kuratoränderungen bewusst koordinieren. Dateisystem-/Plattformanforderungen dokumentieren.
- **Tests:** Prozessabbruch während Writes, zwei gleichzeitige PATCHes/Template-Updates/History-Updates, PATCH parallel OCR; keine verlorenen Updates/Audit-Einträge, gültige alte oder neue Datei.
- **Abhängigkeiten/Komplexität:** SAR-03/08; **L**.

### SAR-05 — CSV-Formelpräfixe werden nicht neutralisiert

- **Quelle/Dateien:** A F-1; `features/results/useResultsExport.ts::downloadCSV`, `services/bulk_export.py::_RowWriter.row/iter_consolidated_csv/iter_failures_csv`.
- **Status/Evidenz:** **offen**, bestätigte Serialisierung; Bulk-Probe `=1+1` bleibt unverändert. Quotes verhindern CSV-Strukturbruch, keine Tabellenkalkulations-Formeln. Tatsächliche Auswertung ist abhängig vom importierenden Programm; kein Excel-/LibreOffice-Exploit ausgeführt.
- **Relevanz/Priorität:** manipulierte OCR-/Dateiname-/Fehlerzellen beim Öffnen; **P1**.
- **Korrektur:** konsistente Spreadsheet-sichere Exportstrategie für jede Zelle einschließlich Header/Provenienz/Fehler; Formelpräfixe und führende Steuerzeichen berücksichtigen. Falls unveränderte Katalogdaten benötigt werden, bewusst getrennte Exportoption mit klarer Semantik vorsehen.
- **Tests:** `=`, `+`, `-`, `@`, Tab/CR/LF, führende Leerzeichen, Quotes/Unicode in Frontend-, Bulk- und Fehler-CSV; gezielter Excel-/LibreOffice-Import. Bestehende `test_bulk_export.py`/Gruppenexporttests erhalten.
- **Abhängigkeiten/Komplexität:** Exportvertrag abstimmen, sonst unabhängig; **M**.

### SAR-06 — Regex läuft ohne Zeitbudget im Backend und Browser

- **Quelle/Dateien:** A M-2/F-2; `validation/regex_rules.py::check_regex`, Frontend `clean/validationRuntime.ts`, `CleanStep.tsx`, `FacetPanel.tsx`, `ColumnWorkspace.tsx`, `RegexReplaceModal.tsx`.
- **Status/Evidenz:** **offen**, fehlende Laufzeitbegrenzung bestätigt; keine absichtlich lang laufende ReDoS-Probe. Syntaxfehlerbehandlung und Compile-Cache sind kein Ausführungszeitbudget. Angreifer benötigt Einfluss auf Pattern und passende Eingabe.
- **Relevanz/Priorität:** blockierter Serverworker/Browser; **P1 Backend**, **P2 Browser**.
- **Korrektur:** begrenzte Pattern-/Wertlänge; Engine mit garantiert begrenzter Laufzeit oder abbrechbare Prozessisolation. Browser-Auswertung in terminierbarem Worker, Debounce/Zeilenbudget. Heuristiken allein reichen nicht; Thread-Timeout beendet CPU-Arbeit nicht zuverlässig.
- **Tests:** pathologische Patterns in isoliertem Prozess/Worker mit hartem Gesamttimeout; Server/UI bleibt bedienbar, sichere Patterns behalten Semantik.
- **Abhängigkeiten/Komplexität:** SAR-10 für mögliche neue Engine; **M–L**.

### SAR-07 — Pfadvalidierung schützt nicht durchgängig gegen lokal platzierte Symlinks

- **Quelle/Dateien:** A K-3, P W-02/W-05; `core/security.py`, `batch_manager.py::get_temp_session_path/get_batch_path`, `endpoints/upload.py::upload_files`, `main.py::serve_batch_image`, `bulk_import.py::source_images/resolve_source_folder/_link_or_copy`.
- **Status/Evidenz:** **teilweise behoben**. Traversal-Komponenten werden verworfen; Bildroute verankert aufgelöste Pfade, Bulk verwirft statische Quell-Symlinks. `get_batch_path` gibt dagegen unaufgelöste Pfade zurück, Upload öffnet Zieldateien mit `wb` ohne No-follow. Isoliert bestätigt: bereits angelegter Batch-Symlink wird verfolgt. Kein Nachweis, dass ein entfernter API-Nutzer solche Links selbst anlegen kann. TOCTOU beim Austausch von Bulk-Quellen bleibt potenziell.
- **Relevanz/Priorität:** **P1 bei gemeinsam beschreibbarer Ablage**, sonst **P2**; lokale Schreib-/Austauschmöglichkeit erforderlich.
- **Korrektur:** Daten-/Importverzeichnisse ausschließlich Dienst/vertrauenswürdigen Operatoren schreibbar; Root-Verankerung in allen Services, vorhandene Symlinks ablehnen. Für angreifbar veränderliche Ablage deskriptorbasierte Opens mit No-follow/atomarer Anlage; `resolve` allein schließt Rennen nicht. Hardlink-Originale unverändert lassen.
- **Tests:** Symlink-Verzeichnis, Datei-Symlink auf externen Sentinel, Austausch zwischen Prüfung und Open/Copy; keine externen Lese-/Schreibzugriffe. `test_path_validation.py`, `test_bulk_security.py`, `test_bulk_immutability.py` erhalten.
- **Abhängigkeiten/Komplexität:** SAR-11; **M**.

### SAR-08 — Dokumentierter Mehrworkerbetrieb widerspricht prozesslokaler Jobsteuerung

- **Quelle/Dateien:** D Compose/uvicorn `--workers 4`; `ws_manager.py::ConnectionManager`, `bulk_orchestrator.py` Task-/Stop-Steuerung, `bulk_manager.py::mark_interrupted_runs`, `main.py::lifespan`, `batch_manager.py` Run-Locks.
- **Status/Evidenz:** **offen**, Architekturkonflikt bestätigt, Mehrprozess-E2E ausstehend. WS-Zustände und Cancel-Events sind prozesslokal; Redis synchronisiert nur Rate Limits. Worker B erreicht daher nicht die Events/Verbindungen von Worker A. Startup-Recovery nimmt unterbrochene Runs an und entfernt Locks; Worker-Neustart während eines lebenden anderen Workers ist potenziell gefährlich.
- **Relevanz/Priorität:** wirkungslose Cancel-Aufrufe, fehlender Fortschritt, doppelte Arbeit/Kosten; **P1**.
- **Korrektur:** kurzfristig eine Backend-Instanz mit einem Worker als unterstützten Betriebsmodus festlegen und Beispiele anpassen. Für Skalierung eigener Jobworker mit geteilter Queue, Pub/Sub, gemeinsamem Stop-/Progress-Zustand sowie Besitzer-/Lease-basierter Crash-Recovery.
- **Tests:** Start auf A, WS/Cancel auf B, Reconnect und Restart von B während Run auf A; lebende Locks bleiben erhalten. Single-Worker-Stoptests ersetzen diese Tests nicht.
- **Abhängigkeiten/Komplexität:** SAR-04/09/12; **S** Betriebsbegrenzung, **L** Mehrworkerunterstützung.

### SAR-09 — Redis-Rate-Limiter aus Deploymentbeispiel ist nicht vollständig installierbar

- **Quelle/Dateien:** D Compose; `requirements.txt`, `core/rate_limit.py`, `core/config.py::RATE_LIMIT_STORAGE_URI`.
- **Status/Evidenz:** **offen**. Kein expliziter Redis-Client/Extra in Requirements; vorhandene Umgebung hat `limits 5.8.0`, aber kein `redis`. `storage_from_string('redis://localhost:6379')` scheitert schon an `ConfigurationError`, vor Netzwerkzugriff. Frischer Containerbau nicht getestet.
- **Relevanz/Priorität:** Deployment-/Startup-Verfügbarkeit; **P1** für dokumentiertes Redis-Deployment.
- **Korrektur:** Redis-Backend als gepinnte unterstützte Runtime-Abhängigkeit/Extra aufnehmen oder Redis-Beispiel bis dahin aus unterstütztem Setup nehmen; Storage-Ausfallverhalten definieren.
- **Tests:** frische Runtime-only-Installation, App-Startup mit Redis-URI, geteiltes 429-Verhalten und Ausfall-/Reconnect-Test.
- **Abhängigkeiten/Komplexität:** SAR-10/08; **S–M**.

### SAR-10 — Aktuelle CVE-Lage ungeklärt; vollständiger reproduzierbarer Dependency-Stand fehlt

- **Quelle/Dateien:** A H-7, jüngste Dependency-Commits; Root- und Frontend-`package-lock.json`, `requirements*.txt`, `.github/workflows/ci.yml`, `scripts/setup.mjs`, Dockerfiles.
- **Status/Evidenz:** **teilweise behoben**. Direkte Python-Pakete sind gepinnt, npm-Root-Lock aktualisiert. Python-Transitiven-Lock/Hashes fehlen; CI enthält keine npm-/pip-Audit-Gates; Setup nutzt `npm install`, CI/Docker `npm ci`. Zwei npm-Locks bedürfen einer klaren Zuständigkeit. Mutable Image-Tags begrenzen Build-Reproduzierbarkeit. **Aktuelle bekannte Sicherheitsbefunde: ungeklärt**, npm-Scan ohne Registryzugriff, pip-audit fehlt. Keine CVE allein aus Versionsnummern oder Commit-Texten bestätigt.
- **Relevanz/Priorität:** Supply Chain und verlässliche Installation; **P1** Scan/Installationsnachweis, **P2** weitergehende Pinning-Härtung.
- **Korrektur:** in netzfähiger isolierter CI exakte Root-Lock- und Runtime-/Dev-Python-Auflösung auditieren, Advisory-ID/Version/Fix/Reichweite dokumentieren. Transitive Python-Locks/Hashes pro unterstützter Plattform, ein kanonischer Workspace-Installationsweg, Image-Digests und kontrollierte Aktualisierung. Legacy-App separat bewerten, nicht mit Web-Runtime vermischen. Keine pauschalen Major-Updates ohne Befund.
- **Tests:** frisches `npm ci`, unveränderter Lock, Python-Installation aus Lock, Runtime-/Image-Scan, Build/Import/526 Backendtests; CI meldet nicht erreichbare Advisory-Quelle als ungeklärten Scan, nicht als „0 Findings“.
- **Abhängigkeiten/Komplexität:** Netzwerk und SAR-09; **M**.

### SAR-11 — Upload-Limits greifen nach Multipart-Verarbeitung; Gesamtquoten fehlen

- **Quelle/Dateien:** A H-1/H-2/M-5; `upload.py::upload_files`, `batch_manager.py::cleanup_stale_sessions`, `main.py::lifespan`, D Proxyvorgaben.
- **Status/Evidenz:** **teilweise behoben**. Endung/Magic Bytes und pro Datei 25 MiB/pro Request 2000 Dateien werden kontrolliert. FastAPI stellt aber bereits geparste `UploadFile`s bereit; diese Schleife begrenzt nicht frühzeitig den gesamten eingehenden HTTP-Body oder Parser-Spool. Keine Gesamtsession-/Diskquote; wiederholte Requests und abgebrochene Mehrdatei-Uploads können Restdateien hinterlassen. Cleanup läuft nur beim Start. Proxy-Limits im realen Betrieb ungeprüft.
- **Relevanz/Priorität:** temporärer Speicher/Disk/DoS; **P1**.
- **Korrektur:** verbindliches Gesamtbody-Limit am Proxy und geeignete ASGI-/Parser-Grenzen; Session-/Gesamtspeicherquoten, eindeutige Kollisionsstrategie und Cleanup bei Fehler/Disconnect. Periodischer, aktive Sessions respektierender Cleanup.
- **Tests:** Chunked/ohne Content-Length, zu viele Multipart-Teile, viele kleine Requests, Oversize, Disconnect und Fehler in Datei N; gemessene Spool-/Diskgrenze. Magic-Header-Testdaten sind kein Nachweis gültiger Bilddekodierung.
- **Abhängigkeiten/Komplexität:** SAR-01/07/13; **M**.

### SAR-12 — Globale Job-/Kostenobergrenze und WS-Ressourcenbudget fehlen

- **Quelle/Dateien:** A H-2/M-6, P W-06; `ocr_engine.py::process_batch`, `batches.py` Start/Retry, `ws.py`, `ws_manager.py`.
- **Status/Evidenz:** **teilweise behoben**. Ein aktiver Lauf je Batch, scoped Rate Limits und ein Bulk-Run-Lock existieren. Unterschiedliche Batches können jeweils einen ThreadPool starten; ein Request-Ratenlimit begrenzt nicht die Zahl gleichzeitig lang laufender Jobs. WS-Verbindungen/Zustandsspeicher haben kein explizites anwendungsseitiges Budget. Server-/Proxy-Grenzen wurden nicht gemessen.
- **Relevanz/Priorität:** RAM/CPU/Providerkosten; **P1** globale Jobgrenze, **P2** WS-Härtung.
- **Korrektur:** globale Queue/Concurrency-/Kostenbudgets, begrenzte WS-Verbindungen und Nachrichten, State-TTL und Dead-Connection-Cleanup; bei mehreren Prozessen gemeinsam koordinieren.
- **Tests:** parallele Starts verschiedener Batches überschreiten das Budget nicht; Burst/WS-Flood bleiben begrenzt; fertige/gelöschte Zustände werden bereinigt.
- **Abhängigkeiten/Komplexität:** SAR-08/09; **M–L**.

### SAR-13 — Bilddekodierung kann Schutzfehler durch Raw-Fallback umgehen

- **Quelle/Dateien:** A N-1/H-1; `ocr_engine.py::_encode_image_to_base64`, `upload.py`, `bulk_import.py`.
- **Status/Evidenz:** **offen**, bestätigter Fallbackpfad. Pillow besitzt bereits eigene Pixel-Bomben-Warnungen/-Fehler; „überhaupt kein Pixel-Limit“ wäre unzutreffend. Der generische Catch beim Resize fällt aber auf vollständiges `read()` und Base64 ohne Resize zurück, auch bei Dekodier-/Bombenfehlern. Bulk-Quellen unterliegen nicht dem HTTP-Dateigrößenlimit. Kein realer Ressourcenangriff durchgeführt.
- **Relevanz/Priorität:** Speicherverbrauch, Decoderlast und übergroße Provider-Payloads; **P1**.
- **Korrektur:** harte Byte-/Pixel-/Dimension-/Framebudgets für beide Ingestionpfade; Bombenwarnungen/-fehler sicher ablehnen, kein Raw-Fallback bei Schutzverletzung; Bilder mit Context Manager öffnen, Farbmodus bewusst konvertieren. Auch Providerantworten begrenzen.
- **Tests:** große Abmessungen bei kleinen Dateien, korrupte JPEG/TIFF, Mehrseiten-TIFF, RGBA/CMYK; keine Raw-Übertragung nach abgewiesener Dekodierung, konsistente Bulk-/Upload-Grenzen.
- **Abhängigkeiten/Komplexität:** SAR-11/15; **M**.

### SAR-14 — Build-Token im Browser und WS-Query sind keine vertraulichen Secrets

- **Quelle/Dateien:** A F-6/M-3, R Frontend-Bearer; `frontend/src/api/client.ts`, `frontend/Dockerfile`, WS-Hooks, D.
- **Status/Evidenz:** **teilweise behoben**: API-/WS-Tokenübermittlung implementiert. `VITE_API_TOKEN` wird absichtlich in das Bundle eingebaut; `?token=` kann in Access-/Handshake-Logs gelangen. Tatsächliche Logspeicherung nicht geprüft. Dies ersetzt keine individuelle Anmeldung.
- **Relevanz/Priorität:** Missbrauch eines gemeinsamen Backend-Tokens; **P1** Betriebskonzept, **P2** technische Weiterentwicklung.
- **Korrektur:** Authentifizierung primär am Proxy; wenn Backend-Bearer verwendet wird, möglichst serverseitig injizieren und WS-Konzept passend gestalten. Querystrings/Authorization in Proxy-/uvicorn-/APM-Logs redigieren. Bereits exponierte Tokens nach Umsetzung rotieren, nicht in diesem Auditlauf.
- **Tests:** Bundle-/Source-Map-Prüfung mit synthetischem Token, Proxy-/WS-Log-Sentineltest, SSO-Sessionablauf und Tokenrotation.
- **Abhängigkeiten/Komplexität:** SAR-01/02; **M**.

### SAR-15 — Provider-Routing verbessert; Redirect-/Antwort-/Modellgrenzen fehlen teilweise

- **Quelle/Dateien:** A H-3/M-3/M-4; `batches.py::_resolve_provider`, `ocr_engine.py::_call_vlm_api_resilient/_split_extraction/_process_card_sync`, `corrector.py`, `core/config.py`.
- **Status/Evidenz:** **teilweise behoben**. Endpunkte kommen aus Serverkonfiguration, unbekannter/fehlender Provider fällt nicht mehr still auf Cloud zurück; providergetrennte Keys vorhanden. Daher kein bestätigtes frei wählbares SSRF-Ziel über den Provider-Namen. Requests folgen standardmäßig Redirects; Egress-/Redirect-Szenario **potenziell**. `_entries` serialisiert Arrays vollständig und skalare Zusatzfelder werden nicht strikt durch ein erlaubtes Extraktionsschema begrenzt; Gruppen haben bereits eigene Normalisierung/Limits.
- **Relevanz/Priorität:** Integrität, Speicher und unerwünschte Netz-/Datenflüsse; **P2**, Cloudfreigabe vor Produktion.
- **Korrektur:** erlaubte Provider/Modelle serverseitig erzwingen; Redirects ablehnen oder jedes Ziel prüfen; institutionelle Egress-Regeln. HTTP-Antwortbytebudget, Feld-/String-/Arraygrenzen und Schemafilter auch für skalare/Multi-Entry-Antworten. `ollama`-Default nicht als echten Authentifizierungsnachweis behandeln. Cloud-Extraktion und davon unabhängigen Corrector gesondert freigeben.
- **Tests:** Redirect auf unerlaubten Host ohne Folgerequest, unbekannter/deaktivierter Provider, Modell außerhalb Policy, übergroße Antwort/Arrays/Zusatzfelder; Routing-/Corrector-/Gruppentests erhalten.
- **Abhängigkeiten/Komplexität:** SAR-10/13/19; **M**.

### SAR-16 — Authority-URIs werden ohne zentrale Schema-Policy verlinkt

- **Quelle/Dateien:** A F-4; `features/results/ValidationBadge.tsx`, `features/verify/CockpitBadge.tsx`, `features/clean/CandidateDrawer.tsx` (`href={...uri}`).
- **Status/Evidenz:** **offen** als fehlende URL-Policy; erfolgreiche JavaScript-Ausführung **ungeklärt**. React-/Browser-Schutz darf nicht ignoriert werden; kein Live-XSS-Nachweis. `noopener noreferrer` ist bereits vorhanden.
- **Relevanz/Priorität:** potenziell unsichere externe Navigation, **P2**.
- **Korrektur:** zentrale URL-Validierung nur für zulässige HTTP(S)-Authority-URLs, ungültige Werte als Text; optional Hostallowlist und Backendvalidierung.
- **Tests:** `javascript:`, `data:`, Steuerzeichen/Whitespace, relative und gültige Authority-URLs im tatsächlich eingesetzten React/Browser; keine aktive unsichere Navigation.
- **Abhängigkeiten/Komplexität:** keine; **S**.

### SAR-17 — Persistierte Sitzungsreferenzen und endloser WS-Reconnect

- **Quelle/Dateien:** A F-5/F-9/F-10; `store/wizardStore.ts::partialize`, `processing/useProcessingWebSocket.ts`, `upload/Dropzone.tsx`.
- **Status/Evidenz:** **offen** für gespeicherte `sessionId`/`batchId` und fortgesetzten Reconnect nach jeweils 1 s. Cleanup verhindert bereits Wiederverbindung nach Unmount. IDs in localStorage sind kein eigener Auth-Bypass; Gemeinschaftsrechner und fehlende Benutzerisolation sind Voraussetzungen. `Math.random` für rein lokale Datei-Keys ist kein bestätigter Sicherheitsfehler.
- **Relevanz/Priorität:** Sitzungsprivatsphäre/unnötige Last, **P2**; lokale Key-Erzeugung **P3**.
- **Korrektur:** Referenzen bei Benutzerwechsel/Logout löschen oder Sessionstorage nutzen, versionierte Persistenz; Backoff/Jitter/Obergrenze, Auth-Fehler beenden Reconnect. Lokale Keys optional `crypto.randomUUID()`.
- **Tests:** Benutzer-/Sessionwechsel, alte Storeversionen, WS-Close 1008, langdauernder Ausfall, Cleanup mit ausstehendem Timer.
- **Abhängigkeiten/Komplexität:** SAR-01/14; **S–M**.

### SAR-18 — Bereits behobene Traversal-/Stored-XSS-/Header-/Docs-Kernbefunde

- **Quelle/Dateien:** A K-3/K-4/H-1/H-4/H-6/M-1/N-3/F-3/F-6/F-7/F-8, P W-02 bis W-05/W-07/W-08; `security.py`, `upload.py`, `main.py`, `api.py`, API-Client, D.
- **Status/Evidenz:** **behoben im beschriebenen Kernumfang**, durch Codeabgleich und bestehende Tests gestützt. Direkte Traversal-Komponenten werden abgewiesen, HTML/SVG-Upload/-Auslieferung blockiert, Bildtypen/nosniff festgelegt, WS vor Accept geprüft, Security-Header und optional CORS vorhanden, OpenAPI standardmäßig deaktiviert. TLS ist dokumentierte Proxyaufgabe. Kein aktueller Beleg für die ursprünglichen uneingeschränkten Angriffe. Dokumentierte ASCII-Whitelist/UUID4-Aussagen sind genauer als der Code: Namen erlauben bewusst Unicode/Spaces, UUID-Prüfung prüft Form statt Versionsbits. Das ist für sich kein Traversal-Exploit.
- **Relevanz/Priorität:** ursprüngliche kritische Risiken; **kein erneuter Fixauftrag**, Regressionserhalt **P2**. SPA-Header am tatsächlichen Proxy weiter in SAR-01 abnehmen.
- **Korrektur:** Dokumentation an tatsächliche Validierungssemantik angleichen; keine inkompatible ASCII-Whitelist ohne Bedarf einführen. Restpfade separat SAR-02/07/11 behandeln.
- **Tests:** `test_security.py`, `test_path_validation.py`, `test_ws_auth.py`; zusätzlich exakte Size-/Count-Grenzen und erlaubte Unicode-/Space-Namen. Produktionsheader für SPA und Bilder überprüfen.
- **Abhängigkeiten/Komplexität:** SAR-01/07; **S**.

### SAR-19 — Retention/Audit implementiert; Datenschutz-Betriebsnachweise offen

- **Quelle/Dateien:** A I-2/I-3/M-3, Z; `core/audit.py::resolve_actor/log_event`, `services/retention.py`, Authority-Cache, D GDPR-Abschnitt.
- **Status/Evidenz:** **teilweise behoben**. Semantisches Auditlog, vertrauensgebundener Identity-Header, konfigurierbare Retention und Cache-TTL sind vorhanden; Standard-Retention/TTL 0 deaktiviert automatische Fristen. Audit ersetzt kein Proxy-Zugriffslog. Verschlüsselung, Backups, Logrotation/-zugriff, Verträge und reale Cloud-/Corrector-Freigabe **ungeklärt**. Personenbezug ist eine Daten-/Betriebsfrage, hier kein bestätigter Rechtsverstoß.
- **Relevanz/Priorität:** Vertraulichkeit/Nachvollziehbarkeit; **P1 betriebliche Freigabe**, **P2** Automatisierung.
- **Korrektur:** institutionelle Aufbewahrungs-/Lösch-/Backup-/Verschlüsselungspolicy nachweisen; Logbegrenzung und Manipulationsschutz definieren. Proxy muss Identitätsheader überschreiben und echte Peer-/Forwarded-IP-Verarbeitung mit uvicorn abgestimmt sein. Externe Extraktion und Corrector unabhängig bewerten. Bulk-Exporte und fehlgeschlagene Runs in Fristen einbeziehen.
- **Tests:** `test_audit.py`, `test_retention.py`; echte Proxykette mit gefälschten Headern, Fristablauf/Backups, Bulk-Datenspuren, Logging-Ausfall und prozessübergreifende JSONL-Konsistenz.
- **Abhängigkeiten/Komplexität:** SAR-01/02/04/15; **M**, organisatorische Nachweise separat.

### SAR-20 — Bereits behobene Batch-/Bulk-/Retry-Regressionsbefunde

- **Quelle/Dateien:** C jüngste Commits, D Bulkplan; `checkpoint.py`, `batch_manager.py`, `bulk_orchestrator.py`, `batches.py`, `ws_manager.py`, `corrector.py`.
- **Status/Evidenz:** **behoben für getestete Szenarien**: Legacy-/Objektcheckpoint kompatibel, GET liest ohne Migration; Audit über Resume erhalten; fertige Ergebnisse nach Cancel erhalten; Provider-Routing/Schlüsseltrennung; bounded Retry für getestete Fehler; aktive Batches nicht lösch-/purgebar, nach Löschen kein stale Batch-WS-Zustand. Die 526 erfolgreichen Tests schließen SAR-02/03/04/08 nicht aus.
- **Relevanz/Priorität:** Integrität/Kosten/Vertraulichkeit; **kein erneuter Fixauftrag**, Regressionserhalt **P1** bei Änderungen an Jobsteuerung.
- **Korrektur:** bestehenden Code nicht durch neue Resume-/Retry-Schichten duplizieren; Tests als Abnahmekriterien weiterführen.
- **Tests:** `test_checkpoint_compat.py`, `test_batch_deletion_safety.py`, `test_bulk_stop_semantics.py`, `test_bulk_run.py`, `test_bulk_state.py`, `test_bulk_immutability.py`, `test_provider_routing.py`, `test_corrector.py`, `test_model_response_handling.py`.
- **Abhängigkeiten/Komplexität:** begleitet SAR-02/03/04/08/12; **S–M** für Regressionserhalt.

### SAR-21 — CI-/Deployment-Abnahme deckt Security-Restfälle nicht ab

- **Quelle/Dateien:** A H-7, M NFR4/Integrationshinweise, D; `.github/workflows/ci.yml`, Frontend-`package.json`, Dockerfiles, `batch_manager.py` Import `fcntl`.
- **Status/Evidenz:** **teilweise behoben**. CI enthält Lint/Typecheck/Build/Backendtests und Docker-Builds; keine Security-Scan-, Browser-, Proxy-, Redis- oder Mehrprozessabnahme. Python 3.14 ist abgestimmt. Unbedingtes `fcntl` macht den Backendimport unter nativem Windows inkompatibel; Linux/macOS sind davon nicht betroffen. Kein Windows-/frischer Docker-Installationslauf durchgeführt. Alte M-Funktionslücken nicht pauschal erneut als offen einstufen; etwa `authority_bindings` wird heute gespeichert, Shared-Contract-Tests existieren.
- **Relevanz/Priorität:** fehlende Freigabeevidenz/Plattform-Reproduzierbarkeit; **P2**, Redis-/Mehrworker-Gates bereits **P1** in SAR-08/09.
- **Korrektur:** unterstützte OS-/Node-/npm-/Python-Versionen eindeutig festlegen; Windows entweder über Linuxcontainer unterstützen oder portable Locks einführen. Sicherheitsabnahme an konkrete Betriebsarchitektur binden. Historischen Milestone-Audit gezielt aktualisieren, ohne aus offenen Checkboxen Sicherheitslücken abzuleiten.
- **Tests:** frische kanonische Installation, Security-Sentinel-Tests, Browserexports, Proxyintegration und gewünschte Plattformmatrix; Docker-Smoke-Test zusätzlich zu Imagebau.
- **Abhängigkeiten/Komplexität:** SAR-01/08/09/10 und jeweilige Fixes; **M**.

## Priorisierte Implementierungsreihenfolge

1. **Freigaberahmen festlegen (SAR-01/19, P0/P1):** aktuelles Zieldeployment mit TLS/SSO, Daten-/Cloudfreigabe und direkter Backend-Unerreichbarkeit nachweisen. Bis zur gemeinsamen Jobsteuerung einen Worker als unterstützte Grenze setzen (SAR-08). Die Hinweise aus `eb879a5` sind bereits umgesetzt, ein produktives Abnahmeprotokoll fehlt.
2. **Fehlerkanäle schließen (SAR-02, P1):** gemeinsame sichere Fehlerkonvention und Sentineltests; danach alle weiteren Fehlerpfade daran ausrichten.
3. **Datenhaltungsfehler sicher behandeln (SAR-03/04, P1):** zuerst Abbruch statt stiller Fortsetzung, dann atomare Writer und koordinierte Zustandsänderungen. Bestehende Cancel-/Resume-/Audit-Garantien aus SAR-20 erhalten.
4. **Export- und Ausführungsgrenzen (SAR-05/06/13, P1):** Formelneutralisierung, Backend-Regexbudget, harte Bildgrenzen ohne unsicheren Raw-Fallback. Browser-Regexschutz als unmittelbar anschließender Teil.
5. **Ingestion und globale Ressourcen (SAR-07/11/12, P1/P2):** Body-/Disk-/Jobquoten und Cleanup; Symlinkmaßnahmen nach tatsächlicher Schreibvertrauensgrenze. Bei Mehrworkerziel zuerst SAR-08 als Architekturprojekt lösen.
6. **Installationsnachweis und Dependency-Gates (SAR-09/10, P1/P2):** Redis-Runtime vervollständigen, frische Installation und aktuelle Scans in netzfähiger CI; bestätigte Advisories separat priorisieren. Kann unabhängig bereits parallel zu Schritten 2–5 vorbereitet werden, ohne ungeprüfte Updates vorzuziehen.
7. **Browser-/Providerhärtung (SAR-14/15/16/17, P2):** Token-/Logkonzept, Egress-/Antwortgrenzen, sichere URI-Policy, Sitzungsbereinigung und Reconnectbudget.
8. **Betriebs-/CI-Abnahme abschließen (SAR-18/19/20/21):** vollständige bestehende Tests plus neue adversariale Tests, Proxy-/Redis-/Docker-Smoke-Tests und gegebenenfalls Mehrprozesssuite. Nachweise mit Commit, Runtime-/Lockstand und Datum archivieren.

**Abnahmekriterium:** keine verbleibenden P0-Freigabelücken; P1-Fixes oder ausdrücklich dokumentierte, nachgewiesene Betriebsbegrenzungen; aktueller Dependency-Scan mit überprüfbarer Advisory-Auswertung; weiterhin grüne bestehende Regressionstests. Ein bestandener Unit-Testlauf allein ist keine Produktionsfreigabe.
