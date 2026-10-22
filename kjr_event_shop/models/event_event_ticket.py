# -*- coding: utf-8 -*-
from odoo import api, models


class EventEventTicket(models.Model):
    _inherit = 'event.event.ticket'

    # Der Ticketdialog der Website zeigt price_incl bzw. price_reduce_taxinc. Der Kern
    # rechnet dafür mit der Produktsteuer (meist 19 %), der Warenkorb aber mit der
    # Steuer auf Teilnahmegebühren aus den Einstellungen (Termin 13.10.2026: 0 %).
    # Sonst stand im Dialog 23,80 € und im Warenkorb 20,00 €.

    def _kjr_display_taxes(self):
        self.ensure_one()
        taxes = self.event_id._kjr_fee_taxes() if self.event_id else self.env['account.tax']
        if taxes:
            return taxes
        return self.product_id.taxes_id.filtered(
            lambda tax: tax.company_id == self.event_id.company_id)

    def _compute_price_reduce_taxinc(self):
        super()._compute_price_reduce_taxinc()
        for ticket in self.filtered(lambda t: t.event_id.is_kjr):
            taxes = ticket._kjr_display_taxes()
            company = ticket.event_id.company_id
            ticket.price_reduce_taxinc = taxes.compute_all(
                ticket.price_reduce, company.currency_id, 1.0,
                product=ticket.product_id)['total_included']

    @api.depends('event_id.is_kjr')
    def _compute_price_incl(self):
        super()._compute_price_incl()
        for ticket in self.filtered(lambda t: t.event_id.is_kjr and t.product_id and t.price):
            taxes = ticket._kjr_display_taxes()
            ticket.price_incl = taxes.compute_all(
                ticket.price, ticket.currency_id, 1.0,
                product=ticket.product_id)['total_included']
