# -*- coding: utf-8 -*-
"""Einwilligungs-Sperre bei Anmeldungen mit Verkaufsauftrag (19.0.2.1.0).

Fachliche Leitplanken:

* Eine gesperrte Anmeldung bleibt unbestätigt, auch wenn der Auftrag bestätigt
  wird oder kostenlos ist (der Status-Compute von event_sale würde sonst auf
  "registriert" setzen).
* Nach der Freigabe entscheidet event_sale: kostenlos bzw. verkauft wird
  registriert (Kern-Mails genau einmal), zu bezahlen bleibt unbestätigt, bis der
  Auftrag bestätigt ist. Ein unbezahlter Auftrag wird nie freigegeben.
* Solange der Auftrag ein Warenkorb ist, wird die Unterschriftsanfrage
  zurückgestellt; beim Wechsel auf "gesendet" oder "Auftrag" startet sie.

Angelegt wird wie im Shop: Auftragszeile mit Ticket, die Anmeldung mit dem
Kontext ``kjr_consent_hold_event_id`` (den setzt der Website-Controller). Der
Start der Unterschriftsanfrage ist durch einen Platzhalter ersetzt, damit die
Tests nicht von kjr_event_sign abhängen.
"""
from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.kjr_event.models import kjr_event_document


@tagged('post_install', '-at_install')
class TestKjrConsentHoldSale(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Registration = cls.env['event.registration']
        cls.event = cls.env['event.event'].create({
            'name': 'Zeltlager (Shop-Einwilligungstest)',
            'is_kjr': True,
            'date_begin': '2027-07-10 09:00:00',
            'date_end': '2027-07-15 17:00:00',
            'requires_parental_consent': True,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Teilnahme (Test)',
            'type': 'service',
            'service_tracking': 'event',
            'list_price': 0.0,
        })
        cls.partner = cls.env['res.partner'].create({
            'name': 'Bestellende Person', 'email': 'eltern@example.com'})

    def _order_with_held_registration(self, price, birthdate='2015-01-01', event=None,
                                      **extra):
        """Auftrag mit einer Ticketzeile und einer gesperrten Anmeldung dazu."""
        event = event or self.event
        ticket = self.env['event.event.ticket'].create({
            'name': 'Teilnahme %s' % price,
            'event_id': event.id,
            'product_id': self.product.id,
            'price': price,
        })
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [Command.create({
                'product_id': self.product.id,
                'event_id': event.id,
                'event_ticket_id': ticket.id,
                'product_uom_qty': 1,
                'price_unit': price,
            })],
        })
        reg = self.Registration.with_context(kjr_consent_hold_event_id=event.id).create({
            'event_id': event.id,
            'name': 'Kind',
            'email': 'eltern@example.com',
            'birthdate': birthdate,
            'sale_order_line_id': order.order_line.id,
            **extra,
        })
        reg = self.Registration.browse(reg.id)
        self.assertTrue(reg.kjr_consent_hold)
        self.assertEqual(reg.sale_order_id, order)
        return order, reg

    def _patch_request_start(self):
        return patch.object(type(self.Registration), '_kjr_consent_request_start',
                            autospec=True)

    def test_free_order_confirm_keeps_held_draft(self):
        """Auftrag über 0 Euro bestätigt: die gesperrte Anmeldung bleibt unbestätigt."""
        order, reg = self._order_with_held_registration(0.0)
        with self._patch_request_start():
            order.action_confirm()
        self.assertEqual(order.state, 'sale')
        self.assertEqual(reg.state, 'draft')
        self.assertTrue(reg.kjr_consent_hold)

    def test_release_free_order_opens_with_schedulers(self):
        """Freigabe nach der Einwilligung: registriert, Kern-Mails werden angestoßen."""
        order, reg = self._order_with_held_registration(0.0)
        with self._patch_request_start():
            order.action_confirm()
        with patch.object(type(self.Registration), '_update_mail_schedulers',
                          autospec=True) as schedulers:
            reg.write({'parental_consent': True})
            self.assertEqual(reg.state, 'open')
        self.assertFalse(reg.kjr_consent_hold)
        self.assertTrue(schedulers.called)

    def test_release_unpaid_order_stays_draft_until_confirmed(self):
        """Zu bezahlen: Freigabe lässt die Anmeldung unbestätigt, erst der Auftrag bestätigt."""
        order, reg = self._order_with_held_registration(50.0)
        reg.write({'parental_consent': True})
        self.assertFalse(reg.kjr_consent_hold)
        self.assertEqual(reg.state, 'draft',
                         'Ein unbezahlter Auftrag darf durch die Einwilligung nicht '
                         'registriert werden.')
        order.action_confirm()
        self.assertEqual(reg.state, 'open')

    def test_cart_defers_request(self):
        """Warenkorb (Auftrag im Entwurf): Anfrage wird zurückgestellt."""
        order, reg = self._order_with_held_registration(50.0)
        self.assertEqual(order.state, 'draft')
        self.assertTrue(reg._kjr_consent_defer_request())
        with self._patch_request_start():
            order.write({'state': 'sent'})
        self.assertFalse(reg._kjr_consent_defer_request())

    def test_order_sent_starts_request(self):
        """Wechsel auf "gesendet" startet die Einwilligungsanfrage."""
        order, reg = self._order_with_held_registration(50.0)
        with self._patch_request_start() as request_start:
            order.write({'state': 'sent'})
        self.assertEqual(request_start.call_count, 1)
        self.assertIn(reg, request_start.call_args[0][0])

    def test_order_sent_skips_cancelled_registration(self):
        """Im Warenkorb abgesagte Anmeldung: der Auftragswechsel startet keine Anfrage."""
        order, reg = self._order_with_held_registration(50.0)
        reg.action_cancel()
        self.assertEqual(reg.state, 'cancel')
        self.assertTrue(reg.kjr_consent_hold)
        with self._patch_request_start() as request_start:
            order.write({'state': 'sent'})
        request_start.assert_not_called()

    def test_release_waitlist_with_free_order_stays_on_waitlist(self):
        """Wartelistenplatz mit Auftrag: Freigabe lässt ihn auf der Warteliste (unbestätigt).

        Ohne den Wartelisten-Zweig im Compute würde event_sale den kostenlosen
        Wartelistenplatz nach Wegfall der Sperre ohne Platzprüfung registrieren.
        """
        order, reg = self._order_with_held_registration(0.0, kjr_is_waitlist=True)
        self.assertTrue(reg.kjr_is_waitlist)
        with self._patch_request_start():
            order.action_confirm()
        self.assertEqual(reg.state, 'draft')
        reg.write({'parental_consent': True})
        self.assertFalse(reg.kjr_consent_hold)
        self.assertTrue(reg.kjr_is_waitlist)
        self.assertEqual(reg.state, 'draft',
                         'Ein Wartelistenplatz darf durch die Freigabe nicht registriert '
                         'werden.')
        self.assertFalse(reg.activity_ids.filtered(
            lambda a: a.summary == 'Freigabe nach Einwilligung fehlgeschlagen'))

    def test_cart_gets_no_consent_reminder(self):
        """Abgebrochener Warenkorb: keine Einwilligungs-Erinnerung an die Eltern (E11).

        Erst mit dem Abschluss der Bestellung (Auftrag "gesendet") darf die
        Erinnerung hinausgehen; Cron und Handaktion verhalten sich gleich.
        """
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('kjr_event.automation_active_from', '2000-01-01 00:00:00')
        params.set_param('kjr_event.consent_reminder_lead_days', '30')
        now = fields.Datetime.now()
        event = self.env['event.event'].create({
            'name': 'Bald (Shop-Einwilligungstest)',
            'is_kjr': True,
            'date_begin': now + timedelta(days=5),
            'date_end': now + timedelta(days=8),
            'requires_parental_consent': True,
        })
        order, reg = self._order_with_held_registration(50.0, event=event)
        self.assertTrue(reg.consent_missing)
        self.assertEqual(order.state, 'draft')
        self.assertFalse(self.Registration.search(
            self.Registration._kjr_consent_reminder_domain() + [('id', '=', reg.id)]))
        with patch.object(kjr_event_document, '_kjr_send_template',
                          return_value=True) as send:
            self.Registration._cron_kjr_consent_reminder()
            result = reg.action_kjr_send_consent_reminder()
        send.assert_not_called()
        self.assertFalse(reg.kjr_consent_reminder_sent)
        self.assertEqual(result['params']['type'], 'warning')
        with self._patch_request_start():
            order.write({'state': 'sent'})
        with patch.object(kjr_event_document, '_kjr_send_template',
                          return_value=True) as send:
            self.Registration._cron_kjr_consent_reminder()
        self.assertEqual(send.call_count, 1)
        self.assertTrue(reg.kjr_consent_reminder_sent)
