# -*- coding: utf-8 -*-
"""Vierteljährlicher Auszahlungslauf für bewilligte Zuschussanträge.

Bisher wird jeder bewilligte Antrag einzeln zur Zahlung angewiesen. Die
Richtlinie sieht die Auszahlung quartalsweise vor; ein Jahresend-Stichtag
steuert, ob ein Antrag noch im laufenden Haushaltsjahr ausgezahlt wird.

Bewusste Festlegungen dieses Assistenten:

* Er erzeugt KEINE eigene Buchung und schreibt KEINE Bearbeitungsvermerke.
  Die Zahlungsanweisung erfolgt ausschließlich über die vorhandene
  Workflow-Action ``kjr.grant.application.action_order_payment()``. Nur sie
  kennt die prozessinterne Freigabe (``_workflow_write()`` /
  ``_WORKFLOW_WRITE_ALLOWED``) und nur sie darf die Vermerke setzen.

* Das Vier-Augen-Prinzip wird durch den Massenlauf NICHT aufgeweicht.
  Anträge, die die auslösende Person selbst sachlich geprüft hat, werden
  übersprungen und im Ergebnisbericht mit Begründung aufgeführt – der Lauf
  bricht deswegen nicht ab, sonst wäre er in einer kleinen Geschäftsstelle
  praktisch nicht benutzbar.

* Der Stichtag ist NICHT im Code hinterlegt, sondern wird aus den
  Systemparametern ``kjr_grant.payout_cutoff_day`` /
  ``kjr_grant.payout_cutoff_month`` gelesen (dieselben Parameter, aus denen
  auch ``kjr.grant.application.payout_year`` gebildet wird). Ist dort nichts
  gepflegt, wird die Stichtagsregel NICHT angewendet und der Assistent sagt
  das ausdrücklich – ein Datum wird nicht angenommen.

* Der Assistent ist ein TransientModel: das Ergebnis wird im Formular
  angezeigt und zusätzlich in das Serverprotokoll sowie in den Chatter der
  angewiesenen Anträge geschrieben (Nachvollziehbarkeit für die
  Kassenprüfung). Ein dauerhaftes Objekt "Auszahlungslauf" ist bewusst nicht
  angelegt (siehe TODO(KJR) weiter unten).
"""
import logging
from datetime import date

import markupsafe

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)

# Quartalsgrenzen: Auswahlwert -> (Startmonat, Starttag, Endmonat, Endtag)
QUARTER_BOUNDS = {
    'q1': (1, 1, 3, 31),
    'q2': (4, 1, 6, 30),
    'q3': (7, 1, 9, 30),
    'q4': (10, 1, 12, 31),
    'year': (1, 1, 12, 31),
}


