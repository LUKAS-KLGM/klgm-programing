# Ferienprogramm Termin 13.10.2026 (`tools/ferienprogramm_t1013`)

Skripte für Daten auf der Produktivinstanz, die nicht im Modulcode liegen.
Alle laufen als Odoo-Shell-Skript, Standard ist ein Probelauf ohne Änderung.

> **Ausführen darf das nur eine berechtigte Person** (Administration der
> Instanz), zuerst auf einer Server-Kopie, dann nach Snapshot und Freigabe
> durch den KJR auf der Produktion. **Nicht durch den Assistenten**, nicht
> lokal.

- `kjr_event_questions_t1013.py`: alte Veranstaltungsfragen durch die
  Standardfragen ersetzen (Beschreibung im Kopf der Datei).
- `testauftraege.py`: Test-Aufträge in Veranstaltung 56 stornieren (unten).

## Test-Aufträge S00001, S00004 bis S00006 (Veranstaltung 56)

**Befund (Prüfbericht 22.10.2026):** Die Aufträge S00001, S00004, S00005 und
S00006 stammen aus KLGM-Tests. Sie stehen auf „gesendet“ mit offener
Überweisung. Ihre Anmeldungen in der veröffentlichten Veranstaltung 56
„Selbstbehauptung für Mädchen und Jungen“ (Beginn 03.11.2026) halten als
unbezahlte Reservierung 5 von 10 Plätzen frei. Schaltet der KJR den Cron für
Zahlungserinnerung und Platzfreigabe ein, bekämen sie außerdem eine
Erinnerung.

**Werkzeug:** `testauftraege.py`. Es listet die Aufträge mit Überweisungen und
Anmeldungen sowie zur Information alle weiteren nicht abgesagten Anmeldungen
der Veranstaltung. Im Schreiblauf storniert es die Aufträge über das ORM
(`sale.order._action_cancel`, keine Mail an Kund:innen), setzt offene
Überweisungen auf „abgebrochen“ (`payment.transaction._set_canceled`) und
prüft, dass die Anmeldungen abgesagt sind. Übersprungen wird jeder Auftrag
ohne Zeile zur Veranstaltung, mit anderem Status als Warenkorb/gesendet oder
mit erledigter Zahlung.

### Schritte

1. **Freigabe des KJR einholen** (Schreibvorgang auf Produktion) und
   **Snapshot bei CloudPepper anlegen**.
2. **Probelauf:**

   ```
   odoo shell -d <db> --no-http < testauftraege.py
   ```

   Weitere Startparameter (`-c <konfig>`, Addons-Pfad) wie beim normalen
   Serverstart der Instanz.
3. **Ausgabe prüfen:** Je Auftrag Status, Betrag, Überweisungen und
   Anmeldungen (ID, Name, Status) und am Ende „wird im Schreiblauf storniert“
   oder „übersprungen: Grund“. Unter „Weitere nicht abgesagte Anmeldungen“
   stehen Anmeldungen der Veranstaltung ohne diese Aufträge; sie werden NICHT
   geändert (Test-Entwürfe dort bei Bedarf von Hand absagen).
4. **Schreiben:**

   ```
   KJR_FIX_WRITE=1 KJR_FIX_OUT=/root/kjr_backup odoo shell -d <db> --no-http < testauftraege.py
   ```

   Zuerst entsteht `testauftraege_backup_<zeit>.json` (Aufträge, Zahlungen,
   Anmeldungen mit Status). Danach stehen die Aufträge auf „storniert“, die
   Anmeldungen auf „abgesagt“, und die Zeile „Veranstaltung 56 danach“ zeigt
   die freigegebenen Plätze.

Optionen: `KJR_ORDERS=S00001,S00004` (andere Auswahl), `KJR_EVENT_ID=<id>`.

### Rückweg

Snapshot zurückspielen. Einzelne Aufträge lassen sich im Backend über
„Auf Angebot setzen“ wieder öffnen; Status und Beträge stehen im Backup.

### Getestet

Auf einer Kopie der Produktionsdatenbank (n2_night, 22.10.2026): Probelauf
und Schreiblauf, Ergebnis im Abschlussbericht der Nachtarbeit.
