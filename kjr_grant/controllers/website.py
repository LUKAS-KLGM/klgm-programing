# -*- coding: utf-8 -*-
"""
Website-Controller für kjr_grant — öffentliche und User-Seiten.

Routen:
  GET      /service/zuschuss                        Öffentliche Landingpage
  GET/POST /service/antrag-stellen                  Antragsformular (Login)
  GET      /service/antrag-bestaetigung             Bestätigungsseite
  GET      /service/zuschuss-hilfe                  Hilfeseite zum Antrag (öffentlich)
  GET      /service/zuschuss/belegliste-vorlage     Belegliste zum Ausdrucken (öffentlich)
"""
import base64
import logging
import os
import re
from datetime import date as date_cls

from odoo import fields, http, _
from odoo.exceptions import ValidationError
from odoo.http import request

# Formatregeln der Bankverbindung aus dem Modell wiederverwenden, damit die
# Vorprüfung im Formular und der Constraint beim Speichern nicht auseinanderlaufen.
from odoo.addons.kjr_grant.models.kjr_grant_application import BIC_RE, IBAN_LENGTHS

_logger = logging.getLogger(__name__)
ALLOWED_EXTENSIONS = {'.pdf', '.xlsx', '.xls', '.csv', '.docx', '.doc', '.jpg', '.jpeg', '.png'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
# Menschenlesbare Fassung von ALLOWED_EXTENSIONS für Fehlermeldungen. Muss zu den
# accept-Attributen der Datei-Felder in views/portal_templates.xml passen —
# sonst findet der Antragsteller seine Datei im Dateidialog nicht wieder.
UPLOAD_FORMATS_LABEL = 'PDF, Word, Excel/CSV oder Bild (JPG/PNG), max. 10 MB'

# ── Formular-Konstanten ──────────────────────────────────────────────────────
# Gültige Selection-Keys der Teilnahmeliste (Spiegel von kjr.grant.participant).
PARTICIPANT_GENDERS = ('male', 'female', 'diverse')
PARTICIPANT_ROLE_CODES = ('EA', 'HA', 'HO', 'PR', 'SO')
# Plausibilitätsgrenze für das manuell erfasste Alter — seit 07/2026 wird im
# Formular das Alter statt des Geburtsdatums erfasst.
MAX_PARTICIPANT_AGE = 120
# Förderart, bei der das Neugründungsformular Pflicht ist (§ 4.7 Gruppenstarthilfe).
FOUNDATION_GRANT_CODE = '4_7'
# Positionen der digitalen Belegliste (Spiegel von kjr.grant.receipt). Fachliche
# Quelle der Einnahme-Zuordnung ist dort die Klassenkonstante INCOME_CATEGORIES;
# sie wird zur Laufzeit bevorzugt gelesen, diese Liste dient nur als Fallback.
RECEIPT_INCOME_CATEGORIES = ('tn_fees', 'municipality', 'association', 'bjr', 'income_other')
RECEIPT_EXPENSE_CATEGORIES = (
    'accommodation', 'transport', 'referees', 'allowances',
    'materials', 'jl_fees', 'cost_other',
)
RECEIPT_CATEGORIES = RECEIPT_INCOME_CATEGORIES + RECEIPT_EXPENSE_CATEGORIES

# Bewusst einfache, robuste E-Mail-Prüfung — kein RFC-5322-Vollparser und keine
# Fremdbibliothek. Verlangt genau ein @ ohne Leerzeichen, danach eine Domain mit
# mindestens einem Punkt und einer Endung ab zwei Zeichen. Fängt die typischen
# Tippfehler ab (fehlendes @, "foo@bar", Leerzeichen), ohne gültige Adressen
# fälschlich abzulehnen (auch Umlaut-Domains bleiben zulässig).
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s.]{2,}$')

