# -*- coding: utf-8 -*-
{
    'name': 'KJR App',
    'version': '19.0.8.3.0',
    'category': 'Custom/KJR',
    'summary': 'Zuschussverwaltung, Juleica, Vollversammlung, Fördermittel-Akquise und Verwendungsnachweis für Kreisjugendringe (Odoo 19)',
    'author': 'KLGM UG (haftungsbeschränkt)',
    'website': 'https://www.klgm-consulting.de',
    'license': 'OPL-1',
    # Hinweis: Einrichtungsbuchung (Diepolz/NiSo), Materialverleih, Ferienprogramm/Schulungen
    # und Newsletter sind als eigenständige Folge-Module geplant (Roadmap) und bringen ihre
    # Abhängigkeiten (sale_renting, event, mass_mailing) selbst mit. Dieses Modul bleibt schlank.
    # 'sign' (Enterprise) ist optional: fehlt es im Build, wird das Modul sonst
    # übersprungen ("Unmet dependencies"). Die digitale Unterschrift degradiert
    # sauber (PDF wird angehängt), siehe action_send_signature.
    'depends': ['base', 'mail', 'portal', 'website', 'account'],
    'data': [
        'security/kjr_grant_security.xml',
        'security/ir.model.access.csv',
        # Seed-/Stammdaten für den ersten Staging-Build deaktiviert (Build hatte
        # geskippt). Nach erfolgreicher Installation einzeln wieder aktivieren und
        # die Daten ggf. per UI/Import nachpflegen.
        'data/ir_sequence_data.xml',
        'data/ir_config_parameter_data.xml',
        'data/kjr_grant_type_data.xml',
        'data/auth_signup_data.xml',
        'data/website_menu_data.xml',
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
        'views/kjr_grant_type_views.xml',
        'views/kjr_grant_application_views.xml',
        'views/kjr_grant_settlement_views.xml',
        'views/kjr_grant_budget_views.xml',
        'views/kjr_juleica_views.xml',
        'views/kjr_assembly_views.xml',
        'views/kjr_funding_views.xml',
        'views/res_partner_views.xml',
        'views/kjr_volunteer_log_views.xml',
        'views/menu.xml',
        'views/portal_templates.xml',
        'report/kjr_report_actions.xml',
        'report/kjr_bescheid_template.xml',
        'report/kjr_jahresbericht_template.xml',
        'report/kjr_ehrenamt_template.xml',
        'report/kjr_verwendungsnachweis_template.xml',
        'report/kjr_datenauskunft_template.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'kjr_grant/static/src/css/portal.css',
        ],
    },
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
}
