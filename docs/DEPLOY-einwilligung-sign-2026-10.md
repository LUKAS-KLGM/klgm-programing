# Deploy-Notizen: Einwilligung per Odoo Sign, Spam-Schutz, Befund A/B/C

Stand 2026-10-12, Repo `klgm-programing`, Branch `feat/esign-einwilligung-2026-10`
(nichts committet, nichts gepusht).

| Modul | Version | Art |
|---|---|---|
| `kjr_event` | 19.0.5.8.1 -> 19.0.5.9.0 | Update, Migration `migrations/19.0.5.9.0/post-migration.py` |
| `kjr_event_shop` | 19.0.2.0.0 -> 19.0.2.1.0 | Update (keine Migration nötig) |
| `kjr_rental` | 19.0.5.5.1 -> 19.0.5.6.0 | Update (keine Migration nötig) |
| `kjr_website_antispam` | neu 19.0.1.0.0 | Installation (`auto_install` False) |
| `kjr_event_sign` | neu 19.0.1.0.0 | Installation (`auto_install` True, greift aber beim Update nicht) |
| `kjr_grant` | 19.0.15.7.0 -> 19.0.16.0.0 | Update, Migration `migrations/19.0.16.0.0/post-migration.py` (Registrierung Verein/Privatperson, Abschnitt 7) |

Statisch geprüft (lokal, ohne Odoo/Postgres): `py_compile` 138 Dateien OK,
`xmllint --noout` 78 Dateien OK, JS-Syntax der zwei Interactions OK (JavaScriptCore,
node fehlt lokal), `tools/icons/build_icons.py --check` 8/8 passt,
`tools/einwilligung/build_einwilligung_pdf.py` erzeugt PDF und
`sign_template_data.xml` byte-identisch (`--check` passt).

---

## 1. Upgrade-Reihenfolge (NUR Server-Kopie/Staging, nie direkt Produktion)

0. Snapshot bei CloudPepper (Datenbank + Filestore). Branch auf die Kopie bringen.
1. Update der bestehenden Module:
   ```
   odoo -d <db> -u kjr_event,kjr_event_shop,kjr_rental --stop-after-init
   ```
   (`kjr_event_shop` nur, wenn installiert; sonst prüfen, warum nicht:
   es hängt an `website_event_sale`, `payment_custom`, `l10n_din5008_sale`.
   Ohne `kjr_event_shop`, aber MIT `website_event_sale`, ist die Reihenfolge der
   Anmelde-Controller nicht deterministisch.)
   Im Log erwarten: Migration 19.0.5.9.0 ergänzt den Link-Block in
   `kjr_event.mail_template_consent_reminder` je Sprache, ODER Warnung
   „Vorlage <id> individuell angepasst, Link-Block manuell ergänzen".
2. Spam-Schutz installieren und SOFORT auf Protokollieren stellen:
   ```
   odoo -d <db> -i kjr_website_antispam --stop-after-init
   ```
   Danach Systemparameter `kjr_website_antispam.mode` = `log`.
   Die Parameter-Schlüssel NICHT vorher von Hand anlegen (Duplikatfehler).
3. Sign-Brücke installieren (nur wenn das Enterprise-Modul `sign` installiert ist):
   ```
   odoo -d <db> -i kjr_event_sign --stop-after-init
   ```
   Im Log: „Standardvorlage <id> ist gültig" und „Absender mit E-Mail-Adresse
   vorhanden/FEHLT". Die Brücke bleibt AUS, bis sie eingeschaltet wird.
4. Neustart des Odoo-Dienstes (neue Assets: `kjr_consent_fields.js`,
   `kjr_antispam.js`, `kjr_antispam.scss`), Browser-Cache leeren.
5. Tests:
   ```
   odoo -d <testdb> --test-tags /kjr_event,/kjr_event_shop,/kjr_event_sign,/kjr_website_antispam --stop-after-init
   ```

## 2. Einstellungen im Backend

### 2.1 Sign-Vorlage prüfen (vor dem Einschalten)
- Sign > Vorlagen > „Einwilligung Erziehungsberechtigte (Standard)" öffnen.
- Prüfen: genau eine Rolle „Erziehungsberechtigte/r"; Felder Name des Kindes,
  Veranstaltung, Einwilligung (Checkbox), Name, Ort, Datum, Unterschrift liegen
  passend auf dem PDF; kein Firmenname, keine Gesundheitsfragen.
- Text des PDF mit Geschäftsstelle/Datenschutz abstimmen (TODO(KJR)). Änderungen
  NIE an der ausgelieferten Vorlage: neue Vorlage anlegen (bzw. neue XML-ID `_v2`
  über das Skript) und in den Einstellungen als Standardvorlage wählen.
