# Changelog — KJR App (`kjr_grant`)

## 19.0.16.0.0 (2026-10-12)

### Neu
- Registrierung unterscheidet „als Privatperson“ und „für einen Verein / Verband“
  (Vereinsname Pflicht, mindestens 2 Zeichen, damit Abkürzungen wie „SV“ gehen; leeres
  und zu kurzes Feld haben getrennte Meldungen; Funktion und Ort freiwillig). Privatkonten sind wie bisher sofort
  nutzbar. Vereinskonten sind nutzbar, werden aber erst nach Genehmigung durch die
  Geschäftsstelle dem Verband zugeordnet (`parent_id`); bis dahin keine Antrags-,
  Verbands- oder Mitgliedspreisrechte (alle Rechte hängen unverändert am commercial
  partner: `is_kjr_member` bzw. Mitgliedsverbände im Teilbaum `child_of`).
- Neues Modell `kjr.affiliation.request` (Menü Verbände ▸ Vereinsregistrierungen):
  Genehmigen mit Auswahl oder Neuanlage der Organisation, Ablehnen mit optionalem
  Grund, Aktivität für die Geschäftsstelle, zwei Mailvorlagen (Firmenname aus der Firma).
  Status, Zuordnung und Ablehnungsgrund sind gegen direktes Schreiben gesperrt; entschieden
  wird nur über die beiden Assistenten. Vereinsangaben (Name, Funktion, Ort) und Firma
  (Absender und Firmenname der Mails) sind nur bis zur Entscheidung änderbar, danach
  Nachweis (auch per RPC und Import). Die Liste der Vereinsregistrierungen am Kontakt
  (`kjr_affiliation_request_ids`) ist wie das Modell nur für Sachbearbeiter und Leitung
  sichtbar (auch in `fields_get` und im Export). Beim Genehmigen schützt eine Adresswache davor, dass Odoo die
  Privatanschrift der Person in eine Organisation ohne vollständige Anschrift schreibt,
  und die USt-IdNr. der Person wandert nicht zum Verband. Eine Rechtewache verhindert,
  dass Sachbearbeiter ohne Kontaktrecht darüber Kontakte interner Benutzer zuordnen
  oder Kontakte aus einer anderen Organisation umhängen.
- Statushinweis im Portal (Mein Konto, Mein Verband, Zuschussantrag) statt leerer Formulare.
- Datenschutzhinweis (Art. 13) zu den Vereinsangaben im Registrierungsformular; abgelehnte
  Registrierungen löscht der Cron „KJR: Abgelehnte Vereinsregistrierungen löschen“ nach
  `kjr_grant.affiliation_rejected_retention_days` Tagen (Vorgabe 180, 0 = aus). Der
  Hinweis nennt dieselbe Frist wie der Cron (gemeinsame Auslegung
  `_kjr_retention_days`); bei 0 steht dort, dass abgelehnte Registrierungen bis zur
  Löschung durch die Geschäftsstelle aufbewahrt werden. Der Hinweis nennt auch die
  Folgen der Genehmigung: die angegebene Funktion wird in die Kontaktdaten übernommen
  (wenn dort noch keine steht), Name, Funktion und Kontaktdaten erscheinen in „Mein
  Verband“ für die anderen Zugänge des Verbands, und die Funktion bleibt beim Kontakt,
  auch wenn der Nachweis gelöscht wird.

### Behoben
- **Signup-Token ergaben ein Verbandskonto ohne Freigabe.** Ist die freie Registrierung
  an (website_sale, also jede Instanz mit kjr_event_shop, setzt `auth_signup_uninvited`
  auf b2c), enthalten Benachrichtigungen an Mitgliedsverbände und deren Kontakte sowie
  die Shop-Bestellbestätigung einen Registrierungslink. Darüber entstand ein Konto unter
  dem Verband. Jetzt gesperrt in `res.users.signup`; die Portaleinladung der
  Geschäftsstelle funktioniert unverändert. Archivierte Portalzugänge unter einem
  Mitgliedsverband reaktiviert die Geschäftsstelle. Maßstab ist derselbe wie für die
  Rechte (`res.partner._kjr_grants_member_rights`, Mitgliedsverband im Teilbaum des
  commercial partners): gesperrt sind also auch Kontakte unter einem Dachverband ohne
  eigene Mitgliedschaft, unter dem Mitgliedsorganisationen hängen. Zusätzlich lässt
  `res.partner.signup_get_auth_param` den Registrierungslink in Mails an Kontakte unter
  einem Mitgliedsverband weg (Kosmetik; der Zugriffslink bleibt).

### Geändert
- Texte auf Landing- und Hilfeseite der Zuschussstrecke.
- `/service/antrag-stellen` zeigt ohne zugeordneten Mitgliedsverband eine Hinweisseite;
  das gilt auch für interne Benutzer ohne Sachbearbeiterrolle und ohne Verband.
- Datenauskunft (Art. 15) um Vereinsregistrierungen ergänzt (Angaben, Status,
  zugeordnete Organisation, Ablehnungsgrund).
- Kommentar in `data/auth_signup_data.xml` korrigiert (Schlüssel wird nicht gelesen).
- `auth_signup` steht jetzt ausdrücklich in `depends` (war über `website` ohnehin geladen).

### Hinweise
- Migration 19.0.16.0.0 übernimmt aktive Portalkonten unter Mitgliedsverbänden als „genehmigt“
  (Herkunft „Bestandsübernahme“); dieselbe Übernahme läuft im `post_init_hook`. Maßstab
  ist derselbe wie für die Rechte (`_kjr_grants_member_rights`, `child_of`): auch Konten
  unter einem Dachverband ohne eigene Mitgliedschaft, unter dem Mitgliedsorganisationen
  hängen, werden übernommen (Zielorganisation: der Dachverband).
- Freie Registrierung: mit kjr_event_shop (website_sale) bereits b2c; sonst in den
  Website-Einstellungen einschalten, andernfalls liefert `/web/signup` 404.
- Zuständige Person für neue Vereinsregistrierungen optional per Systemparameter
  `kjr_grant.affiliation_responsible_user_id` (Benutzer-ID, nur wirksam für aktive interne
  Sachbearbeiter); sonst die erste Person der Gruppe Sachbearbeiter, sonst bleibt die
  Aktivität ohne Zuweisung (Warnung im Log).
