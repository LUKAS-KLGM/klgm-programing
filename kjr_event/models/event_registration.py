# -*- coding: utf-8 -*-
"""KJR-Erweiterung der Veranstaltungsanmeldung: Minderjährige, Einwilligung, Juleica."""
from odoo import api, fields, models


class EventRegistration(models.Model):
    _inherit = 'event.registration'

    birthdate = fields.Date(string='Geburtsdatum')
    kjr_age = fields.Integer(string='Alter (bei Beginn)', compute='_compute_kjr_age', store=True)
    is_minor = fields.Boolean(string='Minderjährig', compute='_compute_kjr_age', store=True)
    parental_consent = fields.Boolean(string='Einwilligung Erziehungsberechtigte')
    guardian_name = fields.Char(string='Erziehungsberechtigte/r')
    guardian_phone = fields.Char(string='Telefon Erziehungsberechtigte/r')
    emergency_contact = fields.Char(string='Notfallkontakt')
    consent_missing = fields.Boolean(string='Einwilligung fehlt', compute='_compute_consent_missing')
    age_out_of_range = fields.Boolean(string='Außerhalb Altersgruppe', compute='_compute_consent_missing')
    # Juleica-Ausstellung (nur bei Juleica-Schulungen)
    event_is_juleica = fields.Boolean(related='event_id.is_juleica_course')
    juleica_issued = fields.Boolean(string='Juleica ausgestellt')
    juleica_valid_until = fields.Date(string='Juleica gültig bis')

    @api.depends('birthdate', 'event_id.date_begin')
    def _compute_kjr_age(self):
        for rec in self:
            if rec.birthdate and rec.event_id.date_begin:
                start = rec.event_id.date_begin.date()
                bd = rec.birthdate
                age = start.year - bd.year - ((start.month, start.day) < (bd.month, bd.day))
                rec.kjr_age = age
                rec.is_minor = age < 18
            else:
                rec.kjr_age = 0
                rec.is_minor = False

    @api.depends('parental_consent', 'is_minor', 'kjr_age',
                 'event_id.requires_parental_consent', 'event_id.kjr_min_age', 'event_id.kjr_max_age')
    def _compute_consent_missing(self):
        for rec in self:
            ev = rec.event_id
            rec.consent_missing = bool(
                ev.requires_parental_consent and rec.is_minor and not rec.parental_consent
            )
            out = False
            if rec.birthdate:  # Alter 0 ist gültig – nicht auf kjr_age (falsy bei 0) prüfen
                if ev.kjr_min_age and rec.kjr_age < ev.kjr_min_age:
                    out = True
                elif ev.kjr_max_age and rec.kjr_age > ev.kjr_max_age:
                    out = True
            rec.age_out_of_range = out
