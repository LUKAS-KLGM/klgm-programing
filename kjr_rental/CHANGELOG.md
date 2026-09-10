# Changelog – KJR Materialverleih

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
