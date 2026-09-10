# Changelog — KJR App (`kjr_grant`)

## 19.0.15.6.1 (2026-09-10)

- Abstand zwischen Label und Wert im Datenschutzblock.

## 19.0.15.6.0 (2026-09-10)

- **Die Angaben im Datenschutzblock kommen jetzt aus der Konfiguration.** Bisher
  standen dort feste Platzhalter „wird vom KJR ergänzt", die kein Kunde füllen
  konnte, ohne die Vorlage zu ändern, und deren Änderung jedes Modulupdate wieder
  überschrieben hätte.
- Gelesen werden sechs Systemparameter: `kjr.privacy.operator`,
  `kjr.privacy.controller`, `kjr.privacy.dpo`, `kjr.privacy.legal_basis`,
  `kjr.privacy.retention`, `kjr.privacy.authority`.
- Ist ein Parameter leer, bleibt der bisherige Warnhinweis stehen. Nichts
  verschwindet unbemerkt.

## 19.0.15.5.0 (2026-09-10)

- Beispieltexte im Zuschussantrag ersetzt. Die Platzhalter nannten mit
  „Sommerausflug Skylinepark", „86871" und „Skylinepark, Rammingen" einen fremden
  Fall. Jetzt neutral: „z. B. Sommerfreizeit der Jungschar 2026" und
  „z. B. Jugendzeltplatz", die PLZ ohne Platzhalter.
- Offenen TODO-Kommentar zum Skylinepark entfernt.

## 19.0.15.4.0 — Gedankenstriche in Antragsstrecke und Verbandsportal (M2 aus dem Fehlerbericht 30.08.2026)

### Geändert
- **31 Gedankenstriche aus den kundenseitigen Texten entfernt**, verteilt auf
  Verbandsportal (`/my/verband`), Antragsformular, Hilfeseite zum Antrag und die
  Belegliste-Vorlage. Der eingeschobene Halbsatz im Fließtext ist jeweils zu einem
  eigenen Satz oder zu einem Komma-Einschub aufgelöst, der Wortlaut bleibt sonst
  gleich. Einige dabei entstandene Kommasplices sind zu zwei Sätzen getrennt.
- Bewusst **nicht** angefasst: Paragrafenverweise (`§ 4.9 – Fahrtkosten n. BayRKG`),
  Bereichsangaben, der Strich als Leerwert in Tabellen und Auswahlfeldern
  (`— Bitte wählen —`), Überschriften, die Textbausteine der Datenschutzerklärung und
  Bezeichnungen aus den Zuschussrichtlinien des KJR. Hilfetexte im Backend bleiben
  ebenfalls unverändert.

### Dokumentiert
- **M4 Sequenz-Präfix bleibt `ANT/`.** Im Bestand des KJR stehen Anträge als
  `ZA/2026/...`. Gewachsene Kundennummerierung, kein Codefehler; Begründung als
  Kommentar in `data/ir_sequence_data.xml`.

## 19.0.15.3.0 — Mailvorlagen rendern wieder (Fehlerbericht 30.08.2026)

### Behoben
- **`{{ … }}` stand sichtbar im Mailtext.** `mail.template.body_html` wird als QWeb
  gerendert, und QWeb interpoliert `{{ }}` nur innerhalb von Attributen, nie in
  Textknoten. Im Fließtext gehört `<t t-out="…"/>`. 20 Stellen umgestellt.
  Betreff, Absender und Empfänger bleiben unverändert bei `{{ }}` — die laufen über
  die Engine `inline_template`, die `{{ }}` sehr wohl ersetzt (genau daran war der
  Fehler erkennbar: Betreff aufgelöst, Text darunter nicht).

## 19.0.10.0.0 — Restpaket: Regelversionierung, Vier-Augen-Prinzip, Hilfeseite

Umsetzung der offenen code-lösbaren Punkte aus dem Abgleich „Funktionsideen ↔ Code"
(Vault: `Projects/KJR Ideen-Code-Abgleich 2026-08.md`).

