# -*- coding: utf-8 -*-
from odoo import models


class ResPartnerBank(models.Model):
    _inherit = 'res.partner.bank'

    def _kjr_transfer_rows(self):
        """Bankverbindung als Zeilen (Bezeichnung, Wert) fuer eine Ueberweisung.
        Der Odoo-Standard nennt nur "IBAN - Bank"; fuer eine Ueberweisung
        braucht es auch den Kontoinhaber (Empfaengername) und die BIC."""
        self.ensure_one()
        rows = [
            ('Kontoinhaber', self.acc_holder_name or self.partner_id.name or ''),
            ('IBAN', self.acc_number),
            ('BIC', self.bank_id.bic),
            ('Bank', self.bank_id.name),
        ]
        return [(label, value) for label, value in rows if value]
