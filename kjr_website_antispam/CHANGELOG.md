# Changelog – KJR Spam-Schutz für Website-Formulare (`kjr_website_antispam`)

## 19.0.1.0.0 (2026-10-12)

### Neu
- **Unsichtbarer Spam-Schutz ohne Drittanbieter** für Website-Builder-Formulare
  (`website_form`), die Veranstaltungsanmeldung (`website_event_registration`)
  und alle KJR-Formulare (`kjr_*`, zuerst die Spielmobil-Anfrage aus
  `kjr_rental`). Honeypot `kjr_hp` und signiertes Zeittoken `kjr_ts`
  (HMAC mit `database.secret`), angehängt an den Standard-Hook
  `ir.http._verify_request_recaptcha_token` nach reCAPTCHA/Turnstile.
- **Modus** `enforce` | `log` | `off` über `kjr_website_antispam.mode`;
  Mindestzeit (2 s), Höchstalter (24 h) und Aktionsliste als Systemparameter
  (`noupdate`).
- **Keine Mindestzeit für den Teilnehmerdialog der Veranstaltung.** Die
  Mindestzeit läuft ab dem Ausstellen des Tokens. Der Dialog wird erst nach
  Ticketauswahl gerendert und für angemeldete Benutzer bzw. wiedererkannte
  Besucher vom Kern vorausgefüllt; ein sofortiger Klick auf „Registrierung
  bestätigen" ist dort normal und wurde im Modus `enforce` als `too_fast`
  abgewiesen. Neuer Systemparameter `kjr_website_antispam.min_seconds_exempt`
  (fnmatch, Start `website_event_registration`, `-` = keine Ausnahme); für
  diese Aktionen gelten weiter Honeypot, Signatur und Höchstalter.
- **Token-Route** `/service/antispam/token` (jsonrpc, öffentlich, nur lesend)
  und Interaction `kjr_website_antispam.antispam`, die Honeypot und Token zur
  Laufzeit in Builder- und `data-captcha`-Formulare einfügt und das Token nach
  20 Stunden beim nächsten Fokus erneuert.
- **Teilnehmerdialog der Veranstaltung**: Felder serverseitig gerendert (vor
  `div.modal-footer`).
- **Neutrale Fehlermeldung** statt „Suspicious activity detected by Google
  reCaptcha" bei `registration_error_code=recaptcha_failed`.
- **Vorabprüfung** `ir.http._kjr_antispam_precheck(action)`: liefert ohne
  Nebenwirkung (keine Parameter entfernt, kein Log, Captcha-Einmal-Token
  unberührt) den Abweisungsgrund im Modus `enforce`, sonst `None`. Für den
  äußeren Veranstaltungs-Controller, weil `website_event_sale` die
  Fehler-Weiterleitung bei gefülltem Warenkorb verwirft (README, „Grenzen").
- **README „Grenzen"**: Schutz nur gegen einfache Bots (Token öffentlich,
  bis zum Höchstalter mehrfach verwendbar, keine Ratenbegrenzung);
  Kernverhalten der Veranstaltungsanmeldung mit gefülltem Warenkorb und
  gezielter Rollout-Test dafür.
- Tests (`tests/test_antispam.py`): gültiges, zu junges, zu altes und
  manipuliertes Token, Honeypot, nicht gelistete Aktion, `kjr_*`-Muster,
  Modus `log`/`off`, Entfernen der Parameter, Log ohne Werte, Vorabprüfung
  ohne Nebenwirkung, Standard-Mindestzeit, Ausnahme für den Teilnehmerdialog,
  Ansichten.
- README: Abschnitt „Mindestzeit"; im Rollout (Modus `log`) ausdrücklich auf
  `too_fast` bei angemeldeten Benutzern und erneut abgesendeten Formularen
  achten.

### Hinweise zur Installation
- Kein `auto_install`: Installation mit `-i kjr_website_antispam`.
- Direkt nach der Installation `kjr_website_antispam.mode` auf `log` stellen,
  beobachten, dann `enforce` (README.md, Abschnitt „Betrieb und Rollout").
- Die Parameter-Schlüssel nicht vorab von Hand anlegen (eindeutiger Schlüssel,
  die Installation bräche ab).
- Das App-Icon (`static/description/icon.png`) erzeugt
  `tools/icons/build_icons.py`.

### Abweichungen von der Spezifikation
- Auch wenn eine Aktion NICHT geprüft wird (nicht gelistet, Modus `off`, GET),
  werden `kjr_hp` und `kjr_ts` aus `request.params` entfernt. Sonst landeten
  sie im Modus `off` beim Website-Formular als zusätzliche Angaben im
  erzeugten Datensatz.
- `_kjr_antispam_token()` nimmt optional `timestamp` an (nur für Tests).
- `min_seconds` startet mit 2 statt 3 (Spezifikation 4.1): weniger
  Fehlabweisungen echter Besucher bei schnell bzw. erneut abgesendeten
  Formularen. Zusätzlicher Parameter `min_seconds_exempt` (nicht in der
  Spezifikation), siehe oben.
- Die Interaction holt das Token weiterhin beim Laden der Seite, nicht erst
  bei der ersten Eingabe: Das verkürzte die gemessene Zeit nur, und
  Absendungen ohne Fokuswechsel (Safari, Autofill) hätten kein Token.
- `max_age_hours` = 0 bedeutet nicht „unbegrenzt", sondern fällt auf 24 zurück
  (ein Token ohne Ablauf wäre beliebig wiederverwendbar).
- `_kjr_antispam_precheck()` ist nicht in der Spezifikation vorgesehen
  (zusätzliche, rein lesende Methode; aufgerufen von `kjr_event` 19.0.5.9.0,
  `_kjr_antispam_rejects`, vor der Verkaufslogik).
- README: `google_recaptcha` bedient in Odoo 19 entgegen der Spezifikation
  `form[data-captcha]` (`RecaptchaForm`); der Test der Spielmobil-Seite vor dem
  Setzen der reCAPTCHA-Schlüssel bleibt trotzdem Pflicht.
