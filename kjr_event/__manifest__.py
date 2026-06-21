# -*- coding: utf-8 -*-
{
    'name': 'KJR Ferienprogramm & Schulungen',
    'version': '19.0.2.0.0',
    'category': 'Custom/KJR',
    'summary': 'Erweiterung der Odoo-Veranstaltungen für KJR-Ferienprogramm und Schulungen '
               '(Juleica, Rettungsschwimmer): Altersgruppen, Einwilligung Minderjähriger, '
               'Notfallkontakt, Teilnahmebescheinigung',
    'author': 'Lukas Klauser / LM Consulting UG',
    'website': 'https://lm-consulting.de',
    'license': 'OPL-1',
    # event_sale/website_event_sale (Sales-App) sind OPTIONAL: das Modul soll auch auf
    # Instanzen ohne installierte Sales-App laden. Die Schulungsrechnung läuft direkt über
    # 'account'; die optionale sale.order-Anbindung wird im Code defensiv geprüft.
    'depends': [
        'event',
        'website_event',
        'account',
    ],
    'data': [
        'security/kjr_event_security.xml',
        'security/ir.model.access.csv',
        'report/kjr_event_report.xml',
        # Seed-/Mail-Daten für den ersten Staging-Build deaktiviert (Build hatte
        # geskippt). Nach erfolgreicher Installation wieder aktivieren.
        'data/mail_templates.xml',
        'views/event_views.xml',
        'views/website_event_templates.xml',
        'views/portal_templates.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
