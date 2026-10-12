# -*- coding: utf-8 -*-
"""Registrierung: Vereinsangaben übernehmen und Verbandskonten ohne Freigabe sperren.

1. ``signup`` (verbindliche Sperre, Lücke G1): Ein Signup-Token für einen
   Kontakt OHNE Benutzer, dessen commercial partner einen KJR-Mitgliedsverband
   im Teilbaum hat (Mitgliedsverband selbst, sein Kontakt oder ein Dachverband
   mit Mitgliedsorganisationen; res.partner._kjr_grants_member_rights), ergäbe
   ohne jede Freigabe ein Verbandskonto
   (auth_signup/models/res_users.py, Zweig „Token ohne bestehenden Benutzer“
   übernimmt den Partner mitsamt parent_id). Solche Token entstehen überall, wo
   die freie Registrierung an ist (website_sale setzt auth_signup_uninvited auf
   b2c): Benachrichtigungen (portal mail_thread / portal_mixin über
   signup_get_auth_param), die Shop-Bestellbestätigung und Mailvorlagen mit
   signup_url. Gesperrt wird nur dieser eine Zweig; die Portaleinladung der
   Geschäftsstelle (portal.wizard legt den Benutzer vorher an), das Zurücksetzen
   des Passworts und Token für Partner außerhalb eines Mitgliedsbaums bleiben
   möglich.

2. ``_signup_create_user``: Vereinsangaben aus dem Registrierungsformular
   (Schlüssel AFFILIATION_KEY, gesetzt in controllers/signup.py) werden als
   Vereinsregistrierung „beantragt“ angelegt; Benutzer und Antrag entstehen
   gemeinsam in einem Savepoint oder gar nicht.
"""
import logging

from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.addons.auth_signup.models.res_partner import SignupError

_logger = logging.getLogger(__name__)

AFFILIATION_KEY = 'kjr_affiliation'


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model
    def signup(self, values, token=None):
        """Verbindliche Sperre gegen Verbandskonten ohne Freigabe (Lücke G1)."""
        if token:
            # IMMER vor super(): im Token-Zweig mit bestehendem Benutzer schreibt
            # Odoo values per partner_user.write (auth_signup res_users.signup).
            values.pop(AFFILIATION_KEY, None)
            partner = self.env['res.partner'].sudo()._signup_retrieve_partner(
                token, check_validity=True, raise_exception=True)
            # user_ids mit active_test: ein ARCHIVIERTER Portalzugang unter einem
            # Mitgliedsverband fällt bewusst in den gesperrten Zweig; die
            # Geschäftsstelle reaktiviert ihn.
            # Maßstab wie die Rechte (child_of commercial partner), siehe
            # res.partner._kjr_grants_member_rights: auch ein Dachverband ohne
            # eigene Mitgliedschaft mit Mitgliedsorganisationen darunter.
            if not partner.user_ids and partner._kjr_grants_member_rights():
                raise UserError(_(
                    'Für diese Adresse richtet die Geschäftsstelle den Zugang ein. '
                    'Bitte wenden Sie sich an die Geschäftsstelle.'))
        return super().signup(values, token)

    @api.model
    def _signup_create_user(self, values):
        affiliation = values.pop(AFFILIATION_KEY, None)
        if not affiliation or values.get('partner_id'):
            return super()._signup_create_user(values)
        try:
            with self.env.cr.savepoint():
                new_user = super()._signup_create_user(values)
                self.env['kjr.affiliation.request'].sudo()._kjr_create_from_signup(
                    new_user, affiliation)
        except SignupError:
            raise
        except Exception as err:  # noqa: BLE001
            # Keine reine UserError: die Anfrage würde trotzdem committen und der
            # Benutzer bliebe ohne Antrag bestehen. SignupError fängt
            # web_auth_signup ab und loggt die Meldung, deshalb ohne
            # personenbezogene Daten.
            _logger.error('KJR Vereinsregistrierung: Antrag nicht angelegt (%s).',
                          type(err).__name__)
            raise SignupError(_(
                'Die Registrierung konnte nicht abgeschlossen werden. Bitte versuchen Sie es '
                'erneut oder wenden Sie sich an die Geschäftsstelle.')) from None
        return new_user
