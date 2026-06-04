# -*- coding: utf-8 -*-
"""Website- und Portal-Controller für den Materialverleih."""
import logging
from datetime import date as date_cls

from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError, MissingError

_logger = logging.getLogger(__name__)
ITEMS_PER_PAGE = 10


class KjrRentalWebsite(http.Controller):

    @http.route('/kjr/verleih', type='http', auth='public', website=True, sitemap=True)
    def rental_catalog(self, **kw):
        items = request.env['kjr.rental.item'].sudo().search([('website_published', '=', True)])
        categories = dict(request.env['kjr.rental.item']._fields['category'].selection)
        by_cat = {}
        for item in items:
            by_cat.setdefault(item.category, request.env['kjr.rental.item'].sudo())
            by_cat[item.category] |= item
        return request.render('kjr_rental.website_rental_catalog', {
            'items_by_category': by_cat, 'category_labels': categories, 'page_name': 'kjr_rental',
        })

    @http.route('/kjr/verleih/anfrage', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def rental_request(self, **post):
        items = request.env['kjr.rental.item'].sudo().search([('website_published', '=', True)])
        if request.httprequest.method == 'POST':
            errors = {}
            values = dict(post)
            check_from = check_to = None
            try:
                check_from = date_cls.fromisoformat(post.get('date_from', ''))
                check_to = date_cls.fromisoformat(post.get('date_to', ''))
            except (ValueError, TypeError):
                errors['date_from'] = _('Bitte gültigen Zeitraum (JJJJ-MM-TT) angeben.')
            if check_from and check_to and check_to < check_from:
                errors['date_to'] = _('Das Rückgabedatum darf nicht vor dem Ausleihdatum liegen.')

            selected = []
            for item in items:
                try:
                    qty = int(post.get('item_%d' % item.id) or 0)
                except (ValueError, TypeError):
                    qty = 0
                if qty > 0:
                    selected.append((item, qty))
            if not selected:
                errors['items'] = _('Bitte mindestens einen Artikel mit Menge wählen.')

            if errors:
                return request.render('kjr_rental.website_rental_request', {
                    'items': items, 'errors': errors, 'values': values, 'page_name': 'kjr_rental',
                })

            partner = request.env.user.partner_id.commercial_partner_id
            order = request.env['kjr.rental.order'].sudo().create({
                'partner_id': partner.id,
                'contact_email': post.get('contact_email') or request.env.user.email,
                'contact_phone': post.get('contact_phone') or partner.phone,
                'date_from': check_from,
                'date_to': check_to,
                'note': post.get('note', '').strip(),
                'line_ids': [(0, 0, {'item_id': item.id, 'quantity': qty}) for item, qty in selected],
            })
            return request.redirect('/my/ausleihen/%d' % order.id)

        return request.render('kjr_rental.website_rental_request', {
            'items': items, 'errors': {}, 'values': {
                'contact_email': request.env.user.email or '',
                'contact_phone': request.env.user.partner_id.phone or '',
            }, 'page_name': 'kjr_rental',
        })


class KjrRentalPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'kjr_rental_count' in counters:
            partner = request.env.user.partner_id.commercial_partner_id
            values['kjr_rental_count'] = request.env['kjr.rental.order'].search_count([
                ('partner_id', 'child_of', [partner.id]),
            ])
        return values

    @http.route(['/my/ausleihen', '/my/ausleihen/page/<int:page>'], type='http', auth='user', website=True)
    def portal_my_rentals(self, page=1, **kw):
        partner = request.env.user.partner_id.commercial_partner_id
        Order = request.env['kjr.rental.order']
        domain = [('partner_id', 'child_of', [partner.id])]
        total = Order.search_count(domain)
        pager = portal_pager(url='/my/ausleihen', total=total, page=page, step=ITEMS_PER_PAGE)
        orders = Order.search(domain, order='date_from desc', limit=ITEMS_PER_PAGE, offset=pager['offset'])
        return request.render('kjr_rental.portal_my_rentals', {
            'orders': orders, 'pager': pager, 'page_name': 'kjr_rental',
            'default_url': '/my/ausleihen',
        })

    @http.route('/my/ausleihen/<int:order_id>', type='http', auth='user', website=True)
    def portal_rental_detail(self, order_id, **kw):
        try:
            order = self._document_check_access('kjr.rental.order', order_id)
        except (AccessError, MissingError):
            return request.redirect('/my')
        return request.render('kjr_rental.portal_rental_detail', {
            'order': order, 'page_name': 'kjr_rental',
        })
