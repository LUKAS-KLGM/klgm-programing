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

## Befund C: Editor-Kopie der Einrichtungsliste überdeckt den Modulcode

**Symptom:** `/service/einrichtungen` zeigt beim Zeltplatz „40 Betten“ (Symbol
Bett) statt „40 Plätze“, die Detailseite sagt richtig „40 Plätze“. Änderungen
am Modul-Template `kjr_facility.website_facility_list` kommen auf der Seite
nicht an.

**Ursache:** Live gibt es neben der Modul-Ansicht (ir_ui_view 3714, ohne
Website) eine website-spezifische Kopie (ir_ui_view 4332, `website_id=3`,
angelegt 27.06.2026 von admin). Odoo rendert für die Website immer die Kopie.
Beim Modul-Update gleicht Odoo eine Kopie nur ab, solange sie unverändert ist
(`ir.ui.view._load_records_write`). Diese Kopie ist geändert und bleibt deshalb
auf dem Modulstand vom August stehen.

**Lesender Vergleich vom 22.10.2026:** Die Kopie entspricht dem Modulstand
d51edc5 (16.08.2026) mit **einer Ausnahme**: Der Einleitungssatz wurde im
Editor ersetzt durch „Der Kreisjugendring Oberallgäu verfügt über ein
Jugendtagungshaus in Diepolz für insgesamt 42 Personen und einen
Jugendzeltplatz am Niedersonthofener See für bis zu 40 Personen.“ Das ist eine
erkennbare Inhaltsänderung. Das Skript löscht die Kopie deshalb im normalen
Schreiblauf **nicht**, es meldet nur.

**Werkzeug:** `reset_facility_list_copy.py` (Odoo-Shell-Skript).

1. Snapshot anlegen (wie Befund A, Schritt 1).
2. Probelauf: `odoo-bin shell -c odoo.conf -d <db> --no-http < reset_facility_list_copy.py`.
   Ausgabe: alle website-spezifischen Kopien von `kjr_*`-Ansichten, danach je
   Sprachfassung der Kopie entweder „entspricht Modulstand …“ oder die
   Unterschiede zur Modul-Ansicht (`-` Modul, `+` Kopie). Jede `+`-Zeile ist
   markiert: `[alter Modulstand]` (stand früher so im Modul) oder
   `[NICHT aus dem Modul: Inhaltsänderung im Editor]`.
3. Schreiblauf: `KJR_FIX_WRITE=1 …`. Gelöscht wird nur eine Kopie, die einem
   bekannten Modulstand entspricht (alle Sprachen), keine erbenden Ansichten
   und keine Seite hat. Vorher wird sie als JSON gesichert
   (`backup_ir_ui_view_<id>_<zeit>.json` im aktuellen Verzeichnis oder in
   `KJR_FIX_BACKUP_DIR`).
4. **Für die Live-Kopie 4332:** Mit dem KJR klären, ob der Einleitungssatz
   bleiben soll. Er nennt feste Zahlen (42/40 Personen), die bei Änderungen der
   Einrichtungen veralten; das Modul zeigt bewusst einen neutralen Satz und
   rendert die Zahlen aus den Stammdaten. Nach Zustimmung:
   `KJR_FIX_WRITE=1 KJR_FIX_FORCE=1 …` (sichert und löscht trotz
   Inhaltsänderung). Soll der Satz erhalten bleiben, danach im Website-Editor
   den Einleitungssatz neu eintragen; das legt wieder eine Kopie an, aber auf
   dem aktuellen Modulstand. Künftige Code-Änderungen an der Liste brauchen
   dann erneut diesen Ablauf.
5. Prüfen: `/service/einrichtungen` im privaten Fenster; der Zeltplatz zeigt
   „40 Plätze“ mit Personen-Symbol.

**Rückweg:** Snapshot oder
`KJR_FIX_RESTORE=<backup.json> KJR_FIX_WRITE=1 odoo-bin shell … < reset_facility_list_copy.py`
(spielt die Kopie mit derselben ID und allen Sprachfassungen zurück).

**Getestet** am 22.10.2026 auf einer Kopie der Produktionsdatenbank:
Probelauf und Schreiblauf (Kopie 4332 bleibt, Meldung der Inhaltsänderung),
`KJR_FIX_FORCE=1` (Sicherung + Löschung), `KJR_FIX_RESTORE` (Probelauf rollt
zurück, Schreiblauf stellt die Kopie bytegleich wieder her), unbedenklicher
Fall (Kopie = Modul-Ansicht → gesichert und gelöscht). Auf Prod NICHT
ausgeführt.

**Weitere website-spezifische Kopien von `kjr_*`-Ansichten auf Prod (lesend,
22.10.2026):**

