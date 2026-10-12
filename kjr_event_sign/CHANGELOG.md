# Changelog — KJR Brücke: Veranstaltungen ↔ E-Signatur (`kjr_event_sign`)

## 19.0.1.1.0 (2026-10-12)

Rückmeldung aus dem Betrieb: Im Sign-Dokument stand im Feld „Name" der Name des
Kindes, und die Sign-Mail sprach das Kind an. Ursache: Unterzeichner war der
Kontakt der Anmeldung, den die Website mit dem Namen der angemeldeten Person
(des Kindes) anlegt; das Feld „Name" der Vorlage v1 liest den Namen des
Unterzeichners.

### Neu
- **Vorbefüllte Vorlage v2** `sign_template_consent_v2` („Einwilligung
  Erziehungsberechtigte (vorausgefüllt)", bewusst ohne „Standard": welche
  Vorlage Standard ist, legen die Einstellungen fest; Datei
  `data/sign_template_consent_v2_data.xml`, noupdate, eigene XML-IDs für
  Anhang, Vorlage, Dokument und Felder `item_v2_*`, Rolle
  `sign_item_role_guardian` aus v1). Name des Kindes / Teilnehmer/in,
  Veranstaltung (Name und Zeitraum) und Name der/des Erziehungsberechtigten
  stehen schreibgeschützt (`constant`, kein Pflichtfeld) im Dokument. Die
  Eltern setzen nur den Haken, den Ort und die Unterschrift; das Datum füllt
  Odoo Sign. Neue PDF-Beschriftungen und Einleitung („Die Angaben zu Ihrem
  Kind, zur Veranstaltung und Ihr Name sind aus der Anmeldung übernommen.
  Bitte prüfen Sie sie, …"; gleiche drei Angaben wie im Begleittext der
  Mail). Die Vorlage ist an das Modell `event.registration` gebunden
  (`model_id`): Odoo Sign bietet sie nur aus einer Anmeldung heraus an.
