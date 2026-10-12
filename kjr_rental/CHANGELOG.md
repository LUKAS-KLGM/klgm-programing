# Changelog – KJR Materialverleih

## 19.0.5.6.0 (2026-10-12)

### Geändert
- **Spam-Schutz für die Spielmobil-Anfrage.** Der POST-Zweig von
  `/service/spielmobil` ruft jetzt den Odoo-Standard-Hook
  `ir.http._verify_request_recaptcha_token('kjr_spielmobil')` auf. Schlägt die
  Prüfung fehl (`UserError`, dazu zählt auch `ValidationError`), erscheint oben
  im Formular die Meldung „Die Sicherheitsprüfung ist fehlgeschlagen. Bitte
  prüfen Sie Ihre Angaben, warten Sie einen Moment und senden Sie das
  Formular dann erneut ab."; die übrigen
  Feldprüfungen laufen wie bisher und das Formular wird mit allen Fehlern und
  den eingegebenen Werten neu angezeigt. Es wird nichts angelegt. Die Meldung
  fordert bewusst NICHT zum Neuladen auf (Abweichung vom Wortlaut der
  Spezifikation 4.2): Die Seite ist die Antwort auf den POST, F5 schickte den
  alten POST mit altem Token erneut, ein Neuaufruf verlöre alle Eingaben. Das
  neu gerenderte Formular bekommt ein frisches Token und kann erneut
  abgesendet werden. Weil für das frische Token wieder die Mindestzeit von
  `kjr_website_antispam` gilt (Standard 2 s ab dem Laden), bittet die Meldung
  darum, einen Moment zu warten; sofortiges erneutes Absenden würde sonst
  wieder als `too_fast` abgewiesen.
- Das Formular trägt `data-captcha="kjr_spielmobil"`. Damit fügt
  `kjr_website_antispam` (Honeypot und Zeittoken) bzw. ein eingerichtetes
  Turnstile/reCAPTCHA seine Felder ein.
- Die Feldfehler stehen weiter als Liste über dem Formular; die Captcha-Meldung
  steht als eigener Hinweis davor und wird in der Liste nicht wiederholt.

### Hinweise zur Installation
- **Keine neue Modulabhängigkeit.** Ohne `kjr_website_antispam` und ohne
  Captcha-Schlüssel ist der Hook ein No-op, die Seite verhält sich wie bisher.
- Den eigentlichen Schutz liefert `kjr_website_antispam` (Installation mit
  `-i kjr_website_antispam`, zuerst im Modus `log`; siehe dessen README.md).
- **reCAPTCHA- oder Turnstile-Schlüssel erst setzen, nachdem die
  Spielmobil-Seite damit getestet wurde.** Mit gesetztem Secret wird jede
  Anfrage ohne gültiges Captcha-Token abgewiesen.

## 19.0.5.5.1 (2026-10-11)

### Behoben
- **Warenkorb-Anfrage verlor den Zeitraum.** Die Datumsfelder gehörten zum
  Warenkorb-Formular, „Anfrage absenden" zu einem zweiten Formular mit
  versteckten Datumskopien, die erst nach „Aktualisieren" befüllt waren. Wer
  die Daten eintrug und direkt absendete, bekam „Bitte gültigen Zeitraum
  (JJJJ-MM-TT) angeben". Jetzt ist es ein Formular: Absenden geht an
  `/service/verleih/checkout`, Aktualisieren und Entfernen posten per
  `formaction` (`formnovalidate`) an den Warenkorb. Der Checkout übernimmt in
  der Tabelle geänderte Mengen. Die Datumsfelder sind Pflicht, der Browser
  meldet fehlende Daten vor dem Absenden. (Eintrag nachgetragen, die
  Auslieferung war ohne CHANGELOG-Zeile erfolgt.)

## 19.0.5.5.0 (2026-10-11)

