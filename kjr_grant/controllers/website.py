# -*- coding: utf-8 -*-
"""
Website-Controller für kjr_grant — öffentliche und User-Seiten.

Routen:
  GET      /service/zuschuss                        Öffentliche Landingpage
  GET/POST /service/antrag-stellen                  Antragsformular (Login)
  GET      /service/antrag-bestaetigung             Bestätigungsseite
  GET      /service/zuschuss-hilfe                  Hilfeseite zum Antrag (öffentlich)
  GET      /service/zuschuss/belegliste-vorlage     Kostenaufstellung und Belegliste zum
                                                    Ausdrucken (öffentlich)
  GET      /service/zuschuss/vorlage-kostenaufstellung-belegliste.xlsx
                                                    dieselbe Vorlage als Excel-Datei (öffentlich)
"""
import base64
import io
import logging
import os
import re
from datetime import date as date_cls

from odoo import fields, http, _
from odoo.exceptions import ValidationError
from odoo.http import content_disposition, request

# Formatregeln der Bankverbindung aus dem Modell wiederverwenden, damit die
# Vorprüfung im Formular und der Constraint beim Speichern nicht auseinanderlaufen.
from odoo.addons.kjr_grant.models.kjr_grant_application import BIC_RE, IBAN_LENGTHS
from odoo.addons.kjr_grant.models.res_config_settings_apply import get_apply_form_settings

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
# Feldnamen einer Teilnehmerzeile (tn_<feld>_<nr>). Zeilen werden über ALLE
# übermittelten Nummern gelesen, nicht nur bis zur ersten Lücke: sonst ginge
# eine Zeile hinter einer leer gelassenen Zeile still verloren.
PARTICIPANT_KEY_RE = re.compile(r'^tn_(name|age|gender|zip|city|role|juleica)_(\d+)$')
RECEIPT_KEY_RE = re.compile(r'^rc_(date|no|partner|desc|direction|category|amount)_(\d+)$')
# Schutz gegen manipulierte Formulare mit beliebig vielen Zeilennummern.
MAX_FORM_ROWS = 500
# Alter: ganze Zahl, höchstens drei Stellen (Bereich 0..MAX_PARTICIPANT_AGE).
AGE_RE = re.compile(r'^\d{1,3}$')
RECEIPT_DIRECTIONS = ('income', 'expense')
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

# ── Pflichtfelder des WEBSITE-Formulars (POST-Schlüssel) ─────────────────────
# Diese Namen sind der Vertrag zwischen Controller und Vorlage: jeder Name hier
# MUSS in views/portal_templates.xml (website_kjr_apply) ein required-Attribut
# tragen, und die Vorlage darf darüber hinaus nichts als Pflicht ausweisen.
# tests/test_form_fields.py prüft beide Richtungen; die wenigen bewussten
# Ausnahmen stehen dort in TEMPLATE_ONLY_REQUIRED. Im Backend bleibt alles
# optional, siehe _process_application.
# Hintergrund: Am 10.09.2026 war der Antrag unabsendbar, weil der Controller ein
# Feld verlangte, das im Formular nicht als Pflicht gekennzeichnet war.
#
# WICHTIG: Die drei Listen unten erfassen nur die IMMER geforderten Felder. Die
# bedingt geforderten (Upload je Förderart bzw. je Schalterstellung) stehen in
# CONDITIONAL_REQUIRED_FIELDS weiter unten; sie können hier nicht stehen, weil
# sie nicht bei jedem Antrag Pflicht sind. Wer eine Pflichtprüfung ergänzt, muss
# den Namen in GENAU EINE der vier Listen aufnehmen; tests/test_form_fields.py
# prüft, dass kein Feldname einer Fehlermeldung unbemerkt dazukommt.
REQUIRED_MEASURE_FIELDS = (
    'partner_id', 'grant_type_id', 'measure_name',
    'measure_start', 'measure_start_time', 'measure_end', 'measure_end_time',
    'measure_zip', 'measure_location', 'tn_count', 'tn_leader_count',
    'contact_person', 'contact_email', 'contact_phone',
)
# Bankverbindung: Pflicht im Website-Formular (Entscheidung 18.08.2026), geprüft
# in _check_bank_details. payment_bic wird dort nur auf Format geprüft, nicht
# auf Vorhandensein, und gehört deshalb NICHT in diese Liste.
REQUIRED_BANK_FIELDS = ('payment_iban', 'payment_account_holder')
REQUIRED_CONFIRMATIONS = ('confirm_privacy', 'confirm_guidelines', 'confirm_truthful')
WEBSITE_REQUIRED_FIELDS = (
    REQUIRED_MEASURE_FIELDS + REQUIRED_BANK_FIELDS + REQUIRED_CONFIRMATIONS
)

