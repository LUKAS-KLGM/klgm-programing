# -*- coding: utf-8 -*-
import logging

import pytz

from odoo import _, api, models

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def write(self, vals):
        """Startet die zurückgestellten Einwilligungsanfragen beim Abschluss der Bestellung.

        Im Shop entstehen Anmeldungen zu bezahlten Tickets schon im Warenkorb.
        Die Unterschriftsanfrage an die Erziehungsberechtigten wird dort
        zurückgestellt (event.registration._kjr_consent_defer_request) und erst
        ausgelöst, wenn der Auftrag auf "gesendet" (Checkout, z. B. mit
        Überweisung) oder "Auftrag" (bestätigt bzw. bezahlt) wechselt.

        Ausgewählt werden nur gesperrte, nicht abgesagte Anmeldungen, denen die
        Einwilligung fehlt und deren Geburtsdatum bekannt ist (ohne Geburtsdatum entscheidet
        die Auflösung nach der Online-Anmeldung). _kjr_consent_request_start ist
        idempotent (kjr_event_sign prüft eine bereits gesendete Anfrage). Ein
        Fehler darf den Auftrag nicht kippen; protokolliert werden nur IDs.
        """
        res = super().write(vals)
        if vals.get('state') in ('sent', 'sale'):
            # sudo() VOR dem Zugriff auf die Anmeldungen: der Checkout läuft als
            # Portal- oder öffentlicher Benutzer, der event.registration nicht
            # lesen darf; der Auftrag selbst ist bereits geschrieben.
            # _kjr_consent_releasable() schließt abgesagte Anmeldungen aus
            # (gleiche Auswahl wie _kjr_consent_resolve_holds): eine im
            # Warenkorb- bzw. Angebotsstadium abgesagte Teilnahme bekommt nach
            # Bestätigung oder Zahlung des Auftrags keine Unterschriftsanfrage.
            regs = self.sudo().order_line.registration_ids._kjr_consent_releasable().filtered(
                lambda r: r.consent_missing and r.birthdate)
            if regs:
                savepoint = self.env.cr.savepoint()
                try:
                    with savepoint:
                        regs._kjr_consent_request_start()
                except Exception:  # noqa: BLE001 - der Auftrag hat Vorrang
                    _logger.exception(
                        'KJR Einwilligung: Anfrage zu Auftrag %s fehlgeschlagen '
                        '(Anmeldungen %s).', self.ids, regs.ids)
        return res

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
