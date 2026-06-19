# -*- coding: utf-8 -*-
"""Juleica-Kartenverwaltung für Jugendleiter (Lifecycle nach bayer. Standards)."""
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _


class KjrJuleica(models.Model):
    _name = 'kjr.juleica'
    _description = 'Juleica-Karte'
    _order = 'expiry_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    partner_id = fields.Many2one(
        'res.partner', string='Inhaber/in', required=True,
        ondelete='cascade', tracking=True,
    )
    organization_id = fields.Many2one(
        'res.partner', string='Verband', tracking=True,
        domain="[('is_kjr_member', '=', True), ('is_company', '=', True)]",
    )
    card_number = fields.Char(string='Kartennummer', tracking=True)
    issue_date = fields.Date(string='Ausgestellt am', tracking=True)
    validity_years = fields.Integer(
        string='Gültigkeit (Jahre)', default=3,
        help='Die Juleica ist i. d. R. 3 Jahre gültig.',
    )
    expiry_date = fields.Date(
        string='Gültig bis', compute='_compute_expiry', store=True, readonly=False, tracking=True,
        help='Wird aus Ausstellungsdatum + Gültigkeit berechnet, kann überschrieben werden.',
    )
    state = fields.Selection([
        ('valid', 'Gültig'),
        ('expiring', 'Läuft bald ab'),
        ('expired', 'Abgelaufen'),
    ], string='Status', compute='_compute_state')  # nicht store: hängt von today() ab

    # ── Schulung ─────────────────────────────────────────────────────────────
    training_date = fields.Date(string='Letzte Ausbildung/Schulung')
    training_hours_presence = fields.Float(string='Ausbildungsstunden Präsenz', digits=(6, 1))
    training_hours_online = fields.Float(string='Ausbildungsstunden Online', digits=(6, 1))
    training_hours = fields.Float(
        string='Ausbildungsstunden gesamt', digits=(6, 1),
        compute='_compute_training_hours', store=True,
    )

    # ── Erste Hilfe ──────────────────────────────────────────────────────────
    eh_date = fields.Date(string='Erste-Hilfe-Kurs am')
    eh_valid_years = fields.Integer(
        string='EH-Gültigkeit (Jahre)', default=2,
        help='Erste-Hilfe-Nachweis darf bei Juleica-Beantragung i. d. R. nicht älter als 2 Jahre sein.',
    )
    eh_valid_until = fields.Date(string='EH gültig bis', compute='_compute_eh_until', store=True)
    eh_ok = fields.Boolean(string='Erste-Hilfe aktuell', compute='_compute_eh_ok')
    note = fields.Text(string='Bemerkungen')

    @api.depends('issue_date', 'validity_years')
    def _compute_expiry(self):
        for rec in self:
            if rec.issue_date:
                rec.expiry_date = rec.issue_date + relativedelta(years=rec.validity_years or 3)
            elif not rec.expiry_date:
                # Kein Ausstellungsdatum und (noch) kein manuell gesetztes Datum.
                rec.expiry_date = False
            # sonst: manuell gesetzten Wert unverändert lassen.

    @api.depends('expiry_date')
    def _compute_state(self):
        today = fields.Date.today()
        for rec in self:
            if not rec.expiry_date:
                rec.state = 'valid'
            elif rec.expiry_date < today:
                rec.state = 'expired'
            elif rec.expiry_date <= today + timedelta(days=90):
                rec.state = 'expiring'
            else:
                rec.state = 'valid'

    @api.depends('training_hours_presence', 'training_hours_online')
    def _compute_training_hours(self):
        for rec in self:
            rec.training_hours = (rec.training_hours_presence or 0.0) + (rec.training_hours_online or 0.0)

    @api.depends('eh_date', 'eh_valid_years')
    def _compute_eh_until(self):
        for rec in self:
            rec.eh_valid_until = (
                rec.eh_date + relativedelta(years=rec.eh_valid_years or 2)) if rec.eh_date else False

    @api.depends('eh_valid_until')
    def _compute_eh_ok(self):
        today = fields.Date.today()
        for rec in self:
            rec.eh_ok = bool(rec.eh_valid_until and rec.eh_valid_until >= today)

    def action_renew(self):
        """Juleica verlängern: neues Ausstellungsdatum heute, Gültigkeit wird neu berechnet."""
        for rec in self:
            rec.issue_date = fields.Date.today()
            rec.message_post(
                body=_('Juleica verlängert – neue Gültigkeit bis %s.') % (
                    rec.expiry_date and rec.expiry_date.strftime('%d.%m.%Y') or '—'),
                subtype_xmlid='mail.mt_note',
            )

    @api.model
    def _cron_juleica_expiry_reminder(self):
        """Erinnerung 90 Tage vor Juleica-Ablauf."""
        today = fields.Date.today()
        warn_date = today + timedelta(days=90)
        expiring = self.search([
            ('expiry_date', '<=', warn_date),
            ('expiry_date', '>=', today),
        ])
        for card in expiring:
            # Dedup: keine zweite Erinnerung, solange schon eine offene Aktivität existiert.
            if card.activity_ids:
                continue
            card.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=card.expiry_date,
                summary=_('Juleica läuft ab: %s') % card.partner_id.name,
                note=_('Die Juleica-Karte von %s (Nr. %s) läuft am %s ab.') % (
                    card.partner_id.name,
                    card.card_number or '—',
                    card.expiry_date.strftime('%d.%m.%Y'),
                ),
            )