- Der Ordner `migrations/19.0.15.7.0` bleibt, wo er ist: Odoo führt ihn auch beim Sprung
  auf 19.0.16.0.0 aus, solange die installierte Version kleiner als 19.0.15.7.0 ist
  (`odoo/modules/migration.py`: installiert < Ordnerversion <= Manifestversion).
- Neue Tests: `tests/test_affiliation.py` (TransactionCase) und
  `tests/test_affiliation_signup_http.py` (erster HttpCase im Repo, Registrierungsformular).

### Offen
- Löschfrist abgelehnter Registrierungen bestätigen (Vorgabe 180 Tage).
- TODO(DSGVO): Verarbeitungstätigkeit „Prüfung der Vereinszugehörigkeit“ ins Verzeichnis
  aufnehmen (DOKUS/Datenschutzkonzept).
- Nebenbefund: Über `/my/account` (Feld Firmenname) kann ein zugeordneter Verbandsnutzer
  den Namen des Verbands ändern (Odoo-Standard). Jede Genehmigung vergrößert diesen Kreis.
  Eigenes Ticket.
- Eine Privatperson, die später einem Verein zugeordnet werden möchte, meldet sich bei der
  Geschäftsstelle (Anlage der Registrierung im Backend); kein Portalformular.

## 19.0.15.7.0 (2026-10-11)

### Behoben
- **Die Mailvorlagen-Korrektur aus 19.0.15.3.0 erreicht jetzt auch bestehende
  Instanzen.** Die Vorlagen liegen unter `<data noupdate="1">`; Odoo überspringt
  solche Datensätze im Update-Modus vollständig (`odoo/tools/convert.py`:
  `if self.noupdate and self.mode != 'init'` mit `return None`, zweiter Riegel in
  `models._load_records`). Das neue `migrations/19.0.15.7.0/post-migration.py`
  baut `{{ ... }}` im gespeicherten Mailrumpf auf `<t t-out="..."/>` um, statt die
  Auslieferungswerte zurückzuschreiben. Eigene Formulierungen der Geschäftsstelle
  bleiben erhalten. Idempotent; Platzhalter in HTML-Attributen bleiben stehen und
  werden protokolliert.
- Das Skript lag bisher im Ordner `19.0.15.4.0`. Diese Nummer ist seit der
  Gedankenstrich-Korrektur belegt und installiert, ein Skript darunter wäre nie
  gelaufen (`odoo/modules/migration.py`: die Ordnerversion muss grösser als die
  installierte und kleiner/gleich der neuen Manifestversion sein). Es liegt jetzt
  auf der neuen Manifestversion. **Wird die Version erneut angehoben, muss der
  Ordner mitwandern.**
- Die ausgelieferte `data/mail_template_data.xml` war bereits in Ordnung: `{{ }}`
  steht dort nur noch in Betreff, Absender und Empfänger, wo es hingehört. Im
  Mailrumpf stand allerdings noch ein Halbgeviertstrich zwischen Beginn und Ende
  der Massnahme; er ist zu "bis" geworden. **Dieselbe Korrektur zieht das
  Migrationsskript jetzt auch in Bestandsinstanzen nach** (`_ziehe_zeitraumstrich_nach`),
  nach derselben Vorsichtsregel wie die Förderart-Texte: getauscht wird nur, wo
  noch wörtlich die ausgelieferte Zeitraumzeile steht, sonst bleibt der gepflegte
  Text stehen und es gibt einen Protokolleintrag. Die Reihenfolge in `migrate`
  ist wesentlich: erst der `{{ }}`-Umbau, dann der Strich - so greift der
  Exakt-Vergleich auch auf Instanzen aus der Zeit vor 19.0.15.3.0. Ohne diesen
  Nachzug wäre die Regel "keine Geviert-/Halbgeviertstriche in kundensichtbarem
  Text" ausgerechnet auf Demo und Produktion nicht erfüllt gewesen.
- **Zehn FontAwesome-Icons ohne `title`** nachgerüstet: neun in
  `views/portal_templates.xml`, eines in `views/kjr_grant_application_views.xml`
  (`fa-exclamation-triangle`). Gezählt mit einem Nachbau von
  `ir_ui_view._validate_fa_class_accessibility` über `views/`, `report/` und
  `data/`: auf `kjr/main` zehn Verstösse, im Arbeitsbaum null. (`aria-hidden`
  zählt dort nicht als gültige Angabe.) Dazu kommen zwei Treffer in den
  JavaScript-Zeilen der Vorlage, die neue Tabellenzeilen zusammenbauen; die
  prüft der Validator nicht, weil sie erst im Browser zu Markup werden. Die beiden Löschknöpfe im Antragsformular tragen
  jetzt zusätzlich ein `aria-label`: ihr Icon war ihr einziger Inhalt, für
  Screenreader waren sie namenlos.
- **Kein Platzhalterzeichen mehr in der Altersfenster-Warnung.** Beim Entfernen
  der Gedankenstriche war der Leerwert der Altersgrenze von "-" auf "?" gewandert.
  Bei den ausgelieferten Förderarten mit `min_age = 0` las die Geschäftsstelle im
  Chatter deshalb "ausserhalb des förderfähigen Altersbereichs (? bis 27 Jahre)" -
  wie ein Datenfehler oder ein nicht ersetzter Platzhalter. Die fehlende Grenze
  wird jetzt ausformuliert: "bis 27 Jahre, ohne Untergrenze" bzw. "ab 5 Jahren,
  ohne Obergrenze"; sind beide Grenzen gesetzt, bleibt es bei "5 bis 27 Jahre".

### Geändert
- **Datenschutzangaben sind jetzt konfigurierbar statt nur lesbar.** Die sechs
  Systemparameter `kjr.privacy.*` wurden an 30 Stellen gelesen, aber von keinem
  Modul angelegt und von keiner Oberfläche gepflegt. Neu: Einstellungen,
  Abschnitt "KJR Datenschutzangaben" (`models/res_config_settings.py`,
  `views/res_config_settings_views.xml`). Die Felder tragen `config_parameter`,
  legen also bei der Installation nichts an und kollidieren nicht mit dem
  UNIQUE-Index auf `ir.config_parameter.key`. Ein geleertes Feld entfernt den
  Parameter wieder, dann steht auf den Formularen erneut der Warnhinweis.
  **Reichweite:** Die Maske liegt in `kjr_grant`. Sie schliesst die Lücke damit
  für jede Datenbank, in der `kjr_grant` installiert ist - und nur dort.
  `kjr_event`, `kjr_facility` und `kjr_rental` lesen dieselben sechs Schlüssel,
  hängen aber nicht von `kjr_grant` ab (siehe "Offen").
