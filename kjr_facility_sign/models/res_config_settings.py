# -*- coding: utf-8 -*-
"""Einstellungen der Brücke (Systemparameter kjr_facility_sign.*)."""
from odoo import fields, models

from .kjr_facility_booking import (
    DEFAULT_REMINDER_DAYS,
    DEFAULT_VALIDITY_DAYS,
    PARAM_ENABLED,
    PARAM_REMINDER,
    PARAM_SENDER,
    PARAM_VALIDITY,
)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    kjr_facility_sign_enabled = fields.Boolean(
        string='Vertrag digital unterschreiben', config_parameter=PARAM_ENABLED,
        help='Ein: Beim verbindlichen Buchen erhält der Mieter statt der Vertragsmail eine '
             'Unterschriftsanfrage (Odoo Sign). Aus: Vertrag wie bisher als PDF per Mail.')
    kjr_facility_sign_sender_id = fields.Many2one(
        'res.users', string='Absender der Unterschriftsanfragen',
        domain=[('share', '=', False)], config_parameter=PARAM_SENDER,
        help='Interner Benutzer mit E-Mail-Adresse. Leer = verantwortliche Person der '
             'Einrichtung, sonst der buchende Benutzer, sonst der Administrator. Absender '
             'nicht deaktivieren und nicht ohne E-Mail lassen, solange Anfragen offen sind '
             '(Odoo Sign braucht ihn auch für Ablehnung und Abschluss).')
    kjr_facility_sign_validity_days = fields.Integer(
        string='Gültigkeit (Tage)', default=DEFAULT_VALIDITY_DAYS,
        config_parameter=PARAM_VALIDITY,
        help='Spätestens bis zum Tag vor der Anreise, mindestens bis morgen. '
             '0 = Standard (14).')
    kjr_facility_sign_reminder_days = fields.Integer(
        string='Erinnerung alle (Tage)', default=DEFAULT_REMINDER_DAYS,
        config_parameter=PARAM_REMINDER,
        help='Automatische Erinnerung durch Odoo Sign. 0 = keine Erinnerung.')

    def set_values(self):
        super().set_values()
        # res.config.settings löscht Integer-Parameter mit dem Wert 0
        # (base/models/res_config.py: 0 -> False -> set_param löscht). Für die
        # Erinnerung bedeutet 0 aber "keine Erinnerung" und darf nicht auf den
        # Standard zurückfallen. Deshalb hier ausdrücklich '0' speichern.
        if self.kjr_facility_sign_reminder_days == 0:
            self.env['ir.config_parameter'].sudo().set_param(PARAM_REMINDER, '0')
