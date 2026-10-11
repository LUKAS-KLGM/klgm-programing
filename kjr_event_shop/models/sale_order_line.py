# -*- coding: utf-8 -*-
import json
import re

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

    def _kjr_event_image_url(self):
        """URL des Titelbilds der Veranstaltung (website_event speichert es als
        CSS background-image in cover_properties) oder False. Das Bild ist
        oeffentlich, weil es auch auf der Veranstaltungsseite steht."""
        self.ensure_one()
        if not self.event_id:
            return False
        try:
            props = json.loads(self.event_id.sudo().cover_properties or '{}')
        except ValueError:
            return False
        match = re.match(r"""^url\(\s*['"]?([^'")]+)['"]?\s*\)$""",
                         (props.get('background-image') or '').strip())
        url = match and match.group(1)
        # nur lokale Bilder, keine fremden Hosts und keine Platzhalter
        return url if url and url.startswith('/') and not url.startswith('//') else False
