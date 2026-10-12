# -*- coding: utf-8 -*-
"""Anmeldung zur Vollversammlung über den Link aus der Einladung.

Route: GET/POST /vollversammlung/anmeldung/<invitation_id>/<token>

Der Link steht nur in der Einladungs-Mail (kjr.assembly.invitation,
Mailvorlage mail_template_assembly_invitation) und trägt den
Zugangsschlüssel der Einladung. Ohne passenden Schlüssel gibt es 404 (kein
Hinweis, ob die Einladung existiert). Delegierte haben oft kein Konto,
deshalb auth='public'.

Telefon ist Pflicht (Anforderung: Anmeldungen per E-Mail ohne Telefonnummer
haben die Beschlussfähigkeit gefährdet). Geprüft wird hier für verständliche
Meldungen am Feld und zusätzlich am Modell (kjr.assembly.registration).

Datensparsam: Die Seite zeigt keine gespeicherten Kontaktdaten Dritter an.
Nur wer angemeldet ist, bekommt seine EIGENEN Angaben vorbelegt, und nur dann
wird die Anmeldung dem eigenen Kontakt zugeordnet. Eine im Formular
eingetippte Adresse ordnet nichts zu (kjr.assembly.invitation._kjr_register).
Der Datenschutzhinweis nennt Löschfrist (dieselbe Auslegung wie der Lösch-Cron)
und Verantwortlichen (Systemparameter kjr.privacy.controller, wie im
Registrierungsformular).
"""
import logging

from werkzeug.exceptions import NotFound

from odoo import fields, http
from odoo.http import request
from odoo.tools import consteq, format_datetime

from odoo.addons.kjr_grant.controllers.portal import PHONE_RE
from odoo.addons.kjr_grant.controllers.website import EMAIL_RE

_logger = logging.getLogger(__name__)

NAME_MIN, NAME_MAX, EMAIL_MAX, PHONE_MAX = 2, 120, 120, 32


class KjrAssemblyRegistrationController(http.Controller):

    @staticmethod
    def _kjr_invitation(invitation_id, token):
        invitation = request.env['kjr.assembly.invitation'].sudo().browse(invitation_id).exists()
        if (not invitation or not invitation.access_token or not token
                or not consteq(invitation.access_token, token)):
            raise NotFound()
        return invitation

    @staticmethod
    def _kjr_is_open(assembly):
        return assembly.state == 'invited' and assembly.date and assembly.date > fields.Datetime.now()

    @staticmethod
    def _kjr_validate(post):
        values = {
            'name': ' '.join((post.get('name') or '').split()),
            'email': (post.get('email') or '').strip(),
            'phone': ' '.join((post.get('phone') or '').split()),
        }
        errors = {}
        if len(values['name']) < NAME_MIN or len(values['name']) > NAME_MAX:
            errors['name'] = 'Bitte geben Sie Ihren vollständigen Namen an.'
        if not values['email'] or len(values['email']) > EMAIL_MAX or not EMAIL_RE.match(values['email']):
            errors['email'] = 'Bitte geben Sie eine gültige E-Mail-Adresse an.'
        if not values['phone']:
            errors['phone'] = ('Die Telefonnummer ist Pflicht, damit die Geschäftsstelle Sie vor '
                               'und am Tag der Vollversammlung erreichen kann.')
        elif len(values['phone']) > PHONE_MAX or not PHONE_RE.match(values['phone']):
            errors['phone'] = ('Telefon bitte nur mit Ziffern und den Zeichen + ( ) / - angeben '
                               '(z. B. 08321 1234-0).')
        return values, errors

    @http.route(
        '/vollversammlung/anmeldung/<int:invitation_id>/<string:token>',
        type='http', auth='public', website=True, methods=['GET', 'POST'], sitemap=False,
    )
    def kjr_assembly_registration(self, invitation_id, token, **post):
        invitation = self._kjr_invitation(invitation_id, token)
        assembly = invitation.assembly_id
        company = assembly.company_id
        tz = company.partner_id.tz or 'Europe/Berlin'
        render_values = {
            'invitation_id': invitation.id,
            'token': token,
            'assembly_name': assembly.name or '',
            'assembly_date': format_datetime(
                request.env, assembly.date, tz=tz, dt_format='dd.MM.yyyy, HH:mm') if assembly.date else '',
            'assembly_location': assembly.location or '',
            'member_name': invitation.member_id.name or '',
            'is_open': self._kjr_is_open(assembly),
            'office': {'name': company.name or '', 'email': company.email or '',
                       'phone': company.phone or ''},
            'values': {},
            'errors': {},
            'success': False,
            'retention_days': request.env[
                'kjr.assembly.registration'].sudo()._kjr_retention_days(),
            'privacy_controller': request.env['ir.config_parameter'].sudo().get_param(
                'kjr.privacy.controller') or '',
        }
        user = request.env.user
        own_partner = user.partner_id if not user._is_public() else None
        if request.httprequest.method != 'POST':
            if own_partner:
                # Nur die eigenen Angaben der angemeldeten Person.
                render_values['values'] = {
                    'name': own_partner.name or '', 'email': own_partner.email or '',
                    'phone': own_partner.phone or '',
                }
            return request.render('kjr_grant.assembly_registration_page', render_values)

        if not render_values['is_open']:
            return request.render('kjr_grant.assembly_registration_page', render_values)
        values, errors = self._kjr_validate(post)
        render_values['values'] = values
        if errors:
            render_values['errors'] = errors
            return request.render('kjr_grant.assembly_registration_page', render_values)
        partner = None
        if own_partner and (own_partner.email or '').strip().lower() == values['email'].lower():
            partner = own_partner.sudo()
            if not (partner.phone or '').strip():
                # Eigene Kontaktdaten der angemeldeten Person: Telefon nachtragen.
                partner.phone = values['phone']
        invitation._kjr_register(values['name'], values['email'], values['phone'], partner=partner)
        _logger.info('KJR Vollversammlung: Anmeldung zu Einladung %s gespeichert.', invitation.id)
        render_values['success'] = True
        return request.render('kjr_grant.assembly_registration_page', render_values)
