# -*- coding: utf-8 -*-
{
    'name': 'KJR App',
    'version': '19.0.17.0.0',
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
    # 'auth_signup' ausdrücklich: controllers/signup.py und models/res_users.py
    # importieren daraus, views/auth_signup_templates.xml erbt auth_signup.signup.
    'depends': ['base', 'mail', 'portal', 'auth_signup', 'website', 'account'],
    'data': [
        'security/kjr_grant_security.xml',
        'security/ir.model.access.csv',
        # Seed-/Stammdaten. Alle Dateien sind aktiv. Sie liegen jeweils unter
        # <data noupdate="1">, damit im Backend gepflegte Werte ein Modulupdate
        # überleben. Kehrseite: Änderungen an bereits ausgelieferten Datensätzen
        # erreichen Bestandsinstanzen nur über ein Migrationsskript (migrations/).
        'data/ir_sequence_data.xml',
        'data/ir_config_parameter_data.xml',
        'data/kjr_grant_type_data.xml',
        'data/auth_signup_data.xml',
        'data/website_menu_data.xml',
        'data/mail_template_data.xml',
        'data/kjr_affiliation_mail_template_data.xml',
        'data/kjr_assembly_mail_template_data.xml',
        'data/ir_cron_data.xml',
        # Löschfrist und Cron der Anmeldungen zur Vollversammlung (DSGVO).
        'data/kjr_assembly_data.xml',
        'views/kjr_grant_type_views.xml',
        'views/kjr_grant_application_views.xml',
        'views/kjr_grant_settlement_views.xml',
        'views/kjr_grant_payout_run_views.xml',
        'views/kjr_grant_budget_views.xml',
        'views/kjr_juleica_views.xml',
        'views/kjr_assembly_views.xml',
        'views/kjr_funding_views.xml',
        'views/kjr_affiliation_request_views.xml',
        'views/res_partner_views.xml',
        'views/kjr_volunteer_log_views.xml',
        'views/res_config_settings_views.xml',
        'views/res_config_settings_apply_views.xml',
        'views/menu.xml',
        'views/portal_templates.xml',
        'views/kjr_assembly_portal_templates.xml',
        'views/auth_signup_templates.xml',
        'report/kjr_report_actions.xml',
        'report/kjr_bescheid_template.xml',
        'report/kjr_jahresbericht_template.xml',
        'report/kjr_ehrenamt_template.xml',
        'report/kjr_verwendungsnachweis_template.xml',
        'report/kjr_datenauskunft_template.xml',
        'report/kjr_tn_liste_template.xml',
        'report/kjr_assembly_protokoll_template.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'kjr_grant/static/src/css/portal.css',
            'kjr_grant/static/src/interactions/kjr_signup_club.js',
            'kjr_grant/static/src/interactions/kjr_apply_totals.js',
        ],
    },
    # Kein 'images'-Eintrag: der Schlüssel benennt die Screenshots bzw. das
    # Titelbild für den App Store, nicht das Icon. Das Icon zieht Odoo fest aus
    # static/description/icon.png (odoo/modules/module.py: get_module_icon()).
    # Ein Titelbild gibt es für dieses Kundenmodul nicht; der bisherige Eintrag
    # zeigte auf das Icon und hätte es als Screenshot ausgeliefert.
    # Blendet bei der Installation die nicht benötigten Standardrubriken
    # auf der Portalseite „Mein Konto" aus (siehe hooks.py).
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': True,
    'auto_install': False,
}
