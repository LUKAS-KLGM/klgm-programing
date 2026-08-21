# -*- coding: utf-8 -*-
"""Website- und Portal-Controller für die Einrichtungsbuchung."""
import base64
import logging
from datetime import date as date_cls

from dateutil.relativedelta import relativedelta

from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError, MissingError

_logger = logging.getLogger(__name__)
ITEMS_PER_PAGE = 10
MEAL_OPTIONS = ('none', 'breakfast', 'half', 'full')
# Werte, die ein angehaktes Kästchen im HTML-Formular liefern kann.
CHECKBOX_TRUE = ('1', 'true', 'on', 'yes', 'ja', 'checked')


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

    # ══════════════════════════════════════════════════════════════════════════
    # ANFRAGEFORMULAR — Hilfsfunktionen
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _to_int(value):
        """Robuste Umwandlung eines Formularwerts in eine ganze Zahl (0 als Fallback)."""
        try:
            return int(value or 0)
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _to_date(value):
        """Formularwert (JJJJ-MM-TT) in ein Datum wandeln; None bei ungültiger Eingabe."""
        try:
            return date_cls.fromisoformat((value or '').strip())
        except (ValueError, AttributeError, TypeError):
            return None

    @staticmethod
    def _to_bool(value):
        """Ankreuzfeld auswerten (ein nicht angehaktes Kästchen wird gar nicht gesendet)."""
        return str(value or '').strip().lower() in CHECKBOX_TRUE

    @staticmethod
    def _meal_option_for(facility, value):
        """Verpflegungsauswahl serverseitig auf das Angebot der Einrichtung begrenzen.

        Erbringt die Einrichtung keine Verpflegung (`kjr.facility.offers_catering`
        ist nicht gesetzt — beide Häuser des KJR sind Selbstversorgerhäuser), wird ein
        trotzdem übermittelter Wert VERWORFEN und 'none' (Selbstverpflegung) gesetzt.

        Bewusst OHNE Fehlermeldung: Das Formular bietet die Auswahl bei
        Selbstverpflegung gar nicht erst an (siehe website_facility_request). Ein
        gesendeter Wert kann deshalb nur aus einem veralteten, zwischengespeicherten
        oder manipulierten Formular stammen — also aus einem Umstand, den die
        anfragende Gruppe nicht zu verantworten hat. Daran soll ihre Anfrage nicht
        scheitern; die Angabe wird still auf den einzig zutreffenden Wert korrigiert.

        Gilt ausschließlich für NEUE bzw. hier erfasste Vorgänge. Bereits
        gespeicherte Buchungen rührt das nicht an — deren `amount_meals` bleibt
        unverändert, damit fakturierte Beträge nicht nachträglich abweichen.
        """
        if not facility.offers_catering:
            return 'none'
        return value if value in MEAL_OPTIONS else 'none'

    @staticmethod
    def _nights_label(count):
        """Deutsche Ein-/Mehrzahl für Nächte — für gut lesbare Fehlermeldungen."""
        return _('1 Nacht') if count == 1 else _('%d Nächte') % count

    def _website_tariff(self, facility):
        """Tarif, der dem Formular (Zusatzpositionen + Kostenvorschau) zugrunde liegt.

        Die endgültige Tarifgruppe (Mitgliedsverband, Partner, kommerziell) ordnet die
        Geschäftsstelle im Backend zu — im öffentlichen Formular wird bewusst konservativ
        der Standardtarif angesetzt. Einrichtungsspezifische Tarife haben Vorrang vor
        den übergreifenden Tarifen (facility_id leer)."""
        Tariff = request.env['kjr.facility.tariff'].sudo()
        for domain in (
            [('facility_id', '=', facility.id), ('tariff_type', '=', 'standard')],
            [('facility_id', '=', facility.id)],
            [('facility_id', '=', False), ('tariff_type', '=', 'standard')],
            [('facility_id', '=', False)],
        ):
            tariff = Tariff.search(domain, limit=1)
            if tariff:
                return tariff
        return Tariff.browse()

    @staticmethod
    def _tariff_rate_maintained(tariff):
        """Ist am Tarif überhaupt ein Übernachtungssatz gepflegt?

        Ein Betrag von 0,00 € ist KEINE Preisaussage, solange er auch schlicht der
        Startwert eines nie gepflegten Feldes sein kann: Die Tarife der Stammdaten
        stehen bewusst auf 0,00 € (siehe TODO(KJR) in
        data/kjr_facility_data.xml — die Sätze der Live-Seite sind nicht belegt).
        Ohne diese Prüfung rechnet die Kostenvorschau daraus eine vollständige
        Aufstellung mit „Unterkunft 0,00 €" und „Gesamt (brutto) 0,00 €" — für die
        anfragende Gruppe liest sich das als kostenloser Aufenthalt und ist schlimmer
        als gar keine Angabe, weil es plausibel wirkt.

        Anker ist der Übernachtungssatz (Personenpreis, Mo–Fr-Preis oder Pauschale
        je Nacht) — dieselbe Regel wie im Materialverleih, wo der Standardbetrag
        derselben Betragsart darüber entscheidet, ob eine Zahl genannt werden darf.
        Verpflegung, Endreinigung und Fremdenverkehrsbeitrag taugen NICHT als Anker:
        ohne Übernachtungssatz stünde in der Aufstellung weiterhin „Unterkunft
        0,00 €".
        """
        if not tariff:
            return False
        return any((getattr(tariff, name, 0.0) or 0.0) > 0 for name in (
            'price_per_person_night',
            'weekday_price_per_person_night',
            'price_flat_per_night',
        ))

    def _facility_request_preview(self, facility, tariff, values):
        """Kostenvorschau für das Formular — bewusst OHNE eigene Rechenlogik.

        Es wird ein nicht gespeicherter Buchungssatz (`new()`) aufgebaut und dessen
        Compute-Felder ausgelesen. Damit rechnet die Vorschau garantiert mit derselben
        Logik wie das Modell (`_compute_amounts`); eine zweite Preisformel im Frontend
        gibt es ausdrücklich nicht. Liefert None, wenn zu wenig Daten vorliegen ODER
        der Tarif noch keinen gepflegten Übernachtungssatz hat (siehe
        _tariff_rate_maintained) — eine Aufstellung aus lauter Nullbeträgen wäre eine
        falsche Preisauskunft."""
        check_in = self._to_date(values.get('check_in'))
        check_out = self._to_date(values.get('check_out'))
        pax = self._to_int(values.get('participant_count'))
        if not (tariff and check_in and check_out and check_out > check_in and pax > 0):
            return None
        if not self._tariff_rate_maintained(tariff):
            return None
        # Ohne Verpflegungsangebot der Einrichtung rechnet die Vorschau mit
        # 'none' — die Verpflegungszeile bleibt dadurch bei 0,00 € und wird im
        # Template nicht ausgegeben.
        meal = self._meal_option_for(facility, values.get('meal_option'))
        try:
            draft = request.env['kjr.facility.booking'].sudo().new({
                'company_id': request.env.company.id,
                'facility_id': facility.id,
                'tariff_id': tariff.id,
                'check_in': check_in,
                'check_out': check_out,
                'participant_count': pax,
                'leader_count': self._to_int(values.get('leader_count')),
                'meal_option': meal,
                'visitor_tax_exempt_count': self._to_int(values.get('visitor_tax_exempt_count')),
                'is_organized_group': self._to_bool(values.get('is_organized_group')),
            })
            return {
                'nights': draft.nights,
                'participant_count': draft.participant_count,
                'accommodation': draft.amount_accommodation,
                'meals': draft.amount_meals,
                'cleaning': draft.amount_cleaning,
                'visitor_tax': draft.amount_visitor_tax,
                'untaxed': draft.amount_untaxed,
                'tax': draft.amount_tax,
                'total': draft.amount_total,
                'occupancy_warning': draft.occupancy_warning,
            }
        except Exception as e:  # noqa: BLE001 - eine Vorschau darf das Formular nie blockieren
            _logger.warning('Kostenvorschau für %s fehlgeschlagen: %s', facility.name, e)
            return None

    def _validate_facility_request(self, facility, post):
        """Serverseitige Prüfung der Anfrage; liefert (errors, check_in, check_out).

        Geprüft wird in Stufen — erst Pflichtfelder, dann das Datum, dann die
        Belegungsregeln der Einrichtung und zuletzt die Verfügbarkeit. Dadurch entsteht
        je Formularfeld immer nur eine Meldung, und die Meldungen bleiben eindeutig.
        Die Schlüssel des Fehler-Dicts entsprechen den Feldnamen im Formular, damit das
        Template das betroffene Feld markieren kann."""
        errors = {}
        for fname, label in (('check_in', _('Anreise')), ('check_out', _('Abreise')),
                             ('participant_count', _('Teilnehmerzahl')),
                             ('contact_person', _('Ansprechpartner/in'))):
            if not str(post.get(fname) or '').strip():
                errors[fname] = _('%s ist ein Pflichtfeld.') % label

        check_in = self._to_date(post.get('check_in'))
        check_out = self._to_date(post.get('check_out'))
        if errors:
            return errors, check_in, check_out
        if not check_in or not check_out:
            errors['check_in'] = _('Ungültiges Datum (JJJJ-MM-TT).')
            return errors, check_in, check_out
        if check_out <= check_in:
            errors['check_out'] = _('Die Abreise muss nach der Anreise liegen.')
            return errors, check_in, check_out

        nights = (check_out - check_in).days
        pax = self._to_int(post.get('participant_count'))
        leaders = self._to_int(post.get('leader_count'))
        persons = pax + leaders
        today = date_cls.today()

        # ── Buchungsvorlauf ──────────────────────────────────────────────────
        if check_in < today:
            errors['check_in'] = _('Die Anreise darf nicht in der Vergangenheit liegen.')
        elif facility.max_advance_months:
            # B2: Der Buchungsvorlauf ist im Backend nur ein weicher Hinweis (die
            # Geschäftsstelle muss Ausnahmen erfassen können) — im öffentlichen
            # Formular wird er dagegen hart durchgesetzt. 0 = unbegrenzt.
            latest = today + relativedelta(months=facility.max_advance_months)
            if check_in > latest:
                errors['check_in'] = _(
                    'Laut Vorstandsbeschluss vom 21.07.2026 nehmen wir Anfragen für %(fac)s '
                    'höchstens %(m)d Monate im Voraus an. Die Anreise darf daher spätestens '
                    'am %(d)s liegen. Für spätere Termine wenden Sie sich bitte an die '
                    'Geschäftsstelle.'
                ) % {'fac': facility.name, 'm': facility.max_advance_months,
                     'd': latest.strftime('%d.%m.%Y')}

        # ── Mindestbelegung / Kapazität ──────────────────────────────────────
        if pax <= 0:
            errors['participant_count'] = _('Bitte geben Sie mindestens eine teilnehmende Person an.')
        elif facility.min_persons and persons < facility.min_persons:
            errors['participant_count'] = _(
                '%(fac)s wird erst ab einer Mindestbelegung von %(min)d Personen vergeben. '
                'Ihre Anfrage umfasst %(cur)d Personen (%(pax)d Teilnehmende + %(led)d Betreuende). '
                'Bitte erhöhen Sie die Personenzahl oder wenden Sie sich an die Geschäftsstelle.'
            ) % {'fac': facility.name, 'min': facility.min_persons, 'cur': persons,
                 'pax': pax, 'led': leaders}
        elif facility.capacity and pax > facility.capacity:
            errors['participant_count'] = _(
                'Die Teilnehmerzahl (%(pax)d) übersteigt die Kapazität von %(fac)s '
                '(max. %(cap)d Personen).'
            ) % {'pax': pax, 'fac': facility.name, 'cap': facility.capacity}

        # ── Mindestaufenthalt ────────────────────────────────────────────────
        if facility.min_nights and nights < facility.min_nights:
            errors['check_out'] = _(
                'Für %(fac)s gilt ein Mindestaufenthalt von %(min)s. Ihr Zeitraum umfasst '
                'nur %(cur)s. Bitte wählen Sie einen längeren Zeitraum.'
            ) % {'fac': facility.name, 'min': self._nights_label(facility.min_nights),
                 'cur': self._nights_label(nights)}

        # ── Organisierte Jugend-/Bildungsgruppe ──────────────────────────────
        if facility.requires_organized_group and not self._to_bool(post.get('is_organized_group')):
            errors['is_organized_group'] = _(
                '%s wird nur an organisierte Jugend- und Bildungsgruppen vergeben. Bitte '
                'bestätigen Sie, dass Ihre Gruppe diese Voraussetzung erfüllt — andernfalls '
                'wenden Sie sich bitte direkt an die Geschäftsstelle.'
            ) % facility.name

        # ── Befreiungen vom Fremdenverkehrsbeitrag ───────────────────────────
        # B3: Betreuende sind als Begleitpersonen ohnehin beitragsfrei und gehen gar
        # nicht erst in die Grundmenge ein (siehe _compute_amounts). Das Feld erfasst
        # deshalb nur die WEITEREN Befreiungen unter den Teilnehmenden — die Obergrenze
        # ist die Teilnehmerzahl, nicht die Gesamtpersonenzahl. Sonst würde doppelt
        # abgezogen bzw. eine unplausible Zahl akzeptiert.
        exempt = self._to_int(post.get('visitor_tax_exempt_count'))
        if exempt < 0 or (pax > 0 and exempt > pax):
            errors['visitor_tax_exempt_count'] = _(
                'Es können höchstens %(p)d teilnehmende Personen vom Fremdenverkehrsbeitrag '
                'befreit sein — so viele Teilnehmende umfasst Ihre Anfrage. Betreuende sind '
                'als Begleitpersonen bereits automatisch befreit und hier nicht mitzuzählen.'
            ) % {'p': pax}

        # BUG-a / B1: Verfügbarkeit VOR dem Anlegen prüfen — aber gegen die KAPAZITÄT,
        # nicht gegen die blosse Existenz einer Überschneidung. Ein Haus wie Diepolz
        # (42 Betten) darf nicht durch eine einzige 8-Personen-Anfrage gesperrt werden.
        #
        # Zählweise bewusst identisch zu kjr.facility.booking._check_double_booking:
        # dieselbe Hilfsmethode `_find_overlapping` (ohne Raumauswahl, da das Formular
        # keine Räume anbietet) und dieselbe Summe aus Teilnehmenden + Betreuenden.
        # ENTSCHEIDUNG: Auch noch unbestätigte Anfragen (Status "Anfrage"/"Reserviert")
        # zählen mit — genau wie im Modell, das lediglich stornierte Buchungen ausnimmt.
        # Würden wir sie hier schwächer gewichten, liesse das Formular eine Anfrage zu,
        # die der harte Constraint beim anschliessenden create() sofort mit einem
        # Fehler abweisen würde; der Gast bekäme statt einer Meldung einen Serverfehler.
        # Die Geschäftsstelle kann abgelaufene Vormerkungen jederzeit stornieren und so
        # Plätze wieder freigeben.
        # TODO(KJR): Ohne gepflegte "Max. Personen" (capacity = 0) kann die Auslastung
        # nicht bewertet werden — dann findet wie im Backend keine Prüfung statt. Die
        # Kapazität je Einrichtung ist vom KJR zu bestätigen (Diepolz: 42 Betten).
        if not errors and facility.capacity:
            overlapping = request.env['kjr.facility.booking'].sudo()._find_overlapping(
                facility.id, check_in, check_out)
            occupied = sum(
                (bk.participant_count or 0) + (bk.leader_count or 0) for bk in overlapping
            )
            free = facility.capacity - occupied
            # Ohne Parallelbuchung greift bereits die Kapazitätsprüfung weiter oben —
            # so bleibt es bei genau einer Meldung pro Sachverhalt (wie im Backend,
            # das bei fehlender Überschneidung ebenfalls nicht eingreift).
            if overlapping and persons > free:
                if free > 0:
                    errors['check_in'] = _(
                        'Im gewählten Zeitraum sind in %(fac)s bereits %(occ)d von %(cap)d '
                        'Plätzen belegt. Frei sind noch %(free)d Plätze, Ihre Anfrage umfasst '
                        'aber %(cur)d Personen. Bitte wählen Sie einen anderen Zeitraum oder '
                        'wenden Sie sich an die Geschäftsstelle.'
                    ) % {'fac': facility.name, 'occ': occupied, 'cap': facility.capacity,
                         'free': free, 'cur': persons}
                else:
                    errors['check_in'] = _(
                        'Im gewählten Zeitraum ist %(fac)s mit %(occ)d von %(cap)d Plätzen '
                        'ausgebucht — es sind derzeit keine Plätze frei. Bitte wählen Sie '
                        'einen anderen Zeitraum oder wenden Sie sich an die Geschäftsstelle.'
                    ) % {'fac': facility.name, 'occ': occupied, 'cap': facility.capacity}
        return errors, check_in, check_out

    def _render_facility_request(self, facility, values, errors, preview_requested=False):
        """Formular rendern — inkl. bereits erfasster Eingaben, Tarif-Hinweisen und
        (sofern berechenbar) der Kostenvorschau."""
        tariff = self._website_tariff(facility)
        return request.render('kjr_facility.website_facility_request', {
            'facility': facility,
            'page_name': 'kjr_facilities',
            'errors': errors,
            'values': values,
            'tariff': tariff,
            'preview': self._facility_request_preview(facility, tariff, values),
            'preview_requested': preview_requested,
            # Tarif vorhanden, aber ohne gepflegten Übernachtungssatz: Die Vorschau
            # bleibt aus (siehe _tariff_rate_maintained). Das Template braucht die
            # Unterscheidung, damit es nicht fälschlich fehlende Formulareingaben
            # bemängelt, obwohl die Eingaben vollständig sind.
            'tariff_unpriced': bool(tariff) and not self._tariff_rate_maintained(tariff),
        })

    # ══════════════════════════════════════════════════════════════════════════
    # ANFRAGEFORMULAR — Route
    # ══════════════════════════════════════════════════════════════════════════

    # HINWEIS (offene Produktentscheidung): Die Anfrage setzt bewusst einen Login
    # voraus (auth='user'), damit die Buchung einem Partner zugeordnet und im Portal
    # nachverfolgt werden kann. Ob Anfragen auch ohne Konto möglich sein sollen, ist
    # mit dem KJR noch zu klären — bis dahin NICHT auf auth='public' umstellen.
    @http.route('/service/einrichtung/<int:facility_id>/anfrage', type='http', auth='user',
                website=True, methods=['GET', 'POST'])
    def facility_request(self, facility_id, **post):
        facility = request.env['kjr.facility'].sudo().browse(facility_id)
        if not facility.exists() or not facility.website_published:
            return request.redirect('/service/einrichtungen')

        if request.httprequest.method == 'POST':
            # Eingaben für das erneute Rendern aufheben — niemand soll das Formular
            # nach einer Fehlermeldung noch einmal ausfüllen müssen.
            values = {k: v for k, v in post.items() if k not in ('csrf_token', 'action')}

            if post.get('action') == 'preview':
                # Reine Kostenvorschau: es wird nichts angelegt und es werden bewusst
                # keine Pflichtfeld-/Regelmeldungen erzeugt.
                return self._render_facility_request(facility, values, {}, preview_requested=True)

            errors, check_in, check_out = self._validate_facility_request(facility, post)
            if errors:
                return self._render_facility_request(facility, values, errors)

            partner = request.env.user.partner_id.commercial_partner_id
            # @api.onchange feuert hier nicht — alle Werte explizit setzen.
            # TODO(KJR): tariff_id wird bewusst NICHT vorbelegt; die Tarifgruppe
            # (Mitgliedsverband/Partner/kommerziell) ordnet die Geschäftsstelle im
            # Backend zu. Die Kostenvorschau im Formular rechnet mit dem Standardtarif.
            booking = request.env['kjr.facility.booking'].sudo().create({
                'facility_id': facility.id,
                'partner_id': partner.id,
                'group_name': post.get('group_name', '').strip(),
                'contact_person': post.get('contact_person', '').strip(),
                'contact_email': post.get('contact_email') or request.env.user.email,
                'contact_phone': post.get('contact_phone') or request.env.user.partner_id.phone,
                'check_in': check_in,
                'check_out': check_out,
                'participant_count': self._to_int(post.get('participant_count')),
                'leader_count': self._to_int(post.get('leader_count')),
                'is_organized_group': self._to_bool(post.get('is_organized_group')),
                'visitor_tax_exempt_count': self._to_int(post.get('visitor_tax_exempt_count')),
                # Siehe _meal_option_for: bei Selbstversorgerhäusern wird ein
                # mitgeschickter Wert still verworfen statt abgewiesen.
                'meal_option': self._meal_option_for(facility, post.get('meal_option')),
                'note': post.get('note', '').strip(),
            })
            return request.redirect('/my/einrichtungsbuchungen/%d' % booking.id)

        return self._render_facility_request(facility, {
            'contact_person': request.env.user.partner_id.name or '',
            'contact_email': request.env.user.email or '',
            'contact_phone': request.env.user.partner_id.phone or '',
            'meal_option': 'none',
        }, {})


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
