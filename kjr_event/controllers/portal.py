# -*- coding: utf-8 -*-
"""Portal-Zugriff für KJR-Kooperationspartner auf die Teilnehmerlisten."""
from odoo import http, _
from odoo.http import request
from odoo.exceptions import AccessError, MissingError
from odoo.addons.portal.controllers.portal import CustomerPortal


class KjrCooperationPortal(CustomerPortal):

    def _kjr_cooperation_events_domain(self):
        partner = request.env.user.partner_id
        return [
            '|',
            ('cooperation_partner_id', '=', partner.id),
            ('cooperation_user_ids', 'in', request.env.user.id),
        ]

    @http.route(['/my/kjr-events'], type='http', auth='user', website=True)
    def kjr_cooperation_events(self, **kw):
        Event = request.env['event.event']
        events = Event.search(self._kjr_cooperation_events_domain(), order='date_begin desc')
        values = {
            'events': events,
            'page_name': 'kjr_events',
        }
        return request.render('kjr_event.portal_kjr_events', values)

    @http.route(['/my/kjr-events/<int:event_id>/teilnehmer'],
                type='http', auth='user', website=True)
    def kjr_cooperation_attendees(self, event_id, **kw):
        try:
            event = request.env['event.event'].browse(event_id)
            event.check_access('read')
            event.read(['name'])  # löst AccessError aus, falls nicht erlaubt
        except (AccessError, MissingError):
            return request.redirect('/my')
        # Zusätzliche Absicherung: Event muss zur Kooperation des Nutzers gehören.
        allowed = request.env['event.event'].search(
            self._kjr_cooperation_events_domain() + [('id', '=', event_id)])
        if not allowed:
            return request.redirect('/my/kjr-events')
        registrations = request.env['event.registration'].search(
            [('event_id', '=', event_id)], order='name')
        values = {
            'event': event,
            'registrations': registrations,
            'page_name': 'kjr_events',
        }
        return request.render('kjr_event.portal_kjr_event_attendees', values)
