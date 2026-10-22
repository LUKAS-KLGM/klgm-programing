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