- In den Einstellungen erscheint eine Warnung, falls die gewählte Vorlage die
  Prüfung nicht besteht (aktiv, Dokument, genau eine Rolle, Unterschriftsfeld).

### 2.2 Einstellungen > „KJR Einwilligung" (nur Administratoren)
- **Absender**: interner Benutzer mit E-Mail-Adresse (Absender der Sign-Mail).
  Leer = verantwortliche Person der Veranstaltung, sonst Administrator.
- **Standardvorlage**: leer = mitgelieferte Vorlage.
- **Fristen**: Gültigkeit 14 Tage, Erinnerung alle 3 Tage (0 = keine Sign-
  Erinnerung). Beides TODO(KJR) Kundenentscheidung.
- **„Einwilligung digital einholen"** erst nach erfolgreichem Testplan
  einschalten (Systemparameter `kjr_event_sign.enabled`). Ab dann laufen alle
  Veranstaltungen mit „Einwilligung Erziehungsberechtigter erforderlich" im
  Verfahren „Digitale Unterschrift" (je Veranstaltung optional eigene Vorlage
  im Feld „Einwilligungsvorlage (Sign)").
- Rückweg/Notbremse: Schalter aus. Neue Anmeldungen laufen dann wieder mit
  Häkchen im Formular; bestehende Sperren bleiben, Freigabe per „Einwilligung
  liegt vor (Papier)".
- Benutzer der Geschäftsstelle, die Unterschriftsanfragen öffnen sollen,
  brauchen Sign-Rechte (`sign.group_sign_user`).

### 2.3 Spam-Schutz (Systemparameter `kjr_website_antispam.*`)
- `mode`: nach Installation `log`; Protokoll einige Tage beobachten
  (`Spam-Schutz: Aktion ... abgewiesen (<grund>), Modus log`), besonders
  `too_fast` und `token_missing`; dann `enforce`. Notbremse: `off` (wirkt sofort).
- `min_seconds` 2, `min_seconds_exempt` `website_event_registration`,
  `max_age_hours` 24, `actions` `website_form,website_event_registration,kjr_*`.
- Login, Registrierung, Passwort-Zurücksetzen NIE in `actions` eintragen.

### 2.4 Optional: Cloudflare Turnstile
- Modul `website_cf_turnstile` installieren; Einstellungen > Website:
  `cf.turnstile_site_key` und `cf.turnstile_secret_key`.
- WARNUNG: Mit gesetztem Secret scheitert jede geprüfte Aktion ohne Widget;
  eigene Formulare brauchen `data-captcha` + `button[type=submit]`
  (Spielmobil hat `data-captcha="kjr_spielmobil"`). Vorher Spielmobil-Seite,
  Builder-Formulare und Veranstaltungsanmeldung testen.
- Rollback: Secret leeren.
- Datenschutz: Turnstile/reCAPTCHA = Drittlandtransfer, Datenschutzerklärung
  anpassen (Honeypot/Zeittoken nicht nötig). reCAPTCHA-Keys nicht setzen, ohne
  die Spielmobil-Seite zu testen.

### 2.5 Sonstiges
- KJR-Vorlaufserinnerung zur Einwilligung (Cron, Default AUS) enthält jetzt den
  Signierlink-Block. Versand nur über Aktion „Einwilligungs-Erinnerung senden"
  oder Cron (sudo-Rendering, Empfänger nur Erziehungsberechtigte), nicht über
  den Chatter-Composer.
- AVV/TOM-Anlage um Odoo Sign ergänzen; Löschkonzept: Eltern-Kontakte
  (Kategorie „KJR Erziehungsberechtigte"), Aufbewahrungsfrist signierter
  Einwilligungen (TODO(KJR)).

## 3. Befund A: Skriptaufruf (nur berechtigte Person, nach Snapshot)

Anleitung: `tools/website_fixes/README.md`.
```
# 1. Dry-Run (schreibt nichts, Rollback)
odoo shell -d <db> --no-http < tools/website_fixes/fix_textarea_br.py
# 2. Ausgabe prüfen (Ansichts-IDs, keys, URLs, Sprachen, Textarea-Namen)
# 3. Schreiben
KJR_FIX_WRITE=1 odoo shell -d <db> --no-http < tools/website_fixes/fix_textarea_br.py
#    erwartet: "noch betroffen: keine"
# 4. Sonderfall HTML-Feld (event.event.description), nur lesend, nur IDs
KJR_FIX_SCAN_HTML=1 odoo shell -d <db> --no-http < tools/website_fixes/fix_textarea_br.py
```
Danach je betroffener Seite und Sprache Quelltext prüfen (keine `<br`/`&lt;br`
zwischen `<textarea>` und `</textarea>`), Testformular im privaten Fenster absenden.
Zusätzliche Startparameter (`-c <konfig>`, addons-path) wie beim Serverstart.

## 4. Testplan Server-Kopie

### 4.1 Funktionstests (Spezifikation 5, Rollout Schritt 5)
Voraussetzung: Brücke eingeschaltet, Absender gesetzt, Testveranstaltung mit
„Einwilligung Erziehungsberechtigter erforderlich", echte Test-Postfächer.

1. **Kostenlos, minderjährig (Online)**: Geburtsdatum < 18 am Beginntag,
   Eltern-E-Mail angeben. Erwartet: Erfolgsseite „Anmeldung vorgemerkt",
   maskierte Adresse, kein Ticket-Download; Anmeldung draft + „Einwilligung
   ausstehend", keine Kern-Mail, keine Rechnung, kein Platz belegt;
   Sign-Mail (deutsch) an die Eltern; Referenz/Betreff ohne Kindsnamen.
   Unterschreiben -> Anmeldung „Registriert", Kern-Mail genau einmal,
   Quelle „Digitale Unterschrift", KEIN PDF-Anhang an der Anmeldung (liegt an
   der Anfrage).