- **White Label**: Kundenname und Ortsbezug sind aus allen kundensichtbaren
  Texten verschwunden. Datenschutzblöcke, Anleitungsseite und Teilnahmeliste
  ziehen den Namen jetzt aus `res_company` bzw. `o.company_id`; Feldbeschriftungen,
  Hilfetexte und Nutzermeldungen nennen Rolle oder Voreinstellung statt Träger.
  Betroffen sind unter anderem `kjr_funding.funder` (Auswahlwert "Landkreis",
  technischer Schlüssel unverändert), `kjr_grant_participant.role_code`,
  vier Hilfetexte in `kjr_grant_type` und zwei Nutzertexte in
  `kjr_grant_application`.
  - Nachgezogen: der Nachbarwert derselben Auswahlliste hiess weiter
    "Bezirksjugendring Schwaben" und nannte damit die Region des Erstkunden auf
    jedem Fördergeber-Formular. Jetzt "Bezirksjugendring"; der technische
    Schlüssel `bezjr` bleibt, also keine Datenmigration.
  - Nachgezogen: der Landkreisbezug und rund fünfzehn `KJR-OA`-Kürzel standen
    weiter in Kommentaren, Docstrings und Testbeschreibungen - der Quelltext geht
    beim Verkauf mit aus. Sie heissen jetzt "Richtlinie des Trägers",
    "Voreinstellung" bzw. "Geschäftsstelle". **Nicht** angefasst ist
    `STARTHILFE_DOCS_ALT` in `migrations/19.0.15.7.0/post-migration.py`: das ist
    der wörtliche Altwert, an dem der Exakt-Vergleich hängt; er wird verglichen,
    nie angezeigt, und ein "Aufräumen" dort würde den Nachzug stillschweigend
    wirkungslos machen. Ein Kommentar sagt das jetzt an Ort und Stelle.
  - **Der Platzhalter im Datenschutzblock ist nicht mehr an den Träger
    adressiert.** Solange ein Systemparameter leer ist, stand auf den
    öffentlichen Formularen zwölfmal das gelbe Etikett "wird vom KJR ergänzt" -
    ein interner Arbeitsauftrag im Text einer Pflichtangabe nach Art. 13 DSGVO,
    der ausserdem eine bestimmte Organisationsform nennt. Jetzt steht dort
    "Angabe folgt"; die Zuständigkeit steht in der Einstellungsmaske. Dasselbe
    gilt für das dreizehnte Etikett im Verbandsportal, das bei fehlenden
    Kontaktdaten der Geschäftsstelle erschien ("Kontaktdaten folgen").
  - **"Träger" bezeichnet wieder genau eine Partei.** Drei Hilfetexte in
    `res_partner` sagten neu "Feststellung des Trägers" und meinten den
    Zuschussgeber, während dasselbe Wort im Modul sonst den Antragsteller
    bezeichnet (Teilnahmeliste, Export-Spaltenköpfe "Träger / Antragsteller").
    Auf einem Verbandsdatensatz las sich das als Selbstauskunft des Verbands -
    das Gegenteil dessen, was das Portal daneben erklärt. Die drei Texte nennen
    jetzt die Geschäftsstelle, das im Modul durchgängige Wort für den
    Zuschussgeber.
- **Personennamen und ein wörtliches Zitat** aus einem Terminmitschnitt sind aus
  dem ausgelieferten Quellcode entfernt (Seed-Daten, beide Migrationsskripte,
  Modelle, Controller, Vorlagen, Changelog). Sie standen teils im Server-Logstrom.
  An ihrer Stelle steht die Rolle ("die Kassenleitung") bzw. die Sachaussage.
  Das Skript `migrations/19.0.10.0.0` wurde dabei NICHT inhaltlich verändert und
  behält seinen Ordnernamen, sonst liefe es auf Bestandsinstanzen erneut.
- **Seed-Förderart "Investitionszuschuss"**: Name und Beschreibung nannten einen
  konkreten Fördergeber und trugen das Wort PLATZHALTER in Grossbuchstaben im
  Kundentext. Beides ist jetzt trägerneutral. Weil die Datei unter `noupdate="1"`
  liegt, zieht dasselbe Migrationsskript den Text in Bestandsinstanzen nach, aber
  nur dort, wo noch wörtlich der alte Auslieferungswert steht. Genauso behandelt
  ist die Pflichtunterlage der Gruppenstarthilfe (§ 4.7), die das Kürzel des
  Trägers trug und auf der öffentlichen Hilfeseite erscheint.
- **Gedankenstriche** aus den verbliebenen kundensichtbaren Texten entfernt:
  Datenschutz-Prosa, Überschriften, Leerwerte in Tabellen ("-" statt Geviertstrich),
  Auswahlplatzhalter ("Bitte wählen"), Quartalsbezeichnungen, Kennziffer-Labels,
  Feldhilfen und Fehlermeldungen. Bewusst unangetastet bleiben Kommentare und
  reine Logmeldungen.
  - Nachgezogen: `static/description/index.html`, die Seite, die Odoo in "Apps"
    beim Anklicken des Moduls zeigt. Sie stand nicht im Suchraum der Prüfung
    (nur `*.xml` und `*.py`) und enthielt drei Halbgeviertstriche im Fliesstext.
    `.html` gehört ab sofort in den Suchraum.
