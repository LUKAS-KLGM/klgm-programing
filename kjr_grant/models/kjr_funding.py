# -*- coding: utf-8 -*-
"""Fördermittel-Akquise — KJR-eigene Anträge an BJR/BezJR/Ministerium."""
from odoo import api, fields, models, _


class KjrFunding(models.Model):
    _name = 'kjr.funding'
    _description = 'KJR Fördermittel-Akquise'
    _order = 'deadline desc'
    _inherit = ['mail.thread']

    name = fields.Char(string='Förderprogramm', required=True, tracking=True)
    funder = fields.Selection([
        ('bjr', 'Bayerischer Jugendring (BJR)'),
        ('bezjr', 'Bezirksjugendring Schwaben'),
        ('stmas', 'Staatsministerium (StMAS)'),
        ('landkreis', 'Landkreis Oberallgäu'),
        ('bund', 'Bundesministerium (BMFSFJ)'),
        ('eu', 'EU-Förderprogramm'),
        ('stiftung', 'Stiftung'),
        ('other', 'Sonstige'),
    ], string='Fördergeber', required=True, tracking=True)
    funder_name = fields.Char(string='Name Fördergeber')
    amount_requested = fields.Float(string='Beantragt (€)', digits=(10, 2), tracking=True)
    amount_approved = fields.Float(string='Bewilligt (€)', digits=(10, 2), tracking=True)
    deadline = fields.Date(string='Antragsfrist', tracking=True)
    project_name = fields.Char(string='Projektbezeichnung')
    project_description = fields.Text(string='Projektbeschreibung')
    project_start = fields.Date(string='Projektzeitraum von')
    project_end = fields.Date(string='Projektzeitraum bis')
    state = fields.Selection([
        ('draft', 'Entwurf'),
        ('submitted', 'Eingereicht'),
        ('approved', 'Bewilligt'),
        ('rejected', 'Abgelehnt'),
        ('running', 'Laufend'),
        ('closed', 'Abgeschlossen'),
    ], default='draft', tracking=True)
    responsible_id = fields.Many2one('res.users', string='Verantwortlich', tracking=True)
    note = fields.Text(string='Anmerkungen')
    verwendungsnachweis_deadline = fields.Date(string='Verwendungsnachweis bis')
