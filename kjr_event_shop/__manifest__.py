# -*- coding: utf-8 -*-
{
    'name': 'KJR Brücke: Veranstaltungen ↔ Shop',
    'version': '19.0.1.0.0',
    'category': 'Custom/KJR',
    'summary': 'Bestellbestätigung im Shop: Kursname statt Ticketname, '
               '"Referenz" statt "Mitteilungen", vollständige Bankverbindung.',
    'author': 'KLGM UG (haftungsbeschränkt)',
    'website': 'https://www.klgm-consulting.de',
    'license': 'OPL-1',
    # Reine Brücke: kjr_event haengt bewusst NICHT von der Sales-App ab. Dieses
    # Modul installiert sich automatisch, sobald kjr_event, website_event_sale
    # und payment_custom (Ueberweisung) vorhanden sind.
    'depends': ['kjr_event', 'website_event_sale', 'payment_custom'],
    'data': [
        'views/website_sale_templates.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': True,
}
