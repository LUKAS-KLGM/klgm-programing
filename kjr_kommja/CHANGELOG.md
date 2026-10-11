# Changelog — KJR KommJA: Einrichtungsverzeichnis (`kjr_kommja`)

## 19.0.1.0.1 (2026-10-11)

### Geändert
- **Eigenes App-Icon** statt des bisherigen Platzhalters:
  `static/description/icon.png`, 256x256 mit Alphakanal, Landkarten-Stecknadel
  in Weiß auf der Grundfläche der KJR-Icon-Familie. Erzeugt wird es aus
  `tools/icons/build_icons.py` gemeinsam mit den fünf anderen KJR-Icons, in
  derselben Palette und demselben Aufbau; eine zweite Icon-Quelle gibt es
  bewusst nicht. Kein `icon`-Key im Manifest: Odoo zieht
  `static/description/icon.png` ohnehin fest (`odoo/modules/module.py`,
  `get_module_icon`).
  Als einziges der sechs Motive kommt dieses ohne Akzentfarbe aus: der
  Nadelkopf ist das Motiv, ein zweiter Ton darin wäre entweder zu klein oder
  zu kontrastarm. Das Loch in der Grundfarbe hat 11,3:1 gegen das Weiß.

### Behoben
- **Das Wurzelmenü trägt jetzt `web_icon`** (`views/menu.xml`). Vorher stand
  dort `<menuitem id="menu_kjr_kommja_root" name="KommJA" sequence="98"/>` ohne
  das Attribut, während `kjr_grant`, `kjr_facility` und `kjr_rental` es setzen.
  Folge: `ir.ui.menu.web_icon_data` blieb leer und Odoo zeigte für diese App in
  der täglich genutzten App-Leiste das Standardsymbol, obwohl die
  Apps-Übersicht daneben schon das gezeichnete Icon zeigte — von sechs
  zusammengehörigen Icons war nur die Hälfte dort angekommen, wo man sie sieht.
- **Versionsanhebung auf 19.0.1.0.1.** Sie ist hier nicht bloß Formsache:
  `web_icon_data` ist ein **gespeichertes** Feld, das Odoo ausschließlich in
  `create()` und `write()` neu aus der Datei liest
  (`odoo/addons/base/models/ir_ui_menu.py`). Ohne Versionsanhebung aktualisiert
  Odoo das Modul nicht, `write()` läuft nie über das Wurzelmenü, und weder das
  neue `web_icon` noch ein künftig geändertes PNG erreichten eine
  Bestandsinstanz. Ein Migrationsskript braucht es dafür nicht: `views/menu.xml`
  steht im Manifest unter `data` und in keinem `noupdate`-Block.

### Neu
- **Test `tests/test_menu_icon.py`**: das Wurzelmenü zeigt auf das Icon dieses
  Moduls, und `web_icon_data` ist nach dem Laden der Daten tatsächlich gefüllt.
  Der zweite Teil ist der eigentliche Punkt — ein `web_icon`, das auf einen
  falschen Pfad zeigt, bleibt in der Oberfläche stumm und hinterlässt nur ein
  leeres Feld.

### Hinweis
- Dieses Modul hatte bis heute keine `CHANGELOG.md`, obwohl die
  Projektkonvention für jede Modulanpassung einen Eintrag verlangt. Diese Datei
  beginnt deshalb mit der laufenden Änderung; der Auslieferungsstand
  19.0.1.0.0 (Stammdatenmodell `kjr.youth.facility` mit Backend-Ansichten,
  Zugriffsrechten und Tests) ist unten nur zusammengefasst nachgetragen.

## 19.0.1.0.0

### Neu
- **Verzeichnis der offenen Jugendeinrichtungen** (`kjr.youth.facility`):
  Jugendzentren, Jugendtreffs und mobile Angebote mit Träger, Anschrift,
  Öffnungszeiten, Altersgruppe und Ansprechperson. Eigenständiges
  Stammdatenmodul, abhängig allein von `base` und `mail`, damit es ohne
  `kjr_grant` installierbar bleibt.
- Backend-Ansichten (Liste, Formular, Kanban, Suche), Menü, Zugriffsrechte und
  Tests zur berechneten Altersgruppe samt ihrer Prüfungen.
