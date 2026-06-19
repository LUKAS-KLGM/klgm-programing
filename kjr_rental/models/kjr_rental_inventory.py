# -*- coding: utf-8 -*-
"""Schlanke Inventur für Verleihartikel (kein Enterprise stock/inventory)."""
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class KjrRentalInventory(models.Model):
    _name = 'kjr.rental.inventory'
    _description = 'KJR Verleih Inventur'
    _order = 'year desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string='Bezeichnung', required=True, copy=False,
        default=lambda self: _('Inventur'), tracking=True,
    )
    year = fields.Integer(
        string='Jahr', required=True, tracking=True,
        default=lambda self: fields.Date.context_today(self).year,
    )
    company_id = fields.Many2one(
        'res.company', string='Gesellschaft', required=True,
        default=lambda self: self.env.company,
    )
    state = fields.Selection([
        ('draft', 'Erfassung'),
        ('done', 'Abgeschlossen'),
    ], string='Status', default='draft', required=True, tracking=True, index=True)
    date_done = fields.Date(string='Abgeschlossen am', readonly=True)
    line_ids = fields.One2many('kjr.rental.inventory.line', 'inventory_id', string='Positionen')
    note = fields.Text(string='Anmerkungen')

    def action_open(self):
        """'Inventur eröffnen': kopiert aktive Artikel als Zähl-Positionen."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Nur Inventuren in Erfassung können (neu) eröffnet werden.'))
            rec.line_ids.unlink()
            items = self.env['kjr.rental.item'].search([('active', '=', True)])
            rec.line_ids = [(0, 0, {
                'item_id': item.id,
                'qty_expected': item.quantity_total,
                'qty_counted': item.quantity_total,
            }) for item in items]
            rec.message_post(
                body=_('Inventur eröffnet: %d Artikel erfasst.') % len(items),
                subtype_xmlid='mail.mt_note')

    def action_done(self):
        """'abschließen': schreibt Ausschuss (scrap) auf Artikel zurück.

        Bei scrap=True wird die gezählte Differenz (qty_expected - qty_counted, min. 1)
        vom Gesamtbestand abgezogen; sinkt der Bestand auf 0, wird der Artikel
        deaktiviert (active=False).
        """
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Diese Inventur ist bereits abgeschlossen.'))
            for line in rec.line_ids:
                if not line.scrap or not line.item_id:
                    continue
                diff = line.qty_expected - line.qty_counted
                scrap_qty = diff if diff > 0 else 1
                new_total = max(line.item_id.quantity_total - scrap_qty, 0)
                vals = {'quantity_total': new_total}
                if new_total <= 0:
                    vals['active'] = False
                line.item_id.write(vals)
            rec.state = 'done'
            rec.date_done = fields.Date.context_today(rec)
            rec.message_post(body=_('Inventur abgeschlossen.'), subtype_xmlid='mail.mt_note')

    def action_reset_draft(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError(_(
                    'Eine abgeschlossene Inventur kann nicht erneut geöffnet werden, da der '
                    'Ausschuss bereits auf den Bestand verbucht wurde (eine erneute Buchung '
                    'würde den Bestand doppelt reduzieren). Bitte eine neue Inventur anlegen.'))
            rec.state = 'draft'


class KjrRentalInventoryLine(models.Model):
    _name = 'kjr.rental.inventory.line'
    _description = 'KJR Inventurposition'
    _order = 'inventory_id, id'

    inventory_id = fields.Many2one(
        'kjr.rental.inventory', string='Inventur', required=True,
        ondelete='cascade', index=True)
    item_id = fields.Many2one('kjr.rental.item', string='Artikel', required=True)
    qty_expected = fields.Integer(string='Soll-Bestand')
    qty_counted = fields.Integer(string='Gezählt')
    qty_diff = fields.Integer(string='Differenz', compute='_compute_qty_diff', store=True)
    condition = fields.Selection([
        ('good', 'Gut'),
        ('used', 'Gebraucht'),
        ('damaged', 'Beschädigt'),
        ('lost', 'Verloren'),
    ], string='Zustand', default='good')
    scrap = fields.Boolean(string='Ausschuss / abschreiben')
    note = fields.Char(string='Notiz')

    @api.depends('qty_expected', 'qty_counted')
    def _compute_qty_diff(self):
        for rec in self:
            rec.qty_diff = (rec.qty_counted or 0) - (rec.qty_expected or 0)