- **Pflichtfelder des Antragsformulars**: Die Liste des Controllers steht jetzt
  als Konstante `WEBSITE_REQUIRED_FIELDS` in `controllers/website.py` und wird von
  `tests/test_form_fields.py` gegen die `required`-Felder der Vorlage geprüft, in
  beide Richtungen. Es war nichts zu verschieben: alle 19 geprüften Felder waren
  bereits gekennzeichnet. Die drei Felder, die die Vorlage strenger kennzeichnet
  (`receipt_file`, `tn_name_1`, `tn_age_1`), sind als Ausnahme festgenagelt und
  an Ort und Stelle begründet.
  - **Die Konstanten sind jetzt auch die Prüfquelle.** `REQUIRED_CONFIRMATIONS`
    und `REQUIRED_BANK_FIELDS` wurden vom Controller gar nicht gelesen: die fünf
    Namen standen ein zweites Mal als Literale in `_process_application` und
    `_check_bank_details`. Für diese fünf der 19 Pflichtfelder prüfte der Test
    also nur eine handgepflegte Kopie. Beide Stellen laufen jetzt über die
    Konstante mit einem `messages`-Wörterbuch, wie es `REQUIRED_MEASURE_FIELDS`
    schon tat. Eine vierte Pflichtbestätigung, die jemand nur im Controller
    ergänzt, fällt damit im Test auf statt beim Antragsteller.
  - **Bedingte Pflichtfelder sind benannt**: `foundation_file` (Pflicht nur bei
    der Gruppenstarthilfe § 4.7) stand in keiner der Listen, der Test konnte es
    also aus beiden Richtungen nicht sehen. Neu: `CONDITIONAL_REQUIRED_FIELDS`
    mit `receipt_file` und `foundation_file` samt Bedingung im Klartext. Ein
    statisches `required` wäre für `foundation_file` falsch: es liegt in einem
    ausgeblendeten `div`, und ein ausgeblendetes Pflichtfeld lässt der Browser
    überhaupt nicht mehr absenden. Der Kommentar über den Konstanten behauptet
    nicht länger, `WEBSITE_REQUIRED_FIELDS` sei der vollständige Vertrag.
- **Neues Modul-Icon** statt des blauen Platzhalterkreises: 256x256 RGBA,
  Antragsblatt mit Siegel und Haken, Weiß und Orange auf der Navy-Fläche der
  Modul-CI. Der bisherige `images`-Eintrag im Manifest ist entfallen: er benennt
  die Screenshots für den App Store, nicht das Icon; das Icon findet Odoo fest
  unter `static/description/icon.png` (`odoo/modules/module.py`,
  `get_module_icon`).
  - **Erzeugt wird es aus `tools/icons/build_icons.py`**, gemeinsam mit den fünf
    anderen KJR-Icons: ein Skript, eine Palette, ein Aufbau. Vorher hatte dieses
    Modul daneben eine `static/description/icon.svg` als zweite „Quelle der
    Wahrheit", die eine andere Geometrie und einen blauen Verlauf zeichnete als
    das ausgelieferte PNG. Die SVG ist **entfallen**; Odoo hat sie ohne
    Manifest-Key `icon` ohnehin nie herangezogen.
  - **Das neue Bild erreicht die App-Leiste nur über ein Modul-Update.**
    `views/menu.xml` setzt `web_icon` am Wurzelmenü, und
    `ir.ui.menu.web_icon_data` ist ein gespeichertes Feld, das Odoo nur in
    `create()`/`write()` neu aus der Datei liest
    (`odoo/addons/base/models/ir_ui_menu.py`). In der Apps-Übersicht
    (`icon_image`, nicht gespeichert) erscheint es sofort. Ohne die
    Versionsanhebung dieser Lieferung stünden auf einer Bestandsinstanz altes
    und neues Icon nebeneinander.

### Dokumentiert
- Kommentare auf den Ist-Stand gebracht: Die Bestätigungen am Formularende sind
  seit 2026 zu dritt, nicht zu viert. Die Seed-Daten im Manifest sind alle aktiv,
  nicht deaktiviert. Die offenen Datenschutzangaben werden in Systemparametern
  gepflegt, nicht in der Vorlage, und der Kommentar sagt jetzt auch, wo.

### Offen
- **Datenschutzangaben in den drei Geschwistermodulen.** `kjr_event`,
  `kjr_facility` und `kjr_rental` lesen dieselben sechs Systemparameter
  `kjr.privacy.*` per `get_param`, hängen aber nicht von `kjr_grant` ab
  (`kjr_event`: `event`/`website_event`/`account`; `kjr_facility` und
  `kjr_rental`: `base`/`mail`/`portal`/`website`/`account`). In einer Datenbank,
  in der nur eines dieser Module installiert ist, gibt es für die sechs Angaben
  weiterhin keine Eingabemaske, und auf dem Buchungs- bzw. Veranstaltungsformular
  steht sechsmal der Platzhalter. Der Audit-Punkt "Datenschutzparameter nirgends
  anlegbar" ist damit **nicht** modulfamilienweit geschlossen. Nötig ist derselbe
  `_inherit = 'res.config.settings'`-Block in den drei Modulen oder ein
  gemeinsames Basismodul `kjr_base`, von dem alle vier abhängen. Beides greift in
  fremde Manifeste ein und gehört deshalb in ein eigenes Arbeitspaket.
- **Teilnahmeliste**: Der Browser verlangt in Zeile 1 Name und Alter, der Server
  prüft die Liste gar nicht. Ob mindestens eine Teilnehmerzeile fachlich Pflicht
  ist, braucht eine Kundenentscheidung; bis dahin bleibt beides unverändert und
  der Test hält den Zustand fest.

## 19.0.15.6.1 (2026-09-10)

- Abstand zwischen Label und Wert im Datenschutzblock.

## 19.0.15.6.0 (2026-09-10)

- **Die Angaben im Datenschutzblock kommen jetzt aus der Konfiguration.** Bisher
  standen dort feste Platzhalter „wird vom KJR ergänzt", die kein Kunde füllen
  konnte, ohne die Vorlage zu ändern, und deren Änderung jedes Modulupdate wieder
  überschrieben hätte.
- Gelesen werden sechs Systemparameter: `kjr.privacy.operator`,
  `kjr.privacy.controller`, `kjr.privacy.dpo`, `kjr.privacy.legal_basis`,
  `kjr.privacy.retention`, `kjr.privacy.authority`.
- Ist ein Parameter leer, bleibt der bisherige Warnhinweis stehen. Nichts
  verschwindet unbemerkt.

## 19.0.15.5.0 (2026-09-10)

- Beispieltexte im Zuschussantrag ersetzt. Die Platzhalter nannten mit
  „Sommerausflug Skylinepark", „86871" und „Skylinepark, Rammingen" einen fremden
  Fall. Jetzt neutral: „z. B. Sommerfreizeit der Jungschar 2026" und
  „z. B. Jugendzeltplatz", die PLZ ohne Platzhalter.
