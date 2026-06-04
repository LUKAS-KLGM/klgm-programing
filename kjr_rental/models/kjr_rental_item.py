# -*- coding: utf-8 -*-
"""Verleihartikel mit Bestand, Lager und Tarifen."""
from odoo import api, fields, models, _


class KjrRentalItem(models.Model):
    _name = 'kjr.rental.item'
    _description = 'Verleihartikel'
    _order = 'category, name'

    name = fields.Char(string='Bezeichnung', required=True)
    code = fields.Char(string='Inventarnummer', copy=False)
    active = fields.Boolean(default=True)
    category = fields.Selection([
        ('vehicle', 'Fahrzeuge / Bus'),
        ('tent', 'Zelte'),
        ('tech', 'Technik'),
        ('sport', 'Sport'),
        ('kitchen', 'Küche'),
        ('games', 'Spielgeräte'),
        ('other', 'Sonstiges'),
    ], string='Kategorie', required=True, default='other')
    location = fields.Selection([
        ('sonthofen', 'Lager Sonthofen'),
        ('immenstadt', 'Lager Immenstadt'),
        ('oberstdorf', 'Lager Oberstdorf'),
    ], string='Lager', default='sonthofen')
    quantity_total = fields.Integer(string='Bestand gesamt', default=1)
    price_per_day = fields.Float(string='Tagespreis Standard (€)', digits=(8, 2))
    has_member_price = fields.Boolean(
        string='Eigener Mitgliedstarif', default=True,
        help='Wenn aktiv, gilt für Mitglieder der Mitgliedstarif (auch 0 € = gratis). '
             'Wenn inaktiv, gilt für alle der Standardtarif.',
    )
    price_member_per_day = fields.Float(string='Tagespreis Mitglied (€)', digits=(8, 2))
    deposit = fields.Float(string='Kaution (€)', digits=(8, 2))
    image_1920 = fields.Image(string='Bild', max_width=1920, max_height=1920)
    description = fields.Text(string='Beschreibung')
    website_published = fields.Boolean(string='Auf Website', default=True)
    icon = fields.Char(string='FontAwesome-Icon', help='z. B. fa-bus')

    def price_for(self, is_member):
        """Tagespreis je nach Mitgliedsstatus. Ein konfigurierter Mitgliedstarif gilt
        auch bei 0 € (gratis), sofern 'Eigener Mitgliedstarif' aktiv ist."""
        self.ensure_one()
        if is_member and self.has_member_price:
            return self.price_member_per_day
        return self.price_per_day

    def quantity_available(self, date_from, date_to, exclude_order=None):
        """Im Zeitraum verfügbare Menge (Bestand minus überlappende Reservierungen/Ausgaben)."""
        self.ensure_one()
        if not (date_from and date_to):
            return self.quantity_total
        line_domain = [
            ('item_id', '=', self.id),
            ('order_id.state', 'in', ('reserved', 'issued')),
            ('order_id.date_from', '<=', date_to),
            ('order_id.date_to', '>=', date_from),
        ]
        if exclude_order:
            line_domain.append(('order_id', '!=', exclude_order.id))
        # sudo(): Artikel sind eine firmenübergreifend GETEILTE Ressource (kein company_id).
        # Die Verfügbarkeit muss daher alle überlappenden Reservierungen ALLER Gesellschaften
        # zählen – sonst umgeht die Company-Record-Rule die Belegung (Doppelbuchung).
        lines = self.env['kjr.rental.order.line'].sudo().search(line_domain)
        reserved = sum(lines.mapped('quantity'))
        return self.quantity_total - reserved
