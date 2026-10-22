# -*- coding: utf-8 -*-
"""Höchstbetrag pro Jahr und Verband und Kommas in Förderart-Texten (19.0.18.0.1).

Die Förderarten liegen unter noupdate="1". Das neue Feld max_amount_per_year
bliebe auf Bestandsinstanzen 0 (keine Jahresgrenze). Gesetzt werden nur die
Werte, die die Zuschussrichtlinie (Fassung ab 01.12.2022) wörtlich als
Jahresgrenze nennt:
  § 4.5  „jedoch max. 700 € pro Jahr“
  § 4.6  „Die jährliche Höchstfördersumme beträgt 300 €.“
  § 4.8a „jedoch max. 400 € jährlich“
Ein im Backend schon gepflegter Wert (≠ 0) bleibt stehen.

Außerdem zwei fehlende Kommas in den ausgelieferten Beschreibungen (§ 4.2,
§ 4.6). Ersetzt wird nur das genau so ausgelieferte Teilstück; ein im Backend
umformulierter Text bleibt unverändert. Idempotent. Protokoll nur mit IDs.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

MODULE = 'kjr_grant'
VERSION = '19.0.18.0.1'

YEAR_CAPS = {
    'kjr_grant.grant_type_4_5': 700.0,
    'kjr_grant.grant_type_4_6': 300.0,
    'kjr_grant.grant_type_4_8a': 400.0,
}

DESCRIPTION_REPLACEMENTS = {
    'kjr_grant.grant_type_4_2': (
        ('Maßnahmen die dem Verbandszweck dienen', 'Maßnahmen, die dem Verbandszweck dienen'),
    ),
    'kjr_grant.grant_type_4_6': (
        ('Nur für Gegenstände die ausschließlich', 'Nur für Gegenstände, die ausschließlich'),
    ),
}


def ersetze(text, replacements):
    """Reine Textfunktion. Rückgabe: (neuer Text, Anzahl ersetzter Teilstücke)."""
    if not text:
        return text, 0
    count = 0
    for old, new in replacements:
        if old in text:
            count += text.count(old)
            text = text.replace(old, new)
    return text, count


def _year_caps(env):
    for xmlid, amount in YEAR_CAPS.items():
        grant_type = env.ref(xmlid, raise_if_not_found=False)
        if not grant_type:
            _logger.info('Migration %s %s: %s nicht gefunden - übersprungen.', MODULE, VERSION, xmlid)
            continue
        if grant_type.max_amount_per_year:
            _logger.info('Migration %s %s: Förderart id %s hat bereits einen Jahreshöchstbetrag '
                         '- unverändert.', MODULE, VERSION, grant_type.id)
            continue
        grant_type.max_amount_per_year = amount
        _logger.info('Migration %s %s: Förderart id %s Jahreshöchstbetrag %.2f gesetzt.',
                     MODULE, VERSION, grant_type.id, amount)


def _descriptions(env):
    for xmlid, replacements in DESCRIPTION_REPLACEMENTS.items():
        grant_type = env.ref(xmlid, raise_if_not_found=False)
        if not grant_type:
            _logger.info('Migration %s %s: %s nicht gefunden - übersprungen.', MODULE, VERSION, xmlid)
            continue
        new_text, count = ersetze(grant_type.description, replacements)
        if count:
            grant_type.description = new_text
        _logger.info('Migration %s %s: Förderart id %s, %s Stelle(n) angepasst.',
                     MODULE, VERSION, grant_type.id, count)


def migrate(cr, version):
    if not version:
        return  # Neuinstallation: die XML liefert bereits den neuen Stand.
    env = api.Environment(cr, SUPERUSER_ID, {})
    _year_caps(env)
    _descriptions(env)