- Offenen TODO-Kommentar zum Skylinepark entfernt.

## 19.0.15.4.0 — Gedankenstriche in Antragsstrecke und Verbandsportal (M2 aus dem Fehlerbericht 30.08.2026)

### Geändert
- **31 Gedankenstriche aus den kundenseitigen Texten entfernt**, verteilt auf
  Verbandsportal (`/my/verband`), Antragsformular, Hilfeseite zum Antrag und die
  Belegliste-Vorlage. Der eingeschobene Halbsatz im Fließtext ist jeweils zu einem
  eigenen Satz oder zu einem Komma-Einschub aufgelöst, der Wortlaut bleibt sonst
  gleich. Einige dabei entstandene Kommasplices sind zu zwei Sätzen getrennt.
- Bewusst **nicht** angefasst: Paragrafenverweise (`§ 4.9 – Fahrtkosten n. BayRKG`),
  Bereichsangaben, der Strich als Leerwert in Tabellen und Auswahlfeldern
  (`— Bitte wählen —`), Überschriften, die Textbausteine der Datenschutzerklärung und
  Bezeichnungen aus den Zuschussrichtlinien des KJR. Hilfetexte im Backend bleiben
  ebenfalls unverändert.

### Dokumentiert
- **M4 Sequenz-Präfix bleibt `ANT/`.** Im Bestand des KJR stehen Anträge als
  `ZA/2026/...`. Gewachsene Kundennummerierung, kein Codefehler; Begründung als
  Kommentar in `data/ir_sequence_data.xml`.

## 19.0.15.3.0 — Mailvorlagen rendern wieder (Fehlerbericht 30.08.2026)

### Behoben
- **`{{ … }}` stand sichtbar im Mailtext.** `mail.template.body_html` wird als QWeb
  gerendert, und QWeb interpoliert `{{ }}` nur innerhalb von Attributen, nie in
  Textknoten. Im Fließtext gehört `<t t-out="…"/>`. 20 Stellen umgestellt.
  Betreff, Absender und Empfänger bleiben unverändert bei `{{ }}` — die laufen über
  die Engine `inline_template`, die `{{ }}` sehr wohl ersetzt (genau daran war der
  Fehler erkennbar: Betreff aufgelöst, Text darunter nicht).

## 19.0.10.0.0 — Restpaket: Regelversionierung, Vier-Augen-Prinzip, Hilfeseite

Umsetzung der offenen code-lösbaren Punkte aus dem Abgleich „Funktionsideen ↔ Code"
(Vault: `Projects/KJR Ideen-Code-Abgleich 2026-08.md`).

### Neu
- **Datierte Richtlinienfassungen**: `kjr.grant.type` hat `valid_from` / `valid_to` und
  `rule_group`; überlappende Zeiträume derselben Regelgruppe werden abgewiesen.
  Neue API `find_for_date(code, date_ref)` wählt die zum Maßnahmenbeginn gültige Fassung.
  Bisher überschrieb eine Richtlinienänderung Altanträge rückwirkend — in einer
  Verwendungsprüfung angreifbar. Altbestand ohne Datumsgrenzen bleibt über einen
  Fallback gültig. Der Antrag zeigt über `applicable_type_id` /
  `applicable_type_warning` an, wenn die gewählte Fassung von der gültigen abweicht.
- **Vier-Augen-Prinzip technisch erzwungen** (vorher nur dokumentiert). Prüfen,
  Bewilligen und Anweisen müssen von verschiedenen Personen kommen; abschaltbar über
  den Systemparameter `kjr_grant.enforce_four_eyes` (Default `1`) für den
  Ein-Personen-Betrieb. Die Bearbeitungsvermerke sind gegen direktes Schreiben
  geschützt — die Administrator-Gruppe darf korrigieren, jede Korrektur landet im
  Chatter. Absicherung über eine prozessinterne `ContextVar` (NICHT über den
  Odoo-Kontext, der bei `call_kw` vom Client kommt), plus Guards in `create()`,
  `default_get()` und `copy=False` auf allen Vermerken.
- **IBAN-Prüfung nach ISO 13616** (Mod-97, ohne `base_iban`) und BIC-Format nach
  ISO 9362 — im Modell und bereits im Website-Formular, mit feldgenauer Fehlermeldung.
- **Hilfeseite** `/service/zuschuss-hilfe`: wer ist antragsberechtigt, welche Förderart
  passt, welche Unterlagen, Fristen, Schritt für Schritt, häufige Fehler. Förderarten
  und Pflichtunterlagen werden dynamisch aus den Stammdaten gelesen.
- **Belegliste-Vorlage** `/service/zuschuss/belegliste-vorlage` zum Ausdrucken,
  spaltengleich zur digitalen Belegliste (ANBest-P Nr. 6.4).
- **Teilnahmeliste als Unterschriftenliste** (QWeb-PDF, A4 quer) mit Kennziffern-Legende
  und Leerzeilen zum handschriftlichen Ergänzen. Auf die Sachbearbeiter-Gruppe
  beschränkt — die Liste enthält Klarnamen und Wohnorte auch Minderjähriger.

### Geändert
- **§ 4.4 Jugendleiterschulung**: Höchstbetrag von 75 € auf **50 €**. Beleg:
  Kundentermin vom 30.07.2026 mit der Kassenleitung: Höchstbetrag der
  Jugendleiterschulung 50 € statt 75 €.
  Auch `jl_max_with_juleica` und der Beschreibungstext wurden angeglichen, sonst
  hätte die globale Deckelung eine im Portal zugesagte Leistung stillschweigend
  gekappt. **Auslegung — bitte von der Kassenleitung bestätigen**, beide Varianten stehen als
  TODO im Code.
- **Förderart „Investitionszuschuss (Landkreis)"** deaktiviert (Entscheidung
  30.07.2026).
- Beide Stammdatenkorrekturen wirken über `migrations/19.0.10.0.0/post-migration.py`
  auch auf bestehende Datenbanken — `noupdate="1"` allein erreicht sie nicht. Das
  Skript ist idempotent und überschreibt keine manuell gepflegten Werte.
