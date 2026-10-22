# -*- coding: utf-8 -*-
from markupsafe import escape

from odoo import models


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    def action_recompute_pending_msg(self):
        """Der Odoo-Standard nennt nur "IBAN - Bank". Fuer eine Ueberweisung
        braucht es auch den Kontoinhaber (Empfaengername) und die BIC."""
        super().action_recompute_pending_msg()
        if self.env['ir.module.module']._get('account_payment').state != 'installed':
            return
        for provider in self.filtered(lambda p: p.custom_mode == 'wire_transfer'):
            accounts = self.env['account.journal'].search([
                *self.env['account.journal']._check_company_domain(provider.company_id.id),
                ('type', '=', 'bank'),
            ]).bank_account_id
            if not accounts:
                continue
            blocks = [
                '<li><p>%s</p></li>' % '<br>'.join(
                    '<strong>%s:</strong> %s' % (label, escape(value))
                    for label, value in acc._kjr_transfer_rows())
                for acc in accounts
            ]
            msg = (
                '<div><h5>Bitte überweisen Sie den Betrag auf folgendes Konto</h5>'
                '<h6>%s</h6><ul class="list-unstyled">%s</ul></div>'
            ) % ('Bankverbindung' if len(accounts) == 1 else 'Bankverbindungen', ''.join(blocks))
            provider.pending_msg = msg
            # Prüfbericht 22.10.2026: der Text ist deutsch, gespeichert wurde er
            # aber nur in der Sprache des Aufrufs (beim Installieren en_US).
            # Deshalb in jeder aktiven Sprache denselben Text setzen.
            provider._update_field_translations('pending_msg', {
                code: msg for code, _name in self.env['res.lang'].get_installed()})
