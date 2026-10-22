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

## Befund B: Seitenfuß nach Entscheidung 10 (Termin 13.10.2026)

**Entscheidung:** Seitenübersicht und Kontaktblock raus, ein Link zur
Kontaktseite rein. Rechtliches (Impressum, Datenschutz, Cookies,
Barrierefreiheit) und Suche bleiben. Keine neue Gestaltung.

**Betroffen:** die website-eigene Ansicht `website.template_footer_mega_links`
(auf der Produktion `ir.ui.view` 4473, Website 3), Sprachfassungen `de_DE` und
`en_US` (derzeit identisch).

**Werkzeug:** `footer_2026-10.py` (Odoo-Shell-Skript). Es arbeitet je
Sprachfassung mit lxml auf der Struktur, nicht mit Textersetzung:

- entfernt die Rasterelemente „Seitenübersicht“ mit den drei Linkspalten und
  den Kontaktblock „BÜROS“,
- entfernt im Logo-Element alles hinter der mobilen Suche (Trennlinie und
  Kontaktblock „POSTADRESSE“),
- fügt dort einen Link `Kontakt` auf `/ueber-uns/contactus` im Stil der
  übrigen Fußlinks ein (`<p><a class="o_translate_inline">`),
- kürzt die Rasterhöhe der Logo-Spalte (16 auf 10 Zeilen) und die Zeilenzahl
  des Rasters (18 auf 10), damit unter dem Logo keine leere Fläche bleibt.

Logo, mobile Suche, Suche (Desktop), Spalte „Rechtliches“ und die
Copyright-Zeile bleiben unverändert. Weicht der Aufbau ab oder ist der Fuß
schon umgestellt, bricht das Skript ohne Änderung ab (zweiter Lauf ist also
harmlos).

> **Ausführen darf das nur eine berechtigte Person** (Administration der
> Instanz), auf dem Server bzw. zuerst auf einer Server-Kopie. **Nicht durch
> den Assistenten**, nicht lokal und nicht ohne Snapshot.

### Schritte

1. **Snapshot bei CloudPepper anlegen** (wie Befund A, Schritt 1).
2. **Dry-Run** (schreibt im Transaktionsrahmen, prüft, rollt zurück):

   ```
   KJR_FOOTER_OUT=/pfad/ablage odoo shell -d <db> --no-http < footer_2026-10.py
   ```

   Die Ausgabe nennt je Sprache die entfernten Blöcke und den eingefügten
   Link; die neue Fassung liegt als `footer_4473_<lang>_neu.xml` in der Ablage.
   Plausibel: fünf Rasterelemente entfernt, im Logo-Element „Kontakt |
   POSTADRESSE | …“ entfernt, „alle Sprachen geprüft, in Ordnung“.
3. **Schreiben:**

   ```
   KJR_FIX_WRITE=1 KJR_FOOTER_OUT=/pfad/ablage odoo shell -d <db> --no-http < footer_2026-10.py
   ```

   Vor dem Schreiben legt das Skript `footer_4473_backup_<zeit>.json` mit allen
   Sprachfassungen roh ab. Committet wird nur, wenn danach jede Sprache die
   Prüfung besteht.
4. **Startseite prüfen**, angemeldet und im privaten Fenster, am Rechner und
   am Handy: Fuß zeigt Logo, Suche, „Kontakt“ (führt auf die Kontaktseite) und
   „Rechtliches“ mit vier Links; keine Seitenübersicht, keine Anschriften.
   Bei sehr breiten Bildschirmen (über ca. 2200 px) prüfen, ob das Logo die
   Copyright-Zeile berührt; dann im Editor die Logo-Spalte im Raster um eine
   Zeile verlängern.

### Rückweg

Snapshot zurückspielen. Ohne Snapshot: die Backup-Datei aus Schritt 3 je
Sprache zurückschreiben (Odoo-Shell, `view.with_context(lang=…,
no_cow=True).write({'arch_db': …})`, `en_US` zuerst). Die Fassung vor der
Umstellung liegt zusätzlich im Vault unter `Data/Website-Backups/2026-10-22
footer vorher (ir.ui.view 4473) *.xml`.

### Getestet

Am 22.10.2026 auf einer Kopie der Produktionsdatenbank: Dry-Run, Schreiben,
zweiter Lauf (Abbruch „schon umgestellt“), Startseite über HTTP gerendert:
Fuß mit Links Kontakt, Impressum, Datenschutzerklärung, Cookie-Richtlinien,
Barrierefreiheit, beiden Suchfeldern und Logo; keine Anschriften, keine
Seitenübersicht. Auf der Produktion NICHT ausgeführt.
