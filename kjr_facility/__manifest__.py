# -*- coding: utf-8 -*-
{
    'name': 'KJR Einrichtungsbuchung',
    'version': '19.0.1.0.0',
    'category': 'Custom/KJR',
    'summary': 'Belegungs- und Buchungsverwaltung für KJR-Einrichtungen (Jugendhaus Diepolz, '
               'Zeltplatz NiSo): Tarife, Verpflegung, Doppelbelegungsprüfung, Rechnung, Website & Portal',
    'author': 'Lukas Klauser / LM Consulting UG',
    'website': 'https://lm-consulting.de',
    'license': 'OPL-1',
    'depends': ['base', 'mail', 'portal', 'website', 'account'],
    'data': [
        'security/kjr_facility_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/kjr_facility_data.xml',
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
        'views/kjr_facility_views.xml',
        'views/kjr_facility_tariff_views.xml',
        'views/kjr_facility_booking_views.xml',
        'views/menu.xml',
        'views/website_templates.xml',
        'report/kjr_facility_report.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'kjr_facility/static/src/css/facility.css',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