| ID | Key | aktiv | Bewertung |
|----|-----|-------|-----------|
| 4332 | `kjr_facility.website_facility_list` | ja | siehe oben, überdeckt den Modulcode |
| 4334 | `kjr_grant.website_kjr_apply` | **nein** | Editor-Kopie vom 27.06. (admin), weicht vom Modul ab, ist aber archiviert und wird nicht gerendert. Kein Handlungsbedarf; bei Bedarf mit `KJR_FIX_KEY=kjr_grant.website_kjr_apply` prüfen. Nicht reaktivieren. |
| 4724 | `kjr_event.event_description_full_kjr_meeting_info` | ja | von Odoo automatisch angelegte Erb-Kopie unter der Editor-Kopie 4476 (`website_event.event_description_full`), identisch mit dem Modul, wird beim Update mitgezogen |
| 4725 | `kjr_event.opt_event_kjr_documents_block` | ja | wie 4724 |
| 4726 | `kjr_event.event_description_full_kjr_documents` | ja | wie 4724 |
| 4787 | `kjr_event.event_description_full_kjr_location` | ja | wie 4724 |

Hinweis zu 4476: Die Veranstaltungsseite selbst (`website_event.event_description_full`)
ist eine Editor-Kopie des Odoo-Standards. Die kjr_event-Erweiterungen hängen
sich korrekt daran, Änderungen am Odoo-Standard-Template kommen dort aber nicht
mehr an.

## Befund D: Sie-Form im Website-Code und Odoo-Standardseiten (Oktober 2026)

**Entscheidung 4 (13.10.2026):** Website- und Systemtexte siezen. Das Skript
`sie_form_2026-10.py` korrigiert nur Stellen, die KLGM selbst in die
Website-Daten gelegt hat, und nimmt Odoo-Mustertexte vom Netz. Die
Seiteninhalte des KJR mit ihr- bzw. du-Form ändert es nicht (Liste im Vault:
„KJR Seiten mit ihr-Anrede 2026-10“).

| Teil | Befund | Änderung |
|---|---|---|
| 1 | Der Fußbereich-Code (`website.custom_code_footer`, Website 3) enthält ein Skript, das Odoos Platzhalter „…müssen Sie optionale Cookies akzeptieren“ auf „…müsst ihr…“ umschreibt. | Nur dieser Skriptblock samt Kommentar wird entfernt. Der zweite Block (doppelter Cookie-Richtlinien-Link) bleibt. Odoo zeigt danach seinen eigenen Text in Sie-Form. |
| 2 | Cookie-Banner (`website.cookies_bar`, Ansicht 4546): „damit sie für euch besser funktioniert“ | Nur dieser Satz wird zu „damit sie für Sie besser funktioniert“, in allen Sprachfassungen. Klassen und Aufbau bleiben. |
| 3 | `/terms` (englische Odoo-Muster-AGB) und `/website/info` (Liste der installierten Apps) sind öffentlich und stehen in der `sitemap.xml`. | Je eine Weiterleitung vom Typ „404 Not Found“ für Website 3 (Website > Konfiguration > Weiterleitungen). Odoo nimmt die Route dann aus dem Routing, die Seite liefert 404 und fällt aus der Sitemap. Außerdem wird die Einstellung „Standard-Geschäftsbedingungen“ (`account.use_invoice_terms`) ausgeschaltet. Sonst schreibt Odoo in jeden neuen Auftrag „Terms & Conditions: …/terms“. Alle 6 bisherigen Aufträge tragen diesen Hinweis. Wer die Einstellung behalten will, setzt `KJR_KEEP_INVOICE_TERMS=1`. |
| 4 | Für Besucher:innen ohne Cookie-Zustimmung steht der Fußbereich-Code als `<html><head><script>…</script></head></html>` im `<body>`. | Der Code wird mit `<div class="d-none">…</div>` umschlossen (unsichtbar, das Skript läuft weiter). Danach steht er als `<div class="d-none"><script>…` am Ende des `<body>`. |

Am Ende löscht das Skript den zwischengespeicherten Sitemap-Anhang
(`/sitemap-3-*.xml`). Odoo baut ihn beim nächsten Aufruf neu. Nach dem Commit
ruft es `env.registry.signal_changes()` auf. Erst dann sehen die laufenden
Odoo-Prozesse die neuen Weiterleitungen und Vorlagen. Ohne diesen Aufruf
liefert die Website bis zum nächsten Neustart den alten Stand.

**Ursache von Teil 4:** Für Besucher:innen ohne Zustimmung zu optionalen
Cookies schickt Odoo den Code durch
`website._control_third_party_trackers_in_html`, also `lxml.html.fromstring`
und dann `tostring`. Besteht ein Fragment nur aus `<script>`, ordnet lxml es
dem `<head>` zu und gibt ein ganzes Dokument aus. Das ist Odoo-Verhalten. Der
Inhalt des Felds ist nicht fehlerhaft, die Umhüllung umgeht das Verhalten nur.
Beim `custom_code_head` (Seitenklassen, Logo für /freizeiten) passiert
dasselbe innerhalb von `<head>`. Dort darf kein `<div>` stehen. Die Browser
übergehen die doppelten Tags, das Skript läuft. Ein Fix ginge nur im Code (Override von
`_control_third_party_trackers_in_html`), er ist hier nicht enthalten.

