# -*- coding: utf-8 -*-
{
    'name': 'KJR Aktivitäten-Popup',
    'version': '19.0.1.0.0',
    'category': 'Custom/KJR',
    'summary': 'Fällige und überfällige Aktivitäten (auch Aufgaben-Fristen) '
               'erscheinen im Backend als großes, gut lesbares Popup-Fenster.',
    'author': 'KLGM UG (haftungsbeschränkt)',
    'website': 'https://www.klgm-consulting.de',
    'license': 'OPL-1',
    # Bewusst nur base/mail/web: Projekt-Aufgaben werden zusätzlich
    # berücksichtigt, wenn `project` installiert ist (weiche Kopplung über
    # die Registry, keine Abhängigkeit).
    'depends': ['base', 'mail', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_users_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'kjr_activity_popup/static/src/**/*',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
