# Changelog — KJR Ferienprogramm & Schulungen (`kjr_event`)

## 19.0.5.8.0 (2026-10-11)

Korrekturen an der Auslieferung 19.0.5.7.0. Die Prüfung dieser Auslieferung hat
drei Zusagen widerlegt, die 19.0.5.7.0 wörtlich gemacht hatte; sie sind hier
eingelöst und mit Tests festgenagelt.

### Behoben

- **Die Ernährungsangabe der öffentlichen Online-Anmeldung kam nicht mehr an
  (Blocker, durch 19.0.5.7.0 selbst verursacht).** Die neue Prüfung der
  Auswahlwerte las den Wertevorrat mit `fields_get` OHNE `sudo()`.
  `dietary_requirements` ist feldgeschützt (`groups=KJR_SENSITIVE_DATA_GROUP`),
  und `fields_get` überspringt jedes Feld, das der ausführende Benutzer nicht
  lesen darf (`odoo/orm/models.py`, `fields_get` -> `_has_field_access`). Der
  Website-Besucher ist in dieser Gruppe nicht: der Wertevorrat kam leer zurück,
  JEDE Angabe galt als unbekannt und wurde verworfen. Statt der zugesagten
  Behebung einer Altlast war das ein stiller Datenverlust genau an dem Feld, in
  dem die Allergie- und Ernährungsangaben stehen - die Küchenplanung der
  Freizeiten hätte mit leeren Feldern gearbeitet. Gelesen wird jetzt mit
  `sudo()` (zulässig, weil nur der Wertevorrat des Feldes gelesen wird, kein
  personenbezogenes Datum, und der Schreibvorgang ohnehin über ein
  sudo-Recordset läuft). Neu dazu `tests/test_event_website_registration.py`:
  sechs Zusicherungen, die die Wertauswertung als öffentlicher Benutzer prüfen -
  bisher gab es dafür keinen einzigen Test.
- **Der Automatikpfad erzeugt wirklich nur Entwürfe.** Das Auto-Buchen
  (`kjr_event.invoice_auto_post`) war nicht abgeschirmt: `allow_send=False`
  schützte nur den Versand, gebucht wurde weiter. Auf einer Instanz, die diesen
  Parameter für die Sammelaktion eingeschaltet hat, entstand bei JEDER
  Bestätigung einer Anmeldung eine gebuchte, nummerierte Rechnung - nicht mehr
  löschbar, nur per Gutschrift zurückzudrehen, mit verbrauchter Nummer der
  Rechnungssequenz. Das widersprach dem Hilfetext von `kjr_auto_invoice`, dem
  Kopfkommentar in `event_registration.py`, dem Kommentar in
  `data/ir_config_parameter_data.xml` und dem CHANGELOG-Eintrag 19.0.5.7.0.
  `_kjr_create_training_invoices()` hat jetzt den zweiten Schalter `allow_post`;
  der Automatikpfad ruft mit `allow_send=False, allow_post=False`, die Handaktion
  unverändert mit beidem. Test dazu: Parameter auf `'1'`, Anmeldung bestätigen,
  Rechnung ist Entwurf.
- **Die Zusage „Fehler kippen die Anmeldung nicht" trägt jetzt auch im
  Fehlerpfad.** Zwei Lücken: (1) Der Savepoint wurde INNERHALB des `try`
  geöffnet. `cr.savepoint()` führt zuerst `cr.flush()` aus und setzt erst danach
  `SAVEPOINT` ab (`odoo/sql_db.py`, `_FlushingSavepoint`); scheiterte schon
  dieser Flush, gab es keinen Savepoint, der Rollback fehlte und der
  Fehlerzweig schrieb auf einer abgebrochenen Transaktion weiter - der
  ursprüngliche Fehler verschwand hinter „current transaction is aborted". Der
  Savepoint wird jetzt vor dem `try` geöffnet. (2) `message_post` lief ohne
  eigene Absicherung und mit den Rechten des Auslösers, auf dem Website-Pfad
  also möglicherweise unprivilegiert; ein `AccessError` dort nahm die Anmeldung
  mit. Die Notiz wird jetzt mit `sudo()` und in eigenem `try/except`
  geschrieben; misslingt sie, steht der Fehler nur im Protokoll.
