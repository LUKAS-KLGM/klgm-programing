# -*- coding: utf-8 -*-
"""
Kernmodell für Zuschussanträge. Enthält vollständige Berechnungslogik
für alle 12 Förderarten (§ 4.1a–§ 4.9) sowie den kompletten Statusworkflow.
"""
import base64
import contextvars
import math
import logging
import re
from datetime import date

from odoo import api, fields, models, _
import markupsafe
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)

# ── Bankverbindung: Formatmuster ─────────────────────────────────────────────
# IBAN nach ISO 13616: 2 Buchstaben Land, 2 Prüfziffern, danach 11–30 alphanum.
# Zeichen (max. 34 Stellen gesamt). Die Prüfziffer wird zusätzlich per Mod-97
# geprüft (siehe _iban_is_valid) – bewusst selbst implementiert, weil das Modul
# 'base_iban' NICHT in den depends steht.
IBAN_RE = re.compile(r'^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$')
# Landesspezifische Sollängen der in der Geschäftsstelle real vorkommenden Länder.
# Andere Länder werden nur über Grundmuster + Mod-97 geprüft.
IBAN_LENGTHS = {'DE': 22, 'AT': 20, 'CH': 21, 'LI': 21, 'LU': 20}
# BIC/SWIFT nach ISO 9362: 4 Bank + 2 Land + 2 Ort (+ optional 3 Filiale).
BIC_RE = re.compile(r'^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$')

