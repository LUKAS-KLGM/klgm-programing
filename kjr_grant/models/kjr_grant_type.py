# -*- coding: utf-8 -*-
"""
Konfigurierbare Förderarten. Alle Parameter im Backend änderbar ohne Code-Eingriff.
Quelle: Zuschussrichtlinien KJR Oberallgäu, gültig ab 01.12.2022 (Fassung 2026).
"""
from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import format_date


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
        ('invest', 'Investitionszuschuss (Landkreis-Programm, konfigurierbar)'),
    ], string='Code', required=True,
        help='Berechnungslogik je Förderart. „Investitionszuschuss" ist ein '
             'generischer, prozentbasierter Typ (Anteil der Investitionskosten, '
             'gedeckelt) – die konkreten Sätze des jeweiligen Landkreis-Programms '
             'werden über Förderquote/Höchstbetrag gepflegt.')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(
        string='Beschreibung für Antragsteller',
        help='Wird im Portal bei Auswahl dieser Förderart angezeigt.',
    )

    # ── Gültigkeit (Richtlinienfassung) ──────────────────────────────────────
    # Ändert der KJR seine Zuschussrichtlinie, wird die alte Fassung NICHT
    # überschrieben, sondern datiert abgegrenzt und daneben eine neue Fassung
    # angelegt. Nur so lässt sich in einer Verwendungsprüfung belegen, mit
    # welchen Sätzen ein Altantrag seinerzeit berechnet wurde.
    valid_from = fields.Date(
        string='Gültig ab',
        help='Erster Tag, an dem diese Fassung der Förderregel gilt. '
             'Leer = unbefristet gültig (kein Anfangsdatum).',
    )
    valid_to = fields.Date(
        string='Gültig bis',
        help='Letzter Tag, an dem diese Fassung der Förderregel gilt. '
             'Leer = unbefristet gültig (offenes Ende).',
    )
    rule_group = fields.Char(
        string='Regelgruppe',
        compute='_compute_rule_group', store=True, readonly=False,
        help='Fasst mehrere datierte Fassungen derselben Förderart zusammen. '
             'Innerhalb einer Regelgruppe darf zu jedem Stichtag nur eine '
             'Fassung gelten. Vorbelegt mit dem Förderart-Code, änderbar. '
             'Bitte nur mit Bedacht ändern: die Gruppe hält die Fassungen '
             'derselben Förderart zusammen. Ein nachträglicher Wechsel trennt '
             'zusammengehörige Fassungen voneinander und ist nur sinnvoll, wenn '
             'mehrere Codes bewusst dieselbe Regel teilen sollen.',
    )

    @api.depends('code')
    def _compute_rule_group(self):
        """Belegt die Regelgruppe mit dem Förderart-Code vor.

        store=True/readonly=False: der Wert ist nur ein Vorschlag und bleibt im
        Backend frei überschreibbar. Bereits gepflegte Gruppen werden deshalb
        nicht wieder überschrieben – auch nicht, wenn nachträglich der Code
        geändert wird. Der Compute sorgt zugleich dafür, dass der Altbestand
        beim Modul-Upgrade automatisch eine Gruppe erhält (kein Migrationsskript
        nötig).
        """
        for rec in self:
            rec.rule_group = rec.rule_group or rec.code or False

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
        help='Gruppenleitungen mit gültiger Juleica erhalten den Juleica-Zuschlag '
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
        help='Erhöhung des Tagessatzes je Gruppenleitung mit gültiger Juleica (KJR-OA: 50 %). '
             'Greift nur wenn "Juleica-Bonus aktiv".',
    )
    leader_ratio = fields.Integer(
        string='Teilnehmer je anerkannter Gruppenleitung', default=5,
        help='Es wird max. 1 geförderte Gruppenleitung je N Teilnehmer anerkannt (KJR-OA: 5).',
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

    # Achtung: Der Attributname bleibt bewusst `_code_unique` (SQL-Name
    # kjr_grant_type_code_unique). Da sich nur die Definition ändert, ersetzt
    # Odoo die alte UNIQUE(code)-Constraint beim Upgrade automatisch
    # (drop + recreate). Ein reines Umbenennen würde die alte Constraint u. U.
    # stehen lassen und jede zweite datierte Fassung blockieren.
    _code_unique = models.Constraint(
        'UNIQUE(code, valid_from)',
        'Je Förderart-Code darf es pro Gültigkeitsbeginn nur eine Fassung geben.',
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
                raise ValidationError(_('Teilnehmer je Gruppenleitung muss mindestens 1 sein.'))

    @api.constrains('valid_from', 'valid_to')
    def _check_validity_dates(self):
        for rec in self:
            if rec.valid_from and rec.valid_to and rec.valid_from > rec.valid_to:
                raise ValidationError(_(
                    'Bei „%(name)s" liegt „Gültig ab" nach „Gültig bis".',
                    name=rec.name or '',
                ))

    @api.constrains('code', 'rule_group', 'valid_from', 'valid_to', 'active')
    def _check_validity_overlap(self):
        """Zu jedem Stichtag darf nur eine Fassung gelten – je Regelgruppe UND je Code.

        Warum beide Kriterien (Variante A der Prüfung):
        `rule_group` ist ein Compute mit store=True/readonly=False und damit im
        Backend frei änderbar, `find_for_date()` sucht dagegen auf `code`. Würde
        der Überschneidungsschutz nur auf die Regelgruppe schauen, ließen sich
        zwei überlappende Fassungen desselben Codes anlegen, indem man bei einer
        von beiden die Regelgruppe umstellt. Die SQL-Constraint
        UNIQUE(code, valid_from) greift dann ebenfalls nicht, weil sich die
        Anfangsdaten unterscheiden – `find_for_date()` fände aber weiterhin beide
        Fassungen und wählte still die mit dem späteren „Gültig ab". Eine
        falsch berechnete Förderung fiele niemandem auf.

        Deshalb wird zusätzlich auf `code` geprüft: der Constraint deckt damit
        genau das Kriterium mit ab, nach dem find_for_date() tatsächlich sucht.
        Bewusst NICHT gewählt: find_for_date() auf rule_group umstellen (ändert
        die Semantik für alle Aufrufer) oder rule_group readonly machen (nähme
        der Geschäftsstelle die Möglichkeit, mehrere Codes bewusst zu einer
        Regelgruppe zusammenzufassen).

        Archivierte Fassungen bleiben außen vor: sie werden auch von
        find_for_date() ignoriert und können daher nicht kollidieren.
        """
        for rec in self:
            if not rec.active:
                continue
            group = rec.rule_group or rec.code
            if not group and not rec.code:
                continue
            # Kollisionskandidaten: gleiche Regelgruppe ODER gleicher Code.
            # search() blendet archivierte Sätze standardmäßig aus – gewollt.
            domain = [('id', '!=', rec.id)]
            criteria = []
            if group:
                criteria.append(('rule_group', '=', group))
            if rec.code:
                criteria.append(('code', '=', rec.code))
            if len(criteria) == 2:
                domain += ['|'] + criteria
            else:
                domain += criteria
            others = self.search(domain)
            for other in others:
                if not self._periods_overlap(
                    rec.valid_from, rec.valid_to, other.valid_from, other.valid_to,
                ):
                    continue
                if other.rule_group and group and other.rule_group == group:
                    reason = _(
                        'In der Regelgruppe „%(group)s" darf zu jedem Stichtag '
                        'nur eine Fassung gelten.',
                        group=group,
                    )
                else:
                    # Lesbare Selection-Bezeichnung statt des technischen Keys.
                    code_label = dict(
                        self._fields['code']._description_selection(self.env)
                    ).get(rec.code, rec.code or '')
                    reason = _(
                        'Beide Fassungen tragen den Förderart-Code „%(code)s". '
                        'Auch bei unterschiedlicher Regelgruppe darf zu jedem '
                        'Stichtag nur eine Fassung je Code gelten – sonst wählt '
                        'die Berechnung stillschweigend eine der beiden aus.',
                        code=code_label,
                    )
                raise ValidationError(_(
                    'Die Gültigkeitszeiträume überschneiden sich:\n'
                    '• %(first_name)s (%(first_period)s)\n'
                    '• %(second_name)s (%(second_period)s)\n\n'
                    '%(reason)s Grenzen Sie die ältere Fassung mit '
                    '„Gültig bis" ab.',
                    first_name=rec.name or '',
                    first_period=rec._validity_label(),
                    second_name=other.name or '',
                    second_period=other._validity_label(),
                    reason=reason,
                ))

    @staticmethod
    def _periods_overlap(from_a, to_a, from_b, to_b):
        """True, wenn sich zwei Zeiträume berühren. Leere Grenzen = offenes Ende."""
        if from_a and to_b and from_a > to_b:
            return False
        if from_b and to_a and from_b > to_a:
            return False
        return True

    def _validity_label(self):
        """Lesbarer Gültigkeitszeitraum für Meldungen, z. B. „ab 01.01.2026"."""
        self.ensure_one()
        start = format_date(self.env, self.valid_from) if self.valid_from else False
        end = format_date(self.env, self.valid_to) if self.valid_to else False
        if start and end:
            return _('%(start)s bis %(end)s', start=start, end=end)
        if start:
            return _('ab %(start)s', start=start)
        if end:
            return _('bis %(end)s', end=end)
        return _('unbefristet')

    # ── API für die Berechnung ───────────────────────────────────────────────
    # TODO (Bora, Kassenleitung): Welcher Stichtag ist maßgeblich – Beginn der
    # Maßnahme oder Eingang des Antrags? Die Methode nimmt den Stichtag bewusst
    # als Parameter entgegen, die Festlegung trifft der Aufrufer. Konservative
    # Erwartung bis zur Klärung: Maßnahmenbeginn (measure_start), weil die
    # Richtlinie die Maßnahme fördert, nicht den Verwaltungsvorgang.
    @api.model
    def find_for_date(self, code, date_ref=None):
        """Liefert die zum Stichtag gültige Fassung einer Förderart.

        Auswahlreihenfolge:
          a) aktive Fassung mit passendem Code, deren datierter Zeitraum den
             Stichtag enthält (offene Grenzen zählen als unbegrenzt);
          b) sonst die aktive Fassung mit passendem Code ganz ohne
             Datumsgrenzen;
          c) sonst ein leeres Recordset.

        Schritt b) ist die Rückwärtskompatibilität: der gesamte Altbestand
        (und alles, was die Geschäftsstelle künftig ohne Datumspflege anlegt)
        hat weder „Gültig ab" noch „Gültig bis". Ohne diesen Fallback fände die
        Berechnung für Bestandsanträge plötzlich gar keine Förderart mehr und
        würde 0 € ergeben. Datierte Fassungen haben deshalb Vorrang, undatierte
        greifen nur, wenn keine datierte passt.

        Dass zu einem Stichtag höchstens eine Fassung je Code passt, sichert
        _check_validity_overlap() ab (prüft je Regelgruppe UND je Code).

        :param code: Wert des Selection-Feldes `code`, z. B. '4_4'.
        :param date_ref: Stichtag (date oder ISO-String); None = heute.
        :return: Recordset mit 0 oder 1 Datensatz.
        """
        if not code:
            return self.browse()
        date_ref = fields.Date.to_date(date_ref) or fields.Date.today()

        # a) datierte Fassungen: mindestens eine Grenze gesetzt und passend.
        dated = self.search([
            ('code', '=', code),
            '|', ('valid_from', '=', False), ('valid_from', '<=', date_ref),
            '|', ('valid_to', '=', False), ('valid_to', '>=', date_ref),
            '|', ('valid_from', '!=', False), ('valid_to', '!=', False),
        ])
        if dated:
            # Bei mehreren Treffern gewinnt der späteste Beginn; fehlender
            # Beginn zählt dabei als „schon immer" und damit als ältester.
            # (Sortierung in Python, weil SQL NULLs bei DESC vorn einreiht.)
            return dated.sorted(
                key=lambda t: (t.valid_from or date.min, t.id), reverse=True,
            )[0]

        # b) Altbestand ohne jede Datumsgrenze.
        return self.search([
            ('code', '=', code),
            ('valid_from', '=', False),
            ('valid_to', '=', False),
        ], order='sequence, id', limit=1)