2. **Volljährig**: sofort freigegeben (Notiz „volljährig"), keine Sign-Anfrage.
3. **Ohne Geburtsdatum / ohne Eltern-E-Mail und ohne Anmelde-E-Mail**:
   Fehlermeldungen `kjr_birthdate_missing` bzw. `kjr_guardian_email_missing`,
   nichts angelegt, kein Warenkorb.
4. **Bezahlt mit Überweisung (Shop)**: Warenkorb -> Notiz „Unterschriftsanfrage
   folgt nach Abschluss der Bestellung", noch keine Mail. Checkout abschließen:
   Auftrag `sent`? -> Sign-Mail. Unterschrift vor Zahlung: Anmeldung bleibt
   unbestätigt (to_pay). Zahlung/Auftragsbestätigung -> Registriert.
   Bestellbestätigung zeigt den Einwilligungshinweis.
   Abgebrochener Warenkorb: keine Anfrage, kein Eltern-Kontakt.
5. **Kostenloses Ticket über Shop (0 Euro)**: `action_confirm` im Controller,
   Anmeldung bleibt gesperrt, Sign-Mail direkt.
6. **Papier**: „Einwilligung liegt vor (Papier)" -> freigegeben, offene
   Sign-Anfrage storniert (genau eine Notiz).
7. **Ablehnung**: Eltern lehnen ab -> „Unterschrift abgelehnt" (eine Notiz,
   ohne Begründung), Aktivität, Sperre bleibt.
8. **Volle Veranstaltung**: Unterschrift bei vollem Event -> Warteliste (ohne
   Auftrag, Warteliste aktiv) bzw. Sperre + Aktivität „kein Platz frei";
   „Freigabe erneut prüfen" nach freiem Platz.
9. **Storno/Archiv** der gesperrten Anmeldung -> offene Anfrage storniert.
10. **„Erneut senden"**, **E-Mail-Korrektur** der Eltern-Adresse -> alte Anfrage
    storniert, neue an neue Adresse.
11. **Spam-Schutz (Modus log)**: Builder-Formular, Veranstaltungsanmeldung,
    Spielmobil absenden -> keine Abweisung, Log ohne Treffer. `kjr_hp` per
    Entwicklerwerkzeug füllen -> Log `honeypot`. Kurz `enforce`: Veranstaltung
    mit Ticket im Warenkorb + Honeypot -> Weiterleitung
    `registration_error_code=recaptcha_failed`, KEIN Checkout, KEINE
    Bestätigung des Warenkorbs (neu: Vorabprüfung in kjr_event). Danach zurück
    auf `log`.
12. **Spielmobil**: abgewiesene Anfrage zeigt Formular mit Eingaben und
    Meldung oberhalb des Formulars.
13. **Brücke aus**: Schalter aus -> Formular zeigt wieder das Häkchen, keine
    Sperre bei neuen Anmeldungen.

### 4.2 Prüfpunkte Abschnitt 6 der Spezifikation
1. Basis von `_compute_registration_status` / `_has_order` / `sale_status`
   vorhanden (vermutlich `event_product`, lokal nicht im Klon): Update ohne
   AttributeError, Test 4/5 laufen.
2. Kennt die Enterprise-Variante von `event` ein `auto_confirm`? Falls ja:
   gesperrte Anmeldungen bleiben trotzdem draft (Sicherheitsnetz in create()).
3. Setzt der Checkout mit Überweisung den Auftrag auf `sent` (Auslöser der
   zurückgestellten Sign-Anfrage, E11)? Sonst kommt die Anfrage erst bei
   `sale`.