# ── Fachliche Konstanten der Hilfeseite ──────────────────────────────────────
# Einreichfrist: 3 Monate nach Maßnahmenende. Spiegel von
# kjr.grant.application._compute_submission_deadline — dort bei Änderung mitziehen.
SUBMISSION_DEADLINE_MONTHS = 3
# Vorlauf der automatischen Fristerinnerung (_cron_deadline_reminder).
DEADLINE_REMINDER_DAYS = 14
# Leerzeilen der ausdruckbaren Belegliste (passt auf eine A4-Seite quer).
# TODO: Zeilenzahl und Papierformat mit Bora abstimmen — bis dahin bewusst
# konservativ 20 Zeilen auf einer Seite (bisherige Papierliste des KJR).
BLANK_RECEIPT_ROWS = 20


def _valid_grant_type_domain(date_ref=None):
    """Domain der zum Stichtag gültigen Förderarten.

    Aktiv UND der datierte Gültigkeitszeitraum enthält den Stichtag; leere
    Grenzen zählen als unbegrenzt. Spiegelt den Suchfilter „Aktuell gültig"
    aus views/kjr_grant_type_views.xml. Ohne diesen Filter erscheint dieselbe
    Förderart mehrfach, sobald mehrere datierte Fassungen desselben Paragrafen
    gepflegt sind. Bewusst eine gemeinsame Funktion für Antragsformular und
    Hilfeseite, damit beide Seiten dieselbe Auswahl zeigen.
    """
    today = date_ref or fields.Date.context_today(request.env.user)
    return [
        ('active', '=', True),
        '|', ('valid_from', '=', False), ('valid_from', '<=', today),
        '|', ('valid_to', '=', False), ('valid_to', '>=', today),
    ]


def _parse_int(value, default=0):
    """Defensives Parsen von Formularwerten — Client-Daten nie ungeprüft übernehmen."""
    try:
        return int((str(value) if value is not None else '').strip() or default)
    except (ValueError, TypeError):
        return default


