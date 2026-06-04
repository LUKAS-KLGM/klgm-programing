# -*- coding: utf-8 -*-
"""Tarife je Nutzergruppe inkl. konfigurierbarer Umsatzsteuer."""
from odoo import fields, models


class KjrFacilityTariff(models.Model):
    _name = 'kjr.facility.tariff'
    _description = 'KJR Einrichtungstarif'
    _order = 'sequence, name'

    name = fields.Char(string='Bezeichnung', required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    facility_id = fields.Many2one(
        'kjr.facility', string='Einrichtung',
        help='Leer = gilt für alle Einrichtungen.',
    )
    tariff_type = fields.Selection([
        ('kjr_member', 'KJR-Mitgliedsverband'),
        ('partner', 'Partnerorganisation'),
        ('standard', 'Standard (gemeinnützig)'),
        ('commercial', 'Kommerziell'),
    ], string='Tarifgruppe', required=True, default='standard')
    price_per_person_night = fields.Float(string='Preis pro Person/Nacht (€)', digits=(8, 2))
    price_flat_per_night = fields.Float(
        string='Pauschale pro Nacht (€)', digits=(8, 2),
        help='Optionale fixe Pauschale je Nacht zusätzlich zum Personenpreis.',
    )
    meal_breakfast = fields.Float(string='Frühstück p. P./Tag (€)', digits=(8, 2))
    meal_half = fields.Float(string='Halbpension p. P./Tag (€)', digits=(8, 2))
    meal_full = fields.Float(string='Vollpension p. P./Tag (€)', digits=(8, 2))
    tax_id = fields.Many2one(
        'account.tax', string='Umsatzsteuer',
        domain="[('type_tax_use', '=', 'sale')]",
        help='STEUERLICH FINAL ZU PRÜFEN: Bei Jugendgruppen kommt regelmäßig die '
             'USt-Befreiung nach § 4 Nr. 23 UStG bzw. der ermäßigte Satz (7 %, '
             'Zweckbetrieb § 68 Nr. 8 AO) in Betracht; bei kommerzieller Nutzung 19 %. '
             'Der passende Steuersatz ist hier je Tarifgruppe zu hinterlegen.',
    )