### Geändert
- **Firmenlogo im Kopf der Ausleih-Detailseite im Portal.** Das Logo kommt aus
  `res.company` (Gesellschaft des Vorgangs, ersatzweise `res_company`),
  Alternativtext und Titel aus dem Firmennamen. Ohne eigenes hinterlegtes Logo
  bleibt nur die Überschrift stehen, statt den Odoo-Platzhalter zu zeigen.
- **Kunden- und Ortsbezüge aus dem Modul entfernt (White Label).** Die drei
  Seed-Lagerorte heißen jetzt Hauptlager, Nebenlager und Außenlager; die echten
  Lagerorte sind Instanzdaten. In Katalog, Spielmobilseite, Datenschutzblock,
  Rückgabe- und Anonymisierungshinweisen sowie in den Fehlermeldungen des
  öffentlichen Formulars nennt der Text die Organisation über `res.company`
  bzw. spricht von „der Geschäftsstelle" und „dem Betreiber". Die sechs
  Platzhalter im Datenschutzblock heißen jetzt „wird noch ergänzt" statt „wird
  vom KJR ergänzt": die sechs `kjr.privacy.*`-Parameter werden bewusst nicht
  ausgeliefert, der Auslieferungszustand ist also genau dieser Platzhalter, und
  er stand bis hierher als Kürzel des Erstkunden auf der öffentlichen Seite
  jedes weiteren Betreibers. Ebenso im Katalogtext: dort stand das interne
  Feldlabel „KJR-Mitgliedsverband" im Fließtext, jetzt steht dort neutral
  „das bei Ihrer Organisation hinterlegte Mitgliedskennzeichen". Das Feldlabel
  selbst (`models/res_partner.py`) bleibt unverändert, es ist in drei Modulen
  wortgleich und eine einseitige Änderung machte das Verhalten von der
  Ladereihenfolge abhängig.