def _parse_amount(value, default=0.0):
    """Betrag aus dem Formular; akzeptiert auch die deutsche Komma-Schreibweise (12,50)."""
    try:
        raw = (str(value) if value is not None else '').strip().replace(',', '.')
        return float(raw or default)
    except (ValueError, TypeError):
        return default


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
        grant_types = request.env['kjr.grant.type'].sudo().search(_valid_grant_type_domain())
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

        return self._render_apply_form(grant_types, kjr_members, {}, values)

    @staticmethod
    def _render_apply_form(grant_types, kjr_members, errors, values):
        """Antragsformular rendern. Eine Stelle für alle Rückwege (Erstaufruf und
        jeder Fehlerpfad), damit kein Renderaufruf einen Kontextwert vergisst."""
        return request.render('kjr_grant.website_kjr_apply', {
            'grant_types': grant_types, 'kjr_members': kjr_members,
            'page_name': 'kjr_apply', 'errors': errors, 'values': values,
        })

    def _process_application(self, post, kjr_members, grant_types):
        errors = {}
        values = dict(post)

        def _i(key, default=0):
            try:
                return int(post.get(key) or default)
            except (ValueError, TypeError):
                return default

        # Pflichtfelder gelten NUR im Website-Formular — im Backend muss die Geschäfts-
        # stelle weiterhin unvollständige Papieranträge erfassen können.
        # ACHTUNG bei Zahlenfeldern: "0" ist ein gültiger, aber falsy Wert. Deshalb wird
        # auf den leeren String geprüft und nicht auf Truthiness.
        def _filled(key):
            return bool((post.get(key) or '').strip())

        for field, label in [
            ('partner_id',         _('Antragsteller (Organisation)')),
            ('grant_type_id',      _('Förderart')),
            ('measure_name',       _('Maßnahmenbezeichnung')),
            ('measure_start',      _('Beginn der Maßnahme')),
            ('measure_start_time', _('Uhrzeit Beginn')),
            ('measure_end',        _('Ende der Maßnahme')),
            ('measure_end_time',   _('Uhrzeit Ende')),
            ('measure_zip',        _('PLZ Maßnahmenort')),
            ('measure_location',   _('Ort der Maßnahme')),
            ('tn_count',           _('Anzahl der Teilnehmer')),
            ('tn_leader_count',    _('Anzahl der Gruppenleitung')),
            ('contact_person',     _('Ansprechpartner/in')),
            ('contact_email',      _('E-Mail')),
            ('contact_phone',      _('Telefon')),
        ]:
            if not _filled(field):
                errors[field] = _('%s ist ein Pflichtfeld.') % label

        # Formatprüfung der E-Mail zusätzlich zur Pflichtprüfung: an diese Adresse
        # geht die Eingangsbestätigung — eine Adresse mit Tippfehler bleibt sonst
        # unbemerkt, weil der Versand still ins Leere läuft.
        contact_email = (post.get('contact_email') or '').strip()
        if contact_email and not EMAIL_RE.match(contact_email):
            errors['contact_email'] = _(
                'Bitte geben Sie eine gültige E-Mail-Adresse an (z. B. name@verein.de). '
                'An diese Adresse senden wir die Bestätigung zu Ihrem Antrag.'
            )

        # Bestätigungen am Formularende — ohne diese kein Absenden.
        for field, message in [
            ('confirm_privacy', _(
                'Bitte bestätigen Sie, dass Sie die Datenschutzhinweise gelesen haben '
                'und damit einverstanden sind.'
            )),
            ('confirm_guidelines', _(
                'Bitte bestätigen Sie, dass Sie die Zuschussrichtlinien gelesen haben.'
            )),
            ('confirm_truthful', _(
                'Bitte bestätigen Sie, dass alle Angaben vollständig sind und der '
                'Wahrheit entsprechen.'
            )),
        ]:
            if not post.get(field):
                errors[field] = message

        valid_member_ids = kjr_members.ids
        partner_id = _i('partner_id')
        if partner_id not in valid_member_ids and not errors.get('partner_id'):
            errors['partner_id'] = _('Bitte einen gültigen KJR-Mitgliedsverband auswählen.')

        valid_type_ids = grant_types.ids
        grant_type_id = _i('grant_type_id')
        if grant_type_id not in valid_type_ids and not errors.get('grant_type_id'):
            errors['grant_type_id'] = _('Ungültige Förderart.')

        selected_type = grant_types.filtered(lambda t: t.id == grant_type_id)[:1]

        # Belegliste: entweder digital im Formular erfasst ODER als Datei hochgeladen.
        # Die Entweder-oder-Regel wird serverseitig erzwungen, nicht nur per JS —
        # aber nur bei Förderarten, die überhaupt eine Belegliste verlangen
        # (§ 4.4 Jugendleiterschulung: requires_receipt = False). Ohne gültig
        # gewählte Förderart konservativ Pflicht annehmen; in dem Fall steht die
        # Fehlermeldung zur Förderart ohnehin schon im Formular.
        use_digital_receipts = bool(post.get('use_digital_receipts'))
        receipt_required = selected_type.requires_receipt if selected_type else True
        if use_digital_receipts:
            if receipt_required and not self._parse_receipt_rows(post):
                errors['receipt_ids'] = _(
                    'Bitte erfassen Sie mindestens einen vollständigen Beleg (Datum, '
                    'Empfänger/Einzahler, Bezeichnung, Position und Betrag) oder laden '
                    'Sie stattdessen eine Belegliste als Datei hoch.'
                )
        elif receipt_required and not self._has_upload('receipt_file'):
            errors['receipt_file'] = _(
                'Bitte laden Sie die Belegliste als Datei hoch (%s) oder erfassen Sie '
                'die Belege digital im Formular.'
            ) % UPLOAD_FORMATS_LABEL

        # Neugründungsformular ist ausschließlich bei der Gruppenstarthilfe (§ 4.7) Pflicht.
        if selected_type.code == FOUNDATION_GRANT_CODE and not self._has_upload('foundation_file'):
            errors['foundation_file'] = _(
                'Bei der Gruppenstarthilfe ist das Neugründungsformular Pflicht. Bitte '
                'laden Sie es hoch (%s).'
            ) % UPLOAD_FORMATS_LABEL

        # Bankverbindung schon im Formular prüfen. Ohne diese Vorprüfung schlägt erst
        # der Constraint beim Speichern zu; dessen ValidationError landete im
        # allgemeinen Fehlerpfad und der Antragsteller erfuhr nie, dass die IBAN
        # das Problem ist. Geprüft wird mit denselben Hilfsfunktionen wie im Modell.
        self._check_bank_details(post, errors)

        if errors:
            return self._render_apply_form(grant_types, kjr_members, errors, values)

        try:
            measure_start = date_cls.fromisoformat(post['measure_start'])
            measure_end = date_cls.fromisoformat(post['measure_end'])
        except (ValueError, KeyError):
            errors['measure_start'] = _('Ungültiges Datumsformat (JJJJ-MM-TT erwartet).')
            return self._render_apply_form(grant_types, kjr_members, errors, values)

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
                'measure_zip':             post.get('measure_zip', '').strip(),
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
                'confirm_privacy':         bool(post.get('confirm_privacy')),
                'confirm_guidelines':      bool(post.get('confirm_guidelines')),
                'confirm_truthful':        bool(post.get('confirm_truthful')),
                'use_digital_receipts':    use_digital_receipts,
                'delegate_transport_mode': post.get('delegate_transport_mode') or False,
                'delegate_km_one_way':     _f('delegate_km_one_way'),
                'delegate_passenger_count': _i('delegate_passenger_count'),
            }
            application = request.env['kjr.grant.application'].sudo().create(app_vals)
            self._handle_participants(application, post)
            if use_digital_receipts:
                self._handle_receipts(application, post)
            self._handle_file_uploads(application)
        except ValidationError as e:
            # Fachliche Prüfung des Modells (z. B. Bankverbindung, Beträge). Der
            # Rollback ist zwingend: sonst bliebe der bereits eingefügte Antrag mit
            # verbrauchter Sequenznummer halbfertig in der Datenbank stehen, weil
            # der Request ohne Exception endet und deshalb committet wird.
            # Nach dem Rollback wird bewusst nicht mehr auf `application`
            # zugegriffen; grant_types/kjr_members stammen aus dem Bestand und
            # sind beim erneuten Rendern wieder lesbar.
            request.env.cr.rollback()
            _logger.info('KJR-Antrag abgelehnt (Validierung): %s', e)
            errors['general'] = str(e) or _(
                'Die Angaben konnten nicht gespeichert werden. Bitte prüfen Sie das Formular.'
            )
            return self._render_apply_form(grant_types, kjr_members, errors, values)
        except Exception as e:
            # Siehe oben: ohne Rollback bleibt ein halb angelegter Antrag zurück.
            request.env.cr.rollback()
            _logger.error('Fehler beim Erstellen des KJR-Antrags: %s', e, exc_info=True)
            errors['general'] = _(
                'Beim Erstellen des Antrags ist ein Fehler aufgetreten. '
                'Bitte versuchen Sie es erneut oder kontaktieren Sie die KJR-Geschäftsstelle.'
            )
            return self._render_apply_form(grant_types, kjr_members, errors, values)

        return request.redirect(f'/service/antrag-bestaetigung?app_id={application.id}')

    @staticmethod
    def _check_bank_details(post, errors):
        """IBAN und BIC feldgenau prüfen, bevor der Antrag angelegt wird.

        Verwendet die Hilfsfunktionen und Formatmuster des Modells
        (_normalize_bank_code / _iban_is_valid, IBAN_LENGTHS, BIC_RE), damit
        Formular und Constraint dieselbe Regel anwenden.

        Konto ist im Website-Formular PFLICHT (Entscheidung 18.08.2026): ohne
        Bankverbindung lässt sich der Zuschuss nicht auszahlen, und die
        Geschäftsstelle müsste sie hinterhertelefonieren. Das gilt bewusst für
        ALLE Förderarten — allow_private_account entscheidet nur, ob es ein
        Organisations- oder ein Privatkonto sein darf, nicht ob überhaupt eines
        nötig ist. Im Backend bleibt das Feld optional (Projektstandard:
        Papieranträge müssen unvollständig erfassbar sein).
        """
        app_model = request.env['kjr.grant.application']
        raw_iban = (post.get('payment_iban') or '').strip()
        if not raw_iban:
            errors['payment_iban'] = _(
                'Bitte geben Sie die IBAN des Kontos an, auf das der Zuschuss '
                'überwiesen werden soll. Ohne Bankverbindung kann der Antrag nicht '
                'ausgezahlt werden.'
            )
        if not (post.get('payment_account_holder') or '').strip():
            errors['payment_account_holder'] = _(
                'Bitte geben Sie den Kontoinhaber genau so an, wie er bei der Bank '
                'hinterlegt ist.'
            )
        if raw_iban:
            iban = app_model._normalize_bank_code(raw_iban)
            expected_len = IBAN_LENGTHS.get(iban[:2])
            if expected_len and len(iban) != expected_len:
                errors['payment_iban'] = _(
                    'Die IBAN "%(iban)s" ist keine gültige %(country)s-IBAN: erwartet '
                    'werden %(exp)d Stellen, angegeben sind %(act)d.',
                    iban=raw_iban, country=iban[:2],
                    exp=expected_len, act=len(iban),
                )
            elif not app_model._iban_is_valid(iban):
                errors['payment_iban'] = _(
                    'Die IBAN "%(iban)s" ist ungültig. Erwartet wird das Format '
                    'Länderkürzel + 2 Prüfziffern + Kontokennung '
                    '(z. B. DE12 3456 7890 1234 5678 90); die Prüfziffer muss zur '
                    'IBAN passen. Bitte die Angabe mit dem Kontoauszug abgleichen.',
                    iban=raw_iban,
                )
        raw_bic = (post.get('payment_bic') or '').strip()
        if raw_bic and not BIC_RE.match(app_model._normalize_bank_code(raw_bic)):
            errors['payment_bic'] = _(
                'Der BIC "%(bic)s" ist ungültig. Erwartet werden 8 oder 11 Stellen: '
                '4 Buchstaben Bankcode + 2 Buchstaben Ländercode + 2 Zeichen '
                'Ortscode + optional 3 Zeichen Filialcode (z. B. BYLADEM1ALG).',
                bic=raw_bic,
            )

    def _handle_participants(self, application, post):
        """Teilnahmeliste aus dem Formular übernehmen.
        Seit 07/2026 wird das Alter direkt erfasst (kein Geburtsdatum mehr) und die
        Leitungs-Checkbox durch die Kennziffer (EA/HA/HO/PR/SO) ersetzt."""
        participant_model = request.env['kjr.grant.participant'].sudo()
        idx = 1
        while post.get(f'tn_name_{idx}'):
            name = post.get(f'tn_name_{idx}', '').strip()
            if not name:
                idx += 1
                continue
            # Nur gültige Selection-Keys übernehmen, alles andere verwerfen.
            gender = (post.get(f'tn_gender_{idx}') or '').strip()
            if gender not in PARTICIPANT_GENDERS:
                gender = False
            role_code = (post.get(f'tn_role_{idx}') or '').strip().upper()
            if role_code not in PARTICIPANT_ROLE_CODES:
                role_code = False
            age = _parse_int(post.get(f'tn_age_{idx}'))
            if age < 0 or age > MAX_PARTICIPANT_AGE:
                age = 0
            vals = {
                'application_id': application.id,
                'sequence': idx * 10,
                'name': name,
                'age': age,
                'gender': gender,
                'role_code': role_code,
                'zip_code': post.get(f'tn_zip_{idx}', '').strip(),
                'city': post.get(f'tn_city_{idx}', '').strip(),
                # Kennziffer gesetzt ⇒ Mitarbeitende/Leitung. Die Förderlogik
                # (Betreuungsschlüssel, Altersfenster-Ausnahme) hängt an is_leader.
                'is_leader': bool(role_code),
                'has_juleica': bool(post.get(f'tn_juleica_{idx}')),
            }
            participant_model.create(vals)
            idx += 1

    def _parse_receipt_rows(self, post):
        """Zeilen der digitalen Belegliste (rc_*_{i}) aus dem POST lesen.
        Rückgabe: Liste von Wertedicts für kjr.grant.receipt (ohne application_id).
        Wird sowohl für die Validierung als auch für das Anlegen genutzt, damit
        Prüfung und Speicherung nicht auseinanderlaufen. Unvollständige oder
        unplausible Zeilen werden verworfen statt den Antrag scheitern zu lassen."""
        # Einnahme-Zuordnung bevorzugt aus dem Modell lesen, damit Controller und
        # Modell nicht auseinanderlaufen; Fallback auf die Konstante oben. Die
        # Methode läuft auch in der Validierung (außerhalb try/except) — deshalb
        # darf der Modellzugriff hier nicht hart fehlschlagen.
        income_categories = RECEIPT_INCOME_CATEGORIES
        if 'kjr.grant.receipt' in request.env:
            income_categories = tuple(getattr(
                request.env['kjr.grant.receipt'],
                'INCOME_CATEGORIES', RECEIPT_INCOME_CATEGORIES,
            ))
        rows = []
        idx = 1
        while post.get(f'rc_desc_{idx}'):
            description = (post.get(f'rc_desc_{idx}') or '').strip()
            partner_name = (post.get(f'rc_partner_{idx}') or '').strip()
            category = (post.get(f'rc_category_{idx}') or '').strip()
            amount = _parse_amount(post.get(f'rc_amount_{idx}'))
            raw_date = (post.get(f'rc_date_{idx}') or '').strip()
            try:
                receipt_date = date_cls.fromisoformat(raw_date)
            except ValueError:
                receipt_date = None
            if (not description or not partner_name or not receipt_date
                    or category not in RECEIPT_CATEGORIES or amount <= 0):
                _logger.info('Belegzeile %d unvollständig oder ungültig — übersprungen.', idx)
                idx += 1
                continue
            # Richtung immer aus der Position ableiten: die Client-Angabe wird nur
            # zur Plausibilitätsprüfung herangezogen, das Modell erzwingt die
            # Zuordnung ohnehin per Constraint.
            direction = 'income' if category in income_categories else 'expense'
            if (post.get(f'rc_direction_{idx}') or '').strip() not in ('', direction):
                _logger.info(
                    'Belegzeile %d: Art passt nicht zur Position (%s) — aus Position abgeleitet.',
                    idx, category,
                )
            rows.append({
                'sequence': idx * 10,
                'date': receipt_date,
                'receipt_no': (post.get(f'rc_no_{idx}') or '').strip(),
                'partner_name': partner_name,
                'description': description,
                'direction': direction,
                'category': category,
                'amount': amount,
            })
            idx += 1
        return rows

    def _handle_receipts(self, application, post):
        """Digitale Belegliste anlegen. Nur aufrufen, wenn use_digital_receipts gesetzt ist."""
        receipt_model = request.env['kjr.grant.receipt'].sudo()
        for vals in self._parse_receipt_rows(post):
            vals['application_id'] = application.id
            receipt_model.create(vals)

    @staticmethod
    def _is_acceptable_upload(file_obj):
        """Endung und Größe einer hochgeladenen Datei prüfen. Bewusst dieselbe Regel für
        die Pflichtprüfung und das Speichern — sonst würde eine abgelehnte Datei die
        Pflichtprüfung bestehen und danach stillschweigend verworfen."""
        if not file_obj or not file_obj.filename:
            return False
        _, ext = os.path.splitext(os.path.basename(file_obj.filename))
        if ext.lower() not in ALLOWED_EXTENSIONS:
            return False
        file_obj.seek(0, 2)
        size = file_obj.tell()
        file_obj.seek(0)
        return 0 < size <= MAX_FILE_SIZE

    def _has_upload(self, field_name):
        """Prüft, ob im Multipart-Request eine verwertbare Datei unter diesem Feld liegt."""
        return any(
            self._is_acceptable_upload(file_obj)
            for file_obj in request.httprequest.files.getlist(field_name)
        )

    def _handle_file_uploads(self, application):
        FIELD_LABELS = {
            'tn_list_file': 'Teilnahmeliste',
            'report_file': 'Maßnahmenbericht',
            'receipt_file': 'Belegliste',
            'foundation_file': 'Neugründungsformular',
            'other_file_1': 'Weitere Unterlagen',
            'other_file_2': 'Weitere Unterlagen',
        }
        attachment_ids = []
        for field_name in FIELD_LABELS:
            for file_obj in request.httprequest.files.getlist(field_name):
                if not self._is_acceptable_upload(file_obj):
                    continue
                filename = os.path.basename(file_obj.filename)
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

    # ══════════════════════════════════════════════════════════════════════════
    # HILFE- UND VORLAGENSEITEN
    # ══════════════════════════════════════════════════════════════════════════

    @http.route('/service/zuschuss-hilfe', type='http', auth='public', website=True, sitemap=True)
    def kjr_apply_help(self, **kw):
        """Öffentliche Hilfeseite „Wie stelle ich einen Zuschussantrag?".
        Bewusst ohne Login erreichbar — Verbände sollen sich vor der Registrierung
        informieren können. Förderarten und Pflichtunterlagen werden aus den
        gepflegten Stammdaten gelesen, damit die Seite nicht veraltet, sobald die
        Geschäftsstelle im Backend Sätze oder Pflichtdokumente ändert.
        Gezeigt werden nur die heute gültigen Fassungen — dieselbe Auswahl wie im
        Antragsformular (siehe _valid_grant_type_domain)."""
        grant_types = request.env['kjr.grant.type'].sudo().search(_valid_grant_type_domain())
        # Auszahlungs-Stichtag aus den Systemparametern (Default 15.11.) — dieselbe
        # Quelle wie kjr.grant.application._compute_payout_schedule.
        params = request.env['ir.config_parameter'].sudo()
        try:
            cutoff_day = int(params.get_param('kjr_grant.payout_cutoff_day', 15))
            cutoff_month = int(params.get_param('kjr_grant.payout_cutoff_month', 11))
        except (ValueError, TypeError):
            cutoff_day, cutoff_month = 15, 11
        return request.render('kjr_grant.website_kjr_apply_help', {
            'grant_types': grant_types,
            'page_name': 'kjr_apply_help',
            'deadline_months': SUBMISSION_DEADLINE_MONTHS,
            'reminder_days': DEADLINE_REMINDER_DAYS,
            'payout_cutoff_day': cutoff_day,
            'payout_cutoff_month': cutoff_month,
        })

    @http.route(
        '/service/zuschuss/belegliste-vorlage', type='http', auth='public',
        website=True, sitemap=True,
    )
    def kjr_belegliste_vorlage(self, **kw):
        """Leere Belegliste zum Ausdrucken (ANBest-P). Spalten identisch zur
        digitalen Belegliste im Antragsformular (Block 7), damit Papier- und
        Digitalweg deckungsgleich bleiben. Bewusst eine reine Website-Seite und
        kein QWeb-Report: ein Report bräuchte einen Datensatz, hier soll aber ein
        Blankoformular ohne Antrag druckbar sein."""
        return request.render('kjr_grant.website_kjr_belegliste_vorlage', {
            'page_name': 'kjr_belegliste_vorlage',
            'blank_rows': list(range(1, BLANK_RECEIPT_ROWS + 1)),
        })