4. `reference_doc =like` suchbar? (Cron c nutzt direktes SQL; prüfen, dass der
   Cron „KJR Einwilligung: Unterschriftsanfragen nachhalten" ohne Fehler läuft und verwaiste Anfragen
   storniert.)
5. Rendern der Einwilligungs-Erinnerung unter sudo für Benutzer ohne
   Betreuungsgruppe ohne AccessError.
6. Interaction `kjr_event.consent_fields` startet im Anmeldedialog (Pflicht-
   markierung Häkchen/Eltern-E-Mail beim Geburtsdatum; nur Komfort).
7. Sign-Mail und Signierseite mit `partner.lang = de_DE` deutsch.
8. `_kjr_purge_registration_copies` (Anonymisierung) entfernt Sign-Anhänge an
   der Anmeldung, archiviert unterschriebene Anfragen und löscht seit
   `kjr_event_sign` 19.0.1.1.0 alle nie unterschriebenen (siehe 8).

## 5. Bei der Integrationsprüfung geändert

- `kjr_event/controllers/website_event.py`: neue Methode
  `_kjr_antispam_rejects()`; `registration_confirm` ruft
  `ir.http._kjr_antispam_precheck('website_event_registration')` (nur falls
  `kjr_website_antispam` installiert, per `hasattr`, keine neue Abhängigkeit)
  VOR der Einwilligungs-Vorprüfung und VOR super() auf. Grund: Weist der Hook
  erst im Kern ab, verwirft `website_event_sale` die Fehler-Weiterleitung bei
  gefülltem Warenkorb und leitet in den Checkout bzw. bestätigt einen
  kostenlosen Warenkorb. Bei Grund: reguläre Prüfung einmal (Log, Parameter
  entfernen), dann Weiterleitung `recaptcha_failed`.
