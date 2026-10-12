# Changelog — KJR Brücke: Veranstaltungen ↔ E-Signatur (`kjr_event_sign`)

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