- **Behördenexport: Spalte „Einnahmen" hieß Einnahmen, war aber ein Sollwert.**
  Gerechnet wird der AKTUELLE Listenpreis des Schulungsprodukts mal Kopfzahl.
  Tatsächliche Zahlungen, Teilzahlungen und Erstattungen gingen nicht ein, und
  nach einer Preisänderung am Produkt fiel derselbe Export für dasselbe Jahr
  anders aus. In einer amtlichen Meldung behauptet „Einnahmen" einen Zufluss,
  den die Zahl nicht belegt. Die Spalte heißt jetzt **„Teilnahmebeiträge Soll
  (€, aktueller Listenpreis x bestätigte und teilgenommene Anmeldungen)"** -
  Rechenweg und Zählmenge stehen damit in der Beschriftung selbst. Auf
  `amount_paid` umgestellt wurde bewusst NICHT: das Feld wird in diesem Modul
  von Hand gepflegt und ist keine belastbare Grundlage für eine Behördenmeldung
  (als offene Kundenfrage vermerkt).
- **Behördenexport: Beitrag und Beitragssumme widersprachen sich in derselben
  Zeile.** `_event_fee` prüfte die Zahlungspflicht nicht, `_event_income`
  schon: bei einer kostenfreien Maßnahme mit hinterlegtem Produkt meldete die
  Zeile „Teilnahmebeitrag 50,00" und daneben „0,00". Ohne `payment_required`
  sind jetzt beide 0,00.
