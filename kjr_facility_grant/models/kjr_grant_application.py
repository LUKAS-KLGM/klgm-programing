# -*- coding: utf-8 -*-
"""Brücke: Gegenrichtung – Zuschussantrag zeigt die verknüpften Buchungen."""
from odoo import api, fields, models, _


class KjrGrantApplication(models.Model):
    _inherit = 'kjr.grant.application'

    facility_booking_ids = fields.One2many(
        'kjr.facility.booking', 'grant_application_id',
        string='Einrichtungsbuchungen',
    )
    facility_booking_count = fields.Integer(
        string='Anzahl Buchungen', compute='_compute_facility_booking_count',
    )

    @api.depends('facility_booking_ids')
    def _compute_facility_booking_count(self):
        for rec in self:
            rec.facility_booking_count = len(rec.facility_booking_ids)

    def action_view_facility_bookings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Einrichtungsbuchungen'),
            'res_model': 'kjr.facility.booking',
            'view_mode': 'list,form',
            'domain': [('grant_application_id', '=', self.id)],
        }
