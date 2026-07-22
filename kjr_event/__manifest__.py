# -*- coding: utf-8 -*-
{
    'name': 'KJR Ferienprogramm & Schulungen',
    # Hinweis für Lukas: Es gibt parallel einen zweiten offenen PR (Dokumente-Block),
    # der ebenfalls von 19.0.2.1.0 abzweigt und auf 19.0.2.2.0 hochzählt. Je nachdem,
    # welcher PR zuerst gemerged wird, muss die Versionsnummer hier ggf. noch auf
    # 19.0.2.4.0 angepasst werden, damit keine zwei Releases dieselbe Version tragen.
    'version': '19.0.2.3.0',
    'category': 'Custom/KJR',
    'summary': 'Erweiterung der Odoo-Veranstaltungen für KJR-Ferienprogramm und Schulungen '
               '(Juleica, Rettungsschwimmer): Altersgruppen, Einwilligung Minderjähriger, '
               'Notfallkontakt, Teilnahmebescheinigung, Website-Dokumente-Block, '
               'Treffpunkt/Wichtig/Webseite',
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
        'views/event_views.xml',
        'views/website_event_templates.xml',
        'views/portal_templates.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
