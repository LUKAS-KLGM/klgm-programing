# Changelog — kjr_facility_sign

## 19.0.1.0.0 (2026-10-12)

### Neu
- Buchungsvertrag per Odoo Sign digital unterschreiben: beim verbindlichen Buchen
  Unterschriftsanfrage statt Vertragsmail (Vertrags-PDF plus Unterschriftsseite mit Ort,
  Datum, Unterschrift). Unterschrift setzt „Vertrag unterschrieben“ (Datum, Quelle digital).
- Papierweg bleibt: Knopf „Vertrag liegt unterschrieben vor (Papier)“ storniert eine offene
  Anfrage. Das Häkchen „Vertrag unterschrieben“ von Hand gilt ebenfalls als Papierweg.
- Ablehnung/Ablauf: Notiz und Aufgabe für die Geschäftsstelle, im Namen des Absenders der
  Anfrage (nicht „Public user“, auch wenn über den Mail-Link abgelehnt wird). Storno/
  Zurücksetzen/Löschen der Buchung storniert offene Anfragen; täglicher Lauf storniert
  verwaiste Vertragsanfragen.
- Nur von der Brücke angelegte Vertragsanfragen (Kennzeichen „KJR-Buchungsvertrag“ an der
  Unterschriftsanfrage) wirken auf die Buchung. Andere Anfragen, die die Geschäftsstelle in
  Odoo Sign mit einer Buchung verknüpft (z. B. Hausordnung, Kautionsvereinbarung), bleiben
  unberührt, auch vom täglichen Lauf.
- Papierweg nach Ablehnung oder Ablauf: der Stand „Abgelehnt“/„Abgelaufen“ wird aufgehoben
  (Badge ausgeblendet, Stand „Storniert“).
- Einstellungen „KJR Einrichtungen: Vertrag digital unterschreiben“ (Standard AUS), pro
  Einrichtung abschaltbar. Portal: Hinweis und Link zur Unterschrift.
- Backend: Stand der Unterschrift als Badge, Smart-Button zur Anfrage, Knöpfe
  „Unterschrift anfordern“, „Unterschrift erneut anfordern“, „Unterschriftsanfrage
  stornieren“, Filter „Unterschrift ausstehend“.
- Schlägt das Anlegen der Anfrage fehl (z. B. keine E-Mail-Adresse, kein Absender), geht
  der Vertrag wie bisher als PDF per Mail hinaus und die Geschäftsstelle erhält eine Aufgabe.
- Die Unterschrift ändert den Buchungsstatus NICHT („Gebucht“ entsteht weiterhin mit
  „Verbindlich buchen“); Zahlung, Anzahlung und Rechnung bleiben unberührt.
- Quelle „Digital (Odoo Sign)“ nur, wenn die aktuelle Anfrage der Buchung tatsächlich
  unterschrieben ist; ein Kontextschalter allein (z. B. per RPC) zählt als Papierweg.
- Portal: der Link „Jetzt unterschreiben“ wird gegen den angemeldeten Betrachter
  (request.env.user) geprüft, nicht gegen den Benutzer des Datensatzes (der Portal-
  Controller liefert die Buchung als Superuser).
- Smart-Button „Unterschrift“: Sign-Benutzer ohne Leserecht auf die Anfrage (nicht
  Absender/Follower) erhalten einen klaren Hinweis statt eines Zugriffsfehlers.
- Begleittext der Sign-Mail verweist auf den Link (Odoo Sign hängt den Vertrag nicht an).
- Voraussetzung kjr_facility 19.0.7.4.0.
