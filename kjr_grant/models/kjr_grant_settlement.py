# -*- coding: utf-8 -*-
"""
Abrechnung und Verwendungsnachweis nach Maßnahmenabschluss.
Erfasst Ist-Kosten und berechnet ggf. Rückforderungsbetrag.
"""
import math
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class KjrGrantSettlement(models.Model):
    _name = 'kjr.grant.settlement'
    _description = 'KJR Abrechnung / Verwendungsnachweis'
    _order = 'create_date desc'
    _rec_name = 'name'
    _inherit = ['mail.thread']

    name = fields.Char(
        string='Abrechnungsnummer', required=True, readonly=True,
        copy=False, default=lambda self: _('Neu'),
    )
    application_id = fields.Many2one(
        'kjr.grant.application', string='Zuschussantrag',
        required=True, ondelete='cascade', tracking=True,
    )
    partner_id = fields.Many2one(related='application_id.partner_id', store=True)
    state = fields.Selection([
        ('draft',     'Entwurf'),
        ('submitted', 'Eingereicht'),
        ('reviewed',  'Geprüft'),
        ('closed',    'Abgeschlossen'),
    ], default='draft', tracking=True)

    # Ist-Werte
    actual_tn_count = fields.Integer(string='Tatsächliche TN-Anzahl', default=0, tracking=True)
    actual_cost_accommodation = fields.Float(string='Unterkunft/Verpflegung (€)', digits=(10, 2), default=0.0)
    actual_cost_transport = fields.Float(string='Fahrtkosten (€)', digits=(10, 2), default=0.0)
    actual_cost_referees = fields.Float(string='Referentenhonorare (€)', digits=(10, 2), default=0.0)
    actual_cost_materials = fields.Float(string='Sachkosten (€)', digits=(10, 2), default=0.0)
    actual_cost_other = fields.Float(string='Sonstiges (€)', digits=(10, 2), default=0.0)
    actual_cost_total = fields.Float(
        string='Tatsächliche Gesamtkosten (€)', compute='_compute_actuals',
        store=True, digits=(10, 2),
    )
    actual_income_total = fields.Float(string='Tatsächliche Einnahmen (€)', digits=(10, 2), default=0.0)
    actual_deficit = fields.Float(
        string='Tatsächlicher Fehlbetrag (€)', compute='_compute_actuals',
        store=True, digits=(10, 2),
    )
    grant_recalculated = fields.Float(
        string='Neuer Zuschuss auf Ist-Basis (€)', compute='_compute_recalculated',
        store=True, digits=(10, 2),
    )
    repayment_amount = fields.Float(
        string='Rückforderungsbetrag (€)', compute='_compute_repayment',
        store=True, digits=(10, 2),
    )
    # ── Verzugszinsen (§ 247 BGB Basiszinssatz + 3 Prozentpunkte, bayerisch) ──
    repayment_due_date = fields.Date(
        string='Rückzahlung fällig bis',
        help='Ab Fälligkeit werden Verzugszinsen berechnet.')
    interest_rate = fields.Float(
        string='Zinssatz p. a. (%)', digits=(5, 2),
        default=lambda self: self._default_interest_rate(),
        help='Basiszinssatz (§ 247 BGB) + 3 Prozentpunkte gem. bayerischer ANBest-P '
             'Nr. 8.4 i. V. m. Art. 49a Abs. 3 BayVwVfG. Basiszinssatz über System-'
             'Parameter "kjr_grant.base_interest_rate", Zuschlag über '
             '"kjr_grant.default_interest_surcharge" (Default 3) pflegen. '
             'Pro Bescheid überschreibbar.')
    interest_reference_date = fields.Date(
        string='Zinsen berechnet bis', default=fields.Date.context_today,
        help='Stichtag, bis zu dem die Verzugszinsen berechnet werden.')
    interest_days = fields.Integer(string='Verzugstage', compute='_compute_interest')
    interest_amount = fields.Float(string='Verzugszinsen (€)', digits=(10, 2), compute='_compute_interest')
    total_reclaim = fields.Float(string='Gesamtforderung inkl. Zinsen (€)', digits=(10, 2), compute='_compute_interest')
    settlement_note = fields.Text(string='Verwendungsnachweis / Anmerkungen')
    date_submitted = fields.Date(string='Eingangsdatum Abrechnung')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Neu')) == _('Neu'):
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('kjr.grant.settlement') or _('Neu')
                )
        return super().create(vals_list)

    @api.depends('actual_cost_accommodation', 'actual_cost_transport', 'actual_cost_referees',
                 'actual_cost_materials', 'actual_cost_other', 'actual_income_total')
    def _compute_actuals(self):
        for rec in self:
            total = (
                rec.actual_cost_accommodation + rec.actual_cost_transport
                + rec.actual_cost_referees + rec.actual_cost_materials
                + rec.actual_cost_other
            )
            rec.actual_cost_total = total
            rec.actual_deficit = max(total - rec.actual_income_total, 0.0)

    @api.depends('actual_tn_count', 'actual_cost_accommodation', 'actual_cost_transport',
                 'actual_cost_referees', 'actual_cost_materials', 'actual_cost_other',
                 'actual_income_total', 'application_id',
                 'application_id.grant_calculated', 'application_id.grant_approved',
                 'application_id.tn_count', 'application_id.grant_type_id',
                 'application_id.measure_days', 'application_id.tn_leader_count',
                 'application_id.tn_leader_juleica', 'application_id.delegate_transport_mode',
                 'application_id.delegate_km_one_way', 'application_id.delegate_passenger_count')
    def _compute_recalculated(self):
        """Neuberechnung des Zuschusses auf Ist-Basis – mit der GLEICHEN
        förderartspezifischen Logik wie im Antrag (Tagessätze, Juleica-Zuschlag,
        Referenten-/Sachkostendeckel, Pauschalen, BayRKG, Deckelungen). Dazu wird ein
        flüchtiger In-Memory-Antrag mit den Ist-Werten gerechnet. Der neu berechnete
        Zuschuss kann den ursprünglich bewilligten Betrag nicht übersteigen
        (Verwendungsnachweis löst keine Nachzahlung aus)."""
        for rec in self:
            app = rec.application_id
            base_grant = (app.grant_approved or app.grant_calculated) if app else 0.0
            if not app or not base_grant:
                rec.grant_recalculated = 0.0
                continue
            sim = self.env['kjr.grant.application'].new({
                'grant_type_id': app.grant_type_id.id,
                'measure_start': app.measure_start,
                'measure_end': app.measure_end,
                'measure_start_time': app.measure_start_time,
                'measure_end_time': app.measure_end_time,
                'measure_days': app.measure_days,
                'tn_count': rec.actual_tn_count,
                'tn_leader_count': min(app.tn_leader_count, rec.actual_tn_count) if rec.actual_tn_count else app.tn_leader_count,
                'tn_leader_juleica': app.tn_leader_juleica,
                'cost_accommodation': rec.actual_cost_accommodation,
                'cost_transport': rec.actual_cost_transport,
                'cost_referees': rec.actual_cost_referees,
                'cost_materials': rec.actual_cost_materials,
                'cost_other': rec.actual_cost_other,
                'income_tn_fees': rec.actual_income_total,
                'delegate_transport_mode': app.delegate_transport_mode,
                'delegate_km_one_way': app.delegate_km_one_way,
                'delegate_passenger_count': app.delegate_passenger_count,
            })
            recalculated = sim._calculate_grant()
            recalculated = min(recalculated, base_grant)
            rec.grant_recalculated = math.ceil(recalculated) if recalculated > 0 else 0.0

    @api.depends('grant_recalculated', 'application_id.grant_approved')
    def _compute_repayment(self):
        for rec in self:
            approved = rec.application_id.grant_approved or 0.0
            rec.repayment_amount = max(approved - rec.grant_recalculated, 0.0)

    def _default_interest_rate(self):
        params = self.env['ir.config_parameter'].sudo()
        try:
            base = float(params.get_param('kjr_grant.base_interest_rate', 0.0))
            surcharge = float(params.get_param('kjr_grant.default_interest_surcharge', 3.0))
        except (ValueError, TypeError):
            base, surcharge = 0.0, 3.0
        return base + surcharge

    @api.depends('repayment_amount', 'interest_rate', 'repayment_due_date', 'interest_reference_date')
    def _compute_interest(self):
        for rec in self:
            days = 0
            if (rec.repayment_due_date and rec.interest_reference_date
                    and rec.interest_reference_date > rec.repayment_due_date):
                days = (rec.interest_reference_date - rec.repayment_due_date).days
            rec.interest_days = days
            if rec.repayment_amount > 0 and days > 0:
                rec.interest_amount = round(
                    rec.repayment_amount * (rec.interest_rate or 0.0) / 100.0 * days / 365.0, 2)
            else:
                rec.interest_amount = 0.0
            rec.total_reclaim = rec.repayment_amount + rec.interest_amount

    repayment_move_id = fields.Many2one('account.move', string='Rückforderungs-Buchung', readonly=True, copy=False)

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Nur Entwürfe können eingereicht werden.'))
            rec.write({'state': 'submitted', 'date_submitted': fields.Date.today()})
            rec.message_post(
                body=_('Verwendungsnachweis am %s eingereicht.') % fields.Date.today().strftime('%d.%m.%Y'),
                subtype_xmlid='mail.mt_note',
            )

    def action_review(self):
        for rec in self:
            if rec.state not in ('draft', 'submitted'):
                raise UserError(_('Nur eingereichte Abrechnungen können geprüft werden.'))
            rec.write({'state': 'reviewed'})

    def action_close(self):
        for rec in self:
            if rec.state == 'closed':
                continue
            rec.write({'state': 'closed'})

    def action_reset_draft(self):
        for rec in self:
            rec.write({'state': 'draft'})

    def action_print_verwendungsnachweis(self):
        self.ensure_one()
        return self.env.ref('kjr_grant.action_report_kjr_verwendungsnachweis').report_action(self)

    def action_create_repayment_move(self):
        """Rückforderung buchen: Forderung an Verband."""
        self.ensure_one()
        if self.repayment_amount <= 0:
            raise UserError(_('Kein Rückforderungsbetrag vorhanden.'))
        if self.repayment_move_id:
            raise UserError(_('Rückforderung wurde bereits gebucht.'))
        app = self.application_id
        t = app.grant_type_id
        if not t.journal_id or not t.expense_account_id or not t.liability_account_id:
            raise UserError(_('Bitte Buchhaltungskonten in der Förderart "%s" konfigurieren.') % t.name)
        if self.interest_amount > 0 and not t.interest_account_id:
            raise UserError(_(
                'Es sind Verzugszinsen (%(int).2f €) ausgewiesen, aber in der Förderart "%(t)s" '
                'ist kein Zinsertragskonto gepflegt. Bitte das Zinsertragskonto konfigurieren '
                'oder die Verzugszinsen (Fälligkeit/Stichtag) entfernen.'
            ) % {'int': self.interest_amount, 't': t.name})
        analytic = {str(t.analytic_account_id.id): 100.0} if t.analytic_account_id else False
        lines = [
            (0, 0, {
                'name': _('Rückforderung %s') % app.name,
                'account_id': t.liability_account_id.id,
                'partner_id': app.partner_id.id,
                'debit': self.repayment_amount,
                'credit': 0.0,
            }),
            (0, 0, {
                'name': _('Erstattung Zuschuss %s') % app.name,
                'account_id': t.expense_account_id.id,
                'partner_id': app.partner_id.id,
                'debit': 0.0,
                'credit': self.repayment_amount,
                'analytic_distribution': analytic,
            }),
        ]
        booked_interest = 0.0
        if self.interest_amount > 0 and t.interest_account_id:
            booked_interest = self.interest_amount
            lines += [
                (0, 0, {
                    'name': _('Verzugszinsen %(app)s (%(d)d Tage)') % {'app': app.name, 'd': self.interest_days},
                    'account_id': t.liability_account_id.id,
                    'partner_id': app.partner_id.id,
                    'debit': self.interest_amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': _('Zinsertrag %s') % app.name,
                    'account_id': t.interest_account_id.id,
                    'partner_id': app.partner_id.id,
                    'debit': 0.0,
                    'credit': self.interest_amount,
                    'analytic_distribution': analytic,
                }),
            ]
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': t.journal_id.id,
            'date': fields.Date.today(),
            'ref': _('Rückforderung %s — %s') % (app.name, self.name),
            'line_ids': lines,
        })
        self.repayment_move_id = move.id
        app.message_post(
            body=_('Rückforderung gebucht: %(amt).2f € (inkl. %(int).2f € Verzugszinsen, Abrechnung %(nm)s)') % {
                'amt': self.repayment_amount + booked_interest,
                'int': booked_interest,
                'nm': self.name,
            },
            subtype_xmlid='mail.mt_note',
        )
