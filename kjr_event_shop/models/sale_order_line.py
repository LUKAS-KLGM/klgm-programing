# -*- coding: utf-8 -*-
import json
import re

import pytz

from odoo import api, models

# Ticketnamen, die nichts aussagen und deshalb nicht angezeigt werden
GENERIC_TICKET_NAMES = ('standard', 'registration', 'anmeldung')


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _kjr_ticket_suffix(self):
        """Ticketname, wenn er etwas aussagt (z. B. "Ermäßigt"), sonst ''."""
        self.ensure_one()
        ticket = (self.event_ticket_id.name or '').strip()
        return ticket if ticket and ticket.lower() not in GENERIC_TICKET_NAMES else ''

    @api.depends('event_id.name')
    def _compute_name_short(self):
        """website_event_sale zeigt im Warenkorb/in der Bestelluebersicht den
        Ticketnamen (meist nur "Standard"). Fuer Teilnehmende zaehlt der Kurs:
        Kursname, der Ticketname nur dann dahinter, wenn er etwas aussagt."""
        super()._compute_name_short()
        for line in self:
            if line.event_id:
                suffix = line._kjr_ticket_suffix()
                line.name_short = '%s (%s)' % (line.event_id.name, suffix) if suffix else line.event_id.name

    def _kjr_event_when(self):
        """Zeitraum der Veranstaltung in deren Zeitzone, fuer das PDF:
        "03.11.2026, 10:00 – 14:30 Uhr" oder
        "03.11.2026, 10:00 Uhr – 04.11.2026, 14:30 Uhr"."""
        self.ensure_one()
        if self.event_slot_id:
            return self.event_slot_id.display_name
        event = self.event_id
        if not event or not event.date_begin or not event.date_end:
            return ''
        tz = pytz.timezone(event.date_tz or 'Europe/Berlin')
        begin = pytz.utc.localize(event.date_begin).astimezone(tz)
        end = pytz.utc.localize(event.date_end).astimezone(tz)
        if begin.date() == end.date():
            return '%s, %s – %s Uhr' % (
                begin.strftime('%d.%m.%Y'), begin.strftime('%H:%M'), end.strftime('%H:%M'))
        return '%s, %s Uhr – %s, %s Uhr' % (
            begin.strftime('%d.%m.%Y'), begin.strftime('%H:%M'),
            end.strftime('%d.%m.%Y'), end.strftime('%H:%M'))

    def _kjr_attendee_names(self):
        """Namen der (nicht stornierten) Teilnehmenden dieser Zeile."""
        self.ensure_one()
        return [r.name for r in self.registration_ids.sudo()
                if r.state != 'cancel' and r.name]

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