**`/shop` bleibt unverändert.** Der Checkout des Ferienprogramms braucht die
Routen `/shop/cart`, `/shop/checkout` und `/shop/payment`. Odoo-konform aus der
Sitemap bekommt man `/shop` nur mit „E-Commerce-Zugriff: nur angemeldete
Benutzer:innen“ (`website.ecommerce_access = 'logged_in'`). Das sperrt aber
auch den Warenkorb für Gäste (Umleitung auf `/web/login`). Eine
404-Weiterleitung auf `/shop` entfernt nur diese eine URL. Die Sitemap-Funktion
läuft dann über `/shop/page/<n>` weiter und meldet eine URL, die 404 liefert.
Beides geht also nicht. Empfehlung: Zum Go-live in `robots.txt` (Website >
Konfiguration > Einstellungen > robots.txt) `Disallow: /shop` eintragen. Das
nimmt `/shop` und die Checkout-Seiten aus dem Crawling. Ganz aus der Sitemap
kommt `/shop` nur mit einer Code-Änderung (Override von `sitemap_shop` in
`kjr_event_shop`). Derzeit steht in `robots.txt` noch `Disallow: /`
(Staging), es wird also ohnehin nichts indexiert.

> **Ausführen darf das nur eine berechtigte Person** (Administration der
> Instanz), auf dem Server bzw. zuerst auf einer Server-Kopie. **Nicht durch
> den Assistenten**, nicht lokal und nicht ohne Snapshot.

### Schritte

1. **Snapshot bei CloudPepper anlegen** (wie Befund A, Schritt 1).
2. **Probelauf** (schreibt im Transaktionsrahmen, prüft, rollt zurück):

   ```
   KJR_FIX_OUT=/pfad/ablage odoo shell -d <db> --no-http < sie_form_2026-10.py
   ```

   Plausibel ist: „Teil 1: Skriptblock … entfernt (2661 -> 1088 Zeichen)“,
   „Teil 4: … umschlossen“, Ansicht 4546 de_DE/en_US „ändern“, zwei
   404-Weiterleitungen, `account.use_invoice_terms: 'True' -> aus` und
   „Nachprüfung: in Ordnung“. Bei „ABBRUCH“ hier aufhören und klären.
3. **Schreiben:**

   ```
   KJR_FIX_WRITE=1 KJR_FIX_OUT=/pfad/ablage odoo shell -d <db> --no-http < sie_form_2026-10.py
   ```

   Vorher legt das Skript `sie_form_backup_<zeit>.json` an: Fußbereich-Code,
   alle Sprachfassungen der Ansicht 4546, vorhandene Weiterleitungen für die
   beiden URLs und den alten Wert von `account.use_invoice_terms`. Committet
   wird nur, wenn die Nachprüfung in Ordnung ist. Ein zweiter Lauf meldet
   überall „schon erledigt“ und ändert nichts.
4. **Prüfen**, im privaten Fenster (nicht angemeldet, Cookies NICHT
   akzeptiert):
   - Cookie-Hinweis unten: „…damit sie für Sie besser funktioniert.“
   - Eine Seite mit eingebettetem Video bzw. Karte: Der Platzhalter sagt
     „…müssen Sie optionale Cookies akzeptieren.“
   - Quelltext der Startseite (Strg+U), Ende: `<div class="d-none"><script>`
     vor `</body>`, kein `<html><head>` mehr im `<body>`. In der
     Copyright-Leiste steht der Link „Cookie-Richtlinien“ nur einmal.
   - `/terms` und `/website/info` liefern „Seite nicht gefunden“.
   - `/sitemap.xml` enthält `/terms` und `/website/info` nicht mehr, `/shop`
     schon (siehe oben).
   - Eine Testanmeldung für eine bezahlte Veranstaltung bis in den Warenkorb
     (`/shop/cart`) durchspielen. Der Checkout muss unverändert gehen.

### Rückweg

Snapshot zurückspielen. Ohne Snapshot, mit dem Backup aus Schritt 3:
Fußbereich-Code unter Website > Konfiguration > Einstellungen > „Code am Ende
des body“ zurückkopieren. Ansicht 4546 je Sprache zurückschreiben (Odoo-Shell,
`view.with_context(lang=…, no_cow=True).write({'arch_db': …})`, `en_US`
zuerst). Die beiden Weiterleitungen „KJR: … gesperrt“ unter Website >
Konfiguration > Weiterleitungen löschen. „Standard-Geschäftsbedingungen“ in
den Buchhaltungseinstellungen wieder einschalten.

### Getestet

Am 22.10.2026 auf einer Kopie der Produktionsdatenbank (neutralisiert, eigener
Odoo-Prozess auf eigenem Port): Probelauf, Schreiblauf, zweiter Lauf („schon
erledigt“, keine Änderung). Startseite und Sitemap über HTTP abgerufen
(anonym, ohne Cookie-Zustimmung). Vorher: `/terms` und `/website/info` 200 und
in der Sitemap, „für euch“ im Banner, ihr-Skript und `<html><head>` im
`<body>`. Nachher: `/terms` und `/website/info` 404 und nicht mehr in der
Sitemap, `/shop` und `/shop/cart` 200, Banner „für Sie“, ihr-Skript weg,
Cookie-Link-Skript da, Fußbereich-Code als `<div class="d-none">` im `<body>`.
Auf der Produktion NICHT ausgeführt.
