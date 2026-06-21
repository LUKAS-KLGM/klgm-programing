# -*- coding: utf-8 -*-
"""Strukturierte Erfassung ehrenamtlicher Tätigkeitsstunden.

Grundlage für einen substanziellen Ehrenamtsnachweis (statt rein textlicher
Bescheinigung): jede geleistete Stunde wird mit Datum, Tätigkeitskategorie und
optionalem Bezug zu einer geförderten Maßnahme erfasst und im Nachweis-PDF
aggregiert ausgewiesen.
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class KjrVolunteerLog(models.Model):
    _name = 'kjr.volunteer.log'
    _description = 'Ehrenamtsstunden-Eintrag'
    _order = 'date desc, id desc'
    _inherit = ['mail.thread']

    partner_id = fields.Many2one(
        'res.partner', string='Ehrenamtliche/r', required=True,
        ondelete='cascade', tracking=True, index=True,
        domain="[('is_company', '=', False)]",
        help='Person, die die ehrenamtliche Tätigkeit geleistet hat.',
    )
    organization_id = fields.Many2one(
        'res.partner', string='Verband', ondelete='set null', tracking=True,
        domain="[('is_kjr_member', '=', True), ('is_company', '=', True)]",
        help='Mitgliedsverband, in dessen Rahmen die Tätigkeit erbracht wurde.',
    )
    date = fields.Date(
        string='Datum', required=True, default=fields.Date.context_today, tracking=True,
    )
    hours = fields.Float(
        string='Stunden', required=True, digits=(6, 2), tracking=True,
        help='Geleistete Stunden für diesen Eintrag.',
    )
    category = fields.Selection([
        ('freizeit', 'Freizeitmaßnahmen (Planung & Durchführung)'),
        ('betreuung', 'Betreuung & Gruppenaktivitäten'),
        ('schulung', 'Aus- & Fortbildung'),
        ('gremium', 'Verbands- & Gremienarbeit'),
        ('sonstiges', 'Sonstiges'),
    ], string='Tätigkeit', required=True, default='freizeit', tracking=True)
    description = fields.Char(string='Beschreibung')
    application_id = fields.Many2one(
        'kjr.grant.application', string='Bezug Maßnahme', ondelete='set null',
        help='Optionaler Bezug zu einem geförderten Zuschussantrag.',
    )
    company_id = fields.Many2one(
        'res.company', string='Gesellschaft', required=True, index=True,
        default=lambda self: self.env.company,
    )

    @api.constrains('hours')
    def _check_hours(self):
        for rec in self:
            if rec.hours <= 0:
                raise ValidationError(_('Die Stundenzahl muss größer als 0 sein.'))

    @api.depends('partner_id', 'date', 'hours', 'category')
    def _compute_display_name(self):
        labels = dict(self._fields['category'].selection)
        for rec in self:
            d = fields.Date.to_string(rec.date) or ''
            rec.display_name = '%s – %s (%.1f h, %s)' % (
                d, rec.partner_id.name or '', rec.hours or 0.0,
                labels.get(rec.category, rec.category or ''),
            )
