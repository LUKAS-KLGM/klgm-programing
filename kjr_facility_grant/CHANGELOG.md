# Changelog — KJR Brücke: Einrichtung ↔ Zuschuss (`kjr_facility_grant`)

## 19.0.1.0.1 (2026-10-11)

### Geändert
- **Eigenes App-Icon** statt des bisherigen Platzhalters:
  `static/description/icon.png`, 256x256 mit Alphakanal. Es zeigt das Motiv der
  beiden Module, die diese Brücke verbindet — das Haus aus `kjr_facility` und
  das Dokument aus `kjr_grant` —, dazwischen ein Verbindungsbalken in der
  Akzentfarbe. Erzeugt wird es aus `tools/icons/build_icons.py` gemeinsam mit
  den fünf anderen KJR-Icons, in derselben Palette und demselben Aufbau; eine
  zweite Icon-Quelle gibt es bewusst nicht. Kein `icon`-Key im Manifest: Odoo
  zieht `static/description/icon.png` ohnehin fest (`odoo/modules/module.py`,
  `get_module_icon`).
  - **Der Verbindungsbalken trat unter der Hausecke hervor.** Er lief so flach
    nach unten, dass seine untere Flanke an der rechten Hauskante rund fünf
    Pixel unter der Hausunterkante lag; sichtbar war das als heller Keil an der
    abgerundeten Ecke, die Silhouette des Hauses bekam eine Stufe. Balken und
    Haus sind so gelegt, dass der Akzent an dieser Kante sicher innerhalb der
    geraden Hauskante bleibt; nachgemessen am fertigen PNG sind dort jetzt null
    Akzentpixel unterhalb der Hausunterkante.
  - Dieses Modul hat **kein eigenes Wurzelmenü** (es hängt seine Ansichten in
    die Masken der beiden Trägermodule). Es braucht deshalb kein `web_icon`;
    sein Icon erscheint allein in der Apps-Übersicht.
- **Versionsanhebung auf 19.0.1.0.1.** Die Dateiänderung liegt innerhalb des
  Moduls, also bekommt sie eine Versionsstelle und diesen Eintrag. Der Hinweis
  unter 19.0.1.0.0, die Version bleibe unverändert, gilt nur für jenen
  nachgetragenen Eintrag.

## 19.0.1.0.0

### Neu
- **Brückenmodul zwischen Einrichtungsbuchung und Zuschussantrag.** Reine Brücke:
  `auto_install` sorgt dafür, dass sie sich installiert, sobald `kjr_facility` UND
  `kjr_grant` vorhanden sind. Ohne eines der beiden bleibt sie inaktiv, beide
  Module bleiben einzeln installierbar.
- **Aktion „Zuschussantrag erstellen"** an der Buchung. Sie legt einen
  vorbefüllten, mit der Buchung verknüpften Antrag an. Vorbelegt wird die Förderart
  der mehrtägigen Freizeit, weil eine Einrichtungsbuchung immer eine Übernachtung
  umfasst.
- **Feld `grant_application_id`** an `kjr.facility.booking`. Es spiegelt die in
  `kjr_facility` bewusst entkoppelt gehaltenen Felder `is_grant_funded` und
  `grant_reference`, damit beide Module ohne einander lauffähig bleiben.
- **Gegenrichtung `facility_booking_ids`** an `kjr.grant.application` mit
  Smart-Button, dazu ein Smart-Button an der Buchung.
- **Doppelte Antragserzeugung wird verhindert:** Ist an der Buchung bereits ein
  Antrag hinterlegt, öffnet die Aktion ihn, statt einen zweiten anzulegen.
- Fünf Tests: Antragserzeugung, vorbelegte Förderart, blockierte Doppelerzeugung,
  Gegenrichtung und die Spiegelung über den Onchange.

### Hinweis
- Dieser Eintrag ist am 11.10.2026 nachgetragen worden. Das Modul hatte bis dahin
  keine `CHANGELOG.md`, obwohl die Projektkonvention für jede Modulanpassung einen
  Eintrag verlangt. Inhaltlich beschreibt er den Auslieferungsstand 19.0.1.0.0.
  Das Nachtragen dieser Datei allein hat am Modul nichts geändert.
- **Richtigstellung (11.10.2026):** Der Satz „am Modul selbst wurde dabei nichts
  geändert, die Manifestversion bleibt deshalb unverändert" stimmte nicht. Im
  selben Durchgang hat das Icon-Arbeitspaket
  `static/description/icon.png` ausgetauscht (neu 256x256 aus
  `tools/icons/build_icons.py`) und die Manifestversion angehoben. Der
  CHANGELOG-Eintrag zu dieser Anhebung gehört in dasselbe Arbeitspaket und ist
  hier bewusst nicht vorweggenommen worden, damit nicht zwei Pakete dieselbe
  Versionszeile schreiben.
