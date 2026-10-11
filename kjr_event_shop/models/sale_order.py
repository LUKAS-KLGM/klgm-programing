# -*- coding: utf-8 -*-
import pytz

from odoo import _, api, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Hilfsfunktionen fuer das Angebots-/Auftrags-PDF: Bestellungen mit
    # Kursanmeldungen werden als Reservierungs- bzw. Anmeldebestaetigung
    # ausgegeben (report/sale_report_templates.xml).

    def _kjr_is_event_order(self):
        self.ensure_one()
        return bool(self.order_line.filtered('event_id'))

    @api.depends('order_line.event_id')
    def _compute_require_signature(self):
        """website_sale schaltet die Online-Unterschrift fuer Shop-Bestellungen
        grundsaetzlich ab. Kursanmeldungen sollen im Portal unterschrieben
        werden koennen (E-Signatur), solange die Firmeneinstellung
        "Online-Signatur" aktiv ist."""
        super()._compute_require_signature()
        for order in self.filtered(lambda o: o.website_id and o._kjr_is_event_order()):
            order.require_signature = order.company_id.portal_confirmation_sign

    def _compute_type_name(self):
        """Portal-Ueberschrift und PDF-Dateiname: "Reservierung S00005" statt
        "Angebot S00005" fuer Bestellungen mit Kursanmeldungen."""
        super()._compute_type_name()
        for order in self:
            if order._kjr_is_event_order() and order.state != 'cancel':
                order.type_name = _('Reservierung') if order.state in ('draft', 'sent') else _('Anmeldung')

    def _kjr_pending_transfer_tx(self):
        """Offene Ueberweisung (payment_custom, Status 'pending') zur Bestellung."""
        self.ensure_one()
        return self.sudo().transaction_ids.filtered(
            lambda t: t.provider_id.code == 'custom' and t.state == 'pending'
        )[:1]

    def _kjr_is_paid(self):
        self.ensure_one()
        return bool(self.sudo().transaction_ids.filtered(lambda t: t.state == 'done'))

    def _kjr_payment_deadline(self):
        """Bis wann der Platz reserviert bleibt: Gueltigkeit des Angebots,
        spaetestens aber der Beginn der ersten gebuchten Veranstaltung."""
        self.ensure_one()
        dates = []
        if self.validity_date:
            dates.append(self.validity_date)
        for event in self.order_line.event_id:
            if event.date_begin:
                tz = pytz.timezone(event.date_tz or 'Europe/Berlin')
                dates.append(pytz.utc.localize(event.date_begin).astimezone(tz).date())
        return min(dates) if dates else False

    def _kjr_transfer_accounts(self):
        """Bankkonten des Unternehmens, auf die ueberwiesen werden soll."""
        self.ensure_one()
        Journal = self.env['account.journal'].sudo()
        return Journal.search([
            *Journal._check_company_domain(self.company_id.id),
            ('type', '=', 'bank'),
        ]).bank_account_id
