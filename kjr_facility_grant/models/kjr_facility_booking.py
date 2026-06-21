# -*- coding: utf-8 -*-
"""Brücke: Einrichtungsbuchung ↔ Zuschussantrag.

Macht aus dem bewusst entkoppelten Förderbezug (`is_grant_funded` /
`grant_reference`) eine echte Verknüpfung und erzeugt aus einer geförderten
Buchung direkt einen vorbefüllten Zuschussantrag (Maßnahme = Aufenthalt).
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class KjrFacilityBooking(models.Model):
    _inherit = 'kjr.facility.booking'

    grant_application_id = fields.Many2one(
        'kjr.grant.application', string='Zuschussantrag', copy=False,
        ondelete='set null', tracking=True,
        help='Mit dieser Einrichtungsbuchung verknüpfter Zuschussantrag.',
    )

    @api.onchange('grant_application_id')
    def _onchange_grant_application_id(self):
        """Verknüpfung spiegelt sich in den entkoppelten Förderfeldern wider."""
        if self.grant_application_id:
            self.is_grant_funded = True
            if not self.grant_reference:
                self.grant_reference = self.grant_application_id.name

    def action_create_grant_application(self):
        """Aus dieser Buchung einen vorbefüllten Zuschussantrag erstellen und
        verknüpfen. Eine Einrichtungsbuchung ist per Konstrukt immer eine
        Übernachtung (Abreise > Anreise) → Förderart-Vorschlag mehrtägige
        Freizeitmaßnahme (§ 4.1b); im Antrag frei änderbar."""
        self.ensure_one()
        if self.grant_application_id:
            raise UserError(_('Für diese Buchung besteht bereits ein verknüpfter '
                              'Zuschussantrag (%s).') % self.grant_application_id.name)
        GrantType = self.env['kjr.grant.type']
        gtype = (GrantType.search([('code', '=', '4_1b'), ('active', '=', True)], limit=1)
                 or GrantType.search([('active', '=', True)], limit=1))
        if not gtype:
            raise UserError(_('Es ist keine aktive Förderart hinterlegt. Bitte zuerst '
                              'unter „KJR App → Einstellungen → Förderarten" eine anlegen.'))
        app = self.env['kjr.grant.application'].create({
            'partner_id': self.partner_id.id,
            'grant_type_id': gtype.id,
            'measure_name': self.group_name or (self.facility_id.name or self.name),
            'measure_start': self.check_in,
            'measure_end': self.check_out,
            'measure_location': self.facility_id.name,
            'tn_count': self.participant_count,
            'tn_leader_count': self.leader_count,
            'cost_accommodation': self.amount_total,
            'contact_email': self.contact_email,
            'contact_phone': self.contact_phone,
        })
        self.write({
            'grant_application_id': app.id,
            'is_grant_funded': True,
            'grant_reference': app.name,
        })
        self.message_post(body=_('Zuschussantrag %s aus dieser Buchung erstellt.') % app.name)
        app.message_post(body=_('Aus Einrichtungsbuchung %s erstellt.') % self.name)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Zuschussantrag'),
            'res_model': 'kjr.grant.application',
            'res_id': app.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_grant_application(self):
        self.ensure_one()
        if not self.grant_application_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Zuschussantrag'),
            'res_model': 'kjr.grant.application',
            'res_id': self.grant_application_id.id,
            'view_mode': 'form',
        }
