# Changelog — kjr_facility

## 19.0.7.3.0 (2026-10-11)

### Geändert
- **„Fremdenverkehrsbeitrag" heißt überall „Kurbeitrag".** Sachlich ist die Position
  ein kommunaler Gästebeitrag; der Fremdenverkehrsbeitrag ist eine Abgabe der
  Betriebe, nicht der Gäste. Umgestellt sind alle kundensichtbaren Stellen:
  Tariffeld und Hilfetext, das Buchungsfeld „Zusätzlich vom Kurbeitrag befreit",
  der Betrag an der Buchung, die Rechnungsposition, der Buchungsvertrag, der
  Hinweiskasten der Tarifmaske, das Website-Formular samt Preisblock,
  Kostenvorschau und Datenschutzblock sowie die Fehlermeldung des öffentlichen
  Formulars. Die Summenzeilen in Vertrag und Kostenvorschau heißen schlicht
  „Kurbeitrag"; die Rechnungsposition trägt zusätzlich die Bemessung
  („Kurbeitrag, 20 Pers. × 3 Nächte"). Ein Zusatz „(je Person und Nacht)" steht
  dort bewusst NICHT: alle drei Stellen zeigen den Gesamtbetrag, der Satz je
  Person und Nacht steht am Tarif und im Preisblock der Anfrageseite.
- **Die technischen Feldnamen bleiben unverändert** (`visitor_tax_per_person_night`,
  `amount_visitor_tax`, `visitor_tax_exempt_count`). Eine Umbenennung wäre eine
  Spaltenmigration samt Nachziehen aller Verweise in `@api.depends`, Views, Report
  und Controller, ohne fachlich etwas zu ändern. Die Begründung steht als Kommentar
  am Tariffeld.
  *Zu beachten:* Bereits erzeugte Rechnungen behalten ihren alten Positionstext,
  neue bekommen den neuen. Auf einer Instanz stehen danach beide Wörter in der
  Belegablage.
- **Interne Arbeitsnotizen aus den Feld-Tooltips entfernt.** Die Hilfetexte zu
  Kurbeitrag und Umsatzsteuer begannen mit „TODO(KJR)" und waren damit für jede
  Geschäftsstelle sichtbar; der Kurbeitrag-Tooltip war über 20 Zeilen lang. Die
  offenen Punkte stehen jetzt als Python-Kommentar am Feld, der Tooltip trägt nur
  noch die fachliche Anleitung.
- **Gedankenstriche aus kundensichtbarem Text.** Betreffzeilen der Mailvorlagen
  („Reservierungsbestätigung … : …"), Überschrift der Buchungsanfrage, Datenschutz-
  Überschrift und Rechteabsatz, die Abschnittsüberschriften des Übergabeprotokolls
  in Vertrag und Buchungsmaske, der Leerwert im Protokoll („-" statt „—"), die
  Mo-Fr-Beschriftungen und -Fehlermeldungen am Tarif, die Zeitraumangaben in
  Rechnungsposition und Doppelbelegungsmeldung sowie mehrere Feld-Tooltips.
  In Kommentaren bleiben die Striche.

### Neu
- **Logo im Kopf der Portal-Detailseite einer Buchung** (Befund 10.09.2026). Das
  Logo kommt aus `res.company` über `image_data_uri`, nicht aus einer Kundendatei;
  der Alternativtext ist der Firmenname. Ist kein eigenes Logo gepflegt, steht
  statt eines Lochs der Firmenname im Kopf. Geprüft wird das über
  `uses_default_logo`: `res.company.logo` ist nie leer, ein bloßes `t-if` auf
  `logo` hätte auf einer ungepflegten Instanz Odoos Demologo in den Kopf gesetzt.
  - Gezeigt wird die Gesellschaft der **Buchung**, nicht `res_company`. Letzteres
    ist laut `ir_qweb.py` immer die aktive Gesellschaft des *Betrachters*
    (`values.setdefault('res_company', self.env.company.sudo())`); auf einer
    Instanz mit zwei Trägergesellschaften hätte damit der falsche Absender über
    fremden Buchungsdaten gestanden. Der Controller legt die Gesellschaft der
    Buchung ge-sudo-t als `booking_company` in den Render-Kontext (Portalnutzer
    haben auf `res.company` kein Leserecht) und fällt auf `env.company` zurück,
    wenn die Buchung kein `company_id` trägt.
  - Eingebettet wird `logo_web`, nicht `logo`. `logo` ist related auf
    `partner_id.image_1920`, also das Originalbild mit bis zu 1920 px. Als
    `data:`-URI landet es ungecacht und in voller Größe in jedem Seitenaufruf —
    für ein Bild, das mit `max-height:40px` dargestellt wird. `logo_web` ist
    genau dafür da (`res_company.py`: compute auf `size=(180, 0)`, „retrieved in
    SQL for performance reasons").
- **Erkennung doppelter Schlafräume.** Sie liegt am Modell
  (`kjr.facility._find_duplicate_rooms` / `report_duplicate_rooms`) und wird von
  zwei Seiten aufgerufen: einmalig beim Umstieg aus
  `migrations/19.0.7.3.0/post-raum-duplikate.py`, damit der Befund sofort im
  Upgrade-Log steht, und danach wiederholbar aus dem wöchentlichen Cron
  `cron_kjr_room_duplicates`. Ein Migrationsskript allein hätte die Zusage
  „meldet, falls der Fall erneut auftritt" nicht halten können: es läuft genau
  einmal, nämlich beim Schritt auf seine Ordnerversion
  (`odoo/modules/migration.py`), und wäre bei jedem späteren Upgrade
  übersprungen worden.
  Gemeldet wird eine Warnung mit Einrichtung, Name, IDs und Bettenzahl. Geändert
  wird **nichts**: welcher Satz der echte ist, kann das Modul nicht wissen, weil
  die von Hand gepflegten Daten die realen Zimmernummern tragen.
  Als Dublette zählen nur **aktive** Räume. Ein bereits archivierter Satz ist der
  gewollte Endzustand (so hat `migrations/19.0.3.1.0` den Vorfall vom 01.09.2026
  bereinigt) und wird der Gruppe nur als Hinweis beigelegt.
  Der Vergleichsschlüssel nimmt die Zimmernummer am **Namensanfang** und
  schneidet den Klammerzusatz vorher ab. Über die erste Ziffernfolge irgendwo im
  Namen bekäme „Schlafsaal (12 Betten)" den Schlüssel „12" und kollidierte mit
  dem völlig korrekten „Zimmer 12 (1. OG)" — eine Falschmeldung, die auf jeder
  Bestandsinstanz aufgetreten wäre.
- **Tests für `bed_total` und `capacity_label`** (`tests/test_facility_capacity.py`):
  Summenbildung über die Räume, Nachrechnen bei geänderter Bettenzahl, Herausfallen
  archivierter Räume, Einrichtung ohne Räume, „Betten" gegen „Plätze" und das
  Mitziehen der Beschriftung beim Wechsel der Einrichtungsart.
- **Tests für die Dublettenerkennung** (dieselbe Datei): Vergleichsschlüssel aus
  der führenden Zimmernummer, Klammerzusatz bleibt außen vor, „Schlafsaal
  (12 Betten)" kollidiert nicht mehr mit „Zimmer 12 (1. OG)", archivierte Räume
  zählen nicht als Dublette, werden aber als Hinweis mitgeführt, gleiche
  Zimmernummer in zwei Einrichtungen ist keine Dublette, und der Lauf ändert
  keine Daten.
- **Eigenes App-Icon.** `static/description/icon.png` war eine leere navyfarbene
  Fläche ohne Motiv (140x140, eine einzige Farbe, kein Alphakanal); in der
  Apps-Liste erschien ein Blindfleck. Neu: 256x256 mit Alphakanal, Hausmotiv in
  Weiß auf der Navy-Fläche der Modul-CI, Bett als Ausschnitt in der Grundfarbe,
  Kissen im Orange derselben CI (`static/src/css/facility.css`). Kein
  `icon`-Key im Manifest: Odoo zieht `static/description/icon.png` ohnehin fest
  (`odoo/modules/module.py`, `get_module_icon`).
  - **Erzeugt wird das Icon jetzt aus `tools/icons/build_icons.py`**, gemeinsam
    mit den fünf anderen KJR-Icons. Vorher hatte dieses Modul als einziges eine
    zweite Quelle: `static/description/icon.svg` erklärte sich im eigenen
    Kommentar zur „Quelle der Wahrheit", während das Skript dasselbe von sich
    behauptete; beide zeichneten verschiedene Geometrien in verschiedenen Farben.
    Die SVG ist deshalb **entfallen** – Odoo hat sie ohne Manifest-Key `icon`
    nie herangezogen, und zwei Quellen laufen verlässlich auseinander. Wer das
    Icon ändern will, ändert das Skript und lässt es laufen.
  - **Das Kissen ist im Bettausschnitt gelandet statt auf der weißen Hauswand.**
    Vorher lag es in einem hellen Rosaton auf hellem Grund: 1,49:1 Kontrast,
    bei 32 Pixeln unsichtbar und bei 256 Pixeln ein Schmutzfleck, dazu mit einem
    hellen Spalt zum Kopfteil. Jetzt liegt es im Ausschnitt, stößt an das
    Kopfteil und hat 4,7:1 gegen seinen Grund.
  - **Das neue Bild erreicht die App-Leiste nur über ein Modul-Update.** Das
    Wurzelmenü trägt `web_icon`, und `ir.ui.menu.web_icon_data` ist ein
    gespeichertes Feld, das Odoo ausschließlich in `create()`/`write()` neu aus
    der Datei liest (`odoo/addons/base/models/ir_ui_menu.py`). In der
    Apps-Übersicht (`icon_image`, nicht gespeichert) erscheint es dagegen
    sofort. Ohne die Versionsanhebung dieser Lieferung stünden auf einer
    Bestandsinstanz altes und neues Icon nebeneinander.

### Behoben
- **`bed_total` rechnete beim Archivieren eines Raumes nicht nach.** Ein
  One2many liefert beim Lesen nur die nicht archivierten Datensätze
  (`odoo/orm/fields_relational.py` filtert über `Comodel._active_name`), das
  Archivieren ändert aber keine der in `@api.depends` deklarierten
  Abhängigkeiten. Innerhalb derselben Transaktion blieb `bed_total` deshalb auf
  dem alten Wert — genau in dem Ablauf, für den das Archivieren gedacht ist
  (Dublette stilllegen, Bettenzahl prüfen). `@api.depends` nennt jetzt
  zusätzlich `room_ids.active`; der zugehörige Test kommt ohne
  `invalidate_recordset` aus und prüft damit wieder das Verhalten der Anwendung
  statt das Verhalten nach einer Cache-Leerung.
- **Mailvorlagen auf Bestandsinstanzen nachgezogen**
  (`migrations/19.0.7.3.0/post-mailvorlagen.py`). In 19.0.7.0.0 wurden die
  Platzhalter im Fließtext von `{{ … }}` auf `<t t-out="…"/>` umgestellt, die
  Datei liegt aber unter `<data noupdate="1">` und erreichte damit nur
  Neuinstallationen; auf bestehenden Datenbanken standen die geschweiften Klammern
  bis heute sichtbar im Mailtext aller sieben Vorlagen. Das Skript baut den
  **gespeicherten** Wert um, statt die Auslieferungsfassung zurückzuschreiben, damit
  eigene Formulierungen der Geschäftsstelle erhalten bleiben. Platzhalter in
  HTML-Attributen bleiben unangetastet und werden protokolliert. Im selben Lauf
  werden die drei Betreffzeilen mit Geviertstrich auf Doppelpunkt gezogen und der
  Trägerbezug im Rumpf der Stornierungsvorlage neutralisiert.
  *Hinweis:* Eine frühere Fassung des Skripts lag im Ordner `19.0.7.1.0`, also
  unter der installierten Version 19.0.7.2.1, und wäre nie gelaufen
  (`odoo/modules/migration.py`). Migrationsordner tragen deshalb immer die NEUE
  Manifestversion.
- **Kanban-Karte der Einrichtung zeigte auch für Zeltplätze ein Bett-Symbol**, direkt
  neben `capacity_label`, das dort „Plätze" ausgibt. Das Symbol folgt jetzt der Art
  der Einrichtung (gleiche Regel wie auf der Website) und trägt eine Beschriftung;
  ohne die war es der einzige echte Treffer der Odoo-19-Zugänglichkeitsprüfung für
  FontAwesome-Icons in diesem Modul.
- **FontAwesome-Icons der Website ohne Beschriftung.** Symbole mit eigener Aussage
  (Ort, maximale Personenzahl) tragen jetzt ein `title`, Symbole, die nur den
  danebenstehenden Text doppeln, ein `aria-hidden`. Das Betten-/Plätze-Symbol
  gehört in die zweite Gruppe: daneben steht bereits „42 Betten", ein `title`
  ließe den Screenreader „Betten 42 Betten" vorlesen.

- **Beschreibungsseite der App** (`static/description/index.html`). Der
  Halbgeviertstrich im Einleitungssatz ist durch einen Doppelpunkt ersetzt; die
  Datei war vom Strich-Durchgang übersehen worden, obwohl sie im Apps-Raster das
  Erste ist, was ein Interessent liest. Die Überschrift steht jetzt auf #1B3A6B
  statt #1a4f8a, also auf demselben Navy wie `static/src/css/facility.css` und
  das App-Icon; vorher zeigten Icon und Beschreibungsseite zwei verschiedene
  Blautöne.

### White Label
- Einrichtungs- und Trägernamen aus kundensichtbarem Text und aus dem Quellcode
  entfernt: Einleitungssatz der öffentlichen Einrichtungsübersicht (die Karten
  darunter rendern ohnehin aus den Stammdaten), Portal-Kachel, Platzhalter im
  Namensfeld der Einrichtung, Manifest-Kurzbeschreibung, Datenschutzblock
  (Verantwortliche Stelle kommt jetzt aus `res_company.name`, „Kreisjugendring"
  durch „Betreiber" ersetzt, Platzhalterhinweis „wird vom Betreiber ergänzt"),
  Klarname eines Mitarbeiters und interne Ablagepfade in den Kommentaren von
  Seed-Daten, Modell und dem alten Migrationsskript, der Ortsbezug in der
  Begründung zur Beitragsbefreiung sowie die TODO-Marken `TODO(KJR)` und
  `TODO KJR` (ohne Klammern; die Gegenprobe lief zuerst nur auf die Schreibweise
  mit Klammern und hat die andere übersehen).
  Dazu die zuerst übersehenen kundensichtbaren Stellen: der Rumpf der
  Stornierungsmail („KJR-Geschäftsstelle" → `object.company_id.name`), die
  Feld-Tooltips zu Mindestbelegung und Mindestaufenthalt (Ortsname → neutraler
  Beispielwert), der Tooltip zum Buchungsvorlauf und die Fehlermeldung des
  öffentlichen Formulars (datierter Trägerbeschluss → neutrale Formulierung)
  sowie die Träger- und Ortsbezüge in den Kommentarblöcken von `models/`,
  `controllers/`, `data/ir_cron_data.xml` und `tests/`.
  Die fachlichen Seed-Datensätze der beiden Einrichtungen bleiben unverändert.
- **Nicht angefasst:** `static/src/img/einrichtung.svg` behält sein Teal. Die Farbe
  teilt sich das Portal-Icon mit den Portal-Kacheln der anderen Module; ein
  Alleingang hier würde die Kachelreihe im Portal auseinanderreißen. Eine
  Vereinheitlichung gehört in ein eigenes, modulübergreifendes Paket.

### Hinweis zu `data/kjr_facility_data.xml`
- Die Datei liegt unverändert vollständig unter `<data noupdate="1">`, und die
  Seed-Räume tragen stabile XML-IDs. Beides bleibt so. Neu ist nur die Begründung
  als Kommentar am Zimmerblock, inklusive der Feststellung, dass `noupdate` die
  Dublette vom 01.09.2026 gar nicht hätte verhindern können: Odoo überspringt beim
  Update nur Datensätze, deren XML-ID die Instanz bereits kennt; eine unbekannte
  XML-ID wird wegen `forcecreate=True` normal angelegt
  (`odoo/tools/convert.py`). `forcecreate="0"` wäre die einzige echte Sperre, würde
  aber jede Neuinstallation ohne Zimmer zurücklassen und ist deshalb bewusst nicht
  gesetzt.
- **Folge für künftige Änderungen:** Wer dort Namen oder Kapazitäten ändert,
  erreicht damit nur Neuinstallationen. Bestandsinstanzen brauchen ein
  Migrationsskript.

## 19.0.7.2.1 (2026-09-10)

- Abstand zwischen Label und Wert im Datenschutzblock.

## 19.0.7.2.0 (2026-09-10)

- **Die Angaben im Datenschutzblock kommen jetzt aus der Konfiguration.** Bisher
  standen dort feste Platzhalter „wird vom KJR ergänzt", die kein Kunde füllen
  konnte, ohne die Vorlage zu ändern, und deren Änderung jedes Modulupdate wieder
  überschrieben hätte.
- Gelesen werden sechs Systemparameter: `kjr.privacy.operator`,
  `kjr.privacy.controller`, `kjr.privacy.dpo`, `kjr.privacy.legal_basis`,
  `kjr.privacy.retention`, `kjr.privacy.authority`.
- Ist ein Parameter leer, bleibt der bisherige Warnhinweis stehen. Nichts
  verschwindet unbemerkt.

## 19.0.7.1.0 — Gedankenstriche in Einrichtungsanfrage und Vertrag (M2 aus dem Fehlerbericht 30.08.2026)

### Geändert
- **11 Gedankenstriche aus den kundenseitigen Texten entfernt**: Einrichtungsübersicht,
  Buchungsanfrage (Kurbeitrag, Begleitpersonen, Befreiungen, Kostenvorschau,
  fehlender Tarif), Datenschutzhinweise der Anfrage und die Verpflegungszeile im
  Buchungsvertrag. Der eingeschobene Halbsatz im Fließtext ist jeweils zu einem
  eigenen Satz oder zu einem Komma-Einschub aufgelöst.
- Bewusst **nicht** angefasst: Überschriften der Übergabeprotokoll-Abschnitte
  („Anreise — Übergabe an die Gruppe"), Betreffzeilen der Mailvorlagen, der Strich als
  Leerwert im Protokoll und die Textbausteine der Datenschutzerklärung.

## 19.0.7.0.0 — Portalbuchungen bekommen einen Tarif (Fehlerbericht 30.08.2026)

### Behoben
- **Über das Portal erzeugte Buchungen standen mit 0,00 € in allen Beträgen**, bis in
  Vertrag und Anzahlungsanforderung. Ursache: `tariff_id` wurde bei Portalbuchungen
  bewusst nicht vorbelegt, sämtliche Betragsfelder hängen aber am Tarif
  (`_compute_amounts`). Die Tarifgruppe wird jetzt aus dem Mitgliedskennzeichen des
  Kontakts abgeleitet — Mitgliedsverband → Mitgliedstarif, sonst Standardtarif.
  Einrichtungsspezifische Tarife haben weiter Vorrang vor den übergreifenden; für
  Nicht-Mitglieder ist die Suchreihenfolge unverändert.
- **Kostenvorschau und Buchung nutzen denselben Tarif.** Vorher rechnete die Vorschau
  immer mit dem Standardtarif, ein Mitgliedsverband bekam also eine andere Zahl
  angezeigt als anschließend berechnet.

### Neu
- `res.partner.is_kjr_member` — namensgleich zu `kjr_grant` und `kjr_rental`, damit
  alle drei Module sich dieselbe Spalte teilen und kjr_facility trotzdem ohne
  kjr_grant installierbar bleibt.

### Hinweis
- Die Feinunterscheidung **Partnerorganisation/kommerziell** bleibt Sache der
  Geschäftsstelle: am Kontakt gibt es kein Merkmal, aus dem sie sich ableiten ließe.
  Wird sie im Backend gesetzt, rechnen die Beträge automatisch nach (`tariff_id`
  steht in `@api.depends`).
- **Zimmer spielen für den Betrag keine Rolle.** `_compute_amounts` rechnet
  Personen × Nächte; `room_ids` trägt nur `bed_count` für Kapazitäts- und
  Doppelbelegungsprüfung bei. Die Zimmerzuordnung bleibt eine Belegungsentscheidung
  der Geschäftsstelle.

## 19.0.3.0.0 — Buchungsregeln und Preislogik Diepolz/NiSo

### Neu
- **Buchungsvorlauf** je Einrichtung (`max_advance_months`, Default 18) — Vorstands-
  beschluss vom 21.07.2026. Hart durchgesetzt im Website-Formular, im Backend als
  Hinweis: die Geschäftsstelle muss begründete Ausnahmen erfassen können.
- **Mindestbelegung** (`min_persons`, `min_nights`, `requires_organized_group`) nach
  demselben Muster. Gezählt werden Teilnehmende **und** Betreuende — einheitlich in
  Formular, Backend-Hinweis und Hilfetext.
- **Fremdenverkehrsbeitrag** pro Person und Nacht mit Befreiungen. Begleitpersonen
  sind befreit und gehen nicht in die Bemessung ein; `visitor_tax_exempt_count`
  erfasst die *weiteren* Befreiten (Einwohner der Gemeinde, Kinder unter 7,
  Schwerbehinderte). Als durchlaufender Posten ohne Steuer angelegt —
  **TODO(Steuer)**, die Einordnung ist nicht final geklärt.
- **Endreinigung** als einmalige Position je Buchung (nicht pro Nacht — über die
  Ausstattung wäre sie falsch berechnet worden).
- **Wochentagstarif** (Mo–Fr ab einer Mindestnächtezahl) als eigene Preisregel; eine
  reine Mengenstaffel bildet das nicht ab.
- **Ansprechpartner/in** als Namensfeld (bisher gab es nur das Zahlenfeld „Betreuer").

### Behoben
- **Doppelbelegung ohne Raumauswahl** lief im Backend völlig ungeprüft durch; geprüft
  wird jetzt gegen die Kapazität der Einrichtung.
- Die **Website-Verfügbarkeitsprüfung** sperrte die gesamte Einrichtung, sobald
  irgendeine überlappende Anfrage existierte — eine einzelne 8-Personen-Anfrage
  blockierte Diepolz mit 42 Betten. Sie prüft jetzt gegen die freie Kapazität und
  nennt dem Nutzer die verbleibenden Plätze.
- Der **Buchungsvertrag** (PDF) listete Positionen, deren Summe nicht die
  ausgewiesene Gesamtsumme ergab, seit Endreinigung und Beitrag hinzukamen.

## 19.0.2.3.0

### Neu
- **301-Weiterleitungen** der alten `/kjr/…`-Pfade auf `/service/…`
  (`/kjr/einrichtungen`, `/kjr/einrichtung/<id>`), damit bereits geteilte/indexierte alte Links nicht ins Leere laufen.
  Eigene Controller-Datei `controllers/legacy_redirects.py` (nur GET-Landingpages).

## 19.0.2.2.0

### Geändert
- **Öffentlicher URL-Präfix `/kjr/…` → `/service/…`** umbenannt, damit die Seiten
  ins Webseiten-Corporate-Design/-Menü eingebunden werden können. Betroffen:
  `/service/einrichtungen`, `/service/einrichtung/<id>`, `/service/einrichtung/<id>/anfrage`.
  Portal-Routen unter `/my/…` bleiben unverändert (Odoo-Standard).
  Hinweis: Das Website-Menü ist `noupdate` – bei einem **Bestandsupgrade** muss der
  Menü-Link einmalig manuell auf `/service/…` gesetzt werden; Frischinstallationen
  übernehmen die neue URL automatisch.

## 19.0.2.0.0

Transcriptbasierte Lücken (Gruppenhaus/Tagungshaus) additiv umgesetzt.

### F1 — Reserviert vs. Gebucht getrennt (muss)
- Neuer Status `reserved` ("Reserviert (vorgemerkt)") zwischen `draft` und `confirmed`.
- `confirmed` umbenannt zu "Gebucht" (verbindliche Buchung).
- Neue Methode `action_reserve()` (draft -> reserved). `action_confirm()` nun draft/reserved -> confirmed.
- Felder `reservation_date`, `reservation_expiry`, `is_booked` (compute, store).
- Statusbar/Filter/Listen-Decoration + Kalenderfarbe (`calendar_color`, reserviert heller/neutral).
- Doppelbelegungs-Constraint wertet reservierte Buchungen weiterhin als Konflikt.

### F2 — Vertrag automatisch zuschicken (soll)
- mail.template `mail_template_booking_contract` mit `report_template_ids` (PDF-Anhang).
- Beim Übergang auf `confirmed` (gebucht) automatischer Versand + `contract_sent_date`.

### F3 — Reservierungsbestätigung + automatische Ablage (soll)
- Eigenes mail.template `mail_template_booking_reserved` ("Reservierungsbestätigung").
- Helfer `_store_document(report_xmlid, name)`: rendert PDF und legt es deterministisch
  benannt als `ir.attachment` am Datensatz ab (idempotent). Aufruf beim Reservieren/Buchen.

### F5 — Fristen-/Erinnerungs-Crons (muss)
- Felder `contract_sent_date`, `contract_signed`, `deposit_due_date`.
- `_cron_contract_followup` (Vertrag gesendet, nicht unterschrieben, > 10 Tage -> Activity + Mahn-Mail).
- `_cron_deposit_overdue` (deposit_due_date < heute & nicht bezahlt -> Activity).
- `_cron_reservation_expiry` (reservation_expiry < heute in state reserved -> Activity/Hinweis).
- `_cron_booking_reminder` auf Datums-RANGE (13–15 Tage) + Dedup (Activity-Existenz) umgestellt.

### F7 — An-/Abreisezeiten (soll)
- Felder `arrival_time` / `departure_time` (Float, widget float_time) an der Buchung.
- Stammdaten `check_in_default_time` / `check_out_default_time` an `kjr.facility` als Default.
- Anzeige in Form und Report.

### F8 — Mail-Hinweis (kann)
- Feld `mail_hint` (Html) an `kjr.facility`, Ausgabe in den Mail-Templates.

### B-cross (muss)
- `payment_status` (compute aus `invoice_id.payment_state`) in Form/Liste/Portal.
- Eigener Nummernkreis 'V' — Verkaufsjournal (code 'V') per Data; in `action_create_invoice`
  als `journal_id` gesetzt, falls vorhanden.
- Optionaler Schalter `invoice_auto_post` an `kjr.facility` (Auto-Post der Rechnung).

### Bugfixes
- (a) Website-Anfrage (`facility_request`) prüft jetzt vor `create` auf Verfügbarkeit/
  Doppelbelegung (`_find_overlapping`).
- (b) Portal-Detailseite: Download-Link für Vertrags-/Reservierungs-PDF + Route
  `/my/einrichtungsbuchungen/<id>/vertrag`.

### Zurückgestellt (reine Konfiguration)
- E-Rechnung/ZUGFeRD, Bankabgleich, Mass-Mailing-Versand — Odoo-Standardkonfiguration,
  nicht als Code umgesetzt.
