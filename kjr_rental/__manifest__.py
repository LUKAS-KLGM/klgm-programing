# -*- coding: utf-8 -*-
{
    'name': 'KJR Materialverleih',
    'version': '19.0.2.3.0',
    'category': 'Custom/KJR',
    'summary': 'Verleih von Material (Fahrzeuge, Zelte, Technik, Sport, Küche, Spielgeräte) mit '
               'Bestand, Verfügbarkeitsprüfung, Mitgliedertarif, Kaution, Website-Anfrage & Vertrag',
    'author': 'KLGM UG (haftungsbeschränkt)',
    'website': 'https://www.klgm-consulting.de',
    'license': 'OPL-1',
    'depends': ['base', 'mail', 'portal', 'website', 'account'],
    'data': [
        'security/kjr_rental_security.xml',
        'security/ir.model.access.csv',
        # Seed-/Stammdaten für den ersten Staging-Build deaktiviert (Build hatte
        # geskippt). Nach erfolgreicher Installation einzeln wieder aktivieren.
        'data/ir_sequence_data.xml',
        'data/kjr_rental_data.xml',
        'views/kjr_rental_item_views.xml',
        'views/kjr_rental_order_views.xml',
        'views/kjr_rental_inventory_views.xml',
        'views/menu.xml',
        'views/website_templates.xml',
        'report/kjr_rental_report.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'kjr_rental/static/src/css/rental.css',
            'kjr_rental/static/src/js/cart.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
