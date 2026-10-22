# -*- coding: utf-8 -*-
"""Einstellungen KJR Veranstaltungen (Systemparameter kjr_event.*), 19.0.5.11.0."""
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Termin 13.10.2026: Standardliste der zugelassenen Postleitzahlen
    # (Landkreis Oberallgäu inkl. Kempten). Bewusst NICHT vorbelegt: die Liste
    # pflegt der KJR (siehe Bericht). Gilt nur für Veranstaltungen mit dem
    # Haken "Nur zugelassene Postleitzahlen".
    kjr_event_allowed_zips = fields.Char(
        string='Zugelassene Postleitzahlen (Standard)',
        config_parameter='kjr_event.allowed_zips',
        help='Standardliste für Veranstaltungen mit "Nur zugelassene Postleitzahlen", '
             'getrennt durch Komma oder Leerzeichen, z. B. der Landkreis. Je '
             'Veranstaltung lassen sich weitere Postleitzahlen ergänzen.')
    # Termin 13.10.2026 / Theresa 14.10.: Pflicht-Haken für die
    # Teilnahmebedingungen mit Link. Den Inhalt liefert der KJR (Aufgabe 112).
    kjr_event_terms_url = fields.Char(
        string='Link zu den Teilnahmebedingungen',
        config_parameter='kjr_event.terms_url',
        help='Seite der Website mit den Teilnahmebedingungen, z. B. '
             '/teilnahmebedingungen. Leer = der Haken erscheint ohne Link.')
    kjr_event_privacy_url = fields.Char(
        string='Link zu den Datenschutzhinweisen',
        config_parameter='kjr_event.privacy_url',
        help='Leer = /datenschutzerklaerung.')
    # Termin 13.10.2026: 0 % Umsatzsteuer auf Teilnahmegebühren. Die Wahl der
    # Steuer ist eine Entscheidung der Buchhaltung/Steuerberatung.
    kjr_event_fee_tax_id = fields.Many2one(
        'account.tax', string='Steuer auf Teilnahmegebühren',
        config_parameter='kjr_event.fee_tax_id',
        domain=[('type_tax_use', '=', 'sale')],
        help='Steuer für Anmeldungen zu KJR-Veranstaltungen (Ticket im Shop und '
             'Schulungsrechnung). Leer = Steuer des Produkts (beim Ticketprodukt '
             'meist 19 %), deshalb bitte setzen. Die Wahl trifft die Steuerberatung.')
