# -*- coding: utf-8 -*-
"""
Konfigurierbare Förderarten. Alle Parameter im Backend änderbar ohne Code-Eingriff.
Quelle: Zuschussrichtlinien KJR Oberallgäu, gültig ab 01.12.2022 (Fassung 2026).
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class KjrGrantType(models.Model):
    _name = 'kjr.grant.type'
    _description = 'KJR Förderart'
    _order = 'sequence, name'
    _rec_name = 'name'

    # ── Basisfelder ──────────────────────────────────────────────────────────
    name = fields.Char(string='Bezeichnung', required=True)
    code = fields.Selection([
        ('4_1a', '§ 4.1a Freizeitmaßnahme eintägig'),
        ('4_1b', '§ 4.1b Freizeitmaßnahme mehrtägig'),
        ('4_2',  '§ 4.2  Verbandsspezifische Maßnahme'),
        ('4_3',  '§ 4.3  Außerschulische Jugendbildung'),
        ('4_4',  '§ 4.4  Jugendleiterschulung'),
        ('4_5',  '§ 4.5  Internationale Jugendarbeit'),
        ('4_6',  '§ 4.6  Geräte & Materialien'),
        ('4_7',  '§ 4.7  Gruppenstarthilfe'),
        ('4_8a', '§ 4.8a Großveranstaltung (>100 TN)'),
        ('4_8b', '§ 4.8b Traditionelle Veranstaltung'),
        ('4_8c', '§ 4.8c Schwerpunktprojekt'),
        ('4_9',  '§ 4.9  Delegiertenförderung (Fahrtkosten)'),
    ], string='Code', required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(
        string='Beschreibung für Antragsteller',
        help='Wird im Portal bei Auswahl dieser Förderart angezeigt.',
    )

    # ── Berechnungsparameter ─────────────────────────────────────────────────
    rate_per_tn_day = fields.Float(
        string='Tagessatz pro TN (€)', digits=(6, 2), default=0.0,
        help='TN × Tage × Tagessatz. Bei Pauschalen hier 0 lassen.',
    )
    rate_per_tn_single = fields.Float(
        string='Einzelsatz pro TN (€)', digits=(6, 2), default=0.0,
        help='Für Eintagesmaßnahmen ohne Tagesmultiplikation.',
    )
    juleica_bonus = fields.Boolean(
        string='Juleica-Bonus aktiv', default=False,
        help='Jugendleiter mit gültiger Juleica erhalten den Juleica-Zuschlag '
             '(KJR-OA: +50 %) auf ihren Tagessatz. Greift bei allen tagessatz-'
             'basierten Förderarten (§ 4.1b, 4.2, 4.3, 4.5).',
    )
    max_amount = fields.Float(
        string='Höchstfördersumme (€)', digits=(8, 2), required=True, default=0.0,
    )
    max_per_year = fields.Integer(
        string='Max. Anträge/Kalenderjahr', default=0,
        help='0 = unbegrenzt.',
    )
    year_limit_group = fields.Char(
        string='Jahreslimit-Gruppe',
        help='Förderarten mit derselben Gruppe teilen sich das Jahreslimit '
             '(max. Anträge/Kalenderjahr). KJR-OA: § 4.1 eintägig und mehrtägig '
             'zählen gemeinsam (max. 4 Freizeitmaßnahmen/Jahr). Leer = das Limit '
             'gilt nur für diese Förderart allein.',
    )
    max_cofinancing_pct = fields.Float(
        string='Max. Förderquote (%)', digits=(5, 1), default=50.0,
    )
    # ── Konfigurierbare Förderregeln (statt hartcodierter Werte) ─────────────
    juleica_uplift_pct = fields.Float(
        string='Juleica-Zuschlag auf Tagessatz (%)', digits=(5, 1), default=50.0,
        help='Erhöhung des Tagessatzes je Jugendleiter mit gültiger Juleica (KJR-OA: 50 %). '
             'Greift nur wenn "Juleica-Bonus aktiv".',
    )
    leader_ratio = fields.Integer(
        string='Teilnehmer je anerkanntem Jugendleiter', default=5,
        help='Es wird max. 1 geförderter Jugendleiter je N Teilnehmer anerkannt (KJR-OA: 5).',
    )
    max_external_pct = fields.Float(
        string='Max. Anteil auswärtiger TN (%)', digits=(5, 1), default=25.0,
        help='Teilnehmer sollen überwiegend aus dem Landkreis stammen (KJR-OA: max. 25 % auswärts). '
             '0 = keine Prüfung.',
    )
    min_age = fields.Integer(
        string='Mindestalter Teilnehmer', default=0, help='0 = keine Prüfung.',
    )
    max_age = fields.Integer(
        string='Höchstalter Teilnehmer', default=0, help='0 = keine Obergrenze.',
    )
    min_days = fields.Integer(
        string='Mindestdauer (Tage)', default=0, help='0 = keine Prüfung.',
    )
    max_days = fields.Integer(
        string='Maximaldauer (Tage)', default=0, help='0 = keine Obergrenze.',
    )
    # Referenten- und Sachkosten (§ 4.3 / § 4.6)
    referee_pct = fields.Float(string='Referentenkostenquote (%)', digits=(5, 1), default=0.0)
    referee_max = fields.Float(string='Referentenkosten max. (€)', digits=(8, 2), default=0.0)
    material_pct = fields.Float(string='Sachkostenquote (%)', digits=(5, 1), default=0.0)
    material_max = fields.Float(string='Sachkosten max. (€)', digits=(8, 2), default=0.0)
    # Jugendleiterschulung (§ 4.4)
    jl_pct_no_juleica = fields.Float(string='JL-Schulung ohne Juleica (%)', digits=(5, 1), default=0.0)
    jl_max_no_juleica = fields.Float(string='JL-Schulung ohne Juleica max. (€)', digits=(8, 2), default=0.0)
    jl_pct_with_juleica = fields.Float(string='JL-Schulung mit Juleica (%)', digits=(5, 1), default=0.0)
    jl_max_with_juleica = fields.Float(string='JL-Schulung mit Juleica max. (€)', digits=(8, 2), default=0.0)
    allow_private_account = fields.Boolean(
        string='Auszahlung auf Privatkonto erlaubt', default=False,
        help='Nur § 4.4 Jugendleiterschulung.',
    )
    # Pflichtdokumente
    requires_tn_list = fields.Boolean(string='Teilnehmerliste Pflicht', default=True)
    requires_report = fields.Boolean(string='Bericht Pflicht', default=True)
    requires_receipt = fields.Boolean(string='Belegliste Pflicht', default=True)
    requires_other_docs = fields.Char(string='Weitere Pflichtdokumente')
    min_duration_hours = fields.Float(string='Min. Programmdauer/Tag (h)', default=4.0)
    min_participants = fields.Integer(string='Min. Teilnehmeranzahl', default=0)
    # Buchhaltung
    expense_account_id = fields.Many2one(
        'account.account', string='Aufwandskonto',
        help='Konto für Zuschuss-Aufwand (Soll bei Bewilligung).',
    )
    liability_account_id = fields.Many2one(
        'account.account', string='Verbindlichkeitskonto',
        help='Konto für Zuschuss-Verbindlichkeit (Haben bei Bewilligung).',
    )
    journal_id = fields.Many2one(
        'account.journal', string='Journal',
        help='Buchungsjournal für Zuschüsse dieser Förderart.',
        domain="[('type', '=', 'general')]",
    )
    interest_account_id = fields.Many2one(
        'account.account', string='Zinsertragskonto',
        help='Konto für Verzugszinsen bei Rückforderungen (optional).',
    )
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Kostenstelle / Projekt',
        help='Optionale analytische Zuordnung der Zuschussbuchungen (Förderquelle/Projekt).',
    )
    application_count = fields.Integer(
        string='Anträge gesamt', compute='_compute_application_count',
    )

    def _compute_application_count(self):
        data = self.env['kjr.grant.application']._read_group(
            [('grant_type_id', 'in', self.ids)],
            groupby=['grant_type_id'], aggregates=['__count'],
        )
        mapped = {gt.id: count for gt, count in data}
        for rec in self:
            rec.application_count = mapped.get(rec.id, 0)

    _code_unique = models.Constraint(
        'UNIQUE(code)',
        'Jeder Förderart-Code darf nur einmal vorkommen.',
    )

    @api.constrains('max_cofinancing_pct')
    def _check_cofinancing_pct(self):
        for rec in self:
            if not (0 < rec.max_cofinancing_pct <= 100):
                raise ValidationError(_('Die Förderquote muss zwischen 1 % und 100 % liegen.'))

    @api.constrains('leader_ratio')
    def _check_leader_ratio(self):
        for rec in self:
            if rec.leader_ratio < 1:
                raise ValidationError(_('Teilnehmer je Jugendleiter muss mindestens 1 sein.'))