- Wording durchgängig **„Jugendleiter" → „Gruppenleitung"** (Labels, Meldungen,
  Bescheid, Portal). Ausgenommen: Förderart-Name „§ 4.4 Jugendleiterschulung" und
  „Juleica".
- `contact_email` und `contact_person` sind im Website-Formular jetzt Pflicht und
  werden serverseitig geprüft (bisher nur Client-seitig bzw. gar nicht).
- Belegliste-Pflicht im Formular hängt jetzt an `requires_receipt` der Förderart —
  für § 4.4 war das Formular vorher unabsendbar.
- Förderart-Auswahl und Hilfeseite filtern nach Gültigkeit, sonst erschiene ab der
  ersten zweiten Fassung dieselbe Förderart doppelt.
- Jahreslimit auf der Hilfeseite nennt die geteilte Limitgruppe (§ 4.1a und § 4.1b
  teilen sich die vier Anträge — vorher stand dort irreführend „4 je Förderart").

### Behoben
- Fehlerhafte IBAN im Website-Formular lief in einen generischen `except` und der
  Antragsteller sah nur „Bitte versuchen Sie es erneut". Zusätzlich fehlte ein
  `cr.rollback()` — ein halb angelegter Antrag mit verbrauchter Sequenznummer blieb
  in der Datenbank stehen.
- `action_reset_draft` ließ die Bearbeitungsvermerke stehen; nach Zurücksetzen und
  erneuter Bewilligung galt die alte Zahlungsanweisung weiter.

## 19.0.9.0.0 — Zuschussantrag: Feldbezeichnungen & digitale Belegliste (Kundenabstimmung 30.07.2026)

Ergebnis des Kundentermins mit der Kassenleitung am 30.07.2026 zu den
Feldbezeichnungen im öffentlichen Zuschuss-Antragsformular
(`/service/antrag-stellen`). Alle Wortlaute sind abgestimmt.

### Neu
- **Digitale Belegliste** als neues Modell `kjr.grant.receipt` (Datum, Beleg-Nr.,
  Empfänger/Einzahler, Bezeichnung, Art, Position, Betrag, Bemerkung), verknüpft über
  `receipt_ids` am Antrag. Die Positionen spiegeln 1:1 die Kostenaufstellung des Antrags;
  Prüfungen stellen sicher, dass der Betrag > 0 ist und Position und Art (Einnahme/Ausgabe)
  zusammenpassen. Kennzahlen am Antrag: `receipt_count`, `receipt_income_total`,
  `receipt_expense_total`.
- Neuer Formularblock **„Belegliste"** zwischen Kostenaufstellung und Dokumenten mit der
  Checkbox `use_digital_receipts` („Belegliste hier digital ausfüllen"). Entweder-oder,
  vom System geprüft: ist sie aktiv, entfällt der Datei-Upload „Belegliste"; ist sie inaktiv,
  bleibt der Upload sichtbar und Pflicht. Hinweistext: „Diese Belege sind vom Antragsteller
  zum Zwecke der Nachprüfung 5 Jahre im Original aufzubewahren."
- **Vier Bestätigungs-Checkboxen** statt einer, alle Pflicht zum Absenden: Datenschutz­hinweise
  (`confirm_privacy`, mit Link auf `/datenschutz`), Zuschussrichtlinien (`confirm_guidelines`),
  Vollständigkeit/Wahrheit inkl. Rückzahlungshinweis (`confirm_truthful`) sowie die bestehende
  Einwilligung der Erziehungsberechtigten (`participant_consent`, Wortlaut unverändert).
- **PLZ des Maßnahmenorts** als eigenes Feld `measure_zip` — getrennt vom Ort, für die Statistik der Geschäftsstelle.
- Teilnahmeliste: **Geschlecht** (`gender`) und **Kennziffer** (`role_code`: EA/HA/HO/PR/SO
  laut Papier-Teilnahmeliste) je Teilnehmer/in. Die Kennziffer setzt `is_leader` automatisch
  (weiterhin manuell überschreibbar).
- Neues Dokumentenfeld **„Neugründungsformular"** (`foundation_file`) — nur sichtbar und
  pflichtig bei der Förderart Gruppenstarthilfe (Code `4_7`), per JS umgeschaltet.

### Geändert
- **Alter statt Geburtsdatum:** `age` ist jetzt gespeichert und manuell eingebbar
  (`store=True, readonly=False`); aus `birthdate` wird nur noch gerechnet, wenn ein
  Geburtsdatum vorliegt — ein eingetippter Wert wird nicht mehr überschrieben.
  `birthdate` bleibt im Backend erhalten, entfällt aber im Website-Formular.
- **Teilnehmerliste → „Teilnahmeliste"** (durchgängig, umgeht das Gendern). Neuer Hinweistext:
  „Laut Zuschussrichtlinien ist die Teilnahmeliste bei Maßnahmen mit Teilnehmenden Pflicht.
  Bitte alle Teilnehmer/innen eintragen." Spalten neu: Nr. | Name, Vorname * | Alter * |
  Geschlecht | PLZ | Wohnort | Kennziffer | Juleica, dazu eine Legende zu den Kennziffern.
  Die Checkbox „Leitung" entfällt zugunsten der Kennziffer.
- Labels präzisiert: „Beginn Datum *" → **„Beginn der Maßnahme Datum *"**, „Ende Datum *" →
  **„Ende der Maßnahme Datum *"**; „TN aus anderen Regionen (max. 25 %)" → **„davon Teilnehmer
  aus anderen Regionen"** (Zusatz „(max. 25 %)" als Hinweis, bleibt optional);
  „8. Kurzbericht (optional)" → **„Zusatzinformationen"** mit dem Feld **„Ihre Nachricht an uns
  (optional)"** (der eigentliche Bericht ist ein Pflichtdokument — „Kurzbericht" war irreführend).
- Ort der Maßnahme jetzt zwei Felder: **„PLZ *"** + **„Ort der Maßnahme *"**
  (Beispiele „86871" / „Skylinepark, Rammingen").
- Beispiel Maßnahmenbezeichnung auf **„z. B. Sommerausflug Skylinepark"** geändert — aus dem
  Namen muss das Ziel hervorgehen.
- „Anzahl der Teilnehmer *" mit dem Zusatzhinweis **„ohne Gruppenleitung"**;
  **„Anzahl der Gruppenleitung"** und **„Telefon"** sind jetzt Pflichtfelder,
  „Davon mit Juleica" bleibt bewusst optional.
