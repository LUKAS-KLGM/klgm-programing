# -*- coding: utf-8 -*-
{
    'name': 'KJR Brücke: Veranstaltungen ↔ Shop',
    'version': '19.0.2.2.1',
    'category': 'Custom/KJR',
    'summary': 'Bestellbestätigung im Shop: Kursname statt Ticketname, '
               '"Referenz" statt "Mitteilungen", vollständige Bankverbindung, Kursbild; '
               'Angebots-PDF als Reservierungs-/Anmeldebestätigung; '
               'Einwilligungs-Sperre bei Anmeldungen mit Verkaufsauftrag; '
               'Rechnungskontakt mit Anschrift, Rechnung beim Bestätigen, eine '
               'Zahlungserinnerung mit Platzfreigabe, Steuer auf Teilnahmegebühren.',
    'author': 'KLGM UG (haftungsbeschränkt)',
    'website': 'https://www.klgm-consulting.de',
    'license': 'OPL-1',
    # Reine Brücke: kjr_event haengt bewusst NICHT von der Sales-App ab. Dieses
    # Modul installiert sich automatisch, sobald kjr_event, website_event_sale
    # und payment_custom (Ueberweisung) vorhanden sind.
    'depends': ['kjr_event', 'website_event_sale', 'payment_custom', 'l10n_din5008_sale'],
    'data': [
        'views/website_sale_templates.xml',
        'views/payment_templates.xml',
        'report/sale_report_templates.xml',
        'data/kjr_event_shop_data.xml',
        'views/res_config_settings_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': True,
}
