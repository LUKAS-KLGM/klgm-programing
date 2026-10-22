# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import Command, fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestKjrTicketPriceDisplay(TransactionCase):
    """Ticketdialog zeigt den Preis mit der Steuer aus den Einstellungen (19.0.2.2.1)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        cls.tax19 = cls.env['account.tax'].create({
            'name': 'TP 19 %', 'amount': 19.0, 'type_tax_use': 'sale', 'company_id': company.id})
        cls.tax0 = cls.env['account.tax'].create({
            'name': 'TP 0 %', 'amount': 0.0, 'type_tax_use': 'sale', 'company_id': company.id})
        product = cls.env['product.product'].create({
            'name': 'TP Teilnahme', 'type': 'service', 'service_tracking': 'event',
            'list_price': 20.0, 'taxes_id': [Command.set(cls.tax19.ids)]})
        begin = fields.Datetime.now() + timedelta(days=40)
        cls.event = cls.env['event.event'].create({
            'name': 'TP Freizeit', 'is_kjr': True, 'company_id': company.id,
            'date_begin': begin, 'date_end': begin + timedelta(days=2),
            'event_ticket_ids': [Command.create({
                'name': 'TP Ticket', 'product_id': product.id, 'price': 20.0})],
        })
        cls.ticket = cls.event.event_ticket_ids

    def _refresh(self):
        self.ticket.invalidate_recordset(['price_incl', 'price_reduce_taxinc'])

    def test_ohne_einstellung_produktsteuer(self):
        self.env['ir.config_parameter'].sudo().set_param('kjr_event.fee_tax_id', '')
        self._refresh()
        self.assertAlmostEqual(self.ticket.price_incl, 23.8)
        self.assertAlmostEqual(self.ticket.price_reduce_taxinc, 23.8)

    def test_mit_einstellung_null_prozent(self):
        self.env['ir.config_parameter'].sudo().set_param('kjr_event.fee_tax_id', str(self.tax0.id))
        self._refresh()
        self.assertAlmostEqual(self.ticket.price_incl, 20.0)
        self.assertAlmostEqual(self.ticket.price_reduce_taxinc, 20.0)
