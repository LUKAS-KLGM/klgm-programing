# -*- coding: utf-8 -*-
"""
Website-Controller für kjr_grant — öffentliche und User-Seiten.

Routen:
  GET      /service/zuschuss                   Öffentliche Landingpage
  GET/POST /service/antrag-stellen             Antragsformular (Login)
  GET      /service/antrag-bestaetigung        Bestätigungsseite
"""
import base64
import logging
import os
from datetime import date as date_cls

from odoo import http, _
from odoo.http import request

_logger = logging.getLogger(__name__)
ALLOWED_EXTENSIONS = {'.pdf', '.xlsx', '.xls', '.csv', '.docx', '.doc', '.jpg', '.jpeg', '.png'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


class KjrWebsiteController(http.Controller):

    def _allowed_member_domain(self):
        """Verbände, für die der eingeloggte User einen Antrag stellen darf.
        KJR-Sachbearbeiter dürfen für alle Verbände stellen; normale Portal-User
        nur für den eigenen (commercial) Verband bzw. dessen Unterkontakte.
        Verhindert, dass ein Verband Anträge im Namen eines fremden Verbands stellt."""
        user = request.env.user
        if user.has_group('kjr_grant.group_kjr_reviewer'):
            return [('is_kjr_member', '=', True), ('is_company', '=', True)]
        commercial = user.partner_id.commercial_partner_id
        return [('is_kjr_member', '=', True), ('id', 'child_of', [commercial.id])]

    @http.route('/service/zuschuss', type='http', auth='public', website=True, sitemap=True)
    def kjr_landing(self, **kw):
        if not request.env.user._is_public():
            return request.redirect('/service/antrag-stellen')
        return request.render('kjr_grant.website_kjr_landing', {
            'page_name': 'kjr_landing',
        })

    @http.route(
        '/service/antrag-stellen', type='http', auth='user',
        website=True, methods=['GET', 'POST'], sitemap=True,
    )
    def kjr_apply(self, **post):
        grant_types = request.env['kjr.grant.type'].sudo().search([('active', '=', True)])
        kjr_members = request.env['res.partner'].sudo().search(
            self._allowed_member_domain(), order='name',
        )
        user_partner = request.env.user.partner_id
        preselected_member = request.env['res.partner'].sudo().search([
            ('is_kjr_member', '=', True),
            ('id', 'child_of', [user_partner.commercial_partner_id.id]),
        ], limit=1)

        if request.httprequest.method == 'POST':
            return self._process_application(post, kjr_members, grant_types)

        values = {}
        if preselected_member:
            values['partner_id'] = str(preselected_member.id)
        values['contact_person'] = user_partner.name or ''
        values['contact_email'] = user_partner.email or ''
        values['contact_phone'] = user_partner.phone or ''

        return request.render('kjr_grant.website_kjr_apply', {
            'grant_types': grant_types, 'kjr_members': kjr_members,
            'page_name': 'kjr_apply', 'errors': {}, 'values': values,
        })

    def _process_application(self, post, kjr_members, grant_types):
        errors = {}
        values = dict(post)

        def _i(key, default=0):
            try:
                return int(post.get(key) or default)
            except (ValueError, TypeError):
                return default

        for field, label in [
            ('partner_id',    _('Antragsteller (Organisation)')),
            ('grant_type_id', _('Förderart')),
            ('measure_name',  _('Maßnahmenbezeichnung')),
            ('measure_start', _('Beginn')),
            ('measure_end',   _('Ende')),
            ('tn_count',      _('Teilnehmeranzahl')),
        ]:
            if not post.get(field):
                errors[field] = _('%s ist ein Pflichtfeld.') % label

        valid_member_ids = kjr_members.ids
        partner_id = _i('partner_id')
        if partner_id not in valid_member_ids and not errors.get('partner_id'):
            errors['partner_id'] = _('Bitte einen gültigen KJR-Mitgliedsverband auswählen.')

        valid_type_ids = grant_types.ids
        if _i('grant_type_id') not in valid_type_ids and not errors.get('grant_type_id'):
            errors['grant_type_id'] = _('Ungültige Förderart.')

        if errors:
            return request.render('kjr_grant.website_kjr_apply', {
                'grant_types': grant_types, 'kjr_members': kjr_members,
                'page_name': 'kjr_apply', 'errors': errors, 'values': values,
            })

        try:
            measure_start = date_cls.fromisoformat(post['measure_start'])
            measure_end = date_cls.fromisoformat(post['measure_end'])
        except (ValueError, KeyError):
            errors['measure_start'] = _('Ungültiges Datumsformat (JJJJ-MM-TT erwartet).')
            return request.render('kjr_grant.website_kjr_apply', {
                'grant_types': grant_types, 'kjr_members': kjr_members,
                'page_name': 'kjr_apply', 'errors': errors, 'values': values,
            })

        def _f(key, default=0.0):
            try:
                return float(post.get(key) or default)
            except (ValueError, TypeError):
                return default

        def _time_to_float(val):
            if not val:
                return 0.0
            try:
                parts = val.split(':')
                return int(parts[0]) + int(parts[1]) / 60.0
            except (ValueError, IndexError):
                return 0.0

        try:
            app_vals = {
                'partner_id':              partner_id,
                'grant_type_id':           _i('grant_type_id'),
                'measure_name':            post.get('measure_name', '').strip(),
                'measure_start':           measure_start,
                'measure_start_time':      _time_to_float(post.get('measure_start_time')),
                'measure_end':             measure_end,
                'measure_end_time':        _time_to_float(post.get('measure_end_time')),
                'measure_location':        post.get('measure_location', '').strip(),
                'tn_count':                _i('tn_count'),
                'tn_leader_count':         _i('tn_leader_count'),
                'tn_leader_juleica':       _i('tn_leader_juleica'),
                'tn_external_count':       _i('tn_external_count'),
                'contact_person':          post.get('contact_person', '').strip(),
                'contact_email':           post.get('contact_email', '').strip(),
                'contact_phone':           post.get('contact_phone', '').strip(),
                'payment_account_holder':  post.get('payment_account_holder', '').strip(),
                'payment_iban':            post.get('payment_iban', '').strip(),
                'payment_bic':             post.get('payment_bic', '').strip(),
                'payment_bank':            post.get('payment_bank', '').strip(),
                'cost_accommodation':      _f('cost_accommodation'),
                'cost_transport':          _f('cost_transport'),
                'cost_referees':           _f('cost_referees'),
                'cost_allowances':         _f('cost_allowances'),
                'cost_materials':          _f('cost_materials'),
                'cost_jl_fees':            _f('cost_jl_fees'),
                'cost_other':              _f('cost_other'),
                'income_tn_fees':          _f('income_tn_fees'),
                'income_municipality':     _f('income_municipality'),
                'income_association':      _f('income_association'),
                'income_bjr':              _f('income_bjr'),
                'income_other':            _f('income_other'),
                'measure_report':          post.get('measure_report', '').strip(),
                'participant_consent':     bool(post.get('participant_consent')),
                'delegate_transport_mode': post.get('delegate_transport_mode') or False,
                'delegate_km_one_way':     _f('delegate_km_one_way'),
                'delegate_passenger_count': _i('delegate_passenger_count'),
            }
            application = request.env['kjr.grant.application'].sudo().create(app_vals)
            self._handle_participants(application, post)
            self._handle_file_uploads(application)
        except Exception as e:
            _logger.error('Fehler beim Erstellen des KJR-Antrags: %s', e, exc_info=True)
            errors['general'] = _(
                'Beim Erstellen des Antrags ist ein Fehler aufgetreten. '
                'Bitte versuchen Sie es erneut oder kontaktieren Sie die KJR-Geschäftsstelle.'
            )
            return request.render('kjr_grant.website_kjr_apply', {
                'grant_types': grant_types, 'kjr_members': kjr_members,
                'page_name': 'kjr_apply', 'errors': errors, 'values': values,
            })

        return request.redirect(f'/service/antrag-bestaetigung?app_id={application.id}')

    def _handle_participants(self, application, post):
        participant_model = request.env['kjr.grant.participant'].sudo()
        idx = 1
        while post.get(f'tn_name_{idx}'):
            name = post.get(f'tn_name_{idx}', '').strip()
            if not name:
                idx += 1
                continue
            vals = {
                'application_id': application.id,
                'sequence': idx * 10,
                'name': name,
                'zip_code': post.get(f'tn_zip_{idx}', '').strip(),
                'city': post.get(f'tn_city_{idx}', '').strip(),
                'is_leader': bool(post.get(f'tn_leader_{idx}')),
                'has_juleica': bool(post.get(f'tn_juleica_{idx}')),
            }
            birth = post.get(f'tn_birth_{idx}', '').strip()
            if birth:
                try:
                    vals['birthdate'] = date_cls.fromisoformat(birth)
                except ValueError:
                    pass
            participant_model.create(vals)
            idx += 1

    def _handle_file_uploads(self, application):
        FIELD_LABELS = {
            'tn_list_file': 'Teilnehmerliste',
            'report_file': 'Maßnahmenbericht',
            'receipt_file': 'Belegliste',
            'other_file_1': 'Weitere Unterlagen',
            'other_file_2': 'Weitere Unterlagen',
        }
        attachment_ids = []
        for field_name in FIELD_LABELS:
            for file_obj in request.httprequest.files.getlist(field_name):
                if not file_obj or not file_obj.filename:
                    continue
                filename = os.path.basename(file_obj.filename)
                _, ext = os.path.splitext(filename)
                if ext.lower() not in ALLOWED_EXTENSIONS:
                    continue
                file_obj.seek(0, 2)
                size = file_obj.tell()
                file_obj.seek(0)
                if size > MAX_FILE_SIZE:
                    continue
                try:
                    att = request.env['ir.attachment'].sudo().create({
                        'name': filename,
                        'type': 'binary',
                        'datas': base64.b64encode(file_obj.read()),
                        'res_model': 'kjr.grant.application',
                        'res_id': application.id,
                        'mimetype': file_obj.content_type or 'application/octet-stream',
                    })
                    attachment_ids.append(att.id)
                except Exception as e:
                    _logger.warning('Upload fehlgeschlagen (%s): %s', filename, e)
        if attachment_ids:
            application.sudo().message_post(
                body='Unterlagen zum Antrag hochgeladen.',
                attachment_ids=attachment_ids,
                subtype_xmlid='mail.mt_note',
            )

    @http.route('/service/antrag-bestaetigung', type='http', auth='user', website=True)
    def kjr_apply_confirmation(self, app_id=None, **kw):
        application = None
        if app_id:
            try:
                app_id = int(app_id)
            except (ValueError, TypeError):
                app_id = None
            if app_id:
                # Eigentumsprüfung statt sudo().browse: kein IDOR.
                # Sachbearbeiter dürfen (analog _allowed_member_domain) auch Anträge fremder
                # Verbände sehen; die Sichtbarkeit ist über die Record Rule reviewer_all gedeckt.
                user = request.env.user
                domain = [('id', '=', app_id)]
                if not user.has_group('kjr_grant.group_kjr_reviewer'):
                    commercial = user.partner_id.commercial_partner_id
                    domain.append(('partner_id', 'child_of', [commercial.id]))
                application = request.env['kjr.grant.application'].search(domain, limit=1) or None
        return request.render('kjr_grant.website_kjr_confirmation', {
            'application': application, 'page_name': 'kjr_apply',
        })
