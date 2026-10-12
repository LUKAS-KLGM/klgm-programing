# -*- coding: utf-8 -*-
{
    'name': 'KJR Brücke: Einrichtungen ↔ E-Signatur',
    'version': '19.0.1.0.0',
    'category': 'Custom/KJR',
    'summary': 'Buchungsvertrag der Einrichtungsbuchung digital unterschreiben (Odoo Sign).',
    'description': """
Brücke zwischen kjr_facility (Community) und sign (Enterprise).
Beim verbindlichen Buchen erhält der Mieter statt der Vertragsmail eine
Unterschriftsanfrage. Die Unterschrift markiert den Vertrag als unterschrieben.
Standard AUS: wirksam erst, wenn in den Einstellungen eingeschaltet.
Benötigt kjr_facility >= 19.0.7.4.0 (Erweiterungsstelle _send_contract).
""",
    'author': 'KLGM UG (haftungsbeschränkt)',
    'website': 'https://www.klgm-consulting.de',
    'license': 'OPL-1',
    # Reine Brücke: kjr_facility (Community, ohne Sign) und sign (Enterprise).
    # auto_install greift nur bei einer Neuinstallation; in einer bestehenden
    # Datenbank einmal ausdrücklich installieren (-i kjr_facility_sign).
    # Auch installiert bleibt die Brücke INAKTIV, bis in den Einstellungen
    # "Vertrag digital unterschreiben" eingeschaltet ist (Systemparameter
    # kjr_facility_sign.enabled, bewusst nicht vorbelegt).
    # Icon folgt später (bewusst kein 'images'-Eintrag).
    'depends': ['kjr_facility', 'sign'],
    'data': [
        'data/sign_item_role_data.xml',
        'data/res_partner_category_data.xml',
        'data/ir_cron_data.xml',
        'views/kjr_facility_booking_views.xml',
        'views/kjr_facility_views.xml',
        'views/res_config_settings_views.xml',
        'views/website_templates.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': True,
}
