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
CART_KEY = 'kjr_rental_cart'


class KjrRentalWebsite(http.Controller):

    # ------------------------------------------------------------------
    # Warenkorb-Helfer (Session-basiert)
    # ------------------------------------------------------------------
    def _get_cart(self):
        """Liste von {'item_id': int, 'qty': int} aus der Session."""
        cart = request.session.get(CART_KEY) or []
        # defensiv: nur gültige Einträge
        clean = []
        for entry in cart:
            try:
                item_id = int(entry.get('item_id'))
                qty = int(entry.get('qty'))
            except (AttributeError, TypeError, ValueError):
                continue
            if item_id and qty > 0:
                clean.append({'item_id': item_id, 'qty': qty})
        return clean

    def _save_cart(self, cart):
        request.session[CART_KEY] = cart
        request.session.modified = True

    def _cart_count(self):
        return sum(e['qty'] for e in self._get_cart())

    @http.route('/service/verleih', type='http', auth='public', website=True, sitemap=True)
    def rental_catalog(self, **kw):
        items = request.env['kjr.rental.item'].sudo().search([('website_published', '=', True)])
        by_cat = {}
        for item in items:
            by_cat.setdefault(item.category_id, request.env['kjr.rental.item'].sudo())
            by_cat[item.category_id] |= item
        return request.render('kjr_rental.website_rental_catalog', {
            'items_by_category': by_cat, 'page_name': 'kjr_rental',
            'cart_count': self._cart_count(),
            'is_public_user': request.env.user._is_public(),
        })

    # ------------------------------------------------------------------
    # R1: Warenkorb / Sammelbestellung
    # ------------------------------------------------------------------
    @http.route('/service/verleih/cart/add', type='json', auth='user', website=True, methods=['POST'])
    def rental_cart_add(self, item_id=None, qty=1, **kw):
        try:
            item_id = int(item_id)
            qty = int(qty)
        except (TypeError, ValueError):
            return {'error': _('Ungültige Eingabe.')}
        if qty <= 0:
            return {'error': _('Menge muss größer als 0 sein.')}
        item = request.env['kjr.rental.item'].sudo().browse(item_id)
        if not item.exists() or not item.website_published:
            return {'error': _('Artikel nicht verfügbar.')}
        cart = self._get_cart()
        for entry in cart:
            if entry['item_id'] == item_id:
                entry['qty'] += qty
                break
        else:
            cart.append({'item_id': item_id, 'qty': qty})
        self._save_cart(cart)
        return {'cart_count': self._cart_count(), 'item_name': item.name}

    def _cart_lines(self, date_from=None, date_to=None):
        """Aufbereitete Warenkorb-Zeilen inkl. Live-Verfügbarkeit."""
        Item = request.env['kjr.rental.item'].sudo()
        lines = []
        for entry in self._get_cart():
            item = Item.browse(entry['item_id'])
            if not item.exists():
                continue
            available = None
            if date_from and date_to:
                available = item.quantity_available(date_from, date_to)
            lines.append({
                'item': item,
                'qty': entry['qty'],
                'available': available,
            })
        return lines

    @http.route('/service/verleih/warenkorb', type='http', auth='user', website=True,
                methods=['GET', 'POST'])
    def rental_cart_view(self, **post):
        errors = {}
        values = dict(post)
        date_from = date_to = None
        # Mengenaktualisierung / Entfernen aus dem Warenkorb
        if request.httprequest.method == 'POST':
            cart = self._get_cart()
            remove_id = post.get('remove_item')
            if remove_id:
                try:
                    rid = int(remove_id)
                    cart = [e for e in cart if e['item_id'] != rid]
                except (TypeError, ValueError):
                    pass
            else:
                for entry in cart:
                    raw = post.get('qty_%d' % entry['item_id'])
                    if raw is not None:
                        try:
                            entry['qty'] = max(int(raw), 0)
                        except (TypeError, ValueError):
                            pass
                cart = [e for e in cart if e['qty'] > 0]
            self._save_cart(cart)

        raw_from = post.get('date_from', '')
        raw_to = post.get('date_to', '')
        if raw_from or raw_to:
            try:
                date_from = date_cls.fromisoformat(raw_from)
                date_to = date_cls.fromisoformat(raw_to)
            except (ValueError, TypeError):
                errors['date'] = _('Bitte gültigen Zeitraum (JJJJ-MM-TT) angeben.')
            if date_from and date_to and date_to < date_from:
                errors['date'] = _('Das Rückgabedatum darf nicht vor dem Ausleihdatum liegen.')
                date_from = date_to = None

        lines = self._cart_lines(date_from, date_to)
        return request.render('kjr_rental.website_rental_cart', {
            'lines': lines, 'errors': errors, 'values': values,
            'cart_count': self._cart_count(), 'page_name': 'kjr_rental',
            'date_from': raw_from, 'date_to': raw_to,
        })

    @http.route('/service/verleih/checkout', type='http', auth='user', website=True,
                methods=['POST'])
    def rental_checkout(self, **post):
        cart = self._get_cart()
        errors = {}
        date_from = date_to = None
        try:
            date_from = date_cls.fromisoformat(post.get('date_from', ''))
            date_to = date_cls.fromisoformat(post.get('date_to', ''))
        except (ValueError, TypeError):
            errors['date'] = _('Bitte gültigen Zeitraum (JJJJ-MM-TT) angeben.')
        if date_from and date_to and date_to < date_from:
            errors['date'] = _('Das Rückgabedatum darf nicht vor dem Ausleihdatum liegen.')
        if not cart:
            errors['items'] = _('Der Warenkorb ist leer.')

        if not errors:
            Item = request.env['kjr.rental.item'].sudo()
            line_vals = []
            for entry in cart:
                item = Item.browse(entry['item_id'])
                if not item.exists():
                    continue
                available = item.quantity_available(date_from, date_to)
                if entry['qty'] > available:
                    errors['items'] = _(
                        '"%(item)s": angefragt %(req)d, im Zeitraum verfügbar %(av)d.',
                        item=item.name, req=entry['qty'], av=available)
                    break
                line_vals.append((0, 0, {'item_id': item.id, 'quantity': entry['qty']}))

        if errors:
            lines = self._cart_lines(
                date_from if not errors.get('date') else None,
                date_to if not errors.get('date') else None)
            return request.render('kjr_rental.website_rental_cart', {
                'lines': lines, 'errors': errors, 'values': dict(post),
                'cart_count': self._cart_count(), 'page_name': 'kjr_rental',
                'date_from': post.get('date_from', ''), 'date_to': post.get('date_to', ''),
            })

        partner = request.env.user.partner_id.commercial_partner_id
        # BUG-Fix: company_id explizit aus der Website
        company = request.website.company_id
        order = request.env['kjr.rental.order'].sudo().create({
            'partner_id': partner.id,
            'company_id': company.id,
            'contact_email': post.get('contact_email') or request.env.user.email,
            'contact_phone': post.get('contact_phone') or partner.phone,
            'date_from': date_from,
            'date_to': date_to,
            'note': post.get('note', '').strip(),
            'line_ids': line_vals,
        })
        # Warenkorb leeren
        self._save_cart([])
        return request.redirect('/my/ausleihen/%d' % order.id)

    @http.route('/service/verleih/anfrage', type='http', auth='user', website=True, methods=['GET', 'POST'])
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
                'company_id': request.website.company_id.id,
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
