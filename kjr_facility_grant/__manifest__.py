# -*- coding: utf-8 -*-
{
    'name': 'KJR Brücke: Einrichtung ↔ Zuschuss',
    'version': '19.0.1.0.0',
    'category': 'Custom/KJR',
    'summary': 'Verknüpft Einrichtungsbuchungen mit Zuschussanträgen und erzeugt '
               'aus einer geförderten Buchung direkt einen vorbefüllten Antrag.',
    'author': 'KLGM UG (haftungsbeschränkt)',
    'website': 'https://www.klgm-consulting.de',
    'license': 'OPL-1',
    # Reine Brücke: hängt an BEIDEN Modulen. auto_install = wird automatisch
    # installiert, sobald kjr_facility UND kjr_grant vorhanden sind; ohne eines
    # der beiden bleibt sie inaktiv (beide Module bleiben einzeln installierbar).
    'depends': ['kjr_facility', 'kjr_grant'],
    'data': [
        'views/kjr_facility_grant_views.xml',
    ],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': True,
}