class KjrGrantPayoutRun(models.TransientModel):
    _name = 'kjr.grant.payout.run'
    _description = 'KJR – Auszahlungslauf (quartalsweise)'

    # ── Vorgabewerte ─────────────────────────────────────────────────────────

    @api.model
    def _default_fiscal_year(self):
        return fields.Date.context_today(self).year

    @api.model
    def _default_period_type(self):
        """Vorbelegt ist das Quartal, in dem der Lauf gestartet wird."""
        month = fields.Date.context_today(self).month
        return 'q%d' % ((month - 1) // 3 + 1)

    @api.model
    def _default_enforce_cutoff(self):
        """Vorbelegung der Stichtagsregel über einen Systemparameter.

        Default ist AUS: ob der Stichtag den Auszahlungslauf einschränken soll,
        ist eine fachliche Festlegung des KJR und darf nicht stillschweigend
        angenommen werden.

        TODO(KJR): Klären, ob der Jahresend-Stichtag den Quartalslauf
        verbindlich begrenzt (dann Systemparameter
        'kjr_grant.payout_run_enforce_cutoff' auf '1' setzen) oder ob er nur
        ein Hinweis für die Geschäftsstelle bleibt.
        """
        param = self.env['ir.config_parameter'].sudo().get_param(
            'kjr_grant.payout_run_enforce_cutoff', '')
        return str(param).strip().lower() in ('1', 'true', 'on', 'ja')

    # ── Abgrenzung des Laufs ─────────────────────────────────────────────────

    fiscal_year = fields.Integer(
        string='Haushaltsjahr', required=True, default=_default_fiscal_year,
        help='Haushaltsjahr, dem der Auszahlungslauf zugeordnet ist. Steuert die '
             'Quartalsgrenzen und – bei aktiver Stichtagsregel – welche Anträge '
             'noch in diesem Jahr zur Auszahlung gelangen.',
    )
    period_type = fields.Selection([
        ('q1', '1. Quartal (Januar–März)'),
        ('q2', '2. Quartal (April–Juni)'),
        ('q3', '3. Quartal (Juli–September)'),
        ('q4', '4. Quartal (Oktober–Dezember)'),
        ('year', 'Gesamtes Haushaltsjahr'),
        ('custom', 'Freier Zeitraum'),
    ], string='Zeitraum', required=True, default=_default_period_type,
        help='Quartal des Haushaltsjahres. "Freier Zeitraum" lässt Von/Bis frei '
             'einstellbar (Nachlauf, Sonderauszahlung).')
    date_from = fields.Date(
        string='Zeitraum von', required=True,
        compute='_compute_period', store=True, readonly=False,
        help='Erster Tag des Auswertungszeitraums (einschließlich).',
    )
    date_to = fields.Date(
        string='Zeitraum bis', required=True,
        compute='_compute_period', store=True, readonly=False,
        help='Letzter Tag des Auswertungszeitraums (einschließlich).',
    )
    period_basis = fields.Selection([
        ('date_approved', 'Datum der Bewilligung'),
        ('date_submitted', 'Datum des Antragseingangs'),
    ], string='Zeitraum bezieht sich auf', required=True, default='date_approved',
        help='Welches Datum des Antrags in den Zeitraum fallen muss. '
             'Vorbelegt ist die Bewilligung, weil erst danach angewiesen werden '
             'darf. Der Jahresend-Stichtag knüpft davon unabhängig immer am '
             'Antragseingang an.')

    grant_type_ids = fields.Many2many(
        'kjr.grant.type', 'kjr_payout_run_type_rel', 'run_id', 'type_id',
        string='Förderarten',
        help='Optional. Leer lassen = alle Förderarten.',
    )
    partner_ids = fields.Many2many(
        'res.partner', 'kjr_payout_run_partner_rel', 'run_id', 'partner_id',
        string='Mitgliedsverbände',
        domain="[('is_kjr_member', '=', True)]",
        help='Optional. Leer lassen = alle Verbände.',
    )

    enforce_cutoff = fields.Boolean(
        string='Jahresend-Stichtag anwenden', default=_default_enforce_cutoff,
        help='Ist die Regel aktiv, werden nur Anträge einbezogen, deren '
             'Auszahlungsjahr (abgeleitet aus dem Antragseingang und dem '
             'Stichtag) dem gewählten Haushaltsjahr entspricht. Der Stichtag '
             'selbst wird aus den Systemparametern gelesen und ist hier nicht '
             'fest hinterlegt.',
    )
    cutoff_info = fields.Char(
        string='Stichtag', compute='_compute_cutoff_info',
        help='Zeigt den aktuell gepflegten Jahresend-Stichtag.',
    )

    # ── Vorschau ─────────────────────────────────────────────────────────────

    application_ids = fields.Many2many(
        'kjr.grant.application', 'kjr_payout_run_app_rel', 'run_id', 'application_id',
        string='Einbezogene Anträge',
        compute='_compute_applications', store=True, readonly=False,
        help='Vorschau der Anträge, die dieser Lauf zur Zahlung anweist. '
             'Einzelne Anträge können vor dem Lauf entfernt werden; eine '
             'Änderung der Abgrenzung oben stellt die Vorschau neu zusammen.',
    )
    application_count = fields.Integer(
        string='Anzahl Anträge', compute='_compute_totals',
    )
    amount_total = fields.Float(
        string='Auszahlungssumme (€)', compute='_compute_totals', digits=(12, 2),
    )
    blocked_ids = fields.Many2many(
        'kjr.grant.application', 'kjr_payout_run_blocked_rel', 'run_id', 'application_id',
        string='Nicht einbezogen', compute='_compute_blocked', readonly=True,
    )
    blocked_info = fields.Text(
        string='Warum nicht einbezogen?', compute='_compute_blocked', readonly=True,
    )

    # ── Ergebnis ─────────────────────────────────────────────────────────────

    state = fields.Selection([
        ('draft', 'Vorbereitung'),
        ('done', 'Ausgeführt'),
    ], string='Status', default='draft', required=True)
    ordered_ids = fields.Many2many(
        'kjr.grant.application', 'kjr_payout_run_done_rel', 'run_id', 'application_id',
        string='Angewiesene Anträge', readonly=True,
    )
    skipped_ids = fields.Many2many(
        'kjr.grant.application', 'kjr_payout_run_skipped_rel', 'run_id', 'application_id',
        string='Übersprungene Anträge', readonly=True,
    )
    ordered_count = fields.Integer(string='Angewiesen', readonly=True)
    skipped_count = fields.Integer(string='Übersprungen', readonly=True)
    ordered_amount = fields.Float(
        string='Angewiesene Summe (€)', digits=(12, 2), readonly=True,
    )
    result_text = fields.Text(string='Ergebnisbericht', readonly=True)

    # ══════════════════════════════════════════════════════════════════════════
    # COMPUTES / CONSTRAINTS
    # ══════════════════════════════════════════════════════════════════════════

    @api.depends('period_type', 'fiscal_year')
    def _compute_period(self):
        """Quartalsgrenzen aus Haushaltsjahr + Quartal.

        Stored compute: jeder Datensatz bekommt in JEDEM Zweig einen Wert –
        beim freien Zeitraum bleibt der vorhandene Wert bewusst stehen.
        """
        for run in self:
            bounds = QUARTER_BOUNDS.get(run.period_type)
            if not bounds or not run.fiscal_year:
                # 'custom' bzw. noch kein Jahr: vorhandene Eingabe beibehalten.
                run.date_from = run.date_from
                run.date_to = run.date_to
                continue
            m_from, d_from, m_to, d_to = bounds
            run.date_from = date(run.fiscal_year, m_from, d_from)
            run.date_to = date(run.fiscal_year, m_to, d_to)

    @api.depends('enforce_cutoff')
    def _compute_cutoff_info(self):
        cutoff = self._payout_cutoff()
        if cutoff:
            text = _(
                'Stichtag %(day)02d.%(month)02d. – Anträge mit Eingang bis dahin '
                'gehören zum Haushaltsjahr des Eingangs, spätere zum Folgejahr.',
                day=cutoff[0], month=cutoff[1],
            )
        else:
            text = _(
                'Kein Stichtag gepflegt (Systemparameter '
                '"kjr_grant.payout_cutoff_day" / "kjr_grant.payout_cutoff_month"). '
                'Die Stichtagsregel wird deshalb nicht angewendet.'
            )
        for run in self:
            run.cutoff_info = text

    @api.depends('application_ids', 'application_ids.grant_approved')
    def _compute_totals(self):
        for run in self:
            run.application_count = len(run.application_ids)
            run.amount_total = sum(run.application_ids.mapped('grant_approved'))

    @api.depends('fiscal_year', 'period_type', 'date_from', 'date_to',
                 'period_basis', 'enforce_cutoff', 'grant_type_ids', 'partner_ids')
    def _compute_applications(self):
        """Stellt die Vorschau der einbezogenen Anträge zusammen.

        Bewusst eine EIGENE Compute-Methode (getrennt von der Ausschlussliste):
        'application_ids' ist gespeichert und vom Anwender änderbar. Läge die
        Berechnung mit den nicht gespeicherten Anzeigefeldern zusammen, würde
        schon deren Lesen die Auswahl wieder überschreiben – von Hand entfernte
        Anträge kämen zurück in den Lauf.
        """
        for run in self:
            if run.state == 'done':
                # Nach dem Lauf bleibt die Auswahl als Dokumentation stehen.
                run.application_ids = run.application_ids
                continue
            included, _blocked = run._collect_candidates()
            run.application_ids = [(6, 0, included.ids)]

    @api.depends('fiscal_year', 'period_type', 'date_from', 'date_to',
                 'period_basis', 'enforce_cutoff', 'grant_type_ids', 'partner_ids')
    def _compute_blocked(self):
        """Anzeige: welche Anträge des Zeitraums NICHT mitlaufen und warum."""
        for run in self:
            if run.state == 'done':
                run.blocked_ids = [(5, 0, 0)]
                run.blocked_info = ''
                continue
            _included, blocked = run._collect_candidates()
            run.blocked_ids = [(6, 0, [rec.id for rec, _reason in blocked])]
            run.blocked_info = run._format_reasons(blocked)

    @api.constrains('date_from', 'date_to')
    def _check_period(self):
        for run in self:
            if run.date_from and run.date_to and run.date_from > run.date_to:
                raise ValidationError(_('"Zeitraum von" muss vor "Zeitraum bis" liegen.'))

    @api.constrains('fiscal_year')
    def _check_fiscal_year(self):
        for run in self:
            if run.fiscal_year and not (2000 <= run.fiscal_year <= 2100):
                raise ValidationError(_('Bitte ein vierstelliges Haushaltsjahr eingeben.'))

    # ══════════════════════════════════════════════════════════════════════════
    # HILFSLOGIK
    # ══════════════════════════════════════════════════════════════════════════

    @api.model
    def _payout_cutoff(self):
        """Jahresend-Stichtag aus den Systemparametern, sonst None.

        BEWUSST OHNE FALLBACK-DATUM: dass es einen Stichtag gibt, ist belegt,
        das konkrete Datum ist es nicht. Ist nichts gepflegt, wird die Regel
        nicht angewendet, statt ein Datum zu unterstellen.
        """
        params = self.env['ir.config_parameter'].sudo()
        raw_day = (params.get_param('kjr_grant.payout_cutoff_day') or '').strip()
        raw_month = (params.get_param('kjr_grant.payout_cutoff_month') or '').strip()
        if not raw_day or not raw_month:
            return None
        try:
            day, month = int(raw_day), int(raw_month)
        except (TypeError, ValueError):
            return None
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return None
        return (day, month)

    def _base_domain(self):
        """Alle grundsätzlich anweisbaren Anträge (ohne Zeitraumfilter).

        Der Zeitraum wird bewusst erst in Python geprüft: nur so lassen sich
        bewilligte Anträge OHNE das maßgebliche Datum überhaupt melden, statt
        sie stillschweigend aus jedem Lauf herausfallen zu lassen.
        """
        self.ensure_one()
        domain = [
            ('state', '=', 'approved'),
            ('payment_ordered', '=', False),
            ('company_id', 'in', self.env.companies.ids),
        ]
        if self.grant_type_ids:
            domain.append(('grant_type_id', 'in', self.grant_type_ids.ids))
        if self.partner_ids:
            domain.append(('partner_id', 'in', self.partner_ids.ids))
        return domain

    def _collect_candidates(self):
        """Teilt die anweisbaren Anträge in "einbezogen" und "übersprungen".

        :return: (recordset einbezogen, [(record, Begründung), ...])
        """
        self.ensure_one()
        Application = self.env['kjr.grant.application']
        if not self.date_from or not self.date_to:
            return Application.browse(), []

        four_eyes = Application._four_eyes_enabled()
        cutoff = self._payout_cutoff()
        candidates = Application.search(self._base_domain(), order='name')

        included = Application.browse()
        blocked = []
        for rec in candidates:
            ref_date = rec[self.period_basis]
            if not ref_date:
                blocked.append((rec, _(
                    'Kein %(label)s hinterlegt – der Antrag fällt in keinen '
                    'Auszahlungslauf und muss von Hand geklärt werden.',
                    label=Application._fields[self.period_basis].string,
                )))
                continue
            if not (self.date_from <= ref_date <= self.date_to):
                # Außerhalb des Zeitraums: gehört in einen anderen Lauf und wird
                # deshalb gar nicht erst aufgeführt.
                continue
            if self.enforce_cutoff and not cutoff:
                blocked.append((rec, _(
                    'Stichtagsregel aktiv, aber kein Stichtag gepflegt '
                    '(Systemparameter "kjr_grant.payout_cutoff_day" / '
                    '"kjr_grant.payout_cutoff_month").'
                )))
                continue
            if self.enforce_cutoff and rec.payout_year != self.fiscal_year:
                blocked.append((rec, _(
                    'Jahresend-Stichtag: Antragseingang %(eingang)s ergibt das '
                    'Auszahlungsjahr %(jahr)s, der Lauf betrifft %(lauf)s.',
                    eingang=(rec.date_submitted and rec.date_submitted.strftime('%d.%m.%Y')
                             or _('unbekannt')),
                    jahr=rec.payout_year or _('unbestimmt'),
                    lauf=self.fiscal_year,
                )))
                continue
            if rec.grant_approved <= 0:
                blocked.append((rec, _(
                    'Kein bewilligter Betrag hinterlegt (0,00 €).'
                )))
                continue
            if four_eyes and rec.reviewed_by and rec.reviewed_by.id == self.env.user.id:
                blocked.append((rec, _(
                    'Vier-Augen-Prinzip: von %(user)s selbst sachlich geprüft – '
                    'die Zahlung muss eine zweite Person anweisen.',
                    user=rec.reviewed_by.name,
                )))
                continue
            included |= rec
        return included, blocked

    @api.model
    def _format_reasons(self, entries):
        """Formatiert [(record, Grund)] als lesbares Protokoll."""
        lines = []
        for rec, reason in entries:
            lines.append('• %s (%s, %s €): %s' % (
                rec.name,
                rec.partner_id.display_name or _('ohne Verband'),
                ('%.2f' % (rec.grant_approved or 0.0)).replace('.', ','),
                reason,
            ))
        return '\n'.join(lines)

    def _period_label(self):
        self.ensure_one()
        label = dict(self._fields['period_type'].selection).get(
            self.period_type, self.period_type)
        return _(
            '%(period)s %(year)s (%(start)s–%(end)s)',
            period=label, year=self.fiscal_year,
            start=self.date_from and self.date_from.strftime('%d.%m.%Y') or '',
            end=self.date_to and self.date_to.strftime('%d.%m.%Y') or '',
        )

    # ══════════════════════════════════════════════════════════════════════════
    # AKTIONEN
    # ══════════════════════════════════════════════════════════════════════════

    def action_refresh(self):
        """Vorschau neu zusammenstellen (verwirft manuelle Änderungen).

        Nur 'application_ids' wird geschrieben: die Ausschlussliste ist ein
        nicht gespeichertes Anzeigefeld und wird bei jedem Lesen frisch
        ermittelt.
        """
        self.ensure_one()
        if self.state == 'done':
            raise UserError(_('Dieser Auszahlungslauf wurde bereits ausgeführt.'))
        included, _blocked = self._collect_candidates()
        self.application_ids = [(6, 0, included.ids)]
        return self._reopen()

    def action_run(self):
        """Weist die ausgewählten Anträge gebündelt zur Zahlung an.

        Die Anweisung selbst macht ausschließlich action_order_payment() am
        Antrag – dieser Assistent schreibt keine Bearbeitungsvermerke.
        """
        self.ensure_one()
        if not self.env.user.has_group('kjr_grant.group_kjr_reviewer'):
            raise AccessError(_('Keine Berechtigung zur Zahlungsanweisung.'))
        if self.state == 'done':
            raise UserError(_('Dieser Auszahlungslauf wurde bereits ausgeführt.'))
        if not self.application_ids:
            raise UserError(_(
                'Der Lauf enthält keine Anträge. Bitte Zeitraum, Haushaltsjahr '
                'und Abgrenzung prüfen.'
            ))

        Application = self.env['kjr.grant.application']
        # Die Auswahl kann seit der Vorschau bearbeitet worden sein (auch per
        # RPC). Deshalb wird JEDER Datensatz erneut geprüft – die Vorschau ist
        # eine Anzeige, keine Sicherung.
        selected = self.application_ids
        included, blocked = self._collect_candidates()
        skipped = [(rec, reason) for rec, reason in blocked if rec in selected]
        to_order = selected & included
        explained = Application.browse([rec.id for rec, _reason in skipped])
        for rec in selected - included - explained:
            skipped.append((rec, _(
                'Erfüllt die Voraussetzungen des Laufs nicht mehr (Status, '
                'bewilligter Betrag, Zeitraum oder bereits angewiesen).'
            )))

        ordered = Application.browse()
        period_label = self._period_label()
        for rec in to_order:
            # Savepoint je Antrag: eine abgewiesene Anweisung darf den Lauf
            # nicht abbrechen und die bereits erteilten nicht zurückrollen.
            try:
                with self.env.cr.savepoint():
                    rec.action_order_payment()
                    rec.message_post(
                        body=markupsafe.Markup('<p>%s</p>') % _(
                            'Zahlungsanweisung im Auszahlungslauf %(period)s durch '
                            '%(user)s.',
                            period=period_label, user=self.env.user.name,
                        ),
                        subtype_xmlid='mail.mt_note',
                    )
            except (UserError, AccessError, ValidationError) as exc:
                skipped.append((rec, str(exc)))
                continue
            ordered |= rec

        result = self._build_report(ordered, skipped, period_label)
        self.write({
            'state': 'done',
            'ordered_ids': [(6, 0, ordered.ids)],
            'skipped_ids': [(6, 0, [rec.id for rec, _reason in skipped])],
            'ordered_count': len(ordered),
            'skipped_count': len(skipped),
            'ordered_amount': sum(ordered.mapped('grant_approved')),
            'result_text': result,
        })
        _logger.info('KJR Auszahlungslauf %s durch %s:\n%s',
                     period_label, self.env.user.login, result)
        return self._reopen()

    def _build_report(self, ordered, skipped, period_label):
        """Ergebnisbericht im Klartext (Bildschirm, Serverprotokoll, Ausdruck)."""
        self.ensure_one()
        amount = ('%.2f' % sum(ordered.mapped('grant_approved'))).replace('.', ',')
        lines = [
            _('Auszahlungslauf %(period)s') % {'period': period_label},
            _('Ausgeführt von %(user)s am %(day)s') % {
                'user': self.env.user.name,
                'day': fields.Date.context_today(self).strftime('%d.%m.%Y'),
            },
            '',
            _('Zur Zahlung angewiesen: %(count)s Anträge über %(amount)s €') % {
                'count': len(ordered), 'amount': amount,
            },
        ]
        if ordered:
            lines += ['• %s (%s, %s €)' % (
                rec.name,
                rec.partner_id.display_name or _('ohne Verband'),
                ('%.2f' % (rec.grant_approved or 0.0)).replace('.', ','),
            ) for rec in ordered]
        lines += ['', _('Übersprungen: %(count)s Anträge') % {'count': len(skipped)}]
        if skipped:
            lines.append(self._format_reasons(skipped))
        else:
            lines.append(_('– keine –'))
        return '\n'.join(lines)

    def _reopen(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'name': _('Auszahlungslauf'),
        }

    def action_open_ordered(self):
        """Angewiesene Anträge in einer Liste öffnen (Kontrolle nach dem Lauf)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Angewiesene Anträge'),
            'res_model': 'kjr.grant.application',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.ordered_ids.ids)],
        }
