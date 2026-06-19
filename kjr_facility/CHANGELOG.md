# Changelog — kjr_facility

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
