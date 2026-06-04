# -*- coding: utf-8 -*-
"""KJR-spezifische Erweiterung der Veranstaltung (Ferienprogramm, Schulungen)."""
from odoo import api, fields, models


class EventEvent(models.Model):
    _inherit = 'event.event'

    is_kjr = fields.Boolean(string='KJR-Veranstaltung')
    kjr_event_type = fields.Selection([
        ('ferienprogramm', 'Ferienprogramm'),
        ('juleica_course', 'Juleica-Schulung'),
        ('rescue_course', 'Rettungsschwimmer-Kurs'),
        ('other', 'Sonstige'),
    ], string='KJR-Art')
    kjr_min_age = fields.Integer(string='Mindestalter', help='0 = keine Prüfung.')
    kjr_max_age = fields.Integer(string='Höchstalter', help='0 = keine Obergrenze.')
    requires_parental_consent = fields.Boolean(
        string='Einwilligung Erziehungsberechtigter erforderlich',
        help='Bei Maßnahmen für Minderjährige: Einwilligung der Erziehungsberechtigten ist Pflicht. '
             'Erfassung auf der Website am besten über Veranstaltungs-Fragen (event.question) abbilden.',
    )
    is_juleica_course = fields.Boolean(string='Juleica-Ausbildung', compute='_compute_is_juleica', store=True)

    @api.depends('kjr_event_type')
    def _compute_is_juleica(self):
        for rec in self:
            rec.is_juleica_course = rec.kjr_event_type == 'juleica_course'
