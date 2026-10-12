# -*- coding: utf-8 -*-
{
    'name': 'KJR Brücke: Veranstaltungen ↔ E-Signatur',
    'version': '19.0.1.1.0',
    'category': 'Custom/KJR',
    'summary': 'Einwilligung der Erziehungsberechtigten per Odoo Sign: '
               'Unterschriftsanfrage bei Online-Anmeldung Minderjähriger, '
               'Bestätigung erst nach Unterschrift.',
    'author': 'KLGM UG (haftungsbeschränkt)',
    'website': 'https://www.klgm-consulting.de',
    'license': 'OPL-1',
    # Reine Brücke: hängt an kjr_event (Community, ohne Sign) UND an sign
    # (Enterprise). auto_install = wird automatisch installiert, sobald beide
    # vorhanden sind; ohne Sign bleibt kjr_event beim Einwilligungsverfahren
    # "Bestätigung im Formular". Auch installiert bleibt die Brücke INAKTIV,
    # bis in den Einstellungen "Einwilligung digital einholen" eingeschaltet
    # ist (Systemparameter kjr_event_sign.enabled, bewusst nicht vorbelegt).
    # Achtung: auto_install greift nur bei einer Neuinstallation. In einer
    # bestehenden Datenbank muss das Modul einmal ausdrücklich installiert
    # werden (-i kjr_event_sign), ein Update (-u) reicht nicht.
    'depends': ['kjr_event', 'sign'],
    'data': [
        'data/res_partner_category_data.xml',
        'data/ir_config_parameter_data.xml',
        'data/sign_template_data.xml',
        # 19.0.1.1.0: Feldtypen für die Vorbefüllung aus der Anmeldung und die
        # vorbefüllte Vorlage v2 (nutzt die Rolle aus sign_template_data.xml).
        'data/sign_item_type_data.xml',
        'data/sign_template_consent_v2_data.xml',
        'data/ir_cron_data.xml',
        'views/event_registration_views.xml',
        'views/event_event_views.xml',
        'views/res_config_settings_views.xml',
        'views/website_templates.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': True,
}
