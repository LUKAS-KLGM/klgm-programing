# -*- coding: utf-8 -*-
"""19.0.2.2.0 (Termin 13.10.2026, Prüfbericht 22.10.2026).

1. Offene Bestandsaufträge ('sent') mit KJR-Veranstaltung bekommen ein
   Anforderungsdatum (= Zeitpunkt des Updates). Sonst fielen sie dauerhaft aus
   Zahlungserinnerung und Platzfreigabe heraus. Die Frist beginnt bewusst erst
   mit dem Update, nicht rückwirkend.
2. Steuer auf Teilnahmegebühren (Entscheidung 13.10.: 0 %): Ist
   kjr_event.fee_tax_id leer, wird die aktive 0-%-Verkaufssteuer
   "Nicht steuerbare Umsätze" aus dem deutschen Kontenrahmen gesetzt (xmlid
   <firma>_tax_not_taxable_skr03/skr04), sofern sie eindeutig gefunden wird;
   sonst nur eine Warnung. Die Wahl ist mit der Steuerberatung zu bestätigen
   und in den Einstellungen änderbar. Danach werden offene Warenkörbe und
   Angebote neu besteuert.
"""
import logging

from odoo import SUPERUSER_ID, api, fields

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Order = env['sale.order']
    orders = Order.search([
        ('state', '=', 'sent'),
        ('kjr_payment_requested_date', '=', False),
        ('order_line', 'any', [('event_id.is_kjr', '=', True)]),
    ])
    if orders:
        orders.write({'kjr_payment_requested_date': fields.Datetime.now()})
        _logger.info('kjr_event_shop 19.0.2.2.0: Anforderungsdatum für %d offene Aufträge '
                     'gesetzt (%s).', len(orders), orders.ids)

    params = env['ir.config_parameter'].sudo()
    if not params.get_param('kjr_event.fee_tax_id'):
        data = env['ir.model.data'].search([
            ('model', '=', 'account.tax'),
            '|', ('name', '=like', '%\\_tax_not_taxable_skr03'),
            ('name', '=like', '%\\_tax_not_taxable_skr04'),
        ])
        taxes = env['account.tax'].browse(data.mapped('res_id')).exists().filtered(
            lambda t: t.active and t.type_tax_use == 'sale' and not t.amount
            and t.company_id == env.company)
        if len(taxes) == 1:
            params.set_param('kjr_event.fee_tax_id', str(taxes.id))
            _logger.info('kjr_event_shop 19.0.2.2.0: Steuer auf Teilnahmegebühren auf "%s" '
                         '(id %s) gesetzt. Bitte mit der Steuerberatung bestätigen.',
                         taxes.display_name, taxes.id)
        else:
            _logger.warning('kjr_event_shop 19.0.2.2.0: keine eindeutige 0-%%-Steuer gefunden; '
                            'Steuer auf Teilnahmegebühren bitte in den Einstellungen setzen '
                            '(sonst gilt die Produktsteuer).')
    if params.get_param('kjr_event.fee_tax_id'):
        count = Order._kjr_recompute_fee_taxes()
        _logger.info('kjr_event_shop 19.0.2.2.0: %d offene Auftragszeilen neu besteuert.', count)
