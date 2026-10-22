# -*- coding: utf-8 -*-
"""Einstellungen Zahlungsablauf (Termin 13.10.2026), 19.0.2.2.0."""
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    kjr_event_shop_payment_reminder_days = fields.Integer(
        string='Zahlungserinnerung nach (Tagen)',
        config_parameter='kjr_event_shop.payment_reminder_days',
        help='Tage nach Abschluss der Bestellung ohne Zahlungseingang bis zur (einzigen) '
             'Zahlungserinnerung. 0 = keine Erinnerung.')
    kjr_event_shop_payment_release_days = fields.Integer(
        string='Platz freigeben nach (Tagen)',
        config_parameter='kjr_event_shop.payment_release_days',
        help='Tage nach der Zahlungserinnerung ohne Zahlungseingang, bis der Auftrag '
             'storniert und der Platz freigegeben wird (Warteliste rückt nach). 0 = nie.')
    kjr_event_shop_invoice_on_confirm = fields.Boolean(
        string='Rechnung beim Bestätigen erzeugen',
        config_parameter='kjr_event_shop.invoice_on_confirm',
        help='Beim Bestätigen eines Auftrags mit KJR-Veranstaltung (nach Zahlungseingang) '
             'entsteht die Rechnung automatisch. Gebucht wird sie nur, wenn '
             '"kjr_event.invoice_auto_post" gesetzt ist; versendet wird nichts.')

    def set_values(self):
        old_tax = self.env['ir.config_parameter'].sudo().get_param('kjr_event.fee_tax_id')
        super().set_values()
        new_tax = self.env['ir.config_parameter'].sudo().get_param('kjr_event.fee_tax_id')
        if (old_tax or False) != (new_tax or False):
            # Steuer auf Teilnahmegebühren geändert: offene Angebote/Aufträge
            # (Warenkorb, gesendet) neu besteuern (Prüfbericht 22.10.2026).
            self.env['sale.order']._kjr_recompute_fee_taxes()
        # res.config.settings löscht einen Boolean-Parameter beim Abwählen; der
        # Code liest "nicht gesetzt" aber als "ein" (Auslieferungszustand).
        # Deshalb "aus" ausdrücklich speichern.
        if not self.kjr_event_shop_invoice_on_confirm:
            self.env['ir.config_parameter'].sudo().set_param(
                'kjr_event_shop.invoice_on_confirm', '0')
