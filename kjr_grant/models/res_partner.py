# -*- coding: utf-8 -*-
"""Erweiterung res.partner für KJR-Mitgliedsverbände."""
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_kjr_member = fields.Boolean(
        string='KJR-Mitgliedsverband', default=False,
        help='Nur Verbände mit diesem Flag sind antragsberechtigt. '
             'Wird automatisch als Firma (Unternehmen) behandelt.',
    )

    @api.onchange('is_kjr_member')
    def _onchange_is_kjr_member(self):
        if self.is_kjr_member and not self.is_company:
            self.is_company = True
    kjr_member_type = fields.Selection([
        ('large_umbrella', 'Dachverband groß (§ 30 Abs. 2b BJR-Satzung)'),
        ('small_umbrella', 'Dachverband klein (§ 30 Abs. 2a BJR-Satzung)'),
        ('large_assoc',    'Jugendverband groß (§ 30 Abs. 2b BJR-Satzung)'),
        ('assoc',          'Jugendverband (§ 30 Abs. 2a BJR-Satzung)'),
        ('group',          'Jugendgruppe (§ 30 Abs. 2c BJR-Satzung)'),
        ('open',           'Offene Jugendeinrichtung'),
    ], string='Verbandstyp')
    kjr_member_number = fields.Char(string='Mitgliedsnummer KJR', copy=False)
    kjr_vr_right = fields.Boolean(
        string='Vertretungsrecht in Vollversammlung', default=False,
        help='Nur Verbände mit VR sind antragsberechtigt (§ 3.1 Richtlinien).',
    )
    kjr_vr_delegate_ids = fields.Many2many(
        'res.partner', 'kjr_partner_delegate_rel', 'partner_id', 'delegate_id',
        string='Vertreter/innen',
        help='Kontaktpersonen die den Verband in der KJR-Vollversammlung vertreten.',
        domain="[('is_company', '=', False)]",
    )
    kjr_vr_delegate_count = fields.Integer(
        string='Anzahl Vertreter', compute='_compute_delegate_count',
    )
    kjr_vr_votes = fields.Integer(
        string='Stimmen in Vollversammlung', default=0,
        help='Anzahl Stimmen lt. § 30 BJR-Satzung (abhängig von Verbandstyp).',
    )
    kjr_active_since = fields.Date(string='Mitglied seit')
    kjr_grant_ids = fields.One2many(
        'kjr.grant.application', 'partner_id', string='Zuschussanträge',
    )
    kjr_juleica_ids = fields.One2many('kjr.juleica', 'partner_id', string='Juleica-Karten')
    kjr_grant_count = fields.Integer(
        string='Anzahl Anträge', compute='_compute_kjr_grant_count',
    )
    kjr_grant_total_approved = fields.Float(
        string='Bewilligte Zuschüsse gesamt (€)',
        compute='_compute_kjr_grant_count', digits=(10, 2),
    )

    @api.depends('kjr_vr_delegate_ids')
    def _compute_delegate_count(self):
        for rec in self:
            rec.kjr_vr_delegate_count = len(rec.kjr_vr_delegate_ids)

    @api.depends('kjr_grant_ids', 'kjr_grant_ids.state', 'kjr_grant_ids.grant_approved')
    def _compute_kjr_grant_count(self):
        for rec in self:
            grants = rec.kjr_grant_ids
            rec.kjr_grant_count = len(grants)
            rec.kjr_grant_total_approved = sum(
                g.grant_approved for g in grants if g.state in ('approved', 'paid')
            )

    def action_kjr_datenauskunft(self):
        """DSGVO Art. 15: Datenauskunft über die zu dieser Person/Organisation
        im KJR-Modul gespeicherten Daten als PDF."""
        self.ensure_one()
        return self.env.ref('kjr_grant.action_report_kjr_datenauskunft').report_action(self)