# ── Bedingt geforderte Felder (Uploads) ─────────────────────────────────────
# Diese Felder prüft der Server nur unter einer Bedingung. Sie gehören deshalb
# NICHT in WEBSITE_REQUIRED_FIELDS: ein Antrag ohne die Bedingung ist auch ohne
# sie vollständig. Das Formular kann sie aus demselben Grund nicht statisch als
# Pflicht kennzeichnen - 'foundation_file' liegt zudem in einem ausgeblendeten
# Block (d-none), und ein ausgeblendetes required-Feld lässt der Browser
# überhaupt nicht mehr absenden ("not focusable"). Beide Felder werden deshalb
# vom Inline-JavaScript der Vorlage auf die Serverregel nachgezogen.
# Der Wert ist die Bedingung in Worten; sie ist der Prüfauftrag für
# tests/test_form_fields.py und die Erklärung für die nächste Änderung.
CONDITIONAL_REQUIRED_FIELDS = {
    'receipt_file': 'Pflicht, wenn die Förderart eine Belegliste verlangt '
                    '(requires_receipt) UND die digitale Belegliste nicht '
                    'benutzt wird. Ohne gewählte Förderart konservativ Pflicht.',
    'foundation_file': 'Pflicht nur bei der Gruppenstarthilfe '
                       '(Förderart-Code %s).' % FOUNDATION_GRANT_CODE,
}

# ── Fachliche Konstanten der Hilfeseite ──────────────────────────────────────
# Einreichfrist: 3 Monate nach Maßnahmenende. Spiegel von
# kjr.grant.application._compute_submission_deadline — dort bei Änderung mitziehen.
SUBMISSION_DEADLINE_MONTHS = 3
# Vorlauf der automatischen Fristerinnerung (_cron_deadline_reminder).
DEADLINE_REMINDER_DAYS = 14
# Leerzeilen der ausdruckbaren Belegliste (passt auf eine A4-Seite quer).
# TODO(KJR): Zeilenzahl und Papierformat mit der Kassenleitung abstimmen.
# Bis dahin bewusst konservativ 20 Zeilen auf einer Seite (bisherige Papierliste).
BLANK_RECEIPT_ROWS = 20
# Leerzeilen der Belegliste in der Excel-Vorlage (am Rechner ausfüllbar, deshalb
# mehr als auf dem Papier; weitere Zeilen lassen sich in Excel einfügen).
XLSX_RECEIPT_ROWS = 60

# Zeilen der Kostenaufstellung (Punkt 6 des Antragsformulars). Eine Quelle für
# die Druckvorlage und die Excel-Vorlage; die Feldnamen sind die POST-Schlüssel
# des Antragsformulars und die Felder von kjr.grant.application.
COST_STATEMENT_INCOME = (
    ('income_tn_fees', '1. Teilnehmerbeiträge'),
    ('income_municipality', '2. Zuschuss Gemeinde'),
    ('income_association', '3. Zuschuss Verband'),
    ('income_bjr', '4. Zuschuss BJR/BezJR'),
    ('income_other', '5. sonstige Zuschüsse'),
)
COST_STATEMENT_COSTS = (
    ('cost_accommodation', '1. Unterkunftskosten, Miete, Verpflegung'),
    ('cost_transport', '2. Fahrtkosten'),
    ('cost_referees', '3. Honorare für Referenten'),
    ('cost_allowances', '4. Aufwandsentschädigung'),
    ('cost_materials', '5. notw. Arbeits- und Hilfsmittel'),
    ('cost_jl_fees', '6. Kursgebühren bei Teilnahme Jugendleiterschulung'),
    ('cost_other', '7. sonstige Ausgaben'),
)


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


