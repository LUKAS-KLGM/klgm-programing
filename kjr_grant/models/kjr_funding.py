# -*- coding: utf-8 -*-
"""Fördermittel-Akquise — KJR-eigene Anträge an BJR/BezJR/Ministerium."""
from datetime import timedelta

from odoo import api, fields, models, _


class KjrFunding(models.Model):
    _name = 'kjr.funding'
    _description = 'KJR Fördermittel-Akquise'
    _order = 'deadline desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

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

    # ── Workflow ─────────────────────────────────────────────────────────────
    def action_submit(self):
        self.write({'state': 'submitted'})

    def action_approve(self):
        self.write({'state': 'approved'})

    def action_reject(self):
        self.write({'state': 'rejected'})

    def action_start(self):
        self.write({'state': 'running'})

    def action_close(self):
        self.write({'state': 'closed'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    # ── Fristen-Erinnerung ───────────────────────────────────────────────────
    @api.model
    def _cron_funding_deadline_reminder(self):
        """Erinnerung an Antrags- und Verwendungsnachweis-Fristen der Fördermittel
        (28 Tage vorher). Deckt den Wunsch des KJR nach automatischer Fristenüberwachung."""
        today = fields.Date.today()
        horizon = today + timedelta(days=28)
        # Antragsfristen offener (noch nicht eingereichter) Programme
        for rec in self.search([
            ('state', 'in', ('draft', 'submitted')),
            ('deadline', '>=', today), ('deadline', '<=', horizon),
        ]):
            if any(a.summary and 'Antragsfrist' in a.summary for a in rec.activity_ids):
                continue
            rec.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=rec.deadline,
                user_id=(rec.responsible_id or self.env.user).id,
                summary=_('Antragsfrist Fördermittel: %s') % rec.name,
                note=_('Die Antragsfrist für "%s" (%s) endet am %s.') % (
                    rec.name, dict(self._fields['funder'].selection).get(rec.funder, ''),
                    rec.deadline.strftime('%d.%m.%Y')),
            )
        # Verwendungsnachweis-Fristen laufender/bewilligter Programme
        for rec in self.search([
            ('state', 'in', ('approved', 'running')),
            ('verwendungsnachweis_deadline', '>=', today),
            ('verwendungsnachweis_deadline', '<=', horizon),
        ]):
            if any(a.summary and 'Verwendungsnachweis' in a.summary for a in rec.activity_ids):
                continue
            rec.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=rec.verwendungsnachweis_deadline,
                user_id=(rec.responsible_id or self.env.user).id,
                summary=_('Verwendungsnachweis fällig: %s') % rec.name,
                note=_('Der Verwendungsnachweis für "%s" ist bis %s einzureichen.') % (
                    rec.name, rec.verwendungsnachweis_deadline.strftime('%d.%m.%Y')),
            )