### Neu
- **Datierte Richtlinienfassungen**: `kjr.grant.type` hat `valid_from` / `valid_to` und
  `rule_group`; überlappende Zeiträume derselben Regelgruppe werden abgewiesen.
  Neue API `find_for_date(code, date_ref)` wählt die zum Maßnahmenbeginn gültige Fassung.
  Bisher überschrieb eine Richtlinienänderung Altanträge rückwirkend — in einer
  Verwendungsprüfung angreifbar. Altbestand ohne Datumsgrenzen bleibt über einen
  Fallback gültig. Der Antrag zeigt über `applicable_type_id` /
  `applicable_type_warning` an, wenn die gewählte Fassung von der gültigen abweicht.
- **Vier-Augen-Prinzip technisch erzwungen** (vorher nur dokumentiert). Prüfen,
  Bewilligen und Anweisen müssen von verschiedenen Personen kommen; abschaltbar über
  den Systemparameter `kjr_grant.enforce_four_eyes` (Default `1`) für den
  Ein-Personen-Betrieb. Die Bearbeitungsvermerke sind gegen direktes Schreiben
  geschützt — die Administrator-Gruppe darf korrigieren, jede Korrektur landet im
  Chatter. Absicherung über eine prozessinterne `ContextVar` (NICHT über den
  Odoo-Kontext, der bei `call_kw` vom Client kommt), plus Guards in `create()`,
  `default_get()` und `copy=False` auf allen Vermerken.
- **IBAN-Prüfung nach ISO 13616** (Mod-97, ohne `base_iban`) und BIC-Format nach
  ISO 9362 — im Modell und bereits im Website-Formular, mit feldgenauer Fehlermeldung.
- **Hilfeseite** `/service/zuschuss-hilfe`: wer ist antragsberechtigt, welche Förderart
  passt, welche Unterlagen, Fristen, Schritt für Schritt, häufige Fehler. Förderarten
  und Pflichtunterlagen werden dynamisch aus den Stammdaten gelesen.
- **Belegliste-Vorlage** `/service/zuschuss/belegliste-vorlage` zum Ausdrucken,
  spaltengleich zur digitalen Belegliste (ANBest-P Nr. 6.4).
- **Teilnahmeliste als Unterschriftenliste** (QWeb-PDF, A4 quer) mit Kennziffern-Legende
  und Leerzeilen zum handschriftlichen Ergänzen. Auf die Sachbearbeiter-Gruppe
  beschränkt — die Liste enthält Klarnamen und Wohnorte auch Minderjähriger.

### Geändert
- **§ 4.4 Jugendleiterschulung**: Höchstbetrag von 75 € auf **50 €**. Beleg:
  Terminmitschnitt vom 30.07.2026, 00:16:19 — Bora Berlinger wörtlich: „bei
  Jugendleiterschulung, da ist der Maximalbetrag zum Beispiel 50 und nicht 75."
  Auch `jl_max_with_juleica` und der Beschreibungstext wurden angeglichen, sonst
  hätte die globale Deckelung eine im Portal zugesagte Leistung stillschweigend
  gekappt. **Auslegung — bitte von Bora bestätigen**, beide Varianten stehen als
  TODO im Code.
- **Förderart „Investitionszuschuss (Landkreis)"** deaktiviert (Entscheidung
  30.07.2026).
- Beide Stammdatenkorrekturen wirken über `migrations/19.0.10.0.0/post-migration.py`
  auch auf bestehende Datenbanken — `noupdate="1"` allein erreicht sie nicht. Das
  Skript ist idempotent und überschreibt keine manuell gepflegten Werte.
- Wording durchgängig **„Jugendleiter" → „Gruppenleitung"** (Labels, Meldungen,
  Bescheid, Portal). Ausgenommen: Förderart-Name „§ 4.4 Jugendleiterschulung" und
  „Juleica".
- `contact_email` und `contact_person` sind im Website-Formular jetzt Pflicht und
  werden serverseitig geprüft (bisher nur Client-seitig bzw. gar nicht).
