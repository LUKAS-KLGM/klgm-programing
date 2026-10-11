# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """require_signature ist gespeichert: bestehende offene Shop-Bestellungen mit
    Kursanmeldungen neu berechnen, damit sie im Portal unterschrieben werden koennen."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    orders = env['sale.order'].search([
        ('state', 'in', ('draft', 'sent')), ('website_id', '!=', False),
        ('order_line.event_id', '!=', False),
    ])
    orders._compute_require_signature()
