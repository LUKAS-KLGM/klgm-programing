# -*- coding: utf-8 -*-
{
    'name': 'KJR KommJA – Einrichtungsverzeichnis',
    'version': '19.0.1.0.0',
    'category': 'Custom/KJR',
    'summary': 'Verzeichnis der offenen Jugendeinrichtungen im Landkreis '
               '(Kommunale Jugendarbeit): Jugendzentren, -treffs, mobile Angebote.',
    'author': 'KLGM UG (haftungsbeschränkt)',
    'website': 'https://www.klgm-consulting.de',
    'license': 'OPL-1',
    # Eigenständiges Stammdaten-Modul (nur base/mail). Unabhängig von kjr_grant –
    # einzeln installierbar, white-label für beliebige Jugendringe.
    'depends': ['base', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/kjr_youth_facility_views.xml',
        'views/menu.xml',
    ],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
}
