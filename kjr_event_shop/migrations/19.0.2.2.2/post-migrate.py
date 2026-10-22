# -*- coding: utf-8 -*-
"""19.0.2.2.2 (Prüfbericht 22.10.2026).

1. Mailvorlage Zahlungserinnerung (noupdate) und Hinweistext des
   Überweisungs-Anbieters lagen nur unter en_US (deutscher Text, englischer
   Sprachschlüssel). Ergänzt wird die de_DE-Fassung als Kopie, nur wo sie
   fehlt; gepflegte deutsche Texte bleiben (kjr_event/lang_fill.py).
2. Offene Überweisungen (pending) zu offenen Aufträgen mit KJR-Veranstaltung,
   deren Betrag nach der Steuerumstellung nicht mehr zum Auftrag passt
   (23,80 EUR statt 20,00 EUR), werden an den Auftragsbetrag angeglichen, mit
   Notiz am Auftrag (sale.order._kjr_sync_transfer_amounts).
"""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.kjr_event.lang_fill import fill_missing_lang, fill_module_templates

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    fill_module_templates(env, 'kjr_event_shop')
    providers = env['payment.provider'].sudo().search([
        ('code', '=', 'custom'), ('custom_mode', '=', 'wire_transfer')])
    count = fill_missing_lang(env, providers, ('pending_msg',))
    if count:
        _logger.info('kjr_event_shop 19.0.2.2.2: Hinweistext Überweisung um de_DE ergänzt (%s).',
                     providers.ids)
    orders = env['sale.order'].sudo().search([
        ('state', 'in', ('draft', 'sent')),
        ('order_line', 'any', [('event_id.is_kjr', '=', True)]),
        ('transaction_ids', 'any', [('state', 'in', ('draft', 'pending'))]),
    ])
    synced = orders._kjr_sync_transfer_amounts()
    _logger.info('kjr_event_shop 19.0.2.2.2: %d offene Überweisung(en) angeglichen (%s).',
                 len(synced), synced.ids)
