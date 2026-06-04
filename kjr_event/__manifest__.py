# -*- coding: utf-8 -*-
{
    'name': 'KJR Ferienprogramm & Schulungen',
    'version': '19.0.1.0.0',
    'category': 'Custom/KJR',
    'summary': 'Erweiterung der Odoo-Veranstaltungen für KJR-Ferienprogramm und Schulungen '
               '(Juleica, Rettungsschwimmer): Altersgruppen, Einwilligung Minderjähriger, '
               'Notfallkontakt, Teilnahmebescheinigung',
    'author': 'Lukas Klauser / LM Consulting UG',
    'website': 'https://lm-consulting.de',
    'license': 'OPL-1',
    'depends': ['event', 'website_event'],
    'data': [
        'views/event_views.xml',
        'report/kjr_event_report.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
