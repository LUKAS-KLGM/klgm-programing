# -*- coding: utf-8 -*-
"""Website- und Portal-Controller für die Einrichtungsbuchung."""
import base64
import logging
from datetime import date as date_cls

from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError, MissingError

_logger = logging.getLogger(__name__)
ITEMS_PER_PAGE = 10


class KjrFacilityWebsite(http.Controller):

    @http.route('/service/einrichtungen', type='http', auth='public', website=True, sitemap=True)
    def facility_list(self, **kw):
        facilities = request.env['kjr.facility'].sudo().search([
            ('website_published', '=', True),
        ])
        return request.render('kjr_facility.website_facility_list', {
            'facilities': facilities, 'page_name': 'kjr_facilities',
        })

    @http.route('/service/einrichtung/<int:facility_id>', type='http', auth='public', website=True, sitemap=True)
    def facility_detail(self, facility_id, **kw):
        facility = request.env['kjr.facility'].sudo().browse(facility_id)
        if not facility.exists() or not facility.website_published:
            return request.redirect('/service/einrichtungen')
        return request.render('kjr_facility.website_facility_detail', {
            'facility': facility, 'page_name': 'kjr_facilities',
        })

    @http.route('/service/einrichtung/<int:facility_id>/anfrage', type='http', auth='user',
                website=True, methods=['GET', 'POST'])
    def facility_request(self, facility_id, **post):
        facility = request.env['kjr.facility'].sudo().browse(facility_id)
        if not facility.exists() or not facility.website_published:
            return request.redirect('/service/einrichtungen')

        if request.httprequest.method == 'POST':
            errors = {}
            values = dict(post)
            for f, label in [('check_in', _('Anreise')), ('check_out', _('Abreise')),
                             ('participant_count', _('Teilnehmer'))]:
                if not post.get(f):
                    errors[f] = _('%s ist ein Pflichtfeld.') % label
            check_in = check_out = None
            if not errors:
                try:
                    check_in = date_cls.fromisoformat(post['check_in'])
                    check_out = date_cls.fromisoformat(post['check_out'])
                except (ValueError, KeyError):
                    errors['check_in'] = _('Ungültiges Datum (JJJJ-MM-TT).')
                else:
                    if check_out <= check_in:
                        errors['check_out'] = _('Die Abreise muss nach der Anreise liegen.')
            # BUG-a: Verfügbarkeit/Doppelbelegung VOR dem Anlegen prüfen.
            if not errors and check_in and check_out:
                conflict = request.env['kjr.facility.booking'].sudo()._find_overlapping(
                    facility.id, check_in, check_out)
                if conflict:
                    errors['check_in'] = _(
                        'Im gewählten Zeitraum ist %s bereits belegt. Bitte wählen Sie '
                        'einen anderen Zeitraum.') % facility.name
            if errors:
                return request.render('kjr_facility.website_facility_request', {
                    'facility': facility, 'page_name': 'kjr_facilities',
                    'errors': errors, 'values': values,
                })

            def _i(key):
                try:
                    return int(post.get(key) or 0)
                except (ValueError, TypeError):
                    return 0

            partner = request.env.user.partner_id.commercial_partner_id
            booking = request.env['kjr.facility.booking'].sudo().create({
                'facility_id': facility.id,
                'partner_id': partner.id,
                'group_name': post.get('group_name', '').strip(),
                'contact_email': post.get('contact_email') or request.env.user.email,
                'contact_phone': post.get('contact_phone') or request.env.user.partner_id.phone,
                'check_in': check_in,
                'check_out': check_out,
                'participant_count': _i('participant_count'),
                'leader_count': _i('leader_count'),
                'meal_option': post.get('meal_option') if post.get('meal_option') in
                ('none', 'breakfast', 'half', 'full') else 'none',
                'note': post.get('note', '').strip(),
            })
            return request.redirect('/my/einrichtungsbuchungen/%d' % booking.id)

        return request.render('kjr_facility.website_facility_request', {
            'facility': facility, 'page_name': 'kjr_facilities',
            'errors': {}, 'values': {
                'contact_email': request.env.user.email or '',
                'contact_phone': request.env.user.partner_id.phone or '',
            },
        })


class KjrFacilityPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'kjr_booking_count' in counters:
            partner = request.env.user.partner_id.commercial_partner_id
            values['kjr_booking_count'] = request.env['kjr.facility.booking'].search_count([
                ('partner_id', 'child_of', [partner.id]),
            ])
        return values

    @http.route(['/my/einrichtungsbuchungen', '/my/einrichtungsbuchungen/page/<int:page>'],
                type='http', auth='user', website=True)
    def portal_my_bookings(self, page=1, **kw):
        partner = request.env.user.partner_id.commercial_partner_id
        Booking = request.env['kjr.facility.booking']
        domain = [('partner_id', 'child_of', [partner.id])]
        total = Booking.search_count(domain)
        pager = portal_pager(url='/my/einrichtungsbuchungen', total=total, page=page, step=ITEMS_PER_PAGE)
        bookings = Booking.search(domain, order='check_in desc', limit=ITEMS_PER_PAGE, offset=pager['offset'])
        return request.render('kjr_facility.portal_my_bookings', {
            'bookings': bookings, 'pager': pager, 'page_name': 'kjr_booking',
            'default_url': '/my/einrichtungsbuchungen',
        })

    @http.route('/my/einrichtungsbuchungen/<int:booking_id>', type='http', auth='user', website=True)
    def portal_booking_detail(self, booking_id, **kw):
        try:
            booking = self._document_check_access('kjr.facility.booking', booking_id)
        except (AccessError, MissingError):
            return request.redirect('/my')
        # BUG-b: prüfen, ob ein Vertrags-/Reservierungs-PDF abgelegt ist (Download-Link).
        has_contract = bool(request.env['ir.attachment'].sudo().search_count([
            ('res_model', '=', 'kjr.facility.booking'),
            ('res_id', '=', booking.id),
            ('mimetype', '=', 'application/pdf'),
        ]))
        return request.render('kjr_facility.portal_booking_detail', {
            'booking': booking, 'page_name': 'kjr_booking',
            'has_contract': has_contract,
        })

    @http.route('/my/einrichtungsbuchungen/<int:booking_id>/vertrag', type='http',
                auth='user', website=True)
    def portal_booking_contract(self, booking_id, **kw):
        """BUG-b: Download des abgelegten Vertrags-/Reservierungs-PDF aus dem Portal."""
        try:
            booking = self._document_check_access('kjr.facility.booking', booking_id)
        except (AccessError, MissingError):
            return request.redirect('/my')
        attachment = request.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'kjr.facility.booking'),
            ('res_id', '=', booking.id),
            ('mimetype', '=', 'application/pdf'),
        ], order='create_date desc', limit=1)
        if not attachment:
            # Fallback: Vertrag on-the-fly aus dem Report rendern.
            pdf_content, _dummy = request.env['ir.actions.report'].sudo()._render_qweb_pdf(
                'kjr_facility.action_report_booking_contract', res_ids=[booking.id])
            filename = 'Buchungsvertrag_%s.pdf' % (booking.name or '').replace('/', '-')
        else:
            pdf_content = base64.b64decode(attachment.datas)
            filename = attachment.name
        return request.make_response(pdf_content, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Disposition', f'attachment; filename="{filename}"'),
        ])