- Tests dazu in `kjr_event/tests/test_event_website_registration.py`.
- CHANGELOG `kjr_event` und `kjr_website_antispam`, README des Spam-Schutzes
  („Grenzen", Rollout-Test) angepasst.
- Root-README: Modultabelle um `kjr_event_shop`, `kjr_facility_grant`,
  `kjr_kommja` ergänzt, Beschreibung `kjr_event`.

## 6. Commit-Vorschläge (NICHT ausgeführt)

Repo-Stil: `<modul>: <Zusammenfassung> (<version>)`, ohne Umlaute.

```
git add kjr_event
git commit -m "kjr_event: Einwilligungs-Sperre bis zur Einwilligung der Erziehungsberechtigten, Eltern-E-Mail, Spam-Vorabpruefung (19.0.5.9.0)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DADPMh1FPygpdim3LS8ECw"

git add kjr_event_shop
git commit -m "kjr_event_shop: Einwilligungs-Sperre bei Verkaufsauftrag, deterministischer Anmelde-Controller (19.0.2.1.0)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DADPMh1FPygpdim3LS8ECw"

git add kjr_event_sign tools/einwilligung
git commit -m "kjr_event_sign: Einwilligung der Erziehungsberechtigten per Odoo Sign (19.0.1.0.0)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DADPMh1FPygpdim3LS8ECw"

git add kjr_website_antispam
git commit -m "kjr_website_antispam: Honeypot und signiertes Zeittoken fuer Website-Formulare (19.0.1.0.0)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DADPMh1FPygpdim3LS8ECw"

git add kjr_rental
git commit -m "kjr_rental: Spam-Schutz-Hook fuer die Spielmobil-Anfrage (19.0.5.6.0)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DADPMh1FPygpdim3LS8ECw"

git add tools/icons/build_icons.py tools/website_fixes README.md
git commit -m "Werkzeuge: Icons fuer Sign-Bruecke und Spam-Schutz, Befund A (br in Textareas), README

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DADPMh1FPygpdim3LS8ECw"
```
Hinweis: Die Icons `kjr_event_sign/static/description/icon.png` und
`kjr_website_antispam/static/description/icon.png` gehen mit den jeweiligen
Modul-Commits mit.

## 7. Registrierung Verein/Privatperson (`kjr_grant` 19.0.16.0.0)

Kundenwunsch: Wer sich für einen Verein registriert, wird erst nach
**vorheriger Genehmigung** durch die Geschäftsstelle dem Verband zugeordnet.
Privatpersonen registrieren sich wie bisher ohne Prüfung.

Kurzbeschreibung:
- `/web/signup` (ohne Token) fragt „als Privatperson“ / „für einen Verein /
  Verband“ ab. Bei Verein: Vereinsname Pflicht (2-120 Zeichen, keine URLs),
  Funktion und Ort freiwillig, Datenschutzhinweis Art. 13 direkt darunter.
- Das Konto ist sofort nutzbar, hängt aber NICHT unter dem Verband
  (`parent_id` leer). Es entsteht eine Vereinsregistrierung
  (`kjr.affiliation.request`, Status „beantragt“) mit Aktivität für die
  Geschäftsstelle. Erst „Genehmigen“ (Assistent: bestehende Organisation
  wählen oder neu anlegen) setzt `parent_id`; damit greifen Antrags-,
  Verbands- und Mitgliedspreisrechte. „Ablehnen“ mit optionalem Grund.
- Sperre gegen Umgehung: Signup-Token für Kontakte unter einem
  Mitgliedsverband ohne Benutzer (Benachrichtigungs-Links, Shop-Bestätigung)
  führen nicht mehr zu einem Verbandskonto (`res.users.signup`). Portal-
  Einladungen der Geschäftsstelle und Passwort-Reset funktionieren weiter.
- Portal: Statushinweis auf „Mein Konto“, „Mein Verband“ und
  `/service/antrag-stellen` (Hinweisseite statt leerer Verbandsauswahl).

### 7.1 Upgrade (Server-Kopie, nach Snapshot aus Abschnitt 1)
```
odoo -d <db> -u kjr_grant --stop-after-init
```
- Neue Abhängigkeit `auth_signup` ist über `website` bereits installiert,
  es wird also kein weiteres Modul nachinstalliert.
- Im Log erwarten: `Migration 19.0.16.0.0: <n> Bestandskonto(en) als
  genehmigt übernommen.` Aktive Portalkonten unter Mitgliedsverbänden (auch
  unter einem Dachverband mit Mitgliedsorganisationen) bekommen einen
  Nachweis „genehmigt“, Herkunft „Bestandsübernahme“. Bestehende Rechte
  ändern sich dadurch nicht. Im Log stehen nur Zähler.
- Migrationsregel: Odoo führt `migrations/19.0.16.0.0` aus, weil installiert
  (19.0.15.7.0) < Ordner <= Manifest (19.0.16.0.0). Liegt die Instanz noch
  unter 19.0.15.7.0, läuft `19.0.15.7.0` vorher mit.
- Danach Odoo-Dienst neu starten (neues Asset
  `kjr_grant/static/src/interactions/kjr_signup_club.js`), Browser-Cache
  leeren.
- Tests:
  ```
  odoo -d <testdb> --test-tags /kjr_grant --stop-after-init
  ```
  (darin `test_affiliation.py`, TransactionCase, und
  `test_affiliation_signup_http.py`, HttpCase gegen `/web/signup`).

### 7.2 Einstellungen
- **Freie Registrierung**: Website > Konfiguration > Einstellungen >
  „Kundenkonto“ auf „Freie Registrierung“ (`website.auth_signup_uninvited
  = b2c`). Mit `kjr_event_shop`/`website_sale` ist das bereits gesetzt, sonst
  liefert `/web/signup` 404. Der alte Parameter `auth_signup.allow_uninvited`
  wird von Odoo 19 nicht gelesen.
- **Zuständige Person** für neue Vereinsregistrierungen (optional):
  Systemparameter `kjr_grant.affiliation_responsible_user_id` = Benutzer-ID
  eines aktiven internen Sachbearbeiters. Leer: erste Person der Gruppe
  „Sachbearbeiter“, sonst Aktivität ohne Zuweisung (Warnung im Log).
- **Löschfrist** abgelehnter Registrierungen: Systemparameter
  `kjr_grant.affiliation_rejected_retention_days` (Vorgabe 180, 0 = aus;
  TODO(KJR)/TODO(DSGVO) bestätigen). Cron „KJR: Abgelehnte
  Vereinsregistrierungen löschen“ (täglich, aktiv). Die Frist erscheint
  automatisch im Datenschutzhinweis des Formulars.
- **Verantwortliche Stelle** im Datenschutzhinweis: Systemparameter
  `kjr.privacy.controller` (Einstellungen, „KJR Datenschutzangaben“). Leer =
  sichtbarer Warnhinweis „Angabe folgt“ im Formular. Vor Go-live füllen.
- **Mailvorlagen** „Vereinsregistrierung genehmigt/abgelehnt“
  (`kjr_grant.mail_template_affiliation_approved` / `_rejected`) Text mit der
  Geschäftsstelle abstimmen; Firmenname kommt aus der Firma.
- **Rechte**: Menü KJR > Verbände > Vereinsregistrierungen sehen nur
  Sachbearbeiter und Administrator (KJR). Kontakte interner Benutzer kann nur
  zuordnen, wer zusätzlich Kontaktrechte hat.

### 7.3 Testplan Server-Kopie
Voraussetzung: freie Registrierung an, mindestens ein Mitgliedsverband
(`is_kjr_member`), Test-Postfächer, ein Sachbearbeiter-Benutzer.

1. **Privatperson**: `/web/signup` im privaten Fenster, „als Privatperson“.
   Erwartet: Konto angelegt und angemeldet, keine Vereinsregistrierung,
   kein Hinweis auf Mein Konto, `/service/antrag-stellen` zeigt die
   Hinweisseite.
2. **Verein, Pflichtfelder**: „für einen Verein“ ohne Namen bzw. mit einem
   Zeichen bzw. mit `www.` im Namen absenden. Erwartet: je eigene Meldung,
   Formular behält Art und Eingaben, kein Konto angelegt.
3. **Verein, gültig** (z. B. „SV Teststadt“, Funktion „Jugendleitung“):
   Erwartet: Konto sofort nutzbar, `parent_id` leer; Vereinsregistrierung
   „beantragt“, Herkunft „Registrierung“, Aktivität beim Sachbearbeiter.
   Portal: Hinweis „in Prüfung“ auf Mein Konto, Mein Verband und
   Zuschussantrag; KEIN Zugriff auf Verbandsdaten, keine Mitgliedspreise.
4. **Genehmigen** (bestehender Mitgliedsverband): Assistent schlägt den
   Verband bei gleichem Namen vor. Erwartet: Person unter dem Verband,
   Funktion übernommen (wenn leer), USt-IdNr. der Person nicht zum Verband
   übertragen, Mail „genehmigt“; Portal zeigt Mein Verband, Zuschussantrag
   mit vorausgewähltem Verband. Adresswache: hat die Person eine Anschrift
   und der Verband keine vollständige (Straße, PLZ, Ort), bricht die
   Genehmigung mit Hinweis ab; Verbandsanschrift pflegen, erneut genehmigen.
5. **Genehmigen mit Neuanlage**: ohne vollständige Anschrift (Straße, PLZ,
   Ort) abgewiesen; mit Anschrift neue Organisation, Person darunter.
   Hinweis: neue Organisation ist noch kein Mitgliedsverband, Rechte erst
   nach Setzen von `is_kjr_member`.
6. **Ablehnen** mit Grund: Mail mit Grund, Portal zeigt Ablehnung mit Grund,
   Konto bleibt Privatkonto. Status/Zuordnung im Formular nicht direkt
   änderbar; Vereinsangaben nach der Entscheidung gesperrt.
7. **Token-Sperre**: an einen Kontakt (ohne Benutzer) unter einem
   Mitgliedsverband eine Benachrichtigung bzw. Shop-Bestellbestätigung mit
   Registrierungslink auslösen. Erwartet: Mail ohne Registrierungstoken bzw.
   beim Aufruf des Links Meldung „Für diese Adresse richtet die
   Geschäftsstelle den Zugang ein“, kein Konto. Gegenprobe: Portal-Einladung
   durch die Geschäftsstelle und „Passwort zurücksetzen“ funktionieren.
8. **Bestandskonten**: ein vor dem Update bestehender Verbandszugang hat einen
   Nachweis „genehmigt / Bestandsübernahme“ und unveränderte Rechte.
9. **Datenauskunft** (Art. 15) einer Testperson enthält die
   Vereinsregistrierung. Lösch-Cron mit Frist 0 bzw. kurzer Frist manuell
   auslösen: nur abgelehnte, abgelaufene Registrierungen verschwinden.
10. **Ohne JavaScript**: Vereinsblock erscheint nach Serverfehler mit „club“
    wieder; Prüfung greift serverseitig.
11. Logs während 1-9 auf personenbezogene Daten prüfen (erwartet: nur IDs,
    Zähler, Fehlerklassen).

### 7.4 Commit-Vorschlag (NICHT ausgeführt)
```
git add kjr_grant docs/DEPLOY-einwilligung-sign-2026-10.md
git commit -m "kjr_grant: Registrierung als Privatperson oder Verein, Vereinszuordnung erst nach Genehmigung der Geschaeftsstelle (19.0.16.0.0)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DADPMh1FPygpdim3LS8ECw"
```

## 8. Vorbefüllte Einwilligung und eindeutige Beschriftungen (`kjr_event` 19.0.5.10.0, `kjr_event_sign` 19.0.1.1.0)

Anlass: Auf der Produktion (Stand `ceec800`) stand im Sign-Dokument im Feld
„Name" der Name des Kindes, und Eltern trugen im Anmeldedialog im Feld
„Erziehungsberechtigte/r" den Namen des Kindes ein.

Kurz:
- Anmeldedialog: „Name des Kindes / Teilnehmer/in" (Kernfeld „Name", nur die
  Beschriftung per Template-Override, Fragetitel in der Datenbank
  unverändert), „Geburtsdatum (Kind)", „Name der/des Erziehungsberechtigten",
  „E-Mail der/des Erziehungsberechtigten". Im Verfahren „digitale
  Unterschrift" ist der Name der/des Erziehungsberechtigten für Minderjährige
  Pflicht (Fehlercode `kjr_guardian_name_missing`).
