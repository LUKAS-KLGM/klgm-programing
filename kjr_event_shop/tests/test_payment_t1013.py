# -*- coding: utf-8 -*-
"""Zahlungsablauf und Rechnungskontakt (Termin 13.10.2026), 19.0.2.2.0."""
from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestKjrPaymentT1013(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Registration = cls.env['event.registration']
        cls.Params = cls.env['ir.config_parameter'].sudo()
        begin = fields.Datetime.now() + timedelta(days=60)
        cls.event = cls.env['event.event'].create({
            'name': 'Zeltlager (Zahlungstest)',
            'is_kjr': True,
            'date_begin': begin,
            'date_end': begin + timedelta(days=3),
            'seats_limited': True,
            'seats_max': 1,
            'kjr_waitlist_enabled': True,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Teilnahme (Zahlungstest)', 'type': 'service',
            'service_tracking': 'event', 'list_price': 50.0, 'invoice_policy': 'order'})
        cls.ticket = cls.env['event.event.ticket'].create({
            'name': 'Teilnahme', 'event_id': cls.event.id,
            'product_id': cls.product.id, 'price': 50.0})
        cls.partner = cls.env['res.partner'].create({
            'name': 'Eva Muster', 'email': 'eva@example.com'})

    def _order(self, name='Mia', **reg_vals):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [Command.create({
                'product_id': self.product.id, 'event_id': self.event.id,
                'event_ticket_id': self.ticket.id, 'product_uom_qty': 1,
                'price_unit': 50.0})],
        })
        reg = self.Registration.create(dict({
            'event_id': self.event.id, 'name': name, 'email': 'eva@example.com',
            'sale_order_line_id': order.order_line.id}, **reg_vals))
        return order, reg

    def test_unpaid_registration_not_confirmed_until_order_confirmed(self):
        """Bestand (event_sale): erst nach Bestätigung auf der Teilnehmerliste."""
        order, reg = self._order()
        order.write({'state': 'sent'})
        self.assertEqual(reg.state, 'draft')
        self.assertTrue(order.kjr_payment_requested_date)
        order.action_confirm()
        self.assertEqual(reg.state, 'open')

    def test_invoice_on_confirm(self):
        order, _reg = self._order()
        order.action_confirm()
        self.assertEqual(len(order.invoice_ids), 1)
        self.assertEqual(order.invoice_ids.state, 'draft')
        self.Params.set_param('kjr_event_shop.invoice_on_confirm', '0')
        order2, _reg2 = self._order(name='Max')
        order2.action_confirm()
        self.assertFalse(order2.invoice_ids)

    def test_fee_tax_on_ticket_line(self):
        tax = self.env['account.tax'].create({
            'name': '0 % Teilnahme (Zahlungstest)', 'amount': 0.0, 'type_tax_use': 'sale'})
        self.Params.set_param('kjr_event.fee_tax_id', str(tax.id))
        order, _reg = self._order()
        self.assertEqual(order.order_line.tax_ids, tax)

    def test_invoice_partner_moves_to_cart(self):
        order, reg = self._order(
            birthdate='2017-03-01', kjr_street='Bahnhofstraße 1', kjr_zip='87527',
            kjr_city='Sonthofen', guardian_name='Eva Muster',
            guardian_email='eva@example.com', guardian_same_address=True)
        reg._kjr_apply_invoice_partner()
        self.assertEqual(order.partner_invoice_id, reg.kjr_invoice_partner_id)
        self.assertEqual(order.partner_invoice_id.street, 'Bahnhofstraße 1')

    def test_reminder_once_then_release_and_waitlist(self):
        order, reg = self._order()
        order.write({'state': 'sent'})
        # Unbezahlte Anmeldungen belegen keinen Platz (Kern); die Warteliste
        # entsteht über bestätigte Plätze. Hier direkt als Wartelistenplatz.
        _order2, waiting = self._order(name='Wartend', kjr_is_waitlist=True)
        self.assertTrue(waiting.kjr_is_waitlist)
        self.Params.set_param('kjr_event_shop.payment_reminder_days', '7')
        self.Params.set_param('kjr_event_shop.payment_release_days', '5')
        SaleOrder = self.env['sale.order']
        # Noch nicht fällig.
        self.assertEqual(SaleOrder._cron_kjr_payment_reminder(), (0, 0))
        order.kjr_payment_requested_date = fields.Datetime.now() - timedelta(days=8)
        with patch.object(type(self.env['mail.template']), 'send_mail', autospec=True) as send:
            self.assertEqual(SaleOrder._cron_kjr_payment_reminder(), (1, 0))
            # Genau EINE Erinnerung.
            self.assertEqual(SaleOrder._cron_kjr_payment_reminder(), (0, 0))
        self.assertEqual(send.call_count, 1)
        self.assertTrue(order.kjr_payment_release_date)
        order.kjr_payment_reminder_date = fields.Datetime.now() - timedelta(days=6)
        self.assertEqual(SaleOrder._cron_kjr_payment_reminder(), (0, 1))
        self.assertEqual(order.state, 'cancel')
        self.assertEqual(reg.state, 'cancel')
        self.assertFalse(waiting.kjr_is_waitlist, 'Warteliste rückt nach')

    def test_paid_order_not_reminded(self):
        order, _reg = self._order()
        order.action_confirm()
        order.kjr_payment_requested_date = fields.Datetime.now() - timedelta(days=30)
        self.Params.set_param('kjr_event_shop.payment_reminder_days', '7')
        self.assertEqual(self.env['sale.order']._cron_kjr_payment_reminder(), (0, 0))

    def test_cron_inactive_by_default(self):
        cron = self.env.ref('kjr_event_shop.cron_kjr_payment_reminder')
        self.assertFalse(cron.active)
        self.assertEqual(self.env['sale.order']._cron_kjr_payment_reminder(), (0, 0))
