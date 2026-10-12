# KJR Spam-Schutz für Website-Formulare (`kjr_website_antispam`)

Unsichtbarer Spam-Schutz ohne Drittanbieter für die öffentlichen Formulare der
Website. Zwei Prüfungen:

1. **Honeypot** (`kjr_hp`): ein für Menschen unsichtbares Textfeld. Ist es
   ausgefüllt, war es fast sicher ein Bot.
2. **Signiertes Zeittoken** (`kjr_ts`): `<Unix-Sekunden>.<HMAC-SHA256>`, signiert
   mit `database.secret` (`odoo.tools.misc.hmac`, Geltungsbereich
   `kjr_website_antispam`). Abgewiesen wird, wenn das Token fehlt, gefälscht ist,
   jünger als `min_seconds` (Bot sendet sofort) oder älter als `max_age_hours`
   ist. Die Mindestzeit läuft ab dem **Ausstellen des Tokens** (Laden des
   Formulars), nicht ab der ersten Eingabe; für den vorausgefüllten
   Teilnehmerdialog der Veranstaltung gilt sie deshalb nicht (siehe
   „Mindestzeit").

Das hält **einfache Formular-Bots** ab, nicht gezielte Angriffe (siehe
„Grenzen").

Der Schutz hängt am Odoo-Standard-Hook `ir.http._verify_request_recaptcha_token`
(denselben benutzen reCAPTCHA und Cloudflare Turnstile) und läuft NACH deren
Prüfung (`super()` zuerst).

## Wo er greift

Nur bei POST-Anfragen und nur für Aktionen aus dem Systemparameter
`kjr_website_antispam.actions` (kommagetrennt, Platzhalter wie `kjr_*`):

| Aktion | Formular | Woher kommt das Token |
|---|---|---|
| `website_form` | Formulare aus dem Website-Builder | Interaction `kjr_antispam.js` holt es per jsonrpc `/service/antispam/token` |
| `website_event_registration` | Teilnehmerdialog der Veranstaltungsanmeldung | serverseitig beim Rendern des Dialogs (`views/templates.xml`) |
| `kjr_spielmobil` (über `kjr_*`) | Spielmobil-Anfrage (`kjr_rental`, `form[data-captcha="kjr_spielmobil"]`) | Interaction per jsonrpc |

Login, Registrierung und Passwort-Zurücksetzen sind nie betroffen; diese
Aktionen gehören auch nicht in die Liste.

Eigene KJR-Formulare bekommen den Schutz, indem
1. das `<form>` das Attribut `data-captcha="kjr_<name>"` trägt (dann fügt die
   Interaction Honeypot und Token ein) und
2. der Controller im POST-Zweig
   `request.env['ir.http']._verify_request_recaptcha_token('kjr_<name>')` in
   `try/except UserError` aufruft und eine Fehlermeldung rendert.

**Formulare ohne JavaScript werden abgewiesen** (Modus `enforce`): ohne
JavaScript fehlt das Token bei Builder- und `data-captcha`-Formularen. Im
Teilnehmerdialog der Veranstaltung ist das Token serverseitig gerendert; der
Dialog selbst braucht ohnehin JavaScript.

## Systemparameter (Einstellungen > Technisch > Systemparameter)

| Schlüssel | Start | Bedeutung |
|---|---|---|
| `kjr_website_antispam.mode` | `enforce` | `enforce` weist ab, `log` protokolliert nur, `off` prüft nicht. Unbekannte Werte gelten als `enforce`. |
| `kjr_website_antispam.min_seconds` | `2` | Mindestzeit zwischen Ausstellen des Tokens (Laden) und Absenden. `0` = keine Mindestzeit. |
| `kjr_website_antispam.min_seconds_exempt` | `website_event_registration` | Aktionen OHNE Mindestzeit (fnmatch, kommagetrennt); Honeypot, Signatur und Höchstalter gelten weiter. `-` = keine Ausnahme (leer gilt als Standard). |
| `kjr_website_antispam.max_age_hours` | `24` | Höchstalter des Tokens. `0`/leer/ungültig ergibt wieder 24. Offene Seiten holen das Token nach 20 h beim nächsten Klick ins Formular neu. |
| `kjr_website_antispam.actions` | `website_form,website_event_registration,kjr_*` | geprüfte Aktionen (fnmatch) |

Die Startwerte stehen unter `noupdate="1"`: gepflegte Werte überleben ein
Update. Die Schlüssel **nicht vor der Installation von Hand anlegen**:
`ir.config_parameter.key` ist eindeutig, die Installation bräche ab.

### Mindestzeit

Das Token belegt nur, wann es ausgestellt wurde. Echte Besucher können ein
Formular sehr schnell absenden, wenn es schon ausgefüllt ist:

- **Teilnehmerdialog der Veranstaltung** (`website_event_registration`): Das
  Token entsteht erst, wenn der Dialog nach Ticketauswahl und Klick gerendert
  wird (`/event/<id>/registration/new`). Für angemeldete Benutzer und
  wiedererkannte Besucher füllt der Kern Name, E-Mail und Telefon vor;
  `kjr_event` macht ein Feld nur bei Veranstaltungen mit Einwilligungsverfahren
  zur Pflicht. Ein einziger Klick auf „Registrierung bestätigen" kurz nach dem
  Öffnen ist dort normal. Deshalb steht die Aktion standardmäßig in
  `min_seconds_exempt`: geprüft werden nur Honeypot, Signatur und Höchstalter.
  Ein Bot, der den Dialog nicht per jsonrpc abruft, hat ohnehin kein Token
  (`token_missing`).
- **Spielmobil-Anfrage** nach einem Fehler: Der Server zeigt das Formular mit
  allen Eingaben erneut an, die Interaction holt beim Laden ein frisches
  Token. Wer sofort wieder absendet, liegt unter der Mindestzeit; die Meldung
  bittet deshalb darum, einen Moment zu warten.
- **Builder-Formulare** mit vorbelegten Feldern (z. B. Name/E-Mail angemeldeter
  Benutzer): wenige Sekunden reichen in der Regel, weil mindestens ein Feld
  (Nachricht) selbst ausgefüllt wird.

Die Interaction holt das Token bewusst beim Laden der Seite und nicht erst
bei der ersten Eingabe: Das verkürzte die gemessene Zeit nur, und wer ohne
Fokuswechsel absendet (Safari fokussiert Knöpfe beim Klick nicht, Autofill),
hätte gar kein Token.

## Betrieb und Rollout

1. Nur auf Staging bzw. einer Server-Kopie installieren:
   `-i kjr_website_antispam` (kein `auto_install`; ein `-u` installiert das
   Modul nicht).
2. **Direkt danach `kjr_website_antispam.mode` auf `log` stellen** und einige
   Tage beobachten. Im Log stehen Zeilen der Form
   `Spam-Schutz: Aktion website_form abgewiesen (too_fast), Modus log`.
   Gründe: `honeypot`, `token_missing`, `token_invalid`, `too_fast`, `expired`.
   **Besonders auf `too_fast` achten**, vor allem bei Absendungen
   angemeldeter Benutzer bzw. wiedererkannter Besucher (vorausgefüllte
   Formulare) und bei erneut abgesendeten Spielmobil-Anfragen. Das Log nennt
   bewusst keine Benutzer; bei Häufung zeitgleich mit den eingegangenen
   Anfragen bzw. Anmeldungen abgleichen. Treten echte Absendungen als
   `too_fast` auf, `min_seconds` senken (z. B. `1`) oder die Aktion in
   `min_seconds_exempt` aufnehmen, bevor auf `enforce` umgestellt wird.
3. Erscheinen nur erwartbare Treffer, auf `enforce` stellen.
4. Testen: Builder-Kontaktformular, Veranstaltungsanmeldung (kostenlos und
   bezahlt, je einmal angemeldet und abgemeldet), Spielmobil-Anfrage. Jeweils
   normal absenden (muss durchgehen). Builder-Formular und Spielmobil-Anfrage
   einmal sofort nach dem Laden absenden (im Modus `enforce` abgewiesen). Den
   Teilnehmerdialog als angemeldeter Benutzer öffnen und sofort bestätigen
   (muss durchgehen, keine Mindestzeit). Spielmobil: nach einer Abweisung kurz
   warten und erneut absenden (muss durchgehen).
5. **Veranstaltungsanmeldung mit bereits gefülltem Warenkorb** gezielt testen
   (Kernfall, siehe „Grenzen"): im Shop ein Veranstaltungsticket in den
   Warenkorb legen, dann bei einer Veranstaltung mit Tickets den
   Teilnehmerdialog öffnen und eine Abweisung provozieren (je einmal mit nur
   kostenlosen und mit bezahlten Tickets im Warenkorb). Weil für den Dialog
   keine Mindestzeit gilt, dafür auf der Server-Kopie entweder
   `min_seconds_exempt` kurz auf `-` stellen und sofort absenden (`too_fast`)
   oder in den Entwicklerwerkzeugen des Browsers das Feld `kjr_hp` füllen
   (`honeypot`). Im Modus `log` geht die Anmeldung durch und das Log zeigt den
   Grund. Die Abweisung selbst lässt sich nur im Modus `enforce` nachstellen
   (auf der Server-Kopie kurz umschalten, danach beide Werte zurückstellen).
   Erwartet: Weiterleitung auf die Anmeldeseite mit
   `registration_error_code=recaptcha_failed`, KEIN Checkout und KEINE
   Bestätigung des alten Warenkorbs. Landet der Test im Checkout
   (`/shop/checkout`) oder auf `/shop/confirmation`, nicht auf `enforce`
   stellen und prüfen, ob kjr_event (ab 19.0.5.9.0) aktualisiert ist; dessen
   Controller nutzt die Vorabprüfung (siehe „Grenzen").

### Notbremse

Melden echte Besucher Abweisungen: `kjr_website_antispam.mode` auf `log`
(weiter protokollieren) oder `off` (gar nicht prüfen) stellen. Wirkt sofort,
ohne Neustart und ohne Modulupdate.

Bei Abweisung sieht der Besucher eine neutrale Meldung. Builder-Formulare:
dort prüft Odoo vor dem Controller (`captcha='website_form'` an der Route), der Fehler kommt als HTTP-Fehler zurück und das Formular zeigt
seine Standard-Fehlermeldung; genauso verhält sich Odoo bei reCAPTCHA. Die
Veranstaltungsanmeldung leitet wie im Standard auf die Anmeldeseite mit
`registration_error_code=recaptcha_failed`; der dortige Kerntext („Suspicious
activity detected by Google reCaptcha") ist durch einen neutralen deutschen
Text ersetzt („… Bitte wählen Sie Ihre Tickets erneut aus und bestätigen Sie
die Anmeldung noch einmal."). Bewusst ohne Aufforderung zum Neuladen: Die URL
behält `registration_error_code=recaptcha_failed`, nach dem Neuladen stünde
dieselbe Meldung wieder da. Neuladen ist auch nicht nötig, denn das erneute
Öffnen des Teilnehmerdialogs (`/event/<id>/registration/new`) rendert die
Felder serverseitig mit frischem Token. Die Spielmobil-Anfrage
zeigt das Formular mit allen Eingaben und einem frischen Token erneut an und
bittet nur um erneutes Absenden (kein Neuladen: die Seite ist die Antwort auf
den POST, F5 schickte den alten POST mit dem alten Token noch einmal). Weil
das frische Token wieder unter die Mindestzeit fällt, bittet die Meldung
darum, einen Moment zu warten.

## Grenzen

- **Nur einfache Formular-Bots.** Das Zeittoken ist öffentlich: jeder kann es
  anonym und ohne CSRF über `/service/antispam/token` abrufen (im
  Teilnehmerdialog steht es ohnehin im HTML). Es ist weder an eine Aktion
  noch an eine Sitzung gebunden, wird nicht als verbraucht markiert und ist
  bis `max_age_hours` (24 h) **beliebig oft wiederverwendbar**; eine
  Ratenbegrenzung gibt es nicht. Ein gezielt geschriebener Bot holt einmal
  ein Token, wartet `min_seconds` und kann danach 24 h lang beliebig viele
  Builder-Formulare, Veranstaltungsanmeldungen und Spielmobil-Anfragen
  absenden. Abgehalten werden Bots, die Formulare blind ausfüllen (Honeypot)
  oder ohne JavaScript bzw. sofort absenden. Für den Teilnehmerdialog der
  Veranstaltung gilt keine Mindestzeit (siehe „Mindestzeit"); dort schützen
  nur Honeypot und Token (der Dialog muss per jsonrpc abgerufen werden).
- **Gegen gezielte Angriffe** hilft zusätzlich Cloudflare Turnstile (siehe
  unten), mit Drittlandtransfer und Eintrag in der Datenschutzerklärung (siehe
  „Datenschutz"). Diese Abwägung gehört in die Rollout-Entscheidung; eine
  Ratenbegrenzung leistet ggf. der Reverse-Proxy beim Hoster.
- **Veranstaltungsanmeldung mit gefülltem Warenkorb (Odoo-Kernverhalten).**
  Weist der Hook eine Anmeldung ab, leitet `website_event` auf
  `registration_error_code=recaptcha_failed` und legt nichts an. Liegen im
  Warenkorb aber schon Ticketzeilen und enthält die abgewiesene Anmeldung
  Tickets, verwirft `website_event_sale` diese
  Weiterleitung: bei ausschließlich kostenlosen Tickets bestätigt es den
  Warenkorb (`action_confirm`, `/shop/confirmation`), sonst geht es auf
  `/shop/checkout`, und ein anonymer Warenkorb bekommt die Adressdaten aus der
  abgewiesenen Anfrage (`website_event_sale/controllers/main.py`,
  `registration_confirm`). Der Besucher sieht keine Fehlermeldung, sondern
  den Checkout seines alten Warenkorbs. Das gilt genauso für reCAPTCHA und
  Turnstile, wird mit diesem Schutz im Modus `enforce` aber häufiger
  (`expired`, `token_missing`, `honeypot`; `too_fast` nur, wenn die Aktion
  aus `min_seconds_exempt` entfernt wurde). Eine Prüfung der Antwort NACH
  `super()` im äußeren Controller hilft hier nicht, weil die
  Fehler-Weiterleitung dann schon durch die Shop-Weiterleitung ersetzt ist.
  Dafür gibt es `ir.http._kjr_antispam_precheck(action)`: liefert ohne
  Nebenwirkung (nichts entfernt, nichts protokolliert, reCAPTCHA-/Turnstile-
  Einmal-Token unberührt) den Abweisungsgrund im Modus `enforce`, sonst
  `None`. Der äußere Veranstaltungs-Controller (`kjr_event` ab 19.0.5.9.0,
  `_kjr_antispam_rejects`) ruft sie VOR `super()` auf und leitet bei einem
  Grund selbst auf `recaptcha_failed` um; der Warenkorb bleibt unberührt.
  Abweisungen durch reCAPTCHA/Turnstile selbst bleiben Kernverhalten.

## Optional: Cloudflare Turnstile

Zusätzlich zum unsichtbaren Schutz kann das Odoo-Standardmodul
**`website_cf_turnstile`** (Cloudflare Turnstile) eingesetzt werden:

1. Modul `website_cf_turnstile` installieren.
2. Unter *Einstellungen > Website* den Site-Key und den Secret-Key eintragen
   (Systemparameter `cf.turnstile_site_key` und `cf.turnstile_secret_key`).
3. Alle oben genannten Formulare testen.

> **WARNUNG:** Sobald `cf.turnstile_secret_key` gesetzt ist, scheitert JEDE
> Aktion, die den Hook aufruft, wenn das Formular kein Turnstile-Widget
> mitschickt. Turnstile bedient von sich aus nur Builder-Formulare, den
> Teilnehmerdialog der Veranstaltung und Formulare mit `data-captcha` und einem
> `button[type=submit]`. **Eigene Formulare brauchen deshalb zwingend
> `data-captcha`**, sonst sind sie mit gesetztem Secret nicht mehr absendbar.

**Rollback:** `cf.turnstile_secret_key` leeren. Ohne Secret meldet Turnstile
`no_secret` und lässt alles durch; dieser Spam-Schutz arbeitet unverändert weiter.

## Google reCAPTCHA

Die reCAPTCHA-Schlüssel (*Einstellungen > Website > reCAPTCHA*) **nicht setzen,
ohne vorher die Spielmobil-Seite (`/service/spielmobil`) zu testen.** Mit
gesetztem Secret scheitert jede geprüfte Aktion ohne gültiges reCAPTCHA-Token.
In Odoo 19 bedient `google_recaptcha` zwar auch `form[data-captcha]`
(Interaction `RecaptchaForm`, setzt einen `button[type=submit]` im Formular
voraus), das muss auf der Instanz aber vor dem Scharfschalten nachgewiesen
werden. Rollback: Secret leeren.

## Datenschutz

- Honeypot und Zeittoken verarbeiten **keine personenbezogenen Daten** und
  übertragen nichts an Dritte. Sie müssen nicht gesondert in die
  Datenschutzerklärung.
- Das Log enthält nur Aktion, Grund und Modus: keine IP-Adresse, keine
  Formularwerte, kein Token.
- **Turnstile und reCAPTCHA** übertragen IP-Adresse und Browsermerkmale an
  Cloudflare bzw. Google (USA, **Drittlandtransfer**). Vor dem Einschalten
  müssen sie in die Datenschutzerklärung, und die Rechtsgrundlage
  (Einwilligung bzw. berechtigtes Interesse, ggf. Consent-Banner) ist mit der
  oder dem Datenschutzbeauftragten zu klären. AVV/TOM-Anlage ergänzen.

## Offen (Kundenentscheidung)

- Honeypot-Treffer still verwerfen (scheinbarer Erfolg) oder wie heute mit
  Meldung abweisen.
- Ob die B2C-Registrierung aktiv ist (Schutz der `auth='user'`-Formulare).

## Technik

- `models/ir_http.py`: Override von `_verify_request_recaptcha_token`, Helfer
  `_kjr_antispam_mode`, `_kjr_antispam_applies`, `_kjr_antispam_check`,
  `_kjr_antispam_token`, `_kjr_antispam_token_age`,
  `_kjr_antispam_min_seconds(action)` (Ausnahmen aus `min_seconds_exempt`).
- `_kjr_antispam_precheck(action)`: nebenwirkungsfreie Vorabprüfung für
  äußere Controller (siehe „Grenzen").
- `controllers/main.py`: jsonrpc `/service/antispam/token` (öffentlich, nur lesend).
- `views/templates.xml`: `kjr_website_antispam.fields`, Erweiterung des
  Teilnehmerdialogs (vor `div.modal-footer`) und Ersatz der
  `recaptcha_failed`-Meldung.
- `static/src/interactions/kjr_antispam.js`: Interaction für
  `.s_website_form form, form.s_website_form, form[data-captcha]`. Fügt die
  Felder zur Laufzeit ein (`this.insert`), sie landen nie im gespeicherten
  Seiteninhalt.
- Tests: `--test-tags /kjr_website_antispam`.
