# Verleih: doppelte Kategorien und Lagerorte

`bereinige_dubletten.py` räumt die doppelten Verleih-Kategorien (Altbestand ohne
XML-ID neben den Stammdaten mit XML-ID) und die alten Lagernamen „Lager
Sonthofen/Immenstadt/Oberstdorf“ auf. Alle übrigen Lagerorte listet es nur.

1. Snapshot der Datenbank.
2. Dry-Run auf einer Kopie, Ausgabe prüfen:
   `odoo-bin shell -c odoo.conf -d <kopie> --no-http < bereinige_dubletten.py`
3. Mit `KJR_FIX_WRITE=1` auf der Kopie ausführen, Katalog `/service/verleih` prüfen.
4. Erst danach auf Prod, durch eine berechtigte Person.

Regeln und Befund stehen im Kopf des Skripts.

## Reihenfolge der Kategorien („Sonstiges“ vor „Besteck“)

**Befund (Prod, lesend, 22.10.2026):** Kategorie 15 „Sonstiges“
(`kjr_rental.cat_other`, ausgeliefert mit `sequence` 99) steht auf
`sequence` 0, Kategorie 16 „Besteck“ auf 1. Beides hat admin am 13.10.2026 um
09:24 im Termin gesetzt. Katalog und Filterleiste beginnen deshalb mit
„Sonstiges“ (35 Artikel). Der Code ist richtig: Er sortiert nach `sequence`,
dann Name. Die Daten sind `noupdate`, ein Modul-Update ändert daran nichts.

**Zuständig ist der KJR:** Verleih > Konfiguration > Kategorien, Zeilen per
Ziehgriff sortieren. Fachlicher Hinweis: In „Besteck“ liegen auch Essteller,
Kaffeebecher und Kuchenteller, in „Sonstiges“ Geschirr, Töpfe und Spielgeräte.
Am besten ordnet der KJR die Kategorien zusammen mit der Artikelpflege neu.

**Werkzeug (optional):** `kategorie_reihenfolge.py` zeigt die Reihenfolge und
meldet Sammelkategorien („Sonstiges“, „Sonstige“, „Diverses“,
„Verschiedenes“), die vor anderen sichtbaren Kategorien stehen. Mit
`KJR_FIX_WRITE=1` setzt es sie auf das Ende (höchste andere `sequence` + 10,
mindestens 99) und sichert vorher alle `sequence`-Werte als JSON. Nur nach
Rücksprache mit dem KJR ausführen.

    odoo-bin shell -c odoo.conf -d <db> --no-http < kategorie_reihenfolge.py
    KJR_FIX_WRITE=1 odoo-bin shell -c odoo.conf -d <db> --no-http < kategorie_reihenfolge.py

Hinweis: Nach `bereinige_dubletten.py` verschwinden die leeren Dubletten 1–7;
`/service/verleih?kategorie=<alte ID>` leitet ab kjr_rental 19.0.5.8.1 auf
die Gesamtliste um.

Getestet am 22.10.2026 auf einer Prod-Kopie: Probelauf, Schreiblauf
(„Sonstiges“ 0 → 99, Sicherung angelegt), zweiter Lauf „Nichts zu tun“. Auf
Prod NICHT ausgeführt.
