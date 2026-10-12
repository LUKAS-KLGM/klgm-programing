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
   der Anmeldung, archiviert die Anfragen.

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
