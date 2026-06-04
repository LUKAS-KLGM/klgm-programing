# -*- coding: utf-8 -*-
"""Teilnehmerliste für Zuschussanträge (lt. KJR OA TN-Liste)."""
import logging

from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class KjrGrantParticipant(models.Model):
    _name = 'kjr.grant.participant'
    _description = 'Teilnehmer'
    _order = 'sequence, name'

    application_id = fields.Many2one(
        'kjr.grant.application', string='Antrag',
        required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(string='Nr.', default=10)
    name = fields.Char(string='Name, Vorname', required=True)
    birthdate = fields.Date(string='Geburtsdatum')
    age = fields.Integer(string='Alter', compute='_compute_age')
    zip_code = fields.Char(string='PLZ')
    city = fields.Char(string='Wohnort')
    is_leader = fields.Boolean(string='Gruppenleitung', default=False)
    has_juleica = fields.Boolean(string='Juleica', default=False)
    note = fields.Char(string='Bemerkung')
    data_anonymized = fields.Boolean(
        string='Anonymisiert (DSGVO)', default=False, readonly=True, copy=False,
        help='Personenbezogene Daten wurden nach Ablauf der Aufbewahrungsfrist anonymisiert.',
    )

    @api.depends('birthdate', 'application_id.measure_start')
    def _compute_age(self):
        for rec in self:
            if rec.birthdate and rec.application_id.measure_start:
                start = rec.application_id.measure_start
                bd = rec.birthdate
                rec.age = start.year - bd.year - (
                    (start.month, start.day) < (bd.month, bd.day)
                )
            else:
                rec.age = 0

    @api.model
    def _cron_anonymize_expired(self):
        """DSGVO (Storage Limitation): Teilnehmerdaten (z. T. Minderjähriger) nach Ablauf
        der Aufbewahrungsfrist anonymisieren statt zu löschen, damit aggregierte Nachweise
        (Anzahl, Juleica-Quote) für die Förderprüfung erhalten bleiben.
        Frist über System-Parameter 'kjr_grant.participant_retention_years' (Default 5 Jahre).
        TODO(DSGVO): Aufbewahrungsfrist und Anonymisierungsverfahren datenschutzrechtlich final bestätigen."""
        years = int(self.env['ir.config_parameter'].sudo().get_param(
            'kjr_grant.participant_retention_years', 5))
        cutoff = fields.Date.today() - relativedelta(years=years)
        stale = self.search([
            ('data_anonymized', '=', False),
            ('application_id.measure_end', '<', cutoff),
        ])
        for rec in stale:
            rec.write({
                'name': _('(anonymisiert)'),
                'birthdate': False,
                'zip_code': False,
                'city': False,
                'note': False,
                'data_anonymized': True,
            })
        if stale:
            _logger.info('DSGVO-Anonymisierung: %d Teilnehmerdatensätze anonymisiert', len(stale))
