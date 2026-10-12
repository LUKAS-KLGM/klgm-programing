# -*- coding: utf-8 -*-
{
    'name': 'KJR Ferienprogramm & Schulungen',
    'version': '19.0.5.10.0',
    'category': 'Custom/KJR',
    'summary': 'Erweiterung der Odoo-Veranstaltungen für KJR-Ferienprogramm und Schulungen '
               '(Juleica, Rettungsschwimmer): Altersgruppen, Einwilligung Minderjähriger, '
               'Notfallkontakt, Teilnahmebescheinigung, Website-Dokumente-Block, '
               'Treffpunkt/Wichtig/Webseite, Mindestanzahl Teilnehmer, '
               'Einwilligungs-Sperre bis zur Einwilligung der Erziehungsberechtigten',
    'author': 'KLGM UG (haftungsbeschränkt)',
    'website': 'https://www.klgm-consulting.de',
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
        'data/ir_config_parameter_data.xml',
        'data/ir_cron_data.xml',
        'views/event_views.xml',
        'views/kjr_event_statistics_views.xml',
        'views/website_event_templates.xml',
        'views/portal_templates.xml',
    ],
    'assets': {
        'website.website_builder_assets': [
            'kjr_event/static/src/website_builder/**/*',
        ],
        # Einwilligung (19.0.5.9.0): Komfort im Anmeldedialog (Alter rechnen,
        # Einwilligungsfelder markieren). Massgeblich bleibt der Server.
        'web.assets_frontend': [
            'kjr_event/static/src/interactions/kjr_consent_fields.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