- Belegliste-Pflicht im Formular hängt jetzt an `requires_receipt` der Förderart —
  für § 4.4 war das Formular vorher unabsendbar.
- Förderart-Auswahl und Hilfeseite filtern nach Gültigkeit, sonst erschiene ab der
  ersten zweiten Fassung dieselbe Förderart doppelt.
- Jahreslimit auf der Hilfeseite nennt die geteilte Limitgruppe (§ 4.1a und § 4.1b
  teilen sich die vier Anträge — vorher stand dort irreführend „4 je Förderart").

### Behoben
- Fehlerhafte IBAN im Website-Formular lief in einen generischen `except` und der
  Antragsteller sah nur „Bitte versuchen Sie es erneut". Zusätzlich fehlte ein
  `cr.rollback()` — ein halb angelegter Antrag mit verbrauchter Sequenznummer blieb
  in der Datenbank stehen.
- `action_reset_draft` ließ die Bearbeitungsvermerke stehen; nach Zurücksetzen und
  erneuter Bewilligung galt die alte Zahlungsanweisung weiter.

## 19.0.9.0.0 — Zuschussantrag: Feldbezeichnungen & digitale Belegliste (Bora-Abstimmung 30.07.2026)

Ergebnis des Kundentermins mit Barbora „Bora" Berlinger (Kassenleitung KJR Oberallgäu)
am 30.07.2026 zu den Feldbezeichnungen im öffentlichen Zuschuss-Antragsformular
(`/service/antrag-stellen`). Alle Wortlaute sind mit ihr abgestimmt.

### Neu
- **Digitale Belegliste** als neues Modell `kjr.grant.receipt` (Datum, Beleg-Nr.,
  Empfänger/Einzahler, Bezeichnung, Art, Position, Betrag, Bemerkung), verknüpft über
  `receipt_ids` am Antrag. Die Positionen spiegeln 1:1 die Kostenaufstellung des Antrags;
  Prüfungen stellen sicher, dass der Betrag > 0 ist und Position und Art (Einnahme/Ausgabe)
  zusammenpassen. Kennzahlen am Antrag: `receipt_count`, `receipt_income_total`,
  `receipt_expense_total`.
- Neuer Formularblock **„Belegliste"** zwischen Kostenaufstellung und Dokumenten mit der
  Checkbox `use_digital_receipts` („Belegliste hier digital ausfüllen"). Entweder-oder,
  vom System geprüft: ist sie aktiv, entfällt der Datei-Upload „Belegliste"; ist sie inaktiv,
  bleibt der Upload sichtbar und Pflicht. Hinweistext: „Diese Belege sind vom Antragsteller
  zum Zwecke der Nachprüfung 5 Jahre im Original aufzubewahren."
- **Vier Bestätigungs-Checkboxen** statt einer, alle Pflicht zum Absenden: Datenschutz­hinweise
  (`confirm_privacy`, mit Link auf `/datenschutz`), Zuschussrichtlinien (`confirm_guidelines`),
  Vollständigkeit/Wahrheit inkl. Rückzahlungshinweis (`confirm_truthful`) sowie die bestehende
  Einwilligung der Erziehungsberechtigten (`participant_consent`, Wortlaut unverändert).
- **PLZ des Maßnahmenorts** als eigenes Feld `measure_zip` — getrennt vom Ort, für Boras Statistik.
- Teilnahmeliste: **Geschlecht** (`gender`) und **Kennziffer** (`role_code`: EA/HA/HO/PR/SO
  laut Papier-Teilnahmeliste) je Teilnehmer/in. Die Kennziffer setzt `is_leader` automatisch
  (weiterhin manuell überschreibbar).
- Neues Dokumentenfeld **„Neugründungsformular"** (`foundation_file`) — nur sichtbar und
  pflichtig bei der Förderart Gruppenstarthilfe (Code `4_7`), per JS umgeschaltet.

### Geändert
- **Alter statt Geburtsdatum:** `age` ist jetzt gespeichert und manuell eingebbar
  (`store=True, readonly=False`); aus `birthdate` wird nur noch gerechnet, wenn ein
  Geburtsdatum vorliegt — ein eingetippter Wert wird nicht mehr überschrieben.
  `birthdate` bleibt im Backend erhalten, entfällt aber im Website-Formular.
- **Teilnehmerliste → „Teilnahmeliste"** (durchgängig, umgeht das Gendern). Neuer Hinweistext:
  „Laut Zuschussrichtlinien ist die Teilnahmeliste bei Maßnahmen mit Teilnehmenden Pflicht.
  Bitte alle Teilnehmer/innen eintragen." Spalten neu: Nr. | Name, Vorname * | Alter * |
  Geschlecht | PLZ | Wohnort | Kennziffer | Juleica, dazu eine Legende zu den Kennziffern.
  Die Checkbox „Leitung" entfällt zugunsten der Kennziffer.
- Labels präzisiert: „Beginn Datum *" → **„Beginn der Maßnahme Datum *"**, „Ende Datum *" →
  **„Ende der Maßnahme Datum *"**; „TN aus anderen Regionen (max. 25 %)" → **„davon Teilnehmer
  aus anderen Regionen"** (Zusatz „(max. 25 %)" als Hinweis, bleibt optional);
  „8. Kurzbericht (optional)" → **„Zusatzinformationen"** mit dem Feld **„Ihre Nachricht an uns
  (optional)"** (der eigentliche Bericht ist ein Pflichtdokument — „Kurzbericht" war irreführend).