- **Einzugsgebiet des Spielmobils ist konfigurierbar.** Neuer Systemparameter
  `kjr_rental.spielmobil_area` (Freitext, z. B. „im Kreisgebiet"). Er wird nur
  gelesen und bewusst nicht ausgeliefert, genau wie die sechs
  `kjr.privacy.*`-Parameter. Ist er leer, steht dort „im Einzugsgebiet". Der
  enge Adressatenkreis selbst bleibt unverändert, er ist eine Zusage aus dem
  Website-Termin vom 23.07.2026.
- **Kategorie-Icons geprüft und geschärft.** Zelte stehen nicht mehr unter einem
  Haus (`fa-bed` statt `fa-home`), Technik nicht mehr unter einem
  Lautstärkeregler (`fa-sliders` statt `fa-volume-up`, deckt Ton und Licht ab),
  und „Sonstiges" hat überhaupt erst ein Icon (`fa-cube`). Der Beispielartikel
  „Gruppenzelt" läuft mit seiner Kategorie mit. Der Spielmobil-Teaser auf der
  Katalogseite zeigt einen Anhänger statt eines Busses (`fa-truck`, im Gleichlauf
  mit dem Artikel).
- **Die Katalogrubrik für Artikel ohne Kategorie heißt jetzt „Ohne Kategorie".**
  Der Katalog gruppiert nach `item.category_id`; für einen veröffentlichten
  Artikel ohne Kategorie ist der Schlüssel ein leeres Recordset, und die
  Überschrift fiel auf den Literaltext „Sonstiges" zurück. Weil es eine
  gleichnamige Seed-Kategorie gibt, standen damit zwei Blöcke mit derselben
  Überschrift untereinander, einer mit Symbol und einer ohne. Die Rubrik hat
  jetzt einen eigenen Namen und dasselbe `fa-cube` wie `cat_other`.
- **App-Icon und Portalsymbol neu gezeichnet.** Das App-Icon war bisher eine
  leere orange Fläche ohne Motiv, 140 x 140 Pixel groß. Es zeigt jetzt den
  Anhänger mit Zugdeichsel und kommt mit 256 x 256 Pixeln aus dem
  Icon-Generator des Repos (`tools/icons/build_icons.py`, `motiv_rental`), wie
  die Icons der fünf Schwestermodule auch. Damit ist die Datei auf einem
  HiDPI-Bildschirm scharf, sie passt in die Icon-Familie und der nächste Lauf
  des Generators erzeugt sie unverändert wieder, statt sie zu überschreiben. Ein
  zwischenzeitlich von Hand gezeichnetes Kistenmotiv wurde dafür aufgegeben; der
  Generator ist die einzige Quelle der sechs Icons.
  `static/src/img/verleih.svg` zeigt dasselbe Motiv (bisher ein modulfremdes
  Türkis).
  - **Die Palette der Icon-Familie ist Navy `#1B3A6B` mit Orange `#E8952E`:**
    weißer Kasten auf Navy, Deckelband im Orange. Die zwischenzeitlich im
    Generator stehenden Aubergine-Töne `#714B67` / `#5E3F56` waren im Repo durch
    nichts gedeckt und widersprachen dem, was die Module im Frontend zeigen
    (`kjr_facility/static/src/css/facility.css`, der Rückfallwert in
    `rental.css`, die Slogan-Zeilen der `index.html`). Zwei der drei
    Aubergine-Töne lagen außerdem nur 1,25:1 auseinander und waren am Icon nicht
    zu unterscheiden. Gemessen jetzt: Weiß auf Navy 11,3:1, Orange auf Navy
    4,7:1, beides über den 3:1 aus WCAG 1.4.11 für bedeutungstragende Grafik.
    *Offen:* `static/src/img/verleih.svg` trägt noch `#5E3F56` und gehört bei
    der nächsten Gelegenheit auf dieselbe Palette gezogen.
  - **Das neue Bild erreicht die App-Leiste nur über ein Modul-Update.**
    `views/menu.xml` setzt `web_icon` am Wurzelmenü, und
    `ir.ui.menu.web_icon_data` ist ein gespeichertes Feld, das Odoo nur in
    `create()`/`write()` neu aus der Datei liest
    (`odoo/addons/base/models/ir_ui_menu.py`). In der Apps-Übersicht
    (`icon_image`, nicht gespeichert) erscheint es sofort. Ohne die
    Versionsanhebung dieser Lieferung stünden auf einer Bestandsinstanz altes
    und neues Icon nebeneinander.
- **Kartenakzente kommen aus dem Theme.** `rental.css` nutzt `var(--bs-primary)`
  statt der festen Hausfarbe, mit dem bisherigen Wert als Rückfall.
- **Interne Arbeitsnotizen aus den sichtbaren Feldhilfen entfernt.** Die
  TODO-Marken in fünf Tooltips des Artikelmodells und der Hinweis im Infokasten
  der Mengenstaffel stehen jetzt als Kommentar im Quelltext; die Sachaussage
  bleibt im Tooltip.
- **Restliche Gedankenstriche aus kundenseitigen Texten entfernt** (Überschrift
  des Verleihvertrags, Leerwerte in Tabellen, Zeitraumangaben, Bezeichnungen der
  Rechnungszeilen, Fehler- und Hinweismeldungen). Der Durchgang 19.0.5.3.0 hatte
  Report, Backend-Hilfetexte und Chatter-Meldungen ausgenommen.

### Dokumentiert
- **Odoo 19 liefert FontAwesome 4.7.0 aus**, nicht 5 oder 6
  (`addons/web/static/src/libs/fontawesome/css/font-awesome.css`). `fa-futbol-o`
  und `fa-cutlery` sind daher korrekt und bleiben; die FA-5/6-Namen `fa-futbol`
  und `fa-utensils` existieren dort nicht und würden als leerer Kasten rendern.
  Der Hinweis steht als Kommentar über den Seed-Kategorien und in den beiden
  Feldhilfen zum Icon.
- **Die Barrierefreiheitsprüfung von Odoo läuft nicht auf Website-Vorlagen**
  (`ir.ui.view._check_xml` überspringt `type == 'qweb'`). Die Icons der
  Website-Vorlagen sind deshalb von Hand geprüft; genau eines (`fa-arrow-left`
  im Zurück-Link der Detailseite) hatte kein `aria-hidden`. In den Backend-Views
  gab es keinen Verstoß.
- **Das Portalsymbol ist in Odoo 19 sichtbar.** `portal.portal_docs_entry` legt
  es zwar in `<div class="o_portal_icon d-none">`, die mitgelieferte Vorlage
  `portal.portal_docs_entry_layout` („Use Pictograms",
  `addons/portal/views/portal_templates.xml`) ist aber mit `active="True"`
  ausgeliefert und ersetzt das `d-none` durch `d-block align-self-start`. Die
  Kachel „Meine Ausleihen" unter `/my` zeigt `verleih.svg` also genauso wie die
  Kernkacheln (`portal-addresses.svg`, `portal-connection.svg`); die Gestaltung
  der Datei ist kundensichtbar und gehört mitgeprüft. Eine eigene Regel zu
  `o_portal_icon` bleibt trotzdem falsch: sie wäre überflüssig, und weil es eine
  Kernklasse ist, träfe sie die Kacheln aller Module. (Korrigiert die
  gegenteilige Behauptung, die zwischenzeitlich hier und als Kommentar in
  `views/website_templates.xml` stand.)

### Getestet
- Neue Datei `tests/test_seed_data.py`: alle ausgelieferten Kategorien tragen
  ein Icon, das mit `fa-` beginnt, und die ausgelieferte Stammdatendatei nennt
  keinen Kunden- oder Ortsnamen (die drei historischen XML-IDs ausgenommen).
- Beide Zusicherungen lesen die AUSGELIEFERTE Datei
  (`data/kjr_rental_data.xml`), nicht den Zustand der Instanz. Der Icon-Test
  griff zunächst über `env.ref` auf die lebenden Datensätze zu und wäre damit
  rot geworden, sobald die Geschäftsstelle ein Icon leert oder anders schreibt.
  Das ist ausdrücklich erlaubt: `icon` ist optional, die Sätze stehen unter
  `noupdate="1"`, und das Migrationsskript lässt gepflegte Werte bewusst stehen.
  Ein Upgrade darf daran nicht scheitern.

### Hinweis zum Upgrade
- Die Stammdaten stehen unter `noupdate="1"`. Das Skript
  `migrations/19.0.5.5.0/post-migration.py` zieht die neuen Lagerortnamen und
  die vier Icon-Korrekturen in Bestandsinstanzen nach, aber nur dort, wo noch
  der unveränderte Auslieferungswert steht. Von Hand gepflegte Werte bleiben
  unangetastet, jede Änderung wird protokolliert. Ohne dieses Skript bliebe der
  Ortsbezug auf der Bestandsinstanz stehen. Der Icon-Test hängt nicht daran, er
  prüft die ausgelieferte Datei.

## 19.0.5.4.1 (2026-09-10)

- Abstand zwischen Label und Wert im Datenschutzblock.

## 19.0.5.4.0 (2026-09-10)

- **Die Angaben im Datenschutzblock kommen jetzt aus der Konfiguration.** Bisher
  standen dort feste Platzhalter „wird vom KJR ergänzt", die kein Kunde füllen
  konnte, ohne die Vorlage zu ändern, und deren Änderung jedes Modulupdate wieder
  überschrieben hätte.
- Gelesen werden sechs Systemparameter: `kjr.privacy.operator`,
  `kjr.privacy.controller`, `kjr.privacy.dpo`, `kjr.privacy.legal_basis`,
  `kjr.privacy.retention`, `kjr.privacy.authority`.
- Ist ein Parameter leer, bleibt der bisherige Warnhinweis stehen. Nichts
  verschwindet unbemerkt.

## 19.0.5.3.0 — Gedankenstriche in den Verleihtexten (M2 aus dem Fehlerbericht 30.08.2026)

### Geändert
- **9 Gedankenstriche aus den kundenseitigen Texten entfernt** (Katalogkopf,
  Preishinweis, Mitgliedstarif-Hinweis, Spielmobil-Teaser, Zweck-der-Nutzung-Feld,
  Datenschutzhinweise der Anfrage, Kautionsabschnitt der Bestätigung). Der
  eingeschobene Halbsatz im Fließtext ist jeweils zu einem eigenen Satz oder zu einem
  Komma-Einschub aufgelöst, der Wortlaut bleibt sonst gleich.
- Bewusst **nicht** angefasst: Bereichsangaben (`Zeitraum ... – ...`), der Strich als
  Leerwert in Tabellen und Auswahlfeldern, Überschriften und die Textbausteine der
  Datenschutzerklärung. Ebenso bleiben Hilfetexte im Backend unverändert, der Bericht
  zielt auf die Texte, die Verbände und Ehrenamtliche lesen.

### Dokumentiert
- **M4 Sequenz-Präfix bleibt `VL/`.** Im Bestand des KJR stehen Ausleihen als
  `AL/2026/...`. Diese Nummerierung ist gewachsene Kundendatenlage und keine Erfindung
  des Moduls, ein Wechsel im Code würde die laufende Folge brechen. Die Begründung
  steht als Kommentar in `data/ir_sequence_data.xml`.

## 19.0.5.2.0 — Warenkorb wieder benutzbar (Fehlerbericht 30.08.2026)

### Behoben
- **Warenkorb warf bei jedem Hinzufügen `AttributeError` (Odoo-19-Regression).**
  `request.session.modified = True` war bis Odoo 18 der übliche Weg, eine Session als
  geändert zu markieren. In Odoo 19 nutzt `Session` `__slots__` — neue Attribute
  lassen sich nicht mehr setzen, die Zuweisung wirft. Die Zeile ist ersatzlos
  gestrichen: `Session.__setitem__` setzt `is_dirty` selbst, sobald sich der Wert
  ändert, und `_get_cart()` liefert dafür eine frische Liste (echter Wertvergleich,
  keine Selbstzuweisung des mutierten Objekts).
- **Fehler wurden mit HTTP 200 beantwortet.** `type='json'` ist in Odoo 19 nur noch
  ein veralteter Alias auf `jsonrpc`; der beantwortet auch Ausnahmen mit 200 und legt
  den Fehler nur in den Rumpf. Ein abgestürzter Warenkorb sah im Zugriffsprotokoll
  wie ein Erfolg aus. `/service/verleih/cart/add` läuft jetzt über `type='json2'` und
  liefert echte Statuscodes (400 bei ungültiger Eingabe, 404 bei unbekanntem Artikel,
  500 bei unbehandelten Ausnahmen).
- **`alert()` als Fehlerausgabe ersetzt.** Der Dialog blockierte die ganze Seite,
  erzeugte keine Konsolenausgabe und war für jede Automatisierung unsichtbar. Die
  Meldung erscheint jetzt im Seiteninhalt (`role="alert"`, `aria-live`).
- **Zwei sichtbare Platzhalter auf `/service/spielmobil` entfernt.** „Was ist dabei?"
  und „Voraussetzungen vor Ort" zeigten öffentlich ein gelbes Etikett
  „Platzhalter – Text vom KJR zu ergänzen". Die Abschnitte bleiben weg, bis die
  Geschäftsstelle Text liefert — gleiche Linie wie beim Kostenblock, der ohne
  freigegebene Preise ebenfalls stumm bleibt. Was hineingehört, steht als Kommentar
  an der Stelle.

## 19.0.3.0.0 — Barcode, Nutzungshinweise, Rückgabeprotokoll, Spielmobil

### Neu
- **Barcode / Inventaretikett** am Artikel inkl. Etikettenreport (Code128 über den
  Kern-Endpunkt `/report/barcode/`) und Suche nach Barcode und Inventarnummer.
  Bewusst **ohne** die Abhängigkeit `stock` (ADR-1). Ein gescannter Code landet im
  Suchfeld und findet den Artikel; der volle Kamera-Scan der Odoo-App setzt
  `stock_barcode` (Enterprise) voraus — das wäre eine eigene Entscheidung.
- **Nutzungshinweise** je Artikel (`usage_warning`), die vor dem Absenden angezeigt
  und verbindlich bestätigt werden müssen (`usage_terms_accepted`). Als
  eingeblendeter Block, nicht als Popup — ein Popup können Werbeblocker unterdrücken
  und Screenreader überspringen, der Hinweis wäre dann wertlos.
- **Zweck der Nutzung** als Pflichtfeld im Formular (§§ 11/12 SGB VIII) — die
  Nutzungsberechtigung war bisher weder dokumentiert noch auswertbar.
- **Rückgabeprotokoll**: vollständig / gereinigt / Schaden + Vermerk, mit
  Chatter-Protokoll. Jede Abweichung verlangt einen Vermerk, aber die Rückgabe ist
  auch bei Mängeln abschließbar — sonst müsste das Personal falsch ankreuzen.
- **Spielmobil-Infoseite** `/service/spielmobil` mit Anfrageformular. Adressatenkreis
  laut Entscheidung 23.07.2026 ausdrücklich **nur Gemeinden im Landkreis Oberallgäu**;
  die Anfrage geht zusätzlich per Mail an das KJR-Postfach (Systemparameter
  `kjr_rental.spielmobil_notify_email`, sonst Firmen-E-Mail).
- **Fotos im Katalog** (`image_1920`) mit Icon-Fallback.
- `res.partner.is_kjr_member` — namensgleich zu `kjr_grant`, damit beide Module sich
  eine Spalte teilen und `kjr_rental` trotzdem eigenständig lauffähig bleibt.

### Geändert
- **Mitgliedstarif wird abgeleitet** statt manuell gesetzt: `is_member` kommt aus
  `partner_id.is_kjr_member` (überschreibbar). Bisher wurde er weder im Checkout noch
  bei der Direktanfrage gesetzt — jede Online-Anfrage rechnete zum Standardtarif und
  musste von Hand korrigiert werden.
- Eindeutigkeit von Inventarnummer und Barcode wird erzwungen.
- Der Katalog nennt den Mitgliedstarif nur noch, wenn er am Artikel aktiviert ist.

### Behoben
- **Anonyme Anfragen konnten eine fremde Identität übernehmen**: Die öffentliche
  Route ordnete den Absender per E-Mail-Suche einem *bestehenden* Kontakt zu. Wer die
  Adresse eines Mitgliedsverbands kannte, erzeugte auf dessen Namen einen Vorgang —
  inklusive Mitgliedstarif und sichtbar in dessen Portal. Nicht angemeldete Absender
  bekommen jetzt immer einen neuen, als ungeprüft markierten Kontakt und den
  Standardtarif.
- Die Preise fakturierter Ausleihen konnten sich nachträglich noch ändern (der
  Einfrier-Schutz hing am Status statt an der Rechnung).

## 19.0.2.3.0

### Neu
- **301-Weiterleitungen** der alten `/kjr/…`-Pfade auf `/service/…`
  (`/kjr/verleih`, `/kjr/verleih/warenkorb`), damit bereits geteilte/indexierte alte Links nicht ins Leere laufen.
  Eigene Controller-Datei `controllers/legacy_redirects.py` (nur GET-Landingpages).

## 19.0.2.2.0

### Geändert
- **Öffentlicher URL-Präfix `/kjr/…` → `/service/…`** umbenannt, damit die Seiten
  ins Webseiten-Corporate-Design/-Menü eingebunden werden können. Betroffen:
  `/service/verleih` (+ `/warenkorb`, `/cart/add`, `/checkout`, `/anfrage`).
  Portal-Routen unter `/my/…` bleiben unverändert (Odoo-Standard).
  Hinweis: Das Website-Menü ist `noupdate` – bei einem **Bestandsupgrade** muss der
  Menü-Link einmalig manuell auf `/service/…` gesetzt werden; Frischinstallationen
  übernehmen die neue URL automatisch.

## 19.0.2.0.0

### Neu
- **Website-Warenkorb / Sammelbestellung (R1):** Session-basierter Warenkorb
  (`request.session['kjr_rental_cart']` als Liste `{item_id, qty}`).
  Neue Routen:
  - `/kjr/verleih/cart/add` (type=json, POST, auth=user) – Artikel hinzufügen.
  - `/kjr/verleih/warenkorb` (auth=user) – Anzeige, Mengenänderung, Entfernen,
    Zeitraumwahl und Live-Verfügbarkeit (`item.quantity_available(date_from, date_to)`).
  - `/kjr/verleih/checkout` (POST, auth=user) – legt EINEN `kjr.rental.order`
    mit allen Positionen an.
  Katalog bleibt öffentlich; Warenkorb/Anfrage nur für eingeloggte Nutzer
  (Login-Hinweis für öffentliche Besucher). Frontend-JS `static/src/js/cart.js`.
- **Robustere Verfügbarkeit (R2):** `quantity_available()` kann optional `draft`
  als Soft-Reserve einbeziehen (Systemparameter `kjr_rental.reserve_draft`,
  konfigurierbar). Neues Feld `available_in_period` auf der Ausleihposition
  (Spalte „Verfügbar im Zeitraum"). Verfügbarkeits-Recheck bei nachträglicher
  Mengen-/Datumsänderung bleibt erhalten.
- **Abschreibung (R3):** Felder am Artikel `purchase_value`, `purchase_date`,
  `useful_life_years`, `salvage_value` und berechneter `book_value`
  (lineare Abschreibung auf heute, nie unter Restwert; `store=False`, da
  `today()`-abhängig). Keine Nutzung von Enterprise `account_asset`.
- **Inventur (R3):** Neue Modelle `kjr.rental.inventory` (Jahr, state draft/done)
  und `kjr.rental.inventory.line` (item_id, qty_expected, qty_counted, condition,
  scrap). Aktionen „Inventur eröffnen" (kopiert aktive Artikel) und „abschließen"
  (schreibt Ausschuss auf `quantity_total`/`active` zurück). Security, Views, Menü.
- **Auto-Rechnung bei Rücknahme (B-cross-1):** Schalter
  `kjr_rental.auto_invoice_on_return`; `action_return` erstellt und postet bei
  Bedarf automatisch die Rechnung.
- **Zahlungsstatus (B-cross-2):** `invoice_payment_state`
  (`related=invoice_id.payment_state`, store) mit Filtern und Badges.
- **Kaution-Lebenszyklus (B-cross-3):** `deposit_state`
  (none/received/refunded/withheld) plus `deposit_received_date`/
  `deposit_refund_date` und Buttons `action_register_deposit`,
  `action_refund_deposit`, `action_withhold_deposit`.

### Korrekturen (Bugs)
- Rechnungszeilen verwenden jetzt das Service-Produkt „Verleihgebühr"
  (`product.product`) mit `quantity*price_unit` statt einer Zeile ohne
  `product_id`/Steuer – korrekte Steuer- und Kontenfindung.
- Website-Bestellungen setzen `company_id` explizit aus
  `request.website.company_id` (Katalog/Anfrage/Checkout).
- Verfügbarkeits-Race über optionale Draft-Soft-Reserve adressiert.

### Service-Produkte / Konfiguration
- Data: Service-Produkte „Verleihgebühr" und „Kaution".
- Systemparameter `kjr_rental.reserve_draft` und
  `kjr_rental.auto_invoice_on_return` (Default `False`).