- **Mechanik (im Quelltext von Odoo 19 Sign geprüft):** `sign.request.create`
  ruft `_populate_constant_items`; für Felder mit `constant` liest
  `sign.request.item._get_auto_field_value` den Wert über `auto_field` des
  Feldtyps aus `reference_doc` (hier `event.registration,<id>`). Dafür drei
  neue Feldtypen in `data/sign_item_type_data.xml` (Typ Text, Modell
  Anmeldung): `name`, das neue nicht gespeicherte Feld
  `event.registration.kjr_sign_event_label` („<Veranstaltung>, TT.MM.JJJJ bis
  TT.MM.JJJJ" in der Zeitzone der Veranstaltung, eintägig ein Datum) und
  `guardian_name`.
- **Feldschutz und Vorbefüllung:** `guardian_name` ist direkt verknüpft
  (Gruppe `kjr_event.group_kjr_event_care`) und NICHT über ein ungeschütztes
  Hilfsfeld, das jede Person mit Leserecht an der Anmeldung per RPC lesen
  könnte. Beide Lesewege von Odoo Sign (Anlage der Anfrage als Absender mit
  sudo, Signierseite mit sudo) lesen aber mit Systemrechten und prüfen das
  Leserecht an `reference_doc` nicht; die Signierseite liefert den Wert JEDES
  Feldtyps mit `auto_field`, unabhängig von der Vorlage. Ohne Gegenmaßnahme
  hätte jede Person mit Sign-Rechten über eine selbst angelegte Anfrage mit
  `reference_doc = event.registration,<id>` den Namen der Eltern und des
  Kindes jeder Anmeldung lesen können. Deshalb neu
  `models/sign_request_item.py`: `_get_auto_field_value` liefert für Feldtypen
  auf `event.registration` nur dann einen Wert, wenn die Anfrage die aktuelle
  Anfrage der Anmeldung ist (`kjr_sign_request_id`) oder gerade von der Brücke
  für diese Anmeldung angelegt wird (Merker in `cr.cache`, per RPC nicht
  setzbar); sonst leer (Test). Ein Absender ohne die Betreuungsgruppe füllt
  die Felder der eigenen Anfrage trotzdem (Test). Die Installationsprüfung
  `_check_auto_field_exists` läuft auf einem leeren Recordset und greift den
  Feldschutz nicht an.
  **Restrisiko:** Wer eine Anfrage in Odoo Sign öffnen darf, sieht die dort
  gespeicherten Werte (Name des Kindes und der Eltern). Sign-Rechte nur an
  Personen der Betreuungsgruppe vergeben. Folge der Sperre: Über den
  Sign-Assistenten aus v2 verschickte Anfragen bekommen keine Vorbefüllung;
  immer „Unterschrift anfordern" an der Anmeldung verwenden.
- **Standardvorlage ist v2:** Rückfall in `_kjr_consent_sign_template`,
  Einstellungen und Installationsprotokoll nutzen die XML-ID von v2. v1 bleibt
  installiert (versendete Anfragen verweisen darauf) und ist weiter wählbar.
- **v1 umbenannt** in „Einwilligung Erziehungsberechtigte (alt, ohne
  Vorbefüllung)" (`event.event._kjr_sign_rename_template_v1`), damit in der
  Auswahl der Standardvorlage (Einstellungen) und an der Veranstaltung nicht
  zwei Vorlagen mit „Standard" im Namen stehen und niemand v1 für die
  aktuelle Standardvorlage hält. Nur wenn v1 noch den ausgelieferten Namen
  „… (Standard)" trägt (ein eigener Name bleibt); nur der Name ändert sich,
  Dokument, Felder und versendete Anfragen bleiben. Beim Update über die
  Migration, bei einer Neuinstallation im `post_init_hook` (dessen einzige
  Datenänderung). `sign_template_data.xml` bleibt unverändert (Generator
  erzeugt v1 weiter byte-gleich).
- **Migration `migrations/19.0.1.1.0/post-migration.py`:** setzt
  `kjr_event_sign.default_template_id` auf v2, wenn der Parameter leer ist
  oder auf v1 zeigt (eine eigene Vorlage der Geschäftsstelle bleibt), und
  stellt Veranstaltungen mit v1 (auch archivierte) auf v2 um, benennt v1
  um (siehe oben). Logik in
  `event.event._kjr_sign_switch_default_template_v2` (idempotent, getestet).
  Bereits versendete Anfragen bleiben unberührt.
- **Fehlender Name der Eltern:** Enthält die Vorlage das schreibgeschützte
  Feld „Name der/des Erziehungsberechtigten" und fehlt `guardian_name` an der
  Anmeldung (Backend, ältere Anmeldungen, „Erneut senden"), entsteht keine
  Anfrage mit leerem Namensfeld; stattdessen Fehlermerker und Aktivität
  „Unterschriftsanfrage konnte nicht versendet werden" (Text nennt jetzt auch
  den Namen). Online verhindert das die Vorprüfung von `kjr_event`
  19.0.5.10.0 (`kjr_guardian_name_missing`).
- **Name des Kindes im Feld der Eltern** (gemeldeter Fall „erziehungsberechtigter
  ist name des kindes"): Entspricht `guardian_name` dem Namen der Anmeldung
  (ohne Groß-/Kleinschreibung, Leerraum egal), verschickt die Brücke mit
  vorbefüllter Vorlage KEINE Anfrage (`_kjr_sign_check_prefill`: UserError,
  Fehlermerker, Aktivität), sonst stünde der Kindername schreibgeschützt als
  unterschreibende Person im Dokument. Betrifft vor allem Bestandsanmeldungen
  von der Produktion bei „Erneut senden", Adresskorrektur oder Cron-Retry.
  Bei der Wahl des Unterzeichner-Kontakts gilt ein solcher Name als fehlend.
  Online weist `kjr_event` 19.0.5.10.0 den Fall ab
  (`kjr_guardian_name_is_child`).
- **Anonymisierung (Befund K6) löscht nie unterschriebene Anfragen:** Mit v2
  trägt jede Anfrage schon beim Anlegen den Namen des Kindes und der Eltern
  (bei v1 trugen die Eltern ihn erst beim Unterschreiben ein).
  `_kjr_purge_registration_copies` erfasst jetzt ALLE Anfragen einer
  Anmeldung (auch frühere aus „Erneut senden" oder Adresswechsel, über
  `reference_doc`), storniert offene und löscht alle nicht unterschriebenen
  (offen, storniert, abgelaufen, abgelehnt; Odoo Sign verbietet nur das
  Löschen unterschriebener). Unterschriebene bleiben archiviert als Nachweis.
  Scheitert das Löschen, wird archiviert (Fehler im Protokoll, nur IDs).
  Bis zur Anonymisierung bleiben stornierte Anfragen mit den Namen bestehen
  (Verlauf für die Geschäftsstelle).
- **Geänderte Angaben bei offener Anfrage:** Ändert sich bei offener Anfrage
  mit vorbefüllten Feldern der Name des Kindes, der Name der/des
  Erziehungsberechtigten (`event.registration.write`) oder Name bzw. Termine
  der Veranstaltung (`event.event.write`), vergleicht
  `_kjr_sign_check_prefilled` die gespeicherten schreibgeschützten Werte mit
  dem aktuellen Stand. Bei Abweichung wird die Anfrage storniert (Notiz
  „Unterschriftsanfrage storniert: Angaben der Anmeldung geändert.") und wie
  beim Adresswechsel neu versendet; ohne die Rechte für den automatischen
  Neuversand (z. B. Registrierungstheke) oder ohne Sperre entsteht die
  Aktivität „Unterschriftsanfrage neu senden". Sonst unterschrieben die Eltern
  ein Dokument mit veralteten Angaben, die sie nicht ändern können (Odoo Sign
  lehnt jede spätere Änderung eines schreibgeschützten Werts ab). Gleiche
  Werte, v1 und eigene Vorlagen ohne Vorbefüllung lösen nichts aus. Storno
  und Neuversand teilen sich mit dem Adresswechsel die Methode
  `_kjr_sign_cancel_and_restart` (Tests).
- **`kjr_sign_request_id` nur über die Brücke:** `readonly` wirkte nur in der
  Oberfläche; per RPC konnte jede Person mit Sign-Rechten und Schreibrecht an
  der Anmeldung (Registrierungstheke) eine selbst angelegte Anfrage als
  aktuelle eintragen und darüber die Sperre der Vorbefüllung umgehen (Name
  der Eltern, Name des Kindes auf der Signierseite) sowie mit der eigenen
  Unterschrift die Einwilligung buchen. `create` und `write` der Anmeldung
  weisen das Feld (auch als Kontext-Vorgabe `default_kjr_sign_request_id`)
  ohne Systemrechte jetzt mit AccessError ab
  (`_kjr_sign_check_request_link`); die Brücke schreibt es weiter mit sudo
  (Test).

### Geändert
- **Unterzeichner-Kontakt** (`_kjr_sign_guardian_partner`): Mit Namen der/des
  Erziehungsberechtigten wird ein Kontakt nur wiederverwendet, wenn E-Mail UND
  Name passen (ohne Groß-/Kleinschreibung, Leerraum egal), zuerst der Kontakt
  der Anmeldung, dann jeder Kontakt mit derselben Adresse; sonst entsteht ein
  neuer Kontakt mit diesem Namen (Kategorie „KJR Erziehungsberechtigte",
  Deutsch). Ohne Namen wie bisher über die E-Mail, aber nie ein Kontakt mit
  dem Namen des Kindes; dann neuer Kontakt mit der Adresse als Name.
  Bestehende Kontakte werden nie umbenannt. Folge: Hat ein Elternteil ein
  Kundenkonto unter anderem Namen als im Formular angegeben, erscheint die
  Anfrage nicht unter „Mein Konto"; die Mail kommt trotzdem an.
- **Begleittext der Sign-Mail:** Bei Vorlagen mit Vorbefüllung „Bitte prüfen
  Sie die aus der Anmeldung übernommenen Angaben (Name Ihres Kindes,
  Veranstaltung und Ihr Name), …" statt „Bitte tragen Sie im Formular den
  Namen Ihres Kindes ein"; bei Vorlagen ohne Vorbefüllung (v1, eigene) bleibt
  der alte Satz. Weiterhin ohne Kindsnamen in Mail, Betreff und Referenz.
  Der Zeitraum für Mail und Formular kommt aus derselben Methode
  `_kjr_sign_event_period`.
- **Website-Datenschutzblock:** zusätzlicher Satz, dass Name des Kindes /
  Teilnehmer/in, Veranstaltung und Name der/des Erziehungsberechtigten aus
  der Anmeldung in das Einwilligungsformular übernommen werden.
- **Generator** `tools/einwilligung/build_einwilligung_pdf.py`: erzeugt v1
  byte-gleich wie bisher und zusätzlich v2
  (`static/pdf/einwilligung_erziehungsberechtigte_v2.pdf`,
  `data/sign_template_consent_v2_data.xml`); `--check` prüft beide. Neue
  Plausibilitätsprüfungen: schreibgeschützte Felder nur mit erlaubten Typen
  und nicht als Pflichtfeld.
- Tests `tests/test_sign_bridge.py`: Grundlage ist jetzt v2. Neu: v2 ist
  Standard, Vorbefüllung der drei Felder nach dem Anlegen (Absender ohne
  Betreuungsgruppe), schreibgeschützter Wert nicht änderbar, Zeitraum
  eintägig, fehlender Name der Eltern, Begleittext v1/v2, Unterzeichner nie
  der Kind-Kontakt (mit und ohne Namen), gleiche E-Mail mit anderem Namen,
  Migration (Parameter v1/leer/eigene Vorlage, Veranstaltungen inkl.
  archivierter, versendete Anfrage bleibt bei v1, idempotent, v1
  umbenannt), Umbenennung von v1 nur beim ausgelieferten Namen. Angepasst:
  Wiederverwendung nur bei gleichem Namen, Signierwerte ohne
  schreibgeschützte Felder. Außerdem: Name des Kindes als Name der Eltern
  (keine Anfrage, nie Kind-Kontakt), fremde Anfrage mit `reference_doc` einer
  Anmeldung erhält keine Werte, Anonymisierung löscht nicht unterschriebene
  Anfragen (auch frühere) und behält unterschriebene.

### Hinweise zur Installation
- Update `-u kjr_event_sign` (zusammen mit `kjr_event` 19.0.5.10.0). Im Log:
  „Migration kjr_event_sign 19.0.1.1.0: {'param': 'set' | 'kept', 'events': n, 'v1_renamed': True | False}".
- Danach in Sign > Vorlagen die Vorlage „Einwilligung Erziehungsberechtigte
  (vorausgefüllt)" prüfen (Lage der Felder auf dem PDF); v1 heißt jetzt
  „Einwilligung Erziehungsberechtigte (alt, ohne Vorbefüllung)".
- Offene Anfragen mit v1 laufen unverändert weiter. Wer sie auf v2 bringen
  will: „Erneut senden" an der Anmeldung (storniert und versendet neu, dann
  mit v2; der Name der Eltern muss an der Anmeldung stehen).

## 19.0.1.0.0 (2026-10-12)

### Neu
- **Brückenmodul zwischen `kjr_event` und Odoo Sign.** Reine Brücke:
  `auto_install` installiert sie, sobald `kjr_event` UND `sign` vorhanden sind.
  Ohne Sign bleibt `kjr_event` beim Einwilligungsverfahren „Bestätigung im
  Formular“. Das Modul hat keinen eigenen Controller (die Controller-Regel E14
  bleibt unberührt).
- **Einwilligung per digitaler Unterschrift.** Ist an der Veranstaltung die
  Einwilligung verlangt und die Brücke in den Einstellungen eingeschaltet,
  liefert `event.event._kjr_consent_mode()` den Modus `sign`. Online-Anmeldungen
  Minderjähriger bleiben dann gesperrt (`kjr_consent_hold` aus `kjr_event`),
  und die Erziehungsberechtigten erhalten eine Unterschriftsanfrage
  (`sign.request`) mit der Standard-Mail von Odoo Sign. Nach der Unterschrift
  setzt der Hook an `sign.request._sign` die Einwilligung (Quelle „Digitale
  Unterschrift“); `kjr_event` gibt die Anmeldung frei, sofern ein Platz frei
  ist.
- **Datensparsam:** Referenz und Betreff der Anfrage nennen nur Veranstaltung
  und Anmeldenummer, nie den Namen des Kindes (unterschriebene Anfragen und das
  Sign-Protokoll sind nicht löschbar). Das mitgelieferte PDF ist neutral, ohne
  Firmennamen, ohne Geburtsdatum und ohne Gesundheitsfragen; den Namen des
  Kindes tragen die Eltern selbst ein. Der Firmenname im Anschreiben kommt aus
  der Firma der Veranstaltung. Protokolle enthalten nur IDs.
- **Mitgelieferte Vorlage** „Einwilligung Erziehungsberechtigte (Standard)“
  (Rolle „Erziehungsberechtigte/r“, sieben Felder). PDF und
  `data/sign_template_data.xml` erzeugt `tools/einwilligung/build_einwilligung_pdf.py`
  aus einer einzigen Koordinatentabelle; `--check` vergleicht ohne zu schreiben.
  Änderungen nur über eine neue XML-ID (`_v2`) und Umstellen der Standardvorlage.
- **Eltern-Kontakt:** Wiederverwendung des Anmelde-Kontakts bzw. eines Kontakts
  mit derselben E-Mail-Adresse (bei mehreren Treffern zuerst Kontakte mit
  Benutzerkonto, dann Personen vor Firmen); nur wenn keiner existiert, entsteht ein neuer
  Kontakt mit der Kategorie „KJR Erziehungsberechtigte“ (Sprache Deutsch, falls
  aktiv). Bestehende Kontakte werden nie umbenannt.
- **Absender:** Systemparameter `kjr_event_sign.sender_user_id`, sonst die
  verantwortliche Person der Veranstaltung, sonst der Administrator; jeweils
  nur aktive interne Benutzer mit E-Mail-Adresse.
- **Gültigkeit und Erinnerung:** Gültig höchstens 14 Tage, spätestens bis zum
  Tag vor Beginn, mindestens bis morgen. Erinnerungen übernimmt Odoo Sign
  (alle 3 Tage, 0 = keine).
- **Storno:** Papier-Einwilligung, Absage, Archivieren und Löschen der
  Anmeldung stornieren eine offene Anfrage. Die Herkunft „Digitale
  Unterschrift“ aus dem Kontext gilt wie in `kjr_event` nur mit sudo (Weg über
  `sign.request._sign`); ein RPC-Aufruf mit diesem Kontext zählt als Papier und
  storniert die offene Anfrage ebenfalls. Die Ablehnung durch die Eltern setzt einen Merker, legt
  eine Notiz ohne Begründung und eine Aktivität an; die Sperre bleibt.
  Storno-Notizen sind feste Texte je Grund (kein Freitext aus dem Kontext).
- **Kein automatischer Neuversand:** Nach Ablehnung, Ablauf oder Storno startet
  keine neue Anfrage von selbst (etwa wenn der Auftrag nach der Überweisung
  auf „Verkaufsauftrag“ wechselt). Neu senden nur über die Schaltflächen; der
  tägliche Lauf wiederholt nur fehlgeschlagene Versuche.
- **Adresse geändert:** Ändert sich die E-Mail-Adresse der Erziehungsberechtigten
  (bzw. der Anmeldung oder der Kontakt), während eine Anfrage offen ist, wird
  sie storniert und an die neue Adresse neu versendet (bei nicht mehr
  gesperrter Anmeldung nur Aktivität). Automatisch neu versendet wird nur mit
  sudo oder für Veranstaltungs-Benutzer/innen; ändert etwa die
  Registrierungstheke die Anmelde-E-Mail, wird nur storniert und eine
  Aktivität „Unterschriftsanfrage neu senden“ angelegt (sonst ginge der
  Signierlink an eine selbst gewählte Adresse). Der Signierlink der KJR-Erinnerung
  entsteht nur, wenn der Unterzeichner der aktuelle Empfänger ist.
- **Unterschrift zu abgesagter oder archivierter Anmeldung:** reaktiviert die
  Anmeldung nicht, sondern legt eine Aktivität an. Archivieren (Feld `active`
  aus dem Kern) gilt in der Brücke überall wie eine Absage. Abgesagte und
  archivierte Anmeldungen bekommen nie eine Anfrage: „Unterschrift anfordern“
  und „Erneut senden“ sind bei abgesagten ausgeblendet und filtern beide
  serverseitig heraus, `_kjr_consent_request_start` überspringt sie für alle
  Aufrufer.
- **Rückfall ohne aktive Brücke (E10):** Ist die Veranstaltung nicht (mehr) im
  Modus `sign` (Brücke ausgeschaltet, Vorlage ungültig), läuft
  `_kjr_consent_request_start` über `kjr_event` (Aktivität „Einwilligung
  einholen“), ohne Fehlermerker und ohne Fehlversuch. Betrifft vor allem
  zurückgestellte Shop-Warenkörbe beim Zurückschalten. Der tägliche Lauf
  wiederholt Fehlversuche nur im Modus `sign`.
- **Rechte der Schaltflächen serverseitig:** „Unterschrift anfordern“, „Erneut
  senden“ und „Anfrage stornieren“ verlangen auch bei einem Aufruf per RPC die
  Gruppe Veranstaltungen/Benutzer und Schreibrecht an der Anmeldung
  (Registrierungstheke und Portal-Kooperationspartner: Zugriffsfehler).
- **Fehlerzähler:** Ein erfolgreicher Versand und jede bewusste Anforderung über
  die Schaltflächen setzen `kjr_sign_attempts` zurück; jede neue Anforderung hat
  wieder drei Versuche im täglichen Lauf.
- **Datenschutz, unterschriebenes PDF:** Odoo Sign kopiert das unterschriebene
  Dokument (Name und Unterschrift der erziehungsberechtigten Person, Ort,
  Kindsname) als Anhang an die Anmeldung und hängt es an die Nachricht „fully
  signed“. Dort wäre es für alle lesbar, die die Anmeldung lesen dürfen, und
  umginge den Feldschutz der Erziehungsberechtigten-Daten. Der Hook an
  `sign.request._sign` löscht die Kopie und löst den Anhang von der Nachricht.
  Der Nachweis liegt an der Unterschriftsanfrage (nur für Sign-Benutzer/innen).
- **Formular der Anmeldung:** Schaltflächen „Unterschrift anfordern“, „Erneut
  senden“, „Anfrage stornieren“, Smart-Button zur Anfrage (Sign-Benutzer),
  Feld „Stand Unterschrift“. Liste und Suche (Odoo-Standard und
  KJR-Teilnehmerliste): Spalte, Filter „Unterschrift offen“,
  „Unterschrift abgelehnt/abgelaufen“ und Gruppierung.
- **Veranstaltung:** eigene Einwilligungsvorlage wählbar (leer =
  Standardvorlage aus den Einstellungen).
- **Einstellungen „KJR Einwilligung“:** Einschalter, Standardvorlage mit
  Prüfhinweis, Absender, Gültigkeit, Erinnerung.
- **Protokoll:** Eine ungültige Vorlage meldet die Prüfung nur bei der
  Installation und in den Einstellungen als Warnung. Bei der laufenden
  Berechnung des Modus (bei jedem Zugriff, auch je Anmeldung in Listen) nur
  auf DEBUG, damit dieselbe Meldung das Protokoll nicht flutet.
- **Website:** Zusatzhinweise im Datenschutzblock des Anmeldedialogs (Nachweis
  im System zur digitalen Unterschrift, Kontakt der erziehungsberechtigten
  Person mit Name und E-Mail-Adresse) und auf der Erfolgsseite (Spam-Ordner, „Mein Konto“ bei „Signaturanfragen“, sofern die
  Anfrage an die Adresse des Kundenkontos ging).
- **Signierlink für die KJR-Erinnerung:** `kjr_consent_action_url` liefert bei
  offener Anfrage einen frisch erzeugten Signierlink (Feld bleibt in
  `kjr_event` deklariert und geschützt).
- **Täglicher Lauf** `_cron_kjr_event_sign`: bis zu drei Wiederholungen bei
  Versandfehlern, einmalige Aktivität bei Ablauf oder Ablehnung (nicht, wenn
  die Einwilligung inzwischen vorliegt), Storno verwaister Anfragen (Anmeldung
  per Kaskade gelöscht, abgesagt oder archiviert; die Waisen werden in SQL bestimmt, das
  Limit von 200 je Lauf greift erst danach).
- **Anonymisierung (`kjr_event`, Befund K6):** offene Anfragen werden
  storniert, alle archiviert, die Verknüpfung an der Anmeldung geleert.
- **App-Icon** aus `tools/icons/build_icons.py` (Kalenderblatt und
  unterschriebenes Blatt, verbunden; im selben Lauf entsteht das Icon von
  `kjr_website_antispam`).
- Tests `tests/test_sign_bridge.py`.

### Hinweise zur Installation
- `auto_install` greift nur bei einer Neuinstallation. In einer bestehenden
  Datenbank einmal ausdrücklich installieren: `-i kjr_event_sign`
  (Voraussetzung: `kjr_event` 19.0.5.9.0 und Odoo Sign installiert).
- Nach der Installation ist die Brücke **aus**. Einschalten unter
  Einstellungen, „KJR Einwilligung“: zuerst den **Absender** wählen (interner
  Benutzer mit E-Mail-Adresse), dann „Einwilligung digital einholen“ aktivieren.
- Das Protokoll der Installation meldet, ob die Standardvorlage gültig ist und
  ob ein Absender gefunden wurde.
- Vorher auf der Server-Kopie prüfen (Spezifikation Abschnitt 6): Mail- und
  Signierseite von Sign mit Sprache Deutsch, Suche über `reference_doc`,
  Bereinigung der Sign-Anhänge durch die Anonymisierung.

### Offen (Kundenentscheidung nötig)
- TODO(KJR): Aufbewahrungsfrist der unterschriebenen Einwilligungen.
- TODO(KJR): Umgang mit den Eltern-Kontakten (Kategorie „KJR
  Erziehungsberechtigte“) im Löschkonzept; sie sind für alle internen Benutzer
  sichtbar.
- TODO(KJR): Automatische Absage bei Ablauf oder Ablehnung (heute nur Aktivität).
- TODO(KJR): Gültigkeit (14 Tage) und Erinnerungsintervall (3 Tage) bestätigen.
- TODO(KJR): Text des Einwilligungsformulars mit Geschäftsstelle und
  Datenschutzbeauftragter abstimmen; AVV/TOM-Anlage um Odoo Sign ergänzen.
