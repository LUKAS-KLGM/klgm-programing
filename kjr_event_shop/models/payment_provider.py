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
            blocks = []
            for acc in accounts:
                holder = acc.acc_holder_name or acc.partner_id.name or ''
                rows = [
                    ('Kontoinhaber', holder),
                    ('IBAN', acc.acc_number),
                    ('BIC', acc.bank_id.bic),
                    ('Bank', acc.bank_id.name),
                ]
                blocks.append('<li><p>%s</p></li>' % '<br>'.join(
                    '<strong>%s:</strong> %s' % (label, escape(value))
                    for label, value in rows if value))
            provider.pending_msg = (
                '<div><h5>Bitte überweisen Sie den Betrag auf folgendes Konto</h5>'
                '<h6>%s</h6><ul class="list-unstyled">%s</ul></div>'
            ) % ('Bankverbindung' if len(accounts) == 1 else 'Bankverbindungen', ''.join(blocks))