def _format_eur(amount):
    """Betrag in deutscher Schreibweise (1.234,50 €), wie Intl.NumberFormat('de-DE')
    im Formular."""
    text = '{:,.2f}'.format(amount or 0.0)
    return text.replace(',', '#').replace('.', ',').replace('#', '.') + '\u00a0€'


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
        if not kjr_members:
            # Kein Mitgliedsverband zugeordnet (z. B. Vereinsregistrierung noch in
            # Prüfung, abgelehnt oder Privatkonto): verständliche Hinweisseite
            # statt eines Formulars mit leerer Verbandsauswahl. Gilt für GET und
            # POST; die serverseitige Whitelist in _process_application bleibt
            # unverändert die eigentliche Sperre.
            company = request.env.company.sudo()
            return request.render('kjr_grant.website_kjr_apply_no_member', {
                'page_name': 'kjr_apply',
                'kjr_affiliation': request.env.user.partner_id._kjr_affiliation_portal_info(),
                'office': {
                    'name': company.name or '',
                    'phone': company.phone or '',
                    'email': company.email or '',
                },
            })
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

    @classmethod
    def _render_apply_form(cls, grant_types, kjr_members, errors, values):
        """Antragsformular rendern. Eine Stelle für alle Rückwege (Erstaufruf und
        jeder Fehlerpfad), damit kein Renderaufruf einen Kontextwert vergisst.

        Teilnehmer- und Belegzeilen werden aus den übermittelten Werten wieder
        aufgebaut, damit nach einer Fehlermeldung auch die per JavaScript
        angehängten Zeilen 2..n erhalten bleiben (vorher war nur Zeile 1 da).
        Die Summen der Kostenaufstellung rechnet der Server für die erste
        Anzeige vor; das Formular aktualisiert sie danach live
        (static/src/interactions/kjr_apply_totals.js)."""
        tn_rows = [row for row in cls._participant_form_rows(values) if not row['empty']]
        rc_rows = [row for row in cls._receipt_form_rows(values) if not row['empty']]
        return request.render('kjr_grant.website_kjr_apply', {
            'grant_types': grant_types, 'kjr_members': kjr_members,
            'page_name': 'kjr_apply', 'errors': errors, 'values': values,
            'tn_rows': cls._renumber(tn_rows) or [cls._empty_participant_row(1)],
            'rc_rows': cls._renumber(rc_rows) or [cls._empty_receipt_row(1)],
            'form_totals': cls._form_totals(values),
            'rc_income_categories': cls._receipt_income_categories(),
            'apply_settings': get_apply_form_settings(request.env),
        })

    # ── Zeilen der Teilnahme- und Belegliste ────────────────────────────────
    @staticmethod
    def _row_indices(post, key_re):
        """Alle Zeilennummern, zu denen das Formular Werte übermittelt hat."""
        indices = set()
        for key in post:
            match = key_re.match(key)
            if match:
                indices.add(int(match.group(2)))
        return sorted(indices)[:MAX_FORM_ROWS]

    @staticmethod
    def _renumber(rows):
        for nr, row in enumerate(rows, start=1):
            row['nr'] = nr
        return rows

    @staticmethod
    def _empty_participant_row(nr):
        return {'nr': nr, 'name': '', 'age': '', 'gender': '', 'zip': '',
                'city': '', 'role': '', 'juleica': False, 'empty': True}

    @classmethod
    def _participant_form_rows(cls, post):
        """Rohwerte der Teilnahmeliste (tn_*_<nr>) in Formularreihenfolge.

        Eine Zeile gilt als leer, wenn weder Name noch Alter, PLZ, Wohnort,
        Geschlecht, Kennziffer oder Juleica angegeben sind; leere Zeilen
        (z. B. versehentlich angehängt) werden übergangen."""
        rows = []
        for idx in cls._row_indices(post, PARTICIPANT_KEY_RE):
            def _v(field, idx=idx):
                return (post.get(f'tn_{field}_{idx}') or '').strip()
            row = {
                'nr': idx, 'name': _v('name'), 'age': _v('age'),
                'gender': _v('gender'), 'zip': _v('zip'), 'city': _v('city'),
                'role': _v('role').upper(), 'juleica': bool(post.get(f'tn_juleica_{idx}')),
            }
            row['empty'] = not any((
                row['name'], row['age'], row['gender'], row['zip'],
                row['city'], row['role'], row['juleica'],
            ))
            rows.append(row)
        return rows

    @staticmethod
    def _valid_age(raw):
        """Alter als int, wenn es eine ganze Zahl von 0 bis MAX_PARTICIPANT_AGE ist,
        sonst None."""
        raw = (raw or '').strip()
        if not AGE_RE.match(raw):
            return None
        age = int(raw)
        return age if age <= MAX_PARTICIPANT_AGE else None

    @classmethod
    def _check_participant_rows(cls, post, errors):
        """Name und Alter sind je teilnehmender Person Pflicht (Kundenentscheidung
        B20, Besprechung 00:11:59: „Alter ... als Pflichtfeld? Auf jeden Fall").

        Geprüft wird jede nicht leere Zeile. Fehlt das Alter oder ist es keine
        ganze Zahl von 0 bis 120, wird der Antrag mit einer Meldung je Zeile
        zurückgegeben, statt das Alter wie bisher still als 0 zu speichern.
        Eine Teilnahmeliste ganz ohne Zeilen bleibt zulässig: sie kann auch als
        Datei hochgeladen werden (Vollständigkeitsprüfung beim Einreichen).
        Die Namen erscheinen nur in der Meldung an den Antragsteller selbst,
        nicht im Log."""
        problems = []
        # Gezählt wird wie im erneut angezeigten Formular: leere Zeilen fallen
        # dort weg (_render_apply_form), die Nummern rücken nach.
        nr = 0
        for row in cls._participant_form_rows(post):
            if row['empty']:
                continue
            nr += 1
            who = _('Zeile %(nr)d (%(name)s)', nr=nr, name=row['name']) \
                if row['name'] else _('Zeile %d', nr)
            if not row['name']:
                problems.append(_('%s: Name fehlt', who))
            if not row['age']:
                problems.append(_('%s: Alter fehlt', who))
            elif cls._valid_age(row['age']) is None:
                problems.append(_(
                    '%(who)s: Alter muss eine ganze Zahl von 0 bis %(max)d sein',
                    who=who, max=MAX_PARTICIPANT_AGE,
                ))
        if problems:
            shown = problems[:10]
            more = len(problems) - len(shown)
            text = '; '.join(shown)
            if more:
                text += _(' und %d weitere Angabe(n)', more)
            errors['participants'] = _(
                'Teilnahmeliste: Bitte geben Sie für jede teilnehmende Person Name '
                'und Alter an (Alter in Jahren, z. B. 14). %s.', text,
            )

    @staticmethod
    def _empty_receipt_row(nr):
        return {'nr': nr, 'date': '', 'no': '', 'partner': '', 'desc': '',
                'direction': 'expense', 'category': '', 'amount': '', 'empty': True}

    @staticmethod
    def _receipt_income_categories():
        """Positionen, die als Einnahme zählen. Bevorzugt aus dem Modell
        (kjr.grant.receipt.INCOME_CATEGORIES), damit Controller, Modell und die
        Live-Prüfung im Formular (data-kjr-income-categories, gelesen von
        kjr_apply_totals.js) nicht auseinanderlaufen; Fallback auf die Konstante
        oben. Läuft auch in der Validierung (außerhalb try/except) — deshalb darf
        der Modellzugriff hier nicht hart fehlschlagen."""
        if 'kjr.grant.receipt' in request.env:
            return tuple(getattr(
                request.env['kjr.grant.receipt'],
                'INCOME_CATEGORIES', RECEIPT_INCOME_CATEGORIES,
            ))
        return RECEIPT_INCOME_CATEGORIES

    @classmethod
    def _receipt_form_rows(cls, post):
        """Rohwerte der digitalen Belegliste (rc_*_<nr>) für das erneute Rendern.
        Die Art allein macht eine Zeile nicht „nicht leer": sie ist im Formular
        immer vorbelegt. Die Art bleibt roh (leer = keine Angabe), damit
        _parse_receipt_rows eine Zeile ohne Art und ohne Position verwirft; die
        Vorlage wählt bei leerer Art ohnehin „Ausgabe" vor."""
        rows = []
        for idx in cls._row_indices(post, RECEIPT_KEY_RE):
            def _v(field, idx=idx):
                return (post.get(f'rc_{field}_{idx}') or '').strip()
            row = {
                'nr': idx, 'date': _v('date'), 'no': _v('no'), 'partner': _v('partner'),
                'desc': _v('desc'), 'direction': _v('direction'),
                'category': _v('category'), 'amount': _v('amount'),
            }
            row['empty'] = not any((
                row['date'], row['no'], row['partner'], row['desc'],
                row['category'], row['amount'],
            ))
            rows.append(row)
        return rows

    @staticmethod
    def _form_totals(values):
        """Summen der Kostenaufstellung für die erste Anzeige im Formular.
        Dieselbe Rechnung wie kjr.grant.application (_compute_income_total,
        _compute_cost_total, _compute_deficit): Fehlbetrag = Kosten minus
        Einnahmen, nicht unter 0."""
        income = sum(max(_parse_amount(values.get(key)), 0.0) for key, _l in COST_STATEMENT_INCOME)
        cost = sum(max(_parse_amount(values.get(key)), 0.0) for key, _l in COST_STATEMENT_COSTS)
        totals = {
            'income': income,
            'cost': cost,
            'deficit': max(cost - income, 0.0),
        }
        for key in ('income', 'cost', 'deficit'):
            totals[f'{key}_label'] = _format_eur(totals[key])
        return totals

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

        # Jeder Name aus REQUIRED_MEASURE_FIELDS braucht hier eine Beschriftung.
        # Fehlt eine, fällt das beim ersten unvollständigen Antrag als KeyError auf.
        labels = {
            'partner_id':         _('Antragsteller (Organisation)'),
            'grant_type_id':      _('Förderart'),
            'measure_name':       _('Maßnahmenbezeichnung'),
            'measure_start':      _('Beginn der Maßnahme'),
            'measure_start_time': _('Uhrzeit Beginn'),
            'measure_end':        _('Ende der Maßnahme'),
            'measure_end_time':   _('Uhrzeit Ende'),
            'measure_zip':        _('PLZ Maßnahmenort'),
            'measure_location':   _('Ort der Maßnahme'),
            'tn_count':           _('Anzahl der Teilnehmer'),
            'tn_leader_count':    _('Anzahl der Gruppenleitung'),
            'contact_person':     _('Ansprechpartner/in'),
            'contact_email':      _('E-Mail'),
            'contact_phone':      _('Telefon'),
        }
        for field in REQUIRED_MEASURE_FIELDS:
            if not _filled(field):
                errors[field] = _('%s ist ein Pflichtfeld.') % labels[field]

        # Formatprüfung der E-Mail zusätzlich zur Pflichtprüfung: an diese Adresse
        # geht die Eingangsbestätigung — eine Adresse mit Tippfehler bleibt sonst
        # unbemerkt, weil der Versand still ins Leere läuft.
        contact_email = (post.get('contact_email') or '').strip()
        if contact_email and not EMAIL_RE.match(contact_email):
            errors['contact_email'] = _(
                'Bitte geben Sie eine gültige E-Mail-Adresse an (z. B. name@verein.de). '
                'An diese Adresse senden wir die Bestätigung zu Ihrem Antrag.'
            )

        # Bestätigungen am Formularende; ohne diese kein Absenden.
        # Geprüft wird über REQUIRED_CONFIRMATIONS, damit die Konstante die
        # einzige Quelle bleibt: eine vierte Bestätigung, die nur hier stünde,
        # wäre vom Test nicht erfasst und der Antragsteller bekäme eine
        # Fehlermeldung zu einem Haken, den der Browser nie als Pflicht gezeigt
        # hat. Jeder Name aus der Konstante braucht hier eine Meldung; fehlt
        # eine, fällt das beim ersten unvollständigen Antrag als KeyError auf.
        confirmation_messages = {
            'confirm_privacy': _(
                'Bitte bestätigen Sie, dass Sie die Datenschutzhinweise gelesen haben '
                'und damit einverstanden sind.'
            ),
            'confirm_guidelines': _(
                'Bitte bestätigen Sie, dass Sie die Zuschussrichtlinien gelesen haben.'
            ),
            'confirm_truthful': _(
                'Bitte bestätigen Sie, dass alle Angaben vollständig sind und der '
                'Wahrheit entsprechen.'
            ),
        }
        for field in REQUIRED_CONFIRMATIONS:
            if not post.get(field):
                errors[field] = confirmation_messages[field]

        # Teilnahmeliste: Name und Alter je Person (B20).
        self._check_participant_rows(post, errors)

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
                    'Empfänger/Einzahler, Bezeichnung, Art und Betrag) oder laden '
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
        # Vorhandensein über REQUIRED_BANK_FIELDS prüfen, damit die Konstante die
        # einzige Quelle bleibt und der Test alle Pflichtfelder abdeckt. Jeder
        # Name aus der Konstante braucht hier eine Meldung; fehlt eine, fällt das
        # beim ersten unvollständigen Antrag als KeyError auf.
        bank_messages = {
            'payment_iban': _(
                'Bitte geben Sie die IBAN des Kontos an, auf das der Zuschuss '
                'überwiesen werden soll. Ohne Bankverbindung kann der Antrag nicht '
                'ausgezahlt werden.'
            ),
            'payment_account_holder': _(
                'Bitte geben Sie den Kontoinhaber genau so an, wie er bei der Bank '
                'hinterlegt ist.'
            ),
        }
        for field in REQUIRED_BANK_FIELDS:
            if not (post.get(field) or '').strip():
                errors[field] = bank_messages[field]
        # Formatprüfungen danach: sie überschreiben die Pflichtmeldung nur, wenn
        # überhaupt etwas eingegeben wurde.
        raw_iban = (post.get('payment_iban') or '').strip()
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
        Leitungs-Checkbox durch die Kennziffer (EA/HA/HO/PR/SO) ersetzt.
        Seit 19.0.17.0.0 sind Name und Alter je Zeile Pflicht; geprüft wird vorher
        in _check_participant_rows. Gelesen werden alle übermittelten Zeilen,
        auch hinter einer Lücke."""
        participant_model = request.env['kjr.grant.participant'].sudo()
        sequence = 0
        for row in self._participant_form_rows(post):
            if row['empty'] or not row['name']:
                continue
            age = self._valid_age(row['age'])
            if age is None:
                # Nach _check_participant_rows nicht erreichbar; defensiv
                # übergehen statt ein falsches Alter zu speichern.
                continue
            # Nur gültige Selection-Keys übernehmen, alles andere verwerfen.
            gender = row['gender'] if row['gender'] in PARTICIPANT_GENDERS else False
            role_code = row['role'] if row['role'] in PARTICIPANT_ROLE_CODES else False
            sequence += 10
            participant_model.create({
                'application_id': application.id,
                'sequence': sequence,
                'name': row['name'],
                'age': age,
                'gender': gender,
                'role_code': role_code,
                'zip_code': row['zip'],
                'city': row['city'],
                # Kennziffer gesetzt ⇒ Mitarbeitende/Leitung. Die Förderlogik
                # (Betreuungsschlüssel, Altersfenster-Ausnahme) hängt an is_leader.
                'is_leader': bool(role_code),
                'has_juleica': row['juleica'],
            })

    def _parse_receipt_rows(self, post):
        """Zeilen der digitalen Belegliste (rc_*_{i}) aus dem POST lesen.
        Rückgabe: Liste von Wertedicts für kjr.grant.receipt (ohne application_id).
        Wird sowohl für die Validierung als auch für das Anlegen genutzt, damit
        Prüfung und Speicherung nicht auseinanderlaufen. Unvollständige oder
        unplausible Zeilen werden verworfen statt den Antrag scheitern zu lassen.

        Seit 19.0.17.0.0 ist die Position optional (Kundenentscheidung B34:
        je Beleg nur Einnahme oder Ausgabe). Ist eine Position gewählt,
        bestimmt sie die Art wie bisher; ohne Position gilt die gewählte Art."""
        income_categories = self._receipt_income_categories()
        rows = []
        sequence = 0
        for row in self._receipt_form_rows(post):
            if row['empty']:
                continue
            idx = row['nr']
            amount = _parse_amount(row['amount'])
            try:
                receipt_date = date_cls.fromisoformat(row['date'])
            except ValueError:
                receipt_date = None
            category = row['category'] if row['category'] in RECEIPT_CATEGORIES else False
            if category:
                # Richtung aus der Position ableiten: die Client-Angabe wird nur
                # zur Plausibilitätsprüfung herangezogen, das Modell erzwingt die
                # Zuordnung ohnehin per Constraint.
                direction = 'income' if category in income_categories else 'expense'
                if row['direction'] not in ('', direction):
                    _logger.info(
                        'Belegzeile %d: Art passt nicht zur Position (%s), aus Position abgeleitet.',
                        idx, category,
                    )
            else:
                direction = row['direction'] if row['direction'] in RECEIPT_DIRECTIONS else False
            if (not row['desc'] or not row['partner'] or not receipt_date
                    or not direction or amount <= 0):
                _logger.info('Belegzeile %d unvollständig oder ungültig, übersprungen.', idx)
                continue
            sequence += 10
            rows.append({
                'sequence': sequence,
                'date': receipt_date,
                'receipt_no': row['no'],
                'partner_name': row['partner'],
                'description': row['desc'],
                'direction': direction,
                'category': category,
                'amount': amount,
            })
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
            # B43: Abschnitt „Zuschussrichtlinien" (Ziel des Links in Checkbox 2).
            'apply_settings': get_apply_form_settings(request.env),
        })

    @http.route(
        '/service/zuschuss/belegliste-vorlage', type='http', auth='public',
        website=True, sitemap=True,
    )
    def kjr_belegliste_vorlage(self, **kw):
        """Leere Kostenaufstellung und Belegliste zum Ausdrucken (ANBest-P).
        Zeilen und Spalten identisch zu Punkt 6 und zur digitalen Belegliste im
        Antragsformular (Block 7), damit Papier- und Digitalweg deckungsgleich
        bleiben. Bewusst eine reine Website-Seite und kein QWeb-Report: ein
        Report bräuchte einen Datensatz, hier soll aber ein Blankoformular ohne
        Antrag druckbar sein. Seit 19.0.17.0.0 mit Kostenaufstellung (B31)."""
        return request.render('kjr_grant.website_kjr_belegliste_vorlage', {
            'page_name': 'kjr_belegliste_vorlage',
            'blank_rows': list(range(1, BLANK_RECEIPT_ROWS + 1)),
            'cost_income_lines': COST_STATEMENT_INCOME,
            'cost_cost_lines': COST_STATEMENT_COSTS,
        })

    @http.route(
        '/service/zuschuss/vorlage-kostenaufstellung-belegliste.xlsx',
        type='http', auth='public', website=True, sitemap=False, methods=['GET'],
    )
    def kjr_vorlage_xlsx(self, **kw):
        """Kostenaufstellung und Belegliste als Excel-Datei zum Ausfüllen am
        Rechner (Kundenwunsch B31, Besprechung 00:19:06: „downloaden ...,
        dass Sie es mir hier uploaden können"). Die ausgefüllte Datei wird im
        Antragsformular unter „8. Dokumente" hochgeladen (.xlsx ist zulässig).
        xlsxwriter ist eine Kernabhängigkeit von Odoo 19 (setup.py,
        requirements.txt), also auf jeder Instanz vorhanden."""
        content = self._build_template_xlsx(request.env)
        return request.make_response(content, headers=[
            ('Content-Type',
             'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition',
             content_disposition('Kostenaufstellung_und_Belegliste.xlsx')),
            ('Content-Length', str(len(content))),
        ])

    @staticmethod
    def _build_template_xlsx(env):
        """Arbeitsmappe mit den Blättern „Kostenaufstellung" und „Belegliste".

        Kostenaufstellung: Zeilen wie Punkt 6, Summen und Fehlbetrag als
        Formel (Fehlbetrag = Gesamtkosten minus Gesamteinnahmen, nicht unter 0,
        wie _compute_deficit), dazu der Abgleich mit den Summen der Belegliste.
        Belegliste: Spalten wie die digitale Belegliste, Art als Auswahlliste,
        Position optional als Auswahlliste (Positionen aus kjr.grant.receipt).
        Firmenname aus res.company, kein Inhalt aus Anträgen."""
        import xlsxwriter  # noqa: PLC0415 - Kernabhängigkeit, nur hier gebraucht

        company = env.company.sudo()
        receipt_model = env['kjr.grant.receipt']
        positions = [
            label for _value, label
            in receipt_model._fields['category']._description_selection(env)
        ]

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        title = workbook.add_format({'bold': True, 'font_size': 14})
        bold = workbook.add_format({'bold': True})
        muted = workbook.add_format({'italic': True, 'font_color': '#555555', 'text_wrap': True})
        head = workbook.add_format({'bold': True, 'bg_color': '#E9ECEF', 'border': 1, 'text_wrap': True})
        cell = workbook.add_format({'border': 1})
        input_cell = workbook.add_format({'border': 1, 'bg_color': '#FFFDE7'})
        money_in = workbook.add_format({'border': 1, 'bg_color': '#FFFDE7', 'num_format': '#,##0.00 €'})
        money = workbook.add_format({'border': 1, 'num_format': '#,##0.00 €'})
        money_bold = workbook.add_format({'border': 1, 'bold': True, 'num_format': '#,##0.00 €'})
        date_in = workbook.add_format({'border': 1, 'bg_color': '#FFFDE7', 'num_format': 'dd.mm.yyyy'})
        label_bold = workbook.add_format({'border': 1, 'bold': True})

        # Zelladressen der Belegliste vorab, die Kostenaufstellung (erstes Blatt)
        # bezieht sich per Formel darauf. Zeilen 0-basiert wie in xlsxwriter.
        first = 6
        last = first + XLSX_RECEIPT_ROWS - 1
        sum_row = last + 2
        amount_range = 'Belegliste!$H$%d:$H$%d' % (first + 1, last + 1)
        kind_range = 'Belegliste!$F$%d:$F$%d' % (first + 1, last + 1)
        receipts_income_cell = 'Belegliste!$H$%d' % (sum_row + 1)
        receipts_expense_cell = 'Belegliste!$H$%d' % (sum_row + 2)

        # ── Blatt 1: Kostenaufstellung ──────────────────────────────────────
        ka = workbook.add_worksheet('Kostenaufstellung')
        ka.set_paper(9)
        ka.fit_to_pages(1, 1)
        ka.set_column('A:A', 52)
        ka.set_column('B:B', 16)
        ka.set_column('C:C', 4)
        ka.write(0, 0, 'Kostenaufstellung zum Zuschussantrag', title)
        ka.write(1, 0, company.name or '', bold)
        ka.write(2, 0, 'Antragsteller (Organisation)')
        ka.write_blank(2, 1, None, input_cell)
        ka.write(3, 0, 'Bezeichnung der Maßnahme')
        ka.write_blank(3, 1, None, input_cell)
        ka.write(4, 0, 'Beginn und Ende der Maßnahme')
        ka.write_blank(4, 1, None, input_cell)

        row = 6
        ka.write_row(row, 0, ['Einnahmen', 'Betrag (€)'], head)
        income_first = row + 1
        for _key, label in COST_STATEMENT_INCOME:
            row += 1
            ka.write(row, 0, label, cell)
            ka.write_blank(row, 1, None, money_in)
        income_total_row = row + 1
        ka.write(income_total_row, 0, 'Gesamteinnahmen', label_bold)
        ka.write_formula(income_total_row, 1, '=SUM(B%d:B%d)' % (income_first + 1, row + 1), money_bold)

        row = income_total_row + 2
        ka.write_row(row, 0, ['Förderfähige Kosten', 'Betrag (€)'], head)
        cost_first = row + 1
        for _key, label in COST_STATEMENT_COSTS:
            row += 1
            ka.write(row, 0, label, cell)
            ka.write_blank(row, 1, None, money_in)
        cost_total_row = row + 1
        ka.write(cost_total_row, 0, 'Förderfähige Gesamtkosten', label_bold)
        ka.write_formula(cost_total_row, 1, '=SUM(B%d:B%d)' % (cost_first + 1, row + 1), money_bold)

        deficit_row = cost_total_row + 2
        ka.write(deficit_row, 0, 'Fehlbetrag (Gesamtkosten minus Gesamteinnahmen)', label_bold)
        ka.write_formula(
            deficit_row, 1,
            '=MAX(B%d-B%d,0)' % (cost_total_row + 1, income_total_row + 1), money_bold,
        )
        ka.write(
            deficit_row + 1, 0,
            'Der Zuschuss ist in der Regel höchstens so hoch wie der Fehlbetrag '
            '(Ausnahmen siehe Zuschussrichtlinien).', muted,
        )

        check_row = deficit_row + 3
        ka.write_row(check_row, 0, ['Abgleich mit der Belegliste', 'Abweichung (€)'], head)
        ka.write(check_row + 1, 0, 'Belege Einnahmen minus Gesamteinnahmen', cell)
        ka.write_formula(check_row + 1, 1, '=%s-B%d' % (receipts_income_cell, income_total_row + 1), money)
        ka.write(check_row + 2, 0, 'Belege Ausgaben minus förderfähige Gesamtkosten', cell)
        ka.write_formula(check_row + 2, 1, '=%s-B%d' % (receipts_expense_cell, cost_total_row + 1), money)
        ka.write(check_row + 3, 0, 'Beide Abweichungen sollten 0,00 € sein.', muted)
        ka.write(check_row + 6, 0, 'Ort, Datum')
        ka.write(check_row + 8, 0, 'Rechtsverbindliche Unterschrift (Organisation)')
        ka.set_row(check_row + 10, 32)
        ka.merge_range(check_row + 10, 0, check_row + 10, 1,
                       'Gelb hinterlegte Felder ausfüllen. Die Datei ausgefüllt im '
                       'Antragsformular unter „8. Dokumente" hochladen.', muted)

        # ── Blatt 2: Belegliste ─────────────────────────────────────────────
        bl = workbook.add_worksheet('Belegliste')
        bl.set_landscape()
        bl.set_paper(9)  # A4
        bl.fit_to_pages(1, 0)
        bl.repeat_rows(5)
        bl.set_column('A:A', 5)
        bl.set_column('B:C', 12)
        bl.set_column('D:E', 30)
        bl.set_column('F:F', 12)
        bl.set_column('G:G', 36)
        bl.set_column('H:H', 14)
        bl.write(0, 0, 'Belegliste zum Zuschussantrag', title)
        bl.write(1, 0, company.name or '', bold)
        bl.write(2, 0, 'Antragsteller (Organisation):')
        bl.write(3, 0, 'Bezeichnung der Maßnahme:')
        bl.merge_range(2, 3, 2, 7, '', input_cell)
        bl.merge_range(3, 3, 3, 7, '', input_cell)
        headers = ['Nr.', 'Datum', 'Beleg-Nr.', 'Empfänger / Einzahler', 'Bezeichnung',
                   'Art (Einnahme/Ausgabe)', 'Position (optional)', 'Betrag (€)']
        bl.write_row(5, 0, headers, head)
        for offset in range(XLSX_RECEIPT_ROWS):
            row = first + offset
            bl.write_number(row, 0, offset + 1, cell)
            bl.write_blank(row, 1, None, date_in)
            for col in (2, 3, 4, 5, 6):
                bl.write_blank(row, col, None, input_cell)
            bl.write_blank(row, 7, None, money_in)
        bl.data_validation(first, 5, last, 5, {
            'validate': 'list', 'source': '=Listen!$A$1:$A$2',
            'input_title': 'Art', 'input_message': 'Einnahme oder Ausgabe wählen.',
        })
        bl.data_validation(first, 6, last, 6, {
            'validate': 'list', 'source': '=Listen!$B$1:$B$%d' % len(positions),
            'input_title': 'Position (optional)',
            'input_message': 'Zeile der Kostenaufstellung, zu der der Beleg gehört.',
        })
        bl.data_validation(first, 7, last, 7, {
            'validate': 'decimal', 'criteria': '>', 'value': 0,
            'error_message': 'Beträge immer positiv erfassen; Einnahme oder Ausgabe steht in der Spalte „Art".',
        })
        bl.write(sum_row, 6, 'Summe Einnahmen', label_bold)
        bl.write_formula(sum_row, 7, '=SUMIF(%s,"Einnahme",%s)' % (kind_range, amount_range), money_bold)
        bl.write(sum_row + 1, 6, 'Summe Ausgaben', label_bold)
        bl.write_formula(sum_row + 1, 7, '=SUMIF(%s,"Ausgabe",%s)' % (kind_range, amount_range), money_bold)
        bl.set_row(sum_row + 3, 32)
        bl.merge_range(sum_row + 3, 0, sum_row + 3, 7,
                       'Diese Belege sind vom Antragsteller zum Zwecke der Nachprüfung '
                       '5 Jahre im Original aufzubewahren. Die Richtigkeit und sachliche '
                       'Notwendigkeit der aufgeführten Einnahmen und Ausgaben wird bestätigt.',
                       muted)
        bl.write(sum_row + 6, 1, 'Ort, Datum')
        bl.write(sum_row + 6, 4, 'Rechtsverbindliche Unterschrift (Organisation)')

        # ── Blatt 3: Auswahllisten (ausgeblendet). Eine Liste direkt in
        # der Datenüberprüfung ist auf 255 Zeichen begrenzt, die Positionen
        # sind länger.
        lists = workbook.add_worksheet('Listen')
        lists.write_column(0, 0, ['Einnahme', 'Ausgabe'])
        lists.write_column(0, 1, positions)
        lists.hide()

        ka.activate()
        workbook.close()
        return output.getvalue()