- Dokumenten-Block: Maßnahmenbericht mit dem Hilfetext „Aus dem Bericht müssen Charakter,
  Inhalt und Ablauf der Maßnahme hervorgehen."; „Weitere Dokumente" auf **„Z. B. Juleica-Kopie"**
  gekürzt.
- Formular-Blöcke fortlaufend und konsistent durchnummeriert (Kommentar und Überschrift liefen
  auseinander).

### Behoben
- **Altersfenster-Prüfung** stützte sich auf `birthdate` und übersprang damit alle Teilnehmenden,
  die nur ein Alter haben. Sie wertet jetzt `age` aus; Gruppenleitungen bleiben wie bisher
  ausgenommen, Datensätze ohne Alter und ohne Geburtsdatum werden übersprungen.

### Hinweise
- Die neuen Pflichtfelder (`measure_start_time`, `measure_end_time`, `measure_zip`,
  `measure_location`, `tn_leader_count`, `contact_phone`) sind **nur im Website-Formular**
  Pflicht (Template + Controller-Validierung), **nicht** im Modell — die Geschäftsstelle muss
  weiterhin unvollständige Papieranträge im Backend erfassen können.
- `participant_consent` bleibt bewusst unverändert, bis die Datenschutzbeauftragte des KJR
  den Wortlaut geprüft hat.
- Offen: PLZ/Ort des Platzhalterbeispiels mit der Geschäftsstelle gegenprüfen.

## 19.0.8.3.0

### Geändert
- **Zuschussantragsformular** (`/service/antrag-stellen`) auf die Akzentfarbe
  `#45B49F` (Teal) umgestellt: Sektions-Header, Buttons, Fokus-Rahmen und
  Auswahlfelder. Per Scope-Klasse `kjr-apply-form` nur auf das Formular begrenzt
  (übrige Website/Portal unberührt).

## 19.0.8.2.0

### Neu
- **301-Weiterleitungen** der alten `/kjr/…`-Pfade auf `/service/…`
  (`/kjr/zuschuss`, `/kjr/antrag-stellen`, `/kjr/antrag-bestaetigung`), damit bereits geteilte/indexierte alte Links nicht ins Leere laufen.
  Eigene Controller-Datei `controllers/legacy_redirects.py` (nur GET-Landingpages).

## 19.0.8.1.0

### Geändert
- **Öffentlicher URL-Präfix `/kjr/…` → `/service/…`** umbenannt, damit die Seiten
  ins Webseiten-Corporate-Design/-Menü eingebunden werden können. Betroffen:
  `/service/zuschuss`, `/service/antrag-stellen`, `/service/antrag-bestaetigung`, `/service/antrag/<id>/upload`.
  Portal-Routen unter `/my/…` bleiben unverändert (Odoo-Standard).
  Hinweis: Das Website-Menü ist `noupdate` – bei einem **Bestandsupgrade** muss der
  Menü-Link einmalig manuell auf `/service/…` gesetzt werden; Frischinstallationen
  übernehmen die neue URL automatisch.

## 19.0.6.0.0 (2026-06-19) — Richtlinien-Feinabgleich, § 4.9 BayRKG & Härtung

