# -*- coding: utf-8 -*-
"""Frontend-Erweiterung der Online-Anmeldung um KJR-Felder."""
from odoo import http
from odoo.http import request
from odoo.addons.website_event.controllers.main import WebsiteEventController


# Felder, die im Anmeldeformular je Teilnehmer/in erfasst werden können.
KJR_VALUE_FIELDS = (
    'birthdate', 'guardian_name', 'guardian_phone',
    'emergency_contact', 'dietary_requirements', 'dietary_note', 'notes',
)


def _truthy(value):
    return bool(value) and str(value).lower() not in ('0', 'false', 'off', 'no')


class KjrWebsiteEventController(WebsiteEventController):

    def _kjr_extract_attendee_values(self, registrations):
        """Sammelt die KJR-Felder je Teilnehmer/in aus den geposteten Formulardaten.

        Das Frontend liefert die Felder unter ``<counter>-<feldname>`` (z. B. ``1-birthdate``).
        Rückgabe: Liste von Wert-Dicts in derselben Reihenfolge wie die Anmeldungen.
        """
        # Anzahl Teilnehmer/innen anhand der Standardfelder bestimmen.
        counters = sorted({
            int(key.split('-', 1)[0])
            for key in registrations
            if '-' in key and key.split('-', 1)[0].isdigit()
        })
        result = []
        for counter in counters:
            prefix = '%d-' % counter
            values = {}
            for field in KJR_VALUE_FIELDS:
                key = prefix + field
                if key in registrations and registrations[key] not in (None, ''):
                    values[field] = registrations[key]
            consent_key = prefix + 'parental_consent'
            if consent_key in registrations:
                values['parental_consent'] = _truthy(registrations[consent_key])
            result.append((counter, values))
        return result

    @http.route()
    def registration_confirm(self, event, **post):
        # Roh-Post sichern, bevor die Standardverarbeitung läuft.
        kjr_values = self._kjr_extract_attendee_values(post)

        # Anmeldungen vor dem Aufruf zählen, um die neu erzeugten zu identifizieren.
        existing = request.env['event.registration'].sudo().search(
            [('event_id', '=', event.id)]).ids
        before = set(existing)

        response = super().registration_confirm(event, **post)

        if kjr_values:
            new_regs = request.env['event.registration'].sudo().search(
                [('event_id', '=', event.id), ('id', 'not in', list(before))],
                order='id asc')
            # Reihenfolge der neuen Anmeldungen entspricht der Reihenfolge im Formular.
            for reg, (_counter, values) in zip(new_regs, kjr_values):
                if values:
                    reg.write(values)
        return response