- Sign: neue Vorlage v2 „Einwilligung Erziehungsberechtigte
  (vorausgefüllt)". Name des Kindes, Veranstaltung mit Zeitraum und Name der/des
  Erziehungsberechtigten kommen schreibgeschützt aus der Anmeldung; Eltern
  setzen Haken, Ort, Unterschrift. v1 bleibt installiert (versendete Anfragen
  verweisen darauf) und heißt jetzt „Einwilligung Erziehungsberechtigte (alt,
  ohne Vorbefüllung)" (nur wenn sie noch „… (Standard)" hieß); nicht mehr
  auswählen.
- Anmeldedialog: „Name des Kindes / Teilnehmer/in" wird beim ersten Ticket
  nicht mehr mit dem Namen des angemeldeten Kontos bzw. Website-Besuchers
  (meist ein Elternteil) vorbefüllt.
- Unterzeichner-Kontakt nur noch bei passender E-Mail UND passendem Namen
  wiederverwendet, sonst neuer Kontakt mit dem Namen der Eltern; nie ein
  Kontakt mit dem Namen des Kindes.
- Gemeldeter Fall „erziehungsberechtigter ist name des kindes": Steht im Feld
  der Eltern der Name des Kindes, weist die Website das ab
  (`kjr_guardian_name_is_child`), und die Brücke verschickt mit v2 keine
  Anfrage (Fehlermerker, Aktivität „Unterschriftsanfrage konnte nicht
  versendet werden"). Betrifft Bestandsanmeldungen von `ceec800` bei „Erneut
  senden", Adresskorrektur und Cron-Retry: Namen der Eltern an der Anmeldung
  korrigieren, dann „Erneut senden".
- Ändern sich bei offener v2-Anfrage Name des Kindes, Name der Eltern oder
  Name/Termine der Veranstaltung, wird die Anfrage storniert und neu
  versendet (Registrierungstheke: nur Storno und Aktivität „Unterschriftsanfrage
  neu senden"). Hinweis: Die Eltern erhalten dann eine zweite Sign-Mail.
- Vorbefüllung nur für die eigene Anfrage der Anmeldung
  (`sign.request.item._get_auto_field_value`); eine fremde Anfrage mit
  `reference_doc` auf eine Anmeldung bekommt keine Werte. Restrisiko: Wer
  eine Anfrage in Sign öffnen darf, sieht die gespeicherten Namen von Kind
  und Eltern, deshalb Sign-Rechte nur an die Betreuungsgruppe vergeben.
  Anfragen nicht über den Sign-Assistenten („Senden"/„Jetzt unterschreiben")
  aus der Vorlage v2 verschicken, sondern über „Unterschrift anfordern" an
  der Anmeldung; sonst bleiben die drei Felder leer.
- Anonymisierung (K6): Mit v2 trägt jede Anfrage schon beim Anlegen die
  Namen von Kind und Eltern. Nie unterschriebene Anfragen (auch frühere aus
  „Erneut senden"/Adresswechsel) werden bei der Anonymisierung GELÖSCHT,
  unterschriebene bleiben archiviert. Bis dahin bleiben stornierte Anfragen
  mit den Namen in Sign sichtbar.

### 8.1 Upgrade (Server-Kopie, nach Snapshot)
```
odoo -d <db> -u kjr_event,kjr_event_sign --stop-after-init
```
- Im Log erwarten: `KJR Einwilligung (Sign): Standardvorlage <v2-id>
  (Parameter: set|kept), <n> Veranstaltung(en) von Vorlage <v1-id> auf <v2-id>
  umgestellt.` und `Vorlage <v1-id> (v1) umbenannt.` `kept` bedeutet: in den Einstellungen war eine eigene Vorlage
  gewählt, sie bleibt.
- Odoo-Dienst neu starten (geändertes Asset `kjr_consent_fields.js`),
  Browser-Cache leeren.
- Tests:
  ```
  odoo -d <testdb> --test-tags /kjr_event,/kjr_event_sign --stop-after-init
  ```

### 8.2 Prüfen auf der Server-Kopie
1. Sign > Vorlagen: „… (vorausgefüllt)" öffnen; v1 heißt „… (alt, ohne
   Vorbefüllung)", keine Vorlage trägt mehr „Standard" im Namen. Drei Felder als
   „schreibgeschützt" (Read-only), Lage passend zum PDF. Einstellungen >
   „KJR Einwilligung": Standardvorlage ist v2 (oder die eigene).
2. Anmeldedialog einer Veranstaltung mit Einwilligungspflicht: Beschriftungen
   wie oben; Geburtsdatum < 18: Stern am Namen der Eltern, Absenden ohne
   Namen blockiert der Browser; per Entwicklerwerkzeug `required` entfernen:
   Fehlermeldung „Bitte geben Sie den Namen der/des Erziehungsberechtigten
   an.", nichts angelegt.
3. Minderjährige Anmeldung mit Namen und E-Mail der Eltern: Sign-Mail an die
   Eltern mit Anrede des Eltern-Namens (nicht des Kindes); im Dokument Kind,
   „<Veranstaltung>, TT.MM.JJJJ bis TT.MM.JJJJ" und Eltern-Name
   vorbefüllt und nicht änderbar; Haken, Ort, Unterschrift, Datum automatisch.
   Unterschreiben -> Anmeldung registriert. Im fertigen PDF stehen alle Werte.
4. Angemeldet als Elternteil mit Kundenkonto (gleicher Name wie im Formular):
   Anfrage erscheint unter „Mein Konto" > „Signaturanfragen".
5. Backend: Anmeldung ohne Namen der Eltern -> „Unterschrift anfordern" ->
   Meldung „fehlgeschlagen", Aktivität; Namen nachtragen, „Erneut senden" ->
   Anfrage mit v2.
6. Eine vor dem Update versendete v1-Anfrage lässt sich weiter unterschreiben
   (Felder wie bisher von Hand).
7. Logs auf personenbezogene Daten prüfen (erwartet: nur IDs, Zähler).
8. Anmeldedialog, Verfahren „digitale Unterschrift", minderjährig: im Feld
   „Name der/des Erziehungsberechtigten" denselben Namen wie bei „Name des
   Kindes / Teilnehmer/in" eintragen -> der Browser markiert beide Felder;
   per Entwicklerwerkzeug umgangen -> Hinweis „Die Namen bei „Name des
   Kindes / Teilnehmer/in“ und „Name der/des Erziehungsberechtigten“ sind
   gleich. Bitte prüfen Sie beide Angaben.", nichts angelegt.
   Zusätzlich angemeldet (Portal- oder Backend-Konto) den Anmeldedialog
   öffnen -> „Name des Kindes / Teilnehmer/in" beim ersten Ticket ist LEER
   (nicht mehr mit dem Kontonamen vorbefüllt), E-Mail ist vorbefüllt.
9. Backend: Bestandsanmeldung mit Kindernamen im Feld der Eltern ->
   „Erneut senden" -> fehlgeschlagen, Aktivität, keine neue Anfrage; Namen
   korrigieren, „Erneut senden" -> Anfrage an den Eltern-Kontakt.
10. Auf einer Kopie: Anonymisierung einer Anmeldung mit stornierter und
    offener Anfrage laufen lassen -> beide Anfragen gelöscht; eine
    unterschriebene bleibt archiviert.
11. Offene v2-Anfrage, dann im Backend den Namen der Eltern (oder des
    Kindes, oder die Termine der Veranstaltung) berichtigen -> alte Anfrage
    storniert („… Angaben der Anmeldung geändert."), neue Anfrage mit den
    berichtigten Angaben an die Eltern. Als Registrierungstheke geändert ->
    nur Storno und Aktivität „Unterschriftsanfrage neu senden".
12. Per RPC (z. B. Entwicklerkonsole) als Benutzer/in ohne Systemrechte
    `kjr_sign_request_id` einer Anmeldung setzen -> Zugriffsfehler „… kann
    nicht von Hand gesetzt werden".

### 8.3 Offen
- TODO(KJR): Text der Vorlage v2 mit Geschäftsstelle und
  Datenschutzbeauftragter abstimmen (wie bei v1).
- Ist ein Elternteil angemeldet (Website-Login), füllt Odoo das Kernfeld
  „Name des Kindes / Teilnehmer/in" des ersten Teilnehmers mit dem Namen des
  Kontos vor (`default_first_attendee`, website_event). Die neue Beschriftung
  macht das sichtbar; das Vorbelegen selbst ist unverändert (Entscheidung, ob
  es abgeschaltet werden soll).

### 8.4 Commit-Vorschlag (NICHT ausgeführt)
```
git add kjr_event
git commit -m "kjr_event: Eindeutige Beschriftungen im Anmeldedialog, Name der Erziehungsberechtigten Pflicht im Verfahren Unterschrift (19.0.5.10.0)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DADPMh1FPygpdim3LS8ECw"

git add kjr_event_sign tools/einwilligung docs/DEPLOY-einwilligung-sign-2026-10.md
git commit -m "kjr_event_sign: Vorbefuellte Einwilligung v2, Unterzeichner nie der Kind-Kontakt (19.0.1.1.0)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DADPMh1FPygpdim3LS8ECw"
```
