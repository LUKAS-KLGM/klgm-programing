# -*- coding: utf-8 -*-
"""Vollversammlung des KJR — Einladung, Anwesenheit, Beschlüsse."""
from odoo import api, fields, models, _


class KjrAssembly(models.Model):
    _name = 'kjr.assembly'
    _description = 'KJR Vollversammlung'
    _order = 'date desc'
    _inherit = ['mail.thread']

    name = fields.Char(string='Bezeichnung', required=True, tracking=True)
    date = fields.Datetime(string='Datum & Uhrzeit', required=True, tracking=True)
    location = fields.Char(string='Ort', tracking=True)
    state = fields.Selection([
        ('draft', 'Planung'),
        ('invited', 'Eingeladen'),
        ('done', 'Durchgeführt'),
        ('cancelled', 'Abgesagt'),
    ], default='draft', tracking=True)
    agenda = fields.Html(string='Tagesordnung')
    protocol = fields.Html(string='Protokoll')
    attendee_ids = fields.Many2many(
        'res.partner', 'kjr_assembly_attendee_rel',
        string='Anwesende',
    )
    attendee_count = fields.Integer(string='Anwesend', compute='_compute_attendee_count')
    decision_ids = fields.One2many('kjr.assembly.decision', 'assembly_id', string='Beschlüsse')
    decision_count = fields.Integer(string='Beschlüsse', compute='_compute_decision_count')
    invited_member_ids = fields.Many2many(
        'res.partner', 'kjr_assembly_invited_rel',
        string='Eingeladene Verbände',
        domain="[('is_kjr_member', '=', True), ('is_company', '=', True)]",
    )
    note = fields.Text(string='Anmerkungen')
    invited_count = fields.Integer(string='Eingeladen', compute='_compute_invited_count')
    quorum_reached = fields.Boolean(
        string='Beschlussfähig', compute='_compute_quorum',
        help='Beschlussfähig, wenn mehr als die Hälfte der eingeladenen Verbände anwesend ist.',
    )

    @api.depends('attendee_ids')
    def _compute_attendee_count(self):
        for rec in self:
            rec.attendee_count = len(rec.attendee_ids)

    @api.depends('decision_ids')
    def _compute_decision_count(self):
        for rec in self:
            rec.decision_count = len(rec.decision_ids)

    @api.depends('invited_member_ids')
    def _compute_invited_count(self):
        for rec in self:
            rec.invited_count = len(rec.invited_member_ids)

    @api.depends('attendee_ids', 'invited_member_ids')
    def _compute_quorum(self):
        for rec in self:
            invited = len(rec.invited_member_ids)
            rec.quorum_reached = bool(invited) and (len(rec.attendee_ids) * 2 > invited)

    def action_invite(self):
        """Alle KJR-Mitglieder mit VR einladen."""
        members = self.env['res.partner'].search([
            ('is_kjr_member', '=', True),
            ('kjr_vr_right', '=', True),
            ('is_company', '=', True),
        ])
        self.write({
            'invited_member_ids': [(6, 0, members.ids)],
            'state': 'invited',
        })
        self.message_post(
            body=_('%d Mitgliedsverbände eingeladen.') % len(members),
            subtype_xmlid='mail.mt_note',
        )

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})


class KjrAssemblyDecision(models.Model):
    _name = 'kjr.assembly.decision'
    _description = 'Beschluss Vollversammlung'
    _order = 'sequence'

    assembly_id = fields.Many2one('kjr.assembly', string='Vollversammlung', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Beschluss', required=True)
    description = fields.Text(string='Details')
    vote_yes = fields.Integer(string='Ja-Stimmen', default=0)
    vote_no = fields.Integer(string='Nein-Stimmen', default=0)
    vote_abstain = fields.Integer(string='Enthaltungen', default=0)
    result = fields.Selection([
        ('accepted', 'Angenommen'),
        ('rejected', 'Abgelehnt'),
        ('tabled', 'Vertagt'),
    ], string='Ergebnis', compute='_compute_result', store=True, readonly=False,
        help='Wird aus den Stimmen vorbelegt (Mehrheit der Ja-/Nein-Stimmen), '
             'kann aber manuell überschrieben werden.')

    @api.depends('vote_yes', 'vote_no')
    def _compute_result(self):
        for rec in self:
            if not rec.vote_yes and not rec.vote_no:
                # Ohne erfasste Stimmen manuelle Angabe (z. B. "Vertagt") beibehalten.
                rec.result = rec.result or False
            elif rec.vote_yes > rec.vote_no:
                rec.result = 'accepted'
            else:
                rec.result = 'rejected'
