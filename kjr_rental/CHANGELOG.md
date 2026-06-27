# Changelog – KJR Materialverleih

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
