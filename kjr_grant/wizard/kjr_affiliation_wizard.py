# -*- coding: utf-8 -*-
"""Assistenten zur Entscheidung über eine Vereinsregistrierung.

Beide Assistenten entscheiden nichts selbst: sie sammeln die Eingaben der
Geschäftsstelle und rufen ausschließlich kjr.affiliation.request._kjr_do_approve
bzw. _kjr_do_reject. Dort liegen Gruppenprüfung, Adress- und USt-IdNr.-Wache.

Der Genehmigungsassistent setzt NIE is_kjr_member: die Mitgliedschaft beschließt
die Vollversammlung, gepflegt wird sie im Reiter „KJR Verband“ des Kontakts.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import escape_psql


class KjrAffiliationApproveWizard(models.TransientModel):
    _name = 'kjr.affiliation.approve.wizard'
    _description = 'Vereinszugehörigkeit genehmigen'

    request_id = fields.Many2one(
        'kjr.affiliation.request', string='Vereinsregistrierung', required=True,
        readonly=True, ondelete='cascade',
    )
    partner_id = fields.Many2one(related='request_id.partner_id', readonly=True)
    requested_name = fields.Char(related='request_id.requested_name', readonly=True)
    requested_function = fields.Char(related='request_id.requested_function', readonly=True)
    requested_place = fields.Char(related='request_id.requested_place', readonly=True)
    partner_already_linked = fields.Boolean(
        related='request_id.partner_already_linked', readonly=True)

    mode = fields.Selection(
        [('existing', 'Bestehende Organisation wählen'),
         ('new', 'Neue Organisation anlegen')],
        string='Vorgehen', default='existing', required=True,
    )
    target_partner_id = fields.Many2one(
        'res.partner', string='Organisation', domain=[('is_company', '=', True)],
        compute='_compute_target_partner_id', store=True, readonly=False,
    )
    target_is_member = fields.Boolean(
        related='target_partner_id.is_kjr_member', string='KJR-Mitgliedsverband')

    new_name = fields.Char(
        'Name der Organisation', compute='_compute_new_defaults', store=True, readonly=False)
    new_street = fields.Char('Straße')
    new_zip = fields.Char('PLZ')
    new_city = fields.Char(
        'Ort', compute='_compute_new_defaults', store=True, readonly=False)
    new_email = fields.Char('E-Mail der Organisation')
    send_mail = fields.Boolean('Person per E-Mail benachrichtigen', default=True)

    @api.depends('request_id')
    def _compute_target_partner_id(self):
        Partner = self.env['res.partner']
        for wiz in self:
            req = wiz.request_id
            target = Partner.browse()
            if req.partner_already_linked:
                target = req.partner_id.commercial_partner_id
            elif req.requested_name:
                # Nur ein exakter Treffer (ohne Groß-/Kleinschreibung) unter den
                # Mitgliedsverbänden; Platzhalterzeichen im Freitext werden maskiert.
                target = Partner.search([
                    ('name', '=ilike', escape_psql(req.requested_name)),
                    ('is_company', '=', True),
                    ('is_kjr_member', '=', True),
                ], limit=1)
            wiz.target_partner_id = target

    @api.depends('request_id')
    def _compute_new_defaults(self):
        for wiz in self:
            wiz.new_name = wiz.request_id.requested_name or False
            wiz.new_city = wiz.request_id.requested_place or False

    def action_confirm(self):
        self.ensure_one()
        self.request_id._kjr_check_reviewer()
        if self.mode == 'new':
            if not (self.new_name and self.new_street and self.new_zip and self.new_city):
                raise UserError(_('Für eine neue Organisation bitte Name, Straße, PLZ und Ort angeben.'))
            # sudo: group_kjr_reviewer hat kein Anlagerecht auf res.partner; die
            # Gruppenprüfung steht unmittelbar davor.
            target = self.env['res.partner'].sudo().create({
                'name': self.new_name,
                'is_company': True,
                'street': self.new_street,
                'zip': self.new_zip,
                'city': self.new_city,
                'email': self.new_email or False,
            })
            # Ohne is_kjr_member: Mitgliedschaft beschließt die Vollversammlung,
            # gepflegt im Reiter „KJR Verband“.
        else:
            target = self.target_partner_id
            if not target:
                raise UserError(_('Bitte eine Organisation wählen.'))
        self.request_id._kjr_do_approve(target, notify=self.send_mail)
        return {'type': 'ir.actions.act_window_close'}


class KjrAffiliationRejectWizard(models.TransientModel):
    _name = 'kjr.affiliation.reject.wizard'
    _description = 'Vereinsregistrierung ablehnen'

    request_id = fields.Many2one(
        'kjr.affiliation.request', string='Vereinsregistrierung', required=True,
        readonly=True, ondelete='cascade',
    )
    reason = fields.Text('Grund (freiwillig, wird der Person mitgeteilt)')
    send_mail = fields.Boolean('Person per E-Mail benachrichtigen', default=True)

    def action_confirm(self):
        self.ensure_one()
        self.request_id._kjr_do_reject(self.reason, notify=self.send_mail)
        return {'type': 'ir.actions.act_window_close'}
