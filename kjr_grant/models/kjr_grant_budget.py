# -*- coding: utf-8 -*-
"""Jahresbudget pro Förderart — Haushaltsmittel des Landkreises."""
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class KjrGrantBudget(models.Model):
    _name = 'kjr.grant.budget'
    _description = 'KJR Jahresbudget'
    _order = 'year desc, grant_type_id'
    _rec_name = 'display_name'

    year = fields.Integer(string='Haushaltsjahr', required=True, default=lambda self: fields.Date.today().year)
    grant_type_id = fields.Many2one(
        'kjr.grant.type', string='Förderart',
        help='Leer = Gesamtbudget über alle Förderarten.',
    )
    amount_total = fields.Float(string='Budget gesamt (€)', digits=(10, 2), required=True)
    amount_approved = fields.Float(
        string='Bewilligt (€)', digits=(10, 2),
        compute='_compute_amounts',
    )
    amount_paid = fields.Float(
        string='Ausgezahlt (€)', digits=(10, 2),
        compute='_compute_amounts',
    )
    amount_remaining = fields.Float(
        string='Verfügbar (€)', digits=(10, 2),
        compute='_compute_amounts',
    )
    usage_pct = fields.Float(
        string='Auslastung (%)', digits=(5, 1),
        compute='_compute_amounts',
    )
    note = fields.Text(string='Anmerkungen')
    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('year', 'grant_type_id')
    def _compute_display_name(self):
        for rec in self:
            if rec.grant_type_id:
                rec.display_name = f'{rec.year} — {rec.grant_type_id.name}'
            else:
                rec.display_name = f'{rec.year} — Gesamtbudget'

    @api.depends('amount_total', 'year', 'grant_type_id')
    def _compute_amounts(self):
        for rec in self:
            domain = [('measure_year', '=', rec.year)]
            if rec.grant_type_id:
                domain.append(('grant_type_id', '=', rec.grant_type_id.id))

            apps = self.env['kjr.grant.application'].search(domain)
            rec.amount_approved = sum(
                a.grant_approved for a in apps if a.state in ('approved', 'paid')
            )
            rec.amount_paid = sum(
                a.grant_approved for a in apps if a.state == 'paid'
            )
            rec.amount_remaining = rec.amount_total - rec.amount_approved
            rec.usage_pct = (rec.amount_approved / rec.amount_total * 100) if rec.amount_total else 0.0
