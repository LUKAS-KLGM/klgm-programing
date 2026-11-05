# -*- coding: utf-8 -*-
"""Anzahlung auf 0 % zurücksetzen (Rückmeldung KJR 05.11.2026: keine Anzahlung).

19.0.7.6.0 hat ``deposit_pct_default`` mit 20 % eingeführt; die Spalte wurde dabei
für alle Einrichtungen mit dem Default befüllt. Der KJR nimmt keine Anzahlung.

Zurückgesetzt wird nur, was noch den alten Standard trägt:
- Einrichtungen mit genau 20 % (ein bewusst anderer Wert bleibt),
- Buchungen mit genau 20 %, die noch nicht verbindlich sind (Anfrage, Reservierung)
  und deren Anzahlung nicht als erhalten markiert ist. Verbindliche Buchungen
  haben ihren Vertrag schon erhalten und bleiben unverändert.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    facilities = env['kjr.facility'].with_context(active_test=False).search(
        [('deposit_pct_default', '=', 20.0)])
    facilities.write({'deposit_pct_default': 0.0})
    bookings = env['kjr.facility.booking'].with_context(active_test=False).search([
        ('deposit_pct', '=', 20.0),
        ('state', 'in', ('draft', 'reserved')),
        ('deposit_paid', '=', False),
    ])
    bookings.write({'deposit_pct': 0.0, 'deposit_due_date': False})
    _logger.info('kjr_facility: Anzahlung auf 0 %% gesetzt für %d Einrichtung(en) und %d Buchung(en)',
                 len(facilities), len(bookings))