# ── Vier-Augen-Prinzip: prozessinterne Freigabe ──────────────────────────────
# Die Bearbeitungsvermerke (Status, Prüfung, Zahlungsanweisung) dürfen nur aus
# den Workflow-Actions dieses Moduls heraus geschrieben werden. Die Freigabe darf
# deshalb NICHT über den Odoo-Kontext laufen:
#
#   odoo/service/model.py, call_kw():
#       context = kwargs.pop('context', None) or {}
#       recs = recs.with_context(context)
#
# Der Kontext wird bei /web/dataset/call_kw also ungefiltert vom Client
# übernommen. Ein angemeldeter Sachbearbeiter könnte per RPC (Browser-Konsole)
# jeden beliebigen Kontextschlüssel mitschicken und damit eine kontextbasierte
# Freigabe vortäuschen – der komplette Schutz wäre wertlos.
#
# Auch 'readonly=True' in der Felddefinition hilft NICHT: 'readonly' ist in
# Odoo 19 ausschließlich eine UI-Eigenschaft.
#   • odoo/orm/fields.py: 'def is_editable(self): return not self.readonly'
#     – einziger Aufrufer ist odoo/addons/base/models/ir_ui_view.py (View-Prüfung).
#   • odoo/orm/models.py, write(): prüft 'self.check_access("write")' und je Feld
#     'self._check_field_access(field, "write")'.
#   • odoo/orm/models.py, _has_field_access(): wertet ausschließlich
#     'field.groups' (und env.su) aus – 'readonly' kommt darin nicht vor.
# Ein readonly-Feld ist über /web/dataset/call_kw folglich weiterhin schreibbar.
# 'groups=' wäre serverseitig zwar wirksam, hilft hier aber nicht: die Person,
# gegen die geschützt wird, ist selbst Sachbearbeiterin (group_kjr_reviewer).
#
# Deshalb: ein prozessinterner Schalter, der ausschließlich von Servercode in
# dieser Datei gesetzt werden kann. contextvars ist dafür das richtige Werkzeug
# (auch der Odoo-Core nutzt es, z. B. odoo/addons/base/models/ir_cron.py) – der
# Wert gilt pro Thread/Task, ein Request kann den Wert eines anderen Requests
# also weder sehen noch setzen. Über RPC ist er grundsätzlich nicht erreichbar.
_WORKFLOW_WRITE_ALLOWED = contextvars.ContextVar(
    'kjr_grant_workflow_write_allowed', default=False,
)


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
    ], string='Status', default='draft', required=True, copy=False,
        tracking=True, index=True)
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
    # Fassung der Förderart, die zum Maßnahmenbeginn gültig war (valid_from/valid_to).
    # BEWUSSTE ENTSCHEIDUNG: 'grant_type_id' bleibt das führende Feld und wird NICHT
    # automatisch umgehängt. Ein automatischer Wechsel würde bestehende Anträge
    # nachträglich auf eine andere Berechnungsgrundlage stellen – bereits erteilte
    # Bescheide wären dann nicht mehr nachvollziehbar. Stattdessen nur Anzeige +
    # Hinweis, die Geschäftsstelle entscheidet im Einzelfall.
    applicable_type_id = fields.Many2one(
        'kjr.grant.type', string='Gültige Fassung (Maßnahmenbeginn)',
        compute='_compute_applicable_type', store=False,
        help='Die zum Beginn der Maßnahme gültige Fassung der Förderart. '
             'Weicht sie von der gewählten Förderart ab, ist zu prüfen, welcher '
             'Regelstand für die Berechnung anzuwenden ist.',
    )
    applicable_type_warning = fields.Char(
        string='Hinweis Regelstand', compute='_compute_applicable_type', store=False,
    )

    # ── Maßnahme ─────────────────────────────────────────────────────────────
    measure_name = fields.Char(string='Bezeichnung der Maßnahme', required=True, tracking=True)
    measure_start = fields.Date(string='Beginn', required=True, tracking=True)
    measure_start_time = fields.Float(string='Uhrzeit Beginn', help='z. B. 9.5 = 09:30 Uhr')
    measure_end = fields.Date(string='Ende', required=True, tracking=True)
    measure_end_time = fields.Float(string='Uhrzeit Ende', help='z. B. 17.0 = 17:00 Uhr')
    # PLZ getrennt vom Ort erfasst (Auswertung Maßnahmenorte in der Geschäftsstelle).
    measure_zip = fields.Char(string='PLZ Maßnahmenort')
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
    tn_leader_count = fields.Integer(string='Gruppenleitung', default=0)
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

    # ── Bestätigungen Antragsteller ──────────────────────────────────────────
    # Pflicht ausschließlich im Website-Formular (Template + Controller). Im Backend
    # bewusst NICHT required, damit die Geschäftsstelle Papieranträge abtippen kann.
    confirm_privacy = fields.Boolean(
        string='Datenschutzhinweise gelesen und einverstanden', tracking=True,
    )
    confirm_guidelines = fields.Boolean(
        string='Zuschussrichtlinien gelesen', tracking=True,
    )
    confirm_truthful = fields.Boolean(
        string='Angaben vollständig und wahrheitsgemäß', tracking=True,
        help='Antragsteller versichert Vollständigkeit/Richtigkeit und bestätigt, dass zu viel '
             'erhaltene Beträge unaufgefordert mitzuteilen und zurückzuzahlen sind.',
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

    # ── Belegliste ───────────────────────────────────────────────────────────
    # Entweder-oder: digitale Erfassung im Formular ODER Datei-Upload der Belegliste.
    use_digital_receipts = fields.Boolean(
        string='Belegliste digital erfasst',
        help='Wenn aktiv, wurde die Belegliste im Formular digital erfasst; '
             'der Datei-Upload entfällt.',
    )
    receipt_ids = fields.One2many(
        'kjr.grant.receipt', 'application_id', string='Belegliste',
    )
    receipt_count = fields.Integer(
        string='Anzahl Belege', compute='_compute_receipt_totals',
    )
    receipt_income_total = fields.Float(
        string='Belege Einnahmen (€)', compute='_compute_receipt_totals', digits=(12, 2),
    )
    receipt_expense_total = fields.Float(
        string='Belege Ausgaben (€)', compute='_compute_receipt_totals', digits=(12, 2),
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
    # copy=False auf allen Bearbeitungsvermerken: sonst nimmt "Duplizieren"
    # (copy/copy_data) Prüfvermerk, Bewilligung und Zahlungsanweisung mit. Eine
    # Sachbearbeiterin könnte einen von einer Kollegin bewilligten Antrag
    # duplizieren und hätte im Duplikat sofort einen fremden Prüfvermerk stehen –
    # das Vier-Augen-Prinzip liefe leer. 'state' wird von Odoo bereits automatisch
    # nicht kopiert (odoo/orm/fields.py: Felder mit dem Namen 'state' erhalten
    # copy=False als Vorgabe), alle anderen Felder sind per Default copy=True.
    date_submitted = fields.Date(string='Eingangsdatum', readonly=True, copy=False, tracking=True)
    date_approved = fields.Date(string='Zuschuss genehmigt am', readonly=True, copy=False, tracking=True)
    date_paid = fields.Date(string='Auszahlungsdatum', readonly=True, copy=False, tracking=True)
    payout_year = fields.Integer(
        string='Auszahlungsjahr', compute='_compute_payout_schedule', store=True,
        help='Haushaltsjahr der Auszahlung. Anträge bis zum Stichtag (KJR-OA: 15.11.) '
             'gelangen im selben Jahr zur Auszahlung, ab 16.11. erst im Folgejahr.',
    )
    payout_schedule_info = fields.Char(
        string='Auszahlungs-Hinweis', compute='_compute_payout_schedule', store=True,
    )
    reference_number = fields.Char(string='KJR-Aktenzeichen', copy=False, tracking=True)
    reviewed_by = fields.Many2one(
        'res.users', string='Bearbeitet von', copy=False, tracking=True,
    )
    sachlich_richtig = fields.Boolean(
        string='Sachlich richtig', default=False, copy=False, tracking=True,
        help='Bestätigung der Sachbearbeiterin dass alle Angaben geprüft wurden.',
    )
    payment_ordered = fields.Boolean(
        string='Zur Zahlung angewiesen', default=False, copy=False, tracking=True,
        help='Zahlungsanweisung erteilt.',
    )
    payment_ordered_by = fields.Many2one(
        'res.users', string='Zahlung angewiesen von', copy=False, tracking=True,
    )
    payment_ordered_date = fields.Date(string='Zahlung angewiesen am', copy=False, tracking=True)
    rejection_reason = fields.Text(string='Ablehnungsgrund', copy=False, tracking=True)
    note_internal = fields.Text(string='Interne Notizen (nicht für Antragsteller)')
    # Buchhaltung
    move_id = fields.Many2one('account.move', string='Buchung Bewilligung', readonly=True, copy=False)
    payment_id = fields.Many2one('account.payment', string='Auszahlung', readonly=True, copy=False)
    attachment_count = fields.Integer(string='Anhänge', compute='_compute_attachment_count')
    participant_ids = fields.One2many('kjr.grant.participant', 'application_id', string='Teilnehmerliste')
    participant_count = fields.Integer(string='TN-Liste Einträge', compute='_compute_participant_count')
    settlement_id = fields.One2many('kjr.grant.settlement', 'application_id', string='Abrechnungen')
    settlement_count = fields.Integer(string='Anzahl Abrechnungen', compute='_compute_settlement_count')

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

    @api.depends('grant_type_id', 'grant_type_id.code', 'measure_start')
    def _compute_applicable_type(self):
        """Regelauswahl nach Maßnahmenbeginn (§-Fassungen mit valid_from/valid_to).

        Ändert der KJR eine Förderart (z. B. neue Tagessätze ab 01.01.), wird dafür
        eine neue Fassung mit gleichem 'code' angelegt. Maßgeblich ist die Fassung,
        die zum BEGINN der Maßnahme galt. Ermittelt wird sie über
        kjr.grant.type.find_for_date(code, date_ref).

        Das Ergebnis ist nur informativ: 'grant_type_id' bleibt führend und wird
        nicht umgehängt (siehe Kommentar am Feld). Weicht die gültige Fassung ab,
        füllen wir 'applicable_type_warning'; der Text landet zusätzlich beim
        Einreichen als Hinweis im Chatter (_post_compliance_warnings)."""
        Type = self.env['kjr.grant.type']
        # Defensiv: solange die Fassungsverwaltung (find_for_date) in einer älteren
        # Modulversion fehlt, gilt schlicht die gewählte Förderart.
        has_finder = hasattr(Type, 'find_for_date')
        for rec in self:
            # Stored-compute-Regel analog: jedem Record in jedem Zweig einen Wert geben.
            rec.applicable_type_id = rec.grant_type_id
            rec.applicable_type_warning = ''
            if not (has_finder and rec.grant_type_id and rec.grant_type_id.code and rec.measure_start):
                continue
            applicable = Type.find_for_date(rec.grant_type_id.code, rec.measure_start)
            if applicable and applicable.id != rec.grant_type_id.id:
                rec.applicable_type_id = applicable
                rec.applicable_type_warning = _(
                    'Regelstand: Zum Maßnahmenbeginn %(start)s galt die Fassung '
                    '"%(valid)s"%(group)s, gewählt ist aber "%(chosen)s". Bitte prüfen, '
                    'welche Fassung der Berechnung zugrunde zu legen ist – die Förderart '
                    'wird bewusst nicht automatisch umgestellt.'
                ) % {
                    'start': rec.measure_start.strftime('%d.%m.%Y'),
                    'valid': applicable.display_name,
                    'group': (' [%s]' % applicable.rule_group)
                             if applicable._fields.get('rule_group') and applicable.rule_group else '',
                    'chosen': rec.grant_type_id.display_name,
                }

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
        """Tagessatz-Berechnung (TN × Tage × Satz) inkl. anerkannter Gruppenleitungen.

        Gruppenleitungen erhalten ebenfalls den Tagessatz; mit gültiger Juleica erhöht
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
        # Max. 1 anerkannte Gruppenleitung je 'leader_ratio' TN (konfigurierbar, KJR-OA: 5)
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

        # ── Investitionszuschuss (Landkreis-Programm, konfigurierbar) ─────────
        elif t.code == 'invest':
            # Generischer Investitionszuschuss: konfigurierbarer Anteil der
            # (Investitions-)Kosten, gedeckelt auf den Höchstbetrag. Die konkreten
            # Sätze (Förderquote / Höchstbetrag) des jeweiligen Landkreis-Programms
            # werden in der Förderart gepflegt – kein hartkodierter Wert. Anders als
            # die laufenden Maßnahmen ist ein Investitionszuschuss nicht an einen
            # Fehlbetrag gebunden (daher unten von der Fehlbetragsdeckelung ausgenommen).
            if self.cost_total > 0:
                calculated = self.cost_total * (t.max_cofinancing_pct / 100.0)

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
        # § 4.7 (Pauschale), § 4.9 (BayRKG-Fahrtkostenerstattung) und der
        # Investitionszuschuss sind ihrer Natur nach von der 50%-Kofinanzierungs-
        # (im Zweig bereits angewandt) und der Fehlbetragsdeckelung ausgenommen.
        exempt = ('4_7', '4_9', 'invest')
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

    @api.depends('receipt_ids', 'receipt_ids.amount', 'receipt_ids.direction')
    def _compute_receipt_totals(self):
        """Summen der digitalen Belegliste. Das Vorzeichen steckt in 'direction',
        die Beträge selbst sind immer positiv erfasst."""
        for rec in self:
            rec.receipt_count = len(rec.receipt_ids)
            rec.receipt_income_total = sum(
                r.amount for r in rec.receipt_ids if r.direction == 'income'
            )
            rec.receipt_expense_total = sum(
                r.amount for r in rec.receipt_ids if r.direction == 'expense'
            )

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
                    'Es können nicht mehr Gruppenleitungen mit Juleica (%(j)d) als '
                    'Gruppenleitungen insgesamt (%(l)d) angegeben werden.',
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

    # ── Bankverbindung ───────────────────────────────────────────────────────

    @staticmethod
    def _normalize_bank_code(value):
        """Eingabe der Antragsteller tolerant normalisieren: Leerzeichen (auch
        geschützte), Bindestriche und Kleinschreibung sind erlaubt und werden vor
        der Prüfung entfernt bzw. in Großbuchstaben gewandelt."""
        return re.sub(r'[\s -]', '', (value or '')).upper()

    @staticmethod
    def _iban_is_valid(iban):
        """Prüfziffernverfahren Mod 97-10 nach ISO 13616 / DIN 91060.

        Ablauf: die ersten vier Zeichen (Land + Prüfziffer) ans Ende stellen, jeden
        Buchstaben durch seine Position im Alphabet + 9 ersetzen (A=10 … Z=35) und
        den Rest der Division durch 97 bilden. Gültig ist die IBAN bei Rest 1.
        Bewusst selbst gerechnet – 'base_iban' steht NICHT in den depends."""
        if not IBAN_RE.match(iban):
            return False
        rearranged = iban[4:] + iban[:4]
        digits = ''.join(
            str(ord(ch) - 55) if ch.isalpha() else ch for ch in rearranged
        )
        return int(digits) % 97 == 1

    @api.constrains('payment_iban')
    def _check_payment_iban(self):
        """IBAN-Format und Prüfziffer validieren. Leer bleibt erlaubt: ob eine IBAN
        Pflicht ist, entscheidet die Förderart (allow_private_account) und wird beim
        Einreichen/Bewilligen geprüft – nicht hier."""
        for rec in self:
            if not rec.payment_iban:
                continue
            iban = rec._normalize_bank_code(rec.payment_iban)
            expected_len = IBAN_LENGTHS.get(iban[:2])
            if expected_len and len(iban) != expected_len:
                raise ValidationError(_(
                    'Die IBAN "%(iban)s" ist keine gültige %(country)s-IBAN: erwartet '
                    'werden %(exp)d Stellen, angegeben sind %(act)d.',
                    iban=rec.payment_iban, country=iban[:2],
                    exp=expected_len, act=len(iban),
                ))
            if not rec._iban_is_valid(iban):
                raise ValidationError(_(
                    'Die IBAN "%(iban)s" ist ungültig. Erwartet wird das Format '
                    'Länderkürzel + 2 Prüfziffern + Kontokennung '
                    '(z. B. DE12 3456 7890 1234 5678 90); die Prüfziffer muss zur '
                    'IBAN passen (Mod-97-Verfahren). Bitte die Angabe mit dem '
                    'Kontoauszug abgleichen.',
                    iban=rec.payment_iban,
                ))

    @api.constrains('payment_bic')
    def _check_payment_bic(self):
        """BIC-Format nach ISO 9362 prüfen (leer erlaubt – der BIC ist im SEPA-Raum
        nicht mehr zwingend anzugeben)."""
        for rec in self:
            if not rec.payment_bic:
                continue
            bic = rec._normalize_bank_code(rec.payment_bic)
            if not BIC_RE.match(bic):
                raise ValidationError(_(
                    'Der BIC "%(bic)s" ist ungültig. Erwartet werden 8 oder 11 Stellen: '
                    '4 Buchstaben Bankcode + 2 Buchstaben Ländercode + 2 Zeichen '
                    'Ortscode + optional 3 Zeichen Filialcode (z. B. BYLADEM1ALG).',
                    bic=rec.payment_bic,
                ))

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

    # ── Schreibschutz Bearbeitungsvermerke ───────────────────────────────────
    # Diese Felder tragen das Vier-Augen-Prinzip (Prüfung / Bewilligung /
    # Zahlungsanweisung / Auszahlung). Sie dürfen ausschließlich über die
    # Workflow-Actions gesetzt werden; die schreiben über _workflow_write()
    # (prozessinterne Freigabe, siehe _WORKFLOW_WRITE_ALLOWED am Dateianfang).
    # Ohne diese Freigabe ist ein direkter Schreibzugriff nur der Administrator-
    # Gruppe erlaubt – und wird dann im Chatter protokolliert (Korrekturen sollen
    # möglich, aber nachvollziehbar sein).
    _WORKFLOW_PROTECTED_FIELDS = (
        'state', 'reviewed_by', 'payment_ordered', 'payment_ordered_by',
        'payment_ordered_date',
    )
    # 'Sachlich richtig' ist der eigentliche Prüfvermerk und wird von der
    # Sachbearbeitung im Formular gesetzt (dafür gibt es bewusst keinen eigenen
    # Button). Er bleibt deshalb für die Sachbearbeiter-Gruppe direkt setzbar,
    # wird aber protokolliert – und wer zeichnet, gilt als prüfende Person und
    # wird in 'Bearbeitet von' eingetragen, damit er/sie nicht auch bewilligen kann.
    _REVIEW_MARK_FIELD = 'sachlich_richtig'

    # ── Prozessinterne Freigabe ──────────────────────────────────────────────

    def _workflow_write(self, vals):
        """Schreibt Bearbeitungsvermerke aus einer Workflow-Action heraus.

        Nur dieser Weg hebt den Schreibschutz auf. Die Freigabe steckt in einer
        ContextVar (nicht im Odoo-Kontext) und ist damit über RPC nicht setzbar.
        Die Methode selbst ist ebenfalls nicht per RPC aufrufbar – Odoo lässt nur
        öffentliche Methoden zu (odoo/service/model.py, get_public_method():
        "if name.startswith('_') … raise AccessError").

        Die Freigabe gilt bewusst für GENAU EINEN write()-Aufruf: write() setzt
        sie sofort wieder zurück, bevor super().write() läuft. Verschachtelte
        Schreibvorgänge (Computes, Inverse, message_post, One2many-Zeilen) laufen
        dadurch wieder mit vollem Schutz – eine einmal geöffnete Freigabe kann
        sich also nicht über den gesamten Aufrufbaum ausbreiten."""
        token = _WORKFLOW_WRITE_ALLOWED.set(True)
        try:
            return self.write(vals)
        finally:
            _WORKFLOW_WRITE_ALLOWED.reset(token)

    @api.model
    def _workflow_mark_is_set(self, fname, value):
        """Trägt der Wert tatsächlich einen Bearbeitungsvermerk?

        Der Web-Client schickt beim Anlegen auch Vorgabewerte mit. 'state' =
        'draft' bzw. leere/falsche Vermerke sind keine Bevorrechtigung und dürfen
        das Anlegen eines ganz normalen Antrags nicht blockieren."""
        if fname == 'state':
            return bool(value) and value != 'draft'
        return bool(value)

    @api.model
    def default_get(self, fields_list):
        """Vorgabewerte dürfen die Bearbeitungsvermerke nicht vorbelegen.

        Odoo mischt Vorgaben aus drei Quellen zusammen: den 'default_*'-Schlüsseln
        im Kontext (die bei /web/dataset/call_kw vollständig vom Client kommen),
        den persönlichen Vorgabewerten aus ir.default – die sich JEDER Benutzer
        über ir.default.set() selbst auf jedes Feld setzen darf – und den
        default=-Angaben am Feld. Alle drei landen erst in
        _add_missing_default_values() in den Werten, also NACH einer Prüfung, die
        nur vals betrachtet.

        Ohne diesen Filter genügt ein einziges ir.default.set(), um einen Antrag
        anzulegen, der sofort 'approved' ist und einen fremden Prüfvermerk trägt –
        das Vier-Augen-Prinzip wäre damit vollständig ausgehebelt.

        Der Filter greift BEDINGUNGSLOS, insbesondere auch unter sudo(). Das ist
        kein übertriebener Gürtel-und-Hosenträger, sondern zwingend: sudo() setzt
        nur su=True und lässt env.uid unverändert ("The superuser mode does not
        change the current user", odoo/orm/models.py), während
        ir.default._get_model_defaults() die Vorgaben genau über env.uid liest.
        Eine Ausnahme für env.su würde die persönlichen Vorgabewerte des
        angemeldeten Benutzers also ausgerechnet dort wieder durchlassen, wo
        Servercode mit erhöhten Rechten anlegt – etwa im öffentlichen
        Antragsformular (controllers/website.py, sudo().create()). Genau dieser
        Weg war offen und ist hier geschlossen.

        Unbedenklich, weil ausschließlich VORGABEWERTE gefiltert werden: explizit
        übergebene Werte (Migration, Tests, Brückenmodul, Workflow-Actions) laufen
        über vals bzw. _workflow_write() und sind davon nicht berührt."""
        defaults = super().default_get(fields_list)
        for fname in self._WORKFLOW_PROTECTED_FIELDS + (self._REVIEW_MARK_FIELD,):
            if fname not in defaults:
                continue
            if not self._workflow_mark_is_set(fname, defaults[fname]):
                continue
            if fname == 'state':
                # 'state' ist ein Pflichtfeld: entfernen würde beim Anlegen in
                # einen NOT-NULL-Fehler laufen statt in den gewollten Entwurf.
                defaults[fname] = 'draft'
            else:
                del defaults[fname]
        return defaults

    @api.model_create_multi
    def create(self, vals_list):
        """Anlegen: die Bearbeitungsvermerke dürfen keine Hintertür sein.

        Ohne diese Prüfung könnte eine Sachbearbeiterin per RPC einen Antrag
        direkt mit 'sachlich_richtig=True' und einem fremden 'reviewed_by'
        anlegen (oder gleich mit state='paid') und damit das Vier-Augen-Prinzip
        vollständig umgehen – der write()-Schutz greift beim Anlegen nicht.

        Geprüft werden vals UND die 'default_*'-Kontextschlüssel: Odoo füllt
        fehlende Felder über _add_missing_default_values()/default_get() aus dem
        Kontext, der bei /web/dataset/call_kw vom Client kommt. Ein
        'default_state': 'paid' würde sonst an vals vorbei greifen.

        Sonderfall "Sachlich richtig": der Haken wird beim Abtippen von
        Papieranträgen gern direkt mitgesetzt. Er wird deshalb nicht abgewiesen,
        sondern aus dem Anlegen herausgenommen und danach über den normalen
        write()-Weg gesetzt – dort greifen Gruppenprüfung, Chatter-Protokoll und
        vor allem die Zuordnung "wer zeichnet, hat geprüft" (reviewed_by)."""
        protected = self._WORKFLOW_PROTECTED_FIELDS
        privileged = self.env.su or _WORKFLOW_WRITE_ALLOWED.get()
        is_manager = privileged or self.env.user.has_group('kjr_grant.group_kjr_manager')

        # Je Datensatz getrennt ermitteln, damit das Protokoll unten nur die
        # Vermerke nennt, die im jeweiligen Antrag wirklich vorbelegt wurden.
        touched_per_vals = [
            [f for f in protected
             if f in vals and self._workflow_mark_is_set(f, vals[f])]
            for vals in vals_list
        ]
        touched = sorted({f for entry in touched_per_vals for f in entry})
        # 'Sachlich richtig' aus dem Anlegen herausnehmen (siehe Docstring).
        deferred_review = []
        if not privileged:
            for idx, vals in enumerate(vals_list):
                if vals.pop(self._REVIEW_MARK_FIELD, False):
                    deferred_review.append(idx)

        if not privileged and not is_manager:
            if touched:
                raise UserError(_(
                    'Die Bearbeitungsvermerke (%(fields)s) können beim Anlegen eines '
                    'Antrags nicht vorbelegt werden. Ein Antrag beginnt als Entwurf '
                    'und wird über die Schaltflächen geführt: "Einreichen" ▸ "Zur '
                    'Prüfung annehmen" ▸ "Bewilligen" ▸ "Zur Zahlung anweisen" ▸ '
                    '"Als ausgezahlt markieren". So bleibt nachvollziehbar, wer '
                    'geprüft, bewilligt und angewiesen hat (Vier-Augen-Prinzip).',
                    fields=', '.join(self._fields[f].string for f in touched),
                ))
            # Kontext-Defaults auf geschützte Felder verwerfen (sie kämen vom Client).
            ctx_keys = {
                'default_%s' % f
                for f in protected + (self._REVIEW_MARK_FIELD,)
                if self._workflow_mark_is_set(f, self.env.context.get('default_%s' % f))
            }
            if ctx_keys:
                self = self.with_context({
                    k: v for k, v in self.env.context.items() if k not in ctx_keys
                })

        for vals in vals_list:
            if vals.get('name', _('Neu')) == _('Neu'):
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('kjr.grant.application')
                    or _('Neu')
                )
        records = super().create(vals_list)

        if deferred_review:
            # Normaler write()-Weg: prüft die Gruppe, protokolliert im Chatter und
            # trägt die zeichnende Person als "Bearbeitet von" ein.
            records.browse([records[i].id for i in deferred_review]).write(
                {self._REVIEW_MARK_FIELD: True})

        # Korrekturweg für die Geschäftsstellenleitung: erlaubt, aber protokolliert.
        if touched and not privileged:
            user_name = self.env.user.display_name
            for rec, rec_touched in zip(records, touched_per_vals):
                if not rec_touched:
                    continue
                items = markupsafe.Markup('').join(
                    markupsafe.Markup('<li>%s</li>') % (
                        _('%(field)s: %(value)s') % {
                            'field': rec._fields[f].string,
                            'value': rec._format_workflow_value(f, rec[f]),
                        }
                    )
                    for f in rec_touched
                )
                rec.message_post(
                    body=markupsafe.Markup('<p>%s</p><ul>%s</ul>') % (
                        _('Antrag durch %s bereits mit Bearbeitungsvermerken '
                          'angelegt:') % user_name,
                        items,
                    ),
                    subtype_xmlid='mail.mt_note',
                )
        return records

    def _format_workflow_value(self, fname, value):
        """Feldwert für das Chatter-Protokoll lesbar aufbereiten."""
        field = self._fields[fname]
        if field.type == 'boolean':
            return _('Ja') if value else _('Nein')
        if not value:
            return _('(leer)')
        if field.type == 'many2one':
            return value.display_name
        if field.type == 'date':
            return value.strftime('%d.%m.%Y')
        if field.type == 'selection':
            selection = field.selection
            if callable(selection):
                selection = selection(self)
            return dict(selection).get(value, value)
        return str(value)

    def write(self, vals):
        """Schreibschutz für die Bearbeitungsvermerke.

        Ohne diesen Override ließe sich der komplette Workflow im Formular von
        einer einzigen Person durchklicken (Status setzen, 'sachlich richtig'
        haken, Zahlung anweisen) – das Vier-Augen-Prinzip wäre wirkungslos.

        Verhalten:
          • Normale Feldänderungen (Beträge, Texte, Teilnehmer …) und alle
            Schreibvorgänge aus den Workflow-Actions laufen unverändert durch.
          • Direkte Änderungen an Status/Vermerken sind der Administrator-Gruppe
            vorbehalten (Korrekturen bei Fehleingaben) und landen im Chatter.
          • Alle anderen erhalten einen Hinweis auf die Workflow-Schaltflächen.

        Die Freigabe der Workflow-Actions läuft NICHT über den Odoo-Kontext
        (der ist bei /web/dataset/call_kw frei fälschbar, siehe Kommentar bei
        _WORKFLOW_WRITE_ALLOWED), sondern über eine prozessinterne ContextVar,
        die ausschließlich _workflow_write() setzen kann.
        """
        # Freigabe aus einer Workflow-Action: gilt nur für diesen einen Aufruf
        # und wird vor super().write() sofort zurückgesetzt, damit sich die
        # Freigabe nicht auf verschachtelte Schreibvorgänge vererbt.
        if _WORKFLOW_WRITE_ALLOWED.get():
            token = _WORKFLOW_WRITE_ALLOWED.set(False)
            try:
                return super().write(vals)
            finally:
                _WORKFLOW_WRITE_ALLOWED.reset(token)

        touched = [f for f in self._WORKFLOW_PROTECTED_FIELDS if f in vals]
        review_mark = self._REVIEW_MARK_FIELD in vals
        # Schnellpfad: nichts Geschütztes betroffen bzw. Schreibvorgang aus
        # Servercode (sudo, z. B. Website-Formular, Migration, Datenimport).
        if (not touched and not review_mark) or self.env.su:
            return super().write(vals)

        is_manager = self.env.user.has_group('kjr_grant.group_kjr_manager')
        if touched and not is_manager:
            raise UserError(_(
                'Die Bearbeitungsvermerke (%(fields)s) können nicht direkt geändert '
                'werden. Bitte den Antrag über die Schaltflächen führen: '
                '"Zur Prüfung annehmen" ▸ "Bewilligen" ▸ "Zur Zahlung anweisen" ▸ '
                '"Als ausgezahlt markieren". So bleibt nachvollziehbar, wer geprüft, '
                'bewilligt und angewiesen hat (Vier-Augen-Prinzip). '
                'Korrekturen bei Fehleingaben nimmt die Geschäftsstellenleitung '
                '(Gruppe "Administrator") vor; sie werden im Protokoll festgehalten.',
                fields=', '.join(self._fields[f].string for f in touched),
            ))
        if review_mark and not (is_manager or self.env.user.has_group(
                'kjr_grant.group_kjr_reviewer')):
            raise UserError(_(
                'Der Vermerk "Sachlich richtig" darf nur von der Sachbearbeitung '
                'gesetzt werden.'
            ))

        # Altwerte einmal für den gesamten Recordset lesen. Der erste Feldzugriff
        # lädt über den Prefetch alle Records auf einmal – kein Query je Record.
        logged = list(touched) + ([self._REVIEW_MARK_FIELD] if review_mark else [])
        old_values = {rec.id: {f: rec[f] for f in logged} for rec in self}

        res = super().write(vals)

        user_name = self.env.user.display_name
        for rec in self:
            changes = [
                _('%(field)s: von %(old)s auf %(new)s') % {
                    'field': rec._fields[f].string,
                    'old': rec._format_workflow_value(f, old_values[rec.id][f]),
                    'new': rec._format_workflow_value(f, rec[f]),
                }
                for f in logged
                if old_values[rec.id][f] != rec[f]
            ]
            if not changes:
                continue
            items = markupsafe.Markup('').join(
                markupsafe.Markup('<li>%s</li>') % c for c in changes
            )
            rec.message_post(
                body=markupsafe.Markup('<p>%s</p><ul>%s</ul>') % (
                    _('Bearbeitungsvermerk manuell geändert durch %s:') % user_name,
                    items,
                ),
                subtype_xmlid='mail.mt_note',
            )

        # Wer "sachlich richtig" zeichnet, ist die prüfende Person: ist noch keine
        # Prüfung vermerkt, wird sie hier festgehalten. Sonst könnte man den Haken
        # setzen, ohne "in Prüfung" zu nehmen, und anschließend selbst bewilligen.
        # TODO(Bora): konservativ gewählt (kassenrechtlich sauber: wer zeichnet,
        # hat geprüft). Wenn die Geschäftsstelle den Haken auch ohne Zuordnung
        # setzen können soll, diesen Block entfernen – dann greift das Vier-Augen-
        # Prinzip erst ab "Zur Prüfung annehmen".
        if review_mark and vals.get(self._REVIEW_MARK_FIELD):
            to_stamp = self.filtered(lambda r: not r.reviewed_by)
            if to_stamp:
                to_stamp._workflow_write({'reviewed_by': self.env.user.id})
                for rec in to_stamp:
                    rec.message_post(
                        body=_(
                            'Sachliche Prüfung durch %s vermerkt (Bearbeitet von). '
                            'Die Bewilligung muss daher durch eine zweite Person erfolgen.'
                        ) % user_name,
                        subtype_xmlid='mail.mt_note',
                    )
        return res

    # ══════════════════════════════════════════════════════════════════════════
    # WORKFLOW
    # ══════════════════════════════════════════════════════════════════════════

    # ── Vier-Augen-Prinzip ───────────────────────────────────────────────────

    @api.model
    def _four_eyes_enabled(self):
        """Ist das Vier-Augen-Prinzip aktiv? (Systemparameter, Default: an)

        Prüfung, Bewilligung und Zahlungsanweisung dürfen kassenrechtlich nicht in
        einer Hand liegen. Technisch erzwungen wird das über den Systemparameter
        'kjr_grant.enforce_four_eyes' (Default '1' = an).

        Eine Ein-Personen-Geschäftsstelle (Urlaub/Krankheit, sehr kleiner Kreis)
        kann die Sperre abschalten: Einstellungen ▸ Technisch ▸ Parameter ▸
        Systemparameter, 'kjr_grant.enforce_four_eyes' auf '0' setzen. Die
        Bearbeitungsvermerke (Bearbeitet von / Zahlung angewiesen von) werden
        weiterhin protokolliert."""
        param = self.env['ir.config_parameter'].sudo().get_param(
            'kjr_grant.enforce_four_eyes', '1')
        return str(param).strip().lower() not in ('0', 'false', 'off', 'nein', '')

    @api.model
    def _four_eyes_hint(self):
        """Einheitlicher Zusatzhinweis, wie sich die Sperre abschalten lässt."""
        return _(
            'Hinweis: Das Vier-Augen-Prinzip lässt sich für eine Ein-Personen-'
            'Geschäftsstelle über den Systemparameter "kjr_grant.enforce_four_eyes" '
            '(Wert "0") abschalten – Einstellungen ▸ Technisch ▸ Systemparameter.'
        )

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Nur Entwürfe können eingereicht werden.'))
            rec._check_completeness()
            rec._check_yearly_limit()
            rec._workflow_write({
                'state': 'submitted', 'date_submitted': fields.Date.today(),
            })
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
            rec._workflow_write({
                'state': 'in_review', 'reviewed_by': self.env.user.id,
            })

    def action_approve(self):
        if not self.env.user.has_group('kjr_grant.group_kjr_reviewer'):
            raise AccessError(_('Keine Berechtigung zum Bewilligen.'))
        for rec in self:
            if rec.state not in ('submitted', 'in_review'):
                raise UserError(_('Nur eingereichte Anträge können bewilligt werden.'))
            # Sachliche Prüfung ist der Bewilligung zwingend vorgelagert – ohne den
            # Vermerk "sachlich richtig" fehlt die Grundlage für die Anordnung.
            # TODO(Bora): bewusst auch bei abgeschaltetem Vier-Augen-Prinzip zwingend
            # (konservative Variante, kassenrechtlich sauber). Falls die Ein-Personen-
            # Geschäftsstelle das anders wünscht, hier an _four_eyes_enabled() koppeln.
            if not rec.sachlich_richtig:
                raise UserError(_(
                    'Antrag %(name)s: Der Vermerk "Sachlich richtig" fehlt. Bitte den '
                    'Antrag zuerst sachlich prüfen und den Vermerk setzen, bevor '
                    'bewilligt wird.',
                    name=rec.name,
                ))
            # Vier-Augen-Prinzip: wer geprüft hat, darf nicht selbst bewilligen.
            # Ohne vermerkte Prüfung liefe die Sperre ins Leere (der Button
            # "Bewilligen" ist schon im Status "Eingereicht" sichtbar) – dann
            # könnte eine Person bewilligen UND anweisen. Bei aktivem Vier-Augen-
            # Prinzip ist der Prüfvermerk deshalb zwingend.
            if rec._four_eyes_enabled():
                if not rec.reviewed_by:
                    raise UserError(_(
                        'Vier-Augen-Prinzip: Für Antrag %(name)s ist keine prüfende '
                        'Person vermerkt. Bitte den Antrag zuerst über "Zur Prüfung '
                        'annehmen" in Prüfung nehmen (oder den Vermerk "Sachlich '
                        'richtig" setzen); bewilligen muss anschließend eine zweite '
                        'Person.\n\n%(hint)s',
                        name=rec.name, hint=rec._four_eyes_hint(),
                    ))
                if rec.reviewed_by.id == self.env.user.id:
                    raise UserError(_(
                        'Vier-Augen-Prinzip: Antrag %(name)s wurde von %(user)s geprüft – '
                        'dieselbe Person darf ihn nicht auch bewilligen. Bitte eine zweite '
                        'Person der Geschäftsstelle bewilligen lassen.\n\n%(hint)s',
                        name=rec.name, user=rec.reviewed_by.name, hint=rec._four_eyes_hint(),
                    ))
            if not rec.grant_type_id.allow_private_account and not rec.payment_iban:
                raise UserError(_('IBAN fehlt. Bitte vor Bewilligung angeben.'))
            if not rec.grant_approved:
                rec.grant_approved = rec.grant_calculated
            if rec.grant_approved != rec.grant_calculated and not rec.grant_override_reason:
                raise UserError(_(
                    'Bitte begründen Sie die Abweichung vom berechneten Zuschuss '
                    '(Feld "Begründung Abweichung").'
                ))
            rec._workflow_write({
                'state': 'approved', 'date_approved': fields.Date.today(),
            })
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
            rec._workflow_write({'state': 'rejected'})
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
        'Zur Auszahlung'. Bei aktivem Vier-Augen-Prinzip darf die anweisende Person
        nicht dieselbe sein, die den Antrag sachlich geprüft hat."""
        if not self.env.user.has_group('kjr_grant.group_kjr_reviewer'):
            raise AccessError(_('Keine Berechtigung zur Zahlungsanweisung.'))
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_('Nur bewilligte Anträge können zur Zahlung angewiesen werden.'))
            if (rec._four_eyes_enabled() and rec.reviewed_by
                    and rec.reviewed_by.id == self.env.user.id):
                raise UserError(_(
                    'Vier-Augen-Prinzip: Antrag %(name)s wurde von %(user)s geprüft – '
                    'dieselbe Person darf die Zahlung nicht anweisen. Bitte die '
                    'Anweisung durch eine zweite Person erteilen lassen.\n\n%(hint)s',
                    name=rec.name, user=rec.reviewed_by.name, hint=rec._four_eyes_hint(),
                ))
            rec._workflow_write({
                'payment_ordered': True,
                'payment_ordered_by': self.env.user.id,
                'payment_ordered_date': fields.Date.today(),
            })
            rec.message_post(
                body=_('Zur Zahlung angewiesen am %s.') % fields.Date.today().strftime('%d.%m.%Y'),
                subtype_xmlid='mail.mt_note',
            )

    def action_mark_paid(self):
        """Antrag als ausgezahlt markieren.

        Die Zahlungsanweisung wird hier bewusst NICHT mehr nebenbei gesetzt: sonst
        könnte eine Person prüfen, bewilligen und anweisen. Der Vermerk muss über
        "Zur Zahlung anweisen" (action_order_payment) von einer zweiten Person
        gesetzt worden sein."""
        if not self.env.user.has_group('kjr_grant.group_kjr_reviewer'):
            raise AccessError(_('Keine Berechtigung zur Auszahlungsmarkierung.'))
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_('Nur bewilligte Anträge können als ausgezahlt markiert werden.'))
            if not rec.payment_ordered:
                raise UserError(_(
                    'Antrag %(name)s ist noch nicht zur Zahlung angewiesen. Bitte zuerst '
                    'den Schritt "Zur Zahlung anweisen" ausführen; erst danach kann die '
                    'Auszahlung vermerkt werden.',
                    name=rec.name,
                ))
            # Vier-Augen-Prinzip: wer angewiesen hat, vollzieht die Auszahlung nicht selbst.
            # Ohne vermerkte anweisende Person liefe die Sperre ins Leere (der Haken
            # kann von der Administrator-Gruppe auch manuell gesetzt worden sein).
            if rec._four_eyes_enabled() and not rec.payment_ordered_by:
                raise UserError(_(
                    'Antrag %(name)s: Zur Zahlungsanweisung ist keine anweisende '
                    'Person vermerkt. Bitte die Anweisung über die Schaltfläche '
                    '"Zur Zahlung anweisen" erteilen lassen – erst danach kann die '
                    'Auszahlung vermerkt werden.\n\n%(hint)s',
                    name=rec.name, hint=rec._four_eyes_hint(),
                ))
            if (rec._four_eyes_enabled() and rec.payment_ordered_by
                    and rec.payment_ordered_by.id == self.env.user.id):
                raise UserError(_(
                    'Vier-Augen-Prinzip: Die Zahlung für Antrag %(name)s wurde von '
                    '%(user)s angewiesen – dieselbe Person darf die Auszahlung nicht '
                    'selbst vollziehen. Bitte durch eine zweite Person ausführen lassen.'
                    '\n\n%(hint)s',
                    name=rec.name, user=rec.payment_ordered_by.name,
                    hint=rec._four_eyes_hint(),
                ))
            rec._workflow_write({
                'state': 'paid', 'date_paid': fields.Date.today(),
            })
            rec._create_grant_payment()

    def action_reset_draft(self):
        """Antrag auf Entwurf zurücksetzen und alle Bearbeitungsvermerke verwerfen.

        Die Vermerke müssen mit zurückgenommen werden: bleiben Prüfung,
        Bewilligungsdatum und vor allem die Zahlungsanweisung stehen, gilt nach
        einer Änderung (z. B. des Betrags) und erneuter Bewilligung die ALTE
        Anweisung weiter – die Auszahlung wäre dann ohne zweite Person möglich.
        Was verworfen wurde, hält der Chatter fest (Kassenprüfung)."""
        # Serverseitig auf die Administrator-Gruppe begrenzt (die Schaltfläche im
        # Formular ist bereits so eingeschränkt); sonst könnten Antragsteller die
        # Vermerke eines bewilligten Antrags über einen direkten Aufruf verwerfen.
        if not self.env.user.has_group('kjr_grant.group_kjr_manager'):
            raise AccessError(_(
                'Nur die Geschäftsstellenleitung (Gruppe "Administrator") darf '
                'Anträge auf Entwurf zurücksetzen.'
            ))
        cleared_fields = (
            'reviewed_by', 'sachlich_richtig', 'payment_ordered',
            'payment_ordered_by', 'payment_ordered_date', 'date_approved',
        )
        for rec in self:
            if rec.state == 'paid':
                raise UserError(_('Ausgezahlte Anträge können nicht zurückgesetzt werden.'))
            discarded = [
                _('%(field)s (war: %(value)s)') % {
                    'field': rec._fields[f].string,
                    'value': rec._format_workflow_value(f, rec[f]),
                }
                for f in cleared_fields if rec[f]
            ]
            rec._workflow_write({
                'state': 'draft',
                'reviewed_by': False,
                'sachlich_richtig': False,
                'payment_ordered': False,
                'payment_ordered_by': False,
                'payment_ordered_date': False,
                'date_approved': False,
            })
            if discarded:
                items = markupsafe.Markup('').join(
                    markupsafe.Markup('<li>%s</li>') % d for d in discarded
                )
                body = markupsafe.Markup('<p>%s</p><ul>%s</ul><p>%s</p>') % (
                    _('Auf Entwurf zurückgesetzt durch %s. Verworfene '
                      'Bearbeitungsvermerke:') % self.env.user.display_name,
                    items,
                    _('Prüfung, Bewilligung und Zahlungsanweisung sind erneut '
                      'zu durchlaufen.'),
                )
            else:
                body = _('Auf Entwurf zurückgesetzt durch %s.') % self.env.user.display_name
            rec.message_post(body=body, subtype_xmlid='mail.mt_note')

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
        # Die digitale Unterschrift nutzt die optionale Enterprise-App "sign".
        # Ist sie installiert, öffnen wir den Sign-Upload; sonst bleibt das PDF
        # am Antrag angehängt (kein harter Abhängigkeits-/Crash-Zwang).
        sign_installed = bool(self.env['ir.module.module'].sudo().search([
            ('name', '=', 'sign'), ('state', '=', 'installed'),
        ], limit=1))
        if sign_installed:
            return {
                'type': 'ir.actions.act_url',
                'url': f'/sign/new-from-attachment/{attachment.id}',
                'target': 'self',
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('PDF erstellt'),
                'message': _('Das Antrags-PDF wurde angehängt. Die App „Sign" ist nicht '
                             'installiert – bitte das Dokument manuell zur Unterschrift versenden.'),
                'type': 'warning',
                'sticky': False,
            },
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
            # Odoo 19: account.payment nutzt 'memo' (nicht mehr 'ref').
            'memo': f'Zuschuss {self.name} — {self.measure_name}',
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
        # § 4.9 (Delegiertenfahrtkosten), Investitionszuschuss.
        no_tn_codes = ('4_6', '4_7', '4_9', 'invest')
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

        # Teilnahmeliste: digital oder als Datei. 'teilnahme' muss mitgeprüft werden —
        # seit 07/2026 heißt das Feld im Formular „Teilnahmeliste", die Dateien der
        # Antragsteller heißen entsprechend (Bora-Abstimmung 30.07.2026).
        if t.requires_tn_list and not self.participant_ids:
            attachments = self.env['ir.attachment'].search([
                ('res_model', '=', self._name), ('res_id', '=', self.id),
            ])
            names = [a.name.lower() for a in attachments]
            if not any(kw in n for n in names
                       for kw in ['teilnahme', 'teilnehmer', 'tn-liste', 'tn_liste']):
                errors.append(_('Teilnahmeliste fehlt. Bitte digital ausfüllen oder als Datei hochladen.'))

        attachments = self.env['ir.attachment'].search([
            ('res_model', '=', self._name), ('res_id', '=', self.id),
        ])
        names = [a.name.lower() for a in attachments]

        if t.requires_report:
            if not self.measure_report and not any(kw in n for n in names for kw in ['bericht', 'report', 'protokoll']):
                errors.append(_('Maßnahmenbericht fehlt (Textfeld oder Datei mit "bericht" im Namen).'))
        if t.requires_receipt:
            # Entweder-oder: digital erfasste Belegliste ODER hochgeladene Datei.
            if self.use_digital_receipts:
                if not self.receipt_ids:
                    errors.append(_('Die Belegliste ist als digital erfasst markiert, enthält '
                                   'aber keinen einzigen Beleg. Bitte Belege eintragen oder die '
                                   'Belegliste als Datei hochladen.'))
            elif not any(kw in n for n in names for kw in ['beleg', 'rechnung', 'quittung']):
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
        # Regelstand: gewählte Förderart vs. die zum Maßnahmenbeginn gültige Fassung.
        if self.applicable_type_warning:
            warnings.append(self.applicable_type_warning)
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
                'Betreuungsschlüssel: bei %(tn)d Teilnehmern werden mind. %(req)d '
                'Gruppenleitungen empfohlen (1 je %(ratio)d TN), angegeben sind %(have)d.'
            ) % {'tn': self.tn_count, 'req': required_leaders, 'ratio': ratio, 'have': self.tn_leader_count})
        # Juleica.
        if self.tn_leader_count and self.tn_leader_juleica < self.tn_leader_count:
            warnings.append(_(
                'Nicht alle Gruppenleitungen haben eine Juleica (%(j)d von %(l)d). Für den '
                'Juleica-Zuschlag ist eine gültige Juleica erforderlich.'
            ) % {'j': self.tn_leader_juleica, 'l': self.tn_leader_count})
        # Dauer.
        if t.min_days and self.measure_days and self.measure_days < t.min_days:
            warnings.append(_('Die Maßnahme ist kürzer als die Mindestdauer von %d Tagen.') % t.min_days)
        if t.max_days and self.measure_days and self.measure_days > t.max_days:
            warnings.append(_('Die Maßnahme überschreitet die Höchstdauer von %d Tagen.') % t.max_days)
        # Alter (nur wenn Grenzen gesetzt und das Alter erfasst ist).
        # Maßgeblich ist das Feld 'age': es wird in der Teilnahmeliste direkt eingegeben
        # und nur dann aus dem Geburtsdatum berechnet, wenn eines hinterlegt ist.
        # Gruppenleitungen sind von der Teilnehmer-Altersgrenze ausgenommen (KJR-OA: für
        # Gruppenleitungen besteht keine Altersgrenze) und werden hier nicht gezählt.
        if (t.min_age or t.max_age) and self.participant_ids:
            out = 0
            for p in self.participant_ids:
                if p.is_leader:
                    continue
                if not p.age and not p.birthdate:
                    continue
                if t.min_age and p.age < t.min_age:
                    out += 1
                elif t.max_age and p.age > t.max_age:
                    out += 1
            if out:
                warnings.append(_(
                    '%(n)d Teilnehmer (ohne Gruppenleitungen) liegen außerhalb des förderfähigen '
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
                # message_post escapt einfache Zeichenketten – ohne Markup stünden
                # <b>/<br/> als Text im Chatter und in der Benachrichtigungs-Mail.
                # Die eingesetzten Werte werden von Markup.__mod__ weiterhin escaped.
                body=markupsafe.Markup(_(
                    'Antrag <b>%(name)s</b> wurde bewilligt.<br/>'
                    'Bewilligter Betrag: <b>%(amount).2f €</b>'
                )) % {'name': self.name, 'amount': self.grant_approved},
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
