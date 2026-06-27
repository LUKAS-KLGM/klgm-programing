# Changelog — KJR App (`kjr_grant`)

## 19.0.8.2.0

### Neu
- **301-Weiterleitungen** der alten `/kjr/…`-Pfade auf `/service/…`
  (`/kjr/zuschuss`, `/kjr/antrag-stellen`, `/kjr/antrag-bestaetigung`), damit bereits geteilte/indexierte alte Links nicht ins Leere laufen.
  Eigene Controller-Datei `controllers/legacy_redirects.py` (nur GET-Landingpages).

## 19.0.8.1.0

### Geändert
- **Öffentlicher URL-Präfix `/kjr/…` → `/service/…`** umbenannt, damit die Seiten
  ins Webseiten-Corporate-Design/-Menü eingebunden werden können. Betroffen:
  `/service/zuschuss`, `/service/antrag-stellen`, `/service/antrag-bestaetigung`, `/service/antrag/<id>/upload`.
  Portal-Routen unter `/my/…` bleiben unverändert (Odoo-Standard).
  Hinweis: Das Website-Menü ist `noupdate` – bei einem **Bestandsupgrade** muss der
  Menü-Link einmalig manuell auf `/service/…` gesetzt werden; Frischinstallationen
  übernehmen die neue URL automatisch.

## 19.0.6.0.0 (2026-06-19) — Richtlinien-Feinabgleich, § 4.9 BayRKG & Härtung

