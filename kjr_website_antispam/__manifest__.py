# -*- coding: utf-8 -*-
{
    'name': 'KJR Spam-Schutz für Website-Formulare',
    'version': '19.0.1.0.0',
    'category': 'Custom/KJR',
    'summary': 'Unsichtbarer Spam-Schutz (Honeypot und signiertes Zeittoken) für '
               'Website-Formulare, Veranstaltungsanmeldung und KJR-Formulare',
    'description': """
Spam-Schutz ohne Drittanbieter
==============================
Hängt sich an den Odoo-Standard-Hook ``ir.http._verify_request_recaptcha_token``,
den auch reCAPTCHA und Cloudflare Turnstile benutzen. Geprüft werden nur die
Aktionen aus dem Systemparameter ``kjr_website_antispam.actions``
(Standard: Website-Formulare, Veranstaltungsanmeldung, alle ``kjr_*``-Aktionen).
Login, Registrierung und Passwort-Zurücksetzen sind nie betroffen.

Betrieb, Notbremse und optionale Einrichtung von Cloudflare Turnstile: siehe README.md.
""",
    'author': 'KLGM UG (haftungsbeschränkt)',
    'website': 'https://www.klgm-consulting.de',
    'license': 'OPL-1',
    # website_event: das Modul erweitert das Teilnehmerformular und die
    # Fehlermeldung der Veranstaltungsanmeldung (views/templates.xml).
    'depends': ['website', 'website_event'],
    'data': [
        'data/ir_config_parameter_data.xml',
        'views/templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'kjr_website_antispam/static/src/interactions/kjr_antispam.js',
            'kjr_website_antispam/static/src/scss/kjr_antispam.scss',
        ],
    },
    # Kein 'images'-Eintrag (Vorbild kjr_grant): der Schlüssel benennt
    # Screenshots für den App Store, nicht das Icon. Das Icon zieht Odoo fest aus
    # static/description/icon.png; die Datei erzeugt tools/icons/build_icons.py.
    'installable': True,
    'application': False,
    # Bewusst kein auto_install: auto_install greift beim Update ohnehin nicht,
    # die Installation erfolgt gezielt mit -i kjr_website_antispam (Rollout
    # zuerst im Modus 'log', siehe README.md).
    'auto_install': False,
}