- Ort der Maßnahme jetzt zwei Felder: **„PLZ *"** + **„Ort der Maßnahme *"**
  (Beispiele „86871" / „Skylinepark, Rammingen").
- Beispiel Maßnahmenbezeichnung auf **„z. B. Sommerausflug Skylinepark"** geändert — aus dem
  Namen muss das Ziel hervorgehen.
- „Anzahl der Teilnehmer *" mit dem Zusatzhinweis **„ohne Gruppenleitung"**;
  **„Anzahl der Gruppenleitung"** und **„Telefon"** sind jetzt Pflichtfelder,
  „Davon mit Juleica" bleibt bewusst optional.
- Dokumenten-Block: Maßnahmenbericht mit dem Hilfetext „Aus dem Bericht müssen Charakter,
  Inhalt und Ablauf der Maßnahme hervorgehen."; „Weitere Dokumente" auf **„Z. B. Juleica-Kopie"**
  gekürzt.
- Formular-Blöcke fortlaufend und konsistent durchnummeriert (Kommentar und Überschrift liefen
  auseinander).

### Behoben
- **Altersfenster-Prüfung** stützte sich auf `birthdate` und übersprang damit alle Teilnehmenden,
  die nur ein Alter haben. Sie wertet jetzt `age` aus; Gruppenleitungen bleiben wie bisher
  ausgenommen, Datensätze ohne Alter und ohne Geburtsdatum werden übersprungen.

### Hinweise
- Die neuen Pflichtfelder (`measure_start_time`, `measure_end_time`, `measure_zip`,
  `measure_location`, `tn_leader_count`, `contact_phone`) sind **nur im Website-Formular**
  Pflicht (Template + Controller-Validierung), **nicht** im Modell — die Geschäftsstelle muss
  weiterhin unvollständige Papieranträge im Backend erfassen können.
- `participant_consent` bleibt bewusst unverändert, bis die Datenschutzbeauftragte des KJR
  den Wortlaut geprüft hat.
- Offen: PLZ/Ort des Skylineparks (Platzhalterbeispiel) mit Bora gegenprüfen.

## 19.0.8.3.0

### Geändert
- **Zuschussantragsformular** (`/service/antrag-stellen`) auf die Akzentfarbe
  `#45B49F` (Teal) umgestellt: Sektions-Header, Buttons, Fokus-Rahmen und
  Auswahlfelder. Per Scope-Klasse `kjr-apply-form` nur auf das Formular begrenzt
  (übrige Website/Portal unberührt).

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
