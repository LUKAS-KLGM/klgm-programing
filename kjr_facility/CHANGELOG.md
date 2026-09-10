# Changelog — kjr_facility

## 19.0.7.1.0 — Gedankenstriche in Einrichtungsanfrage und Vertrag (M2 aus dem Fehlerbericht 30.08.2026)

### Geändert
- **11 Gedankenstriche aus den kundenseitigen Texten entfernt**: Einrichtungsübersicht,
  Buchungsanfrage (Kurbeitrag, Begleitpersonen, Befreiungen, Kostenvorschau,
  fehlender Tarif), Datenschutzhinweise der Anfrage und die Verpflegungszeile im
  Buchungsvertrag. Der eingeschobene Halbsatz im Fließtext ist jeweils zu einem
  eigenen Satz oder zu einem Komma-Einschub aufgelöst.
- Bewusst **nicht** angefasst: Überschriften der Übergabeprotokoll-Abschnitte
  („Anreise — Übergabe an die Gruppe"), Betreffzeilen der Mailvorlagen, der Strich als
  Leerwert im Protokoll und die Textbausteine der Datenschutzerklärung.

## 19.0.7.0.0 — Portalbuchungen bekommen einen Tarif (Fehlerbericht 30.08.2026)

### Behoben
- **Über das Portal erzeugte Buchungen standen mit 0,00 € in allen Beträgen**, bis in
  Vertrag und Anzahlungsanforderung. Ursache: `tariff_id` wurde bei Portalbuchungen
  bewusst nicht vorbelegt, sämtliche Betragsfelder hängen aber am Tarif
  (`_compute_amounts`). Die Tarifgruppe wird jetzt aus dem Mitgliedskennzeichen des
  Kontakts abgeleitet — Mitgliedsverband → Mitgliedstarif, sonst Standardtarif.
  Einrichtungsspezifische Tarife haben weiter Vorrang vor den übergreifenden; für
  Nicht-Mitglieder ist die Suchreihenfolge unverändert.
- **Kostenvorschau und Buchung nutzen denselben Tarif.** Vorher rechnete die Vorschau
  immer mit dem Standardtarif, ein Mitgliedsverband bekam also eine andere Zahl
  angezeigt als anschließend berechnet.

### Neu
- `res.partner.is_kjr_member` — namensgleich zu `kjr_grant` und `kjr_rental`, damit
  alle drei Module sich dieselbe Spalte teilen und kjr_facility trotzdem ohne
  kjr_grant installierbar bleibt.

### Hinweis
- Die Feinunterscheidung **Partnerorganisation/kommerziell** bleibt Sache der
  Geschäftsstelle: am Kontakt gibt es kein Merkmal, aus dem sie sich ableiten ließe.
  Wird sie im Backend gesetzt, rechnen die Beträge automatisch nach (`tariff_id`
  steht in `@api.depends`).
- **Zimmer spielen für den Betrag keine Rolle.** `_compute_amounts` rechnet
  Personen × Nächte; `room_ids` trägt nur `bed_count` für Kapazitäts- und
  Doppelbelegungsprüfung bei. Die Zimmerzuordnung bleibt eine Belegungsentscheidung
  der Geschäftsstelle.

## 19.0.3.0.0 — Buchungsregeln und Preislogik Diepolz/NiSo

### Neu
- **Buchungsvorlauf** je Einrichtung (`max_advance_months`, Default 18) — Vorstands-
  beschluss vom 21.07.2026. Hart durchgesetzt im Website-Formular, im Backend als
  Hinweis: die Geschäftsstelle muss begründete Ausnahmen erfassen können.
- **Mindestbelegung** (`min_persons`, `min_nights`, `requires_organized_group`) nach
  demselben Muster. Gezählt werden Teilnehmende **und** Betreuende — einheitlich in
  Formular, Backend-Hinweis und Hilfetext.
- **Fremdenverkehrsbeitrag** pro Person und Nacht mit Befreiungen. Begleitpersonen
  sind befreit und gehen nicht in die Bemessung ein; `visitor_tax_exempt_count`
  erfasst die *weiteren* Befreiten (Einwohner der Gemeinde, Kinder unter 7,
  Schwerbehinderte). Als durchlaufender Posten ohne Steuer angelegt —
  **TODO(Steuer)**, die Einordnung ist nicht final geklärt.
- **Endreinigung** als einmalige Position je Buchung (nicht pro Nacht — über die
  Ausstattung wäre sie falsch berechnet worden).
- **Wochentagstarif** (Mo–Fr ab einer Mindestnächtezahl) als eigene Preisregel; eine
  reine Mengenstaffel bildet das nicht ab.
- **Ansprechpartner/in** als Namensfeld (bisher gab es nur das Zahlenfeld „Betreuer").

### Behoben
- **Doppelbelegung ohne Raumauswahl** lief im Backend völlig ungeprüft durch; geprüft
  wird jetzt gegen die Kapazität der Einrichtung.
- Die **Website-Verfügbarkeitsprüfung** sperrte die gesamte Einrichtung, sobald
  irgendeine überlappende Anfrage existierte — eine einzelne 8-Personen-Anfrage
  blockierte Diepolz mit 42 Betten. Sie prüft jetzt gegen die freie Kapazität und
  nennt dem Nutzer die verbleibenden Plätze.
- Der **Buchungsvertrag** (PDF) listete Positionen, deren Summe nicht die
  ausgewiesene Gesamtsumme ergab, seit Endreinigung und Beitrag hinzukamen.

## 19.0.2.3.0

### Neu
- **301-Weiterleitungen** der alten `/kjr/…`-Pfade auf `/service/…`
  (`/kjr/einrichtungen`, `/kjr/einrichtung/<id>`), damit bereits geteilte/indexierte alte Links nicht ins Leere laufen.
  Eigene Controller-Datei `controllers/legacy_redirects.py` (nur GET-Landingpages).

## 19.0.2.2.0

### Geändert
- **Öffentlicher URL-Präfix `/kjr/…` → `/service/…`** umbenannt, damit die Seiten
  ins Webseiten-Corporate-Design/-Menü eingebunden werden können. Betroffen:
  `/service/einrichtungen`, `/service/einrichtung/<id>`, `/service/einrichtung/<id>/anfrage`.
  Portal-Routen unter `/my/…` bleiben unverändert (Odoo-Standard).
  Hinweis: Das Website-Menü ist `noupdate` – bei einem **Bestandsupgrade** muss der
  Menü-Link einmalig manuell auf `/service/…` gesetzt werden; Frischinstallationen
  übernehmen die neue URL automatisch.

## 19.0.2.0.0

Transcriptbasierte Lücken (Gruppenhaus/Tagungshaus) additiv umgesetzt.

### F1 — Reserviert vs. Gebucht getrennt (muss)
- Neuer Status `reserved` ("Reserviert (vorgemerkt)") zwischen `draft` und `confirmed`.
- `confirmed` umbenannt zu "Gebucht" (verbindliche Buchung).
- Neue Methode `action_reserve()` (draft -> reserved). `action_confirm()` nun draft/reserved -> confirmed.
- Felder `reservation_date`, `reservation_expiry`, `is_booked` (compute, store).
- Statusbar/Filter/Listen-Decoration + Kalenderfarbe (`calendar_color`, reserviert heller/neutral).
- Doppelbelegungs-Constraint wertet reservierte Buchungen weiterhin als Konflikt.

### F2 — Vertrag automatisch zuschicken (soll)
- mail.template `mail_template_booking_contract` mit `report_template_ids` (PDF-Anhang).
- Beim Übergang auf `confirmed` (gebucht) automatischer Versand + `contract_sent_date`.

### F3 — Reservierungsbestätigung + automatische Ablage (soll)
- Eigenes mail.template `mail_template_booking_reserved` ("Reservierungsbestätigung").
- Helfer `_store_document(report_xmlid, name)`: rendert PDF und legt es deterministisch
  benannt als `ir.attachment` am Datensatz ab (idempotent). Aufruf beim Reservieren/Buchen.

### F5 — Fristen-/Erinnerungs-Crons (muss)
- Felder `contract_sent_date`, `contract_signed`, `deposit_due_date`.
- `_cron_contract_followup` (Vertrag gesendet, nicht unterschrieben, > 10 Tage -> Activity + Mahn-Mail).
- `_cron_deposit_overdue` (deposit_due_date < heute & nicht bezahlt -> Activity).
- `_cron_reservation_expiry` (reservation_expiry < heute in state reserved -> Activity/Hinweis).
- `_cron_booking_reminder` auf Datums-RANGE (13–15 Tage) + Dedup (Activity-Existenz) umgestellt.

### F7 — An-/Abreisezeiten (soll)
- Felder `arrival_time` / `departure_time` (Float, widget float_time) an der Buchung.
- Stammdaten `check_in_default_time` / `check_out_default_time` an `kjr.facility` als Default.
- Anzeige in Form und Report.

### F8 — Mail-Hinweis (kann)
- Feld `mail_hint` (Html) an `kjr.facility`, Ausgabe in den Mail-Templates.

### B-cross (muss)
- `payment_status` (compute aus `invoice_id.payment_state`) in Form/Liste/Portal.
- Eigener Nummernkreis 'V' — Verkaufsjournal (code 'V') per Data; in `action_create_invoice`
  als `journal_id` gesetzt, falls vorhanden.
- Optionaler Schalter `invoice_auto_post` an `kjr.facility` (Auto-Post der Rechnung).

### Bugfixes
- (a) Website-Anfrage (`facility_request`) prüft jetzt vor `create` auf Verfügbarkeit/
  Doppelbelegung (`_find_overlapping`).
- (b) Portal-Detailseite: Download-Link für Vertrags-/Reservierungs-PDF + Route
  `/my/einrichtungsbuchungen/<id>/vertrag`.

### Zurückgestellt (reine Konfiguration)
- E-Rechnung/ZUGFeRD, Bankabgleich, Mass-Mailing-Versand — Odoo-Standardkonfiguration,
  nicht als Code umgesetzt.