Vollständiger Abgleich der Zuschussverwaltung gegen den verifizierten Wortlaut der
Zuschussrichtlinie des Trägers (Fassung gültig ab 01.12.2022, als „2026" republiziert) und
die einschlägigen BJR-Regeln. Statisch geprüft (py_compile, xmllint, Feld-/Methoden-
Referenzcheck), Berechnungslogik numerisch gegen Richtlinien-Beispiele getestet, in einem
3-fachen adversarialen Review (Odoo-19-Laufzeit / Richtlinien / Vollständigkeit) gehärtet.

### Richtlinien-Korrektheit (Berechnung)
- **§ 4.9 Delegiertenförderung** korrekt als **Fahrtkostenerstattung nach BayRKG** umgesetzt
  (statt Platzhalter): PKW = Wegstreckenentschädigung je km (Hin- und Rückfahrt) + Mitnahme-
  entschädigung je Mitfahrer; ÖPNV/Sonstiges = belegte Fahrtkosten. Sätze über System-Parameter
  (`kjr_grant.bayrkg_rate_per_km` 0,35 €, `…_passenger_rate_per_km` 0,03 €). Kein eigener
  Höchstbetrag (max_amount 0), Auszahlung auf Delegiertenkonto erlaubt, Verknüpfung zur
  Vollversammlung (`assembly_id`) — bei Einreichung Pflicht; Hinweis, wenn der Verband dort
  nicht erfasst ist.
- **Juleica-Zuschlag (+50 %)** gilt jetzt einheitlich für **alle Tagessatz-Förderarten**
  (§ 4.1b/4.2/4.3/4.5) über den gemeinsamen Helfer `_day_rate_grant` (zuvor nur § 4.1b).
- **§ 4.7 (Pauschale)** und **§ 4.9 (BayRKG)** sind jetzt korrekt von Kofinanzierungs- **und**
  Fehlbetragsdeckel ausgenommen (§ 4.7 wurde zuvor fälschlich auf das Defizit gedeckelt).
- **Tageszählung** berücksichtigt die An-/Abreiseregel (nach 10:00 begonnen / vor 17:00 beendet
  → An- und Abreisetag zählen als ein Tag) über die vorhandenen Uhrzeit-Felder.
- **Auszahlungsstichtag 15.11.** (knüpft an den Antragseingang) als `payout_year`/
  `payout_schedule_info` ergänzt (Stichtag konfigurierbar).
- **Rückforderungszins** auf **Basiszinssatz + 3 Prozentpunkte** (bayer. ANBest-P Nr. 8.4 /
  Art. 49a Abs. 3 BayVwVfG) korrigiert (zuvor +5 PP); Zuschlag konfigurierbar.
- **Altersfenster** 5–27 in den Stammdaten gesetzt; Jugendleiter von der Altersprüfung
  ausgenommen (keine Altersgrenze lt. Richtlinie).
- **Kombiniertes Jahreslimit** § 4.1a + § 4.1b (max. 4 Freizeitmaßnahmen/Jahr gemeinsam) über
  `year_limit_group`.
- **§ 4.8a** verlangt jetzt korrekt **mehr als** 100 TN (min. 101); § 4.4 `juleica_bonus`
  deaktiviert (dort wirkungslos, eigene 50/75 %-Logik).
- **Verwendungsnachweis-Neuberechnung** nutzt jetzt die **echte förderartspezifische Logik**
  auf Ist-Werten (In-Memory-Antrag) statt linearer Skalierung; gedeckelt auf den bewilligten Betrag.

### Korrektheit & Bugfixes
- Portal-Datei-Upload nahm `tn_list_file`/`other_file_2` nicht entgegen → ergänzt.
- `payment_ordered`-Workflow: Button **„Zur Zahlung anweisen"** (setzt Vermerk + Benutzer + Datum).
- **Abrechnung** und **Fördermittel-Akquise** haben jetzt vollständige Workflow-Buttons
  (Eingang/Prüfung/Abschluss; setzt Eingangsdatum).
- **Juleica**: Portal-/Antragsteller-Lesezugriff auf die **eigene** Karte (ACL + Record Rule);
  Sachbearbeiter sehen alle (DSGVO-Mandantentrennung). No-Op in `_compute_expiry` bereinigt.
- **Mail-Templates** fallen auf die Verbands-E-Mail zurück (kein stiller Fehlversand mehr).
- **Vollversammlungs-Quorum** auf die **stimmberechtigten Mitglieder** gestützt (§ 33 BJR-Satzung)
  inkl. quorumsunabhängiger Wiederholungssitzung (§ 33 Abs. 3).
- Vollständige `@api.depends` für die §-4.9- und Settlement-Neuberechnung (keine veralteten Werte).

### Neue Funktionen
- Nicht-blockierende **Budget-Warnung** bei Bewilligung über dem Jahresbudget + Live-Anzeige
  „verbleibendes Budget" am Antrag (Finanzlage-/Ermessensvorbehalt der Richtlinie).
- Förderfähigkeits-Hinweise um **Subsidiarität** (anderweitige Zuschüsse ausschöpfen) und die
  **Ausschlussliste** nicht förderfähiger Kosten (Alkohol/Tabak, Personalkosten Hauptamtliche,
  berufsqualifizierende Fortbildungen, touristische Unternehmen) erweitert.
- **Fristen-Erinnerungs-Cron** für Fördermittel-Antrags- und Verwendungsnachweis-Fristen.
- System-Parameter-Defaults als Seed-Daten (`data/ir_config_parameter_data.xml`).

### Hinweise
- § 4.9 wird über das Backend erfasst (Antragsliste der Vollversammlung); das öffentliche
  Portal-Antragsformular bildet weiterhin die maßnahmenbasierten Förderarten ab.
- Basiszinssatz (`kjr_grant.base_interest_rate`) ist halbjährlich zu pflegen; BayRKG-Sätze und
  Auszahlungsstichtag sind über System-Parameter konfigurierbar (Vertrieb an weitere Ringe).
- Weiterhin offen: Laufzeit-/Abnahmetest auf einer Odoo-19-Staging-Instanz (lokal nicht möglich).

## 19.0.3.0.0 (2026-06-02) — Review, Härtung & Förderfest-Ausbau

### Behoben (kritisch/hoch)
- **`action_approve` brach komplett ab (Rollback):** `pdf_content, _ = _render_qweb_pdf(...)` überschrieb die gettext-Funktion `_` → `TypeError`. Jetzt `_report_type`.
- **Korrupte Bescheid-/Antrags-PDFs:** `ir.attachment.datas` erhielt rohe Bytes statt Base64 → `base64.b64encode(...)` (2 Stellen).
- **Mail-Templates versandten nie:** Modell hatte kein `company_id` (von Templates referenziert) → Feld ergänzt.
- **Jahresbericht-PDF crashte:** `o.env.cr.now()` existiert nicht → `context_timestamp(datetime.datetime.now())`.
- **Rückforderung falsch:** skalierte `grant_calculated` statt `grant_approved`; `@api.depends` vervollständigt.
- **Budget-Kennzahlen stale:** `store=True` ohne gültige Dependencies → auf non-stored (live) umgestellt.

### Security & DSGVO
- `base.group_public`-Schreibrecht auf `kjr.grant.participant` entfernt.
- Record Rules für `kjr.grant.participant` (Mandantentrennung der Teilnehmerdaten).
- IDOR auf Bestätigungsseite geschlossen; Antrag nur für eigene Verbände (Sachbearbeiter alle).
- Einwilligung Erziehungsberechtigter (`participant_consent`) + Anonymisierungs-Cron (`participant_retention_years`, Default 5 J.).

### Korrektheit / Datenintegrität
- `@api.constrains`: Datum (Ende ≥ Beginn), TN-Zahlen, keine negativen Beträge, `leader_ratio ≥ 1`.
- `<chatter/>` statt `oe_chatter` (5 Forms); `portal.pager` statt `web.pager`; Portal-Searchbar verdrahtet; `measure_end` Pflichtfeld.

### Neue Funktionen
- **Förderregeln konfigurierbar** (`kjr.grant.type`): Juleica-Zuschlag, Betreuungsschlüssel, Herkunftsquote, Alter, Dauer — statt hartcodiert (verifiziert gegen die Zuschussrichtlinie des Trägers).
- **Förderfähigkeits-Hinweise** beim Einreichen.
- **Verwendungsnachweis-PDF** (Soll/Ist) + **„Abrechnung erstellen"** aus dem Antrag.
- **Vollversammlung**: Quorum + automatisches Beschlussergebnis.

### Aufräumen
- Ungenutzte Enterprise-Deps entfernt (`event`, `website_event`, `mass_mailing`, `sale_renting`, `website_sale_renting`) — kommen als eigene Folge-Module. `kjr_grant_type`-Stammdaten `noupdate="1"`.

### Hinweis
Steuer/USt/E-Rechnung betreffen die geplanten Einrichtungs-/Verleih-Module, nicht die Zuschussverwaltung (Zuschüsse = kein steuerbarer Umsatz). GoBD-Festschreibung über Odoo-Core (`l10n_de`) aktivieren.
Getestet: statisch (`py_compile`, `xmllint`, Referenz-Checks) + 2 adversariale Review-Durchgänge. Vor Produktivnahme auf Staging installieren und Workflows manuell testen.