Vollständiger Abgleich der Zuschussverwaltung gegen den verifizierten Wortlaut der
KJR-OA-Zuschussrichtlinie (Fassung gültig ab 01.12.2022, als „2026" republiziert) und
die einschlägigen BJR-Regeln. Statisch geprüft (py_compile, xmllint, Feld-/Methoden-
Referenzcheck), Berechnungslogik numerisch gegen Richtlinien-Beispiele getestet, in einem
3-fachen adversarialen Review (Odoo-19-Laufzeit / Richtlinien / Vollständigkeit) gehärtet.

### Richtlinien-Korrektheit (Berechnung)
- **§ 4.9 Delegiertenförderung** korrekt als **Fahrtkostenerstattung nach BayRKG** umgesetzt
  (statt Platzhalter): PKW = Wegstreckenentschädigung je km (Hin- und Rückfahrt) + Mitnahme-
  entschädigung je Mitfahrer; ÖPNV/Sonstiges = belegte Fahrtkosten. Sätze über System-Parameter
  (`kjr_grant.bayrkg_rate_per_km` 0,35 €, `…_passenger_rate_per_km` 0,03 €). Kein eigener
  Höchstbetrag (max_amount 0), Auszahlung auf Delegiertenkonto erlaubt, Verknüpfung zur
  Vollversammlung (`assembly_id`) — bei Einreichung Pflicht; Hinweis, wenn der Verband dort
  nicht erfasst ist.
- **Juleica-Zuschlag (+50 %)** gilt jetzt einheitlich für **alle Tagessatz-Förderarten**
  (§ 4.1b/4.2/4.3/4.5) über den gemeinsamen Helfer `_day_rate_grant` (zuvor nur § 4.1b).
- **§ 4.7 (Pauschale)** und **§ 4.9 (BayRKG)** sind jetzt korrekt von Kofinanzierungs- **und**
  Fehlbetragsdeckel ausgenommen (§ 4.7 wurde zuvor fälschlich auf das Defizit gedeckelt).
- **Tageszählung** berücksichtigt die An-/Abreiseregel (nach 10:00 begonnen / vor 17:00 beendet
  → An- und Abreisetag zählen als ein Tag) über die vorhandenen Uhrzeit-Felder.
- **Auszahlungsstichtag 15.11.** (knüpft an den Antragseingang) als `payout_year`/
  `payout_schedule_info` ergänzt (Stichtag konfigurierbar).
- **Rückforderungszins** auf **Basiszinssatz + 3 Prozentpunkte** (bayer. ANBest-P Nr. 8.4 /
  Art. 49a Abs. 3 BayVwVfG) korrigiert (zuvor +5 PP); Zuschlag konfigurierbar.
- **Altersfenster** 5–27 in den Stammdaten gesetzt; Jugendleiter von der Altersprüfung
  ausgenommen (keine Altersgrenze lt. Richtlinie).
- **Kombiniertes Jahreslimit** § 4.1a + § 4.1b (max. 4 Freizeitmaßnahmen/Jahr gemeinsam) über
  `year_limit_group`.
- **§ 4.8a** verlangt jetzt korrekt **mehr als** 100 TN (min. 101); § 4.4 `juleica_bonus`
  deaktiviert (dort wirkungslos, eigene 50/75 %-Logik).
- **Verwendungsnachweis-Neuberechnung** nutzt jetzt die **echte förderartspezifische Logik**
  auf Ist-Werten (In-Memory-Antrag) statt linearer Skalierung; gedeckelt auf den bewilligten Betrag.

### Korrektheit & Bugfixes
- Portal-Datei-Upload nahm `tn_list_file`/`other_file_2` nicht entgegen → ergänzt.
- `payment_ordered`-Workflow: Button **„Zur Zahlung anweisen"** (setzt Vermerk + Benutzer + Datum).
- **Abrechnung** und **Fördermittel-Akquise** haben jetzt vollständige Workflow-Buttons
  (Eingang/Prüfung/Abschluss; setzt Eingangsdatum).
- **Juleica**: Portal-/Antragsteller-Lesezugriff auf die **eigene** Karte (ACL + Record Rule);
  Sachbearbeiter sehen alle (DSGVO-Mandantentrennung). No-Op in `_compute_expiry` bereinigt.
- **Mail-Templates** fallen auf die Verbands-E-Mail zurück (kein stiller Fehlversand mehr).
- **Vollversammlungs-Quorum** auf die **stimmberechtigten Mitglieder** gestützt (§ 33 BJR-Satzung)
  inkl. quorumsunabhängiger Wiederholungssitzung (§ 33 Abs. 3).
- Vollständige `@api.depends` für die §-4.9- und Settlement-Neuberechnung (keine veralteten Werte).

### Neue Funktionen
- Nicht-blockierende **Budget-Warnung** bei Bewilligung über dem Jahresbudget + Live-Anzeige
  „verbleibendes Budget" am Antrag (Finanzlage-/Ermessensvorbehalt der Richtlinie).
- Förderfähigkeits-Hinweise um **Subsidiarität** (anderweitige Zuschüsse ausschöpfen) und die
  **Ausschlussliste** nicht förderfähiger Kosten (Alkohol/Tabak, Personalkosten Hauptamtliche,
  berufsqualifizierende Fortbildungen, touristische Unternehmen) erweitert.
- **Fristen-Erinnerungs-Cron** für Fördermittel-Antrags- und Verwendungsnachweis-Fristen.
- System-Parameter-Defaults als Seed-Daten (`data/ir_config_parameter_data.xml`).

### Hinweise
- § 4.9 wird über das Backend erfasst (Antragsliste der Vollversammlung); das öffentliche
  Portal-Antragsformular bildet weiterhin die maßnahmenbasierten Förderarten ab.
- Basiszinssatz (`kjr_grant.base_interest_rate`) ist halbjährlich zu pflegen; BayRKG-Sätze und
  Auszahlungsstichtag sind über System-Parameter konfigurierbar (Vertrieb an weitere Ringe).
- Weiterhin offen: Laufzeit-/Abnahmetest auf einer Odoo-19-Staging-Instanz (lokal nicht möglich).

## 19.0.3.0.0 (2026-06-02) — Review, Härtung & Förderfest-Ausbau

### Behoben (kritisch/hoch)
- **`action_approve` brach komplett ab (Rollback):** `pdf_content, _ = _render_qweb_pdf(...)` überschrieb die gettext-Funktion `_` → `TypeError`. Jetzt `_report_type`.
- **Korrupte Bescheid-/Antrags-PDFs:** `ir.attachment.datas` erhielt rohe Bytes statt Base64 → `base64.b64encode(...)` (2 Stellen).
- **Mail-Templates versandten nie:** Modell hatte kein `company_id` (von Templates referenziert) → Feld ergänzt.
- **Jahresbericht-PDF crashte:** `o.env.cr.now()` existiert nicht → `context_timestamp(datetime.datetime.now())`.
- **Rückforderung falsch:** skalierte `grant_calculated` statt `grant_approved`; `@api.depends` vervollständigt.
- **Budget-Kennzahlen stale:** `store=True` ohne gültige Dependencies → auf non-stored (live) umgestellt.

### Security & DSGVO
- `base.group_public`-Schreibrecht auf `kjr.grant.participant` entfernt.
- Record Rules für `kjr.grant.participant` (Mandantentrennung der Teilnehmerdaten).
- IDOR auf Bestätigungsseite geschlossen; Antrag nur für eigene Verbände (Sachbearbeiter alle).
- Einwilligung Erziehungsberechtigter (`participant_consent`) + Anonymisierungs-Cron (`participant_retention_years`, Default 5 J.).

### Korrektheit / Datenintegrität
- `@api.constrains`: Datum (Ende ≥ Beginn), TN-Zahlen, keine negativen Beträge, `leader_ratio ≥ 1`.
- `<chatter/>` statt `oe_chatter` (5 Forms); `portal.pager` statt `web.pager`; Portal-Searchbar verdrahtet; `measure_end` Pflichtfeld.

### Neue Funktionen
- **Förderregeln konfigurierbar** (`kjr.grant.type`): Juleica-Zuschlag, Betreuungsschlüssel, Herkunftsquote, Alter, Dauer — statt hartcodiert (verifiziert gegen KJR-OA-Zuschussrichtlinie).
- **Förderfähigkeits-Hinweise** beim Einreichen.
- **Verwendungsnachweis-PDF** (Soll/Ist) + **„Abrechnung erstellen"** aus dem Antrag.
- **Vollversammlung**: Quorum + automatisches Beschlussergebnis.

### Aufräumen
- Ungenutzte Enterprise-Deps entfernt (`event`, `website_event`, `mass_mailing`, `sale_renting`, `website_sale_renting`) — kommen als eigene Folge-Module. `kjr_grant_type`-Stammdaten `noupdate="1"`.

### Hinweis
Steuer/USt/E-Rechnung betreffen die geplanten Einrichtungs-/Verleih-Module, nicht die Zuschussverwaltung (Zuschüsse = kein steuerbarer Umsatz). GoBD-Festschreibung über Odoo-Core (`l10n_de`) aktivieren.
Getestet: statisch (`py_compile`, `xmllint`, Referenz-Checks) + 2 adversariale Review-Durchgänge. Vor Produktivnahme auf Staging installieren und Workflows manuell testen.
