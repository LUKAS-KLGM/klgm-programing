# -*- coding: utf-8 -*-
"""Einrichtungsbuchung mit Workflow, Preis-/Steuerberechnung und Rechnungsstellung."""
import logging
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class KjrFacilityBooking(models.Model):
    _name = 'kjr.facility.booking'
    _description = 'KJR Einrichtungsbuchung'
    _order = 'check_in desc, name desc'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']

    name = fields.Char(
        string='Buchungsnummer', required=True, copy=False, readonly=True,
        default=lambda self: _('Neu'), tracking=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Gesellschaft', required=True, index=True,
        default=lambda self: self.env.company,
    )
    state = fields.Selection([
        ('draft', 'Anfrage'),
        ('confirmed', 'Bestätigt'),
        ('deposit', 'Anzahlung'),
        ('checked_in', 'Angereist'),
        ('invoiced', 'Berechnet'),
        ('done', 'Abgeschlossen'),
        ('cancelled', 'Storniert'),
    ], string='Status', default='draft', required=True, tracking=True, index=True)

    facility_id = fields.Many2one(
        'kjr.facility', string='Einrichtung', required=True,
        ondelete='restrict', tracking=True,
    )
    color = fields.Integer(related='facility_id.color', store=True)
    partner_id = fields.Many2one(
        'res.partner', string='Gruppe / Mieter', required=True,
        ondelete='restrict', tracking=True,
    )
    group_name = fields.Char(string='Gruppenbezeichnung')
    contact_email = fields.Char(string='E-Mail')
    contact_phone = fields.Char(string='Telefon')

    # ── Zeitraum ─────────────────────────────────────────────────────────────
    check_in = fields.Date(string='Anreise', required=True, tracking=True)
    check_out = fields.Date(string='Abreise', required=True, tracking=True)
    nights = fields.Integer(string='Nächte', compute='_compute_nights', store=True)

    # ── Belegung ─────────────────────────────────────────────────────────────
    participant_count = fields.Integer(string='Teilnehmer', default=0, tracking=True)
    leader_count = fields.Integer(string='Betreuer', default=0)
    supervision_ok = fields.Boolean(string='Betreuung ausreichend', compute='_compute_supervision')
    room_ids = fields.Many2many(
        'kjr.facility.room', 'kjr_booking_room_rel', 'booking_id', 'room_id',
        string='Räume',
    )
    bed_count = fields.Integer(string='Betten gebucht', compute='_compute_bed_count')

    # ── Leistungen ───────────────────────────────────────────────────────────
    tariff_id = fields.Many2one('kjr.facility.tariff', string='Tarif', tracking=True)
    meal_option = fields.Selection([
        ('none', 'Selbstverpflegung'),
        ('breakfast', 'Frühstück'),
        ('half', 'Halbpension'),
        ('full', 'Vollpension'),
    ], string='Verpflegung', default='none', required=True)
    equipment_ids = fields.Many2many(
        'kjr.facility.equipment', 'kjr_booking_equipment_rel', 'booking_id', 'equipment_id',
        string='Zusatzausstattung',
    )
    equipment_notes = fields.Text(string='Anmerkungen Ausstattung')

    # ── Förderbezug (entkoppelt von kjr_grant) ───────────────────────────────
    is_grant_funded = fields.Boolean(string='Gefördert (Zuschuss)')
    grant_reference = fields.Char(
        string='Zuschuss-Aktenzeichen', groups='kjr_facility.group_kjr_facility_user')

    # ── Beträge ──────────────────────────────────────────────────────────────
    currency_id = fields.Many2one(related='company_id.currency_id')
    amount_accommodation = fields.Monetary(string='Unterkunft', compute='_compute_amounts', store=True)
    amount_meals = fields.Monetary(string='Verpflegung', compute='_compute_amounts', store=True)
    amount_equipment = fields.Monetary(string='Ausstattung', compute='_compute_amounts', store=True)
    amount_untaxed = fields.Monetary(string='Netto', compute='_compute_amounts', store=True)
    amount_tax = fields.Monetary(string='USt', compute='_compute_amounts', store=True)
    amount_total = fields.Monetary(string='Gesamt (brutto)', compute='_compute_amounts', store=True)
    deposit_pct = fields.Float(string='Anzahlung (%)', default=20.0)
    deposit_amount = fields.Monetary(string='Anzahlungsbetrag', compute='_compute_deposit', store=True)
    deposit_paid = fields.Boolean(string='Anzahlung erhalten', tracking=True)

    invoice_id = fields.Many2one('account.move', string='Rechnung', readonly=True, copy=False)
    note = fields.Text(string='Anmerkungen')
    internal_note = fields.Text(
        string='Interne Notiz', groups='kjr_facility.group_kjr_facility_user',
        help='Nur für Mitarbeiter sichtbar (nicht im Portal).')

    # ══════════════════════════════════════════════════════════════════════════
    # COMPUTED
    # ══════════════════════════════════════════════════════════════════════════

    @api.depends('check_in', 'check_out')
    def _compute_nights(self):
        for rec in self:
            if rec.check_in and rec.check_out and rec.check_out > rec.check_in:
                rec.nights = (rec.check_out - rec.check_in).days
            else:
                rec.nights = 0

    @api.depends('participant_count', 'leader_count', 'facility_id.supervision_ratio')
    def _compute_supervision(self):
        for rec in self:
            ratio = rec.facility_id.supervision_ratio or 0
            if not rec.participant_count:
                rec.supervision_ok = True
            elif ratio <= 0:
                rec.supervision_ok = True
            else:
                rec.supervision_ok = (rec.leader_count * ratio) >= rec.participant_count

    @api.depends('room_ids.capacity')
    def _compute_bed_count(self):
        for rec in self:
            rec.bed_count = sum(rec.room_ids.mapped('capacity'))

    @api.depends(
        'nights', 'participant_count', 'meal_option', 'tariff_id',
        'tariff_id.price_per_person_night', 'tariff_id.price_flat_per_night',
        'tariff_id.meal_breakfast', 'tariff_id.meal_half', 'tariff_id.meal_full',
        'tariff_id.tax_id', 'equipment_ids', 'equipment_ids.price_per_day',
        'company_id', 'company_id.currency_id',
    )
    def _compute_amounts(self):
        for rec in self:
            t = rec.tariff_id
            nights = rec.nights or 0
            pax = rec.participant_count or 0
            accommodation = nights * (pax * (t.price_per_person_night if t else 0.0)
                                      + (t.price_flat_per_night if t else 0.0))
            meal_rate = 0.0
            if t:
                meal_rate = {
                    'breakfast': t.meal_breakfast,
                    'half': t.meal_half,
                    'full': t.meal_full,
                }.get(rec.meal_option, 0.0)
            meals = nights * pax * meal_rate
            equipment = nights * sum(rec.equipment_ids.mapped('price_per_day'))
            rec.amount_accommodation = accommodation
            rec.amount_meals = meals
            rec.amount_equipment = equipment
            # Steuer positionsweise berechnen, damit die Buchungsbeträge exakt mit der
            # später erzeugten Rechnung (Rundung je Position) übereinstimmen.
            currency = rec.company_id.currency_id or self.env.company.currency_id
            taxes = t.tax_id if t else self.env['account.tax']
            untaxed = tax = 0.0
            for component in (accommodation, meals, equipment):
                if not component:
                    continue
                res = taxes.compute_all(component, currency=currency, quantity=1.0)
                untaxed += res['total_excluded']
                tax += res['total_included'] - res['total_excluded']
            rec.amount_untaxed = untaxed
            rec.amount_tax = tax
            rec.amount_total = untaxed + tax

    @api.depends('amount_total', 'deposit_pct')
    def _compute_deposit(self):
        for rec in self:
            rec.deposit_amount = rec.amount_total * (rec.deposit_pct or 0.0) / 100.0

    def _compute_access_url(self):
        super()._compute_access_url()
        for rec in self:
            rec.access_url = f'/my/einrichtungsbuchungen/{rec.id}'

    # ══════════════════════════════════════════════════════════════════════════
    # CONSTRAINTS
    # ══════════════════════════════════════════════════════════════════════════

    @api.constrains('check_in', 'check_out')
    def _check_dates(self):
        for rec in self:
            if rec.check_in and rec.check_out and rec.check_out <= rec.check_in:
                raise ValidationError(_('Die Abreise muss nach der Anreise liegen.'))

    @api.constrains('participant_count', 'leader_count')
    def _check_counts(self):
        for rec in self:
            if rec.participant_count < 0 or rec.leader_count < 0:
                raise ValidationError(_('Teilnehmer-/Betreuerzahlen dürfen nicht negativ sein.'))

    @api.constrains('participant_count', 'facility_id', 'room_ids', 'bed_count')
    def _check_capacity(self):
        for rec in self:
            if rec.facility_id.capacity and rec.participant_count > rec.facility_id.capacity:
                raise ValidationError(_(
                    'Die Teilnehmerzahl (%(p)d) übersteigt die Kapazität der Einrichtung (%(c)d).',
                    p=rec.participant_count, c=rec.facility_id.capacity,
                ))
            if rec.room_ids and rec.bed_count and rec.participant_count > rec.bed_count:
                raise ValidationError(_(
                    'Die Teilnehmerzahl (%(p)d) übersteigt die gebuchten Betten (%(b)d).',
                    p=rec.participant_count, b=rec.bed_count,
                ))

    @api.constrains('room_ids', 'check_in', 'check_out', 'state')
    def _check_double_booking(self):
        for rec in self:
            if rec.state == 'cancelled' or not rec.room_ids or not (rec.check_in and rec.check_out):
                continue
            conflicting = self.search([
                ('id', '!=', rec.id),
                ('state', '!=', 'cancelled'),
                ('room_ids', 'in', rec.room_ids.ids),
                ('check_in', '<', rec.check_out),
                ('check_out', '>', rec.check_in),
            ], limit=1)
            if conflicting:
                raise ValidationError(_(
                    'Raum-Doppelbelegung: Mindestens ein gewählter Raum ist im Zeitraum '
                    'bereits durch Buchung %(other)s belegt.',
                    other=conflicting.name,
                ))

    # ══════════════════════════════════════════════════════════════════════════
    # ORM
    # ══════════════════════════════════════════════════════════════════════════

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('Neu'):
                vals['name'] = self.env['ir.sequence'].next_by_code('kjr.facility.booking') or _('Neu')
        return super().create(vals_list)

    # ══════════════════════════════════════════════════════════════════════════
    # WORKFLOW
    # ══════════════════════════════════════════════════════════════════════════

    def _send_template(self, xmlid):
        try:
            self.env.ref(xmlid).send_mail(self.id, force_send=False)
        except Exception as e:  # noqa: BLE001 - Mailversand darf den Workflow nicht blockieren
            _logger.warning('Mailversand %s für %s fehlgeschlagen: %s', xmlid, self.name, e)

    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Nur Anfragen können bestätigt werden.'))
            rec.state = 'confirmed'
            rec._send_template('kjr_facility.mail_template_booking_confirmed')

    def action_request_deposit(self):
        for rec in self:
            if rec.state not in ('confirmed',):
                raise UserError(_('Anzahlung kann nur für bestätigte Buchungen angefordert werden.'))
            rec.state = 'deposit'
            rec._send_template('kjr_facility.mail_template_booking_deposit')

    def action_check_in(self):
        for rec in self:
            if rec.state not in ('confirmed', 'deposit'):
                raise UserError(_('Anreise nur bei bestätigter Buchung möglich.'))
            rec.state = 'checked_in'

    def action_create_invoice(self):
        self.ensure_one()
        if self.invoice_id:
            return self.action_view_invoice()
        if not self.partner_id:
            raise UserError(_('Bitte einen Mieter/eine Gruppe angeben.'))
        if self.amount_total <= 0:
            raise UserError(_('Es gibt nichts zu berechnen (Betrag ist 0). Bitte Tarif/Zeitraum prüfen.'))
        tax = self.tariff_id.tax_id
        tax_cmd = [(6, 0, tax.ids)] if tax else False
        lines = []
        if self.amount_accommodation:
            lines.append((0, 0, {
                'name': _('Unterkunft %(fac)s, %(n)d Nächte, %(p)d Pers. (%(ci)s–%(co)s)') % {
                    'fac': self.facility_id.name, 'n': self.nights, 'p': self.participant_count,
                    'ci': self.check_in, 'co': self.check_out,
                },
                'quantity': 1.0, 'price_unit': self.amount_accommodation,
                'tax_ids': tax_cmd,
            }))
        if self.amount_meals:
            lines.append((0, 0, {
                'name': _('Verpflegung (%s)') % dict(self._fields['meal_option'].selection).get(self.meal_option),
                'quantity': 1.0, 'price_unit': self.amount_meals, 'tax_ids': tax_cmd,
            }))
        if self.amount_equipment:
            lines.append((0, 0, {
                'name': _('Zusatzausstattung'),
                'quantity': 1.0, 'price_unit': self.amount_equipment, 'tax_ids': tax_cmd,
            }))
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'invoice_origin': self.name,
            'invoice_line_ids': lines,
        })
        self.invoice_id = move.id
        self.state = 'invoiced'
        self.message_post(
            body=_('Rechnung %s erstellt.') % move.name, subtype_xmlid='mail.mt_note',
        )
        # Anzahlung: Die Rechnung lautet bewusst über den vollen Betrag. Eine bereits
        # geleistete Anzahlung ist in der Buchhaltung als Kundenzahlung gegen diese
        # Rechnung abzugleichen (kein automatischer Abzug, um die USt-Aufteilung nicht
        # zu verfälschen). TODO(Steuer): Anzahlungsbesteuerung § 13 UStG final prüfen.
        if self.deposit_paid and self.deposit_amount:
            move.message_post(body=_(
                'Hinweis: Anzahlung von %.2f € wurde bereits geleistet und ist mit dieser '
                'Rechnung als Kundenzahlung zu verrechnen.'
            ) % self.deposit_amount)
        return self.action_view_invoice()

    def action_done(self):
        for rec in self:
            if rec.state not in ('checked_in', 'invoiced'):
                raise UserError(_('Abschluss nur nach Anreise/Rechnung möglich.'))
            if rec.state == 'checked_in' and rec.amount_total > 0 and not rec.invoice_id:
                raise UserError(_(
                    'Bitte zuerst die Rechnung erstellen, bevor die Buchung abgeschlossen wird '
                    '(berechenbarer Betrag vorhanden).'
                ))
            rec.state = 'done'
            # Belegte Räume zur Reinigung markieren.
            rec.room_ids.filtered(lambda r: r.housekeeping_state != 'blocked').write(
                {'housekeeping_state': 'dirty'})

    def action_cancel(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError(_('Abgeschlossene Buchungen können nicht storniert werden.'))
            rec.state = 'cancelled'
            rec._send_template('kjr_facility.mail_template_booking_cancelled')

    def action_reset_draft(self):
        for rec in self:
            if rec.state in ('invoiced', 'done'):
                raise UserError(_('Berechnete/abgeschlossene Buchungen können nicht zurückgesetzt werden.'))
            rec.state = 'draft'

    def action_view_invoice(self):
        self.ensure_one()
        if not self.invoice_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Rechnung'),
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'view_mode': 'form',
        }

    def action_print_contract(self):
        self.ensure_one()
        return self.env.ref('kjr_facility.action_report_booking_contract').report_action(self)

    # ══════════════════════════════════════════════════════════════════════════
    # CRON
    # ══════════════════════════════════════════════════════════════════════════

    @api.model
    def _cron_booking_reminder(self):
        """Erinnerung 14 Tage vor Anreise an aktive Buchungen."""
        target = fields.Date.today() + timedelta(days=14)
        bookings = self.search([
            ('state', 'in', ('confirmed', 'deposit', 'checked_in')),
            ('check_in', '=', target),
        ])
        for bk in bookings:
            bk.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=bk.check_in,
                summary=_('Anreise in 14 Tagen: %s') % bk.name,
                note=_('Die Gruppe "%(grp)s" reist am %(d)s in %(fac)s an.') % {
                    'grp': bk.group_name or bk.partner_id.display_name,
                    'd': bk.check_in.strftime('%d.%m.%Y'),
                    'fac': bk.facility_id.name,
                },
            )
            bk._send_template('kjr_facility.mail_template_booking_reminder')
        _logger.info('Einrichtungs-Erinnerung: %d Buchungen', len(bookings))
