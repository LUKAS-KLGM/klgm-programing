# -*- coding: utf-8 -*-
"""Ausleihvorgang mit Workflow und Verfügbarkeitsprüfung."""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class KjrRentalOrder(models.Model):
    _name = 'kjr.rental.order'
    _description = 'KJR Ausleihe'
    _order = 'date_from desc, name desc'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']

    name = fields.Char(
        string='Ausleihnummer', required=True, copy=False, readonly=True,
        default=lambda self: _('Neu'), tracking=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Gesellschaft', required=True, index=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related='company_id.currency_id')
    partner_id = fields.Many2one('res.partner', string='Entleiher', required=True, ondelete='restrict', tracking=True)
    contact_email = fields.Char(string='E-Mail')
    contact_phone = fields.Char(string='Telefon')
    is_member = fields.Boolean(string='KJR-Mitglied (Tarif)', tracking=True)
    state = fields.Selection([
        ('draft', 'Anfrage'),
        ('reserved', 'Reserviert'),
        ('issued', 'Ausgegeben'),
        ('returned', 'Zurückgegeben'),
        ('cancelled', 'Storniert'),
    ], string='Status', default='draft', required=True, tracking=True, index=True)
    date_from = fields.Date(string='Von', required=True, tracking=True)
    date_to = fields.Date(string='Bis', required=True, tracking=True)
    rental_days = fields.Integer(string='Tage', compute='_compute_rental_days', store=True)
    line_ids = fields.One2many('kjr.rental.order.line', 'order_id', string='Positionen')
    amount_total = fields.Monetary(string='Gebühr gesamt', compute='_compute_amounts', store=True)
    deposit_total = fields.Monetary(string='Kaution gesamt', compute='_compute_amounts', store=True)
    deposit_paid = fields.Boolean(string='Kaution erhalten', tracking=True)
    invoice_id = fields.Many2one('account.move', string='Rechnung', readonly=True, copy=False)
    note = fields.Text(string='Anmerkungen')

    @api.depends('date_from', 'date_to')
    def _compute_rental_days(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_to >= rec.date_from:
                rec.rental_days = (rec.date_to - rec.date_from).days + 1
            else:
                rec.rental_days = 0

    @api.depends('line_ids.subtotal', 'line_ids.deposit_subtotal')
    def _compute_amounts(self):
        for rec in self:
            rec.amount_total = sum(rec.line_ids.mapped('subtotal'))
            rec.deposit_total = sum(rec.line_ids.mapped('deposit_subtotal'))

    def _compute_access_url(self):
        super()._compute_access_url()
        for rec in self:
            rec.access_url = f'/my/ausleihen/{rec.id}'

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_to < rec.date_from:
                raise ValidationError(_('Das Rückgabedatum darf nicht vor dem Ausleihdatum liegen.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('Neu'):
                vals['name'] = self.env['ir.sequence'].next_by_code('kjr.rental.order') or _('Neu')
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        # Bei Änderung von Zeitraum/Positionen aktive Ausleihen erneut auf Verfügbarkeit prüfen,
        # damit reservierte/ausgegebene Vorgänge nicht nachträglich überbucht werden.
        if {'date_from', 'date_to', 'line_ids'} & set(vals):
            self.filtered(lambda r: r.state in ('reserved', 'issued'))._check_availability()
        return res

    def _check_availability(self):
        """Stellt sicher, dass der Gesamtbedarf je Artikel (über alle Positionen) im Zeitraum
        verfügbar ist."""
        for rec in self:
            demand = {}
            for line in rec.line_ids:
                demand[line.item_id] = demand.get(line.item_id, 0) + line.quantity
            for item, qty in demand.items():
                avail = item.quantity_available(rec.date_from, rec.date_to, exclude_order=rec)
                if qty > avail:
                    raise UserError(_(
                        'Nicht genügend verfügbar: "%(item)s" – angefragt %(req)d, verfügbar %(av)d '
                        'im Zeitraum %(df)s–%(dt)s.',
                        item=item.name, req=qty, av=avail,
                        df=rec.date_from, dt=rec.date_to,
                    ))

    def action_reserve(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Nur Anfragen können reserviert werden.'))
            if not rec.line_ids:
                raise UserError(_('Bitte mindestens eine Position hinzufügen.'))
            rec._check_availability()
            rec.state = 'reserved'

    def action_issue(self):
        for rec in self:
            if rec.state != 'reserved':
                raise UserError(_('Nur reservierte Ausleihen können ausgegeben werden.'))
            rec._check_availability()
            rec.state = 'issued'

    def action_return(self):
        for rec in self:
            if rec.state != 'issued':
                raise UserError(_('Nur ausgegebene Ausleihen können zurückgenommen werden.'))
            rec.state = 'returned'

    def action_cancel(self):
        for rec in self:
            if rec.state == 'returned':
                raise UserError(_('Zurückgegebene Ausleihen können nicht storniert werden.'))
            rec.state = 'cancelled'

    def action_reset_draft(self):
        for rec in self:
            if rec.state == 'returned':
                raise UserError(_('Zurückgegebene Ausleihen können nicht zurückgesetzt werden.'))
            rec.state = 'draft'

    def action_create_invoice(self):
        self.ensure_one()
        if self.invoice_id:
            return self.action_view_invoice()
        if self.amount_total <= 0:
            raise UserError(_('Keine berechenbare Gebühr vorhanden.'))
        lines = [(0, 0, {
            'name': _('%(item)s (%(q)d × %(d)d Tage)') % {
                'item': line.item_id.name, 'q': line.quantity, 'd': self.rental_days},
            'quantity': 1.0,
            'price_unit': line.subtotal,
        }) for line in self.line_ids if line.subtotal]
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'invoice_origin': self.name,
            'invoice_line_ids': lines,
        })
        self.invoice_id = move.id
        self.message_post(body=_('Rechnung zur Ausleihe %s erstellt.') % self.name, subtype_xmlid='mail.mt_note')
        return self.action_view_invoice()

    def action_view_invoice(self):
        self.ensure_one()
        if not self.invoice_id:
            return False
        return {
            'type': 'ir.actions.act_window', 'res_model': 'account.move',
            'res_id': self.invoice_id.id, 'view_mode': 'form', 'name': _('Rechnung'),
        }

    def action_print_contract(self):
        self.ensure_one()
        return self.env.ref('kjr_rental.action_report_rental_contract').report_action(self)


class KjrRentalOrderLine(models.Model):
    _name = 'kjr.rental.order.line'
    _description = 'Ausleihposition'
    _order = 'order_id, sequence, id'

    order_id = fields.Many2one('kjr.rental.order', string='Ausleihe', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    item_id = fields.Many2one('kjr.rental.item', string='Artikel', required=True)
    quantity = fields.Integer(string='Menge', default=1)
    price_per_day = fields.Float(
        string='Tagespreis (€)', digits=(8, 2),
        compute='_compute_price', store=True, readonly=False,
    )
    deposit_unit = fields.Float(string='Kaution/Stück (€)', digits=(8, 2), compute='_compute_price', store=True, readonly=False)
    currency_id = fields.Many2one(related='order_id.currency_id')
    subtotal = fields.Monetary(string='Zwischensumme', compute='_compute_subtotal', store=True)
    deposit_subtotal = fields.Monetary(string='Kaution', compute='_compute_subtotal', store=True)

    @api.depends('item_id', 'order_id.is_member')
    def _compute_price(self):
        for rec in self:
            # Preise ausgegebener/zurückgegebener/stornierter Vorgänge nicht überschreiben
            # (auch nicht bei programmatischen Writes auf item_id/is_member).
            if rec.order_id.state in ('issued', 'returned', 'cancelled'):
                continue
            if rec.item_id:
                rec.price_per_day = rec.item_id.price_for(rec.order_id.is_member)
                rec.deposit_unit = rec.item_id.deposit
            else:
                rec.price_per_day = 0.0
                rec.deposit_unit = 0.0

    @api.depends('price_per_day', 'quantity', 'deposit_unit', 'order_id.rental_days')
    def _compute_subtotal(self):
        for rec in self:
            days = rec.order_id.rental_days or 0
            rec.subtotal = rec.price_per_day * rec.quantity * days
            rec.deposit_subtotal = rec.deposit_unit * rec.quantity

    @api.constrains('quantity')
    def _check_quantity(self):
        for rec in self:
            if rec.quantity <= 0:
                raise ValidationError(_('Die Menge muss größer als 0 sein.'))
