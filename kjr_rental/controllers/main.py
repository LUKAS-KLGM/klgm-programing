# -*- coding: utf-8 -*-
"""Website- und Portal-Controller für den Materialverleih."""
import logging
from datetime import date as date_cls

from markupsafe import Markup

from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError, MissingError
from odoo.tools import email_normalize, is_html_empty

_logger = logging.getLogger(__name__)
ITEMS_PER_PAGE = 10
CART_KEY = 'kjr_rental_cart'
# R3: Seed-Artikel für die Spielmobil-Anfrage (wird über die Stammdaten geliefert).
SPIELMOBIL_XMLID = 'kjr_rental.item_spielmobil'


class KjrRentalWebsite(http.Controller):

    # ------------------------------------------------------------------
    # Gemeinsame Helfer: Tarif, Pflichtfelder, Nutzungshinweise
    # ------------------------------------------------------------------
    def _website_partner(self):
        """Kontakt, auf den ein Vorgang gebucht wird (kaufmännischer Hauptkontakt)."""
        return request.env.user.partner_id.commercial_partner_id

    def _partner_is_member(self, partner):
        """Mitgliedstarif-Kennzeichen des Kontakts.

        sudo(): Portal- und öffentliche Nutzer dürfen ihren eigenen Kontakt nur
        eingeschränkt lesen; das Kennzeichen ist reine Stammdatenpflege der
        Geschäftsstelle und wird hier nur ausgewertet, nicht verändert.
        """
        if not partner:
            return False
        return bool(partner.sudo().is_kjr_member)

    def _usage_warning_items(self, items):
        """Artikel mit gepflegten Nutzungshinweisen (Reihenfolge bleibt erhalten).

        is_html_empty(): ein leerer Html-Editor liefert '<p><br></p>' und wäre
        sonst „gefüllt“ – der Nutzer müsste einen leeren Hinweis bestätigen.
        """
        seen, result = set(), []
        for item in items:
            if item.id in seen:
                continue
            seen.add(item.id)
            if not is_html_empty(item.usage_warning):
                result.append(item)
        return result

    def _can_stream_item_images(self):
        """Kann der aktuelle Besucher Artikelbilder über /web/image laden?

        Die Katalogseite selbst wird mit sudo() aufbereitet, die Bilder holt der
        Browser aber in EINEM EIGENEN Request ohne sudo. Fehlt dem Besucher das
        Leserecht auf kjr.rental.item, liefert /web/image den grauen Odoo-
        Platzhalter – das sähe schlechter aus als unser Icon-Fallback.
        Leere Recordset + has_access() prüft genau das Modellrecht (ir.model.access).
        Hinweis: Für die öffentliche Gruppe ist derzeit kein Leserecht auf
        kjr.rental.item hinterlegt; sobald es ergänzt wird, zeigt der Katalog die
        Fotos automatisch auch nicht angemeldeten Besuchern.
        """
        return request.env['kjr.rental.item'].browse().has_access('read')

    @staticmethod
    def _is_checked(raw):
        """HTML-Checkbox robust auswerten (Browser senden 'on', JS ggf. '1'/'true')."""
        return str(raw or '').strip().lower() in ('1', 'true', 'on', 'yes', 'ja')

    def _validate_purpose(self, post, errors):
        """Zweck der Nutzung ist Pflicht im Website-Formular (Projektstandard:
        NICHT required=True am Modell – die Geschäftsstelle muss unvollständige
        Vorgänge im Backend erfassen können)."""
        purpose = (post.get('purpose') or '').strip()
        if not purpose:
            errors['purpose'] = _(
                'Bitte beschreiben Sie kurz den Zweck der Nutzung. Der Verleih ist an '
                'Zwecke der Kinder- und Jugendarbeit nach dem SGB VIII gebunden.')
        return purpose

    def _validate_usage_terms(self, warn_items, post, errors):
        """Nutzungshinweise müssen bestätigt sein, sobald mindestens ein angefragter
        Artikel welche hat. Serverseitig erzwungen – das Template-`required` allein
        genügt nicht (JS deaktiviert, direkter POST)."""
        accepted = self._is_checked(post.get('usage_terms_accepted'))
        if warn_items and not accepted:
            errors['usage_terms'] = _(
                'Bitte bestätigen Sie die Nutzungshinweise zu den gewählten Artikeln '
                '(%(items)s), bevor Sie die Anfrage absenden.',
                items=', '.join(i.name for i in warn_items),
            )
        return accepted

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
        is_public_user = request.env.user._is_public()
        partner = self._website_partner() if not is_public_user else None
        return request.render('kjr_rental.website_rental_catalog', {
            'items_by_category': by_cat, 'page_name': 'kjr_rental',
            'cart_count': self._cart_count(),
            'is_public_user': is_public_user,
            'partner': partner,
            'is_member': self._partner_is_member(partner),
            'show_images': self._can_stream_item_images(),
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

    def _cart_render_values(self, post, errors, date_from=None, date_to=None):
        """Einheitliche Renderwerte der Warenkorbseite (GET, Aktualisierung und
        Checkout-Fehlerfall) – so bleiben Tarifanzeige und Nutzungshinweise überall gleich."""
        lines = self._cart_lines(date_from, date_to)
        partner = self._website_partner()
        usage_items = self._usage_warning_items([line['item'] for line in lines])
        return {
            'lines': lines, 'errors': errors, 'values': dict(post),
            'cart_count': self._cart_count(), 'page_name': 'kjr_rental',
            'date_from': post.get('date_from', ''), 'date_to': post.get('date_to', ''),
            'partner': partner,
            'is_member': self._partner_is_member(partner),
            'usage_items': usage_items,
            # Pflicht-Checkbox: im Warenkorb ist die Artikelmenge serverseitig bekannt,
            # das Attribut kann deshalb hart gesetzt werden.
            'usage_required': bool(usage_items),
        }

    @http.route('/service/verleih/warenkorb', type='http', auth='user', website=True,
                methods=['GET', 'POST'])
    def rental_cart_view(self, **post):
        errors = {}
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

        return request.render(
            'kjr_rental.website_rental_cart',
            self._cart_render_values(post, errors, date_from, date_to))

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

        # Pflichtangaben des Website-Formulars
        purpose = self._validate_purpose(post, errors)
        cart_items = [line['item'] for line in self._cart_lines()]
        warn_items = self._usage_warning_items(cart_items)
        terms_accepted = self._validate_usage_terms(warn_items, post, errors)

        line_vals = []
        if not errors:
            Item = request.env['kjr.rental.item'].sudo()
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
            values = self._cart_render_values(
                post, errors,
                date_from if not errors.get('date') else None,
                date_to if not errors.get('date') else None)
            return request.render('kjr_rental.website_rental_cart', values)

        partner = self._website_partner()
        # BUG-Fix: company_id explizit aus der Website
        company = request.website.company_id
        order = request.env['kjr.rental.order'].sudo().create({
            'partner_id': partner.id,
            'company_id': company.id,
            'contact_email': post.get('contact_email') or request.env.user.email,
            'contact_phone': post.get('contact_phone') or partner.phone,
            'date_from': date_from,
            'date_to': date_to,
            # Mitgliedstarif hier EXPLIZIT setzen: @api.onchange feuert bei create()
            # aus dem Controller nicht, die Positionspreise würden sonst zum
            # Standardtarif berechnet.
            'is_member': self._partner_is_member(partner),
            'purpose': purpose,
            'usage_terms_accepted': terms_accepted,
            'note': post.get('note', '').strip(),
            'line_ids': line_vals,
        })
        # Warenkorb leeren
        self._save_cart([])
        return request.redirect('/my/ausleihen/%d' % order.id)

    @http.route('/service/verleih/anfrage', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def rental_request(self, **post):
        items = request.env['kjr.rental.item'].sudo().search([('website_published', '=', True)])
        partner = self._website_partner()
        is_member = self._partner_is_member(partner)
        # Auf der Direktanfrage steht die Artikelauswahl erst nach dem Absenden fest.
        # Deshalb werden die Hinweise ALLER Artikel mit Nutzungsregeln angezeigt; die
        # Pflicht zur Bestätigung greift serverseitig nur für die tatsächlich
        # gewählten Artikel (kein hartes required im Formular).
        # TODO: Wenn der KJR eine dynamische Einblendung wünscht, dafür ein eigenes
        # Frontend-Asset vorsehen (bewusst kein Inline-Script in diesem Template).
        all_usage_items = self._usage_warning_items(items)

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

            purpose = self._validate_purpose(post, errors)
            warn_items = self._usage_warning_items([item for item, _qty in selected])
            terms_accepted = self._validate_usage_terms(warn_items, post, errors)

            if errors:
                return request.render('kjr_rental.website_rental_request', {
                    'items': items, 'errors': errors, 'values': values, 'page_name': 'kjr_rental',
                    'partner': partner, 'is_member': is_member,
                    'usage_items': all_usage_items, 'usage_required': False,
                })

            order = request.env['kjr.rental.order'].sudo().create({
                'partner_id': partner.id,
                'company_id': request.website.company_id.id,
                'contact_email': post.get('contact_email') or request.env.user.email,
                'contact_phone': post.get('contact_phone') or partner.phone,
                'date_from': check_from,
                'date_to': check_to,
                # siehe Checkout: Mitgliedstarif explizit mitgeben
                'is_member': is_member,
                'purpose': purpose,
                'usage_terms_accepted': terms_accepted,
                'note': post.get('note', '').strip(),
                'line_ids': [(0, 0, {'item_id': item.id, 'quantity': qty}) for item, qty in selected],
            })
            return request.redirect('/my/ausleihen/%d' % order.id)

        return request.render('kjr_rental.website_rental_request', {
            'items': items, 'errors': {}, 'values': {
                'contact_email': request.env.user.email or '',
                'contact_phone': request.env.user.partner_id.phone or '',
            }, 'page_name': 'kjr_rental',
            'partner': partner, 'is_member': is_member,
            'usage_items': all_usage_items, 'usage_required': False,
        })

    # ------------------------------------------------------------------
    # R3: Spielmobil – Infoseite mit Anfrageformular
    # ------------------------------------------------------------------
    def _spielmobil_item(self):
        """Seed-Artikel „Spielmobil" oder None.

        Der Artikel kommt aus den Stammdaten und kann fehlen (Daten nicht geladen,
        Artikel archiviert/gelöscht). Der Aufrufer MUSS None abfangen – die Seite
        soll dann eine verständliche Meldung zeigen und keinen Serverfehler.
        """
        # env(su=True): ir.model.data ist für öffentliche Nutzer nicht lesbar.
        item = request.env(su=True).ref(SPIELMOBIL_XMLID, raise_if_not_found=False)
        if item is None or item._name != 'kjr.rental.item' or not item.exists():
            return None
        return item

    def _spielmobil_partner(self, email, contact_person, organisation, phone):
        """Kontakt für die Anfrage ermitteln.

        SICHERHEIT — bewusste Abwägung zwischen Komfort und Identitätsschutz:
        Die Route ist auth='public'. Ein nicht angemeldeter Absender hat seine
        E-Mail-Adresse NICHT nachgewiesen. Eine Zuordnung über
        search([('email', '=ilike', ...)]) würde deshalb jedem, der die Mailadresse
        eines Mitgliedsverbands kennt, erlauben, eine Anfrage auf dessen Namen zu
        erzeugen – inklusive Mitgliedstarif und Sichtbarkeit im Portal des fremden
        Verbands. Anonyme Anfragen werden daher NIEMALS einem bestehenden Kontakt
        zugeordnet; es entsteht immer ein neuer, ausdrücklich als ungeprüft
        gekennzeichneter Kontakt.

        Preis dieser Entscheidung: Bei wiederholten Anfragen derselben Gemeinde
        entstehen Dubletten. Das ist gewollt – das Zusammenführen ist Stammdaten-
        pflege der Geschäftsstelle (res.partner bietet dafür die Dubletten-
        Zusammenführung), eine Identitätsübernahme wäre dagegen nicht heilbar.
        Angemeldete Nutzer buchen unverändert auf ihren eigenen Hauptkontakt –
        dort ist die Identität durch die Anmeldung belegt.
        """
        if not request.env.user._is_public():
            return self._website_partner()
        Partner = request.env['res.partner'].sudo()
        name = organisation or contact_person or email or _('Unbekannte Anfrage')
        return Partner.create({
            # Kennzeichnung direkt im Namen: die Geschäftsstelle sieht in jeder
            # Liste und in jedem Bericht sofort, dass der Kontakt aus einer
            # unbestätigten Website-Anfrage stammt.
            'name': _('%s (ungeprüfte Website-Anfrage)') % name,
            'is_company': bool(organisation),
            'email': email or False,
            'phone': phone or False,
            # is_kjr_member wird BEWUSST nicht gesetzt: der Mitgliedsstatus darf
            # nur aus der Stammdatenpflege der Geschäftsstelle kommen.
            'comment': _(
                'Automatisch angelegt aus der Spielmobil-Anfrage der Website.\n'
                'Der Absender war NICHT angemeldet: Name, E-Mail-Adresse, Telefon '
                'und Mitgliedsstatus sind ungeprüft. Bitte vor der Reservierung '
                'bestätigen und den Kontakt gegebenenfalls mit dem bestehenden '
                'Datensatz zusammenführen.'),
        })

    # Postfach für Spielmobil-Anfragen. Leer = Firmen-E-Mail der Website-Company.
    SPIELMOBIL_MAIL_PARAM = 'kjr_rental.spielmobil_notify_email'

    def _spielmobil_notify(self, order, contact_person, organisation, place,
                           participants, wish_date, email, phone):
        """Anfrage per Mail an das KJR-Postfach schicken.

        Ausdrückliche Anforderung aus dem Website-Termin am 23.07.2026: das
        Spielmobil-Formular „geht per Mail ans KJR-Postfach". Der angelegte
        Vorgang allein genügt nicht — die Geschäftsstelle arbeitet nicht
        dauerhaft im Backend und würde die Anfrage sonst erst spät sehen.

        Empfänger: Systemparameter kjr_rental.spielmobil_notify_email, sonst die
        E-Mail-Adresse der Website-Company. Fehlt beides, wird nur protokolliert —
        eine fehlende Mailadresse darf die Anfrage des Bürgers nicht scheitern
        lassen, der Vorgang ist ja bereits gespeichert.
        """
        company = order.company_id or request.website.company_id
        recipient = (request.env['ir.config_parameter'].sudo()
                     .get_param(self.SPIELMOBIL_MAIL_PARAM) or '').strip()
        recipient = recipient or (company.email or '').strip()
        if not recipient:
            _logger.warning(
                'Spielmobil-Anfrage %s: kein Empfänger für die Benachrichtigung '
                '(Systemparameter %s und Firmen-E-Mail sind leer).',
                order.name, self.SPIELMOBIL_MAIL_PARAM)
            return
        body = Markup(
            '<p>Über das Formular <strong>Spielmobil</strong> auf der Website ist eine '
            'neue Anfrage eingegangen.</p>'
            '<table style="border-collapse:collapse">'
            '<tr><td><strong>Vorgang</strong></td><td>%(order)s</td></tr>'
            '<tr><td><strong>Gemeinde / Organisation</strong></td><td>%(org)s</td></tr>'
            '<tr><td><strong>Ansprechpartner/in</strong></td><td>%(person)s</td></tr>'
            '<tr><td><strong>E-Mail</strong></td><td>%(email)s</td></tr>'
            '<tr><td><strong>Telefon</strong></td><td>%(phone)s</td></tr>'
            '<tr><td><strong>Wunschtermin</strong></td><td>%(date)s</td></tr>'
            '<tr><td><strong>Einsatzort</strong></td><td>%(place)s</td></tr>'
            '<tr><td><strong>Erwartete Teilnehmerzahl</strong></td><td>%(pax)s</td></tr>'
            '</table>'
            '<p>Zweck der Nutzung:<br/>%(purpose)s</p>'
        ) % {
            'order': order.name or '',
            'org': organisation,
            'person': contact_person,
            'email': email,
            'phone': phone,
            'date': wish_date.strftime('%d.%m.%Y') if wish_date else '',
            'place': place,
            'pax': participants,
            'purpose': order.purpose or '',
        }
        try:
            # savepoint(): ein Datenbankfehler beim Anlegen der Mail (z. B. verletzte
            # Bedingung) würde die laufende Transaktion sonst abbrechen — das except
            # unten schluckt zwar die Ausnahme, aber JEDE weitere Abfrage des Requests
            # (Rendern der Bestätigungsseite) liefe danach ins Leere und der bereits
            # gespeicherte Vorgang des Bürgers ginge mit zurück. Der Savepoint macht
            # nur den Mailversand rückgängig, der Vorgang bleibt bestehen.
            with request.env.cr.savepoint():
                request.env['mail.mail'].sudo().create({
                    'subject': _('Spielmobil-Anfrage: %(org)s zum %(date)s', org=organisation,
                                 date=wish_date.strftime('%d.%m.%Y') if wish_date else ''),
                    'email_to': recipient,
                    'reply_to': email or recipient,
                    'body_html': body,
                    'auto_delete': True,
                }).send()
        except Exception:
            # Der Vorgang ist gespeichert – ein Mailfehler darf die Anfrage nicht
            # zurückweisen. Die Geschäftsstelle findet sie im Backend.
            _logger.exception('Spielmobil-Anfrage %s: Benachrichtigung fehlgeschlagen.',
                              order.name)

    def _spielmobil_prices_confirmed(self, item):
        """Dürfen auf der öffentlichen Spielmobil-Seite Preise genannt werden?

        Die Seite ist auth='public', der Seed-Artikel steht dagegen mit 0,00 € und
        website_published=False in den Stammdaten – die Preise sind laut Seed-Daten
        ausdrücklich unbestätigte Platzhalter. Eine öffentlich lesbare Angabe
        „0,00 € pro Tag" wäre eine Preisauskunft, an der sich Gemeinden festhalten
        würden. Preise werden deshalb NUR genannt, wenn die Geschäftsstelle sie
        freigegeben hat:
        - website_published: bewusstes Veröffentlichen durch die Geschäftsstelle,
        - mindestens ein Tagespreis > 0: gepflegter, kein Platzhalterwert.
        Die Kaution allein genügt nicht – sonst stünde neben ihr wieder
        „Standardtarif: 0,00 € pro Tag".
        """
        if not item:
            return False
        return bool(item.website_published) and (
            item.price_per_day > 0 or item.price_member_per_day > 0)

    def _spielmobil_values(self, item, values=None, errors=None, order=None):
        usage_items = self._usage_warning_items(item) if item else []
        partner = None if request.env.user._is_public() else self._website_partner()
        return {
            'page_name': 'kjr_rental',
            'item': item,
            'values': values or {},
            'errors': errors or {},
            'order': order,
            'is_public_user': request.env.user._is_public(),
            'partner': partner,
            'is_member': self._partner_is_member(partner),
            'usage_items': usage_items,
            'usage_required': bool(usage_items),
            'cart_count': self._cart_count(),
            'show_images': self._can_stream_item_images(),
            'show_prices': self._spielmobil_prices_confirmed(item),
        }

    @http.route('/service/spielmobil', type='http', auth='public', website=True,
                sitemap=True, methods=['GET', 'POST'])
    def rental_spielmobil(self, **post):
        item = self._spielmobil_item()
        if request.httprequest.method != 'POST':
            return request.render('kjr_rental.website_spielmobil',
                                  self._spielmobil_values(item))

        errors = {}
        values = dict(post)
        if not item:
            # Verständliche Meldung statt Serverfehler, wenn der Seed-Artikel fehlt.
            errors['item'] = _(
                'Das Spielmobil ist derzeit nicht für Online-Anfragen hinterlegt. '
                'Bitte wenden Sie sich direkt an die Geschäftsstelle des Kreisjugendrings.')

        contact_person = (post.get('contact_person') or '').strip()
        organisation = (post.get('organisation') or '').strip()
        phone = (post.get('contact_phone') or '').strip()
        place = (post.get('place') or '').strip()
        email = email_normalize(post.get('contact_email') or '')
        if not contact_person:
            errors['contact_person'] = _('Bitte eine Ansprechpartnerin oder einen Ansprechpartner angeben.')
        if not organisation:
            errors['organisation'] = _(
                'Bitte den Namen der anfragenden Gemeinde angeben. Das Spielmobil steht '
                'ausschließlich Gemeinden im Landkreis Oberallgäu zur Verfügung '
                '(Entscheidung KJR vom 23.07.2026).')
        if not email:
            errors['contact_email'] = _('Bitte eine gültige E-Mail-Adresse angeben.')
        if not phone:
            errors['contact_phone'] = _('Bitte eine Telefonnummer für Rückfragen angeben.')
        if not place:
            errors['place'] = _('Bitte den geplanten Einsatzort angeben.')

        wish_date = None
        try:
            wish_date = date_cls.fromisoformat(post.get('date_wish', ''))
        except (ValueError, TypeError):
            errors['date_wish'] = _('Bitte einen Wunschtermin (JJJJ-MM-TT) angeben.')
        if wish_date and wish_date < date_cls.today():
            errors['date_wish'] = _('Der Wunschtermin darf nicht in der Vergangenheit liegen.')

        try:
            participants = int(post.get('participants') or 0)
        except (TypeError, ValueError):
            participants = 0
        if participants <= 0:
            errors['participants'] = _('Bitte die erwartete Teilnehmerzahl als Zahl angeben.')

        purpose = self._validate_purpose(post, errors)
        warn_items = self._usage_warning_items(item) if item else []
        terms_accepted = self._validate_usage_terms(warn_items, post, errors)

        if errors:
            return request.render('kjr_rental.website_spielmobil',
                                  self._spielmobil_values(item, values, errors))

        is_public = request.env.user._is_public()
        partner = self._spielmobil_partner(email, contact_person, organisation, phone)
        note_lines = [
            _('Anfrage über das Online-Formular „Spielmobil".'),
            _('Ansprechpartner/in: %s') % contact_person,
            _('Organisation: %s') % organisation,
            _('Einsatzort: %s') % place,
            _('Erwartete Teilnehmerzahl: %s') % participants,
        ]
        if is_public:
            note_lines.append(_(
                'ACHTUNG – Absender war NICHT angemeldet: Die Identität des Absenders '
                'ist nicht nachgewiesen. Der Kontakt wurde deshalb neu angelegt und '
                'nicht einem bestehenden Verband zugeordnet; der Vorgang läuft zunächst '
                'zum Standardtarif. Kontaktdaten, Zuordnung und Mitgliedsstatus bitte '
                'vor der Reservierung prüfen und den Vorgang danach gegebenenfalls auf '
                'den richtigen Kontakt umtragen.'))
        if (post.get('note') or '').strip():
            note_lines.append(_('Anmerkungen: %s') % post.get('note').strip())

        order = request.env['kjr.rental.order'].sudo().create({
            'partner_id': partner.id,
            'company_id': request.website.company_id.id,
            'contact_email': email,
            'contact_phone': phone,
            # Einsatz an einem Tag: Beginn = Ende. Mehrtägige Einsätze klärt die
            # Geschäftsstelle im Vorgang.
            'date_from': wish_date,
            'date_to': wish_date,
            # Mitgliedstarif niemals aus einer ungeprüften Anfrage übernehmen:
            # bei anonymen Absendern hart Standardtarif. Die Geschäftsstelle kann
            # is_member im Vorgang übersteuern, sobald der Verband bestätigt ist.
            # (Ein hier mitgegebener Wert schützt das speichernde Compute-Feld vor
            # dem Neuberechnen – siehe _compute_is_member.)
            'is_member': False if is_public else self._partner_is_member(partner),
            'purpose': purpose,
            'usage_terms_accepted': terms_accepted,
            'note': '\n'.join(note_lines),
            'line_ids': [(0, 0, {'item_id': item.id, 'quantity': 1})],
        })
        self._spielmobil_notify(order, contact_person, organisation, place,
                                participants, wish_date, email, phone)
        if not is_public:
            return request.redirect('/my/ausleihen/%d' % order.id)
        # Öffentliche Absender haben keinen Portalzugang -> Bestätigung auf der Seite.
        return request.render('kjr_rental.website_spielmobil',
                              self._spielmobil_values(item, order=order))


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
