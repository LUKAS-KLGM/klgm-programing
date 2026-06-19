# -*- coding: utf-8 -*-
"""
Kernmodell für Zuschussanträge. Enthält vollständige Berechnungslogik
für alle 12 Förderarten (§ 4.1a–§ 4.9) sowie den kompletten Statusworkflow.
"""
import base64
import math
import logging
from datetime import date

from odoo import api, fields, models, _
import markupsafe
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)


class KjrGrantApplication(models.Model):
    _name = 'kjr.grant.application'
    _description = 'KJR Zuschussantrag'
    _order = 'date_submitted desc, name desc'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']

    # ── Identifikation ───────────────────────────────────────────────────────
    name = fields.Char(
        string='Antragsnummer', required=True, copy=False,
        readonly=True, default=lambda self: _('Neu'), tracking=True,
    )
    state = fields.Selection([
        ('draft',     'Entwurf'),
        ('submitted', 'Eingereicht'),
        ('in_review', 'In Prüfung'),
        ('approved',  'Bewilligt'),
        ('rejected',  'Abgelehnt'),
        ('paid',      'Ausgezahlt'),
    ], default='draft', required=True, tracking=True, index=True)
    company_id = fields.Many2one(
        'res.company', string='Gesellschaft', required=True, index=True,
        default=lambda self: self.env.company,
    )

    # ── Antragsteller ────────────────────────────────────────────────────────
    partner_id = fields.Many2one(
        'res.partner', string='Antragsteller (Verband)', required=True, tracking=True,
        domain="[('is_kjr_member', '=', True), ('is_company', '=', True)]",
        ondelete='restrict',
    )
    contact_person = fields.Char(string='Ansprechperson')
    contact_email = fields.Char(string='E-Mail Ansprechperson')
    contact_phone = fields.Char(string='Telefon Ansprechperson')

    # ── Förderart ────────────────────────────────────────────────────────────
    grant_type_id = fields.Many2one(
        'kjr.grant.type', string='Förderart', required=True,
        tracking=True, domain="[('active', '=', True)]", ondelete='restrict',
    )
    grant_type_code = fields.Selection(related='grant_type_id.code', store=True)

    # ── Maßnahme ─────────────────────────────────────────────────────────────
    measure_name = fields.Char(string='Bezeichnung der Maßnahme', required=True, tracking=True)
    measure_start = fields.Date(string='Beginn', required=True, tracking=True)
    measure_start_time = fields.Float(string='Uhrzeit Beginn', help='z. B. 9.5 = 09:30 Uhr')
    measure_end = fields.Date(string='Ende', required=True, tracking=True)
    measure_end_time = fields.Float(string='Uhrzeit Ende', help='z. B. 17.0 = 17:00 Uhr')
    measure_location = fields.Char(string='Ort')
    measure_days = fields.Integer(
        string='Anzahl Tage', compute='_compute_measure_days',
        store=True, readonly=False,
    )
    measure_report = fields.Text(string='Maßnahmenbericht')
    measure_year = fields.Integer(
        string='Maßnahmenjahr', compute='_compute_measure_year', store=True, index=True,
    )
    submission_deadline = fields.Date(
        string='Einreichfrist', compute='_compute_submission_deadline',
        store=True, help='Spätestens 3 Monate nach Maßnahmenende.',
    )

    # ── Teilnehmer ───────────────────────────────────────────────────────────
    tn_count = fields.Integer(string='Anzahl Teilnehmer', default=0, tracking=True)
    tn_leader_count = fields.Integer(string='Jugendleiter', default=0)
    tn_leader_juleica = fields.Integer(string='Davon mit Juleica', default=0)
    tn_external_count = fields.Integer(string='TN aus anderen Regionen', default=0)
    tn_external_pct = fields.Float(
        string='Anteil externer TN (%)', compute='_compute_tn_external_pct', digits=(5, 1),
    )
    participant_consent = fields.Boolean(
        string='Einwilligung Erziehungsberechtigte liegt vor', tracking=True,
        help='Bestätigung, dass für minderjährige Teilnehmer die Einwilligung der '
             'Erziehungsberechtigten zur Verarbeitung der Teilnehmerdaten vorliegt '
             '(Art. 6 Abs. 1 / Art. 8 DSGVO).',
    )

    # ── Delegiertenförderung § 4.9 (Fahrtkosten n. Bayer. Reisekostengesetz) ──
    assembly_id = fields.Many2one(
        'kjr.assembly', string='Vollversammlung', ondelete='set null',
        help='Nur § 4.9: Vollversammlung, zu der der/die Delegierte angereist ist '
             '(Grundlage der Fahrtkostenerstattung).',
    )
    delegate_transport_mode = fields.Selection([
        ('car', 'PKW'),
        ('public', 'Öffentliche Verkehrsmittel'),
        ('other', 'Sonstiges'),
    ], string='Verkehrsmittel', help='Nur § 4.9 Delegiertenförderung.')
    delegate_km_one_way = fields.Float(
        string='Gefahrene km (einfache Strecke)', digits=(8, 1), default=0.0,
        help='Nur § 4.9: einfache Wegstrecke in km. Erstattet wird Hin- und Rückfahrt '
             'nach dem Bayer. Reisekostengesetz (BayRKG).',
    )
    delegate_passenger_count = fields.Integer(
        string='Mitfahrer/innen', default=0,
        help='Nur § 4.9: Zahl der mitgenommenen weiteren Delegierten (Mitnahme-'
             'entschädigung nach BayRKG).',
    )

    # ── Bankverbindung ───────────────────────────────────────────────────────
    payment_account_holder = fields.Char(string='Kontoinhaber (exakt)')
    payment_iban = fields.Char(string='IBAN (Organisationskonto)', tracking=True)
    payment_bic = fields.Char(string='BIC')
    payment_bank = fields.Char(string='Geldinstitut')

    # ── Einnahmen ────────────────────────────────────────────────────────────
    income_tn_fees = fields.Float(string='Teilnehmerbeiträge (€)', digits=(10, 2), default=0.0)
    income_municipality = fields.Float(string='Zuschuss Gemeinde (€)', digits=(10, 2), default=0.0)
    income_association = fields.Float(string='Zuschuss Verband (€)', digits=(10, 2), default=0.0)
    income_bjr = fields.Float(string='Zuschuss BJR/BezJR (€)', digits=(10, 2), default=0.0)
    income_other = fields.Float(string='Sonstige Zuschüsse (€)', digits=(10, 2), default=0.0)
    income_total = fields.Float(
        string='Gesamteinnahmen (€)', compute='_compute_income_total',
        digits=(10, 2), store=True,
    )

    # ── Ausgaben ─────────────────────────────────────────────────────────────
    cost_accommodation = fields.Float(string='Unterkunft/Verpflegung/Miete (€)', digits=(10, 2), default=0.0)
    cost_transport = fields.Float(string='Fahrtkosten (€)', digits=(10, 2), default=0.0)
    cost_referees = fields.Float(string='Honorare Referenten (€)', digits=(10, 2), default=0.0)
    cost_allowances = fields.Float(string='Aufwandsentschädigungen (€)', digits=(10, 2), default=0.0)
    cost_materials = fields.Float(string='Arbeits- und Hilfsmittel (€)', digits=(10, 2), default=0.0)
    cost_jl_fees = fields.Float(
        string='Kursgebühren JL-Schulung (€)', digits=(10, 2), default=0.0,
        help='Nur § 4.4: Kursgebühren bei Teilnahme Jugendleiterschulung.',
    )
    cost_other = fields.Float(string='Sonstige Ausgaben (€)', digits=(10, 2), default=0.0)
    cost_total = fields.Float(
        string='Förderfähige Gesamtkosten (€)', compute='_compute_cost_total',
        digits=(10, 2), store=True,
    )

    # ── Förderberechnung ─────────────────────────────────────────────────────
    deficit = fields.Float(
        string='Fehlbetrag (€)', compute='_compute_deficit', digits=(10, 2), store=True,
    )
    grant_calculated = fields.Float(
        string='Berechneter Zuschuss (€)', compute='_compute_grant',
        digits=(10, 2), store=True,
    )
    grant_approved = fields.Float(
        string='Bewilligter Zuschuss (€)', digits=(10, 2), tracking=True,
        help='Vom KJR bestätigter Betrag. Übernimmt "Berechneter Zuschuss" bei Bewilligung.',
    )
    grant_override_reason = fields.Char(
        string='Begründung Abweichung',
        help='Pflichtfeld wenn bewilligter Betrag vom berechneten abweicht.',
    )
    budget_info = fields.Char(
        string='Budget-Status', compute='_compute_budget_info',
        help='Verbleibendes Jahresbudget der Förderart (Live-Anzeige für die Bewilligung).',
    )

    # ── Bearbeitungsvermerke KJR OA ──────────────────────────────────────────
    date_submitted = fields.Date(string='Eingangsdatum', readonly=True, tracking=True)
    date_approved = fields.Date(string='Zuschuss genehmigt am', readonly=True, tracking=True)
    date_paid = fields.Date(string='Auszahlungsdatum', readonly=True, tracking=True)
    payout_year = fields.Integer(
        string='Auszahlungsjahr', compute='_compute_payout_schedule', store=True,
        help='Haushaltsjahr der Auszahlung. Anträge bis zum Stichtag (KJR-OA: 15.11.) '
             'gelangen im selben Jahr zur Auszahlung, ab 16.11. erst im Folgejahr.',
    )
    payout_schedule_info = fields.Char(
        string='Auszahlungs-Hinweis', compute='_compute_payout_schedule', store=True,
    )
    reference_number = fields.Char(string='KJR-Aktenzeichen', copy=False, tracking=True)
    reviewed_by = fields.Many2one('res.users', string='Bearbeitet von', tracking=True)
    sachlich_richtig = fields.Boolean(
        string='Sachlich richtig', default=False, tracking=True,
        help='Bestätigung der Sachbearbeiterin dass alle Angaben geprüft wurden.',
    )
    payment_ordered = fields.Boolean(
        string='Zur Zahlung angewiesen', default=False, tracking=True,
        help='Zahlungsanweisung erteilt.',
    )
    payment_ordered_by = fields.Many2one(
        'res.users', string='Zahlung angewiesen von', tracking=True,
    )
    payment_ordered_date = fields.Date(string='Zahlung angewiesen am', tracking=True)
    rejection_reason = fields.Text(string='Ablehnungsgrund', tracking=True)
    note_internal = fields.Text(string='Interne Notizen (nicht für Antragsteller)')
    # Buchhaltung
    move_id = fields.Many2one('account.move', string='Buchung Bewilligung', readonly=True, copy=False)
    payment_id = fields.Many2one('account.payment', string='Auszahlung', readonly=True, copy=False)
    attachment_count = fields.Integer(string='Anhänge', compute='_compute_attachment_count')
    participant_ids = fields.One2many('kjr.grant.participant', 'application_id', string='Teilnehmerliste')
    participant_count = fields.Integer(string='TN-Liste Einträge', compute='_compute_participant_count')
    settlement_id = fields.One2many('kjr.grant.settlement', 'application_id', string='Abrechnungen')
    settlement_count = fields.Integer(string='Abrechnungen', compute='_compute_settlement_count')

    # ══════════════════════════════════════════════════════════════════════════
    # COMPUTED FIELDS
    # ══════════════════════════════════════════════════════════════════════════

    @api.depends('measure_start', 'measure_end', 'measure_start_time', 'measure_end_time')
    def _compute_measure_days(self):
        """Förderfähige Maßnahmentage nach KJR-OA-Richtlinie.

        Grundregel: Kalendertage inklusive (Ende − Beginn + 1).
        An-/Abreise-Regel (Ziff. zu § 4.1/4.2/4.3): An- und Abreisetag gelten
        zusammen als EIN Tag, wenn am Anreisetag nach 10:00 Uhr begonnen und am
        Abreisetag vor 17:00 Uhr beendet wird. Greift nur bei mehrtägigen
        Maßnahmen und wenn beide Uhrzeiten erfasst sind; der berechnete Wert ist
        überschreibbar (Einzelfälle)."""
        for rec in self:
            if rec.measure_start and rec.measure_end:
                base = (rec.measure_end - rec.measure_start).days + 1
                if (base >= 2 and rec.measure_start_time and rec.measure_end_time
                        and rec.measure_start_time >= 10.0 and rec.measure_end_time <= 17.0):
                    base -= 1
                rec.measure_days = max(base, 1)
            else:
                rec.measure_days = 1

    @api.depends('measure_start')
    def _compute_measure_year(self):
        for rec in self:
            rec.measure_year = rec.measure_start.year if rec.measure_start else 0

    @api.depends('measure_end')
    def _compute_submission_deadline(self):
        for rec in self:
            if not rec.measure_end:
                rec.submission_deadline = False
                continue
            end = rec.measure_end
            month = end.month + 3
            year = end.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1
            try:
                rec.submission_deadline = date(year, month, end.day)
            except ValueError:
                import calendar
                rec.submission_deadline = date(year, month, calendar.monthrange(year, month)[1])

    @api.depends('date_submitted')
    def _compute_payout_schedule(self):
        """Auszahlungs-Stichtag nach KJR-OA-Richtlinie (knüpft an den Antragseingang):
        Anträge, die bis zum Stichtag (Default 15.11.) eingehen, gelangen im selben
        Jahr (bis 31.12.) zur Auszahlung; ab dem Folgetag eingehende ab dem 1.1. des
        Folgejahres. Stichtag über System-Parameter konfigurierbar (Vertrieb)."""
        params = self.env['ir.config_parameter'].sudo()
        try:
            cutoff_day = int(params.get_param('kjr_grant.payout_cutoff_day', 15))
            cutoff_month = int(params.get_param('kjr_grant.payout_cutoff_month', 11))
        except (ValueError, TypeError):
            cutoff_day, cutoff_month = 15, 11
        for rec in self:
            if not rec.date_submitted:
                rec.payout_year = 0
                rec.payout_schedule_info = ''
                continue
            d = rec.date_submitted
            after_cutoff = (d.month, d.day) > (cutoff_month, cutoff_day)
            rec.payout_year = d.year + 1 if after_cutoff else d.year
            if after_cutoff:
                rec.payout_schedule_info = _(
                    'Eingang nach dem %(day)02d.%(month)02d. – Auszahlung ab 1.1.%(year)d '
                    '(vierteljährlich).'
                ) % {'day': cutoff_day, 'month': cutoff_month, 'year': rec.payout_year}
            else:
                rec.payout_schedule_info = _(
                    'Eingang bis %(day)02d.%(month)02d. – Auszahlung bis 31.12.%(year)d '
                    '(vierteljährlich).'
                ) % {'day': cutoff_day, 'month': cutoff_month, 'year': rec.payout_year}

    @api.depends('tn_count', 'tn_external_count')
    def _compute_tn_external_pct(self):
        for rec in self:
            rec.tn_external_pct = (rec.tn_external_count / rec.tn_count * 100) if rec.tn_count else 0.0

    @api.depends('income_tn_fees', 'income_municipality', 'income_association',
                 'income_bjr', 'income_other')
    def _compute_income_total(self):
        for rec in self:
            rec.income_total = (
                rec.income_tn_fees + rec.income_municipality + rec.income_association
                + rec.income_bjr + rec.income_other
            )

    @api.depends('cost_accommodation', 'cost_transport', 'cost_referees',
                 'cost_allowances', 'cost_materials', 'cost_jl_fees', 'cost_other')
    def _compute_cost_total(self):
        for rec in self:
            rec.cost_total = (
                rec.cost_accommodation + rec.cost_transport + rec.cost_referees
                + rec.cost_allowances + rec.cost_materials + rec.cost_jl_fees
                + rec.cost_other
            )

    @api.depends('cost_total', 'income_total')
    def _compute_deficit(self):
        for rec in self:
            rec.deficit = max(rec.cost_total - rec.income_total, 0.0)

    @api.depends(
        'grant_type_id', 'grant_type_id.code', 'grant_type_id.rate_per_tn_day',
        'grant_type_id.rate_per_tn_single', 'grant_type_id.juleica_bonus',
        'grant_type_id.max_amount', 'grant_type_id.max_cofinancing_pct',
        'grant_type_id.referee_pct', 'grant_type_id.referee_max',
        'grant_type_id.material_pct', 'grant_type_id.material_max',
        'grant_type_id.jl_pct_no_juleica', 'grant_type_id.jl_max_no_juleica',
        'grant_type_id.jl_pct_with_juleica', 'grant_type_id.jl_max_with_juleica',
        'grant_type_id.juleica_uplift_pct', 'grant_type_id.leader_ratio',
        'tn_count', 'tn_leader_count', 'tn_leader_juleica', 'measure_days',
        'cost_total', 'cost_referees', 'cost_materials', 'cost_transport',
        'cost_jl_fees', 'deficit',
        'delegate_transport_mode', 'delegate_km_one_way', 'delegate_passenger_count',
    )
    def _compute_grant(self):
        for rec in self:
            rec.grant_calculated = rec._calculate_grant()

    def _day_rate_grant(self, t, tn, days, leaders, leaders_juleica):
        """Tagessatz-Berechnung (TN × Tage × Satz) inkl. anerkannter Jugendleiter.

        Jugendleiter erhalten ebenfalls den Tagessatz; mit gültiger Juleica erhöht
        er sich um den Juleica-Zuschlag (KJR-OA: +50 %, konfigurierbar). Diese Logik
        gilt einheitlich für alle tagessatz-basierten Förderarten (§ 4.1b/4.2/4.3/4.5)."""
        leaders_no_juleica = leaders - leaders_juleica
        base = tn * days * t.rate_per_tn_day
        if t.juleica_bonus:
            uplift = 1.0 + (t.juleica_uplift_pct or 0.0) / 100.0
            base += leaders_juleica * days * (t.rate_per_tn_day * uplift)
            base += leaders_no_juleica * days * t.rate_per_tn_day
        else:
            base += leaders * days * t.rate_per_tn_day
        return base

    def _calculate_grant(self):
        """
        Zentrale Berechnungslogik für alle 12 Förderarten (§ 4.1a–§ 4.9).

        Globale Deckelungsregeln (lt. Richtlinien KJR OA):
          1. Höchstbetrag der Förderart (max_amount)
          2. Max. Förderquote der förderfähigen Kosten (max_cofinancing_pct, Standard 50%)
             — Ausnahme: §4.7 Pauschale ist davon ausgenommen
          3. Nie mehr als der Fehlbetrag (Kosten − Einnahmen)
          4. Aufrundung auf volle Euro
        """
        self.ensure_one()
        t = self.grant_type_id
        if not t:
            return 0.0

        days = max(self.measure_days or 1, 1)
        tn = max(self.tn_count or 0, 0)
        # Max. 1 anerkannter Jugendleiter je 'leader_ratio' TN (konfigurierbar, KJR-OA: 5)
        ratio = t.leader_ratio if t.leader_ratio and t.leader_ratio > 0 else 5
        max_leaders = math.ceil(tn / ratio) if tn > 0 else 0
        leaders = min(self.tn_leader_count or 0, max_leaders)
        leaders_juleica = min(self.tn_leader_juleica or 0, leaders)

        calculated = 0.0

        # ── §4.1a Freizeitmaßnahme eintägig ──────────────────────────────────
        if t.code == '4_1a':
            calculated = tn * t.rate_per_tn_single

        # ── §4.1b Freizeitmaßnahme mehrtägig ─────────────────────────────────
        elif t.code == '4_1b':
            calculated = self._day_rate_grant(t, tn, days, leaders, leaders_juleica)

        # ── §4.2 Verbandsspezifische Maßnahme ────────────────────────────────
        elif t.code == '4_2':
            calculated = self._day_rate_grant(t, tn, days, leaders, leaders_juleica)

        # ── §4.3 Außerschulische Jugendbildung ────────────────────────────────
        elif t.code == '4_3':
            base = self._day_rate_grant(t, tn, days, leaders, leaders_juleica)
            referee_contrib = 0.0
            if t.referee_pct > 0 and self.cost_referees > 0:
                referee_contrib = min(
                    self.cost_referees * (t.referee_pct / 100.0),
                    t.referee_max,
                )
            material_contrib = 0.0
            if t.material_pct > 0 and self.cost_materials > 0:
                material_contrib = min(
                    self.cost_materials * (t.material_pct / 100.0),
                    t.material_max,
                )
            calculated = base + referee_contrib + material_contrib

        # ── §4.4 Jugendleiterschulung ─────────────────────────────────────────
        elif t.code == '4_4':
            self_costs = self.cost_transport + self.cost_jl_fees
            if leaders_juleica > 0 and t.jl_pct_with_juleica > 0:
                calculated = min(
                    self_costs * (t.jl_pct_with_juleica / 100.0),
                    t.jl_max_with_juleica,
                )
            elif t.jl_pct_no_juleica > 0:
                calculated = min(
                    self_costs * (t.jl_pct_no_juleica / 100.0),
                    t.jl_max_no_juleica,
                )

        # ── §4.5 Internationale Jugendarbeit ──────────────────────────────────
        elif t.code == '4_5':
            calculated = self._day_rate_grant(t, tn, days, leaders, leaders_juleica)

        # ── §4.6 Geräte & Materialien ─────────────────────────────────────────
        elif t.code == '4_6':
            if t.material_pct > 0 and self.cost_materials > 0:
                calculated = min(
                    self.cost_materials * (t.material_pct / 100.0),
                    t.material_max if t.material_max > 0 else t.max_amount,
                )

        # ── §4.7 Gruppenstarthilfe ────────────────────────────────────────────
        elif t.code == '4_7':
            calculated = t.max_amount

        # ── §4.8a Großveranstaltung ───────────────────────────────────────────
        elif t.code == '4_8a':
            calculated = tn * t.rate_per_tn_single

        # ── §4.8b Traditionelle Veranstaltung ────────────────────────────────
        elif t.code == '4_8b':
            calculated = tn * t.rate_per_tn_single

        # ── §4.8c Schwerpunktprojekt ──────────────────────────────────────────
        elif t.code == '4_8c':
            if self.cost_total > 0:
                calculated = min(
                    self.cost_total * (t.max_cofinancing_pct / 100.0),
                    t.max_amount,
                )

        # ── §4.9 Delegiertenförderung (Fahrtkostenerstattung n. Bayer. RKG) ───
        elif t.code == '4_9':
            # Jeder stimmberechtigte Delegierte, der zur Vollversammlung anreist,
            # erhält Fahrtkostenerstattung nach dem Bayer. Reisekostengesetz (BayRKG):
            #   • PKW: Wegstreckenentschädigung je km × Hin- und Rückfahrt
            #          (= 2 × einfache Strecke) + Mitnahmeentschädigung je Mitfahrer/km.
            #   • ÖPNV/Sonstiges: Erstattung der belegten Fahrtkosten.
            # Sätze über System-Parameter pflegbar (BayRKG, halbjährlich/jährlich anpassbar).
            params = self.env['ir.config_parameter'].sudo()
            try:
                rate_km = float(params.get_param('kjr_grant.bayrkg_rate_per_km', 0.35))
                rate_pax = float(params.get_param('kjr_grant.bayrkg_passenger_rate_per_km', 0.03))
            except (ValueError, TypeError):
                rate_km, rate_pax = 0.35, 0.03
            if self.delegate_transport_mode == 'car' and self.delegate_km_one_way > 0:
                round_trip = self.delegate_km_one_way * 2.0
                calculated = round_trip * (rate_km + (self.delegate_passenger_count or 0) * rate_pax)
            elif self.cost_transport > 0:
                calculated = self.cost_transport

        # ── Globale Deckelungsregeln ──────────────────────────────────────────
        # § 4.7 (Pauschale) und § 4.9 (BayRKG-Fahrtkostenerstattung) sind ihrer Natur
        # nach von der 50%-Kofinanzierungs- und der Fehlbetragsdeckelung ausgenommen.
        exempt = ('4_7', '4_9')
        if t.max_amount > 0:
            calculated = min(calculated, t.max_amount)

        if t.code not in exempt and self.cost_total > 0:
            max_by_costs = self.cost_total * (t.max_cofinancing_pct / 100.0)
            calculated = min(calculated, max_by_costs)

        if t.code not in exempt:
            calculated = min(calculated, self.deficit)

        return math.ceil(calculated) if calculated > 0 else 0.0

    @api.depends('grant_type_id', 'measure_year', 'grant_approved', 'state')
    def _compute_budget_info(self):
        Budget = self.env['kjr.grant.budget']
        for rec in self:
            if not rec.grant_type_id or not rec.measure_year:
                rec.budget_info = ''
                continue
            budget = Budget.search([
                ('year', '=', rec.measure_year), ('grant_type_id', '=', rec.grant_type_id.id),
            ], limit=1) or Budget.search([
                ('year', '=', rec.measure_year), ('grant_type_id', '=', False),
            ], limit=1)
            if not budget or not budget.amount_total:
                rec.budget_info = _('Kein Jahresbudget hinterlegt.')
            else:
                rec.budget_info = _(
                    '%(rem).2f € von %(tot).2f € verbleibend (%(used).1f %% ausgeschöpft, %(year)d).'
                ) % {
                    'rem': budget.amount_remaining, 'tot': budget.amount_total,
                    'used': budget.usage_pct, 'year': rec.measure_year,
                }

    def _compute_attachment_count(self):
        data = self.env['ir.attachment']._read_group(
            [('res_model', '=', self._name), ('res_id', 'in', self.ids)],
            groupby=['res_id'], aggregates=['__count'],
        )
        mapped = {res_id: count for res_id, count in data}
        for rec in self:
            rec.attachment_count = mapped.get(rec.id, 0)

    @api.depends('settlement_id')
    def _compute_settlement_count(self):
        for rec in self:
            rec.settlement_count = len(rec.settlement_id)

    @api.depends('participant_ids')
    def _compute_participant_count(self):
        for rec in self:
            rec.participant_count = len(rec.participant_ids)

    # ══════════════════════════════════════════════════════════════════════════
    # CONSTRAINTS
    # ══════════════════════════════════════════════════════════════════════════

    @api.constrains('measure_start', 'measure_end')
    def _check_measure_dates(self):
        for rec in self:
            if rec.measure_start and rec.measure_end and rec.measure_end < rec.measure_start:
                raise ValidationError(_(
                    'Das Ende der Maßnahme (%(end)s) darf nicht vor dem Beginn (%(start)s) liegen.',
                    end=rec.measure_end.strftime('%d.%m.%Y'),
                    start=rec.measure_start.strftime('%d.%m.%Y'),
                ))

    @api.constrains('tn_count', 'tn_leader_count', 'tn_leader_juleica', 'tn_external_count')
    def _check_tn_counts(self):
        for rec in self:
            if min(rec.tn_count, rec.tn_leader_count, rec.tn_leader_juleica, rec.tn_external_count) < 0:
                raise ValidationError(_('Teilnehmerzahlen dürfen nicht negativ sein.'))
            if rec.tn_leader_juleica > rec.tn_leader_count:
                raise ValidationError(_(
                    'Es können nicht mehr Jugendleiter mit Juleica (%(j)d) als '
                    'Jugendleiter insgesamt (%(l)d) angegeben werden.',
                    j=rec.tn_leader_juleica, l=rec.tn_leader_count,
                ))
            if rec.tn_external_count > rec.tn_count:
                raise ValidationError(_(
                    'Die Zahl externer Teilnehmer kann die Gesamtteilnehmerzahl nicht übersteigen.'
                ))

    @api.constrains(
        'income_tn_fees', 'income_municipality', 'income_association', 'income_bjr',
        'income_other', 'cost_accommodation', 'cost_transport', 'cost_referees',
        'cost_allowances', 'cost_materials', 'cost_jl_fees', 'cost_other', 'grant_approved',
    )
    def _check_no_negative_amounts(self):
        money_fields = [
            'income_tn_fees', 'income_municipality', 'income_association', 'income_bjr',
            'income_other', 'cost_accommodation', 'cost_transport', 'cost_referees',
            'cost_allowances', 'cost_materials', 'cost_jl_fees', 'cost_other', 'grant_approved',
        ]
        for rec in self:
            for fname in money_fields:
                if (rec[fname] or 0.0) < 0:
                    raise ValidationError(
                        _('Negativer Betrag im Feld "%s" ist nicht zulässig.')
                        % rec._fields[fname].string
                    )

    # ══════════════════════════════════════════════════════════════════════════
    # PORTAL MIXIN
    # ══════════════════════════════════════════════════════════════════════════

    def _compute_access_url(self):
        super()._compute_access_url()
        for rec in self:
            rec.access_url = f'/my/kjr-antraege/{rec.id}'

    # ══════════════════════════════════════════════════════════════════════════
    # ORM OVERRIDES
    # ══════════════════════════════════════════════════════════════════════════

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Neu')) == _('Neu'):
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('kjr.grant.application')
                    or _('Neu')
                )
        return super().create(vals_list)

    # ══════════════════════════════════════════════════════════════════════════
    # WORKFLOW
    # ══════════════════════════════════════════════════════════════════════════

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Nur Entwürfe können eingereicht werden.'))
            rec._check_completeness()
            rec._check_yearly_limit()
            rec.write({'state': 'submitted', 'date_submitted': fields.Date.today()})
            rec.message_post(
                body=_('Antrag am %s eingereicht.') % fields.Date.today().strftime('%d.%m.%Y'),
                subtype_xmlid='mail.mt_note',
            )
            rec._post_compliance_warnings()
            try:
                template = self.env.ref('kjr_grant.mail_template_grant_submitted')
                template.send_mail(rec.id, force_send=False)
            except Exception:
                pass

    def action_start_review(self):
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Nur eingereichte Anträge können in Prüfung genommen werden.'))
            rec.write({'state': 'in_review', 'reviewed_by': self.env.user.id})

    def action_approve(self):
        if not self.env.user.has_group('kjr_grant.group_kjr_reviewer'):
            raise AccessError(_('Keine Berechtigung zum Bewilligen.'))
        for rec in self:
            if rec.state not in ('submitted', 'in_review'):
                raise UserError(_('Nur eingereichte Anträge können bewilligt werden.'))
            if not rec.grant_type_id.allow_private_account and not rec.payment_iban:
                raise UserError(_('IBAN fehlt. Bitte vor Bewilligung angeben.'))
            if not rec.grant_approved:
                rec.grant_approved = rec.grant_calculated
            if rec.grant_approved != rec.grant_calculated and not rec.grant_override_reason:
                raise UserError(_(
                    'Bitte begründen Sie die Abweichung vom berechneten Zuschuss '
                    '(Feld "Begründung Abweichung").'
                ))
            rec.write({'state': 'approved', 'date_approved': fields.Date.today()})
            rec._create_grant_move()
            rec._warn_budget_exceeded()
            rec._send_approval_notification()
            try:
                template = self.env.ref('kjr_grant.mail_template_grant_approved')
                template.send_mail(rec.id, force_send=False)
            except Exception:
                pass

    def action_reject(self):
        if not self.env.user.has_group('kjr_grant.group_kjr_reviewer'):
            raise AccessError(_('Keine Berechtigung zum Ablehnen.'))
        for rec in self:
            if rec.state not in ('submitted', 'in_review'):
                raise UserError(_('Nur eingereichte Anträge können abgelehnt werden.'))
            if not rec.rejection_reason:
                raise UserError(_('Bitte einen Ablehnungsgrund angeben.'))
            rec.write({'state': 'rejected'})
            rec.message_post(
                body=_('Antrag abgelehnt. Begründung: %s') % markupsafe.escape(rec.rejection_reason or ''),
                subject=_('Antrag %s abgelehnt') % rec.name,
                subtype_xmlid='mail.mt_comment',
                partner_ids=[rec.partner_id.id],
            )
            try:
                template = self.env.ref('kjr_grant.mail_template_grant_rejected')
                template.send_mail(rec.id, force_send=False)
            except Exception:
                pass

    def action_order_payment(self):
        """Bearbeitungsvermerk 'zur Zahlung angewiesen' setzen (KJR-OA-Antragsformular).
        Zwischenschritt zwischen Bewilligung und Auszahlung; steuert das Dashboard
        'Zur Auszahlung'."""
        if not self.env.user.has_group('kjr_grant.group_kjr_reviewer'):
            raise AccessError(_('Keine Berechtigung zur Zahlungsanweisung.'))
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_('Nur bewilligte Anträge können zur Zahlung angewiesen werden.'))
            rec.write({
                'payment_ordered': True,
                'payment_ordered_by': self.env.user.id,
                'payment_ordered_date': fields.Date.today(),
            })
            rec.message_post(
                body=_('Zur Zahlung angewiesen am %s.') % fields.Date.today().strftime('%d.%m.%Y'),
                subtype_xmlid='mail.mt_note',
            )

    def action_mark_paid(self):
        if not self.env.user.has_group('kjr_grant.group_kjr_reviewer'):
            raise AccessError(_('Keine Berechtigung zur Auszahlungsmarkierung.'))
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_('Nur bewilligte Anträge können als ausgezahlt markiert werden.'))
            if not rec.payment_ordered:
                rec.write({
                    'payment_ordered': True,
                    'payment_ordered_by': self.env.user.id,
                    'payment_ordered_date': fields.Date.today(),
                })
            rec.write({'state': 'paid', 'date_paid': fields.Date.today()})
            rec._create_grant_payment()

    def action_reset_draft(self):
        for rec in self:
            if rec.state == 'paid':
                raise UserError(_('Ausgezahlte Anträge können nicht zurückgesetzt werden.'))
            rec.write({'state': 'draft'})

    def action_print_bescheid(self):
        self.ensure_one()
        return self.env.ref('kjr_grant.action_report_kjr_bescheid').report_action(self)

    def action_send_signature(self):
        """PDF generieren, an Antrag anhängen und Sign-Upload öffnen."""
        self.ensure_one()
        report = self.env.ref('kjr_grant.action_report_kjr_bescheid')
        pdf_content, _report_type = report._render_qweb_pdf('kjr_grant.kjr_bescheid_template', res_ids=[self.id])
        filename = f'Antrag_{self.name.replace("/", "-")}.pdf'
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })
        self.message_post(
            body=_('Antrag-PDF für Unterschrift generiert: %s') % filename,
            attachment_ids=[attachment.id],
            subtype_xmlid='mail.mt_note',
        )
        # Sign Template aus Attachment erstellen via Upload-Action
        return {
            'type': 'ir.actions.act_url',
            'url': f'/sign/new-from-attachment/{attachment.id}',
            'target': 'self',
        }

    def action_view_settlements(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Abrechnungen'),
            'res_model': 'kjr.grant.settlement',
            'view_mode': 'list,form',
            'domain': [('application_id', '=', self.id)],
            'context': {'default_application_id': self.id},
        }

    def action_create_settlement(self):
        """Verwendungsnachweis/Abrechnung aus dem Antrag erstellen und mit den
        geplanten Werten vorbefüllen (der KJR-Mitarbeiter trägt dann die Ist-Werte ein)."""
        self.ensure_one()
        if self.state not in ('approved', 'paid'):
            raise UserError(_('Eine Abrechnung kann erst nach der Bewilligung erstellt werden.'))
        settlement = self.env['kjr.grant.settlement'].create({
            'application_id': self.id,
            'actual_tn_count': self.tn_count,
            'actual_cost_accommodation': self.cost_accommodation,
            'actual_cost_transport': self.cost_transport,
            'actual_cost_referees': self.cost_referees,
            'actual_cost_materials': self.cost_materials,
            'actual_cost_other': self.cost_allowances + self.cost_jl_fees + self.cost_other,
            'actual_income_total': self.income_total,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Abrechnung / Verwendungsnachweis'),
            'res_model': 'kjr.grant.settlement',
            'res_id': settlement.id,
            'view_mode': 'form',
        }

    # ══════════════════════════════════════════════════════════════════════════
    # BUCHHALTUNG
    # ══════════════════════════════════════════════════════════════════════════

    def _create_grant_move(self):
        """Buchung bei Bewilligung: Aufwand (Soll) / Verbindlichkeit (Haben).

        Steuer/GoBD-Hinweis (steuerlich final zu prüfen): Zuschuss-Auszahlungen an
        Mitgliedsverbände sind kein steuerbarer Umsatz – es wird daher bewusst KEINE
        Umsatzsteuer (§ 4 Nr. 23 / § 68 Nr. 8 AO sind hier nicht einschlägig) gebucht.
        Die GoBD-konforme Unveränderbarkeit/Festschreibung dieser account.move-Buchungen
        liefert der Odoo-Core (Sperrdatum / l10n_de Secure Ledger) und ist auf Ebene der
        Buchhaltung zu aktivieren – nicht in diesem Modul.
        TODO(Steuer/E-Rechnung): USt-Sätze und E-Rechnung betreffen die geplanten
        Einrichtungs-/Verleih-Module (Leistungsentgelte), nicht die Zuschussverwaltung."""
        self.ensure_one()
        t = self.grant_type_id
        if not t.expense_account_id or not t.liability_account_id or not t.journal_id:
            return
        if self.move_id:
            return
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': t.journal_id.id,
            'date': self.date_approved or fields.Date.today(),
            'ref': f'Zuschuss {self.name} — {self.measure_name}',
            'line_ids': [
                (0, 0, {
                    'name': f'Zuschuss {self.name} ({t.name})',
                    'account_id': t.expense_account_id.id,
                    'partner_id': self.partner_id.id,
                    'debit': self.grant_approved,
                    'credit': 0.0,
                    'analytic_distribution': (
                        {str(t.analytic_account_id.id): 100.0} if t.analytic_account_id else False),
                }),
                (0, 0, {
                    'name': f'Verbindlichkeit {self.name}',
                    'account_id': t.liability_account_id.id,
                    'partner_id': self.partner_id.id,
                    'debit': 0.0,
                    'credit': self.grant_approved,
                }),
            ],
        })
        self.move_id = move.id
        self.message_post(
            body=_('Buchung erstellt: %s (%.2f €)') % (move.name, self.grant_approved),
            subtype_xmlid='mail.mt_note',
        )

    def _warn_budget_exceeded(self):
        """Nicht-blockierender Hinweis, wenn die Bewilligung das Jahresbudget der
        Förderart überschreitet. Zuschüsse werden nur nach Finanzlage gewährt
        (Ermessen, kein Rechtsanspruch) – daher Warnung statt harter Sperre."""
        self.ensure_one()
        year = self.measure_year or fields.Date.today().year
        Budget = self.env['kjr.grant.budget']
        budget = Budget.search([
            ('year', '=', year), ('grant_type_id', '=', self.grant_type_id.id),
        ], limit=1) or Budget.search([
            ('year', '=', year), ('grant_type_id', '=', False),
        ], limit=1)
        if budget and budget.amount_total and budget.amount_remaining < 0:
            self.message_post(
                body=_(
                    'Budget-Hinweis: Mit dieser Bewilligung ist das Jahresbudget %(y)d '
                    'für "%(t)s" um %(over).2f € überschritten (Budget %(tot).2f €, '
                    'bereits bewilligt %(appr).2f €). Bewilligung nur nach Finanzlage.'
                ) % {
                    'y': year, 't': budget.grant_type_id.name or _('Gesamt'),
                    'over': -budget.amount_remaining, 'tot': budget.amount_total,
                    'appr': budget.amount_approved,
                },
                subtype_xmlid='mail.mt_note',
            )

    def _create_grant_payment(self):
        """Zahlung bei Auszahlung erstellen."""
        self.ensure_one()
        t = self.grant_type_id
        if not t.journal_id or self.payment_id:
            return
        # Zahlungsjournal in der Gesellschaft der Buchung/des Antrags suchen (nicht env.company).
        pay_journal = self.env['account.journal'].search([
            ('type', 'in', ('bank', 'cash')),
            ('company_id', '=', (self.move_id.company_id or self.company_id).id),
        ], limit=1)
        if not pay_journal:
            raise UserError(_(
                'Kein Bank-/Kassenjournal für die Gesellschaft "%s" gefunden. '
                'Bitte ein Zahlungsjournal anlegen, bevor die Auszahlung erfolgt.'
            ) % (self.move_id.company_id or self.company_id).display_name)
        payment = self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': self.partner_id.id,
            'amount': self.grant_approved,
            'journal_id': pay_journal.id,
            'date': self.date_paid or fields.Date.today(),
            'ref': f'Zuschuss {self.name} — {self.measure_name}',
        })
        self.payment_id = payment.id
        self.message_post(
            body=_('Zahlung erstellt: %s (%.2f €)') % (payment.name, self.grant_approved),
            subtype_xmlid='mail.mt_note',
        )

    def action_view_move(self):
        self.ensure_one()
        if not self.move_id:
            return
        return {
            'type': 'ir.actions.act_window',
            'name': _('Buchung'),
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
        }

    def action_view_payment(self):
        self.ensure_one()
        if not self.payment_id:
            return
        return {
            'type': 'ir.actions.act_window',
            'name': _('Zahlung'),
            'res_model': 'account.payment',
            'res_id': self.payment_id.id,
            'view_mode': 'form',
        }

    # ══════════════════════════════════════════════════════════════════════════
    # CRON
    # ══════════════════════════════════════════════════════════════════════════

    @api.model
    def _cron_deadline_reminder(self):
        """Erinnerung an ablaufende Einreichfristen (14 Tage vorher)."""
        today = fields.Date.today()
        from datetime import timedelta
        warn_date = today + timedelta(days=14)
        drafts = self.search([
            ('state', '=', 'draft'),
            ('submission_deadline', '<=', warn_date),
            ('submission_deadline', '>=', today),
        ])
        for app in drafts:
            if app.activity_ids:  # Dedup: keine täglich neue Erinnerung
                continue
            app.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=app.submission_deadline,
                summary=_('Einreichfrist läuft ab: %s') % app.name,
                note=_('Die Einreichfrist für "%s" endet am %s. '
                       'Bitte den Antrag zeitnah einreichen.') % (
                    app.measure_name,
                    app.submission_deadline.strftime('%d.%m.%Y'),
                ),
            )
        _logger.info('Fristen-Erinnerung: %d Anträge benachrichtigt', len(drafts))

    # ══════════════════════════════════════════════════════════════════════════
    # DUPLIKAT-PRÜFUNG
    # ══════════════════════════════════════════════════════════════════════════

    @api.onchange('partner_id', 'grant_type_id', 'measure_name', 'measure_start')
    def _onchange_check_duplicate(self):
        if not (self.partner_id and self.grant_type_id and self.measure_start):
            return
        domain = [
            ('partner_id', '=', self.partner_id.id),
            ('grant_type_id', '=', self.grant_type_id.id),
            ('measure_start', '=', self.measure_start),
            ('state', 'not in', ['rejected']),
        ]
        if self._origin.id:
            domain.append(('id', '!=', self._origin.id))
        existing = self.search(domain, limit=1)
        if existing:
            return {
                'warning': {
                    'title': _('Mögliches Duplikat'),
                    'message': _('Es existiert bereits ein Antrag von "%s" für '
                                '"%s" am %s (Antrag %s, Status: %s).') % (
                        self.partner_id.name,
                        self.grant_type_id.name,
                        self.measure_start.strftime('%d.%m.%Y'),
                        existing.name,
                        dict(existing._fields['state'].selection).get(existing.state),
                    ),
                },
            }

    # ══════════════════════════════════════════════════════════════════════════
    # HILFSMETHODEN
    # ══════════════════════════════════════════════════════════════════════════

    def _check_completeness(self):
        self.ensure_one()
        t = self.grant_type_id
        errors = []
        if not self.partner_id:
            errors.append(_('Antragsteller fehlt.'))
        if self.partner_id and not self.partner_id.kjr_vr_right:
            errors.append(_('Der Verband "%s" hat kein Vertretungsrecht in der '
                           'Vollversammlung (§ 3.1 Richtlinien). Nur Verbände '
                           'mit VR sind antragsberechtigt.') % self.partner_id.name)
        if not self.measure_name:
            errors.append(_('Bezeichnung der Maßnahme fehlt.'))
        if not self.measure_start or not self.measure_end:
            errors.append(_('Beginn und Ende der Maßnahme fehlen.'))
        if self.measure_start and self.measure_end and self.measure_end < self.measure_start:
            errors.append(_('Ende liegt vor Beginn.'))
        # Förderarten ohne Maßnahmen-Teilnehmer: § 4.6 (Geräte), § 4.7 (Starthilfe),
        # § 4.9 (Delegiertenfahrtkosten).
        no_tn_codes = ('4_6', '4_7', '4_9')
        if t.code not in no_tn_codes and self.tn_count <= 0:
            errors.append(_('Anzahl Teilnehmer muss > 0 sein.'))
        if self.participant_ids and not self.participant_consent:
            errors.append(_('Bitte bestätigen Sie, dass die Einwilligung der '
                           'Erziehungsberechtigten zur Verarbeitung der '
                           'Teilnehmerdaten vorliegt (Datenschutz).'))
        if t.min_participants and self.tn_count < t.min_participants:
            errors.append(_('Mindestens %d Teilnehmer erforderlich für "%s".')
                         % (t.min_participants, t.name))
        # § 4.9 braucht eine Vollversammlung (Grundlage der Erstattung lt. Antragsliste)
        # und entweder gefahrene km (PKW) oder belegte Fahrtkosten.
        if t.code == '4_9':
            if not self.assembly_id:
                errors.append(_('Bitte die Vollversammlung angeben, zu der die Delegierten '
                               'angereist sind (Grundlage der Fahrtkostenerstattung § 4.9).'))
            if self.delegate_km_one_way <= 0 and self.cost_transport <= 0:
                errors.append(_('Bitte die gefahrenen Kilometer (einfache Strecke) oder die '
                               'belegten Fahrtkosten der Delegierten angeben.'))
        if self.cost_total <= 0 and t.code not in ('4_7', '4_9'):
            errors.append(_('Bitte Kosten angeben.'))
        if not t.allow_private_account and not self.payment_iban:
            errors.append(_('IBAN fehlt. Auszahlung nur auf Organisationskonto.'))

        # Teilnehmerliste: digital oder als Datei
        if t.requires_tn_list and not self.participant_ids:
            attachments = self.env['ir.attachment'].search([
                ('res_model', '=', self._name), ('res_id', '=', self.id),
            ])
            names = [a.name.lower() for a in attachments]
            if not any(kw in n for n in names for kw in ['teilnehmer', 'tn-liste', 'tn_liste']):
                errors.append(_('Teilnehmerliste fehlt. Bitte digital ausfüllen oder als Datei hochladen.'))

        attachments = self.env['ir.attachment'].search([
            ('res_model', '=', self._name), ('res_id', '=', self.id),
        ])
        names = [a.name.lower() for a in attachments]

        if t.requires_report:
            if not self.measure_report and not any(kw in n for n in names for kw in ['bericht', 'report', 'protokoll']):
                errors.append(_('Maßnahmenbericht fehlt (Textfeld oder Datei mit "bericht" im Namen).'))
        if t.requires_receipt:
            if not any(kw in n for n in names for kw in ['beleg', 'rechnung', 'quittung']):
                errors.append(_('Belegliste fehlt (Datei mit "beleg" oder "rechnung" im Namen).'))

        if errors:
            raise UserError(
                _('Antrag unvollständig:\n\n') + '\n'.join(f'• {e}' for e in errors)
            )

    def _check_yearly_limit(self):
        self.ensure_one()
        t = self.grant_type_id
        if not t.max_per_year:
            return
        year = self.measure_start.year if self.measure_start else date.today().year
        # Förderarten mit gemeinsamer Jahreslimit-Gruppe zählen zusammen
        # (KJR-OA: § 4.1 eintägig und mehrtägig = max. 4 Freizeitmaßnahmen/Jahr gemeinsam).
        if t.year_limit_group:
            type_ids = self.env['kjr.grant.type'].search([
                ('year_limit_group', '=', t.year_limit_group),
            ]).ids
            group_label = _('Förderart-Gruppe "%s"') % t.year_limit_group
        else:
            type_ids = [t.id]
            group_label = _('"%s"') % t.name
        count = self.search_count([
            ('partner_id', '=', self.partner_id.id),
            ('grant_type_id', 'in', type_ids),
            ('state', 'not in', ['draft', 'rejected']),
            ('measure_year', '=', year),
            ('id', '!=', self.id),
        ])
        if count >= t.max_per_year:
            raise UserError(_(
                'Das Jahreslimit von %(limit)d Anträgen für %(group)s in %(year)d '
                'ist für "%(partner)s" bereits erreicht.',
                limit=t.max_per_year, group=group_label,
                year=year, partner=self.partner_id.name,
            ))

    def _post_compliance_warnings(self):
        """Nicht-blockierende Hinweise zur Förderfähigkeit (BJR/KJR-OA-Richtlinien).
        Bewusst als Hinweis (kein Fehler), da der KJR im Einzelfall Ausnahmen zulassen kann.
        Schwellenwerte stammen aus der konfigurierbaren Förderart (kjr.grant.type)."""
        self.ensure_one()
        t = self.grant_type_id
        warnings = []
        # Herkunft: TN sollen überwiegend aus dem Landkreis kommen.
        if t.max_external_pct and self.tn_external_pct > t.max_external_pct:
            warnings.append(_(
                'Hoher Anteil auswärtiger Teilnehmer (%(pct).0f %%, zulässig max. %(max).0f %%). '
                'Die Teilnehmer sollen überwiegend aus dem Landkreis Oberallgäu stammen.'
            ) % {'pct': self.tn_external_pct, 'max': t.max_external_pct})
        # Betreuungsschlüssel.
        ratio = t.leader_ratio if t.leader_ratio and t.leader_ratio > 0 else 5
        required_leaders = math.ceil(self.tn_count / ratio) if self.tn_count else 0
        if self.tn_count and self.tn_leader_count < required_leaders:
            warnings.append(_(
                'Betreuungsschlüssel: bei %(tn)d Teilnehmern werden mind. %(req)d Jugendleiter '
                'empfohlen (1 je %(ratio)d TN), angegeben sind %(have)d.'
            ) % {'tn': self.tn_count, 'req': required_leaders, 'ratio': ratio, 'have': self.tn_leader_count})
        # Juleica.
        if self.tn_leader_count and self.tn_leader_juleica < self.tn_leader_count:
            warnings.append(_(
                'Nicht alle Jugendleiter haben eine Juleica (%(j)d von %(l)d). Für den '
                'Juleica-Zuschlag ist eine gültige Juleica erforderlich.'
            ) % {'j': self.tn_leader_juleica, 'l': self.tn_leader_count})
        # Dauer.
        if t.min_days and self.measure_days and self.measure_days < t.min_days:
            warnings.append(_('Die Maßnahme ist kürzer als die Mindestdauer von %d Tagen.') % t.min_days)
        if t.max_days and self.measure_days and self.measure_days > t.max_days:
            warnings.append(_('Die Maßnahme überschreitet die Höchstdauer von %d Tagen.') % t.max_days)
        # Alter (nur wenn Grenzen gesetzt und Geburtsdaten vorhanden).
        # Jugendleiter sind von der Teilnehmer-Altersgrenze ausgenommen (KJR-OA: für
        # Jugendleiter besteht keine Altersgrenze) und werden hier nicht gezählt.
        if (t.min_age or t.max_age) and self.participant_ids:
            out = 0
            for p in self.participant_ids:
                if not p.birthdate or p.is_leader:
                    continue
                if t.min_age and p.age < t.min_age:
                    out += 1
                elif t.max_age and p.age > t.max_age:
                    out += 1
            if out:
                warnings.append(_(
                    '%(n)d Teilnehmer (ohne Jugendleiter) liegen außerhalb des förderfähigen '
                    'Altersbereichs (%(min)s–%(max)s Jahre).'
                ) % {'n': out, 'min': t.min_age or '–', 'max': t.max_age or '–'})
        # Subsidiarität: anderweitige Zuschussmöglichkeiten sind auszuschöpfen und
        # anzugeben; eine angemessene Eigenleistung wird vorausgesetzt (KJR-OA Grundsätze).
        other_income = (self.income_municipality + self.income_association
                        + self.income_bjr + self.income_other)
        if t.code not in ('4_4', '4_7', '4_9') and self.cost_total >= 200 and other_income <= 0:
            warnings.append(_(
                'Subsidiarität: Es sind keine anderweitigen Zuschüsse (Gemeinde/Verband/BJR/'
                'sonstige) angegeben. Andere Fördermöglichkeiten sind vorrangig auszuschöpfen '
                'und im Antrag anzugeben.'
            ))
        # § 4.9: Delegierter-Verband sollte zur gewählten Vollversammlung gehören.
        if t.code == '4_9' and self.assembly_id and self.partner_id:
            a = self.assembly_id
            if self.partner_id not in (a.invited_member_ids | a.attendee_ids):
                warnings.append(_(
                    'Der Verband "%s" ist für die gewählte Vollversammlung weder als '
                    'eingeladen noch als anwesend erfasst – bitte die Delegierten-'
                    'berechtigung prüfen.'
                ) % self.partner_id.name)
        # Hinweis auf nicht förderfähige Kosten (KJR-OA Ziff. 2 / 3.3).
        if t.code not in ('4_7', '4_9') and self.cost_total > 0:
            warnings.append(_(
                'Bitte beachten: Nicht förderfähig sind u. a. Alkohol und Tabakwaren, '
                'Personalkosten für Hauptamtliche, berufsqualifizierende Aus-/Fortbildungen, '
                'touristische Unternehmen sowie reine Unterhaltungs-/Schulveranstaltungen.'
            ))
        if warnings:
            items = markupsafe.Markup('').join(
                markupsafe.Markup('<li>%s</li>') % w for w in warnings
            )
            self.message_post(
                body=markupsafe.Markup('<p><strong>%s</strong></p><ul>%s</ul>') % (
                    _('Hinweise zur Förderfähigkeit:'), items,
                ),
                subtype_xmlid='mail.mt_note',
            )

    def _send_approval_notification(self):
        self.ensure_one()
        try:
            report = self.env.ref('kjr_grant.action_report_kjr_bescheid')
            pdf_content, _report_type = report._render_qweb_pdf('kjr_grant.kjr_bescheid_template', res_ids=[self.id])
            filename = f'Bescheid_{self.name.replace("/", "-")}.pdf'
            attachment = self.env['ir.attachment'].create({
                'name': filename,
                'type': 'binary',
                'datas': base64.b64encode(pdf_content),
                'res_model': self._name,
                'res_id': self.id,
                'mimetype': 'application/pdf',
            })
            self.message_post(
                body=_(
                    'Antrag <b>%(name)s</b> wurde bewilligt.<br/>'
                    'Bewilligter Betrag: <b>%(amount).2f €</b>',
                    name=self.name, amount=self.grant_approved,
                ),
                subject=_('Zuschussbescheid %s') % self.name,
                attachment_ids=[attachment.id],
                subtype_xmlid='mail.mt_comment',
                partner_ids=[self.partner_id.id],
            )
        except Exception as e:
            _logger.warning('Bescheid für %s konnte nicht generiert werden: %s', self.name, e)
            self.message_post(
                body=_('Antrag bewilligt. Bescheid bitte manuell generieren.'),
                subtype_xmlid='mail.mt_note',
            )
