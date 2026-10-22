# -*- coding: utf-8 -*-
"""Prüfbericht 22.10.2026 (19.0.2.2.2): Überweisungsbetrag, Erinnerung ohne
E-Mail, Rechnungskontakt im gemeinsamen Warenkorb, deutsche Mailvorlage."""
import json
from datetime import timedelta

from odoo import Command, fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.kjr_event.lang_fill import fill_module_templates


@tagged('post_install', '-at_install')
class TestKjrAuditN2(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Registration = cls.env['event.registration']
        cls.Params = cls.env['ir.config_parameter'].sudo()
        begin = fields.Datetime.now() + timedelta(days=60)
        cls.event = cls.env['event.event'].create({
            'name': 'Ferienfahrt (Prüfbericht)',
            'is_kjr': True,
            'date_begin': begin,
            'date_end': begin + timedelta(days=2),
            'seats_limited': True,
            'seats_max': 10,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Teilnahme (Prüfbericht)', 'type': 'service',
            'service_tracking': 'event', 'list_price': 20.0, 'invoice_policy': 'order'})
        cls.ticket = cls.env['event.event.ticket'].create({
            'name': 'Teilnahme', 'event_id': cls.event.id,
            'product_id': cls.product.id, 'price': 20.0})
        cls.partner = cls.env['res.partner'].create({
            'name': 'Eva Muster', 'email': 'eva@example.com'})
        cls.tax0 = cls.env['account.tax'].create({
            'name': '0 % Teilnahme (Prüfbericht)', 'amount': 0.0, 'type_tax_use': 'sale'})
        cls.Params.set_param('kjr_event.fee_tax_id', str(cls.tax0.id))

    def _order(self, partner=None, regs=1):
        order = self.env['sale.order'].create({
            'partner_id': (partner or self.partner).id,
            'order_line': [Command.create({
                'product_id': self.product.id, 'event_id': self.event.id,
                'event_ticket_id': self.ticket.id, 'product_uom_qty': regs,
                'price_unit': 20.0})],
        })
        created = self.Registration.browse()
        for i in range(regs):
            created |= self.Registration.create({
                'event_id': self.event.id, 'name': 'Teilnehmer:in %s' % i,
                'email': 'eva@example.com', 'sale_order_line_id': order.order_line.id})
        return order, created

    def _transfer_tx(self, order, amount):
        provider = self.env.ref('payment.payment_provider_transfer')
        return self.env['payment.transaction'].sudo().create({
            'provider_id': provider.id,
            'payment_method_id': self.env.ref('payment_custom.payment_method_wire_transfer').id,
            'amount': amount,
            'currency_id': order.currency_id.id,
            'partner_id': order.partner_id.id,
            'reference': '%s-n2-%s' % (order.name, amount),
            'sale_order_ids': [Command.set(order.ids)],
            'state': 'pending',
        })

    # ------------------------------------------------------------------
    # Befund: Überweisung 23,80 EUR, Auftrag 20,00 EUR
    # ------------------------------------------------------------------
    def test_recompute_fee_taxes_syncs_pending_transfer(self):
        order, _regs = self._order()
        order.write({'state': 'sent'})
        self.assertEqual(order.amount_total, 20.0)
        stale = self._transfer_tx(order, 23.80)
        self.env['sale.order']._kjr_recompute_fee_taxes()
        self.assertEqual(stale.amount, 20.0, 'Überweisung auf den Auftragsbetrag angeglichen')
        self.assertEqual(stale.state, 'pending', 'Status und Referenz bleiben')
        self.assertIn('angeglichen', order.message_ids[:1].body)
        self.assertFalse(order._kjr_sync_transfer_amounts(), 'zweiter Lauf ändert nichts')

    def test_sync_leaves_matching_and_paid_alone(self):
        order, _regs = self._order()
        order.write({'state': 'sent'})
        ok = self._transfer_tx(order, 20.0)
        self.assertFalse(order._kjr_sync_transfer_amounts())
        self.assertEqual(ok.amount, 20.0)
        # Bezahlt (done): nichts anfassen.
        paid_order, _r = self._order()
        paid_order.write({'state': 'sent'})
        done = self._transfer_tx(paid_order, 20.0)
        done._set_done()
        other = self._transfer_tx(paid_order, 23.80)
        self.assertFalse(paid_order._kjr_sync_transfer_amounts())
        self.assertEqual(other.amount, 23.80)

    # ------------------------------------------------------------------
    # Befund: Kunde ohne E-Mail reserviert unbegrenzt
    # ------------------------------------------------------------------
    def test_order_without_email_gets_activity_then_release(self):
        no_mail = self.env['res.partner'].create({'name': 'Ohne Mail'})
        order, regs = self._order(partner=no_mail)
        order.write({'state': 'sent'})
        self.Params.set_param('kjr_event_shop.payment_reminder_days', '7')
        self.Params.set_param('kjr_event_shop.payment_release_days', '5')
        order.kjr_payment_requested_date = fields.Datetime.now() - timedelta(days=8)
        SaleOrder = self.env['sale.order']
        self.assertEqual(SaleOrder._cron_kjr_payment_reminder(), (1, 0))
        self.assertTrue(order.kjr_payment_reminder_date)
        self.assertTrue(order.activity_ids.filtered(
            lambda a: a.summary == 'Zahlungserinnerung ohne E-Mail'))
        self.assertEqual(SaleOrder._cron_kjr_payment_reminder(), (0, 0), 'nur einmal')
        order.kjr_payment_reminder_date = fields.Datetime.now() - timedelta(days=6)
        self.assertEqual(SaleOrder._cron_kjr_payment_reminder(), (0, 1))
        self.assertEqual(order.state, 'cancel')
        self.assertEqual(regs.state, 'cancel')

    # ------------------------------------------------------------------
    # Befund: Geschwister im selben Warenkorb, doppelte Kontakte
    # ------------------------------------------------------------------
    def _minor_vals(self, **kw):
        vals = dict(birthdate='2016-03-01', kjr_street='Bahnhofstraße 1', kjr_zip='87527',
                    kjr_city='Sonthofen', guardian_name='Eva Muster',
                    guardian_email='eva@example.com', guardian_phone='0831 1',
                    guardian_same_address=True)
        vals.update(kw)
        return vals

    def test_same_cart_siblings_share_guardian_contact(self):
        public = self.env.ref('base.public_partner')
        order, regs = self._order(partner=public, regs=2)
        first, second = regs
        first.write(self._minor_vals())
        second.write(self._minor_vals(guardian_name='  eva   muster '))
        Partner = self.env['res.partner']
        before = Partner.search_count([])
        public_user = self.env.ref('base.public_user')
        first.with_user(public_user).sudo()._kjr_apply_invoice_partner()
        second.with_user(public_user).sudo()._kjr_apply_invoice_partner()
        self.assertEqual(Partner.search_count([]), before + 1, 'nur EIN Kontakt je Warenkorb')
        self.assertEqual(first.kjr_invoice_partner_id, second.kjr_invoice_partner_id)
        self.assertEqual(order.partner_invoice_id, first.kjr_invoice_partner_id)
        self.assertEqual(order.partner_id, first.kjr_invoice_partner_id)

    def test_other_cart_never_reused_for_guests(self):
        public = self.env.ref('base.public_partner')
        order_a, (reg_a,) = self._order(partner=public)
        order_b, (reg_b,) = self._order(partner=public)
        reg_a.write(self._minor_vals())
        reg_b.write(self._minor_vals())
        public_user = self.env.ref('base.public_user')
        reg_a.with_user(public_user).sudo()._kjr_apply_invoice_partner()
        reg_b.with_user(public_user).sudo()._kjr_apply_invoice_partner()
        self.assertNotEqual(reg_a.kjr_invoice_partner_id, reg_b.kjr_invoice_partner_id,
                            'Datenschutz: kein Abgleich über Warenkörbe hinweg')

    def test_mixed_cart_keeps_first_invoice_address(self):
        public = self.env.ref('base.public_partner')
        order, regs = self._order(partner=public, regs=2)
        minor, adult = regs
        minor.write(self._minor_vals())
        adult.write({'birthdate': '1990-01-01', 'name': 'Max Groß', 'email': 'max@example.com',
                     'kjr_street': 'Marktplatz 2', 'kjr_zip': '87509', 'kjr_city': 'Immenstadt'})
        minor._kjr_apply_invoice_partner()
        adult._kjr_apply_invoice_partner()
        self.assertNotEqual(minor.kjr_invoice_partner_id, adult.kjr_invoice_partner_id)
        self.assertEqual(order.partner_invoice_id, minor.kjr_invoice_partner_id,
                         'Rechnungsadresse wechselt nicht mit jeder Anmeldung')
        self.assertIn('verschiedenen', order.message_ids[:1].body)

    # ------------------------------------------------------------------
    # Befund: Mailvorlage 78 nur en_US
    # ------------------------------------------------------------------
    def test_payment_reminder_template_gets_german_copy(self):
        self.env['res.lang']._activate_lang('de_DE')
        template = self.env.ref('kjr_event_shop.mail_template_payment_reminder')
        self.env.cr.execute(
            "UPDATE mail_template SET subject = %s, body_html = %s WHERE id = %s",
            [json.dumps({'en_US': 'Zahlungserinnerung: {{ object.name }}'}),
             json.dumps({'en_US': '<p>Text</p>'}), template.id])
        template.invalidate_recordset()
        fill_module_templates(self.env, 'kjr_event_shop')
        self.env.cr.execute("SELECT subject, body_html FROM mail_template WHERE id = %s",
                            [template.id])
        subject, body = self.env.cr.fetchone()
        self.assertEqual(subject.get('de_DE'), 'Zahlungserinnerung: {{ object.name }}')
        self.assertEqual(body.get('de_DE'), '<p>Text</p>')
        # Gepflegte deutsche Fassung bleibt.
        template.with_context(lang='de_DE').subject = 'Eigener Betreff'
        fill_module_templates(self.env, 'kjr_event_shop')
        self.assertEqual(template.with_context(lang='de_DE').subject, 'Eigener Betreff')