- **Behördenexport: die Geschlechtsspalten nennen ihre Zählmenge** („Basis: nicht
  storniert"). Sie zählen die nicht stornierten Anmeldungen, die Nachbarspalte
  „Anmeldungen gesamt" dagegen alle Status einschließlich Storno - ohne den
  Zusatz summierten sich die Spalten sichtbar auf eine andere Zahl und die
  Sachbearbeiterin musste die Differenz erraten. Der Kommentar in `_collect_data`,
  der genau das Gegenteil behauptete, ist korrigiert.
- **Behördenexport: „Geschlecht keine Angabe" und „Geschlecht ohne Angabe"
  standen nebeneinander.** Zwei Nachbarspalten, deren sachlich wichtige
  Unterscheidung (bewusst nicht angegeben gegen gar nicht erhoben) an einem
  einzigen Wort hing. Die Spalte für das leere Feld heißt jetzt **„Geschlecht
  nicht erfasst"**. Im öffentlichen Formular heißt die Leeroption „bitte wählen"
  statt „-", damit sie nicht mit der Stufe „keine Angabe" verwechselt wird.
- **Behördenexport: ohne das Feld `kjr_gender` entfällt die Spaltengruppe
  vollständig.** Bisher blieb eine Spalte „Geschlecht ohne Angabe" mit konstant 0
  stehen - gelesen als „bei niemandem fehlt die Angabe", obwohl das Merkmal
  überhaupt nicht erhoben wird. `_gender_headers` und `_gender_values` geben bei
  leerer Stufenliste jetzt beide eine leere Liste zurück; Kopf und Zeile bleiben
  gleich lang.
- **Mailvorlagen stehen unter `noupdate="1"`** (Projektstandard, wie in
  `kjr_grant` und `kjr_facility`). `data/mail_templates.xml` stand ohne Schutz:
  jedes Modul-Update schrieb ALLE fünf Vorlagen auf den Modulstand zurück und
  verwarf ohne Meldung, was die Geschäftsstelle unter Einstellungen -> Technisch
  -> E-Mail-Vorlagen gepflegt hatte. Die sieben Server-Aktionen derselben Datei
  bleiben bewusst ohne `noupdate`: sie rufen Modellmethoden auf und müssen bei
  einer Umbenennung mitwandern. Die Betreffkorrektur aus 19.0.5.7.0 wird über
  ein Migrationsskript nachgezogen (siehe Hinweise zur Installation).
- **Ein Halbgeviertstrich in kundensichtbarem Text war übrig.** Die Zusage aus
  19.0.5.7.0, der maschinelle Scan melde keine Fundstelle mehr, hat `security/`
  nicht erfasst: die Beschreibung (`comment`) der Gruppe
  „Betreuung/Freizeitleitung" wird im Backend unter Einstellungen -> Benutzer &
  Unternehmen -> Gruppen angezeigt und enthielt einen. Ersetzt durch ein Komma,
  Satzbau unverändert. Der Scan deckt jetzt auch `security/` ab.
- **Online-Formular: „Ernährung" und „Ernährung: Hinweis" stehen wieder
  nebeneinander.** Der neue Geschlechtsblock war zwischen die beiden gesetzt
  worden; in einer Zeile mit drei Spalten (`col-md-4`) rutschte das Hinweisfeld
  damit in die nächste Zeile und stand auf dem Desktop nicht mehr neben der
  Auswahl, auf die es sich bezieht. Der Geschlechtsblock steht jetzt dahinter,
  die Begründung als Kommentar daneben.
- **Hinweistext versprach eine Mehrfachbearbeitung, die es nicht gibt.** Formular
  und `data/ir_config_parameter_data.xml` nannten die Veranstaltungsliste als Weg,
  „Rechnung automatisch erzeugen" für mehrere Veranstaltungen auf einmal zu
  setzen. Dieses Modul erbt überhaupt keine Listenansicht von `event.event`, die
  Spalte existiert dort nicht und ist auch nicht zuschaltbar. Der Satz nennt
  jetzt den Weg, den es gibt (Formular, Reiter KJR, Gruppe „Zahlung"). Eine
  Vererbung von `event.view_event_tree` wurde bewusst NICHT angelegt: das
  Community-Addon `event` liegt auf dieser Maschine nicht vor, die xml_id der
  Listenansicht ist hier nicht verifizierbar, und eine falsche Referenz bricht
  die Installation. Vorschlag für die nächste Runde an einer echten Instanz.
- **Ortsbezug in einer Testdatei.** `tests/test_event_meeting_info.py` setzte
  einen Treffpunkt mit dem Namen des Landkreises; der White-Label-Scan aus
  19.0.5.7.0 hatte `tests/` nicht erfasst. Der Test prüft nur Speichern und
  Auslesen des Freitextes, der Wert ist jetzt ortsneutral.

### Hinweise zur Installation

- **Migrationsskript `migrations/19.0.5.8.0/post-migration.py`.** Weil die
  Mailvorlagen jetzt unter `noupdate="1"` stehen, erreicht die Betreffkorrektur
  an der Einwilligungs-Erinnerung bestehende Datenbanken nicht mehr von allein
  (Odoo überspringt `noupdate`-Datensätze im Update-Modus vollständig). Das
  Skript zieht sie nach und schreibt NUR, wenn im Feld noch wörtlich der alte
  Auslieferungswert steht; ein selbst gepflegter Betreff bleibt unangetastet und
  der Fall steht im Protokoll. Idempotent. Der Ordner trägt die neue
  Manifestversion, weil `odoo/modules/migration.py` nur Skripte ausführt, deren
  Version strikt größer als die installierte ist.
- **Eigene Änderungen an den Mailvorlagen vor dem Update sichern.** Dieses eine
  Update setzt die Vorlagen noch auf den Modulstand zurück, falls die Instanz von
  19.0.5.7.0 oder früher kommt und dort Texte angepasst wurden: der Schutz greift
  erst mit dem Laden dieser Fassung. Ab dann bleibt die Pflege erhalten.
- **Die Spaltenköpfe des Statistik-Exports haben sich geändert** (Beitragssumme
  und die fünf Geschlechtsspalten). Wer die CSV in eine Excel-Vorlage einliest,
  die auf die Beschriftung abgleicht, zieht sie einmal nach. Spaltenzahl und
  Spaltenfolge sind unverändert; die Längentests decken das weiter ab.
- Keine Feld- oder Modelländerungen, keine neuen Systemparameter, keine neuen
  Abhängigkeiten.

## 19.0.5.7.0 (2026-10-11)

### Neu

- **Automatische Schulungsrechnung bei Bestätigung.** Bisher musste jede Rechnung
  von Hand erzeugt werden. Neuer Schalter je Veranstaltung
  (`event.event.kjr_auto_invoice`, im Reiter KJR unter „Zahlung"): sobald eine
  Anmeldung auf „registriert" oder „teilgenommen" wechselt, entsteht die Rechnung
  als **Entwurf**.
  - Ausgelöst wird in `create()`/`write()` von `event.registration` — die beiden
    einzigen hier verifizierbaren Durchgangspunkte, weil das Community-Addon
    `event` auf der Entwicklungsmaschine nicht vorliegt. Auf derselben Annahme
    ruht seit 19.0.2.x auch die Wartelistenlogik. **Vor dem Go-live an einer
    echten Instanz gegenprüfen.**
  - Der Auslieferungszustand kommt aus dem neuen Systemparameter
    `kjr_event.auto_invoice` und steht auf **aus**. Bestandsveranstaltungen
    bleiben damit unangetastet; wer die Automatik will, schaltet sie je
    Veranstaltung ein (in der Liste auch für mehrere auf einmal).
  - **Erzeugen ja, Versenden nein.** Der Versand bleibt die bewusste Aktion
    „KJR: Schulungsrechnung versenden". Der Automatikpfad wertet auch
    `kjr_event.invoice_auto_send` nicht aus — wer ihn eingeschaltet hat, bekommt
    durch die Automatik keine Rechnungsmails, die er nie beauftragt hat.
  - **Idempotent**, dreifach abgesichert: bereits fakturierte Anmeldungen fallen
    aus den Kandidaten, der Rechnungskern prüft denselben Fall erneut, und es
    feuert nur der Übergang nach bestätigt, nicht jeder weitere Schreibvorgang.
  - **Fehler kippen die Anmeldung nicht.** Jede Anmeldung läuft in einem eigenen
    Savepoint; schlägt die Rechnung fehl, bleibt die Anmeldung bestehen, der
    Fehler steht als Notiz im Chatter und im Protokoll.
  - Die bestehende Sammelaktion wurde dafür nicht kopiert, sondern in den
    wiederverwendbaren Kern `_kjr_create_training_invoices()` zerlegt. Ihr
    Verhalten ist unverändert.
- **Merkmal Geschlecht an der Anmeldung** (`event.registration.kjr_gender`):
  freiwillig, mit den Stufen des Vorbilds aus `kjr_grant` plus „keine Angabe",
  im öffentlichen Anmeldeformular erfassbar und im Backend pflegbar. Es wird
  ausschließlich aggregiert gezählt und nie einzeln ausgewiesen; bewusst ohne
  Feldschutz, weil der Statistik-Assistent es sonst nicht lesen könnte
  (Begründung im Code). Der Datenschutzblock des Anmeldeformulars nennt das
  Merkmal und seinen Zweck.
- **Statistik-Export erweitert** (Meldung an das Landesamt):
  - **PLZ des Veranstaltungsorts** als eigene Spalte. Ohne gepflegte PLZ bleibt
    sie leer — ein Platzhalter wäre in einer Behördenmeldung ein erfundener Wert.
  - **Einnahmen aus Teilnahmebeiträgen** je Maßnahme und in der Summenzeile. Die
    Zählmenge steht in der Spaltenbeschriftung („Basis: bestätigt und
    teilgenommen"); ohne Zahlungspflicht sind die Einnahmen 0,00.
  - **Geschlechtsspalten**: je Stufe eine Spalte, dazu „Geschlecht ohne Angabe"
    für das leere Feld. Gezählt wird dieselbe Menge wie bei den Altersklassen
    (alle nicht stornierten Anmeldungen).
  - Die Infobox des Assistenten nennt jetzt je Spaltengruppe die Zählmenge.
- **Altersklassen konfigurierbar** über den neuen Systemparameter
  `kjr_event.statistics_age_buckets` (JSON). Die bisherigen sechs Klassen bleiben
  der Standard und werden als gültiges Muster ausgeliefert. Geprüft wird streng:
  aufsteigend, lückenlos, überschneidungsfrei und den gesamten Wertebereich
  abdeckend. Jeder unbrauchbare Wert fällt auf die sechs Standardklassen zurück
  **und schreibt eine Warnung ins Protokoll** — eine stille Teilauswertung wäre
  in einer Behördenmeldung der schlimmere Fehler.

### Geändert

- **Modul-Icon ersetzt.** Das bisherige `static/description/icon.png` war ein
  Platzhalter: 140x140, 279 Byte, genau EINE Farbe auf allen 19600 Pixeln, also
  eine leere grüne Fläche ohne jedes Motiv. Neu nach dem Bildsystem der
  KJR-Module: abgerundete Kachel 256x256 in der Grundfarbe, darauf ein
  Kalenderblatt in Weiß mit Kopfleiste in der Akzentfarbe. Das Motiv folgt der
  bereits vorhandenen `static/src/img/veranstaltung.svg` (Blatt, Kopfbalken,
  zwei Aufhänger, Tagesraster), damit Apps-Kachel und Portalkachel dieselbe
  Formensprache sprechen. Kein Text, kein Kundenname, keine Verläufe, kein
  Fremdlogo.
  - **Erzeugt wird das Icon aus `tools/icons/build_icons.py`**, gemeinsam mit den
    fünf anderen KJR-Icons. Die zwischenzeitlich angelegte
    `static/description/icon.svg` ist **entfallen**: sie war als „Pflegequelle"
    gedacht, stand aber neben dem Generator als zweite Quelle für dasselbe Bild,
    mit anderer Geometrie und anderen Farben. Odoo zieht ohnehin fest das PNG
    (`odoo/modules/module.py`, `get_module_icon`), eine SVG wird ohne
    Manifest-Key `icon` nie herangezogen. Wer das Icon ändern will, ändert das
    Skript und lässt es laufen; `--check` meldet ein PNG, das nicht mehr dazu
    passt.
  - **Alle sechs Module tragen dieselbe Grundfarbe** statt je einer eigenen. Die
    Begründung „drei blaue Kacheln wären nicht auseinanderzuhalten" hat sich in
    der Gegenprobe nicht gehalten: unterschieden werden die Kacheln durch das
    Motiv, nicht durch den Farbton. Die Farbe ist jetzt das Navy `#1B3A6B` mit
    Orange `#E8952E`, also die Töne, die die Module dem Kunden im Frontend
    ohnehin zeigen (`kjr_facility/static/src/css/facility.css`,
    `kjr_rental/static/src/img/verleih.svg`, Slogan-Zeile aller `index.html`).
    *Zu beachten:* `static/src/img/veranstaltung.svg` trägt weiterhin das
    geringfügig abweichende Orange `#f2a900`; die Portalsymbole aller Module
    sind ein eigener offener Punkt.
  - Geprüft: 256x256, RGBA mit transparenten Ecken, als Gegenstand erkennbar bis
    hinunter auf 32 px, Weiß auf Grundfarbe 11,3:1, Akzent auf Grundfarbe 4,7:1.
- **White Label:** Aus den kundensichtbaren Texten sind der Kundenname und die
  Ortsbezüge verschwunden. Der Datenschutzblock des Anmeldeformulars spricht vom
  „Veranstalter" statt vom namentlich genannten Träger (der konkrete Name steht
  ohnehin direkt darüber aus `kjr.privacy.controller`); der Treffpunkt-Hilfetext
  und der zugehörige Formular-Platzhalter nennen ein ortsneutrales Beispiel.
- **Fremdprodukt aus den Nutzertexten:** Der Name des Altsystems stand im
  Hilfetext von `kjr_seats_min` und damit im Backend jeder Instanz. Er ist dort
  entfernt; in den Code-Kommentaren heißt es jetzt „Parität zum Altsystem".
- **Gedankenstriche:** Version 19.0.5.5.0 hatte nur vier Stellen erwischt. Jetzt
  sind alle Halbgeviertstriche aus dem kundensichtbaren Text dieses Moduls
  entfernt: CSV-Spaltenköpfe und Zeitraumbeschriftung des Behördenexports,
  Modellbeschreibung des Assistenten, Feldbeschriftung und Formularlabel
  „Ernährung: Hinweis" (beide gemeinsam, sonst laufen Backend und Website
  auseinander), Überschriften im Datenschutzblock, Betreff der
  Einwilligungs-Erinnerung, Portal-Überschriften, Altersgruppen-Schaltflächen
  der Freizeitenübersicht, Zeilentext der Schulungsrechnung sowie die
  Hinweistexte und Gruppenüberschriften im Backend („KJR: Warteliste" statt
  „KJR – Warteliste"). Die 5.5.0 getroffene Festlegung, die Gruppenüberschriften
  stehen zu lassen, ist damit bewusst aufgehoben. In Code-Kommentaren bleiben die
  Striche.
- **Wording „Ticket":** Der Backend-Hilfetext von `training_product_id` sprach
  von „Ticket-/Verkaufslogik" und damit von dem Begriff, den der Kunde abgelehnt
  hat; er heißt jetzt „Verkaufslogik". Geprüft und **absichtlich unverändert**
  geblieben sind: die `t-else`-Zweige der E15-Vererbungen (sie tragen den
  deutschen Kerntext für Fremdveranstaltungen; mit dem englischen Original würde
  dort Englisch erscheinen) und die Ausgabe von `ticket['name']` im
  Teilnehmerformular (das ist ein Stammdatum des Kunden, kein Modultext). Damit
  fällt dieser Punkt in der nächsten Runde nicht erneut auf.
- **CHANGELOG aufgeräumt:** Die Datei hatte keine H1, der oberste Eintrag war ein
  leerer 19.0.5.5.0-Kopf, und die Reihenfolge war verdreht (5.5.0 vor 5.6.1 vor
  5.6.0 vor 5.4.0). Jetzt absteigend sortiert; der Abschnitt „Geändert" mit den
  vier entfernten Gedankenstrichen steht wieder unter 19.0.5.5.0, wo er
  inhaltlich hingehört.

### Behoben

- **Auswahlfelder aus dem öffentlichen Anmeldeformular werden geprüft, bevor sie
  geschrieben werden.** Die Formularwerte liefen bisher ungeprüft ins Modell; ein
  präparierter POST mit einem unbekannten Schlüssel für „Ernährung" brach die
  öffentliche Anmeldung mit `ValueError: Wrong value for ...` ab. Unbekannte
  Werte werden jetzt verworfen (das Feld bleibt leer), die Anmeldung läuft durch.
  Der Wertevorrat wird dafür zur Laufzeit am Modell gelesen, nicht im Controller
  kopiert. Mit dem neuen Feld `kjr_gender` hätte sich diese Fläche sonst
  verdoppelt.
- **Die automatisch erzeugte Rechnung löst keine zweite Anmeldebestätigung aus.**
  `action_create_training_invoice()` versendet nach jeder Rechnung die Vorlage
  „Anmeldebestätigung" — dieselbe, die `action_kjr_send_registration_confirm()`
  ohne Merkerfeld von Hand versendet. Auf dem Automatikpfad ist dieser Versand
  jetzt unterdrückt; Hand- und Sammelaktion verhalten sich unverändert.
- **Zwei FontAwesome-Icons ohne `title`** in den E15-Vererbungen
  (`fa-chevron-right` im Karten-CTA, `fa-check` im Teilnahme-Badge). Odoos
  Ansichtsprüfung (`_validate_fa_class_accessibility`) verlangt dort einen
  `title` oder gültigen Nachbartext; ein `<t t-if>` zählt nicht als Text. Beide
  haben jetzt einen `title`, die Anker selbst wurden nicht angefasst.

### Offen (Kundenentscheidung nötig)

- **GaFöG-Export**: nicht umgesetzt. Es liegt keine Spezifikation vor
  (Spaltenfolge, Satzaufbau, Dateiformat, Abgabeweg). Ein erfundener Export wäre
  für eine Behördenmeldung schlechter als keiner. Benötigt wird die Meldevorlage
  bzw. der Erhebungsbogen des Landesamts; danach ist der Export analog zum
  bestehenden Assistenten in wenigen Stunden ergänzbar.
- **Wie viele Altersklassen** meldet der Träger tatsächlich? Die Vorlage des
  Landesamts kennt fünf, ausgeliefert sind sechs. Die Einteilung ist ohne
  Codeänderung umstellbar (siehe oben), die Entscheidung fehlt.
- **„Ausverkauft" oder „Ausgebucht"?** Der Verkaufsbegriff steht weiterhin an
  mehreren Stellen von Liste und Dialog. Er stand am 23.07.2026 nicht auf der
  Kundenliste und wurde deshalb nicht angefasst; eine Ersetzung braucht denselben
  `is_kjr`-Fallback-Aufbau wie die übrigen E15-Blöcke.
- **Rechtsgrundlage für das Merkmal Geschlecht** gehört in
  `kjr.privacy.legal_basis` (Entscheidung des Trägers bzw. der
  Datenschutzbeauftragten).
- **Aufbewahrungsfrist** steht weiterhin auf 0, die DSGVO-Anonymisierung läuft
  also nicht. Unverändert offen seit 19.0.5.x.

### Hinweise zur Installation

- **Kein Migrationsskript nötig und bewusst keines angelegt.** Die neuen Felder
  legt der ORM an (Standard leer bzw. aus), die beiden neuen Systemparameter
  entstehen beim Update trotz `<data noupdate="1">` (neue xml_ids werden angelegt,
  nur bestehende bleiben unangetastet), und es müssen keine Bestandsdaten
  umgeschrieben werden. Bestandsveranstaltungen bleiben absichtlich ohne
  Auto-Rechnung.

## 19.0.5.6.1 (2026-09-10)

- Abstand zwischen Label und Wert im Datenschutzblock.

## 19.0.5.6.0 (2026-09-10)

- **Die Angaben im Datenschutzblock kommen jetzt aus der Konfiguration.** Bisher
  standen dort feste Platzhalter „wird vom KJR ergänzt", die kein Kunde füllen
  konnte, ohne die Vorlage zu ändern, und deren Änderung jedes Modulupdate wieder
  überschrieben hätte.
- Gelesen werden sechs Systemparameter: `kjr.privacy.operator`,
  `kjr.privacy.controller`, `kjr.privacy.dpo`, `kjr.privacy.legal_basis`,
  `kjr.privacy.retention`, `kjr.privacy.authority`.
- Ist ein Parameter leer, bleibt der bisherige Warnhinweis stehen. Nichts
  verschwindet unbemerkt.

## 19.0.5.5.0 — Gedankenstriche in den Teilnehmertexten (M2 aus dem Fehlerbericht 30.08.2026)

### Geändert
- **4 Gedankenstriche aus den kundenseitigen Texten entfernt**: Datenschutzhinweis über
  der Teilnehmerliste im Kooperationspartner-Portal, Hilfetext des Ernährungsfelds und
  der Zweckabsatz der Datenschutzhinweise im Anmeldeformular.
- Bewusst **nicht** angefasst: Gruppenüberschriften im Backend („KJR – Warteliste"),
  Betreffzeilen der Mailvorlagen und die Textbausteine der Datenschutzerklärung.
- Versionssprung von 5.4.0 auf **5.5.0**: die Demo-Datenbank hatte 19.0.5.4.0 bereits
  eingetragen. Bei gleicher Nummer fuehrt Odoo kein Upgrade aus, die geaenderten
  Templates waeren dort stillschweigend nicht neu geladen worden.

## 19.0.5.4.0 (2026-09-01)

### Behoben

- **Veranstaltungsanmeldung brach beim Rendern ab.** Die Ansicht
  `registration_attendee_details_kjr_wording` ankerte den Absende-Knopf auf
  `//div[hasclass('modal-footer')]/button[@type='submit']`. `website_event_sale`
  ersetzt diesen Knopf durch zwei Knoepfe innerhalb eines `<t t-if>`; sie sind danach
  keine direkten Kinder des `modal-footer` mehr, der Selektor fand nichts und QWeb
  brach mit `ValueError: Element ... kann nicht in der uebergeordneten Ansicht
  lokalisiert werden` ab. Betroffen waren kostenlose und kostenpflichtige
  Veranstaltungen gleichermassen, weil die Ansicht von `website_event_sale`
  unabhaengig vom Preis greift.

  Neuer Anker: `(//div[hasclass('modal-footer')]//button[hasclass('btn-primary')])[last()]`.
  Der trifft ohne Sales-App den einzigen Kernknopf und mit Sales-App den
  `t-else`-Knopf. Ein blosser Nachfahren-Selektor waere falsch gewesen, weil dessen
  erster Treffer der Anmelden-Knopf (`Sign In`) ist.

  Der Zahlungsfall wird jetzt selbst aus `tickets` bestimmt statt ueber
  `has_paying_ticket`, das es nur mit installierter Sales-App gibt. Das Modul haengt
  bewusst nicht von `website_event_sale` ab.

## 19.0.5.3.0 — Mailvorlagen rendern wieder (Fehlerbericht 30.08.2026)

### Behoben
- **`{{ … }}` stand sichtbar im Mailtext.** Siehe kjr_grant 19.0.15.3.0 — dieselbe
  Ursache, 6 Stellen in `data/mail_templates.xml` umgestellt. Betroffen war hier nur
  die Grußformel, deshalb sind die bisher versendeten Anmeldebestätigungen
  unauffällig geblieben.

## 19.0.3.0.0 — Wording, Altersfilter, Statistik-Export

### Neu
- **Statistik-Export je Maßnahme** (`kjr.event.statistics.wizard`): Zeitraum,
  Veranstaltungsauswahl und Gruppierung, Ausgabe als CSV mit Semikolon und UTF-8-BOM
  (Excel-tauglich, die Datei geht an eine Behörde). Die gesetzliche Statistikmeldung
  musste bisher von Hand zusammengestellt werden — einer der Hauptkritikpunkte am
  abzulösenden Altsystem.
- **Altersfilter auf der Freizeiten-Übersicht** als GET-Parameter mit
  Schnellfilter-Buttons, ohne JavaScript und ohne die Paginierung zu brechen.
  Veranstaltungen ohne Altersangabe werden nie herausgefiltert; angeboten werden nur
  Altersgruppen, in die tatsächlich eine Veranstaltung fällt.

### Geändert
- **„Tickets" → „Anmeldung"** im Frontend (Kundenentscheidung 23.07.2026: für
  Freizeit-Anmeldungen ist der Verkaufsbegriff sachlich falsch). Umgesetzt über
  Template-Vererbung auf die `website_event`-Kerntemplates, eingegrenzt auf
  `event.is_kjr`. Bewusst **keine** `.po`-Datei: modulfremde Kernbegriffe lassen sich
  darüber nicht zuverlässig überschreiben, ein späteres `-u website_event` würde sie
  wieder überschreiben. Die Vererbungsblöcke sind kommentiert und nach einem
  Odoo-Update zu prüfen.
- **Nicht umgesetzt**: „Ticketpreis" → „Teilnahmebeitrag". Die Preisdarstellung kommt
  aus `website_event_sale`; ein Zugriff darauf würde das Modul auf Instanzen ohne
  Sales-App unbrauchbar machen. Architekturentscheidung nötig.

## 19.0.2.5.0

### Hinzugefügt
- **E13 Mindestanzahl Teilnehmer (Nupian-Parität)**: Odoo kennt nativ nur ein
  Sitzplatz-Maximum (`seats_max`), keine Mindestanzahl. Neues Feld `event.event.kjr_seats_min`
  (0 = keine Mindestanzahl) + computed `kjr_seats_min_reached` (Vergleich mit `seats_taken` =
  Registrierte + bereits Erschienene). Backend: Feld in der bestehenden „Teilnahme"-Gruppe im
  KJR-Reiter, Warnbox erscheint, sobald die Mindestanzahl unterschritten ist. Rein
  backend-intern, keine Website-Darstellung (Feld dient der internen Planung/Entscheidung,
  ob eine Veranstaltung bei zu wenig Anmeldungen abgesagt wird).

## 19.0.2.3.0

### Hinzugefügt
- **E12 Treffpunkt/Wichtig/Webseite (Nupian-Parität)**: Drei neue Felder auf `event.event`:
  `kjr_meeting_point` (Text, "Treffpunkt"), `kjr_important_note` (Html, "Wichtig"),
  `kjr_website_url` (Char, "Webseite"). Backend: neuer Reiter „Treffpunkt & Hinweise".
  Frontend: „Wichtig" erscheint immer (kein Toggle) als Warnbox oberhalb der Beschreibung;
  „Treffpunkt" und „Webseite" ergänzen den bestehenden Ort-Block in der Seitenleiste und
  teilen sich dessen vorhandenen Toggle (`opt_event_location_block`).

## 19.0.2.2.0

### Hinzugefügt
- **E11 Dokumente-Block (Website)**: Neues Model `kjr.event.document` (Mehrfach-Dateien
  je Veranstaltung, `event.event.kjr_document_ids`). Backend: eigener Reiter „Dokumente“
  im Event-Formular (editierbare Liste, Datei-Upload). Frontend: neuer optionaler
  Sidebar-Block auf der öffentlichen Event-Seite (`website_event.event_description_full`),
  an-/abschaltbar im Website-Editor unter „Anpassen → Sidebar-Blöcke → Dokumente“ –
  analog zu den bestehenden Blöcken Ort/Organizer/Teilen. Block erscheint automatisch nur,
  wenn mindestens ein Dokument hinterlegt ist. Zugriffsrechte (public/portal: nur Lesen;
  Event-Nutzer/-Manager: volle Verwaltung) analog zu den bestehenden `website_event`-Modellen.

## 19.0.2.0.0

### Hinzugefügt
- **E1 Online-Anmeldefelder**: Frontend-Formular (`website_event.registration_attendee_details`)
  um Geburtsdatum, Erziehungsberechtigte/r (Name/Telefon), Notfallkontakt, Ernährung
  (+ Hinweis), Einwilligungs-Checkbox und Bemerkungen erweitert. Controller
  `WebsiteEventController.registration_confirm` überschrieben, um die Werte in
  `event.registration` zu schreiben.
- **E2 Altersgruppen-Prüfung**: Konfig-Schalter `event.event.kjr_enforce_age_range`;
  harte `@api.constrains('birthdate','event_id')`-Prüfung; weiche Markierung über
  bestehendes `age_out_of_range`.
- **E3 Ernährung & Bemerkungen**: Felder `dietary_requirements`, `dietary_note`, `notes`
  auf `event.registration`; eigene Backend-Listenansicht + Such-/Gruppierungsfilter
  + Menü „KJR-Teilnehmer/innen“.
- **E4 Kooperationspartner-Zugriff**: Felder `cooperation_partner_id`,
  `cooperation_user_ids` auf `event.event`; Gruppe „KJR Kooperationspartner“
  (erbt `base.group_portal`); `ir.rule` (read-only) auf `event.event` und
  `event.registration`; Portal-Controller `/my/kjr-events` und
  `/my/kjr-events/<id>/teilnehmer` mit Templates.
- **E5/E6 Zahlung**: `event.event.payment_required`; auf `event.registration`
  `kjr_payment_state` (computed/manuell), `amount_due`, `amount_paid`, `payment_date`,
  `kjr_currency_id`. Ableitung aus `sale_order_id`/Rechnungen wenn vorhanden.
- **E7 Mail-Vorlagen**: Anmeldebestätigung, Einwilligungs-Erinnerung, Packliste, Absage,
  Bescheinigung (mit PDF-Anhang); Serverm-Action „Bescheinigung senden“.
- **E9 Schulungsanmeldung → Rechnung**: `event.event.training_product_id` +
  `action_create_training_invoice` (modulseitiges Mapping ohne event_sale-Verkaufslogik).
- **E10 Juleica/Nachweisversand**: `action_send_certificate` mailt das bestehende
  PDF (`kjr_event.participation_certificate_template`); Juleica-`juleica_valid_until`
  Default = Ausstellung + 3 Jahre.

### Bugfixes
- `consent_missing`/`age_out_of_range` jetzt gespeichert + such-/filterbar.
- `has_birthdate`-Flag entschärft die Fehlinterpretation von `kjr_age == 0`.
- Juleica-Gültigkeit erhält einen sinnvollen Default.

### Abhängigkeiten
- Neu: `event_sale`, `website_event_sale`, `account` (Odoo-Community-Core).
