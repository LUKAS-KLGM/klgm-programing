# -*- coding: utf-8 -*-
{
    'name': 'Website-Downloadbereich',
    'version': '19.0.1.0.0',
    'category': 'Website/Website',
    'summary': 'Downloadbereich für die ganze Website: Dateien mit Kategorien, '
               'Reihenfolge und Veröffentlichung, öffentliche Seite /service/downloads',
    'description': """
Downloadbereich
===============
Dateien ohne feste Rubrik (z. B. Positionspapiere, Vorlagen, Bausteine eines
Schutzkonzepts) zentral pflegen und auf einer öffentlichen Seite anbieten.

* Downloads mit Titel, Beschreibung, Datei, Kategorie, Datum, Reihenfolge und
  Schalter „Veröffentlicht“; Kategorien mit eigener Reihenfolge
* Backend: Website > Website > Inhalt > Downloads,
  Website > Konfiguration > Download-Kategorien
* Öffentliche Seite /service/downloads, nach Kategorie gruppiert, mit Dateityp,
  Größe und Datum; schlicht im Standard-Layout der Website
* Pflege durch die Gruppe Website-Designer

Ein Menüpunkt auf der Website wird bewusst nicht angelegt; die Website-Menüs
pflegt der Betreiber selbst.
""",
    'author': 'KLGM UG (haftungsbeschränkt)',
    'website': 'https://www.klgm-consulting.de',
    'license': 'OPL-1',
    'depends': ['website'],
    'data': [
        'security/ir.model.access.csv',
        'views/website_download_views.xml',
        'views/templates.xml',
    ],
    # Kein 'images'-Eintrag: das Icon zieht Odoo fest aus
    # static/description/icon.png (erzeugt von tools/icons/build_icons.py).
    'installable': True,
    'application': False,
    'auto_install': False,
}
