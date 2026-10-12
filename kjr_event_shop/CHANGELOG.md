# Changelog — KJR Brücke: Veranstaltungen ↔ Shop (`kjr_event_shop`)

## 19.0.2.1.0 (2026-10-12)

Einwilligungs-Sperre aus `kjr_event` 19.0.5.9.0 für Anmeldungen, die über den
Shop (Verkaufsauftrag) laufen.

### Neu

- **Status-Compute kennt die Sperre.** `event.registration._compute_registration_status`
  hängt zusätzlich an `kjr_consent_hold` und ruft zuerst den Standard auf. Eine
  gesperrte Anmeldung bleibt unbestätigt, auch wenn der Auftrag bestätigt oder
  kostenlos ist. Nach der Freigabe entscheidet event_sale wie gewohnt:
  kostenlos oder verkauft wird registriert (Kern-Mails genau einmal), zu
  bezahlen bleibt unbestätigt. Ein unbezahlter Auftrag wird durch die
  Einwilligung also nie freigegeben. Wartelistenplätze (`kjr_is_waitlist`,
  ebenfalls Abhängigkeit) bleiben unbestätigt, auch wenn die Sperre fällt oder
  der Auftrag bestätigt wird; registriert werden sie nur über „Von Warteliste
  nachrücken".
- **Unterschriftsanfrage erst nach dem Checkout.** Solange der Auftrag ein
  Warenkorb ist, wird die Anfrage an die Erziehungsberechtigten zurückgestellt
  (`_kjr_consent_defer_request`). Wechselt der Auftrag auf „gesendet" oder
  „Auftrag", startet sie (`sale.order.write`). Abgebrochene Warenkörbe erzeugen
  damit weder eine Anfrage noch einen Kontakt der Erziehungsberechtigten.
  Abgesagte Anmeldungen sind ausgenommen (gleiche Auswahl wie
  `_kjr_consent_releasable()` in `kjr_event`): wird eine gesperrte Anmeldung im
  Warenkorb oder Angebot abgesagt, geht nach Bestätigung oder Zahlung des
  Auftrags keine Unterschriftsanfrage an die Erziehungsberechtigten.
- **Keine Einwilligungs-Erinnerung aus dem Warenkorb.** Die Auswahl der
  Erinnerung (`_kjr_consent_reminder_domain`) schließt gesperrte Anmeldungen
  aus, deren Auftrag noch ein Warenkorb ist. Abgebrochene Warenkörbe lösen auch
  über die Erinnerung keinen Kontakt zu den Erziehungsberechtigten aus.
- **Feste Reihenfolge der Anmelde-Controller.** `KjrEventShopController` erbt von
  `KjrWebsiteEventController` (kjr_event) und `WebsiteEventSaleController`
  (website_event_sale) und ist damit das einzige Blatt beider Linien. Die
  KJR-Vorprüfung läuft immer vor dem Warenkorb, die KJR-Angaben werden danach
  geschrieben (Begründung im Kopf von `controllers/main.py`).
- **Hinweis auf der Bestellbestätigung**, wenn Anmeldungen der Bestellung auf die
  Einwilligung warten (ohne Adresse und ohne Namen).

### Abgrenzung

- Die Portal-Unterschrift unter der Bestellung (`require_signature`, seit
  19.0.2.0.0) ist die **Vertragsannahme** der bestellenden Person. Die
  Einwilligung über Odoo Sign (`kjr_event_sign`) ist die **Erklärung der
  Erziehungsberechtigten** zur Teilnahme ihres Kindes. Beides ist unabhängig
  voneinander und ersetzt sich nicht.

### Hinweise zur Installation

- Setzt `kjr_event` 19.0.5.9.0 voraus (Felder und Methoden der Sperre).
- Auf der Server-Kopie prüfen: ob der Checkout mit Überweisung den Auftrag auf
  „gesendet" setzt (Auslöser der Anfrage), und dass die Basis von
  `_compute_registration_status` (event_product) vorhanden ist.
- Keine Datenänderung, keine Migration.

### Offen (Kundenentscheidung nötig)

- TODO(KJR): Erstattung, wenn bezahlt, aber nie unterschrieben.
- TODO(KJR): Icon dieses Moduls in `tools/icons/build_icons.py` aufnehmen.

## 19.0.2.0.0 (2026-10-11)

Rückblick (Commit e5f34b9).

- Angebots-PDF für Bestellungen mit Kursanmeldungen wird zur
  Reservierungsbestätigung (unbezahlt) bzw. Anmeldebestätigung (bezahlt): Kopf
  mit Reservierungsnummer, Datum und „Reserviert bis", Anrede, Kursname statt
  „Standard", Termin, Ort und Teilnehmende je Zeile, Zahlungshinweis mit
  Kontoinhaber, IBAN, BIC und Verwendungszweck bei offener Überweisung.
- Dateiname „Reservierungsbestätigung - S00005" (in allen Sprachen, da
  übersetzbar), Portal-Titel „Reservierung S00005".
- `/payment/status`: bei Überweisung wird die kurz aufblitzende Seite „Ihre
  Zahlung abschließen" ausgeblendet, nur Wartehinweis mit Link.
- Online-Unterschrift (E-Signatur) für Shop-Bestellungen mit Kursen wieder aktiv
  (website_sale schaltet sie ab); eine Migration berechnet offene Bestellungen
  neu.
- Bankverbindung als gemeinsame Hilfsfunktion auf `res.partner.bank`.

## 19.0.1.1.0 (2026-10-11)

- Kursbild in Bestellübersicht und Warenkorb statt des leeren Produktbilds.
- Bestellbestätigung mit Kursname, „Referenz" statt „Mitteilungen" und
  vollständiger Bankverbindung.
