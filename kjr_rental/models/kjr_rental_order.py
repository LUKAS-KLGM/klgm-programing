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
    # B-cross-2: Zahlungsstatus der Rechnung gespiegelt (store für Filter/Gruppierung)
    invoice_payment_state = fields.Selection(
        related='invoice_id.payment_state', string='Zahlungsstatus',
        store=True, tracking=True,
    )
    # B-cross-3: Kaution als eigener Lebenszyklus
    deposit_state = fields.Selection([
        ('none', 'Keine / offen'),
        ('received', 'Erhalten'),
        ('refunded', 'Erstattet'),
        ('withheld', 'Einbehalten'),
    ], string='Kautionsstatus', default='none', required=True, tracking=True)
    deposit_received_date = fields.Date(string='Kaution erhalten am', tracking=True)
    deposit_refund_date = fields.Date(string='Kaution erstattet/einbehalten am', tracking=True)
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
        # B-cross-1: optionaler Auto-Rechnungs-Schalter via Systemparameter
        auto_invoice = str(self.env['ir.config_parameter'].sudo().get_param(
            'kjr_rental.auto_invoice_on_return', default='False')).lower() in ('1', 'true', 'yes')
        for rec in self:
            if rec.state != 'issued':
                raise UserError(_('Nur ausgegebene Ausleihen können zurückgenommen werden.'))
            rec.state = 'returned'
            if auto_invoice and not rec.invoice_id and rec.amount_total > 0:
                # Auto-Rechnung darf die Rückgabe nicht blockieren: schlägt das Buchen fehl
                # (z. B. fehlende Kontenfindung), bleibt die Rechnung als Entwurf bestehen
                # und die Rücknahme ist trotzdem abgeschlossen.
                try:
                    rec._create_invoice(post=True)
                except Exception as exc:  # noqa: BLE001 - bewusst breit, Rückgabe schützen
                    rec.message_post(
                        body=_('Automatische Rechnung konnte nicht gebucht werden (%s). '
                               'Bitte die Rechnung manuell erstellen/buchen.') % exc,
                        subtype_xmlid='mail.mt_note')

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

    def _get_fee_product(self):
        """Service-Produkt 'Verleihgebühr' (für korrekte Steuer-/Kontenfindung)."""
        return self.env.ref('kjr_rental.product_rental_fee', raise_if_not_found=False)

    def _create_invoice(self, post=False):
        """B-cross-1/BUG: Rechnung mit Service-Produkt je Position erstellen.

        Jede Position bekommt das Service-Produkt 'Verleihgebühr'; quantity*price_unit
        ergibt den Positionsbetrag, sodass Steuer- und Kontenfindung über das Produkt
        greifen (statt einer Zeile ohne product_id/Steuer).
        """
        self.ensure_one()
        if self.invoice_id:
            return self.invoice_id
        if self.amount_total <= 0:
            raise UserError(_('Keine berechenbare Gebühr vorhanden.'))
        fee_product = self._get_fee_product()
        line_vals = []
        for line in self.line_ids:
            if not line.subtotal:
                continue
            vals = {
                'name': _('%(item)s (%(q)d × %(d)d Tage)') % {
                    'item': line.item_id.name, 'q': line.quantity, 'd': self.rental_days},
                'quantity': float(line.quantity) * float(self.rental_days or 1),
                'price_unit': line.price_per_day,
            }
            if fee_product:
                vals['product_id'] = fee_product.id
            line_vals.append((0, 0, vals))
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'invoice_origin': self.name,
            'invoice_line_ids': line_vals,
        })
        self.invoice_id = move.id
        if post:
            move.action_post()
        self.message_post(body=_('Rechnung zur Ausleihe %s erstellt.') % self.name, subtype_xmlid='mail.mt_note')
        return move

    def action_create_invoice(self):
        self.ensure_one()
        if self.invoice_id:
            return self.action_view_invoice()
        self._create_invoice(post=False)
        return self.action_view_invoice()

    def action_view_invoice(self):
        self.ensure_one()
        if not self.invoice_id:
            return False
        return {
            'type': 'ir.actions.act_window', 'res_model': 'account.move',
            'res_id': self.invoice_id.id, 'view_mode': 'form', 'name': _('Rechnung'),
        }

    def action_register_deposit(self):
        """B-cross-3: Kaution als erhalten verbuchen."""
        for rec in self:
            if rec.deposit_total <= 0:
                raise UserError(_('Für diese Ausleihe ist keine Kaution vorgesehen.'))
            if rec.deposit_state != 'none':
                raise UserError(_('Die Kaution ist bereits erfasst (Status: %s).') % rec.deposit_state)
            rec.deposit_state = 'received'
            rec.deposit_paid = True
            rec.deposit_received_date = fields.Date.context_today(rec)
            rec.message_post(
                body=_('Kaution (%.2f) als erhalten verbucht.') % rec.deposit_total,
                subtype_xmlid='mail.mt_note')

    def action_refund_deposit(self):
        """B-cross-3: Kaution erstatten (Standard) – Einbehalt erfolgt manuell über das Feld."""
        for rec in self:
            if rec.deposit_state != 'received':
                raise UserError(_('Es ist keine erhaltene Kaution vorhanden, die erstattet werden kann.'))
            rec.deposit_state = 'refunded'
            rec.deposit_paid = False
            rec.deposit_refund_date = fields.Date.context_today(rec)
            rec.message_post(
                body=_('Kaution (%.2f) erstattet.') % rec.deposit_total,
                subtype_xmlid='mail.mt_note')

    def action_withhold_deposit(self):
        """B-cross-3: Kaution einbehalten (z. B. bei Schaden)."""
        for rec in self:
            if rec.deposit_state != 'received':
                raise UserError(_('Es ist keine erhaltene Kaution vorhanden, die einbehalten werden kann.'))
            rec.deposit_state = 'withheld'
            rec.deposit_paid = False
            rec.deposit_refund_date = fields.Date.context_today(rec)
            rec.message_post(
                body=_('Kaution (%.2f) einbehalten.') % rec.deposit_total,
                subtype_xmlid='mail.mt_note')

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
    # R2: Live-Verfügbarkeit im Zeitraum (today/Reservierungs-abhängig => NICHT store)
    available_in_period = fields.Integer(
        string='Verfügbar im Zeitraum', compute='_compute_available_in_period', store=False)

    @api.depends('item_id', 'order_id.date_from', 'order_id.date_to')
    def _compute_available_in_period(self):
        for rec in self:
            if rec.item_id and rec.order_id.date_from and rec.order_id.date_to:
                rec.available_in_period = rec.item_id.quantity_available(
                    rec.order_id.date_from, rec.order_id.date_to, exclude_order=rec.order_id)
            else:
                rec.available_in_period = 0

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
