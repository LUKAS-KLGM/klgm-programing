# Changelog – kjr_event

## 19.0.2.3.0

### Hinzugefügt
- **E12 Treffpunkt/Wichtig/Webseite (Nupian-Parität)**: Drei neue Felder auf `event.event`:
  `kjr_meeting_point` (Text, "Treffpunkt"), `kjr_important_note` (Html, "Wichtig"),
  `kjr_website_url` (Char, "Webseite"). Backend: neuer Reiter „Treffpunkt & Hinweise".
  Frontend: „Wichtig" erscheint immer (kein Toggle) als Warnbox oberhalb der Beschreibung;
  „Treffpunkt" und „Webseite" ergänzen den bestehenden Ort-Block in der Seitenleiste und
  teilen sich dessen vorhandenen Toggle (`opt_event_location_block`).

## 19.0.2.2.0

### Hinzugefügt
- **E11 Dokumente-Block (Website)**: Neues Model `kjr.event.document` (Mehrfach-Dateien
  je Veranstaltung, `event.event.kjr_document_ids`). Backend: eigener Reiter „Dokumente“
  im Event-Formular (editierbare Liste, Datei-Upload). Frontend: neuer optionaler
  Sidebar-Block auf der öffentlichen Event-Seite (`website_event.event_description_full`),
  an-/abschaltbar im Website-Editor unter „Anpassen → Sidebar-Blöcke → Dokumente“ –
  analog zu den bestehenden Blöcken Ort/Organizer/Teilen. Block erscheint automatisch nur,
  wenn mindestens ein Dokument hinterlegt ist. Zugriffsrechte (public/portal: nur Lesen;
  Event-Nutzer/-Manager: volle Verwaltung) analog zu den bestehenden `website_event`-Modellen.

## 19.0.2.0.0

### Hinzugefügt
- **E1 Online-Anmeldefelder**: Frontend-Formular (`website_event.registration_attendee_details`)
  um Geburtsdatum, Erziehungsberechtigte/r (Name/Telefon), Notfallkontakt, Ernährung
  (+ Hinweis), Einwilligungs-Checkbox und Bemerkungen erweitert. Controller
  `WebsiteEventController.registration_confirm` überschrieben, um die Werte in
  `event.registration` zu schreiben.
- **E2 Altersgruppen-Prüfung**: Konfig-Schalter `event.event.kjr_enforce_age_range`;
  harte `@api.constrains('birthdate','event_id')`-Prüfung; weiche Markierung über
  bestehendes `age_out_of_range`.
- **E3 Ernährung & Bemerkungen**: Felder `dietary_requirements`, `dietary_note`, `notes`
  auf `event.registration`; eigene Backend-Listenansicht + Such-/Gruppierungsfilter
  + Menü „KJR-Teilnehmer/innen“.
- **E4 Kooperationspartner-Zugriff**: Felder `cooperation_partner_id`,
  `cooperation_user_ids` auf `event.event`; Gruppe „KJR Kooperationspartner“
  (erbt `base.group_portal`); `ir.rule` (read-only) auf `event.event` und
  `event.registration`; Portal-Controller `/my/kjr-events` und
  `/my/kjr-events/<id>/teilnehmer` mit Templates.
- **E5/E6 Zahlung**: `event.event.payment_required`; auf `event.registration`
  `kjr_payment_state` (computed/manuell), `amount_due`, `amount_paid`, `payment_date`,
  `kjr_currency_id`. Ableitung aus `sale_order_id`/Rechnungen wenn vorhanden.
- **E7 Mail-Vorlagen**: Anmeldebestätigung, Einwilligungs-Erinnerung, Packliste, Absage,
  Bescheinigung (mit PDF-Anhang); Serverm-Action „Bescheinigung senden“.
- **E9 Schulungsanmeldung → Rechnung**: `event.event.training_product_id` +
  `action_create_training_invoice` (modulseitiges Mapping ohne event_sale-Verkaufslogik).
- **E10 Juleica/Nachweisversand**: `action_send_certificate` mailt das bestehende
  PDF (`kjr_event.participation_certificate_template`); Juleica-`juleica_valid_until`
  Default = Ausstellung + 3 Jahre.

### Bugfixes
- `consent_missing`/`age_out_of_range` jetzt gespeichert + such-/filterbar.
- `has_birthdate`-Flag entschärft die Fehlinterpretation von `kjr_age == 0`.
- Juleica-Gültigkeit erhält einen sinnvollen Default.

### Abhängigkeiten
- Neu: `event_sale`, `website_event_sale`, `account` (Odoo-Community-Core).
