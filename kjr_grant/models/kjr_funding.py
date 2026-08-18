# -*- coding: utf-8 -*-
"""Fördermittel-Akquise — KJR-eigene Anträge an BJR/BezJR/Ministerium."""
import base64
import csv
import io
import re
from datetime import date, datetime, timedelta

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

# Datumsfeld, nach dem der Abrechnungszeitraum des BezJR-Exports abgegrenzt wird.
# Die Zuordnung steht hier zentral, damit Domain-Aufbau und Spaltenbeschriftung
# nicht auseinanderlaufen können.
BEZJR_DATE_BASIS_FIELDS = {
    'start': 'measure_start',
    'end': 'measure_end',
    'approved': 'date_approved',
    'paid': 'date_paid',
}

# Umlaute für den Dateinamen (der Download-Pfad soll ASCII bleiben).
_FILENAME_TRANSLATION = str.maketrans({
    'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue', 'ß': 'ss',
})


class KjrFunding(models.Model):
    _name = 'kjr.funding'
    _description = 'KJR Fördermittel-Akquise'
    _order = 'deadline desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Förderprogramm', required=True, tracking=True)
    funder = fields.Selection([
        ('bjr', 'Bayerischer Jugendring (BJR)'),
        ('bezjr', 'Bezirksjugendring Schwaben'),
        ('stmas', 'Staatsministerium (StMAS)'),
        ('landkreis', 'Landkreis Oberallgäu'),
        ('bund', 'Bundesministerium (BMFSFJ)'),
        ('eu', 'EU-Förderprogramm'),
        ('stiftung', 'Stiftung'),
        ('other', 'Sonstige'),
    ], string='Fördergeber', required=True, tracking=True)
    funder_name = fields.Char(string='Name Fördergeber')
    amount_requested = fields.Float(string='Beantragt (€)', digits=(10, 2), tracking=True)
    amount_approved = fields.Float(string='Bewilligt (€)', digits=(10, 2), tracking=True)
    deadline = fields.Date(string='Antragsfrist', tracking=True)
    project_name = fields.Char(string='Projektbezeichnung')
    project_description = fields.Text(string='Projektbeschreibung')
    project_start = fields.Date(string='Projektzeitraum von')
    project_end = fields.Date(string='Projektzeitraum bis')
    state = fields.Selection([
        ('draft', 'Entwurf'),
        ('submitted', 'Eingereicht'),
        ('approved', 'Bewilligt'),
        ('rejected', 'Abgelehnt'),
        ('running', 'Laufend'),
        ('closed', 'Abgeschlossen'),
    ], default='draft', tracking=True)
    responsible_id = fields.Many2one('res.users', string='Verantwortlich', tracking=True)
    note = fields.Text(string='Anmerkungen')
    verwendungsnachweis_deadline = fields.Date(string='Verwendungsnachweis bis')

    # ── Förderabrechnung Bezirksjugendring Schwaben (Exportparameter) ────────
    # Der KJR rechnet seine Mittel (u. a. AEJ und JBM) mit dem BezJR ab und baut
    # die Aufstellung der geförderten Maßnahmen bisher von Hand in Fremdvordrucke.
    # Die Parameter sind bewusst Felder am Förderprogramm und keine Eingaben in
    # einem Assistenten: die Abgrenzung („welche Förderarten gehören zu diesem
    # Programm?") ist je Programm stabil und soll für die nächste Abrechnung
    # erhalten bleiben.
    export_date_from = fields.Date(
        string='Abrechnung von', compute='_compute_export_period',
        store=True, readonly=False,
        help='Beginn des Abrechnungszeitraums. Vorbelegt mit dem Projektzeitraum, '
             'frei änderbar (z. B. für eine Zwischenabrechnung).',
    )
    export_date_to = fields.Date(
        string='Abrechnung bis', compute='_compute_export_period',
        store=True, readonly=False,
        help='Ende des Abrechnungszeitraums (einschließlich).',
    )
    export_date_basis = fields.Selection([
        ('start', 'Maßnahmenbeginn'),
        ('end', 'Maßnahmenende'),
        ('approved', 'Bewilligungsdatum'),
        ('paid', 'Auszahlungsdatum'),
    ], string='Zeitraum bezogen auf', default='start', required=True,
        help='Nach welchem Datum die Maßnahmen dem Abrechnungszeitraum zugeordnet '
             'werden. Vorbelegt mit dem Maßnahmenbeginn — gefördert wird die '
             'Maßnahme, nicht der Verwaltungsvorgang. Welche Abgrenzung der '
             'Bezirksjugendring erwartet, ist mit dem BezJR abzustimmen.')
    export_state = fields.Selection([
        ('approved_paid', 'Bewilligte und ausgezahlte Anträge'),
        ('paid', 'Nur ausgezahlte Anträge'),
        ('all', 'Alle eingereichten Anträge (auch noch in Prüfung)'),
    ], string='Berücksichtigte Anträge', default='approved_paid', required=True,
        help='Entwürfe und abgelehnte Anträge werden nie exportiert.')
    export_grant_type_ids = fields.Many2many(
        'kjr.grant.type',
        'kjr_funding_grant_type_rel', 'funding_id', 'grant_type_id',
        string='Berücksichtigte Förderarten',
        help='Leer = alle Förderarten. Eine Auswahl grenzt den Export auf die '
             'Maßnahmen ein, die über dieses Förderprogramm abgerechnet werden.',
    )
    export_analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Kostenstelle / Projekt',
        help='Optionaler Filter: nur Maßnahmen, deren Förderart auf diese '
             'Kostenstelle gebucht wird (Feld „Kostenstelle / Projekt" an der '
             'Förderart, das auch die Buchungen analytisch verteilt).',
    )
    funding_source_code = fields.Char(
        string='Kennzeichen Förderquelle',
        help='Bezeichnung oder Aktenzeichen, unter dem der Bezirksjugendring '
             'dieses Programm führt (z. B. die Kennung des Zuwendungsbescheids). '
             'Wird in der Spalte „Förderquelle" ausgegeben. Leer = es wird der '
             'Name des Förderprogramms ausgegeben.',
    )
    export_layout = fields.Selection([
        ('detail', 'Je Maßnahme (Detailzeilen)'),
        ('grant_type', 'Verdichtet je Förderart'),
    ], string='Gliederung', default='detail', required=True,
        help='„Je Maßnahme" liefert die zeilenweise Aufstellung, „Verdichtet je '
             'Förderart" die Summen für das Deckblatt.')
    export_file = fields.Binary(string='Abrechnung (CSV)', readonly=True, copy=False)
    export_filename = fields.Char(string='Dateiname', readonly=True, copy=False)
    export_date = fields.Datetime(string='Zuletzt erzeugt am', readonly=True, copy=False)
    export_line_count = fields.Integer(
        string='Ausgegebene Zeilen', readonly=True, copy=False,
        help='Anzahl der Datenzeilen der zuletzt erzeugten Abrechnung (ohne '
             'Kopf- und Summenzeile).',
    )

    # ── Workflow ─────────────────────────────────────────────────────────────
    def action_submit(self):
        self.write({'state': 'submitted'})

    def action_approve(self):
        self.write({'state': 'approved'})

    def action_reject(self):
        self.write({'state': 'rejected'})

    def action_start(self):
        self.write({'state': 'running'})

    def action_close(self):
        self.write({'state': 'closed'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    # ── Fristen-Erinnerung ───────────────────────────────────────────────────
    @api.model
    def _cron_funding_deadline_reminder(self):
        """Erinnerung an Antrags- und Verwendungsnachweis-Fristen der Fördermittel
        (28 Tage vorher). Deckt den Wunsch des KJR nach automatischer Fristenüberwachung."""
        today = fields.Date.today()
        horizon = today + timedelta(days=28)
        # Antragsfristen offener (noch nicht eingereichter) Programme
        for rec in self.search([
            ('state', 'in', ('draft', 'submitted')),
            ('deadline', '>=', today), ('deadline', '<=', horizon),
        ]):
            if any(a.summary and 'Antragsfrist' in a.summary for a in rec.activity_ids):
                continue
            rec.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=rec.deadline,
                user_id=(rec.responsible_id or self.env.user).id,
                summary=_('Antragsfrist Fördermittel: %s') % rec.name,
                note=_('Die Antragsfrist für "%s" (%s) endet am %s.') % (
                    rec.name, dict(self._fields['funder'].selection).get(rec.funder, ''),
                    rec.deadline.strftime('%d.%m.%Y')),
            )
        # Verwendungsnachweis-Fristen laufender/bewilligter Programme
        for rec in self.search([
            ('state', 'in', ('approved', 'running')),
            ('verwendungsnachweis_deadline', '>=', today),
            ('verwendungsnachweis_deadline', '<=', horizon),
        ]):
            if any(a.summary and 'Verwendungsnachweis' in a.summary for a in rec.activity_ids):
                continue
            rec.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=rec.verwendungsnachweis_deadline,
                user_id=(rec.responsible_id or self.env.user).id,
                summary=_('Verwendungsnachweis fällig: %s') % rec.name,
                note=_('Der Verwendungsnachweis für "%s" ist bis %s einzureichen.') % (
                    rec.name, rec.verwendungsnachweis_deadline.strftime('%d.%m.%Y')),
            )

    # ══════════════════════════════════════════════════════════════════════════
    # FÖRDERABRECHNUNG BEZIRKSJUGENDRING SCHWABEN (CSV-EXPORT)
    # ══════════════════════════════════════════════════════════════════════════
    # Der KJR rechnet seine Fördermittel (u. a. AEJ und JBM) mit dem
    # Bezirksjugendring Schwaben ab. Bisher wird die Aufstellung der geförderten
    # Maßnahmen von Hand in Fremdvordrucke übertragen.
    #
    # TODO(KJR): Der jeweils gültige BezJR-Vordruck liegt diesem Modul NICHT vor.
    # Die Spalten unten sind eine nachvollziehbare, sprechend benannte Aufstellung
    # aus den Daten, die dieses Modul tatsächlich führt — sie sind KEINE
    # Nachbildung eines amtlichen Formulars. Vor dem ersten Echteinsatz ist die
    # Spaltenfolge mit dem Bezirksjugendring abzugleichen (Reihenfolge,
    # Bezeichnungen, geforderte Kennziffern, Summenbildung). Kennziffern und
    # Formatvorgaben werden hier bewusst nicht erfunden; für ein vom BezJR
    # vergebenes Kennzeichen gibt es das pflegbare Feld „Kennzeichen Förderquelle".
    #
    # Bewusste Festlegungen (wie beim Statistik-Export in kjr_event):
    # * CSV statt XLSX — xlsxwriter ist keine garantierte Abhängigkeit.
    # * Trennzeichen Semikolon, UTF-8 MIT BOM ("utf-8-sig"), damit Excel unter
    #   Windows die Umlaute korrekt anzeigt. Die Datei geht an eine Behörde.
    # * Beträge mit deutschem Dezimalkomma.

    @api.depends('project_start', 'project_end')
    def _compute_export_period(self):
        """Belegt den Abrechnungszeitraum mit dem Projektzeitraum vor.

        store=True/readonly=False: der Wert ist nur ein Vorschlag und bleibt frei
        überschreibbar (z. B. für eine Zwischenabrechnung). Achtung — dokumentiertes
        Verhalten dieser Feldart: wird der Projektzeitraum später geändert, rechnet
        Odoo den Vorschlag neu und überschreibt eine manuelle Eingabe.

        Ohne Projektzeitraum wird das laufende Kalenderjahr vorgeschlagen. Das ist
        eine reine Bedienhilfe (Haushaltsjahr) und keine Aussage über Fristen.
        """
        today = fields.Date.context_today(self)
        for rec in self:
            rec.export_date_from = rec.project_start or date(today.year, 1, 1)
            rec.export_date_to = rec.project_end or date(today.year, 12, 31)

    @api.constrains('export_date_from', 'export_date_to')
    def _check_export_period(self):
        for rec in self:
            if rec.export_date_from and rec.export_date_to and rec.export_date_from > rec.export_date_to:
                raise ValidationError(_(
                    'Bei „%(name)s" liegt „Abrechnung von" nach „Abrechnung bis".',
                    name=rec.name or '',
                ))

    # ── Hilfsfunktionen Formatierung ─────────────────────────────────────────
    @api.model
    def _fmt_date(self, value):
        """Datum als deutsches Datum. Nimmt date, datetime und ISO-String an."""
        if not value:
            return ''
        if isinstance(value, str):
            value = fields.Date.to_date(value)
        if isinstance(value, datetime):
            value = value.date()
        return value.strftime('%d.%m.%Y')

    @api.model
    def _fmt_amount(self, value):
        """Betrag mit deutschem Dezimalkomma (Excel-tauglich in DE-Umgebung)."""
        return ('%.2f' % (value or 0.0)).replace('.', ',')

    # ── Auswahl der Maßnahmen ────────────────────────────────────────────────
    def _bezjr_date_field(self):
        """Datumsfeld der Zeitraumabgrenzung laut „Zeitraum bezogen auf"."""
        self.ensure_one()
        return BEZJR_DATE_BASIS_FIELDS[self.export_date_basis or 'start']

    def _bezjr_domain(self):
        """Domain der zu exportierenden Zuschussanträge (= geförderte Maßnahmen).

        Entwürfe und abgelehnte Anträge bleiben in jeder Variante außen vor: sie
        sind keine geförderten Maßnahmen und haben in einer Abrechnung gegenüber
        dem Fördergeber nichts verloren.
        """
        self.ensure_one()
        date_field = self._bezjr_date_field()
        domain = [
            (date_field, '>=', self.export_date_from),
            (date_field, '<=', self.export_date_to),
        ]
        if self.export_state == 'paid':
            domain.append(('state', '=', 'paid'))
        elif self.export_state == 'all':
            domain.append(('state', 'in', ('submitted', 'in_review', 'approved', 'paid')))
        else:
            domain.append(('state', 'in', ('approved', 'paid')))
        if self.export_grant_type_ids:
            domain.append(('grant_type_id', 'in', self.export_grant_type_ids.ids))
        if self.export_analytic_account_id:
            domain.append(
                ('grant_type_id.analytic_account_id', '=', self.export_analytic_account_id.id))
        return domain

    def _bezjr_source_label(self):
        """Inhalt der Spalte „Förderquelle"."""
        self.ensure_one()
        return self.funding_source_code or self.name or ''

    def _bezjr_grant_type_info(self, grant_types):
        """Bezeichnung, Code-Label und Kostenstelle je Förderart — gebündelt gelesen.

        :param grant_types: Recordset kjr.grant.type
        :return: dict {id: (Bezeichnung, Code-Label, Kostenstelle)}
        """
        code_labels = dict(
            self.env['kjr.grant.type']._fields['code']._description_selection(self.env))
        # Ein browse + Feldzugriff lädt alle Datensätze gebündelt (kein N+1).
        grant_types.mapped('analytic_account_id').mapped('display_name')
        return {
            gt.id: (
                gt.name or '',
                code_labels.get(gt.code, gt.code or ''),
                gt.analytic_account_id.display_name or '' if gt.analytic_account_id else '',
            )
            for gt in grant_types
        }

    def _bezjr_no_data_error(self):
        """Verständliche Meldung statt einer leeren Datei."""
        self.ensure_one()
        basis_labels = dict(self._fields['export_date_basis']._description_selection(self.env))
        state_labels = dict(self._fields['export_state']._description_selection(self.env))
        hints = []
        if self.export_grant_type_ids:
            hints.append(_('Förderarten: %s') % ', '.join(
                self.export_grant_type_ids.mapped('name')))
        if self.export_analytic_account_id:
            hints.append(_('Kostenstelle: %s') % self.export_analytic_account_id.display_name)
        filter_info = ('\n' + _('Gesetzte Filter: %s') % '; '.join(hints)) if hints else ''
        return UserError(_(
            'Für den Zeitraum %(start)s bis %(end)s wurden keine geförderten '
            'Maßnahmen gefunden.\n'
            'Zeitraum bezogen auf: %(basis)s\n'
            'Berücksichtigte Anträge: %(states)s%(filters)s\n\n'
            'Bitte Zeitraum, Bezugsdatum und Filter prüfen. Hinweis: Entwürfe und '
            'abgelehnte Anträge werden nie exportiert.',
            start=self._fmt_date(self.export_date_from),
            end=self._fmt_date(self.export_date_to),
            basis=basis_labels.get(self.export_date_basis, ''),
            states=state_labels.get(self.export_state, ''),
            filters=filter_info,
        ))

    # ── Detailaufstellung: je Maßnahme eine Zeile ────────────────────────────
    def _bezjr_detail_header(self):
        return [
            'Lfd. Nr.', 'Antragsnummer', 'KJR-Aktenzeichen',
            'Träger / Antragsteller', 'PLZ Träger', 'Ort Träger',
            'Maßnahme', 'Förderart', 'Förderart-Code',
            'Beginn', 'Ende', 'Förderfähige Tage',
            'PLZ Maßnahmenort', 'Ort der Maßnahme',
            'Teilnehmer gesamt', 'davon Gruppenleitung',
            'davon Gruppenleitung mit Juleica', 'davon auswärtige Teilnehmer',
            'Förderfähige Gesamtkosten (€)', 'Gesamteinnahmen (€)', 'Fehlbetrag (€)',
            'Berechneter Zuschuss (€)', 'Bewilligter Zuschuss (€)',
            'Zuschuss BJR/BezJR laut Antrag (€)',
            'Status', 'Bewilligt am', 'Ausgezahlt am',
            'Förderquelle', 'Kostenstelle / Projekt',
        ]

    def _bezjr_detail_rows(self):
        """Detailzeilen mit wenigen gebündelten Abfragen (kein Zugriff je Zeile).

        search_read liefert alle Antragsfelder in EINER Abfrage; Träger und
        Förderarten werden anschließend gebündelt nachgeladen.
        """
        self.ensure_one()
        Application = self.env['kjr.grant.application']
        records = Application.search_read(
            self._bezjr_domain(),
            [
                'name', 'reference_number', 'partner_id', 'measure_name',
                'grant_type_id', 'measure_start', 'measure_end', 'measure_days',
                'measure_zip', 'measure_location', 'tn_count', 'tn_leader_count',
                'tn_leader_juleica', 'tn_external_count', 'cost_total',
                'income_total', 'income_bjr', 'deficit', 'grant_calculated',
                'grant_approved', 'state', 'date_approved', 'date_paid',
            ],
            order='measure_start, id',
        )
        if not records:
            return []

        partner_ids = {r['partner_id'][0] for r in records if r['partner_id']}
        partners = {
            p['id']: p
            for p in self.env['res.partner'].browse(sorted(partner_ids)).read(
                ['display_name', 'zip', 'city'])
        }
        type_ids = {r['grant_type_id'][0] for r in records if r['grant_type_id']}
        type_info = self._bezjr_grant_type_info(
            self.env['kjr.grant.type'].browse(sorted(type_ids)))
        state_labels = dict(
            Application._fields['state']._description_selection(self.env))
        source = self._bezjr_source_label()

        totals = dict.fromkeys((
            'measure_days', 'tn_count', 'tn_leader_count', 'tn_leader_juleica',
            'tn_external_count', 'cost_total', 'income_total', 'deficit',
            'grant_calculated', 'grant_approved', 'income_bjr',
        ), 0)
        rows = []
        for index, rec in enumerate(records, start=1):
            partner = partners.get(rec['partner_id'][0], {}) if rec['partner_id'] else {}
            type_name, type_code, analytic = type_info.get(
                rec['grant_type_id'][0] if rec['grant_type_id'] else 0, ('', '', ''))
            for key in totals:
                totals[key] += rec.get(key) or 0
            rows.append([
                index,
                rec['name'] or '',
                rec['reference_number'] or '',
                partner.get('display_name') or '',
                partner.get('zip') or '',
                partner.get('city') or '',
                rec['measure_name'] or '',
                type_name,
                type_code,
                self._fmt_date(rec['measure_start']),
                self._fmt_date(rec['measure_end']),
                rec['measure_days'] or 0,
                rec['measure_zip'] or '',
                rec['measure_location'] or '',
                rec['tn_count'] or 0,
                rec['tn_leader_count'] or 0,
                rec['tn_leader_juleica'] or 0,
                rec['tn_external_count'] or 0,
                self._fmt_amount(rec['cost_total']),
                self._fmt_amount(rec['income_total']),
                self._fmt_amount(rec['deficit']),
                self._fmt_amount(rec['grant_calculated']),
                self._fmt_amount(rec['grant_approved']),
                self._fmt_amount(rec['income_bjr']),
                state_labels.get(rec['state'], rec['state'] or ''),
                self._fmt_date(rec['date_approved']),
                self._fmt_date(rec['date_paid']),
                source,
                analytic,
            ])
        summary = (
            ['SUMME'] + [''] * 10
            + [totals['measure_days'], '', '']
            + [
                totals['tn_count'], totals['tn_leader_count'],
                totals['tn_leader_juleica'], totals['tn_external_count'],
                self._fmt_amount(totals['cost_total']),
                self._fmt_amount(totals['income_total']),
                self._fmt_amount(totals['deficit']),
                self._fmt_amount(totals['grant_calculated']),
                self._fmt_amount(totals['grant_approved']),
                self._fmt_amount(totals['income_bjr']),
            ]
            + [''] * 5
        )
        return [self._bezjr_detail_header()] + rows + [summary]

    # ── Verdichtete Aufstellung: je Förderart eine Zeile ─────────────────────
    def _bezjr_summary_header(self):
        return [
            'Förderart', 'Förderart-Code', 'Anzahl Maßnahmen',
            'Förderfähige Tage gesamt', 'Teilnehmer gesamt', 'davon Gruppenleitung',
            'Förderfähige Gesamtkosten (€)', 'Gesamteinnahmen (€)', 'Fehlbetrag (€)',
            'Berechneter Zuschuss (€)', 'Bewilligter Zuschuss (€)',
            'Förderquelle', 'Kostenstelle / Projekt',
        ]

    def _bezjr_summary_rows(self):
        """Summen je Förderart — vollständig in der Datenbank aggregiert."""
        self.ensure_one()
        groups = self.env['kjr.grant.application']._read_group(
            self._bezjr_domain(),
            groupby=['grant_type_id'],
            aggregates=[
                '__count', 'measure_days:sum', 'tn_count:sum', 'tn_leader_count:sum',
                'cost_total:sum', 'income_total:sum', 'deficit:sum',
                'grant_calculated:sum', 'grant_approved:sum',
            ],
        )
        if not groups:
            return []
        type_info = self._bezjr_grant_type_info(
            self.env['kjr.grant.type'].browse([gt.id for gt, *_rest in groups if gt]))
        source = self._bezjr_source_label()

        totals = [0] * 9
        rows = []
        for grant_type, *values in groups:
            for idx, value in enumerate(values):
                totals[idx] += value or 0
            name, code, analytic = type_info.get(
                grant_type.id if grant_type else 0, (_('Ohne Förderart'), '', ''))
            (count, days, tn, leaders, costs, income,
             deficit, calculated, approved) = values
            rows.append([
                name, code, count, days or 0, tn or 0, leaders or 0,
                self._fmt_amount(costs), self._fmt_amount(income),
                self._fmt_amount(deficit), self._fmt_amount(calculated),
                self._fmt_amount(approved), source, analytic,
            ])
        summary = [
            'SUMME', '', totals[0], totals[1], totals[2], totals[3],
            self._fmt_amount(totals[4]), self._fmt_amount(totals[5]),
            self._fmt_amount(totals[6]), self._fmt_amount(totals[7]),
            self._fmt_amount(totals[8]), '', '',
        ]
        return [self._bezjr_summary_header()] + rows + [summary]

    # ── Dateiaufbau und Aktion ───────────────────────────────────────────────
    def _bezjr_filename(self):
        self.ensure_one()
        slug = re.sub(r'[^A-Za-z0-9]+', '_',
                      (self.name or 'Foerderprogramm').translate(_FILENAME_TRANSLATION)).strip('_')
        return 'KJR_Foerderabrechnung_BezJR_%s_%s_%s.csv' % (
            slug or 'Foerderprogramm',
            self.export_date_from.strftime('%Y-%m-%d'),
            self.export_date_to.strftime('%Y-%m-%d'),
        )

    def action_export_bezjr(self):
        """Erzeugt die Förderabrechnung als CSV und gibt sie zum Download aus."""
        self.ensure_one()
        if not self.export_date_from or not self.export_date_to:
            raise UserError(_(
                'Bitte zuerst den Abrechnungszeitraum („Abrechnung von" und '
                '„Abrechnung bis") ausfüllen.'))
        # Die Abrechnung wird am Förderprogramm gespeichert. Ohne Schreibrecht
        # (Sachbearbeitung hat auf Fördermittel nur Leserecht) würde der Odoo-Kern
        # eine technische Zugriffsmeldung werfen — hier lieber ein klarer Hinweis.
        if not self.has_access('write'):
            raise UserError(_(
                'Zum Erzeugen der Förderabrechnung wird Schreibrecht auf das '
                'Förderprogramm benötigt (Gruppe „KJR Administrator"). Bitte an '
                'die Geschäftsstellenleitung wenden.'))

        if self.export_layout == 'grant_type':
            rows = self._bezjr_summary_rows()
        else:
            rows = self._bezjr_detail_rows()
        if not rows:
            raise self._bezjr_no_data_error()
        width = len(rows[0])
        if any(len(row) != width for row in rows):
            raise UserError(_(
                'Die Abrechnung konnte nicht erzeugt werden: Kopfzeile und '
                'Datenzeilen haben unterschiedlich viele Spalten. Bitte die '
                'KLGM UG informieren.'))

        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=';', quotechar='"',
                            quoting=csv.QUOTE_MINIMAL, lineterminator='\r\n')
        writer.writerows(rows)
        # UTF-8 MIT BOM: nur so erkennt Excel unter Windows die Kodierung und
        # stellt die Umlaute korrekt dar. Die Datei geht an eine Behörde.
        content = buffer.getvalue().encode('utf-8-sig')
        buffer.close()

        filename = self._bezjr_filename()
        line_count = len(rows) - 2  # ohne Kopf- und Summenzeile
        self.write({
            'export_file': base64.b64encode(content),
            'export_filename': filename,
            'export_date': fields.Datetime.now(),
            'export_line_count': line_count,
        })
        self.message_post(
            body=Markup('<p>%s</p>') % _(
                'Förderabrechnung erzeugt: %(file)s (%(lines)s Zeilen, Zeitraum '
                '%(start)s bis %(end)s).',
                file=filename, lines=line_count,
                start=self._fmt_date(self.export_date_from),
                end=self._fmt_date(self.export_date_to),
            ),
            subtype_xmlid='mail.mt_note',
        )
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/kjr.funding/%s/export_file/%s?download=true' % (
                self.id, filename),
            'target': 'download',
        }
