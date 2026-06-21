# -*- coding: utf-8 -*-
"""Verzeichnis der offenen Jugendeinrichtungen (Kommunale Jugendarbeit / KommJA).

Reines Stammdaten-/Verzeichnismodell: erfasst die vom Kreisjugendring
betreuten bzw. koordinierten offenen Jugendeinrichtungen im Landkreis
(Jugendzentren, Jugendtreffs, mobile/aufsuchende Angebote) mit Träger,
Anschrift, Kontakt, Zielgruppe und Angebotsschwerpunkten.
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class KjrYouthFacility(models.Model):
    _name = 'kjr.youth.facility'
    _description = 'Offene Jugendeinrichtung (KommJA-Verzeichnis)'
    _order = 'name'
    _inherit = ['mail.thread']

    name = fields.Char(string='Bezeichnung', required=True, tracking=True)
    code = fields.Char(string='Kürzel', copy=False)
    active = fields.Boolean(default=True)
    facility_type = fields.Selection([
        ('jz', 'Jugendzentrum'),
        ('jt', 'Jugendtreff'),
        ('jugendraum', 'Jugendraum'),
        ('mobil', 'Mobile / aufsuchende Jugendarbeit (Spielmobil, Streetwork)'),
        ('other', 'Sonstige Einrichtung'),
    ], string='Art', required=True, default='jz', tracking=True)

    # ── Träger & Verortung ───────────────────────────────────────────────────
    operator_id = fields.Many2one(
        'res.partner', string='Träger', tracking=True,
        help='Trägerorganisation der Einrichtung (Kommune, Verein, Verband).',
    )
    municipality = fields.Char(string='Kommune / Gemeinde')
    street = fields.Char(string='Straße & Hausnr.')
    zip = fields.Char(string='PLZ')
    city = fields.Char(string='Ort')

    # ── Kontakt ──────────────────────────────────────────────────────────────
    contact_person = fields.Char(string='Ansprechperson')
    phone = fields.Char(string='Telefon')
    email = fields.Char(string='E-Mail')
    website = fields.Char(string='Website')

    # ── Zielgruppe & Angebot ─────────────────────────────────────────────────
    age_min = fields.Integer(string='Alter von')
    age_max = fields.Integer(string='Alter bis')
    age_range = fields.Char(
        string='Altersgruppe', compute='_compute_age_range', store=True,
    )
    capacity = fields.Integer(string='Plätze / Kapazität')
    opening_hours = fields.Text(string='Öffnungszeiten')
    offerings = fields.Text(string='Angebote / Schwerpunkte')
    note = fields.Text(string='Interne Notizen')
    company_id = fields.Many2one(
        'res.company', string='Gesellschaft', required=True, index=True,
        default=lambda self: self.env.company,
    )

    @api.depends('age_min', 'age_max')
    def _compute_age_range(self):
        for rec in self:
            if rec.age_min and rec.age_max:
                rec.age_range = '%d–%d Jahre' % (rec.age_min, rec.age_max)
            elif rec.age_min:
                rec.age_range = 'ab %d Jahre' % rec.age_min
            elif rec.age_max:
                rec.age_range = 'bis %d Jahre' % rec.age_max
            else:
                rec.age_range = ''

    @api.constrains('age_min', 'age_max')
    def _check_age(self):
        for rec in self:
            if rec.age_min and rec.age_max and rec.age_max < rec.age_min:
                raise ValidationError(_('Das Höchstalter darf nicht kleiner als das Mindestalter sein.'))
            if (rec.age_min and rec.age_min < 0) or (rec.age_max and rec.age_max < 0):
                raise ValidationError(_('Altersangaben dürfen nicht negativ sein.'))
