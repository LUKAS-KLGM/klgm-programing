# -*- coding: utf-8 -*-
from odoo import api, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.depends('event_id.name')
    def _compute_name_short(self):
        """website_event_sale zeigt im Warenkorb/in der Bestelluebersicht den
        Ticketnamen (meist nur "Standard"). Fuer Teilnehmende zaehlt der Kurs:
        Kursname, der Ticketname nur dann dahinter, wenn er etwas aussagt."""
        super()._compute_name_short()
        for line in self:
            if line.event_id:
                ticket = line.event_ticket_id.name or ''
                if ticket and ticket.strip().lower() not in ('standard', 'registration', 'anmeldung'):
                    line.name_short = '%s (%s)' % (line.event_id.name, ticket)
                else:
                    line.name_short = line.event_id.name
