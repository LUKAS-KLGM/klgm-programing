# -*- coding: utf-8 -*-
"""Einstellungen der Brücke (Systemparameter kjr_event_sign.*)."""
from odoo import _, api, fields, models

from .event_event import XMLID_DEFAULT_TEMPLATE


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    kjr_event_sign_enabled = fields.Boolean(
        string='Einwilligung digital einholen',
        config_parameter='kjr_event_sign.enabled',
        help='Ein: Bei Veranstaltungen mit Einwilligungspflicht erhalten die '
             'Erziehungsberechtigten minderjähriger Online-Anmeldungen eine '
             'Unterschriftsanfrage (Odoo Sign); die Anmeldung wird erst nach der '
             'Unterschrift bestätigt. Aus: Bestätigung per Ankreuzfeld im Formular.')
    kjr_event_sign_template_id = fields.Many2one(
        'sign.template', string='Standardvorlage Einwilligung',
        domain=[('active', '=', True)],
        config_parameter='kjr_event_sign.default_template_id',
        help='Leer = mitgelieferte Vorlage "Einwilligung Erziehungsberechtigte '
             '(vorausgefüllt)": Name des Kindes, Veranstaltung und Name der/des '
             'Erziehungsberechtigten kommen schreibgeschützt aus der Anmeldung. '
             'Die alte Vorlage "… (alt, ohne Vorbefüllung)" nicht mehr wählen. '
             'An der Veranstaltung kann eine eigene Vorlage gewählt werden.')
    kjr_event_sign_sender_id = fields.Many2one(
        'res.users', string='Absender der Unterschriftsanfragen',
        domain=[('share', '=', False)],
        config_parameter='kjr_event_sign.sender_user_id',
        help='Interner Benutzer mit E-Mail-Adresse, in dessen Namen die Anfragen '
             'verschickt werden. Leer = verantwortliche Person der Veranstaltung, '
             'sonst der Administrator.')
    kjr_event_sign_validity_days = fields.Integer(
        string='Gültigkeit der Anfrage (Tage)', default=14,
        config_parameter='kjr_event_sign.validity_days',
        help='Höchstens so viele Tage ab Versand, spätestens bis zum Tag vor Beginn, '
             'mindestens bis morgen. 0 = Standard (14 Tage).')
    kjr_event_sign_reminder_days = fields.Integer(
        string='Erinnerung alle (Tage)', default=3,
        config_parameter='kjr_event_sign.reminder_days',
        help='Abstand der automatischen Erinnerungen von Odoo Sign. 0 = keine Erinnerung.')
    kjr_event_sign_template_warning = fields.Char(
        string='Hinweis zur Vorlage', compute='_compute_kjr_event_sign_template_warning')

    @api.depends('kjr_event_sign_template_id', 'kjr_event_sign_enabled')
    def _compute_kjr_event_sign_template_warning(self):
        Event = self.env['event.event']
        for rec in self:
            template = rec.kjr_event_sign_template_id or self.env.ref(
                XMLID_DEFAULT_TEMPLATE, raise_if_not_found=False)
            if not template:
                rec.kjr_event_sign_template_warning = _(
                    'Keine Vorlage gefunden. Ohne gültige Vorlage bleibt es bei der '
                    'Bestätigung im Formular.')
            elif not Event._kjr_consent_template_ok(template, log=True):
                rec.kjr_event_sign_template_warning = _(
                    'Die Vorlage ist nicht geeignet: Sie muss aktiv sein, ein Dokument, '
                    'genau eine Rolle und ein Unterschriftsfeld haben. Ohne gültige '
                    'Vorlage bleibt es bei der Bestätigung im Formular.')
            else:
                rec.kjr_event_sign_template_warning = False

    def set_values(self):
        super().set_values()
        # res.config.settings löscht einen Integer-Parameter mit dem Wert 0
        # (base/models/res_config.py: 0 -> False -> set_param löscht). Für die
        # Erinnerung bedeutet 0 aber "keine Erinnerung" und darf nicht auf den
        # Standard (3) zurückfallen. Deshalb hier ausdrücklich '0' speichern.
        if self.kjr_event_sign_reminder_days == 0:
            self.env['ir.config_parameter'].sudo().set_param('kjr_event_sign.reminder_days', '0')
