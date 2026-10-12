# Website-Korrekturen (`tools/website_fixes`)

## Befund A: `<br/>` als vorausgefüllter Text in Formular-Textfeldern

**Symptom:** In einem Website-Formular steht im mehrzeiligen Textfeld
(`<textarea>`) schon beim Laden der Text `<br/>` (bzw. eine leere Zeile).
Besucher müssen ihn erst löschen; wird er mitgeschickt, steht er im erzeugten
Datensatz.

**Ursache:** Im gespeicherten Seiteninhalt (`ir_ui_view.arch_db`, eine Fassung
je Sprache) enthält die `<textarea>` nur ein `<br>`-Element bzw. nach einem
erneuten Speichern den escapten Text `&lt;br/&gt;`. Der Browser zeigt den
Inhalt einer Textarea als Vorbelegung.

**Werkzeug:** `fix_textarea_br.py` (Odoo-Shell-Skript). Es sucht die
betroffenen Ansichten nur lesend per SQL, parst jede Sprachfassung mit lxml und
schreibt ausschließlich über das ORM (Validierung, Caches, Übersetzungen).
Standard ist ein Dry-Run.

> **Ausführen darf das nur eine berechtigte Person** (Administration der
> Instanz), auf dem Server bzw. zuerst auf einer Server-Kopie. **Nicht durch
> den Assistenten**, nicht lokal und nicht ohne Snapshot.

### Schritte

1. **Snapshot bei CloudPepper anlegen.** Vor jedem schreibenden Lauf einen
   Snapshot bzw. ein Backup von Datenbank und Filestore erstellen und notieren,
   wie er zurückgespielt wird. Ohne Snapshot nicht weitermachen.

2. **Dry-Run** (schreibt nichts, rollt am Ende zurück):

   ```
   odoo shell -d <db> --no-http < fix_textarea_br.py
   ```

   Weitere Startparameter (`-c <konfig>`, Addons-Pfad) wie beim normalen
   Serverstart der Instanz.

3. **Ausgabe prüfen.** Je Treffer erscheinen Ansichts-ID, technischer
   Schlüssel (`key`), Name, `website_id`, aktiv ja/nein, die zugehörigen
   Seiten-URLs, die betroffenen Sprachen und je Textarea `name`, `id` und der
   gefundene Inhalt. Plausibel ist: nur `<br/>`-Inhalte, nur Formularseiten,
   die bekannt betroffen sind. Bei Unerwartetem (andere Seiten, „nicht
   parsebar", sehr viele Treffer) hier abbrechen und klären.

4. **Schreiben** mit `KJR_FIX_WRITE=1`:

   ```
   KJR_FIX_WRITE=1 odoo shell -d <db> --no-http < fix_textarea_br.py
   ```

   Das Skript schreibt je Sprache (Quellsprache `en_US` zuerst), liest danach
   roh nach und meldet `noch betroffen: keine`. Erst dann wird committet.
   Steht dort eine Sprache, ist sie NICHT korrigiert: Schritt 5 und ggf. 6.

5. **Seitenquelltext je Sprache prüfen.** Jede betroffene Seite in jeder
   aktiven Website-Sprache öffnen (z. B. `/kontakt` und `/en/kontakt`),
   Quelltext anzeigen (Strg+U) und nach `<textarea` suchen: zwischen
   öffnendem und schließendem Tag darf nichts stehen, weder `<br` noch
   `&lt;br`. Zusätzlich im privaten Fenster (nicht angemeldet) prüfen und
   einmal ein Testformular absenden.

6. **Alternative im Website-Builder** (für Einzelfälle oder wenn das Skript
   eine Sprache nicht korrigiert): Seite im Editor öffnen, das Textfeld
   anklicken, in den Feldoptionen den Vorgabewert („Standardwert") leeren bzw.
   das Feld löschen und neu aus dem Formularbaustein einfügen, speichern. Für
   jede Sprache über den Sprachumschalter des Editors wiederholen und danach
   Schritt 5 durchführen.

7. **Sonderfall HTML-Feld.** Steht das Formular nicht in einer Website-Seite,
   sondern im Inhalt eines Datensatzes (z. B. Beschreibung einer Veranstaltung,
   `event.event.description`), findet das Skript es NICHT (es bearbeitet nur
   `ir.ui.view`). Betroffene Veranstaltungen nur lesend auflisten:

   ```
   KJR_FIX_SCAN_HTML=1 odoo shell -d <db> --no-http < fix_textarea_br.py
   ```

   Ausgegeben werden nur die IDs. Korrigiert wird von Hand: die Veranstaltung
   auf der Website im Editor öffnen und wie in Schritt 6 verfahren (je
   Sprache), danach Schritt 5. Der Lesemodus schreibt nie, auch nicht
   zusammen mit `KJR_FIX_WRITE=1`.

8. **Vorbeugung.**
   - In den Feldoptionen mehrzeiliger Textfelder keinen Vorgabewert eintragen;
     Hinweise gehören in den Platzhalter oder die Beschriftung.
   - Keinen formatierten Text (aus Word, E-Mails, anderen Seiten) in
     Formularfelder des Editors einfügen.
   - Nach jeder Bearbeitung eines Formulars Schritt 5 für diese Seite
     durchführen.
   - Nach Odoo-Updates und nach dem Übersetzen einer Seite einen Dry-Run
     (Schritt 2) laufen lassen; er ändert nichts und zeigt neue Fälle sofort.

### Rückweg

Ist nach dem Schreiben etwas falsch, den Snapshot aus Schritt 1 zurückspielen.
Einzelne Ansichten lassen sich im Backend (Einstellungen > Technisch >
Ansichten, Entwicklermodus) nicht verlässlich „zurückdrehen", deshalb ist der
Snapshot Pflicht.
