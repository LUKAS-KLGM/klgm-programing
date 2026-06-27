# -*- coding: utf-8 -*-
"""
Portal-Controller für kjr_grant — /my/ Routen für eingeloggte User.

Routen:
  GET      /my/kjr-antraege[/page/<n>]      Portal-Liste
  GET      /my/kjr-antraege/<id>            Portal-Detailansicht
  POST     /service/antrag/<id>/upload          Datei-Upload für bestehenden Antrag
"""
import base64
import logging
import os

from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError, MissingError

_logger = logging.getLogger(__name__)
ITEMS_PER_PAGE = 10
ALLOWED_EXTENSIONS = {'.pdf', '.xlsx', '.xls', '.csv', '.docx', '.doc', '.jpg', '.jpeg', '.png'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


class KjrPortalController(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'kjr_grant_count' in counters:
            partner = request.env.user.partner_id
            values['kjr_grant_count'] = request.env['kjr.grant.application'].search_count([
                ('partner_id', 'child_of', [partner.commercial_partner_id.id]),
            ])
        return values

    @http.route(
        ['/my/kjr-antraege', '/my/kjr-antraege/page/<int:page>'],
        type='http', auth='user', website=True,
    )
    def portal_my_kjr_grants(self, page=1, sortby='date', filterby='all', **kw):
        partner = request.env.user.partner_id
        domain = [('partner_id', 'child_of', [partner.commercial_partner_id.id])]

        filter_options = {
            'all':       {'label': _('Alle'),        'domain': []},
            'draft':     {'label': _('Entwürfe'),    'domain': [('state', '=', 'draft')]},
            'submitted': {'label': _('Eingereicht'), 'domain': [('state', 'in', ('submitted', 'in_review'))]},
            'approved':  {'label': _('Bewilligt'),   'domain': [('state', '=', 'approved')]},
            'paid':      {'label': _('Ausgezahlt'),  'domain': [('state', '=', 'paid')]},
            'rejected':  {'label': _('Abgelehnt'),   'domain': [('state', '=', 'rejected')]},
        }
        if filterby in filter_options:
            domain += filter_options[filterby]['domain']

        sort_options = {
            'date':  {'label': _('Datum'),   'order': 'date_submitted desc, name desc'},
            'name':  {'label': _('Nummer'),  'order': 'name asc'},
            'state': {'label': _('Status'),  'order': 'state asc, name desc'},
        }
        order = sort_options.get(sortby, sort_options['date'])['order']

        grant_model = request.env['kjr.grant.application']
        count = grant_model.search_count(domain)
        pager = portal_pager(
            url='/my/kjr-antraege',
            url_args={'sortby': sortby, 'filterby': filterby},
            total=count, page=page, step=ITEMS_PER_PAGE,
        )
        grants = grant_model.search(
            domain, order=order, limit=ITEMS_PER_PAGE, offset=pager['offset'],
        )
        return request.render('kjr_grant.portal_my_kjr_grants', {
            'grants': grants, 'pager': pager,
            'sortby': sortby, 'filterby': filterby,
            'searchbar_sortings': sort_options, 'searchbar_filters': filter_options,
            'page_name': 'kjr_grant', 'default_url': '/my/kjr-antraege',
        })

    @http.route('/my/kjr-antraege/<int:app_id>', type='http', auth='user', website=True)
    def portal_my_kjr_grant_detail(self, app_id, **kw):
        try:
            grant = self._document_check_access('kjr.grant.application', app_id)
        except (AccessError, MissingError):
            return request.redirect('/my')
        return request.render('kjr_grant.portal_kjr_grant_detail', {
            'grant': grant, 'page_name': 'kjr_grant',
        })

    @http.route(
        '/service/antrag/<int:app_id>/upload',
        type='http', auth='user', website=True, methods=['POST'], csrf=True,
    )
    def kjr_upload_attachment(self, app_id, **kw):
        try:
            application = self._document_check_access('kjr.grant.application', app_id)
        except (AccessError, MissingError):
            return request.redirect('/my')
        if application.state in ('draft', 'submitted'):
            attachment_ids = []
            for field_name in ['tn_list_file', 'report_file', 'receipt_file',
                               'other_file_1', 'other_file_2']:
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
                    body='Unterlagen nachgereicht.',
                    attachment_ids=attachment_ids,
                    subtype_xmlid='mail.mt_note',
                )
        return request.redirect(f'/my/kjr-antraege/{app_id}')
